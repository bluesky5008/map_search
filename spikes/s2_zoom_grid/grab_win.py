"""Screen-grab a window by HWND (spike helper; avoids WGC title-match ambiguity)."""

import ctypes
import ctypes.wintypes as wt
import sys

from PIL import ImageGrab

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

hwnd, out = int(sys.argv[1]), sys.argv[2]
r = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
img.save(out)
print(f"rect=({r.left},{r.top},{r.right - r.left},{r.bottom - r.top}) saved {img.size} -> {out}")
