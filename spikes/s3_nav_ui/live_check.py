"""T12 실기 검증 — 지도 모드 확인 → 맵 크기 자동 감지 → 좌표 점프 → 분류.

관리자 권한으로 실행해야 한다(게임이 elevated). run_live.ps1 참조.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.nav import Navigator, ScanPlanner
from mapscan.vision import TileClassifier
from mapscan.win import PostMessageInput, WgcCapture, WindowSession


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--dir", default=str(Path(__file__).parent / "work"))
    ap.add_argument("--jump", type=int, nargs=2, default=(1020, 620))
    ap.add_argument("--skip-detect", action="store_true")
    args = ap.parse_args()
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    session = WindowSession.attach(args.hwnd)
    info = session.info()
    print(f"대상: hwnd={info.hwnd:#x} client={info.client} elevated={info.elevated}")
    capture = WgcCapture(args.hwnd, info.title)
    with capture:
        nav = Navigator(capture, PostMessageInput(args.hwnd, delay_range=(0.2, 0.4)))
        frame = capture.grab_fresh()
        print(f"지도 모드 마커 점수: {nav.map_mode_score(frame):.3f}")
        nav.enter_map_mode()
        print("지도 모드 진입 확인")

        if not args.skip_detect:
            t0 = time.monotonic()
            map_max = nav.detect_map_size()
            print(f"맵 크기 감지: {map_max} ({time.monotonic() - t0:.1f}s)")
        else:
            map_max = (1619, 1619)

        t0 = time.monotonic()
        grid = nav.jump(*args.jump)
        print(f"점프 {tuple(args.jump)} 완료 ({time.monotonic() - t0:.1f}s), "
              f"앵커 픽셀 {grid.anchor_px}")
        frame = capture.grab_fresh()
        Image.fromarray(frame).save(out / "live_jump.png")

        clf = TileClassifier(grid.basis)
        cells = grid.visible_cells(frame.shape[1::-1])
        t0 = time.monotonic()
        results = [(c, clf.classify(frame, c.px, c.py)) for c in cells]
        print(f"가시 타일 {len(results)}개 분류 {time.monotonic() - t0:.1f}s")
        target = next((r for c, r in results if (c.mx, c.my) == tuple(args.jump)), None)
        print(f"대상 타일 {tuple(args.jump)} 분류: {target}")

        planner = ScanPlanner(map_max)
        print(f"방문 계획: 보폭 {planner.stride}, 커버 오프셋 {len(planner.offsets)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
