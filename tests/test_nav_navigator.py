import unittest

import numpy as np

from mapscan.nav.navigator import (
    VK_BACK, VK_END, Navigator, NotInMapMode, StabilizeTimeout, frame_client_offset,
)

MARK = (7, 3, 27, 13)          # 작은 마커 영역으로 테스트
CLIENT = (100, 60)
FRAME_SHAPE = (62, 102, 3)     # 테두리 1px, 제목 표시줄 1px

TEMPLATE = np.tile(np.arange(20, dtype=np.uint8).reshape(1, 20, 1) * 10, (10, 1, 3))


class FakeUi:
    CLIENT_SIZE = CLIENT
    MAP_MODE_MARK = MARK
    MAP_MODE_THRESHOLD = 0.7
    MAP_BUTTON = (10, 50)
    COORD_INPUT_X = (80, 40)
    COORD_INPUT_Y = (90, 40)
    GO_BUTTON = (95, 40)
    COORD_READ_X = (60, 20, 76, 30)
    COORD_READ_Y = (60, 32, 76, 42)
    JUMP_ANCHOR = (50.0, 30.0)
    IME_CONFIRM = (98, 5)


def make_frame(map_mode: bool = True, fill: int = 0) -> np.ndarray:
    f = np.full(FRAME_SHAPE, fill, dtype=np.uint8)
    if map_mode:
        x0, y0, x1, y1 = MARK
        f[y0 + 1:y1 + 1, x0 + 1:x1 + 1] = TEMPLATE
    return f


class FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)

    def grab_fresh(self, timeout=2.0):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


class FakeInput:
    def __init__(self):
        self.calls: list[tuple] = []

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def key(self, vk, count=1):
        self.calls.append(("key", vk, count))

    def type_text(self, text):
        self.calls.append(("type", text))

    def pause(self):
        pass


def nav_with(frames, inp=None) -> Navigator:
    return Navigator(FakeCapture(frames), inp or FakeInput(), ui_cfg=FakeUi,
                     map_mode_template=TEMPLATE)


class FrameOffsetTest(unittest.TestCase):
    def test_wgc_frame(self):
        self.assertEqual(frame_client_offset((689, 2546, 3), (2544, 657)), (1, 31))

    def test_window_rect_grab(self):
        self.assertEqual(frame_client_offset((696, 2560, 3), (2544, 657)), (8, 31))


class MapModeTest(unittest.TestCase):
    def test_detects_map_mode(self):
        self.assertTrue(nav_with([make_frame()]).is_map_mode(make_frame()))

    def test_rejects_normal_view(self):
        nav = nav_with([make_frame(False)])
        self.assertFalse(nav.is_map_mode(make_frame(False)))

    def test_enter_map_mode_is_noop_when_already_there(self):
        inp = FakeInput()
        nav_with([make_frame()], inp).enter_map_mode()
        self.assertEqual(inp.calls, [])

    def test_enter_map_mode_clicks_then_verifies(self):
        inp = FakeInput()
        nav_with([make_frame(False)] + [make_frame()] * 5, inp).enter_map_mode()
        self.assertEqual(inp.calls[0], ("click", 10, 50))

    def test_enter_map_mode_gives_up(self):
        with self.assertRaises(NotInMapMode):
            nav_with([make_frame(False)]).enter_map_mode(attempts=2)


