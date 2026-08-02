"""ScanController/DetailScan — 행 계획 기하와 스캔 루프(가짜 협력자) 검증."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from mapscan.controller import C_BAND, DetailScan, Row, ScanController, plan_rows
from mapscan.nav import ui
from mapscan.store import DataStore
from mapscan.vision import GridBasis
from mapscan.vision.grid import GridMapper


class PlanRowsTest(unittest.TestCase):
    def test_rows_are_deterministic_and_bounded(self):
        rows = plan_rows((1619, 1619))
        self.assertEqual(rows, plan_rows((1619, 1619)))
        # 경계 인셋: 시작점이 서·남 경계에서 안쪽으로 들어와 있다
        self.assertEqual(rows[0], Row(0, (10, 0)))
        for r in rows[1:-1]:
            self.assertTrue(r.start[0] >= 10 or r.start[1] <= 1608)
        for r in rows:
            self.assertTrue(0 <= r.start[0] <= 1619)
            self.assertTrue(0 <= r.start[1] <= 1619)
        # c = 49·mx + 45·my 가 행 간격(C_BAND)만큼 증가한다
        c0 = 49 * rows[10].start[0] + 45 * rows[10].start[1]
        c1 = 49 * rows[11].start[0] + 45 * rows[11].start[1]
        self.assertLess(abs((c1 - c0) - C_BAND), 50)

    def test_row_starts_cover_full_c_range(self):
        # 경계 인셋으로 양 끝 스트라이프는 행이 아니라 보충 방문 몫이다 —
        # 행들이 c 범위를 2·C_BAND 여유 안에서 커버하면 된다.
        rows = plan_rows((100, 100))
        c_last = 49 * rows[-1].start[0] + 45 * rows[-1].start[1]
        self.assertGreaterEqual(c_last + 2 * C_BAND, 94 * 100)


class _FakeResult:
    category, kind, occupancy, confidence = "resource", "목재", "neutral", 0.9


class _FakeClassifier:
    def classify(self, frame, px, py):
        return _FakeResult()


class _FakeCapture:
    def __init__(self, frame):
        self.frame = frame

    def grab_fresh(self):
        return self.frame


class _FakeTracker:
    """팬 없이도 _classify_new를 시험하기 위한 0-이동 추적기."""

    def __init__(self, offset):
        self.offset = offset

    def shift_at(self, y):
        return 0.0


class ClassifyNewTest(unittest.TestCase):
    """대역 한정 열거 + 커버 비트맵 중복 제거 + upsert."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.scan_id = self.store.create_scan("A2")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _scanner(self):
        scanner = DetailScan.__new__(DetailScan)
        scanner.store = self.store
        scanner.clf = _FakeClassifier()
        return scanner

    def test_band_limit_dedup_and_upsert(self):
        frame = np.zeros((689, 2546, 3), dtype=np.uint8)
        grid = GridMapper(GridBasis(), (1226.0, 368.0), (800, 800))
        covered = np.zeros((1620, 1620), dtype=bool)
        scanner = self._scanner()
        tracker = _FakeTracker((1, 31))
        n1 = scanner._classify_new(self.scan_id, grid, tracker, frame,
                                   (1619, 1619), covered)
        self.assertGreater(n1, 20)          # 대역에 셀이 있다
        self.assertEqual(int(covered.sum()), n1)
        self.assertEqual(self.store.tile_count(self.scan_id), n1)
        # 같은 프레임 재분류 → 전부 중복 제거
        n2 = scanner._classify_new(self.scan_id, grid, tracker, frame,
                                   (1619, 1619), covered)
        self.assertEqual(n2, 0)
        # 셀들이 실제로 대역(BAND_Y) 안에만 있다
        ys = [grid.to_screen(r["x"], r["y"])[1] - 31
              for r in self.store.iter_tiles(self.scan_id)]
        self.assertTrue(all(ui.BAND_Y[0] <= y <= ui.BAND_Y[1] for y in ys))

    def test_popup_rect_excluded_on_row_start(self):
        frame = np.zeros((689, 2546, 3), dtype=np.uint8)
        grid = GridMapper(GridBasis(), (1226.0, 368.0), (800, 800))
        scanner = self._scanner()
        tracker = _FakeTracker((1, 31))
        base = np.zeros((1620, 1620), dtype=bool)
        with_popup = np.zeros((1620, 1620), dtype=bool)
        n_all = scanner._classify_new(self.scan_id, grid, tracker, frame,
                                      (1619, 1619), base)
        anchor_c = (1225, 337)
        popup = (anchor_c[0] + ui.POPUP_RECT_REL[0],
                 anchor_c[1] + ui.POPUP_RECT_REL[1],
                 anchor_c[0] + ui.POPUP_RECT_REL[2],
                 anchor_c[1] + ui.POPUP_RECT_REL[3])
        n_popup = scanner._classify_new(self.scan_id, grid, tracker, frame,
                                        (1619, 1619), with_popup,
                                        extra_exclude=[popup])
        self.assertLess(n_popup, n_all)


class ControllerLifecycleTest(unittest.TestCase):
    def test_unimplemented_modes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "t.db"))
            ctl = ScanController(nav=None, store=store)
            for mode in ("A1", "B", "C"):
                with self.assertRaises(NotImplementedError):
                    ctl.run(mode)
            store.close()


if __name__ == "__main__":
    unittest.main()
