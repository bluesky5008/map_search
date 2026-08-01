"""S-1b elevated helper: peek -> wait for go-file -> before/click/after in one session.

Runs elevated (UAC) so SetWindowPos/PostMessage reach the elevated game window.
Flow:
  1. Raise target hwnd, bind WGC session, save peek frame. Session stays open.
  2. Poll go-file (up to 180s). Contents "x,y" = client click point; "abort" = stop.
  3. Save before frame, post click, save after frame. Write status file.

Usage (elevated):
  s1b_elevated.py --hwnd 328668 --dir <evidence_dir>
Files: peek2.png, go.txt(read), before2.png, after2.png, status.txt(written)
"""

import argparse
import ctypes
import os
import sys
import threading
import time

from PIL import Image
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

TITLE = "삼국지-전략판 113.554"
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x200, 0x201, 0x202, 1


def log(dirp, msg):
    with open(os.path.join(dirp, "status.txt"), "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=int, required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    d = a.dir
    open(os.path.join(d, "status.txt"), "w").close()
    gofile = os.path.join(d, "go.txt")
    if os.path.exists(gofile):
        os.remove(gofile)

    log(d, f"elevated={bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    rc = user32.SetWindowPos(a.hwnd, 0, 0, 0, 0, 0, 0x13)
    log(d, f"SetWindowPos rc={rc} err={ctypes.get_last_error()}")

    state = {"phase": "peek", "click": None, "t_after": 0.0}
    done = threading.Event()

    cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=TITLE)

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        now = time.time()
        ph = state["phase"]
        if ph == "peek":
            Image.fromarray(frame.frame_buffer[:, :, :3][:, :, ::-1]).save(
                os.path.join(d, "peek2.png"))
            log(d, "peek saved; waiting for go.txt")
            state["phase"] = "wait"
            state["t_wait_end"] = now + 180
            return
        if ph == "wait":
            if now > state["t_wait_end"]:
                log(d, "TIMEOUT waiting for go.txt")
                done.set(); control.stop(); return
            if os.path.exists(gofile):
                txt = open(gofile, encoding="utf-8").read().strip()
                if txt == "abort":
                    log(d, "aborted by go.txt")
                    done.set(); control.stop(); return
                try:
                    x, y = (int(v) for v in txt.split(","))
                except ValueError:
                    return  # partially written; retry next frame
                state["click"] = (x, y)
                Image.fromarray(frame.frame_buffer[:, :, :3][:, :, ::-1]).save(
                    os.path.join(d, "before2.png"))
                lparam = (y << 16) | (x & 0xFFFF)
                r1 = user32.PostMessageW(a.hwnd, WM_MOUSEMOVE, 0, lparam)
                r2 = user32.PostMessageW(a.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
                r3 = user32.PostMessageW(a.hwnd, WM_LBUTTONUP, 0, lparam)
                log(d, f"click ({x},{y}) rc={r1},{r2},{r3} err={ctypes.get_last_error()}")
                state["t_after"] = now + a.delay
                state["phase"] = "after"
            return
        if ph == "after" and now >= state["t_after"]:
            Image.fromarray(frame.frame_buffer[:, :, :3][:, :, ::-1]).save(
                os.path.join(d, "after2.png"))
            log(d, "after saved; DONE")
            state["phase"] = "done"
            done.set(); control.stop()

    @cap.event
    def on_closed():
        done.set()

    threading.Thread(target=cap.start, daemon=True).start()
    done.wait(240)
    log(d, f"exit phase={state['phase']}")


if __name__ == "__main__":
    main()
