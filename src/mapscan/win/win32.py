"""Win32 바인딩과 상수 (설계 §2 win 계층 공용).

Per-Monitor v2 DPI 인식을 임포트 시 설정하여 모든 픽셀 계산을 물리 좌표로 통일한다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except (AttributeError, OSError):  # pragma: no cover - 구버전 Windows
    pass

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEWHEEL = 0x020A
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOP = 0

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


def window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """(left, top, width, height) — 창 외곽."""
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def client_size(hwnd: int) -> tuple[int, int]:
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def process_id(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_process_elevated(pid: int) -> bool | None:
    """대상 프로세스의 상승 여부. 조회 실패 시 None."""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            elevation = wt.DWORD()
            size = wt.DWORD()
            ok = advapi32.GetTokenInformation(
                tok, TOKEN_ELEVATION, ctypes.byref(elevation), 4, ctypes.byref(size))
            return bool(elevation.value) if ok else None
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def is_self_elevated() -> bool:
    return bool(shell32.IsUserAnAdmin())


def work_area(hwnd: int) -> tuple[int, int, int, int]:
    """대상 창이 속한 모니터의 작업 영역 (left, top, width, height)."""
    mon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    w = mi.rcWork
    return w.left, w.top, w.right - w.left, w.bottom - w.top


def set_window_rect(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    return bool(user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE))


def raise_to_top(hwnd: int) -> bool:
    """활성화 없이 z순서 최상단으로 올린다 (캡처 대상 확정용)."""
    return bool(user32.SetWindowPos(
        hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE))


def post(hwnd: int, msg: int, wparam: int, lparam: int) -> bool:
    return bool(user32.PostMessageW(hwnd, msg, wparam, lparam))


def last_error() -> int:
    return ctypes.get_last_error()
