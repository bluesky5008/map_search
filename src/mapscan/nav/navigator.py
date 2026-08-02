"""화면 이동·안정화·맵 크기 감지 (설계 §2 Navigator, §4.1~4.3 / FR-01, FR-02).

좌표계 규약: 입력(click/type)은 클라이언트 좌표, 캡처 프레임은 창 전체(제목
표시줄 포함)다. 변환은 frame_client_offset()으로 한다.

**안전 규칙(T12 실기 사고로 도입):** 지도 모드 UI를 조작하기 전에 매번 프레임에서
지도 모드를 확인한다. 지도 모드가 아닐 때 같은 좌표를 클릭하면 선택 팝업의
'점령·행군' 같은 되돌릴 수 없는 버튼을 누를 수 있다(S-2 발견 #5로 예견,
T12에서 실제 발생 — ESC로 취소).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..vision import GridBasis, GridMapper
from . import ui

log = logging.getLogger(__name__)

MAP_MODE_TEMPLATE = (Path(__file__).resolve().parents[3]
                     / "assets" / "templates" / "ui" / "map_mode.png")

_DIFF_PER_PIXEL = 12     # 픽셀이 "변했다"고 보는 채널 합 차이
_STABLE_FRACTION = 0.05  # 변한 픽셀 비율이 이 미만이면 정지 프레임
_JUMP_ANIM_SETTLE_S = 1.2  # 안정화 불가 지역(수면 애니메이션)의 점프 후 고정 대기
_FIELD_MAX_DIGITS = 12   # 입력란을 비울 때 보낼 백스페이스 수
VK_BACK, VK_END = 0x08, 0x23

# ESC는 쓰지 않는다: 일반 뷰에서 누르면 "게임을 종료하시겠습니까?" 확인 창이
# 뜬다(T12 실측). 팝업 닫기가 필요하면 팝업의 X 버튼을 프레임에서 찾아 누른다.


class NotInMapMode(RuntimeError):
    """지도 모드가 아니어서 좌표 UI 조작을 중단했다(오클릭 방지)."""


class NotDetailView(RuntimeError):
    """디테일 뷰 시그니처 불일치 — 드래그·클릭을 중단했다(오조작 방지, R-10)."""


class StabilizeTimeout(RuntimeError):
    """화면이 제한 시간 안에 안정되지 않았다(설계 §4.4 재시도 대상)."""


class Navigator:
    def __init__(self, capture, input_, basis: GridBasis = GridBasis(),
                 ui_cfg=ui, map_mode_template: np.ndarray | None = None):
        self.capture = capture      # grab_fresh() -> RGB 프레임
        self.input = input_         # click/key/type_text (클라이언트 좌표)
        self.basis = basis
        self.ui = ui_cfg
        if map_mode_template is None and MAP_MODE_TEMPLATE.exists():
            map_mode_template = np.asarray(Image.open(MAP_MODE_TEMPLATE).convert("RGB"))
        self._map_mark = map_mode_template

    # -- 프레임 상태 -------------------------------------------------------

    def client_offset(self, frame: np.ndarray) -> tuple[int, int]:
        return frame_client_offset(frame.shape, self.ui.CLIENT_SIZE)

    def crop_client(self, frame: np.ndarray,
                    rect: tuple[int, int, int, int]) -> np.ndarray:
        ox, oy = self.client_offset(frame)
        x0, y0, x1, y1 = rect
        return frame[y0 + oy:y1 + oy, x0 + ox:x1 + ox]

    def map_mode_score(self, frame: np.ndarray) -> float:
        if self._map_mark is None:
            raise FileNotFoundError(f"지도 모드 템플릿이 없습니다: {MAP_MODE_TEMPLATE}")
        crop = self.crop_client(frame, self.ui.MAP_MODE_MARK)
        if crop.shape[:2] != self._map_mark.shape[:2]:
            return 0.0
        return float(cv2.matchTemplate(crop, self._map_mark, cv2.TM_CCOEFF_NORMED)[0, 0])

    def is_map_mode(self, frame: np.ndarray) -> bool:
        return self.map_mode_score(frame) >= self.ui.MAP_MODE_THRESHOLD

    # -- 안정화 ------------------------------------------------------------

    def wait_stable(self, timeout: float = 6.0, min_still: int = 2,
                    fraction: float = _STABLE_FRACTION) -> np.ndarray:
        """연속 프레임 변화율이 임계 미만인 상태가 min_still회 이어질 때까지 대기.

        게임은 상시 애니메이션이 있어 변화율 0은 나오지 않는다. 임계는 이동
        직후의 대규모 변화와 대기 애니메이션을 구분하는 수준으로 잡는다.
        """
        deadline = time.monotonic() + timeout
        prev = self.capture.grab_fresh()
        still = 0
        while time.monotonic() < deadline:
            cur = self.capture.grab_fresh()
            still = still + 1 if _changed_fraction(prev, cur) < fraction else 0
            prev = cur
            if still >= min_still:
                return cur
        raise StabilizeTimeout(f"{timeout}s 내 화면 미안정 (임계 {fraction})")

    # -- 지도 모드·점프 ----------------------------------------------------

    def enter_map_mode(self, attempts: int = 3) -> np.ndarray:
        """지도 모드에 진입하고 프레임으로 확인한다. 이미 지도 모드면 그대로 둔다."""
        frame = self.capture.grab_fresh()
        for _ in range(attempts):
            if self.is_map_mode(frame):
                return frame
            self.input.click(*self.ui.MAP_BUTTON)
            self.input.pause()
            try:
                frame = self.wait_stable()
            except StabilizeTimeout:
                frame = self.capture.grab_fresh()
        if not self.is_map_mode(frame):
            raise NotInMapMode(
                f"지도 모드 진입 실패 (마커 점수 {self.map_mode_score(frame):.2f})")
        return frame

    def jump(self, mx: int, my: int) -> GridMapper:
        """좌표로 이동하고 그리드를 확정한다(FR-01).

        점프 후에는 선택 하이라이트 링이 그려지지 않으므로(T12 실측) 대상 타일이
        놓이는 고정 화면 위치(ui.JUMP_ANCHOR)를 앵커로 쓴다.

        T14 실기 보완 2건: ① 선택 팝업이 열린 상태에서는 첫 GO 클릭이 무시되어
        지도 모드가 잔류한다 — GO를 재클릭한다(보충 방문의 연속 점프에서 발생).
        ② 수면(강) 애니메이션 지역은 화면이 계속 변해 안정화가 시간초과된다 —
        지도 모드가 닫혔으면 점프는 완료된 것이므로 고정 대기로 대체한다.
        """
        self.enter_map_mode()
        self._set_coords(mx, my)
        for _ in range(3):
            self._click_verified(self.ui.GO_BUTTON)
            try:
                frame = self.wait_stable()
            except StabilizeTimeout:
                frame = self.capture.grab_fresh()
                if self.is_map_mode(frame):
                    continue          # GO 무시 — 재클릭
                time.sleep(_JUMP_ANIM_SETTLE_S)   # 상시 애니메이션 지역
                frame = self.capture.grab_fresh()
                break
            if not self.is_map_mode(frame):
                break
            log.warning("점프 (%d,%d): GO 후에도 지도 모드 — 재클릭", mx, my)
        else:
            raise StabilizeTimeout(f"점프 ({mx},{my}): GO 재클릭 후에도 지도 모드 잔류")
        ox, oy = self.client_offset(frame)
        anchor = (self.ui.JUMP_ANCHOR[0] + ox, self.ui.JUMP_ANCHOR[1] + oy)
        return GridMapper(self.basis, anchor, (mx, my))

    # -- 디테일 뷰·팬 (설계 v3 §4.3) ---------------------------------------

    def capture_detail_ref(self, frame: np.ndarray) -> None:
        """점프 직후 프레임의 계정 HUD를 디테일 뷰 시그니처 기준으로 삼는다."""
        self._detail_ref = self._sig_crop(frame)

    def detail_view_score(self, frame: np.ndarray) -> float:
        if getattr(self, "_detail_ref", None) is None:
            raise RuntimeError("capture_detail_ref()로 시그니처를 먼저 확보하세요")
        return float(cv2.matchTemplate(self._sig_crop(frame), self._detail_ref,
                                       cv2.TM_CCOEFF_NORMED)[0, 0])

    def verify_detail_view(self, frame: np.ndarray) -> float:
        """디테일 뷰가 아니면 중단한다. 점프 완료 후 지도 UI는 닫혀 있는 것이
        정상이므로(S-5) 지도 모드 '아님'도 함께 요구한다."""
        score = self.detail_view_score(frame)
        if score < self.ui.DETAIL_SIG_THRESHOLD or self.is_map_mode(frame):
            raise NotDetailView(
                f"디테일 뷰 아님 (시그니처 {score:.2f}, "
                f"지도마커 {self.map_mode_score(frame):.2f})")
        return score

    def pan(self, src: tuple[int, int], dst: tuple[int, int],
            steps: int = 24) -> np.ndarray:
        """디테일 뷰 확인 후 드래그 팬을 실행하고 정착된 프레임을 반환한다.

        이동량 산출은 호출자가 PanTracker로 전후 프레임을 대조한다(전단 이동장).
        """
        self.verify_detail_view(self.capture.grab_fresh())
        self.input.drag(*src, *dst, steps=steps)
        time.sleep(self.ui.PAN_SETTLE_S)
        return self.capture.grab_fresh()

    def _sig_crop(self, frame: np.ndarray) -> np.ndarray:
        x0, y0, x1, y1 = self.ui.DETAIL_SIG_RECT
        return frame[y0:y1, x0:x1]

    def detect_map_size(self, upper: int = 2047) -> tuple[int, int]:
        """클램프 동작으로 맵 최대 좌표를 감지한다(FR-02, 설계 §4.2).

        입력란 폰트는 숫자 글리프가 붙어 있어 OCR이 불안정하다(S-3). 대신
        "입력값이 클램프되었는가"를 렌더링 이미지 비교로 판정하고 이진 탐색한다.
        clamp(v) = min(v, max) 이므로 v의 렌더링이 상한 렌더링과 같아지는
        최소 v가 곧 max다. 폰트에 의존하지 않아 게임 업데이트에 강하다.
        """
        self.enter_map_mode()
        return (self._detect_axis(self.ui.COORD_INPUT_X, self.ui.COORD_READ_X, upper),
                self._detect_axis(self.ui.COORD_INPUT_Y, self.ui.COORD_READ_Y, upper))

    # -- 내부 --------------------------------------------------------------

    def _detect_axis(self, field: tuple[int, int],
                     read_rect: tuple[int, int, int, int], upper: int) -> int:
        clamped = self._render_of(field, read_rect, upper)
        lo, hi = 0, upper           # hi는 항상 상한과 같은 렌더링(=클램프됨)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if _same_image(self._render_of(field, read_rect, mid), clamped):
                hi = mid
            else:
                lo = mid
        log.info("맵 최대 좌표 감지: %d", hi)
        return hi

    def _render_of(self, field: tuple[int, int],
                   read_rect: tuple[int, int, int, int], value: int) -> np.ndarray:
        """입력란에 값을 넣고 포커스를 뗀 뒤(클램프 확정) 숫자 영역을 캡처한다."""
        self._type_into(field, value)
        other = (self.ui.COORD_INPUT_Y if field == self.ui.COORD_INPUT_X
                 else self.ui.COORD_INPUT_X)
        self._click_verified(other)   # 블러 시점에 클램프가 적용된다(실측)
        self.input.pause()
        return self.crop_client(self.capture.grab_fresh(), read_rect).copy()

    def _set_coords(self, mx: int, my: int) -> None:
        self._type_into(self.ui.COORD_INPUT_X, mx)
        self._type_into(self.ui.COORD_INPUT_Y, my)
        self._click_verified(self.ui.COORD_INPUT_X)  # 블러 → Y 값 확정

    def _type_into(self, field: tuple[int, int], value: int) -> None:
        """입력란을 완전히 비우고 값을 넣는다.

        백스페이스는 커서 왼쪽만 지우므로 먼저 End로 커서를 끝으로 보낸다
        (T12 실측 — 생략하면 잔여 문자가 남아 엉뚱한 좌표로 이동한다).
        """
        self._click_verified(field)
        self.input.key(VK_END)
        self.input.key(VK_BACK, _FIELD_MAX_DIGITS)
        self.input.type_text(str(value))

    def _click_verified(self, point: tuple[int, int]) -> None:
        """지도 모드를 확인한 뒤에만 클릭한다(오클릭 방지)."""
        if not self.is_map_mode(self.capture.grab_fresh()):
            raise NotInMapMode(f"지도 모드가 아니어서 클릭을 중단했습니다: {point}")
        self.input.click(*point)


def frame_client_offset(frame_shape: tuple[int, ...],
                        client_size: tuple[int, int]) -> tuple[int, int]:
    """캡처 프레임 안에서 클라이언트 (0,0)의 위치.

    좌·우·하단 테두리는 같은 두께, 나머지 상단이 제목 표시줄이라는 창 구조
    가정. WGC 프레임(2546x689→(1,31))과 창 사각형 그랩(2560x696→(8,31))
    모두에서 성립함을 실측했다.
    """
    fh, fw = frame_shape[:2]
    cw, ch = client_size
    border = (fw - cw) // 2
    return border, fh - ch - border


def _changed_fraction(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2)
    return float((diff > _DIFF_PER_PIXEL).mean())


_SAME_PIXEL_DIFF = 30    # 글리프 획이 바뀌면 채널 합 차이가 이보다 훨씬 크다
_SAME_MAX_FRACTION = 0.01


def _same_image(a: np.ndarray, b: np.ndarray) -> bool:
    """같은 문자열이 렌더링되었는지 판정한다.

    읽기 시점의 입력란은 포커스가 없어 텍스트 커서가 없다(_render_of가 다른
    필드를 클릭해 블러시킨다). 따라서 안티에일리어싱 수준의 미세 차이만
    허용하는 엄격한 비교로 충분하다. 한 글자만 달라도 수 %의 픽셀이 바뀐다.
    """
    if a.shape != b.shape:
        return False
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2)
    return float((diff > _SAME_PIXEL_DIFF).mean()) <= _SAME_MAX_FRACTION
