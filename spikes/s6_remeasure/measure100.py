"""DCR-002 안 (d) 재측정 — 팬 전환 + 대역 한정 분류 + HUD 축소로 방문 100회 실측.

관리자 권한 인프로세스로 실행한다(run_measure.ps1) — 원격 프로토콜 오버헤드
없이 실제 방문당 소요를 잰다. 산출: work/measure_results.json (방문별 소요·
신규 커버 타일 수·추적 점수), work/measure.log.

이동 전략(S-5 확정 사실 반영):
- 행 시작마다 좌표 점프(재앵커) → 행 내 좌팬 반복. 팬 1회차는 점프 팝업
  영역을 피한 짧은 드래그, 이후는 화면 전폭 드래그.
- 팬 이동장은 화면 y에 선형(전단) — 전폭 밴드 3개(상/중/하)로 팬마다
  (dx = a + b·y)를 적합해 셀 위치를 갱신한다. 세로 성분은 0(실측).
- 분류는 y 대역(BAND_Y)의 신규 진입 셀로 한정(전역 커버 집합으로 중복 제거).
"""

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "s5_drag_pan"))

import cv2
import numpy as np
from PIL import Image

from driver import make_view_check  # S-5 디테일 뷰 시그니처 검증 재사용
from mapscan.nav import Navigator
from mapscan.nav import ui
from mapscan.vision import TileClassifier
from mapscan.vision.grid import _cell_intersects_rect
from mapscan.win import PostMessageInput, WgcCapture, WindowSession

WORK = Path(__file__).parent / "work"

ROWS = 9
PANS_PER_ROW = 10
ROW0 = (1020, 620)
ROW_STEP = (2, 4)        # 분류 대역 높이(280px)의 화면 수직 이동에 해당하는 맵 증분
PAN_SHORT = ((2180, 260), (1660, 260))   # 행 첫 팬: 점프 팝업 영역 밖
PAN_WIDE = ((2230, 260), (330, 260))     # 이후: 화면 전폭(팝업 소멸 확인 후)
SETTLE = 0.6             # 릴리스 +0.5s부터 잔여 이동 0 (S-5 G2)

BAND_Y = (180, 460)      # 분류 대역(클라이언트 y) — 국소 기저 오차 통제(S-5 발견 3)
# 전단 적합용 전폭 추적 밴드 (클라이언트 y0, 높이). x는 5..2250 (우측 패널 제외)
TRACK_BANDS = [(180, 70), (300, 70), (395, 60)]
TRACK_X = (5, 2250)
GAIN0, GAIN_SLOPE = 0.853, (1.0 - 0.853) / (466 - 127)   # gain(y), S-5 실측

# HUD 사각형 실제 불투명 영역 축소(최적화 3, 여유 ~15px 유지, f_00015·g3_click 실측)
HUD_REFINED = [
    (0, 0, 2544, 72),        # 상단 자원·계정 바 (기존 95)
    (0, 55, 640, 165),       # 좌상 아이콘 그리드 (기존 660x175와 유사)
    (2255, 40, 2544, 380),   # 우측 부대 패널 — 목록 실측 ~330 + 여유 (기존 520)
    (0, 460, 165, 657),      # 좌하 버튼 열 (기존 310 폭)
    (950, 540, 1560, 657),   # 하단 임무·장수·모집 버튼 밴드 (기존 y495)
    (1070, 565, 1460, 622),  # 채팅 라인(반투명, 길이 가변 — 여유 포함)
    (2395, 585, 2544, 657),  # 우하 도위 버튼 (기존 y545)
]
# 점프 팝업(행 시작 프레임 전용) — 대상 타일 중심 상대, S-5 실측 + 여유
POPUP_REL = (-290, -215, 370, 150)


def log_print(f, msg):
    print(msg)
    f.write(msg + "\n")
    f.flush()


def gain(y: float) -> float:
    return GAIN0 + GAIN_SLOPE * (y - 127)


