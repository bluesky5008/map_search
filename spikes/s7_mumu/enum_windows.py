"""MuMu·게임 창 열거(읽기 전용) — 게이트 4 사전 프로그램 확인.

입력·캡처 없이 Win32 조회만: 제목/클래스/rect/client/pid + 자식 창 트리.
"""
import ctypes
import ctypes.wintypes as wt
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
u32 = ctypes.windll.user32

def text_of(h):
    n = u32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(h, buf, n + 1)
    return buf.value

def class_of(h):
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, buf, 256)
    return buf.value

def rect_of(h):
    r = wt.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)

def client_of(h):
    r = wt.RECT()
    u32.GetClientRect(h, ctypes.byref(r))
    return (r.right, r.bottom)

def pid_of(h):
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value

KEYS = ("삼국지", "MuMu", "mumu", "용스", "전략판", "NemuPlayer")
tops = []

@ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
def on_top(h, _):
    if not u32.IsWindowVisible(h):
        return True
    t = text_of(h)
    c = class_of(h)
    if any(k in t for k in KEYS) or any(k in c for k in ("Qt5", "nemu", "Mumu", "MuMu")):
        tops.append(h)
    return True

u32.EnumWindows(on_top, 0)

def dump_children(h, depth, out):
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def on_child(ch, _):
        out.append((depth, ch))
        dump_children(ch, depth + 1, out)
        return True
    u32.EnumChildWindows(h, on_child, 0)

for h in tops:
    print(f"top hwnd={h:#x} pid={pid_of(h)} class='{class_of(h)}' title='{text_of(h)}'")
    print(f"    rect={rect_of(h)} client={client_of(h)}")
    kids = []
    dump_children(h, 1, kids)
    for depth, ch in kids[:20]:
        cw = client_of(ch)
        print(f"    {'  ' * depth}child hwnd={ch:#x} class='{class_of(ch)}' "
              f"title='{text_of(ch)}' client={cw}")
    if len(kids) > 20:
        print(f"    ... 자식 {len(kids) - 20}개 더")
