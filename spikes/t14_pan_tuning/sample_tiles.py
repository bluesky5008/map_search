"""T14.3 점령형·내땅 표본 수집 — 비중립 타일 클릭으로 팝업 진실 + 스프라이트 크롭.

점령된 자원 타일은 스프라이트가 생산 시설로 바뀌므로(확정 사실 10) 템플릿을
점령형으로 따로 수집해야 한다. 내땅(초록) 테두리 표본은 미확보라 잠정
임계값 상태다(확정 사실 13). 이 스크립트는 지정 지점에서:

  점프 → 프레임 저장(스프라이트 소스) → 대역 내 셀 분류 → 비중립(점령) 셀을
  팝업 회피 순서로 클릭 → 팝업 스트립(이름·레벨·좌표 진실)과 타일 크롭 저장

산출물을 보고 템플릿 등록(assets/templates/tiles/)과 점령 색 임계 확정을
진행한다(AC-02 연계).
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
from mapscan.vision import TileClassifier                    # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"
POPUP_PAD = (-300, -225, 380, 160)   # 직전 팝업 회피(안전 여유 포함)
CROP_HALF = (60, 40)                 # 타일 크롭 반폭·반높이 (wood.png 96x64 참고 + 여유)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--site", type=int, nargs=2, required=True, metavar=("MX", "MY"))
    ap.add_argument("--name", required=True)
    ap.add_argument("--max-clicks", type=int, default=10)
    ap.add_argument("--occupancy", default="",
                    help="이 점령상태만 표본(쉼표 구분, 예: mine,ally — 기본 전체 비중립)")
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    want = set(args.occupancy.split(",")) if args.occupancy else None

    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    out = {"site": args.name, "jump": list(args.site), "samples": []}
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            clf = TileClassifier()
            grid = nav.jump(*args.site)
            frame = cap.grab_fresh()
            nav.capture_detail_ref(frame)
            offset = nav.client_offset(frame)
            ox, oy = offset
            Image.fromarray(frame).save(WORK / f"tiles_{args.name}_frame.png")

            # 점프 팝업 영역은 분류 표본에서 제외
            anchor_c = (grid.anchor_px[0] - ox, grid.anchor_px[1] - oy)
            popup0 = (anchor_c[0] + ui.POPUP_RECT_REL[0],
                      anchor_c[1] + ui.POPUP_RECT_REL[1],
                      anchor_c[0] + ui.POPUP_RECT_REL[2],
                      anchor_c[1] + ui.POPUP_RECT_REL[3])
            exclude = [(r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)
                       for r in list(ui.HUD_RECTS_CLIENT) + [popup0]]
            cells = []
            for cell in grid.visible_cells(frame.shape[1::-1], exclude=exclude):
                cx_cli, cy_cli = cell.px - ox, cell.py - oy
                if not (ui.BAND_Y[0] <= cy_cli <= ui.BAND_Y[1]):
                    continue
                # 좌상단 셀의 팝업은 디테일 뷰 시그니처(50..400,55..110)를 가려
                # 이후 클릭 검증을 전부 막는다(1차 실행 실측) — 제외
                if cx_cli < 730 and cy_cli < 340:
                    continue
                r = clf.classify(frame, cell.px, cell.py)
                if r.occupancy == "neutral":
                    continue
                if want and r.occupancy not in want:
                    continue
                cells.append((cell, r))
            counts: dict[str, int] = {}
            for _, r in cells:
                counts[r.occupancy] = counts.get(r.occupancy, 0) + 1
            print(f"비중립 후보 {len(cells)}개: {counts}")

            # 점령상태별로 고르게, 직전 팝업 영역을 피해 클릭
            by_occ: dict[str, list] = {}
            for c, r in cells:
                by_occ.setdefault(r.occupancy, []).append((c, r))
            picked, prev = [], None
            pools = [list(v) for v in by_occ.values()]
            while len(picked) < args.max_clicks and any(pools):
                for pool in pools:
                    while pool:
                        c, r = pool.pop(0)
                        if prev is not None and \
                                prev[0] + POPUP_PAD[0] <= c.px <= prev[0] + POPUP_PAD[2] and \
                                prev[1] + POPUP_PAD[1] <= c.py <= prev[1] + POPUP_PAD[3]:
                            continue
                        picked.append((c, r))
                        prev = (c.px, c.py)
                        break
                    if len(picked) >= args.max_clicks:
                        break
                if not any(pools):
                    break

            for i, (c, r) in enumerate(picked):
                # 클릭 전에 원본 프레임에서 스프라이트 크롭(팝업 오염 없는 상태)
                x0 = round(c.px) - CROP_HALF[0]
                y0 = round(c.py) - CROP_HALF[1]
                crop = frame[max(0, y0):y0 + 2 * CROP_HALF[1],
                             max(0, x0):x0 + 2 * CROP_HALF[0]]
                Image.fromarray(crop).save(
                    WORK / f"tiles_{args.name}_{i:02d}_sprite.png")
                try:
                    nav.verify_detail_view(cap.grab_fresh())
                    inp.click(round(c.px - ox), round(c.py - oy))
                    time.sleep(1.1)
                    after = cap.grab_fresh()
                    strip = after[max(0, round(c.py) - 280):round(c.py) + 40,
                                  max(0, round(c.px) - 140):round(c.px) + 340]
                    Image.fromarray(strip).save(
                        WORK / f"tiles_{args.name}_{i:02d}_popup.png")
                    out["samples"].append(
                        {"i": i, "map": [c.mx, c.my], "occupancy": r.occupancy,
                         "confidence": r.confidence,
                         "screen": [round(c.px), round(c.py)]})
                    print(f"  #{i} ({c.mx},{c.my}) {r.occupancy} 저장")
                except Exception as exc:
                    print(f"  #{i} 실패: {exc!r}")
                    out["samples"].append({"i": i, "map": [c.mx, c.my],
                                           "error": repr(exc)})
    (WORK / f"tiles_{args.name}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: tiles_{args.name}.json + 표본 {len(out['samples'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
