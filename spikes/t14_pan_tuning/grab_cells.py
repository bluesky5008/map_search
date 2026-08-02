"""표적 셀 프레임 크롭 채집 — 분류 임계 튜닝·회귀 픽스처용 (240x160, 중심 120,80).

점프 후 지정 맵 좌표 셀의 화면 위치를 잘라 저장한다. 클릭하지 않는다.
사용: --hwnd H --jump MX MY --cells x,y x,y --name PREFIX
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.nav import Navigator                                    # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"
HALF = (120, 80)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--jump", type=int, nargs=2, required=True)
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    cells = [tuple(int(v) for v in c.split(",")) for c in args.cells]

    session = WindowSession.attach(args.hwnd)
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            nav = Navigator(cap, PostMessageInput(session.hwnd))
            grid = nav.jump(*args.jump)
            frame = cap.grab_fresh()
            for mx, my in cells:
                px, py = grid.to_screen(mx, my)
                x0, y0 = round(px) - HALF[0], round(py) - HALF[1]
                crop = frame[max(0, y0):y0 + 2 * HALF[1],
                             max(0, x0):x0 + 2 * HALF[0]]
                out = WORK / f"{args.name}_{mx}_{my}_cell.png"
                Image.fromarray(crop).save(out)
                print(f"({mx},{my}) @({px:.0f},{py:.0f}) -> {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
