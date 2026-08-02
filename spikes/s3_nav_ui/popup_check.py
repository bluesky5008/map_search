"""S-4 — 점프 직후 선택 팝업을 ESC로 닫을 수 있는가? (커버리지 영향 측정)

판정: **불가.** 일반 뷰에서 ESC는 팝업을 닫지 않고 "게임을 종료하시겠습니까?"
확인 창을 띄운다(실측, 취소로 복구). 제품 코드에서 ESC를 쓰지 않는다.
팝업 오클루전은 설계대로 인접 방문의 겹침으로 커버한다(P-06).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
from PIL import Image

from mapscan.nav import Navigator, ScanPlanner
from mapscan.nav.navigator import VK_ESCAPE
from mapscan.win import PostMessageInput, WgcCapture, WindowSession


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--jump", type=int, nargs=2, default=(1020, 620))
    args = ap.parse_args()
    out = Path(__file__).parent / "work"

    session = WindowSession.attach(args.hwnd)
    capture = WgcCapture(args.hwnd, session.info().title)
    with capture:
        inp = PostMessageInput(args.hwnd, delay_range=(0.2, 0.4))
        nav = Navigator(capture, inp)
        t0 = time.monotonic()
        nav.jump(*args.jump)
        print(f"점프 {tuple(args.jump)}: {time.monotonic() - t0:.1f}s")
        before = capture.grab_fresh()
        Image.fromarray(before).save(out / "popup_before.png")

        inp.key(VK_ESCAPE)
        time.sleep(1.2)
        after = capture.grab_fresh()
        Image.fromarray(after).save(out / "popup_after.png")
        changed = float((np.abs(before.astype(np.int16) - after.astype(np.int16))
                         .sum(axis=2) > 12).mean())
        print(f"ESC 후 변경 픽셀 비율: {changed:.3f}")
        print(f"ESC 후에도 지도 모드? {nav.is_map_mode(after)} "
              f"(마커 {nav.map_mode_score(after):.2f})")

    for popup, label in [(None, "팝업 있음(기본)"), ((0, 0, 0, 0), "팝업 없음")]:
        p = ScanPlanner((1619, 1619), popup_rect=popup)
        area = p.stride[0] * p.stride[1]
        visits = (1620 / p.stride[0]) * (1620 / p.stride[1])
        print(f"{label}: 커버 {len(p.offsets)}개, 보폭 {p.stride}, "
              f"방문/타일 {area}, 1619² 방문 {visits:,.0f}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
