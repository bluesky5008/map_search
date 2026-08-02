import unittest
from pathlib import Path

import cv2
import numpy as np

from mapscan.vision import GridBasis, GridMapper, TileClassifier, find_selection_highlight

REPO = Path(__file__).resolve().parent.parent
WORK3 = REPO / "spikes" / "s2_zoom_grid" / "work3"


def load_rgb(path: Path) -> np.ndarray:
    img = cv2.imread(str(path))
    assert img is not None, f"픽스처 없음: {path}"
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class ClassifierRegressionTest(unittest.TestCase):
    """스캔 창 고정 캡처 회귀 (지상 진실: 팝업 판독·셀 모자이크 수동 라벨링).

    snap_tr_base와 snap_click_R은 같은 뷰다(위상상관 시프트 ~0). 앵커는
    snap_click_R의 하이라이트 = (1020,620) (팝업 "Lv.1 목재 (1020,620)").
    """

    @classmethod
    def setUpClass(cls):
        ref = load_rgb(WORK3 / "snap_click_R.png")
        cls.frame = load_rgb(WORK3 / "snap_tr_base.png")
        cls.grid = GridMapper(GridBasis(), find_selection_highlight(ref), (1020, 620))
        cls.clf = TileClassifier()

    def _classify(self, mx, my):
        px, py = self.grid.to_screen(mx, my)
        return self.clf.classify(self.frame, px, py)

    def test_wood_tile_matches_template(self):
        r = self._classify(1020, 620)
        self.assertEqual((r.category, r.kind), ("resource", "목재"))
        self.assertEqual(r.occupancy, "neutral")
        self.assertGreaterEqual(r.confidence, 0.5)

    def test_plain_tile(self):
        r = self._classify(1021, 619)
        self.assertEqual((r.category, r.kind), ("resource", "공터"), msg=f"{r}")
        self.assertEqual(r.occupancy, "neutral")

    def test_enemy_occupied_tiles(self):
        # 붉은 테두리 밭(점령형 스프라이트) — 종류는 미상, 점령상태는 적군.
        # (1022,619)는 테두리 인셋이 깊어 밴드를 벗어난다(알려진 한계, T14 재조정)
        for mx, my in [(1018, 619), (1019, 620)]:
            r = self._classify(mx, my)
            self.assertEqual(r.occupancy, "enemy", msg=f"({mx},{my}) -> {r}")
            self.assertEqual(r.kind, "미상")

    def test_blue_occupied_city_tiles(self):
        for mx, my in [(1019, 622), (1018, 623)]:
            r = self._classify(mx, my)
            self.assertIn(r.occupancy, ("ally", "friendly"), msg=f"({mx},{my}) -> {r}")

    def test_cliff_and_sand_stay_unknown(self):
        # 절벽·모래는 실기 표본 확보 전까지 보수적으로 미상 (오분류보다 안전)
        for mx, my in [(1020, 621), (1016, 622), (1017, 623)]:
            r = self._classify(mx, my)
            self.assertEqual((r.category, r.kind), ("unknown", "미상"),
                             msg=f"({mx},{my}) -> {r}")
            self.assertEqual(r.occupancy, "neutral")

    def test_full_frame_yields_result_per_visible_cell(self):
        cells = self.grid.visible_cells(self.frame.shape[1::-1])
        self.assertGreater(len(cells), 150)
        sample = cells[:: max(1, len(cells) // 30)]
        for c in sample:
            r = self.clf.classify(self.frame, c.px, c.py)
            self.assertIn(r.category,
                          ("resource", "building1", "building2", "impassable", "unknown"))
            self.assertIn(r.occupancy,
                          ("mine", "ally", "friendly", "enemy", "neutral"))
            self.assertTrue(0.0 <= r.confidence <= 1.0)


if __name__ == "__main__":
    unittest.main()
