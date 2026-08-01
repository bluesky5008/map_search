"""Windows Graphics Capture — 가림 상태에서도 프레임을 얻는다 (ADR-002, S-1a).

`windows-capture`는 창을 제목으로만 매칭하므로, 동일 제목 창이 여럿이면 z순서에
따라 다른 창이 선택된다(S-1 실측). 세션 시작 직전 대상 HWND를 z 최상단으로 올려
바인딩을 확정하고, 첫 프레임 크기를 대상 창과 대조해 검증한다.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
from windows_capture import Frame, InternalCaptureControl, WindowsCapture

from . import win32

log = logging.getLogger(__name__)

BIND_TOLERANCE = 24  # WGC 프레임과 창 외곽 크기의 허용 오차(px)


class WgcCapture:
    """대상 창의 최신 프레임을 보관하는 상시 캡처 세션."""

    def __init__(self, hwnd: int, title: str):
        self.hwnd = hwnd
        self.title = title
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 10.0) -> None:
        win32.raise_to_top(self.hwnd)
        capture = WindowsCapture(cursor_capture=False, draw_border=False,
                                 window_name=self.title)

        @capture.event
        def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
            with self._lock:
                self._frame = frame.frame_buffer[:, :, :3][:, :, ::-1].copy()
            self._ready.set()
            if self._stop.is_set():
                control.stop()

        @capture.event
        def on_closed():
            self._stop.set()
            self._ready.set()

        def run():
            try:
                capture.start()
            except BaseException as exc:  # 세션 스레드의 예외를 호출자에게 전달
                self._error = exc
                self._ready.set()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError(f"캡처 첫 프레임 시간 초과 ({timeout}s)")
        if self._error is not None:
            raise RuntimeError(f"캡처 세션 시작 실패: {self._error}")
        self._verify_binding()

    def _verify_binding(self) -> None:
        """첫 프레임 크기를 대상 창과 대조해 다른 창을 잡지 않았는지 확인한다."""
        frame = self.grab()
        _, _, win_w, win_h = win32.window_rect(self.hwnd)
        dw, dh = abs(frame.shape[1] - win_w), abs(frame.shape[0] - win_h)
        if dw > BIND_TOLERANCE or dh > BIND_TOLERANCE:
            raise RuntimeError(
                f"캡처 대상 불일치: 프레임 {frame.shape[1]}x{frame.shape[0]} vs "
                f"창 {win_w}x{win_h}. 같은 제목의 다른 창이 선택되었을 수 있습니다.")
        log.info("캡처 바인딩 확인: %dx%d", frame.shape[1], frame.shape[0])

    def grab(self) -> np.ndarray:
        """최신 프레임(RGB, HxWx3)을 반환한다."""
        with self._lock:
            if self._frame is None:
                raise RuntimeError("아직 프레임이 없습니다. start()를 먼저 호출하세요.")
            return self._frame

    def grab_fresh(self, timeout: float = 2.0) -> np.ndarray:
        """현재 프레임 이후 새로 도착한 프레임을 반환한다."""
        with self._lock:
            previous = self._frame
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                current = self._frame
            if current is not None and current is not previous:
                return current
            time.sleep(0.01)
        return self.grab()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def __enter__(self) -> "WgcCapture":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
