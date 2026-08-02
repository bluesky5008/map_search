"""세션 1개·콜백 소비 방식별 classify 비용 (프로세스 격리 — 세션 중첩 배제).

--mode copy    : 제품 방식(매 콜백 5.3MB 슬라이스·역순·copy)
--mode skip    : 콜백 즉시 반환(버퍼 미소비)
--mode touch   : 버퍼 1픽셀만 접근
--mode ondemand: 평소 touch, 요청 시에만 copy (0.5s마다 1회 요청 모사)
"""
import argparse
import sys
import threading
import time

import numpy as np
from PIL import Image
from windows_capture import WindowsCapture

sys.path.insert(0, r"C:\src\git\map_search\src")
from mapscan.vision import TileClassifier

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ap = argparse.ArgumentParser()
ap.add_argument("--mode", required=True)
ap.add_argument("--hwnd", type=lambda s: int(s, 0), default=0x60042)
args = ap.parse_args()

frame = np.asarray(Image.open(
    r"C:\src\git\map_search\spikes\t14_pan_tuning\work\tiles_occ_frame.png").convert("RGB"))
clf = TileClassifier()
n = [0]
want = threading.Event()
stored = [None]

cap = WindowsCapture(cursor_capture=False, draw_border=False,
                     window_hwnd=args.hwnd)


@cap.event
def on_frame_arrived(f, control):
    n[0] += 1
    if args.mode == "copy":
        stored[0] = f.frame_buffer[:, :, :3][:, :, ::-1].copy()
    elif args.mode == "touch":
        stored[0] = int(f.frame_buffer[0, 0, 0])
    elif args.mode == "ondemand":
        if want.is_set():
            stored[0] = f.frame_buffer[:, :, :3][:, :, ::-1].copy()
            want.clear()
        else:
            _ = int(f.frame_buffer[0, 0, 0])


@cap.event
def on_closed():
    pass


control = cap.start_free_threaded()
time.sleep(1.5)


def poker():
    while not control.is_finished():
        want.set()
        time.sleep(0.5)


if args.mode == "ondemand":
    threading.Thread(target=poker, daemon=True).start()

n0, t0 = n[0], time.monotonic()
total = 0.0
cells = 0
while time.monotonic() - t0 < 6.0:
    t1 = time.monotonic()
    clf.classify(frame, 600 + (cells % 20) * 30, 250 + (cells % 5) * 30)
    total += time.monotonic() - t1
    cells += 1
fps = (n[0] - n0) / (time.monotonic() - t0)
print(f"mode={args.mode}: classify {total / cells * 1000:.1f}ms/셀 "
      f"({cells}셀), 콜백 {fps:.0f}fps")
control.stop()
