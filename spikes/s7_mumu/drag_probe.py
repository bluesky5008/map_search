"""게이트 4 / 3단계 — 드래그 팬 반응·재현성 (S-5 축약판).

입력은 MuMuNxDevice(클릭 검증 완료 대상), 캡처는 top(WGC). 드래그 경로는
우측 상단 대역(y=260) — 현재 열린 팝업(좌중앙)·부대 패널(x≥2290)·군사 스킬
칩 영역 밖. 첫 팬에서 팝업 소멸(S-5 사실 16)도 함께 확인한다.

판정(S-5 게이트 축약): ① 팬 동작 ② 왕복 이동량 재현성(σ) ③ 관성 없음.
"""

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.win.input import PostMessageInput

from cap_probe import find_mumu_instances, try_wgc
from click_probe import game_origin, verify_detail_view

WORK = Path(__file__).parent / "work"
TOP_STRIP = (1460, 96, 760, 62)      # 측정 패치(게임 좌표) — S-5와 동일
POPUP_REGION = (235, 150, 940, 470)  # 현재 팝업(공터 (346,313)) 실측 영역
H_FROM, H_TO = (2180, 260), (1660, 260)   # 좌팬 Δcmd=(-520,0)
V_FROM, V_TO = (1800, 160), (1800, 410)   # 하팬 Δcmd=(0,+250)
G1_FROM, G1_TO = (2180, 260), (1880, 260)  # 소폭 Δcmd=(-300,0)


def find_shift(before, after, dcmd, rect=TOP_STRIP, search=350):
    x, y, w, h = rect
    tpl = before[y:y + h, x:x + w]
    ex, ey = x + dcmd[0], y + dcmd[1]
    x0, y0 = max(0, ex - search), max(0, ey - search)
    x1 = min(after.shape[1], ex + w + search)
    y1 = min(after.shape[0], ey + h + search)
    res = cv2.matchTemplate(after[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < 0.5:
        res = cv2.matchTemplate(after, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        x0 = y0 = 0
    return x0 + loc[0] - x, y0 + loc[1] - y, round(float(score), 3)


def changed_fraction(a, b, region):
    x0, y0, x1, y1 = region
    ca = a[y0:y1, x0:x1].astype(np.int16)
    cb = b[y0:y1, x0:x1].astype(np.int16)
    return float((np.abs(ca - cb).sum(axis=2) > 12).mean())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = sys.argv[1] if len(sys.argv) > 1 else "용스"
    inst = next((i for i in find_mumu_instances() if i["title"] == want), None)
    if inst is None:
        print(f"인스턴스 '{want}' 미발견")
        return 1
    inp = PostMessageInput(inst["device"])
    results = {"instance": want, "input_hwnd": hex(inst["device"])}

    def grab():
        frame, err = try_wgc(inst["top"])
        if frame is None:
            raise RuntimeError(f"캡처 실패: {err}")
        ox, oy = game_origin(frame)
        return frame[oy:oy + 657, ox:ox + 2544]

    def do_drag(src, dst, settle=0.8):
        before = grab()
        verify_detail_view(before)          # 예상 밖 화면이면 예외로 중단
        inp.drag(*src, *dst, steps=12)
        time.sleep(settle)
        after = grab()
        dcmd = (dst[0] - src[0], dst[1] - src[1])
        return before, after, find_shift(before, after, dcmd)

    # G1: 소폭 팬 + 팝업 소멸
    print("[G1] 소폭 드래그 (-300,0)")
    before, after, (dx, dy, score) = do_drag(G1_FROM, G1_TO)
    popup_gone = changed_fraction(before, after, POPUP_REGION)
    Image.fromarray(before).save(WORK / "drag_g1_before.png")
    Image.fromarray(after).save(WORK / "drag_g1_after.png")
    panned = score >= 0.5 and abs(dx) >= 100 and abs(dy) < 120
    results["g1"] = {"cmd": [-300, 0], "moved": [dx, dy], "score": score,
                     "popup_region_changed": round(popup_gone, 3), "panned": panned}
    print(f"  이동 ({dx},{dy}) 점수 {score} | 팝업 영역 변화율 {popup_gone:.3f} "
          f"| 판정 {'팬 동작' if panned else '실패'}")
    if not panned:
        (WORK / "drag_probe.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    # G2 축약: 수평 왕복 6회 + 수직 왕복 2회, 첫 2회 관성 측정
    print("[G2] 왕복 드래그 수평 6회(±520) + 수직 2회(±250)")
    moves = {"left": [], "right": [], "down": [], "up": []}
    plan = [("left", H_FROM, H_TO), ("right", H_TO, H_FROM)] * 3 + \
           [("down", V_FROM, V_TO), ("up", V_TO, V_FROM)]
    inertia = []
    for i, (name, src, dst) in enumerate(plan):
        _, after, (dx, dy, score) = do_drag(src, dst)
        moves[name].append((dx, dy, score))
        print(f"  #{i + 1} {name:5s} 이동 ({dx:5d},{dy:4d}) 점수 {score}")
        if i < 2:
            time.sleep(0.5)
            cur = grab()
            tdx, tdy, ts = find_shift(after, cur, (0, 0), search=200)
            inertia.append((tdx, tdy, ts))
            print(f"      관성(+0.5s 잔여): ({tdx},{tdy}) 점수 {ts}")
    stats = {}
    for name, vals in moves.items():
        if not vals:
            continue
        xs, ys = [v[0] for v in vals], [v[1] for v in vals]
        stats[name] = {"n": len(vals),
                       "mean": [statistics.mean(xs), statistics.mean(ys)],
                       "stdev": [statistics.stdev(xs) if len(xs) > 1 else 0.0,
                                 statistics.stdev(ys) if len(ys) > 1 else 0.0],
                       "raw": vals}
        print(f"  {name:5s} 평균 ({stats[name]['mean'][0]:7.1f},"
              f"{stats[name]['mean'][1]:6.1f}) σ ({stats[name]['stdev'][0]:.1f},"
              f"{stats[name]['stdev'][1]:.1f})")
    results["g2"] = {"stats": stats, "inertia": inertia}

    (WORK / "drag_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {WORK / 'drag_probe.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
