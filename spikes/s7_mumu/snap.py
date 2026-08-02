"""현재 화면 스냅샷 + 지도 마커 점수 (입력 없음, 진단용)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.nav import Navigator, ui
from mapscan.win import WgcCapture, find_mumu_instance

WORK = Path(__file__).parent / "work"


class _NoInput:
    def click(self, *a): raise RuntimeError("입력 금지(진단 전용)")
    def pause(self): pass
    def key(self, *a): raise RuntimeError("입력 금지")
    def type_text(self, *a): raise RuntimeError("입력 금지")
    def drag(self, *a, **k): raise RuntimeError("입력 금지")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    name = sys.argv[1] if len(sys.argv) > 1 else "용스"
    out = sys.argv[2] if len(sys.argv) > 2 else "snap_now.png"
    inst = find_mumu_instance(name, expect_client=ui.CLIENT_SIZE)
    with WgcCapture(inst.top, inst.title) as cap:
        frame = cap.grab_fresh()
        nav = Navigator(cap, _NoInput())
        score = nav.map_mode_score(frame)
        Image.fromarray(frame).save(WORK / out)
        print(f"프레임 {frame.shape[1]}x{frame.shape[0]} 지도 마커 {score:.3f} "
              f"→ work/{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
