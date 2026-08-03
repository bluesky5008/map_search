"""Windows Graphics Capture — 가림 상태에서도 프레임을 얻는다 (ADR-002, S-1a).

동일 제목 창이 여럿이면 제목 매칭은 z순서에 따라 다른 창을 잡는다(S-1 실측).
`windows-capture` 2.x의 `window_hwnd`로 **HWND에 직접 바인딩**한다. 크기 검증은
같은 크기의 두 창을 구분하지 못하므로(T12 실측 — 제목 매칭 + z-raise 방식이
조용히 다른 창을 잡아 실기 조작이 화면에 반영되지 않았다) 보조 수단일 뿐이다.
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
STALE_LIMIT = 3      # grab_fresh 연속 시간 초과 허용 횟수 → 초과 시 CaptureStalled


class CaptureStalled(RuntimeError):
    """대상의 렌더링이 멈춰 새 프레임이 오지 않는다 (DCR-006).

    GPU 드라이버 리셋으로 에뮬레이터가 사망했을 때 `grab_fresh`가 낡은 프레임을
    조용히 돌려주는 바람에 스캔이 3~4시간을 헛돌았다(2026-08-04 사고). 재시도로
    살아나지 않는 상태이므로 행 단위 복구 대상이 아니다 — 스캔을 중단시킨다.
    """


class WgcCapture:
    """대상 창의 최신 프레임을 보관하는 상시 캡처 세션."""

    def __init__(self, hwnd: int, title: str = ""):
        self.hwnd = hwnd
        self.title = title  # 로그·진단용 (바인딩은 HWND로 한다)
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._control = None  # CaptureControl (start_free_threaded)
        self._stale = 0       # grab_fresh 연속 시간 초과 횟수 (DCR-006)

    def start(self, timeout: float = 10.0) -> None:
        # 세션은 반드시 start_free_threaded(러스트 관리 스레드)로 돌린다.
        # 파이썬 스레드에서 blocking start()로 돌리면 세션이 살아 있는 동안
        # 메인 스레드의 CPU 작업이 4~5배 느려진다(T14 실측: 분류 6ms → 31ms/셀
        # — NFR-02 처리율 저하의 주원인. free-threaded에서는 6.8ms로 동일).
        capture = WindowsCapture(cursor_capture=False, draw_border=False,
                                 window_hwnd=self.hwnd)

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

        try:
            self._control = capture.start_free_threaded()
        except BaseException as exc:
            raise RuntimeError(f"캡처 세션 시작 실패: {exc}")
        if not self._ready.wait(timeout):
            raise RuntimeError(f"캡처 첫 프레임 시간 초과 ({timeout}s)")
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
        """현재 프레임 이후 새로 도착한 프레임을 반환한다.

        시간 초과 시 낡은 프레임을 돌려주되 연속 횟수를 세고, `STALE_LIMIT`을
        넘으면 `CaptureStalled`를 던진다 — 렌더링이 죽은 상태에서 조용히 낡은
        프레임을 계속 돌려주면 호출자가 정상으로 오인한다(DCR-006).
        """
        with self._lock:
            previous = self._frame
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                current = self._frame
            if current is not None and current is not previous:
                self._stale = 0
                return current
            time.sleep(0.01)
        self._stale += 1
        if self._stale >= STALE_LIMIT:
            raise CaptureStalled(
                f"캡처 프레임 정지 — 새 프레임 없이 {self._stale}회 연속 시간 초과"
                f"({self._stale * timeout:.0f}s). 대상 창 종료·렌더링 중단"
                "(GPU 리셋 등)을 확인하세요.")
        log.warning("캡처 프레임 시간 초과 %.1fs (%d/%d) — 낡은 프레임 사용",
                    timeout, self._stale, STALE_LIMIT)
        return self.grab()

    def stop(self) -> None:
        """세션을 정리한다. 정리 실패는 삼킨다 — 이미 끝내는 중이다.

        대상 창이 사라지거나 GPU가 제거된 상태에서 세션을 멈추면 백엔드가
        예외를 던진다(2026-08-04 사고: `DXGI_ERROR_DEVICE_REMOVED`). 그 예외가
        스캔 종료 경로를 덮어 정상 중단(종료 코드 2)이 크래시로 둔갑했다.
        """
        self._stop.set()
        if self._control is not None:
            try:
                self._control.stop()
            except Exception as exc:
                log.warning("캡처 세션 정리 실패(무시): %s", exc)

    def __enter__(self) -> "WgcCapture":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
