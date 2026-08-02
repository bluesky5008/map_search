"""T14 파일럿 — 행 기반 팬 스캔에 '주기적 클릭 재앵커'를 넣어 좌표 무결성 검증.

배경(analyze.py·survey.py 실측): 기저의 y-성분이 지역에 따라 ~2.5px/타일씩
어긋나, 행 이동 중 c-방향(화면 y) 오차가 팬당 ~40px 누적된다. 10팬이면 좌표가
(2..11,-11..-21)타일 어긋난다(클릭 지상 진실). 순수 추측항법으로는 행 기반
스캔의 좌표 무결성이 성립하지 않는다.

파일럿 절차: 점프 → 소폭 팬 → 광폭 팬 10회. REANCHOR_EVERY팬마다 뷰 중앙
대역의 예측 타일을 클릭해 팝업 좌표(±4타일 새니티) + 선택 링(폴백: 클릭점)으로
그리드를 재앵커한다. 마지막에 상·하단 대역 truth 클릭 2점으로 최종 오차 측정.
성공 기준: 최종 |Δmx|,|Δmy| ≤ 1.
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

from mapscan.controller import plan_rows                     # noqa: E402
from mapscan.nav import Navigator, ui                        # noqa: E402
from mapscan.nav.pan import PanTracker, TrackLost            # noqa: E402
from mapscan.vision import DigitReader                       # noqa: E402
from mapscan.vision.grid import GridBasis, GridMapper, find_selection_highlight  # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"
REANCHOR_EVERY = 3
# 판독-예측 차 상한(오판독 방어). 드리프트는 팬당 1~2타일(실측)이므로
# 마지막 성공 앵커 이후 팬 수에 비례해 늘린다.


def sanity_window(pans_since_anchor: int, lost_since_anchor: int) -> int:
    """드리프트는 팬당 1~2타일, TrackLost 팬은 변위(~17 u-스텝) 자체가 유실된다."""
    return 2 + 2 * pans_since_anchor + 15 * lost_since_anchor


def read_popup(reader, frame, cx, cy):
    """클릭점 위 좌표 문자열 판독 — 팝업 구성 변형에 맞춰 x·y 슬라이딩."""
    for dx_off in (0, -30, -60, 30, 60, 90, 120):
        for dy in range(-260, -88, 6):
            y0, x0 = cy + dy, cx - 30 + dx_off
            if y0 < 0 or x0 < 0:
                continue
            strip = frame[y0:y0 + 34, x0:x0 + 225]
            if strip.size == 0:
                continue
            got = reader.read_coords(strip)
            if got:
                return got
    return None


def pick_center_tile(grid, tracker, frame_shape, y_client, offset):
    """뷰 중앙, 지정 대역 y의 예측 타일과 그 화면 위치."""
    h, w = frame_shape[:2]
    ox, oy = offset
    yf = y_client + oy
    ccx, ccy = grid.to_map(w / 2 - tracker.shift_at(yf), yf)
    best = None
    for dmx in range(-3, 4):
        for dmy in range(-3, 4):
            mx, my = round(ccx) + dmx, round(ccy) + dmy
            x0, y0 = grid.to_screen(mx, my)
            px, py = x0 + tracker.shift_at(y0), y0
            d = abs(px - w / 2) + abs(py - yf)
            if best is None or d < best[0]:
                best = (d, mx, my, px, py)
    return best[1:]


def click_and_read(nav, inp, cap, reader, px, py, offset, tag, work):
    ox, oy = offset
    nav.verify_detail_view(cap.grab_fresh())
    inp.click(round(px - ox), round(py - oy))
    time.sleep(1.1)
    after = cap.grab_fresh()
    strip = after[max(0, round(py) - 280):round(py) + 40,
                  max(0, round(px) - 140):round(px) + 340]
    Image.fromarray(strip).save(work / f"pilot_{tag}_strip.png")
    got = read_popup(reader, after, round(px), round(py))
    ring = find_selection_highlight(after)
    # 링은 클릭점 근방(반 타일 여유)일 때만 신뢰 — 오검출(하단 HUD) 방어
    if ring is not None and (abs(ring[0] - px) > 90 or abs(ring[1] - py) > 60):
        ring = None
    return got, ring, after


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--row", type=int, default=150)
    ap.add_argument("--pans", type=int, default=12)
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    out = {"row": args.row, "reanchor_every": REANCHOR_EVERY, "events": []}

    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            reader = DigitReader()
            row = plan_rows((1619, 1619))[args.row]
            grid = nav.jump(*row.start)
            frame = cap.grab_fresh()
            nav.capture_detail_ref(frame)
            offset = nav.client_offset(frame)
            tracker = PanTracker(offset)
            print(f"행 {args.row} 시작 {row.start}, 오프셋 {offset}")

            prev = frame
            pans_since = lost_since = 0
            for k in range(args.pans):
                src, dst = ui.PAN_SHORT if k == 0 else ui.PAN_WIDE
                frame = nav.pan(src, dst, steps=12 if k == 0 else 24)
                pans_since += 1
                try:
                    info = tracker.update(prev, frame, dst[0] - src[0])
                    out["events"].append({"pan": k + 1, "a": info["a"],
                                          "b": info["b"],
                                          "rejected": info["rejected"]})
                except TrackLost as exc:
                    print(f"팬 #{k + 1}: TrackLost {exc}")
                    out["events"].append({"pan": k + 1, "track_lost": str(exc)})
                    lost_since += 1
                prev = frame

                if (k + 1) % REANCHOR_EVERY == 0:
                    mx, my, px, py = pick_center_tile(grid, tracker,
                                                      frame.shape, 340, offset)
                    got, ring, after = click_and_read(
                        nav, inp, cap, reader, px, py, offset, f"p{k + 1}", WORK)
                    ev = {"pan": k + 1, "reanchor": True,
                          "predicted": [mx, my], "read": got and list(got),
                          "ring": ring and [round(v, 1) for v in ring]}
                    win = sanity_window(pans_since, lost_since)
                    if got and abs(got[0] - mx) <= win \
                            and abs(got[1] - my) <= win:
                        pos = ring if ring is not None else (px, py)
                        grid = GridMapper(GridBasis(), tuple(pos), tuple(got))
                        tracker.A = tracker.B = 0.0
                        pans_since = lost_since = 0
                        ev["applied"] = True
                        print(f"팬 #{k + 1} 재앵커: 예측({mx},{my}) → 실측{got} "
                              f"@{tuple(round(v) for v in pos)} 드리프트 "
                              f"({got[0] - mx:+d},{got[1] - my:+d})")
                    else:
                        ev["applied"] = False
                        print(f"팬 #{k + 1} 재앵커 실패: 예측({mx},{my}) 판독{got}")
                    out["events"].append(ev)
                    # 팝업이 다음 팬 드래그 경로에 없도록 확인만 하고 진행
                    prev = cap.grab_fresh()

            # 최종 지상 진실 — 상·하단 대역
            for y_cli, name in ((215, "top"), (425, "bottom")):
                mx, my, px, py = pick_center_tile(grid, tracker, frame.shape,
                                                  y_cli, offset)
                got, ring, _ = click_and_read(nav, inp, cap, reader, px, py,
                                              offset, f"truth_{name}", WORK)
                err = [got[0] - mx, got[1] - my] if got else None
                out["events"].append({"truth": name, "predicted": [mx, my],
                                      "read": got and list(got), "err": err})
                print(f"최종 {name}: 예측({mx},{my}) 실측{got} 오차{err}")

    (WORK / "pilot.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {WORK}\\pilot.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