def track_shift(prev, cur, offset, expect_by_band, search=140):
    """전폭 밴드 3개의 x 이동을 재고 dx(y) = a + b·y 로 적합한다.

    템플릿은 이동 후에도 프레임 안에 남는 x 구간만 잘라 쓴다
    (예상 이동이 -1750이면 x 1760~2245 → 이동 후 10~495).
    """
    ox, oy = offset
    pts, raw = [], []
    for (y0, h), exp in zip(TRACK_BANDS, expect_by_band):
        sy0 = max(0, y0 + oy - 12)
        sy1 = min(cur.shape[0], y0 + h + oy + 12)
        if exp < -800:
            # 광폭 좌팬: cur 좌측의 신규 진입 구간을 prev 우측에서 역탐색한다
            # (순방향은 이동 후 남는 템플릿 폭이 부족)
            cx0, w_tpl = 10, 450
            tpl = cur[y0 + oy:y0 + h + oy, cx0 + ox:cx0 + w_tpl + ox]
            ex = cx0 + ox - int(exp)      # prev에서의 기대 위치
            sx0 = max(0, ex - search)
            sx1 = min(prev.shape[1], ex + w_tpl + search)
            res = cv2.matchTemplate(prev[sy0:sy1, sx0:sx1], tpl,
                                    cv2.TM_CCOEFF_NORMED)
            _, score, _, (px, py) = cv2.minMaxLoc(res)
            dx = (cx0 + ox) - (sx0 + px)
            dy = (y0 + oy) - (sy0 + py)
        else:
            x0, x1 = TRACK_X
            if exp < 0:
                x0 = max(x0, int(-exp) + search + 10)
            else:
                x1 = min(x1, 2544 - int(exp) - search - 10)
            if x1 - x0 < 200:
                raise RuntimeError(f"추적 템플릿 구간 부족: exp={exp}")
            tpl = prev[y0 + oy:y0 + h + oy, x0 + ox:x1 + ox]
            ex = x0 + ox + int(exp)
            sx0 = max(0, ex - search)
            sx1 = min(cur.shape[1], ex + (x1 - x0) + search)
            res = cv2.matchTemplate(cur[sy0:sy1, sx0:sx1], tpl,
                                    cv2.TM_CCOEFF_NORMED)
            _, score, _, (px, py) = cv2.minMaxLoc(res)
            dx = sx0 + px - (x0 + ox)
            dy = sy0 + py - (y0 + oy)
        yc = y0 + h / 2
        pts.append((yc, float(dx)))
        raw.append((round(float(dx), 1), int(dy), round(float(score), 3)))
    ys = np.array([p[0] for p in pts])
    xs = np.array([p[1] for p in pts])
    b, a = np.polyfit(ys, xs, 1)
    return float(a), float(b), raw


