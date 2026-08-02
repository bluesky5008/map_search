import unittest

from mapscan.nav.planner import ScanPlanner, _best_stride


class BestStrideTest(unittest.TestCase):
    def test_solid_rect_offsets_use_full_area(self):
        offsets = {(x, y) for x in range(0, 5) for y in range(0, 3)}
        self.assertEqual(_best_stride(offsets), (5, 3))

    def test_hole_still_tiles_if_residues_cover(self):
        # 3x3에서 (1,1) 구멍 — 보폭 (3,3)은 잉여류 (1,1)이 비어 불가
        offsets = {(x, y) for x in range(0, 3) for y in range(0, 3)}
        offsets.discard((1, 1))
        sx, sy = _best_stride(offsets)
        residues = {(ox % sx, oy % sy) for ox, oy in offsets}
        self.assertEqual(len(residues), sx * sy)
        self.assertLess(sx * sy, 9)

    def test_single_offset(self):
        self.assertEqual(_best_stride({(4, -2)}), (1, 1))


class PlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = ScanPlanner((40, 30))

    def test_stride_matches_residue_condition(self):
        sx, sy = self.planner.stride
        residues = {(ox % sx, oy % sy) for ox, oy in self.planner.offsets}
        self.assertEqual(len(residues), sx * sy)

    def test_visits_cover_entire_map(self):
        covered = set()
        for v in self.planner.visits():
            self.assertTrue(0 <= v.center[0] <= 40, msg=str(v))
            self.assertTrue(0 <= v.center[1] <= 30, msg=str(v))
            covered.update(self.planner.covered(v.center))
        expected = {(x, y) for x in range(41) for y in range(31)}
        self.assertEqual(covered & expected, expected)

    def test_indices_are_sequential(self):
        visits = self.planner.visits()
        self.assertEqual([v.index for v in visits], list(range(len(visits))))

    def test_resume_is_deterministic_suffix(self):
        visits = self.planner.visits()
        fresh = ScanPlanner((40, 30))
        self.assertEqual(list(fresh.resume_from(5)), visits[5:])
        self.assertEqual(list(fresh.resume_from(0)), visits)

    def test_supplemental_covers_missing(self):
        missing = {(0, 0), (17, 22), (40, 30), (3, 29)}
        sup = self.planner.supplemental_visits(missing, start_index=100)
        covered = set()
        for v in sup:
            self.assertTrue(0 <= v.center[0] <= 40)
            self.assertTrue(0 <= v.center[1] <= 30)
            covered.update(self.planner.covered(v.center))
        self.assertTrue(missing <= covered)
        self.assertEqual([v.index for v in sup],
                         list(range(100, 100 + len(sup))))

    def test_supplemental_empty_missing(self):
        self.assertEqual(self.planner.supplemental_visits(set(), 7), [])


class FullMapTest(unittest.TestCase):
    def test_full_map_plan_builds_and_reports_size(self):
        planner = ScanPlanner((1600, 1600))
        visits = planner.visits()
        # 방문 수는 대략 (1601/sx)·(1601/sy) — NFR-02 실측 판단의 입력으로 기록
        sx, sy = planner.stride
        approx = (1601 // sx + 2) * (1601 // sy + 2)
        self.assertLess(len(visits), approx * 1.3)
        self.assertGreater(len(visits), approx * 0.6)


if __name__ == "__main__":
    unittest.main()
