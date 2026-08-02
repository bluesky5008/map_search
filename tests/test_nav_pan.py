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

    def test_wide_pan_far_from_last_but_near_gain_is_kept(self):
        """행 150 실기 회귀: 팬별 이동이 직전 팬에서 150px 넘게 벗어나도
        게인 기대 근방이고 상호 정합하면 유효하다(이중 앵커, T14 튜닝).

        광폭 팬은 새 콘텐츠가 우측에서 진입하므로(역방향 매칭) 프레임을
        파노라마에서 창으로 잘라 만든다 — 같은 프레임을 두 번 밀면 콘텐츠가
        전부 화면 밖으로 나가 검은 영역이 오매칭된다."""
        pano_w = W + 4500
        coarse = RNG.integers(0, 255, size=(H // 8 + 2, pano_w // 8 + 2, 3),
                              dtype=np.uint8)
        pano = cv2.resize(coarse, (pano_w, H), interpolation=cv2.INTER_LINEAR)

        def window(s_a: float, s_b: float) -> np.ndarray:
            out = np.zeros((H, W, 3), dtype=pano.dtype)
            for y in range(H):
                s = int(round(s_a + s_b * y))
                out[y] = pano[y, s:s + W]
            return out

        f0 = window(0, 0)
        f1 = window(1580, 0.4)          # dx(y) = -1580-0.4y, |측정-게인| 15~104px
        f2 = window(1580 + 1740, 0.8)   # 팬별 이동 변동 160px (직전±150 창 밖)
        tracker = PanTracker(OFFSET)
        tracker.update(f0, f1, -1900)
        info = tracker.update(f1, f2, -1900)  # 구 규칙(직전 단일 앵커)은 TrackLost
        self.assertEqual(info["rejected"], [], info)
        want = (-1580 - 0.4 * 366) + (-1740 - 0.4 * 366)
        self.assertLess(abs(tracker.shift_at(366) - want), 8.0, info)


if __name__ == "__main__":
    unittest.main()
