"""이상 화면 감지 (설계 §2 Watchdog, §4.4 / NFR-03) — v1 최소 구현.

화면 상태 검증(지도 모드·디테일 뷰)은 Navigator가 조작 직전에 수행하므로,
여기서는 캡처 자체의 이상(검은 프레임·크기 변경)만 검사한다. 복구 정책
(재시도 → 행 재앵커 → 체크포인트 저장 후 안전 정지)은 컨트롤러가 갖는다.
"""

from __future__ import annotations

import numpy as np

_BLACK_MEAN = 3.0


class WatchdogAlert(RuntimeError):
    """복구 루틴이 필요한 이상 화면."""


class Watchdog:
    def __init__(self, expected_shape: tuple[int, ...] | None = None):
        self.expected_shape = expected_shape

    def check(self, frame: np.ndarray) -> None:
        if frame is None or frame.size == 0:
            raise WatchdogAlert("빈 프레임")
        if self.expected_shape is None:
            self.expected_shape = frame.shape
        elif frame.shape != self.expected_shape:
            raise WatchdogAlert(
                f"프레임 크기 변경: {frame.shape} != {self.expected_shape}")
        if float(frame.mean()) < _BLACK_MEAN:
            raise WatchdogAlert("검은 프레임 — 캡처 세션 이상(S-1a)")
