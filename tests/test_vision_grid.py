import unittest
from pathlib import Path

import cv2
import numpy as np

from mapscan.vision import grid as g

REPO = Path(__file__).resolve().parent.parent
SNAP_R = REPO / "spikes" / "s2_zoom_grid" / "work3" / "snap_click_R.png"


def load_rgb(path: Path) -> np.ndarray:
    img = cv2.imread(str(path))
    assert img is not None, f"픽스처 없음: {path}"
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class BasisTest(unittest.TestCase):
    def test_half_extents_of_scan_basis(self):
        hx, hy = g.GridBasis().half_extents
        self.assertAlmostEqual(hx, 77.5)
        self.assertAlmostEqual(hy, 47.0)


class TransformTest(unittest.TestCase):
    def setUp(self):
        self.m = g.GridMapper(g.GridBasis(), anchor_px=(1000.0, 400.0),
                              anchor_map=(1020, 620))

    def test_anchor_maps_to_itself(self):
        self.assertEqual(self.m.to_screen(1020, 620), (1000.0, 400.0))
        self.assertEqual(self.m.nearest_tile(1000, 400), (1020, 620))

    def test_round_trip(self):
        for mx, my in [(1020, 620), (1028, 611), (990, 645), (0, 0)]:
            px, py = self.m.to_screen(mx, my)
            rx, ry = self.m.to_map(px, py)
            self.assertAlmostEqual(rx, mx, places=9)
            self.assertAlmostEqual(ry, my, places=9)

    def test_neighbor_steps_follow_basis(self):
        px, py = self.m.to_screen(1021, 620)
        self.assertAlmostEqual(px - 1000, g.SCAN_E_MX[0])
        self.assertAlmostEqual(py - 400, g.SCAN_E_MX[1])
        px, py = self.m.to_screen(1020, 621)
        self.assertAlmostEqual(px - 1000, g.SCAN_E_MY[0])
        self.assertAlmostEqual(py - 400, g.SCAN_E_MY[1])

    def test_nearest_tile_within_cell(self):
        # 셀 중심에서 반칸 미만으로 벗어난 픽셀은 같은 타일로 돌아온다
        px, py = self.m.to_screen(1005, 633)
        for dmx, dmy in [(0.4, 0), (-0.4, 0.3), (0.2, -0.45)]:
            d = self.m.basis.matrix() @ (dmx, dmy)
            self.assertEqual(self.m.nearest_tile(px + d[0], py + d[1]),
                             (1005, 633))


class VisibleCellsTest(unittest.TestCase):
    def setUp(self):
        self.m = g.GridMapper(g.GridBasis(), anchor_px=(1272.0, 328.0),
                              anchor_map=(1000, 600))
        self.size = (2544, 657)

    def test_cells_fit_inside_frame(self):
        cells = self.m.visible_cells(self.size)
        self.assertGreater(len(cells), 150)  # 실측 가시 타일 ~230
        hx, hy = self.m.basis.half_extents
        for c in cells:
            self.assertGreaterEqual(c.px, hx)
            self.assertLessEqual(c.px, self.size[0] - hx)
            self.assertGreaterEqual(c.py, hy)
            self.assertLessEqual(c.py, self.size[1] - hy)

    def test_cells_are_unique_and_consistent(self):
        cells = self.m.visible_cells(self.size)
        keys = {(c.mx, c.my) for c in cells}
        self.assertEqual(len(keys), len(cells))
        for c in cells[:20]:
            self.assertEqual(self.m.to_screen(c.mx, c.my), (c.px, c.py))

    def test_exclude_rect_removes_overlapping_cells(self):
        rect = (0, 0, 800, 657)
        cells = self.m.visible_cells(self.size, exclude=[rect])
        hx, hy = self.m.basis.half_extents
        for c in cells:
            self.assertGreaterEqual(c.px - hx, 800)


class HighlightTest(unittest.TestCase):
    """실캡처 회귀: snap_click_R의 선택 타일 = (1020,620), 링 중심 실측 (2131,368)."""

    @classmethod
    def setUpClass(cls):
        cls.frame = load_rgb(SNAP_R)

    def test_highlight_center_found(self):
        center = g.find_selection_highlight(self.frame)
        self.assertIsNotNone(center)
        self.assertAlmostEqual(center[0], 2131, delta=5)
        self.assertAlmostEqual(center[1], 368, delta=5)

    def test_from_frame_maps_click_to_selected_tile(self):
        m = g.GridMapper.from_frame(self.frame, (1020, 620))
        # 클릭 지점 client(2100,350) = 창 픽셀 (2108,381) 은 선택 타일 안에 있다
        self.assertEqual(m.nearest_tile(2108, 381), (1020, 620))

    def test_missing_highlight_raises(self):
        blank = np.zeros((100, 200, 3), dtype=np.uint8)
        self.assertIsNone(g.find_selection_highlight(blank))
        with self.assertRaises(g.AnchorNotFound):
            g.GridMapper.from_frame(blank, (0, 0))


if __name__ == "__main__":
    unittest.main()
