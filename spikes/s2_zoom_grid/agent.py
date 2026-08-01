"""S-2 persistent elevated command agent.

One UAC approval -> long-lived WGC session bound to the target window,
then executes file-based commands until 'quit'. Spike only.

Protocol (in --dir):
  cmd_<NNNN>.txt  : one command per file, consumed in sequence order
  res_<NNNN>.txt  : result line written after execution
  agent_status.txt: lifecycle log

Commands:
  cap <filename.png>          save current frame to --dir/<filename>
  click <cx> <cy>             PostMessage click at client coords
  move <cx> <cy>              WM_MOUSEMOVE only
  wheel <delta> <cx> <cy> <n> n wheel notches (delta e.g. -120) at client coords
  sleep <seconds>             pause command processing
  quit                        stop agent
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time

from PIL import Image
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

TITLE = "삼국지-전략판 113.554"
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_MOUSEWHEEL, MK_LBUTTON = 0x20A, 1
CLIENT_OFFSET = (1, 32)  # window frame -> client area (measured in S-1)


def log(dirp, msg):
    with open(os.path.join(dirp, "agent_status.txt"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


class Agent:
    def __init__(self, hwnd: int, dirp: str):
        self.hwnd = hwnd
        self.dir = dirp
        self.seq = 1
        self.sleep_until = 0.0
        self.frame = None

    def screen_pos(self, cx: int, cy: int) -> tuple[int, int]:
        r = wt.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        return r.left + CLIENT_OFFSET[0] + cx, r.top + CLIENT_OFFSET[1] + cy

    def execute(self, line: str) -> str:
        parts = line.split()
        op = parts[0]
        if op == "cap":
            Image.fromarray(self.frame).save(os.path.join(self.dir, parts[1]))
            return f"cap {parts[1]} ok"
        if op in ("click", "move"):
            cx, cy = int(parts[1]), int(parts[2])
            lp = (cy << 16) | (cx & 0xFFFF)
            user32.PostMessageW(self.hwnd, WM_MOUSEMOVE, 0, lp)
            if op == "click":
                user32.PostMessageW(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
                user32.PostMessageW(self.hwnd, WM_LBUTTONUP, 0, lp)
            return f"{op} ({cx},{cy}) ok"
        if op == "wheel":
            delta, cx, cy, n = (int(v) for v in parts[1:5])
            sx, sy = self.screen_pos(cx, cy)
            clp = (cy << 16) | (cx & 0xFFFF)
            slp = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
            wp = (delta & 0xFFFF) << 16
            for _ in range(n):
                user32.PostMessageW(self.hwnd, WM_MOUSEMOVE, 0, clp)
                user32.PostMessageW(self.hwnd, WM_MOUSEWHEEL, wp, slp)
                time.sleep(0.06)
            return f"wheel {delta}x{n} at ({cx},{cy}) ok"
        if op == "sleep":
            self.sleep_until = time.time() + float(parts[1])
            return f"sleep {parts[1]} ok"
        if op == "quit":
            return "quit"
        return f"unknown command: {line}"

    def poll(self) -> bool:
        """Returns True when the agent should stop."""
        if time.time() < self.sleep_until:
            return False
        path = os.path.join(self.dir, f"cmd_{self.seq:04d}.txt")
        if not os.path.exists(path):
            return False
        try:
            line = open(path, encoding="utf-8").read().strip()
        except OSError:
            return False
        if not line:
            return False
        result = self.execute(line)
        with open(os.path.join(self.dir, f"res_{self.seq:04d}.txt"), "w",
                  encoding="utf-8") as f:
            f.write(result + "\n")
        log(self.dir, f"#{self.seq} {line} -> {result}")
        self.seq += 1
        return result == "quit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=int, required=True)
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    open(os.path.join(a.dir, "agent_status.txt"), "w").close()

    agent = Agent(a.hwnd, a.dir)
    log(a.dir, f"elevated={bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    rc = user32.SetWindowPos(a.hwnd, 0, 0, 0, 0, 0, 0x13)
    log(a.dir, f"SetWindowPos rc={rc}")

    done = threading.Event()
    cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=TITLE)

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        agent.frame = frame.frame_buffer[:, :, :3][:, :, ::-1].copy()
        if agent.poll():
            done.set()
            control.stop()

    @cap.event
    def on_closed():
        log(a.dir, "capture closed")
        done.set()

    threading.Thread(target=cap.start, daemon=True).start()
    log(a.dir, "ready")
    done.wait(1800)  # 30분 상한
    log(a.dir, "exit")


if __name__ == "__main__":
    main()
