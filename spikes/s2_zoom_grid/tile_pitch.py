"""Estimate isometric tile pitch (px) from a map screenshot via row autocorrelation.

Uses a horizontal band of open field, removes low-frequency shading, and reports
the dominant repeat distance — i.e. the horizontal tile pitch in pixels.
"""

import sys

import cv2
import numpy as np


def pitch(path: str, band: tuple[float, float], xrange: tuple[float, float]) -> None:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    h, w = img.shape
    y0, y1 = int(h * band[0]), int(h * band[1])
    x0, x1 = int(w * xrange[0]), int(w * xrange[1])
    strip = img[y0:y1, x0:x1].astype(np.float32)

    sig = strip.mean(axis=0)
    sig -= cv2.GaussianBlur(sig.reshape(1, -1), (0, 0), 25).ravel()  # detrend
    sig -= sig.mean()

    ac = np.correlate(sig, sig, mode="full")[len(sig) - 1:]
    ac /= ac[0]
    lo, hi = 30, min(600, len(ac) - 1)
    peak = lo + int(np.argmax(ac[lo:hi]))
    print(f"{path}\n  size={w}x{h} band=y[{y0}:{y1}] x[{x0}:{x1}]"
          f"  dominant pitch={peak}px  corr={ac[peak]:.3f}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        pitch(p, (0.55, 0.75), (0.05, 0.45))
