"""S-1b: deterministic window binding + single-session before/click/after test.

Binding trick: raise the target HWND to top of the non-topmost band (no activation)
right before starting the WGC session, so the library's title match picks it.
The session then stays bound to that window regardless of later z-order changes.

Usage:
  s1b_session.py peek --hwnd <n> --out peek.png
  s1b_session.py test --hwnd <n> --x <cx> --y <cy> --before b.png --after a.png [--delay 1.0]

Coordinates are client-area pixels. Spike only.
"""

import argparse
import ctypes
import sys
import threading
import time

from PIL import Image
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

TITLE = "삼국지-전략판 113.554"
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x200, 0x201, 0x202, 1
SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE


def raise_to_top(hwnd: int):
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)  # hWndInsertAfter=HWND_TOP


def post_click(hwnd: int, x: int, y: int):
    lparam = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)


def save(frame, path):
    img = Image.fromarray(frame.frame_buffer[:, :, :3][:, :, ::-1])
    img.save(path)


def run_session(hwnd, on_frames, timeout=15.0):
    """Bind a session to hwnd (via raise-to-top) and drive on_frames(state) per frame."""
    done = threading.Event()
    raise_to_top(hwnd)
    cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=TITLE)

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        if on_frames(frame):
            done.set()
            control.stop()

    @cap.event
    def on_closed():
        done.set()

    threading.Thread(target=cap.start, daemon=True).start()
    ok = done.wait(timeout)
    return ok


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("peek")
    p1.add_argument("--hwnd", type=int, required=True)
    p1.add_argument("--out", required=True)
    p2 = sub.add_parser("test")
    p2.add_argument("--hwnd", type=int, required=True)
    p2.add_argument("--x", type=int, required=True)
    p2.add_argument("--y", type=int, required=True)
    p2.add_argument("--before", required=True)
    p2.add_argument("--after", required=True)
    p2.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    if a.cmd == "peek":
        state = {"done": False}

        def on_frames(frame):
            if not state["done"]:
                save(frame, a.out)
                state["done"] = True
            return True

        ok = run_session(a.hwnd, on_frames)
        print("peek", "ok" if ok and state["done"] else "FAIL")
        return 0 if state["done"] else 2

    state = {"phase": 0, "t_after": 0.0}

    def on_frames(frame):
        now = time.time()
        if state["phase"] == 0:
            save(frame, a.before)
            post_click(a.hwnd, a.x, a.y)
            state["t_after"] = now + a.delay
            state["phase"] = 1
            return False
        if state["phase"] == 1 and now >= state["t_after"]:
            save(frame, a.after)
            state["phase"] = 2
            return True
        return False

    ok = run_session(a.hwnd, on_frames)
    print("test", "ok" if ok and state["phase"] == 2 else "FAIL")
    return 0 if state["phase"] == 2 else 2


if __name__ == "__main__":
    sys.exit(main())
