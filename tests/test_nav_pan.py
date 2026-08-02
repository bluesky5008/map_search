"""PanTracker 전단 추적 — 합성 프레임으로 적합·기각·손실 경로를 검증한다."""

import unittest

import cv2
import numpy as np

from mapscan.nav import ui
from mapscan.nav.pan import PanTracker, TrackLost, pan_gain

OFFSET = (1, 31)
W, H = 2546, 689
RNG = np.random.default_rng(7)


def textured_frame() -> np.ndarray:
    """부드러운 무작위 텍스처 — 실제 지형처럼 밴드 내 전단 어긋남(수십 px)에도
    NCC 상관이 유지되도록 저주파 성분으로 만든다(픽셀 노이즈는 상관이 무너진다)."""
    coarse = RNG.integers(0, 255, size=(H // 8 + 2, W // 8 + 2, 3), dtype=np.uint8)
    return cv2.resize(coarse, (W, H), interpolation=cv2.INTER_LINEAR)


def shear_shift(frame: np.ndarray, a: float, b: float) -> np.ndarray:
    """행(y)마다 x로 a + b·y 픽셀 이동시킨 프레임(전단 이동장 모사)."""
    out = np.zeros_like(frame)
    for y in range(H):
        dx = int(round(a + b * y))
        if dx >= 0:
            out[y, dx:] = frame[y, :W - dx] if dx else frame[y]
        else:
            out[y, :W + dx] = frame[y, -dx:]
    return out


class PanTrackerTest(unittest.TestCase):
    def test_recovers_linear_shift(self):
        base = textured_frame()
        a_true, b_true = -300.0, -0.5   # y=344에서 약 -472 (전단)
        cur = shear_shift(base, a_true, b_true)
        tracker = PanTracker(OFFSET)
        info = tracker.update(base, cur, -520)
        got = tracker.shift_at(344.5)
        want = a_true + b_true * 344.5
        self.assertLess(abs(got - want), 6.0, info)
        self.assertEqual(info["rejected"], [])

    def test_accumulates_over_pans(self):
        base = textured_frame()
        f1 = shear_shift(base, -440, -0.1)
        f2 = shear_shift(f1, -440, -0.1)
        tracker = PanTracker(OFFSET)
        tracker.update(base, f1, -520)
        tracker.update(f1, f2, -520)
        want = 2 * (-440 - 0.1 * 300)
        self.assertLess(abs(tracker.shift_at(300) - want), 5.0)

    def test_rejects_corrupted_band_via_fit_residual(self):
        base = textured_frame()
        cur = shear_shift(base, -440, -0.1)
        # 상단 추적 밴드만 어긋난 위치로 오염 → leave-one-out 검정이 잡아야 한다
        y0, h = ui.TRACK_BANDS[0]
        corrupt = cur.copy()
        band = slice(y0 + OFFSET[1] - 12, y0 + h + OFFSET[1] + 12)
        corrupt[band] = np.roll(cur[band], 100, axis=1)
        tracker = PanTracker(OFFSET)
        info = tracker.update(base, corrupt, -520)
        self.assertIn(0, info["rejected"])
        want = -440 - 0.1 * 380
        self.assertLess(abs(tracker.shift_at(380) - want), 8.0, info)

    def test_track_lost_when_shift_far_from_expectation(self):
        base = textured_frame()
        # 기대(-444±허용창)에서 멀리 벗어난 이동 → 전 밴드 기각 → TrackLost
        cur = shear_shift(base, -150, 0.0)
        tracker = PanTracker(OFFSET)
        with self.assertRaises(TrackLost):
            tracker.update(base, cur, -520)

    def test_gain_interpolation_matches_s5(self):
        self.assertAlmostEqual(pan_gain(127), 0.853, places=3)
        self.assertAlmostEqual(pan_gain(466), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
