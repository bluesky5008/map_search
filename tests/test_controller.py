"""ScanController/DetailScan — 행 계획 기하와 스캔 루프(가짜 협력자) 검증."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import mapscan.controller as controller_mod
from mapscan.controller import C_BAND, DetailScan, Row, ScanController, plan_rows
from mapscan.nav import ui
from mapscan.store import DataStore, TileRecord
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

    def test_band_limit_dedup_and_deferred_upsert(self):
        frame = np.zeros((689, 2546, 3), dtype=np.uint8)
        grid = GridMapper(GridBasis(), (1226.0, 368.0), (800, 800))
        covered = np.zeros((1620, 1620), dtype=bool)
        scanner = self._scanner()
        tracker = _FakeTracker((1, 31))
        recs = scanner._classify_new(grid, tracker, frame, (1619, 1619), covered)
        n1 = len(recs)
        self.assertGreater(n1, 20)          # 대역에 셀이 있다
        self.assertEqual(int(covered.sum()), n1)
        # 지연 기록(DCR-004): 분류만으로는 저장되지 않고 flush가 기록한다
        self.assertEqual(self.store.tile_count(self.scan_id), 0)
        scanner._flush(self.scan_id, [(0, recs)], (0, 0), 1, covered,
                       (1619, 1619))
        self.assertEqual(self.store.tile_count(self.scan_id), n1)
        self.assertEqual(int(covered.sum()), n1)
        # 같은 프레임 재분류 → 전부 중복 제거
        recs2 = scanner._classify_new(grid, tracker, frame, (1619, 1619), covered)
        self.assertEqual(recs2, [])
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
        n_all = len(scanner._classify_new(grid, tracker, frame,
                                          (1619, 1619), base))
        anchor_c = (1225, 337)
        popup = (anchor_c[0] + ui.POPUP_RECT_REL[0],
                 anchor_c[1] + ui.POPUP_RECT_REL[1],
                 anchor_c[0] + ui.POPUP_RECT_REL[2],
                 anchor_c[1] + ui.POPUP_RECT_REL[3])
        n_popup = len(scanner._classify_new(grid, tracker, frame,
                                            (1619, 1619), with_popup,
                                            extra_exclude=[popup]))
        self.assertLess(n_popup, n_all)


class ReanchorFlushTest(unittest.TestCase):
    """지연 기록 보정(DCR-004): 드리프트 팬별 보간, 커버 이동, 폐기 경로."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.scan_id = self.store.create_scan("A2")
        self.scanner = DetailScan.__new__(DetailScan)
        self.scanner.store = self.store
        self.covered = np.zeros((100, 100), dtype=bool)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _rec(self, x, y):
        self.covered[y, x] = True
        return TileRecord(x=x, y=y, category="지형")

    def test_flush_interpolates_drift_and_moves_coverage(self):
        buffer = [(0, [self._rec(10, 50)]), (1, [self._rec(20, 50)]),
                  (3, [self._rec(30, 50)])]
        n = self.scanner._flush(self.scan_id, buffer, (-2, 5), 3,
                                self.covered, (99, 99))
        self.assertEqual(n, 3)
        got = {(r["x"], r["y"]) for r in self.store.iter_tiles(self.scan_id)}
        # 보정: i=0→(0,0), i=1→(round(-2/3),round(5/3))=(-1,2), i=3→(-2,5)
        self.assertEqual(got, {(10, 50), (19, 52), (28, 55)})
        for x, y in got:
            self.assertTrue(self.covered[y, x])
        self.assertFalse(self.covered[50, 20] or self.covered[50, 30])

    def test_flush_drops_collision_and_out_of_map(self):
        buffer = [(0, [self._rec(10, 10)]),
                  (3, [self._rec(12, 5), self._rec(99, 97)])]
        # 드리프트 (-2,+5): (12,5)→(10,10) 충돌, (99,97)→(97,102) 맵 밖
        n = self.scanner._flush(self.scan_id, buffer, (-2, 5), 3,
                                self.covered, (99, 99))
        self.assertEqual(n, 1)
        got = {(r["x"], r["y"]) for r in self.store.iter_tiles(self.scan_id)}
        self.assertEqual(got, {(10, 10)})
        self.assertFalse(self.covered[5, 12] or self.covered[97, 99])

    def test_drop_buffer_unsets_coverage(self):
        buffer = [(1, [self._rec(3, 4), self._rec(5, 6)])]
        self.assertEqual(self.scanner._drop_buffer(buffer, self.covered), 2)
        self.assertFalse(self.covered.any())
        self.assertEqual(self.store.tile_count(self.scan_id), 0)


class _ReanchorNav:
    def __init__(self, frame):
        self._frame = frame
        self.capture = self
        self.input = self
        self.clicks = []

    def grab_fresh(self):
        return self._frame

    def verify_detail_view(self, frame):
        return 1.0

    def click(self, x, y):
        self.clicks.append((x, y))


class ReanchorProbeTest(unittest.TestCase):
    """재앵커 클릭: 새니티 창 판정과 그리드 재구성."""

    def _reanchor(self, read_result):
        frame = np.zeros((689, 2546, 3), dtype=np.uint8)
        scanner = DetailScan.__new__(DetailScan)
        scanner.nav = _ReanchorNav(frame)
        scanner.reader = None   # _read_popup_coords를 패치하므로 미사용
        grid = GridMapper(GridBasis(), (1226.0, 368.0), (800, 800))
        tracker = _FakeTracker((1, 31))
        with mock.patch.object(controller_mod, "_REANCHOR_SETTLE_S", 0), \
             mock.patch.object(controller_mod, "_read_popup_coords",
                               lambda *a: read_result), \
             mock.patch.object(controller_mod, "find_selection_highlight",
                               lambda *a, **k: None):
            return scanner, scanner._reanchor(
                Row(5, (800, 800)), grid, tracker, frame.shape, (1, 31),
                pans_since=3, losts=0)

    def test_applies_read_within_sanity_window(self):
        # 뷰 중앙 예측 타일은 앵커 (800,800) 근방 — (801,801)은 창(±8) 안
        scanner, res = self._reanchor((801, 801))
        self.assertIsNotNone(res)
        new_grid, drift = res
        self.assertEqual(new_grid.anchor_map, (801, 801))
        self.assertLessEqual(abs(drift[0]), 2)
        self.assertLessEqual(abs(drift[1]), 2)
        self.assertEqual(len(scanner.nav.clicks), 1)

    def test_rejects_read_outside_sanity_window(self):
        _, res = self._reanchor((900, 900))
        self.assertIsNone(res)

    def test_rejects_read_failure(self):
        _, res = self._reanchor(None)
        self.assertIsNone(res)


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
