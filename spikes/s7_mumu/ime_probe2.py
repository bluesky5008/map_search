"""IME 오버레이 진단 2 — 텍스트 영역 클릭(재포커스) 후 삭제·타이핑·확정 시험."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.win import PostMessageInput, WgcCapture, find_mumu_instance
from mapscan.nav import ui

WORK = Path(__file__).parent / "work"
VK_RETURN = 0x0D
VK_BACK = 0x08
TEXT_AT = (500, 30)     # 게임 좌표 — 오버레이 텍스트 바 안
CONFIRM_AT = (2491, 40)  # ✓ 버튼


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    inst = find_mumu_instance("용스", expect_client=ui.CLIENT_SIZE)
    inp = PostMessageInput(inst.device)
    with WgcCapture(inst.top, inst.title) as cap:
        def shot(tag):
            time.sleep(0.6)
            f = cap.grab_fresh()
            Image.fromarray(f).save(WORK / f"ime2_{tag}.png")
            print(f"{tag}: 저장")

        inp.click(*TEXT_AT)          # 재포커스
        shot("0_refocus")
        for _ in range(8):
            inp.key(VK_BACK)         # VK 백스페이스
        shot("1_vkbs")
        inp.type_text("\b" * 8)      # WM_CHAR 백스페이스
        shot("2_charbs")
        inp.type_text("15")
        shot("3_typed")
        inp.key(VK_RETURN)
        shot("4_enter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
