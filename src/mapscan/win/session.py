"""대상 창 확정과 스캔 창 크기 관리 (설계 §2, §4.1 / FR-12, ADR-005).

스캔 시작 시 창을 넓고 낮은 스캔 크기로 설정하고, 종료·중단·오류 어느 경로에서도
원래 위치·크기로 복원한다(AC-07).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import win32

log = logging.getLogger(__name__)

TITLE_SUBSTR = "삼국지-전략판"
MIN_SCAN_ASPECT = 3.0
# 원래 창 배치의 영속 기록 — 강제 종료(taskkill 등)로 restore()가 못 돈 경우
# 다음 실행이 스캔 배치를 '원래 배치'로 오인해 사용자 배치가 유실된다(T14 실기).
_STATE_DIR = Path("output")


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    rect: tuple[int, int, int, int]      # left, top, width, height
    client: tuple[int, int]              # width, height
    elevated: bool | None


def find_client_windows(title_substr: str = TITLE_SUBSTR) -> list[WindowInfo]:
    """제목에 부분 문자열이 포함된 보이는 창을 모두 반환한다."""
    found: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        if not win32.user32.IsWindowVisible(hwnd) or win32.user32.IsIconic(hwnd):
            return True
        title = win32.window_text(hwnd)
        if title_substr not in title:
            return True
        pid = win32.process_id(hwnd)
        found.append(WindowInfo(
            hwnd=hwnd, title=title, pid=pid,
            rect=win32.window_rect(hwnd), client=win32.client_size(hwnd),
            elevated=win32.is_process_elevated(pid)))
        return True

    win32.user32.EnumWindows(callback, 0)
    return found


@dataclass(frozen=True)
class MuMuInstance:
    """MuMu 인스턴스의 캡처·입력 대상 (DCR-005, S-7 실측).

    WGC 캡처는 top(Qt 창)만 가능하고, PostMessage 입력은 MuMuNxDevice가
    받는다(nemudisplay는 무반응). 자식 클라이언트 크기 = 에뮬레이터 내부
    해상도(1:1)이므로 창 리사이즈(apply_scan_rect)는 금지다.
    """
    title: str                    # 인스턴스명(창 제목, 예: '용스')
    top: int                      # 캡처 대상 HWND (Qt top)
    device: int                   # 입력 대상 HWND (MuMuNxDevice)
    display: int                  # nemudisplay (구조 판별용)
    client: tuple[int, int]       # device 클라이언트 = 게임 해상도


def _mumu_from_top(top: int) -> MuMuInstance | None:
    """창 구조로 MuMu 인스턴스를 판별한다 — 제목 필터는 미검출(인스턴스명이
    제목)이라 Qt top + MuMuNxDevice/nemudisplay 자식 구조를 쓴다(S-7)."""
    if not win32.window_class(top).startswith("Qt"):
        return None
    by_title: dict[str, int] = {}
    for child in win32.child_windows(top):
        by_title.setdefault(win32.window_text(child), child)
    device = by_title.get("MuMuNxDevice")
    display = by_title.get("nemudisplay")
    if device is None or display is None:
        return None
    return MuMuInstance(title=win32.window_text(top), top=top, device=device,
                        display=display, client=win32.client_size(device))


def find_mumu_instances() -> list[MuMuInstance]:
    found = [_mumu_from_top(h) for h in win32.visible_top_windows()]
    return [i for i in found if i is not None]


def find_mumu_instance(title: str,
                       expect_client: tuple[int, int] | None = None) -> MuMuInstance:
    """인스턴스명으로 하나를 확정한다. expect_client가 주어지면 내부 해상도가
    일치해야 한다 — 불일치는 스케일링(1:1 파괴) 상태이므로 명시적으로 막는다."""
    found = find_mumu_instances()
    matched = [i for i in found if i.title == title]
    if not matched:
        names = ", ".join(i.title for i in found) or "(없음)"
        raise RuntimeError(f"MuMu 인스턴스 '{title}'를 찾을 수 없습니다. 발견: {names}")
    if len(matched) > 1:
        raise RuntimeError(f"같은 이름의 MuMu 인스턴스가 {len(matched)}개입니다: '{title}'")
    inst = matched[0]
    if expect_client is not None and inst.client != expect_client:
        raise RuntimeError(
            f"MuMu '{title}' 내부 해상도 {inst.client[0]}x{inst.client[1]} ≠ "
            f"기대 {expect_client[0]}x{expect_client[1]} — 에뮬레이터 해상도를 "
            f"맞추세요(창 리사이즈로 보정하면 1:1이 깨져 금지).")
    return inst


class PermissionError_(RuntimeError):
    """게임이 상승 권한으로 실행 중인데 도구는 아닌 경우."""


def quadrant_scan_rect(hwnd: int) -> tuple[int, int, int, int]:
    """대상 모니터 작업 영역의 우상단 사분면 (넓고 낮은 종횡비, ADR-005)."""
    left, top, width, height = win32.work_area(hwnd)
    half_w, half_h = width // 2, height // 2
    return left + half_w, top, half_w, half_h


class WindowSession:
    """대상 창의 수명주기: 확정 → 스캔 크기 설정 → (스캔) → 복원."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self._original_rect: tuple[int, int, int, int] | None = None

    @classmethod
    def attach(cls, hwnd: int | None = None,
               title_substr: str = TITLE_SUBSTR) -> "WindowSession":
        """HWND를 직접 지정하거나, 후보가 정확히 하나일 때 자동 선택한다.

        같은 제목의 창이 여러 개면 제목 기반 선택이 불안정하므로(S-1 실측)
        호출자가 HWND를 지정해야 한다.
        """
        if hwnd is None:
            candidates = find_client_windows(title_substr)
            if not candidates:
                raise RuntimeError(f"대상 창을 찾을 수 없습니다: '{title_substr}'")
            if len(candidates) > 1:
                listed = ", ".join(f"{c.hwnd:#x}(pid {c.pid})" for c in candidates)
                raise RuntimeError(
                    f"같은 제목의 창이 {len(candidates)}개입니다. --hwnd로 지정하세요: {listed}")
            hwnd = candidates[0].hwnd
        session = cls(hwnd)
        session.check_permission()
        return session

    def info(self) -> WindowInfo:
        pid = win32.process_id(self.hwnd)
        return WindowInfo(
            hwnd=self.hwnd, title=win32.window_text(self.hwnd), pid=pid,
            rect=win32.window_rect(self.hwnd), client=win32.client_size(self.hwnd),
            elevated=win32.is_process_elevated(pid))

    def check_permission(self) -> None:
        """게임이 elevated인데 도구가 아니면 UIPI가 입력·창 조작을 차단한다(S-1)."""
        target = win32.is_process_elevated(win32.process_id(self.hwnd))
        if target and not win32.is_self_elevated():
            raise PermissionError_(
                "게임이 관리자 권한으로 실행 중입니다. "
                "이 도구도 관리자 권한으로 실행해야 입력과 창 조작이 전달됩니다.")

    def apply_scan_rect(self, rect: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
        """스캔 창 크기를 적용하고 실제 클라이언트 크기를 반환한다.

        원래 위치·크기를 기억해 두었다가 restore()에서 복원한다.
        """
        if self._original_rect is None:
            state = self._state_path()
            if state.is_file():
                # 직전 실행이 강제 종료돼 복원하지 못한 원래 배치를 이어받는다
                try:
                    self._original_rect = tuple(
                        json.loads(state.read_text(encoding="utf-8")))
                    log.info("이전 실행의 미복원 원래 배치 인계: %s",
                             self._original_rect)
                except (ValueError, OSError):
                    self._original_rect = win32.window_rect(self.hwnd)
            else:
                self._original_rect = win32.window_rect(self.hwnd)
                try:
                    state.parent.mkdir(parents=True, exist_ok=True)
                    state.write_text(json.dumps(list(self._original_rect)),
                                     encoding="utf-8")
                except OSError:
                    pass   # 기록 실패는 복원 기능 자체를 막지 않는다
        x, y, w, h = rect if rect else quadrant_scan_rect(self.hwnd)
        if not win32.set_window_rect(self.hwnd, x, y, w, h):
            raise RuntimeError(f"창 크기 설정 실패 (err={win32.last_error()})")
        client = win32.client_size(self.hwnd)
        aspect = client[0] / client[1] if client[1] else 0
        if aspect < MIN_SCAN_ASPECT:
            log.warning("스캔 창 종횡비 %.2f < %.1f — 가시 타일 수가 줄어 스캔이 느려집니다",
                        aspect, MIN_SCAN_ASPECT)
        log.info("스캔 창 설정: %dx%d at (%d,%d), client=%dx%d, aspect=%.2f",
                 w, h, x, y, client[0], client[1], aspect)
        return client

    def _state_path(self) -> Path:
        return _STATE_DIR / f"winstate_{self.hwnd:#x}.json"

    def restore(self) -> bool:
        """원래 창 배치로 복원한다. 실패해도 예외를 던지지 않고 기록만 남긴다."""
        if self._original_rect is None:
            return True
        x, y, w, h = self._original_rect
        ok = win32.set_window_rect(self.hwnd, x, y, w, h)
        if ok:
            self._original_rect = None
            try:
                self._state_path().unlink(missing_ok=True)
            except OSError:
                pass
            log.info("창 배치 복원: %dx%d at (%d,%d)", w, h, x, y)
        else:
            log.error("창 배치 복원 실패 (err=%d) — 원래 배치 %dx%d at (%d,%d)",
                      win32.last_error(), w, h, x, y)
        return ok

    def __enter__(self) -> "WindowSession":
        return self

    def __exit__(self, *exc) -> None:
        self.restore()
