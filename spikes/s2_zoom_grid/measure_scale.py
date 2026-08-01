"""Measure map render scale between two captures of different window sizes.

Takes a patch from the small capture, rescales it over a range, and finds the
scale that best matches inside the large capture. Scale ~1.0 means the game
keeps tile pixel size (bigger window => more tiles visible); scale ~ window
ratio means the view is simply magnified (same tiles).
"""

import sys

import cv2
import numpy as np

small_path, large_path = sys.argv[1], sys.argv[2]
small = cv2.imread(small_path)
large = cv2.imread(large_path)
print(f"small={small.shape[1]}x{small.shape[0]}  large={large.shape[1]}x{large.shape[0]}")
print(f"window width ratio = {large.shape[1] / small.shape[1]:.3f}")

# Map-content patches (avoid HUD/panels): x, y, w, h in the small capture.
PATCHES = [
    ("castle-core", 430, 300, 320, 200),
    ("mint-area", 300, 420, 260, 180),
    ("field-left", 120, 300, 220, 160),
]

for name, x, y, w, h in PATCHES:
    patch = small[y:y + h, x:x + w]
    best = (0.0, None)
    for scale in np.arange(1.00, 2.30, 0.01):
        rw, rh = int(w * scale), int(h * scale)
        if rw >= large.shape[1] or rh >= large.shape[0]:
            break
        resized = cv2.resize(patch, (rw, rh), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(large, resized, cv2.TM_CCOEFF_NORMED)
        score = res.max()
        if score > best[0]:
            best = (score, scale, cv2.minMaxLoc(res)[3])
    print(f"{name:12s} best scale={best[1]:.2f} score={best[0]:.3f} at {best[2]}")
