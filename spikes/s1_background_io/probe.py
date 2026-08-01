"""S-1 spike: background capture (PrintWindow) + background input (PostMessage) probe.

Usage:
  probe.py list
  probe.py capture --hwnd <hex|dec> --out <file.png>
  probe.py click   --hwnd <hex|dec> --x <cx> --y <cy>
  probe.py clickcap --hwnd <hex|dec> --x <cx> --y <cy> --before b.png --after a.png [--delay 0.8]

Coordinates are client-area pixels. Not product code (spike only).
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# Per-Monitor v2 DPI awareness so all pixel math is physical.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2


def parse_hwnd(s: str) -> int:
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def list_windows(title_substr: str = "삼국지"):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if title_substr not in title:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        wr, cr = wt.RECT(), wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(wr))
        user32.GetClientRect(hwnd, ctypes.byref(cr))
        found.append(
            dict(hwnd=hwnd, title=title, cls=cls.value, pid=pid.value,
                 win=(wr.left, wr.top, wr.right - wr.left, wr.bottom - wr.top),
                 client=(cr.right, cr.bottom),
                 minimized=bool(user32.IsIconic(hwnd)))
        )
        return True

    user32.EnumWindows(cb, 0)
    return found


def capture(hwnd: int, out: str):
    cr = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    w, h = cr.right, cr.bottom
    if w == 0 or h == 0:
        print(f"FAIL: client rect is {w}x{h}")
        return 1

    hdc_src = user32.GetDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc_src)
    bmp = gdi32.CreateCompatibleBitmap(hdc_src, w, h)
    gdi32.SelectObject(memdc, bmp)
    ok = user32.PrintWindow(hwnd, memdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h  # top-down
    bih.biPlanes, bih.biBitCount, bih.biCompression = 1, 32, 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bih), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc_src)

    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    img.save(out)

    # Quick stats to detect black/blank frames without eyeballing.
    gray = img.convert("L")
    hist = gray.histogram()
    total = w * h
    mean = sum(i * c for i, c in enumerate(hist)) / total
    nonblack = 100.0 * (total - sum(hist[:8])) / total
    print(f"PrintWindow ok={ok} scanlines={got} size={w}x{h} mean={mean:.1f} nonblack={nonblack:.1f}% -> {out}")
    return 0 if ok and nonblack > 5 else 2


def click(hwnd: int, x: int, y: int):
    lparam = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    print(f"posted click at client ({x},{y}) to hwnd {hwnd:#x}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("capture", "click", "clickcap"):
        p = sub.add_parser(name)
        p.add_argument("--hwnd", required=True)
        if name in ("capture",):
            p.add_argument("--out", required=True)
        if name in ("click", "clickcap"):
            p.add_argument("--x", type=int, required=True)
            p.add_argument("--y", type=int, required=True)
        if name == "clickcap":
            p.add_argument("--before", required=True)
            p.add_argument("--after", required=True)
            p.add_argument("--delay", type=float, default=0.8)
    a = ap.parse_args()

    if a.cmd == "list":
        for wnd in list_windows():
            print(wnd)
        return 0
    hwnd = parse_hwnd(a.hwnd)
    if a.cmd == "capture":
        return capture(hwnd, a.out)
    if a.cmd == "click":
        click(hwnd, a.x, a.y)
        return 0
    if a.cmd == "clickcap":
        rc = capture(hwnd, a.before)
        click(hwnd, a.x, a.y)
        time.sleep(a.delay)
        rc2 = capture(hwnd, a.after)
        return rc or rc2
    return 1


if __name__ == "__main__":
    sys.exit(main())
