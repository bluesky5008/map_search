"""PostMessage 기반 백그라운드 입력 (ADR-002, S-1b 검증).

좌표는 모두 클라이언트 좌표계다. 게임이 상승 권한으로 실행 중이면 도구도 상승
권한이어야 메시지가 전달된다(WindowSession.check_permission).
"""

from __future__ import annotations

import logging
import random
import time

from . import win32

log = logging.getLogger(__name__)


def _lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class PostMessageInput:
    """클릭·휠 입력. 조작 간 지연에 무작위 지터를 넣는다(설계 §4.3)."""

    def __init__(self, hwnd: int, delay_range: tuple[float, float] = (0.3, 0.8)):
        self.hwnd = hwnd
        self.delay_range = delay_range

    def pause(self) -> None:
        lo, hi = self.delay_range
        time.sleep(random.uniform(lo, hi))

    def move(self, x: int, y: int) -> None:
        win32.post(self.hwnd, win32.WM_MOUSEMOVE, 0, _lparam(x, y))

    def click(self, x: int, y: int) -> None:
        lp = _lparam(x, y)
        win32.post(self.hwnd, win32.WM_MOUSEMOVE, 0, lp)
        if not win32.post(self.hwnd, win32.WM_LBUTTONDOWN, win32.MK_LBUTTON, lp):
            raise RuntimeError(f"클릭 전달 실패 (err={win32.last_error()}) — "
                               "관리자 권한으로 실행했는지 확인하세요.")
        time.sleep(0.05)
        win32.post(self.hwnd, win32.WM_LBUTTONUP, 0, lp)

    def wheel(self, x: int, y: int, notches: int) -> None:
        """휠 조작. notches > 0 = 줌 인, < 0 = 줌 아웃 (S-2 실측)."""
        left, top, _, _ = win32.window_rect(self.hwnd)
        # WM_MOUSEWHEEL의 lParam은 화면 좌표다.
        screen_lp = _lparam(left + x, top + y)
        client_lp = _lparam(x, y)
        step = 120 if notches > 0 else -120
        for _ in range(abs(notches)):
            win32.post(self.hwnd, win32.WM_MOUSEMOVE, 0, client_lp)
            win32.post(self.hwnd, win32.WM_MOUSEWHEEL, (step & 0xFFFF) << 16, screen_lp)
            time.sleep(0.06)

    def type_text(self, text: str) -> None:
        for ch in text:
            win32.post(self.hwnd, win32.WM_CHAR, ord(ch), 0)
            time.sleep(0.03)

    def key(self, vk: int, count: int = 1) -> None:
        """가상 키 입력(WM_KEYDOWN/UP). 백스페이스 등 편집 키 전달용.

        lParam에 스캔코드를 채운다 — PC 클라이언트는 lParam=0도 처리하지만
        MuMu(IME 오버레이)는 스캔코드 없는 키 메시지를 무시한다(S-7 실측:
        VK_BACK lParam=0 무효, 스캔코드 포함 시 삭제 동작).
        """
        scan = win32.user32.MapVirtualKeyW(vk, 0) & 0xFF  # MAPVK_VK_TO_VSC
        down = 1 | (scan << 16)
        up = down | (1 << 30) | (1 << 31)
        for _ in range(count):
            win32.post(self.hwnd, win32.WM_KEYDOWN, vk, down)
            time.sleep(0.02)
            win32.post(self.hwnd, win32.WM_KEYUP, vk, up)
            time.sleep(0.03)

    def double_click(self, x: int, y: int) -> None:
        lp = _lparam(x, y)
        self.click(x, y)
        time.sleep(0.05)
        win32.post(self.hwnd, win32.WM_LBUTTONDBLCLK, win32.MK_LBUTTON, lp)
        time.sleep(0.05)
        win32.post(self.hwnd, win32.WM_LBUTTONUP, 0, lp)

    def drag(self, x0: int, y0: int, x1: int, y1: int,
             steps: int = 12, hold: float = 0.03) -> None:
        """버튼을 누른 채 이동 — 지도 팬(이동 전략 후보) 검증용."""
        win32.post(self.hwnd, win32.WM_MOUSEMOVE, 0, _lparam(x0, y0))
        win32.post(self.hwnd, win32.WM_LBUTTONDOWN, win32.MK_LBUTTON, _lparam(x0, y0))
        time.sleep(hold)
        for i in range(1, steps + 1):
            x = x0 + (x1 - x0) * i // steps
            y = y0 + (y1 - y0) * i // steps
            win32.post(self.hwnd, win32.WM_MOUSEMOVE, win32.MK_LBUTTON, _lparam(x, y))
            time.sleep(hold)
        win32.post(self.hwnd, win32.WM_LBUTTONUP, 0, _lparam(x1, y1))
