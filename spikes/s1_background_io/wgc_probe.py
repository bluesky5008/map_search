"""S-1 spike: Windows Graphics Capture one-shot frame grab.

Usage:
  wgc_probe.py --title "삼국지-전략판 113.554" --out frame.png [--timeout 5]

Grabs the first arriving frame of the named window and saves it as PNG.
Works while the window is occluded (not minimized). Spike only.
"""

import argparse
import sys
import threading

from PIL import Image
from windows_capture import WindowsCapture, Frame, InternalCaptureControl


def grab(title: str, out: str, timeout: float) -> int:
    done = threading.Event()
    result = {}

    cap = WindowsCapture(cursor_capture=False, draw_border=False, window_name=title)

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        if not done.is_set():
            buf = frame.frame_buffer  # HxWx4 BGRA ndarray
            img = Image.fromarray(buf[:, :, :3][:, :, ::-1])  # -> RGB
            img.save(out)
            g = img.convert("L")
            hist = g.histogram()
            total = img.width * img.height
            result["mean"] = sum(i * c for i, c in enumerate(hist)) / total
            result["nonblack"] = 100.0 * (total - sum(hist[:8])) / total
            result["size"] = (img.width, img.height)
            done.set()
            control.stop()

    @cap.event
    def on_closed():
        done.set()

    t = threading.Thread(target=cap.start, daemon=True)
    t.start()
    if not done.wait(timeout):
        print("FAIL: no frame within timeout")
        return 2
    if not result:
        print("FAIL: capture session closed without frame")
        return 2
    print(f"WGC frame size={result['size']} mean={result['mean']:.1f} "
          f"nonblack={result['nonblack']:.1f}% -> {out}")
    return 0 if result["nonblack"] > 5 else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="삼국지-전략판 113.554")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=5.0)
    a = ap.parse_args()
    sys.exit(grab(a.title, a.out, a.timeout))
