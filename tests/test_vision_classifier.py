import unittest
from pathlib import Path

import cv2
import numpy as np

from mapscan.vision import GridBasis, GridMapper, TileClassifier, find_selection_highlight

REPO = Path(__file__).resolve().parent.parent
WORK3 = REPO / "spikes" / "s2_zoom_grid" / "work3"
T14_WORK = REPO / "spikes" / "t14_pan_tuning" / "work"


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


class FieldSampleRegressionTest(unittest.TestCase):
    """T14.3 실기 표본 회귀 (지상 진실: 클릭 팝업 판독, 라벨은 analyze_tiles.LABELS).

    픽스처는 sample_tiles.py 수집 프레임의 240x160 셀 크롭
    (register_templates.py 추출) — 셀 중심은 항상 (120,80).
    """

    @classmethod
    def setUpClass(cls):
        cls.clf = TileClassifier()

    def _classify(self, name):
        return self.clf.classify(load_rgb(T14_WORK / f"{name}_cell.png"), 120, 80)

    def test_occupied_iron_template_and_ally(self):
        # Lv.5 철광 점령형(동맹 FIRST — 행군/주둔 버튼으로 확인)
        r = self._classify("tiles_occ_02")
        self.assertEqual((r.category, r.kind), ("resource", "철광"))
        self.assertEqual(r.occupancy, "ally")

    def test_occupied_food_template(self):
        # Lv.5 식량 점령형(밭). 소유 패널이 잘려 점령상태 진실은 불확정 —
        # 마주보는 변 규칙상 중립(보수) 판정
        r = self._classify("tiles_mine_01")
        self.assertEqual((r.category, r.kind), ("resource", "식량"))

    def test_cliff_river_blue_not_ally(self):
        # 팝업 진실 "절벽 — 점령 불가". 강 인접 파랑 번짐(blue 8.6%)이
        # 한쪽 변에만 있어 마주보는 변 규칙이 기각한다 (구현 전 ally 오탐)
        r = self._classify("tiles_occ_04")
        self.assertEqual(r.occupancy, "neutral", msg=f"{r}")

    def test_vacant_plot_blue_not_ally(self):
        # 팝업 진실 "무주 공터 (345,335)" — 인접 파랑 번짐 오탐 회귀(확정 사실 37)
        r = self._classify("tiles_mine_00")
        self.assertEqual(r.occupancy, "neutral", msg=f"{r}")

    def test_enemy_occupied_plot_kept(self):
        # 점령 공터(잠봉) — 빨강 정탐이 규칙 변경에 영향받지 않는다
        r = self._classify("tiles_occ_05")
        self.assertEqual(r.occupancy, "enemy", msg=f"{r}")

    def test_one_sided_green_not_mine(self):
        # 무주 공터가 mine으로 오탐된 실기 사례(진실: 팝업 "공터 (181,801)" 등
        # 2건) — 인접 밭의 밝은 초록이 한쪽 변에만 샘플링된 경우를 기각한다
        clf = TileClassifier()
        m = clf.basis.matrix()
        frame = np.zeros((160, 240, 3), dtype=np.uint8)
        frame[:] = (90, 120, 70)  # 저채도 지면(어느 마스크에도 안 걸림)
        green = np.array([60, 220, 70], dtype=np.uint8)  # H~65 S~185 V~220

        def paint(u_sign):
            # 변 중앙부만 — 실기 인접 번짐은 국소 블롭이며, 변 전체를 칠하면
            # 모서리가 이웃 변 표본까지 오염해 검정력이 사라진다
            for t in np.arange(-0.20, 0.201, 0.02):
                for s in np.arange(0.30, 0.421, 0.02):
                    x, y = (np.array([120.0, 80.0])
                            + m @ (u_sign * s, t)).round().astype(int)
                    frame[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = green

        paint(+1)  # 한쪽 변만 초록 → 기각(중립)
        self.assertEqual(clf._occupancy(frame, 120, 80), "neutral")
        paint(-1)  # 마주보는 변까지 초록 → mine
        self.assertEqual(clf._occupancy(frame, 120, 80), "mine")


class StructureDetectionTest(unittest.TestCase):
    """FR-07: 주성 성채 검출·멤버 병합 기하.

    픽스처 tiles_occ_city.png는 도시 無名마산동탁 일대(기준좌표 진실
    (1016,626), 확정 사실 36) — 성벽 다이아몬드 중심이 (140,88)이 되도록
    register_templates.py가 잘랐다.
    """

    @classmethod
    def setUpClass(cls):
        cls.clf = TileClassifier()
        cls.fix = load_rgb(T14_WORK / "tiles_occ_city.png")

    def test_detects_castle_at_wall_center(self):
        hits = self.clf.detect_structures(self.fix)
        self.assertEqual(len(hits), 1, msg=f"{hits}")
        h = hits[0]
        self.assertEqual((h.category, h.kind), ("building2", "주성"))
        self.assertGreaterEqual(h.score, 0.9)
        self.assertAlmostEqual(h.cx, 140, delta=3)
        self.assertAlmostEqual(h.cy, 88, delta=3)

    def test_exclude_rect_suppresses_hit(self):
        hits = self.clf.detect_structures(self.fix,
                                          exclude=((100, 60, 180, 120),))
        self.assertEqual(hits, [])

    def test_member_grouping_radius(self):
        h = self.clf.detect_structures(self.fix)[0]
        m = self.clf.basis.matrix()

        def at(u, v, mx, my):
            px, py = np.array([h.cx, h.cy]) + m @ (u, v)
            return (mx, my, float(px), float(py))

        cells = [at(0.1, 0.05, 1016, 626),   # 중심 셀
                 at(0.5, 0.5, 1016, 627),    # 2x2 이웃 — 멤버
                 at(1.5, 0.0, 1018, 626)]    # 반경(0.75타일) 밖
        got = self.clf.structure_members(h, cells)
        self.assertIsNotNone(got)
        members, center = got
        self.assertEqual(members, [0, 1])
        self.assertEqual(center, 0)

    def test_no_castle_on_unrelated_terrain(self):
        # 임계 0.6의 여유 확인(무관 지형 차순위 ≤0.25 실측)
        hits = self.clf.detect_structures(
            load_rgb(T14_WORK / "tiles_occ_05_cell.png"))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
