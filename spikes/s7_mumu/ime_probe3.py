"""IME 진단 3 — 더블탭 전체선택 → 타이핑 치환 → ✓ 확정 시험."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.nav import Navigator, ui
from mapscan.win import PostMessageInput, WgcCapture, find_mumu_instance

WORK = Path(__file__).parent / "work"
TEXT_AT = (500, 30)
CONFIRM_AT = (2491, 40)


class _NoInput:
    def __getattr__(self, _):
        raise RuntimeError("판정 전용")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    inst = find_mumu_instance("용스", expect_client=ui.CLIENT_SIZE)
    inp = PostMessageInput(inst.device)
    with WgcCapture(inst.top, inst.title) as cap:
        nav = Navigator(cap, _NoInput.__new__(_NoInput))

        def shot(tag):
            time.sleep(0.7)
            f = cap.grab_fresh()
            Image.fromarray(f).save(WORK / f"ime3_{tag}.png")
            print(f"{tag}: 지도마커 {nav.map_mode_score(f):.2f}")

        inp.double_click(*TEXT_AT)
        shot("0_dbl")
        inp.type_text("15")
        shot("1_typed")
        inp.click(*CONFIRM_AT)
        shot("2_confirm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
