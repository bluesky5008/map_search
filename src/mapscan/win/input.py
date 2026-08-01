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
