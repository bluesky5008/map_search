"""IME 진단 4 — 스캔코드 lParam을 채운 VK_BACK/DELETE로 삭제 시험.

X 입력란 클릭 → 오버레이(프리필) → 스캔코드 백스페이스 ×6 → 관찰 →
타이핑 → ✓ 확정 → 입력란 값 확인.
"""

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.nav import Navigator, ui
from mapscan.win import PostMessageInput, WgcCapture, find_mumu_instance
from mapscan.win import win32

WORK = Path(__file__).parent / "work"
CONFIRM_AT = (2491, 40)
FIELD_X = ui.COORD_INPUT_X            # (2266, 498)
VK_BACK, VK_DELETE = 0x08, 0x2E
SC_BACK, SC_DELETE = 0x0E, 0x53


def key_scan(hwnd, vk, scan, extended=False):
    down = 1 | (scan << 16) | ((1 << 24) if extended else 0)
    up = down | (1 << 30) | (1 << 31)
    win32.post(hwnd, win32.WM_KEYDOWN, vk, down)
    time.sleep(0.03)
    win32.post(hwnd, win32.WM_KEYUP, vk, up)
    time.sleep(0.04)


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
            Image.fromarray(f).save(WORK / f"ime4_{tag}.png")
            print(f"{tag}: 지도마커 {nav.map_mode_score(f):.2f}")

        inp.click(*FIELD_X)               # 오버레이 열기
        shot("0_open")
        for _ in range(6):
            key_scan(inst.device, VK_BACK, SC_BACK)
        shot("1_scanbs")
        for _ in range(3):
            key_scan(inst.device, VK_DELETE, SC_DELETE, extended=True)
        shot("2_scandel")
        inp.type_text("15")
        shot("3_typed")
        inp.click(*CONFIRM_AT)
        shot("4_confirm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