def enumerate_band(grid, offset, shift_a, shift_b, frame_size, exclude):
    """행 앵커 기준 + 누적 전단 이동을 적용한 대역 내 완전 가시 셀."""
    w, h = frame_size
    hx, hy = grid.basis.half_extents
    ox, oy = offset
    # 누적 이동 후의 화면 중앙에 대응하는 맵 좌표를 중심으로 열거한다
    ccx, ccy = grid.to_map(w / 2 - shift_a - shift_b * (h / 2), h / 2)
    cells = []
    for dmx in range(-25, 26):
        for dmy in range(-25, 26):
            mx = round(ccx) + dmx
            my = round(ccy) + dmy
            if not (0 <= mx <= 1619 and 0 <= my <= 1619):
                continue
            x0, y0 = grid.to_screen(mx, my)
            px = x0 + shift_a + shift_b * y0
            py = y0
            cy = py - oy
            if not (BAND_Y[0] <= cy <= BAND_Y[1]):
                continue
            if not (hx <= px <= w - hx and hy <= py <= h - hy):
                continue
            if any(_cell_intersects_rect((px - ox, py - oy), grid.basis, r)
                   for r in exclude):
                continue
            cells.append((mx, my, px, py))
    return cells


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    logf = open(WORK / "measure.log", "w", encoding="utf-8")

    session = WindowSession.attach(args.hwnd)
    info = session.info()
    log_print(logf, f"대상 hwnd={info.hwnd:#x} client={info.client} "
                    f"elevated={info.elevated}")
    if tuple(info.client) != ui.CLIENT_SIZE:
        log_print(logf, f"오류: 스캔 창 크기가 아님 {info.client}")
        return 2

    capture = WgcCapture(args.hwnd, info.title)
    visits = []
    covered: set = set()
    t_run0 = time.monotonic()
    with capture:
        inp = PostMessageInput(args.hwnd, delay_range=(0.15, 0.3))
        nav = Navigator(capture, inp)
        clf = None
        view_check = None

        for row in range(ROWS):
            row_start = (ROW0[0] + ROW_STEP[0] * row, ROW0[1] + ROW_STEP[1] * row)
            t0 = time.monotonic()
            grid = nav.jump(*row_start)
            frame = capture.grab_fresh()
            t_jump = time.monotonic() - t0
            offset = nav.client_offset(frame)
            if view_check is None:
                view_check = make_view_check(nav, frame)
                clf = TileClassifier(grid.basis)
                Image.fromarray(frame).save(WORK / "row0_start.png")
            else:
                view_check(frame)

            anchor_c = (grid.anchor_px[0] - offset[0], grid.anchor_px[1] - offset[1])
            popup_abs = (anchor_c[0] + POPUP_REL[0], anchor_c[1] + POPUP_REL[1],
                         anchor_c[0] + POPUP_REL[2], anchor_c[1] + POPUP_REL[3])
            t0 = time.monotonic()
            cells = enumerate_band(grid, offset, 0.0, 0.0, frame.shape[1::-1],
                                   HUD_REFINED + [popup_abs])
            new = [c for c in cells if (c[0], c[1]) not in covered]
            for mx, my, px, py in new:
                clf.classify(frame, px, py)
                covered.add((mx, my))
            t_cls = time.monotonic() - t0
            visits.append({"row": row, "kind": "jump", "t_move": round(t_jump, 2),
                           "t_classify": round(t_cls, 2), "new": len(new)})
            log_print(logf, f"[row {row}] 점프 {row_start} {t_jump:.1f}s, "
                            f"신규 {len(new)}타일 분류 {t_cls:.1f}s")

            A = B = 0.0
            prev = frame
            for k in range(PANS_PER_ROW):
                src, dst = PAN_SHORT if k == 0 else PAN_WIDE
                cmd = dst[0] - src[0]
                view_check(prev)
                t0 = time.monotonic()
                inp.drag(*src, *dst, steps=12 if k == 0 else 24)
                time.sleep(SETTLE)
                frame = capture.grab_fresh()
                t_move = time.monotonic() - t0
                t0 = time.monotonic()
                expect = [cmd * gain(y0 + h / 2) for y0, h in TRACK_BANDS]
                search = 260 if k <= 1 else 140
                a, b, raw = track_shift(prev, frame, offset, expect, search)
                scores = [r[2] for r in raw]
                if min(scores) < 0.30:
                    a, b, raw = track_shift(prev, frame, offset, expect, 400)
                    scores = [r[2] for r in raw]
                A += a
                B += b
                t_track = time.monotonic() - t0
                t0 = time.monotonic()
                cells = enumerate_band(grid, offset, A, B, frame.shape[1::-1],
                                       HUD_REFINED)
                new = [c for c in cells if (c[0], c[1]) not in covered]
                for mx, my, px, py in new:
                    clf.classify(frame, px, py)
                    covered.add((mx, my))
                t_cls = time.monotonic() - t0
                visits.append({"row": row, "kind": "pan", "cmd": cmd,
                               "t_move": round(t_move, 2),
                               "t_track": round(t_track, 2),
                               "t_classify": round(t_cls, 2),
                               "new": len(new), "shift": raw})
                log_print(logf, f"  팬#{k + 1:2d} cmd {cmd} 이동 {raw} "
                                f"이동{t_move:.2f}s 추적{t_track:.2f}s "
                                f"분류{t_cls:.2f}s 신규 {len(new)}")
                prev = frame

    total_s = time.monotonic() - t_run0
    n = len(visits)
    new_total = sum(v["new"] for v in visits)
    per_visit = [v["t_move"] + v.get("t_track", 0) + v["t_classify"]
                 for v in visits]
    pan_visits = [v for v in visits if v["kind"] == "pan"]
    result = {
        "visits": n, "elapsed_s": round(total_s, 1),
        "new_tiles_total": new_total,
        "mean_visit_s": round(statistics.mean(per_visit), 2),
        "mean_new_per_visit": round(new_total / n, 1),
        "pan_mean_s": round(statistics.mean(
            v["t_move"] + v["t_track"] + v["t_classify"] for v in pan_visits), 2)
        if pan_visits else None,
        "pan_mean_new": round(statistics.mean(v["new"] for v in pan_visits), 1)
        if pan_visits else None,
        "detail": visits,
    }
    (WORK / "measure_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log_print(logf, f"\n방문 {n}회, 총 {total_s:.0f}s, 신규 {new_total}타일 "
                    f"(방문당 평균 {new_total / n:.1f}) — "
                    f"방문당 평균 {statistics.mean(per_visit):.2f}s")
    map_tiles = 1620 * 1620
    eff = new_total / total_s
    log_print(logf, f"러프 외삽: {map_tiles:,}타일 ÷ {eff:.1f}타일/s ≈ "
                    f"{map_tiles / eff / 3600:.1f}시간")
    logf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
