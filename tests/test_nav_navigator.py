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


class JumpTest(unittest.TestCase):
    def test_refuses_when_not_in_map_mode(self):
        with self.assertRaises(NotInMapMode):
            nav_with([make_frame(False)]).jump(100, 200)

    def test_jump_clears_field_before_typing(self):
        inp = FakeInput()
        grid = nav_with([make_frame()], inp).jump(123, 456)
        self.assertEqual(inp.calls, [
            ("click", 80, 40), ("key", VK_END, 1), ("key", VK_BACK, 12), ("type", "123"),
            ("click", 90, 40), ("key", VK_END, 1), ("key", VK_BACK, 12), ("type", "456"),
            ("click", 80, 40),   # 블러 → Y 값 확정
            ("click", 95, 40),   # 이동
        ])
        self.assertEqual(grid.anchor_px, (51.0, 31.0))  # JUMP_ANCHOR + 프레임 오프셋
        self.assertEqual(grid.anchor_map, (123, 456))
        self.assertEqual(grid.nearest_tile(51.0, 31.0), (123, 456))


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


if __name__ == "__main__":
    unittest.main()
