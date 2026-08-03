"""WgcCapture 프레임 생동 감지 (DCR-006 / AC-D4).

캡처 세션을 띄우지 않고 프레임 슬롯만 조작해 grab_fresh의 시간 초과 계수를
검증한다 — 실제 WGC 세션은 실기 검증(AC-D1) 몫이다.
"""

import threading
import unittest
from unittest import mock

import numpy as np

from mapscan.win.capture import STALE_LIMIT, CaptureStalled, WgcCapture


def _capture_with_frame() -> WgcCapture:
    cap = WgcCapture(0)   # __init__은 세션을 시작하지 않는다
    cap._frame = np.zeros((2, 2, 3), dtype=np.uint8)
    return cap


class GrabFreshStaleTest(unittest.TestCase):
    def test_raises_after_consecutive_timeouts(self):
        cap = _capture_with_frame()
        stale = cap._frame
        for i in range(STALE_LIMIT - 1):
            # 임계 직전까지는 낡은 프레임을 돌려주되 계수한다
            self.assertIs(cap.grab_fresh(timeout=0.01), stale)
            self.assertEqual(cap._stale, i + 1)
        with self.assertRaises(CaptureStalled):
            cap.grab_fresh(timeout=0.01)

    def test_fresh_frame_resets_counter(self):
        cap = _capture_with_frame()
        cap.grab_fresh(timeout=0.01)
        self.assertEqual(cap._stale, 1)

        fresh = np.ones((2, 2, 3), dtype=np.uint8)
        timer = threading.Timer(0.02, lambda: setattr(cap, "_frame", fresh))
        timer.start()
        self.addCleanup(timer.cancel)
        self.assertIs(cap.grab_fresh(timeout=2.0), fresh)
        self.assertEqual(cap._stale, 0)

        # 초기화된 뒤에는 다시 임계만큼 버틴다(단발 지연이 중단을 부르지 않는다)
        for _ in range(STALE_LIMIT - 1):
            cap.grab_fresh(timeout=0.01)


class StopTeardownTest(unittest.TestCase):
    """대상이 사라진 뒤의 세션 정리 실패가 종료 경로를 덮지 않아야 한다.

    2026-08-04 사고에서 `DXGI_ERROR_DEVICE_REMOVED`가 `__exit__`에서 터져
    정상 중단이 크래시로 보고됐다.
    """

    def test_stop_swallows_backend_failure(self):
        class _Control:
            def stop(self):
                raise Exception("Windows capture error: GPU 장치 인스턴스 중단")

        cap = _capture_with_frame()
        cap._control = _Control()
        cap.stop()   # 예외가 밖으로 나오면 실패

    def test_context_exit_survives_backend_failure(self):
        class _Control:
            def stop(self):
                raise Exception("device removed")

        cap = _capture_with_frame()
        cap._control = _Control()
        with mock.patch.object(WgcCapture, "start", lambda self: None):
            with cap:
                pass


if __name__ == "__main__":
    unittest.main()
