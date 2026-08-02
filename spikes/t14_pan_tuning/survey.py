"""T14 클릭-그리드 측량 — 지점별 국소 기저·앵커 신뢰성·팝업 글리프 수집.

행 150 지상 진실에서 c-방향(화면 y) 오차가 앵커 기준 +400px로 나타났다
(analyze.py). 점프 팝업은 정상 위치였으므로 원인은 장거리 기하(기저의
지역/고도 의존)다. 각 지점에서 화면 전역 12점의 예측 타일을 클릭해
(팝업 좌표 = 지상 진실, 선택 링 = 정밀 화면 위치) 국소 기저를 직접 측정한다.

지점: center(캘리브레이션 원점 대조군) / nw(행 150 문제 지역) /
rowstart(행 시작 인셋) / west(서쪽 경계 — T14.2 카메라 클램프 검증)

수집한 팝업 스트립은 겨울 테마 좌표 글리프 템플릿 소스로도 쓴다(T14.3).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.nav import Navigator, ui                        # noqa: E402
from mapscan.vision import DigitReader                       # noqa: E402
from mapscan.vision.grid import find_selection_highlight     # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"

# 클릭 순서는 직전 팝업(타일 중심 기준 -290..+370 x, -215..+150 y)을 피해
# x를 500px 이상 번갈아 띄운다. 팝업 버튼 오클릭(R-10)은 안전 검사로 재차 방지.
# 좌상단(cx<700, cy<340)은 팝업이 디테일 뷰 시그니처(50..400,55..110)를 가려
# 이후 검증을 막으므로 제외한다(1차 측량 실측).
TARGETS = [(750, 215), (1400, 340), (750, 340), (1400, 215), (400, 445),
           (1900, 215), (900, 215), (1400, 445), (900, 340), (1900, 340),
           (900, 445), (1900, 445)]
TARGETS_EAST = [(1400, 215), (1900, 445), (1400, 340), (1900, 215),
                (1400, 445), (1900, 340)]   # 서쪽 경계용(좌반은 맵 밖)

SITES = [
    ("center", (1020, 620), TARGETS),
    ("nw", (114, 815), TARGETS),
    ("rowstart", (10, 922), TARGETS),
    ("west", (0, 922), TARGETS_EAST),
]

POPUP_PAD = (-300, -225, 380, 160)   # 안전 여유 포함 팝업 회피 사각형


def robust_jump(nav, cap, mx, my):
    """점프 후 지도 모드 잔류 시 GO를 재클릭한다.

    1차 측량에서 선택 팝업이 열린 채 점프하면 GO가 무시되는 현상을 봤다
    (지도 모드가 열린 채 잔류). 재시도 발생 여부를 기록해 원인 검증에 쓴다.
    """
    grid = nav.jump(mx, my)
    retries = 0
    for _ in range(2):
        if not nav.is_map_mode(cap.grab_fresh()):
            break
        retries += 1
        nav._click_verified(nav.ui.GO_BUTTON)
        nav.wait_stable()
    else:
        raise RuntimeError("GO 재클릭 후에도 지도 모드 잔류")
    return grid, retries


def survey_site(nav, inp, cap, reader, name, jump_at, targets, work):
    print(f"[{name}] 점프 {jump_at}")
    grid, retries = robust_jump(nav, cap, *jump_at)
    if retries:
        print(f"  (점프 GO 재클릭 {retries}회 필요)")
    frame = cap.grab_fresh()
    if getattr(nav, "_detail_ref", None) is None:
        nav.capture_detail_ref(frame)
    offset = nav.client_offset(frame)
    ox, oy = offset
    Image.fromarray(frame).save(work / f"survey_{name}_jump.png")
    out = {"site": name, "jump": list(jump_at), "offset": list(offset),
           "jump_go_retries": retries, "clicks": []}
    prev_click = None
    for i, (cx_cli, cy_cli) in enumerate(targets):
        xf, yf = cx_cli + ox, cy_cli + oy
        mx, my = (round(v) for v in grid.to_map(xf, yf))
        px, py = grid.to_screen(mx, my)
        rec = {"i": i, "target_cli": [cx_cli, cy_cli], "predicted": [mx, my],
               "pred_screen": [round(px, 1), round(py, 1)]}
        if prev_click is not None and \
                prev_click[0] + POPUP_PAD[0] <= px <= prev_click[0] + POPUP_PAD[2] and \
                prev_click[1] + POPUP_PAD[1] <= py <= prev_click[1] + POPUP_PAD[3]:
            rec["skipped"] = "직전 팝업 영역"
            out["clicks"].append(rec)
            print(f"  #{i} ({mx},{my}) 건너뜀(팝업 영역)")
            continue
        try:
            nav.verify_detail_view(cap.grab_fresh())
            inp.click(round(px - ox), round(py - oy))
            time.sleep(1.1)
            after = cap.grab_fresh()
            prev_click = (px, py)
            strip = after[max(0, round(py) - 260):round(py) + 40,
                          max(0, round(px) - 120):round(px) + 320]
            Image.fromarray(strip).save(work / f"survey_{name}_{i:02d}_strip.png")
            got = None
            for dx_off in (0, -30, -60, 30, 60):
                for dy in range(-230, -100, 6):
                    s = after[round(py) + dy:round(py) + dy + 34,
                              round(px) - 30 + dx_off:round(px) + 195 + dx_off]
                    got = reader.read_coords(s)
                    if got:
                        break
                if got:
                    break
            ring = find_selection_highlight(after)
            rec["read"] = list(got) if got else None
            rec["ring"] = [round(v, 1) for v in ring] if ring else None
            if ring is None:
                Image.fromarray(after).save(work / f"survey_{name}_{i:02d}_noring.png")
            print(f"  #{i} 예측({mx},{my})@({px:.0f},{py:.0f}) → "
                  f"판독 {got} 링 {rec['ring']}")
        except Exception as exc:
            rec["error"] = repr(exc)
            print(f"  #{i} 실패: {exc!r}")
        out["clicks"].append(rec)
    # 팝업이 열린 채 다음 점프를 하면 GO가 무시된다 — 소폭 팬으로 지운다
    try:
        nav.pan(*ui.PAN_SHORT, steps=12)
    except Exception as exc:
        print(f"  팝업 제거 팬 실패: {exc!r}")
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--only", help="지점 이름 필터(쉼표 구분)")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    sites = SITES if not args.only else \
        [s for s in SITES if s[0] in args.only.split(",")]

    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    results = []
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            reader = DigitReader()
            for name, jump_at, targets in sites:
                try:
                    results.append(survey_site(nav, inp, cap, reader, name,
                                               jump_at, targets, WORK))
                except Exception as exc:   # 한 지점 실패가 전체를 막지 않게
                    print(f"[{name}] 실패: {exc!r}")
                    results.append({"site": name, "error": repr(exc)})
    (WORK / "survey.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {WORK}\\survey.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
