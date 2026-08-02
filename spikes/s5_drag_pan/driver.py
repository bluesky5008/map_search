"""S-5 드래그 팬 실현 가능성 — DCR-002 안 (d)의 착수 게이트.

상주 관리자 에이전트(spikes/s3_nav_ui/agent.py, UAC 1회)를 파일 프로토콜로 원격
조종한다. 이 드라이버는 비상승 권한으로 실행하며, RemoteCapture/RemoteInput
어댑터로 제품 Navigator를 그대로 재사용한다(지도 모드 검증 클릭 포함).

게이트 판정 항목 (DCR-002 승인 기록):
  G1. 드래그로 지도가 팬되는가 (+ 점프 팝업이 팬 중 어떻게 되는가)
  G2. 1회 드래그당 이동량이 재현 가능한가 (분산, 감속·관성 유무)
  G3. 연속 팬 누적 드리프트를 주기적 재앵커링(좌표 점프)으로 흡수할 수 있는가

측정 방법: 팬 전후 프레임의 상단 스트립(클라이언트 y 100~164 — 선택 팝업
사각형과 절대 겹치지 않는다)을 템플릿 매칭해 화면 내용의 이동량을 구한다.
G3 절대 검증은 예측 타일 클릭 → 팝업 좌표 문자열 판독(DigitReader).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.nav import Navigator
from mapscan.vision import DigitReader
from mapscan.vision.grid import GridMapper, find_selection_highlight

WORK = Path(__file__).parent / "work"
JUMP_AT = (1020, 620)          # 기존 실기 검증과 같은 지점(지형 확인 완료 영역)

# 점프 팝업 실측 (2026-08-02 f_00015, 앵커 타일 클라이언트 (1225,337) 기준):
# 패널·버튼 전체가 클라이언트 (950,135)-(1580,412)에 놓인다. ui.POPUP_RECT_REL
# (-600..+160)과 달리 **오른쪽 +352px까지 점령·행군 버튼**이 있다 — 드래그
# 시작·종점은 이 영역을 절대 침범하지 않는다 (릴리스가 버튼 클릭이 될 위험).
POPUP_ABS = (950, 135, 1580, 412)

H_FROM, H_TO = (2180, 260), (1660, 260)   # 좌로 팬: Δcmd=(-520, 0), 팝업 우측 밖
V_FROM, V_TO = (1800, 160), (1800, 410)   # 아래로 팬: Δcmd=(0, +250), x가 팝업 밖
G1_FROM, G1_TO = (2180, 260), (1880, 260)  # 소폭 확인용 Δcmd=(-300, 0)
TOP_STRIP = (1460, 96, 760, 62)    # 측정 패치(클라이언트 x,y,w,h) — 팝업 상단과 무교차
CLICK_AT = (1800, 300)             # G3 절대 검증 클릭 지점(팝업·HUD 밖)
SIG_RECT = (50, 55, 400, 110)      # 프레임 좌상단 계정 HUD — 디테일 뷰 시그니처


class AgentIO:
    """파일 명령 프로토콜 클라이언트. 에이전트가 res를 쓸 때까지 대기한다."""

    def __init__(self, work: Path):
        self.work = work
        existing = sorted(work.glob("cmd_*.txt"))
        self.seq = 1 + (int(existing[-1].stem[4:]) if existing else 0)

    def cmd(self, line: str, timeout: float = 30.0) -> str:
        n = self.seq
        self.seq += 1
        (self.work / f"cmd_{n:04d}.txt").write_text(line, encoding="utf-8")
        res = self.work / f"res_{n:04d}.txt"
        deadline = time.monotonic() + timeout
        while not res.exists():
            if time.monotonic() > deadline:
                raise TimeoutError(f"에이전트 응답 없음: {line!r} — run_agent.ps1 실행 확인")
            time.sleep(0.08)
        time.sleep(0.05)
        out = res.read_text(encoding="utf-8")
        if out.startswith("ERROR"):
            raise RuntimeError(f"{line!r} -> {out}")
        return out


class RemoteCapture:
    def __init__(self, io: AgentIO):
        self.io = io
        self.n = 0

    def grab_fresh(self) -> np.ndarray:
        self.n += 1
        name = f"f_{self.n:05d}.png"
        self.io.cmd(f"cap {name}")
        return np.asarray(Image.open(self.io.work / name).convert("RGB"))


class RemoteInput:
    """Navigator가 기대하는 입력 인터페이스를 에이전트 명령으로 중계한다."""

    def __init__(self, io: AgentIO):
        self.io = io

    def pause(self) -> None:
        time.sleep(0.25)

    def click(self, x: int, y: int) -> None:
        self.io.cmd(f"click {x} {y}")

    def key(self, vk: int, count: int = 1) -> None:
        self.io.cmd(f"key {vk} {count}")

    def type_text(self, text: str) -> None:
        self.io.cmd(f"type {text}")

    def drag(self, x0, y0, x1, y1, steps=12) -> None:
        self.io.cmd(f"drag {x0} {y0} {x1} {y1} {steps}")


class RemoteNavigator(Navigator):
    """원격 캡처는 프레임 간격이 넓어 대기 애니메이션 변화율이 커진다 — 완화."""

    def wait_stable(self, timeout: float = 15.0, min_still: int = 2,
                    fraction: float = 0.12) -> np.ndarray:
        return super().wait_stable(timeout, min_still, fraction)


def find_shift(before, after, offset, dcmd, rect=TOP_STRIP, search=350):
    """before의 패치가 after에서 어디로 갔는지 (dx, dy, NCC 점수)로 반환."""
    ox, oy = offset
    x, y, w, h = rect
    tpl = before[y + oy:y + oy + h, x + ox:x + ox + w]
    ex, ey = x + ox + dcmd[0], y + oy + dcmd[1]
    x0, y0 = max(0, ex - search), max(0, ey - search)
    x1 = min(after.shape[1], ex + w + search)
    y1 = min(after.shape[0], ey + h + search)
    res = cv2.matchTemplate(after[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < 0.5:  # 예측 창 밖으로 갔거나 가려짐 — 전체 프레임 재탐색
        res = cv2.matchTemplate(after, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        x0 = y0 = 0
    return x0 + loc[0] - (x + ox), y0 + loc[1] - (y + oy), round(score, 3)


def changed_fraction(a, b, rect, offset):
    ox, oy = offset
    x0, y0, x1, y1 = rect
    ca = a[y0 + oy:y1 + oy, x0 + ox:x1 + ox].astype(np.int16)
    cb = b[y0 + oy:y1 + oy, x0 + ox:x1 + ox].astype(np.int16)
    return float((np.abs(ca - cb).sum(axis=2) > 12).mean())


def sig_of(frame):
    x, y0, x1, y1 = SIG_RECT
    return frame[y0:y1, x:x1]


def make_view_check(nav, ref_frame):
    """디테일 뷰 검증기 — 점프 직후 프레임의 계정 HUD를 기준 시그니처로 삼는다.

    점프가 끝나면 게임은 지도 UI를 닫고 디테일 뷰로 돌아온다(지도 모드 마커
    부재가 정상). 드래그 전에는 '디테일 뷰가 맞는가'를 확인해야 한다 — 예상
    밖 화면에서의 드래그는 UI 오조작이 될 수 있다(T12 오클릭 사고의 교훈).
    """
    ref = sig_of(ref_frame)

    def check(frame) -> float:
        score = float(cv2.matchTemplate(sig_of(frame), ref,
                                        cv2.TM_CCOEFF_NORMED)[0, 0])
        if score < 0.65 or nav.is_map_mode(frame):
            raise RuntimeError(
                f"디테일 뷰 아님(시그니처 {score:.2f}, "
                f"지도마커 {nav.map_mode_score(frame):.2f}) — 조작 중단")
        return score

    return check


def do_drag(nav, inp, cap, view_check, src, dst, steps=12, settle=0.8):
    """디테일 뷰 확인 → 드래그 → 정착 대기 → 전후 프레임과 이동량 반환."""
    before = cap.grab_fresh()
    view_check(before)
    inp.drag(*src, *dst, steps=steps)
    time.sleep(settle)
    after = cap.grab_fresh()
    dcmd = (dst[0] - src[0], dst[1] - src[1])
    dx, dy, score = find_shift(before, after, nav.client_offset(before), dcmd)
    return before, after, (dx, dy, score)


def read_popup_coords(reader, frame, cx, cy):
    """기준점(프레임 좌표) 위쪽의 좌표 문자열을 슬라이딩 밴드로 찾는다.

    좌표 줄의 세로 위치는 팝업 구성(타일 종류·배지)에 따라 달라진다
    (s2 픽스처 rel y -140, 점프 팝업 실측 rel y -171).
    """
    for dy in range(-205, -119, 8):
        strip = frame[cy + dy:cy + dy + 34, cx - 30:cx + 195]
        got = reader.read_coords(strip)
        if got:
            return got, dy
    return None, None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(WORK))
    ap.add_argument("--phases", default="123", help="실행할 게이트 (예: 1, 12, 123)")
    args = ap.parse_args()
    work = Path(args.work)
    results: dict = {"jump_at": JUMP_AT}

    io = AgentIO(work)
    cap = RemoteCapture(io)
    inp = RemoteInput(io)
    nav = RemoteNavigator(cap, inp)
    print(f"에이전트 연결 확인 (다음 명령 #{io.seq})")

    frame = cap.grab_fresh()
    offset = nav.client_offset(frame)
    print(f"프레임 {frame.shape[1]}x{frame.shape[0]}, 클라이언트 오프셋 {offset}, "
          f"지도 모드 마커 {nav.map_mode_score(frame):.2f}")

    t0 = time.monotonic()
    grid = nav.jump(*JUMP_AT)
    print(f"점프 {JUMP_AT} 완료 ({time.monotonic() - t0:.1f}s), 앵커 {grid.anchor_px}")
    ref_frame = cap.grab_fresh()
    view_check = make_view_check(nav, ref_frame)
    Image.fromarray(ref_frame).save(work / "ref_detail_view.png")

    # ---- G1: 팬 되는가 + 팝업 거동 --------------------------------------
    if "1" in args.phases:
        print("\n[G1] 소폭 드래그 (-300, 0)")
        before, after, (dx, dy, score) = do_drag(
            nav, inp, cap, view_check, G1_FROM, G1_TO)
        popup_still = changed_fraction(before, after, POPUP_ABS, offset)
        ring = find_selection_highlight(after)
        Image.fromarray(before).save(work / "g1_before.png")
        Image.fromarray(after).save(work / "g1_after.png")
        # 게인(명령 대비 이동 비율)·부호는 미지 — 유의미한 수평 이동만 요구
        panned = score >= 0.5 and abs(dx) >= 100 and abs(dy) < 120
        results["g1"] = {"cmd": [-300, 0], "moved": [dx, dy], "score": score,
                         "popup_region_changed": round(popup_still, 3),
                         "ring_after": ring, "panned": panned}
        print(f"  이동 ({dx},{dy}) 점수 {score} | 팝업 영역 변화율 {popup_still:.3f} "
              f"| 링 {ring} | 판정 {'팬 동작' if panned else '실패'}")
        if not panned:
            for steps in (24, 4):
                print(f"  변형 시도: steps={steps}")
                _, after, (dx, dy, score) = do_drag(
                    nav, inp, cap, view_check, G1_FROM, G1_TO, steps=steps)
                if score >= 0.5 and abs(dx) >= 100 and abs(dy) < 120:
                    results["g1"]["variant_steps"] = steps
                    results["g1"]["panned"] = True
                    print(f"  steps={steps}로 팬 동작 확인 ({dx},{dy})")
                    break
        if not results["g1"]["panned"]:
            (work / "s5_results.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print("\nG1 실패 — 드래그 팬 불가. 안 (a) 전환 경로.")
            return 1

    # ---- G2: 재현성·관성 -------------------------------------------------
    if "2" in args.phases:
        print("\n[G2] 왕복 드래그 12회(수평 ±520) + 4회(수직 ±250)")
        moves = {"left": [], "right": [], "down": [], "up": []}
        plan = [("left", H_FROM, H_TO), ("right", H_TO, H_FROM)] * 6 + \
               [("down", V_FROM, V_TO), ("up", V_TO, V_FROM)] * 2
        inertia = []
        for i, (name, src, dst) in enumerate(plan):
            _, after, (dx, dy, score) = do_drag(nav, inp, cap, view_check, src, dst)
            moves[name].append((dx, dy, score))
            print(f"  #{i + 1:2d} {name:5s} 이동 ({dx:5d},{dy:4d}) 점수 {score}")
            if i < 2:  # 관성: 릴리스 직후 잔여 이동 프로파일
                tail = []
                prev = after
                for wait_s in (0.5, 0.8):
                    time.sleep(wait_s)
                    cur = cap.grab_fresh()
                    tdx, tdy, ts = find_shift(prev, cur, offset, (0, 0), search=200)
                    tail.append((wait_s, tdx, tdy, ts))
                    prev = cur
                inertia.append(tail)
                print(f"      관성 프로파일: {tail}")
        stats = {}
        for name, vals in moves.items():
            xs, ys = [v[0] for v in vals], [v[1] for v in vals]
            stats[name] = {
                "n": len(vals), "mean": [statistics.mean(xs), statistics.mean(ys)],
                "stdev": [statistics.stdev(xs) if len(xs) > 1 else 0.0,
                          statistics.stdev(ys) if len(ys) > 1 else 0.0],
                "raw": vals}
            print(f"  {name:5s} 평균 ({stats[name]['mean'][0]:7.1f},"
                  f"{stats[name]['mean'][1]:6.1f}) 표준편차 "
                  f"({stats[name]['stdev'][0]:.1f},{stats[name]['stdev'][1]:.1f})")
        results["g2"] = {"stats": stats, "inertia": inertia}

    # ---- G3: 누적 드리프트 + 재앵커링 ------------------------------------
    if "3" in args.phases:
        print("\n[G3] 재앵커 점프 → 좌로 10연속 팬 → 예측 클릭 검증 → 재점프")
        grid = nav.jump(*JUMP_AT)
        view_check(cap.grab_fresh())
        total = [0.0, 0.0]
        shifts = []
        for i in range(10):
            _, _, (dx, dy, score) = do_drag(nav, inp, cap, view_check, H_FROM, H_TO)
            total[0] += dx
            total[1] += dy
            shifts.append((dx, dy, score))
            print(f"  팬 #{i + 1:2d} ({dx},{dy}) 점수 {score} 누적 "
                  f"({total[0]:.0f},{total[1]:.0f})")
        moved = GridMapper(grid.basis,
                           (grid.anchor_px[0] + total[0], grid.anchor_px[1] + total[1]),
                           grid.anchor_map)
        click_f = (CLICK_AT[0] + offset[0], CLICK_AT[1] + offset[1])
        t_pred = moved.nearest_tile(*click_f)
        tx, ty = moved.to_screen(*t_pred)
        click_c = (round(tx) - offset[0], round(ty) - offset[1])
        print(f"  예측: 클라이언트 {click_c} = 타일 {t_pred} → 클릭")
        pre = cap.grab_fresh()
        view_check(pre)
        inp.click(*click_c)
        time.sleep(1.2)
        ver = cap.grab_fresh()
        Image.fromarray(ver).save(work / "g3_click.png")
        ring = find_selection_highlight(ver)
        base_f = ((round(ring[0]), round(ring[1])) if ring
                  else (round(tx), round(ty)))
        Image.fromarray(ver[base_f[1] - 210:base_f[1] - 110,
                            base_f[0] - 35:base_f[0] + 200]
                        ).save(work / "g3_strip.png")
        t_read, strip_dy = read_popup_coords(DigitReader(), ver, *base_f)
        ring_err = (None if ring is None
                    else [round(ring[0] - tx, 1), round(ring[1] - ty, 1)])
        drift = (None if t_read is None
                 else [t_read[0] - t_pred[0], t_read[1] - t_pred[1]])
        print(f"  팝업 판독 {t_read} (밴드 dy={strip_dy}) vs 예측 {t_pred} → "
              f"드리프트(타일) {drift} | 링 오차(px) {ring_err}")
        t0 = time.monotonic()
        nav.jump(*(t_read or t_pred))
        rejump_s = time.monotonic() - t0
        _, _, (dx, dy, score) = do_drag(nav, inp, cap, view_check, G1_FROM, G1_TO)
        print(f"  재점프 {rejump_s:.1f}s 후 팬 재확인 ({dx},{dy}) 점수 {score}")
        results["g3"] = {
            "per_pan": shifts, "total_moved": total, "tile_pred": t_pred,
            "tile_read": t_read, "strip_dy": strip_dy,
            "drift_tiles": drift, "ring_err_px": ring_err,
            "rejump_s": round(rejump_s, 1), "post_rejump_pan": [dx, dy, score]}

    (work / "s5_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {work / 's5_results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