class WaitStableTest(unittest.TestCase):
    def test_returns_frame_after_stillness(self):
        nav = nav_with([make_frame(fill=0), make_frame(fill=100),
                        make_frame(fill=100), make_frame(fill=100)])
        self.assertEqual(nav.wait_stable(timeout=2.0)[0, 0, 0], 100)

    def test_times_out_when_always_changing(self):
        class Rolling:
            def __init__(self):
                self.i = 0

            def grab_fresh(self, timeout=2.0):
                self.i += 1
                return make_frame(fill=(self.i * 40) % 250)

        nav = Navigator(Rolling(), FakeInput(), ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        with self.assertRaises(StabilizeTimeout):
            nav.wait_stable(timeout=0.3)


class JumpCapture:
    """GO 클릭 시점부터 지도 모드가 닫히는 상태 기반 캡처.

    ignore_go: 처음 n회의 GO 클릭을 무시한다(선택 팝업 잔류 재현, T14 실기).
    """

    def __init__(self, inp: FakeInput, ignore_go: int = 0):
        self.inp = inp
        self.ignore_go = ignore_go

    def grab_fresh(self, timeout=2.0):
        go_clicks = sum(1 for c in self.inp.calls if c == ("click", 95, 40))
        return make_frame(map_mode=go_clicks <= self.ignore_go)


class JumpTest(unittest.TestCase):
    def test_refuses_when_not_in_map_mode(self):
        with self.assertRaises(NotInMapMode):
            nav_with([make_frame(False)]).jump(100, 200)

    def test_jump_clears_field_before_typing(self):
        inp = FakeInput()
        nav = Navigator(JumpCapture(inp), inp, ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        grid = nav.jump(123, 456)
        self.assertEqual(inp.calls, [
            ("click", 80, 40), ("key", VK_END, 1), ("key", VK_BACK, 12), ("type", "123"),
            ("click", 90, 40), ("key", VK_END, 1), ("key", VK_BACK, 12), ("type", "456"),
            ("click", 80, 40),   # 블러 → Y 값 확정
            ("click", 95, 40),   # 이동
        ])
        self.assertEqual(grid.anchor_px, (51.0, 31.0))  # JUMP_ANCHOR + 프레임 오프셋
        self.assertEqual(grid.anchor_map, (123, 456))
        self.assertEqual(grid.nearest_tile(51.0, 31.0), (123, 456))

    def test_jump_reclicks_go_when_ignored(self):
        """선택 팝업이 열려 있으면 첫 GO가 무시된다(T14 실기) — 재클릭해야 한다."""
        inp = FakeInput()
        nav = Navigator(JumpCapture(inp, ignore_go=1), inp, ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        grid = nav.jump(7, 8)
        self.assertEqual(sum(1 for c in inp.calls if c == ("click", 95, 40)), 2)
        self.assertEqual(grid.anchor_map, (7, 8))

    def test_jump_gives_up_when_go_never_works(self):
        inp = FakeInput()
        nav = Navigator(JumpCapture(inp, ignore_go=99), inp, ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        with self.assertRaises(StabilizeTimeout):
            nav.jump(7, 8)

    def test_jump_tolerates_unstable_animation_when_map_closed(self):
        """수면 애니메이션 지역: 안정화 실패라도 지도 모드가 닫혔으면 점프 완료."""
        import mapscan.nav.navigator as nav_mod

        class AnimatedCapture(JumpCapture):
            def __init__(self, inp):
                super().__init__(inp)
                self.i = 0

            def grab_fresh(self, timeout=2.0):
                f = super().grab_fresh()
                self.i += 1
                f[40:60, 40:100] = (self.i * 40) % 250   # 상시 대규모 변화
                return f

        inp = FakeInput()
        nav = Navigator(AnimatedCapture(inp), inp, ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        nav.wait_stable = lambda *a, **k: Navigator.wait_stable(nav, timeout=0.3)
        old = nav_mod._JUMP_ANIM_SETTLE_S
        nav_mod._JUMP_ANIM_SETTLE_S = 0.0
        try:
            grid = nav.jump(3, 4)
        finally:
            nav_mod._JUMP_ANIM_SETTLE_S = old
        self.assertEqual(grid.anchor_map, (3, 4))


class DetectMapSizeTest(unittest.TestCase):
    """클램프 렌더링 이미지 비교로 최대 좌표를 이진 탐색한다."""

    def _run(self, max_x: int, max_y: int) -> tuple[int, int]:
        limits = {FakeUi.COORD_INPUT_X: max_x, FakeUi.COORD_INPUT_Y: max_y}
        state: dict = {"field": None, "value": {}}

        class Capture:
            def grab_fresh(self, timeout=2.0):
                f = make_frame()
                for field, rect in ((FakeUi.COORD_INPUT_X, FakeUi.COORD_READ_X),
                                    (FakeUi.COORD_INPUT_Y, FakeUi.COORD_READ_Y)):
                    v = state["value"].get(field)
                    if v is None:
                        continue
                    c = min(v, limits[field])
                    x0, y0, x1, y1 = rect
                    # 값마다 뚜렷이 다른 렌더링 (같은 값이면 동일, 다르면 대부분 상이)
                    rng = np.random.default_rng(c)
                    f[y0 + 1:y1 + 1, x0 + 1:x1 + 1] = rng.integers(
                        0, 256, (y1 - y0, x1 - x0, 3), dtype=np.uint8)
                return f

        class RecordingInput(FakeInput):
            def click(self, x, y):
                super().click(x, y)
                if (x, y) in limits:
                    state["field"] = (x, y)

            def type_text(self, text):
                super().type_text(text)
                state["value"][state["field"]] = int(text)

        nav = Navigator(Capture(), RecordingInput(), ui_cfg=FakeUi,
                        map_mode_template=TEMPLATE)
        return nav.detect_map_size(upper=2047)

    def test_finds_square_map(self):
        self.assertEqual(self._run(1619, 1619), (1619, 1619))

    def test_finds_asymmetric_map(self):
        self.assertEqual(self._run(1200, 800), (1200, 800))

    def test_finds_small_map(self):
        self.assertEqual(self._run(7, 3), (7, 3))


class ImeOverlayTest(unittest.TestCase):
    """MuMu(앱) 좌표 입력 — IME 오버레이 개폐 감지·✓ 확정 시퀀스(DCR-005, S-7)."""

    def _nav(self, frames, inp):
        return Navigator(FakeCapture(frames), inp, ui_cfg=FakeUi,
                         map_mode_template=TEMPLATE, ime_overlay=True)

    def test_type_into_clears_prefill_and_confirms(self):
        inp = FakeInput()
        # 클릭 검증(마커 O) → 오버레이 열림(마커 X) → ✓ 확정 후 닫힘(마커 O)
        nav = self._nav([make_frame(True), make_frame(False), make_frame(True)],
                        inp)
        nav._type_into(FakeUi.COORD_INPUT_X, 15)
        self.assertEqual(inp.calls, [
            ("click", *FakeUi.COORD_INPUT_X),
            ("key", VK_BACK, 12),          # 프리필 삭제(END 없음 — 커서는 끝)
            ("type", "15"),
            ("click", *FakeUi.IME_CONFIRM),
        ])

    def test_set_coords_skips_final_blur_click(self):
        inp = FakeInput()
        nav = self._nav([make_frame(True), make_frame(False), make_frame(True)] * 2,
                        inp)
        nav._set_coords(10, 20)
        clicks = [c for c in inp.calls if c[0] == "click"]
        # X 필드·✓, Y 필드·✓ — 블러용 X 재클릭(오버레이 재개방 위험)은 없다
        self.assertEqual(clicks, [
            ("click", *FakeUi.COORD_INPUT_X), ("click", *FakeUi.IME_CONFIRM),
            ("click", *FakeUi.COORD_INPUT_Y), ("click", *FakeUi.IME_CONFIRM),
        ])

    def test_wait_marker_times_out(self):
        nav = self._nav([make_frame(True)], FakeInput())
        with self.assertRaises(StabilizeTimeout):
            nav._wait_marker(False, "오버레이 열림", timeout=0.3)

    def test_map_size_detection_is_refused(self):
        nav = self._nav([make_frame(True)], FakeInput())
        with self.assertRaises(NotImplementedError):
            nav.detect_map_size()


if __name__ == "__main__":
    unittest.main()
