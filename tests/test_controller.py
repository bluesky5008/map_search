"""ScanController/DetailScan — 행 계획 기하와 스캔 루프(가짜 협력자) 검증."""

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np

import mapscan.controller as controller_mod
from mapscan.controller import (C_BAND, DetailScan, Row, ScanController,
                                parse_until, plan_rows)
from mapscan.nav import NotInMapMode, ui
from mapscan.store import DataStore, TileRecord
from mapscan.vision import GridBasis
from mapscan.vision.grid import GridMapper
from mapscan.win import CaptureStalled


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

    def detect_structures(self, frame, exclude=()):
        return []


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
        popup = ui.popup_rects_at(1225, 337)
        n_popup = len(scanner._classify_new(grid, tracker, frame,
                                            (1619, 1619), with_popup,
                                            extra_exclude=popup))
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

    def test_flush_shifts_center_reference(self):
        # FR-07: 건물 중심 참조도 셀과 같은 드리프트 보정을 받는다
        rec = TileRecord(x=20, y=50, category="building2", kind="주성",
                         center_x=21, center_y=50, center_estimated=True)
        self.covered[50, 20] = True
        n = self.scanner._flush(self.scan_id, [(3, [rec])], (-2, 5), 3,
                                self.covered, (99, 99))
        self.assertEqual(n, 1)
        row = next(iter(self.store.iter_tiles(self.scan_id)))
        self.assertEqual((row["x"], row["y"]), (18, 55))
        self.assertEqual((row["center_x"], row["center_y"]), (19, 55))
        self.assertEqual(row["center_estimated"], 1)


class _FakeStructClassifier(_FakeClassifier):
    """고정 검출 결과를 돌려주는 분류기 — 병합 로직만 시험한다(기하는 vision 몫)."""

    def __init__(self, hit, members):
        self.hit, self.members = hit, members

    def detect_structures(self, frame, exclude=()):
        return [self.hit]

    def structure_members(self, hit, cells):
        return self.members


class StructureMergeTest(unittest.TestCase):
    """FR-07: 검출된 건물의 멤버 셀이 종류·중심 참조를 공유한다."""

    def test_members_share_center_and_kind(self):
        from mapscan.vision import StructureHit
        scanner = DetailScan.__new__(DetailScan)
        hit = StructureHit("castle", "building2", "주성", 100.0, 100.0, 0.87)
        scanner.clf = _FakeStructClassifier(hit, ([0, 1], 1))
        cells = [(10, 20, 90.0, 95.0), (11, 20, 140.0, 120.0),
                 (12, 20, 400.0, 95.0)]
        recs = scanner._classified_records(None, cells, [])
        for i in (0, 1):
            self.assertEqual((recs[i].category, recs[i].kind),
                             ("building2", "주성"))
            self.assertEqual((recs[i].center_x, recs[i].center_y), (11, 20))
            self.assertTrue(recs[i].center_estimated)
            self.assertEqual(recs[i].confidence, 0.87)
        # 비멤버는 셀별 분류를 유지한다
        self.assertEqual(recs[2].kind, "목재")
        self.assertIsNone(recs[2].center_x)


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
                               lambda *a, **k: None), \
             mock.patch.object(DetailScan, "_save_evidence",
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

    def test_prefers_flat_resource_candidate(self):
        """절벽·산(미상)은 고도 시차 피킹 위험 — 평지(resource) 셀을 클릭한다."""
        frame = np.zeros((689, 2546, 3), dtype=np.uint8)
        scanner = DetailScan.__new__(DetailScan)
        scanner.nav = _ReanchorNav(frame)
        scanner.reader = None
        grid = GridMapper(GridBasis(), (1226.0, 368.0), (800, 800))
        tracker = _FakeTracker((1, 31))
        cands = [TileRecord(x=800, y=800, category="unknown"),
                 TileRecord(x=802, y=799, category="resource")]
        with mock.patch.object(controller_mod, "_REANCHOR_SETTLE_S", 0), \
             mock.patch.object(controller_mod, "_read_popup_coords",
                               lambda *a: (803, 800)), \
             mock.patch.object(controller_mod, "find_selection_highlight",
                               lambda *a, **k: None):
            res = scanner._reanchor(Row(5, (800, 800)), grid, tracker,
                                    frame.shape, (1, 31), 3, 0,
                                    candidates=cands)
        self.assertIsNotNone(res)
        new_grid, drift = res
        self.assertEqual(new_grid.anchor_map, (803, 800))
        self.assertEqual(drift, (1, 1))
        cx, cy = scanner.nav.clicks[0]
        px, py = grid.to_screen(802, 799)
        self.assertAlmostEqual(cx, px - 1, delta=1)
        self.assertAlmostEqual(cy, py - 31, delta=1)

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


class ChunkRunTest(unittest.TestCase):
    """다계정 병렬 청크(end_row) — 상한·체크포인트 재개·보충 생략 (DCR-005)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.addCleanup(self.store.close)
        self.scan_id = self.store.create_scan("A2")
        self.rows_run: list[int] = []
        scanner = DetailScan.__new__(DetailScan)
        scanner.store = self.store
        scanner._run_row = (
            lambda scan_id, row, map_max, covered: self.rows_run.append(row.index))
        scanner._supplement = mock.Mock(
            side_effect=AssertionError("청크·부분 실행에서 보충 방문 금지"))
        self.scanner = scanner

    def test_end_row_bounds_resume_and_skips_supplement(self):
        s = self.scanner.run(self.scan_id, (100, 100), end_row=5)
        self.assertEqual(self.rows_run, [0, 1, 2, 3, 4])
        self.assertEqual(s["rows"], 5)
        self.assertNotIn("supplemented", s)
        # 재실행(체크포인트 5): 같은 상한이면 처리할 행이 없다 — 멱등
        self.rows_run.clear()
        self.scanner.run(self.scan_id, (100, 100), end_row=5)
        self.assertEqual(self.rows_run, [])
        # 상한을 늘리면 체크포인트에서 이어서 진행한다
        self.scanner.run(self.scan_id, (100, 100), end_row=7)
        self.assertEqual(self.rows_run, [5, 6])

    def test_full_run_still_supplements(self):
        self.scanner._supplement = mock.Mock(return_value=3)
        self.scanner.run(self.scan_id, (100, 100))
        self.scanner._supplement.assert_called_once()


class ParseUntilTest(unittest.TestCase):
    """--until HH:MM 해석 — 미래는 당일, 현재 이하는 익일."""

    NOW = datetime(2026, 8, 3, 22, 0)

    def test_future_time_is_today(self):
        self.assertEqual(parse_until("23:30", self.NOW),
                         datetime(2026, 8, 3, 23, 30))

    def test_past_time_rolls_to_tomorrow(self):
        self.assertEqual(parse_until("08:00", self.NOW),
                         datetime(2026, 8, 4, 8, 0))

    def test_equal_time_rolls_to_tomorrow(self):
        self.assertEqual(parse_until("22:00", self.NOW),
                         datetime(2026, 8, 4, 22, 0))

    def test_invalid_format_raises(self):
        for bad in ("2500", "24:00", "8시", ""):
            with self.assertRaises(ValueError):
                parse_until(bad, self.NOW)


class UntilDeadlineTest(unittest.TestCase):
    """--until 자기 정지: 행 경계 검사·체크포인트 유지·보충 생략."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.addCleanup(self.store.close)
        self.scan_id = self.store.create_scan("A2")
        self.rows_run: list[int] = []
        scanner = DetailScan.__new__(DetailScan)
        scanner.store = self.store
        scanner._run_row = (
            lambda scan_id, row, map_max, covered: self.rows_run.append(row.index))
        scanner._supplement = mock.Mock(
            side_effect=AssertionError("데드라인 정지 후 보충 방문 금지"))
        self.scanner = scanner

    def test_expired_deadline_stops_before_next_row(self):
        self.store.set_checkpoint(self.scan_id, 2)
        s = self.scanner.run(self.scan_id, (100, 100), end_row=5,
                             until=time.time() - 1)
        self.assertEqual(self.rows_run, [])
        self.assertTrue(s["deadline"])
        # 체크포인트가 보존돼 다음 실행이 같은 지점에서 재개한다
        self.assertEqual(self.store.get_scan(self.scan_id)["checkpoint"], 2)

    def test_future_deadline_runs_all_rows(self):
        s = self.scanner.run(self.scan_id, (100, 100), end_row=3,
                             until=time.time() + 3600)
        self.assertEqual(self.rows_run, [0, 1, 2])
        self.assertFalse(s["deadline"])

    def test_full_run_skips_supplement_after_deadline(self):
        # setUp의 _supplement mock(AssertionError)이 호출되면 실패한다
        s = self.scanner.run(self.scan_id, (100, 100), until=time.time() - 1)
        self.assertTrue(s["deadline"])

    def test_supplement_stops_between_visits(self):
        scanner = DetailScan.__new__(DetailScan)
        scanner.store = self.store
        # 미커버가 있어 방문 계획은 생기지만, 첫 방문 전에 정지해야 한다
        # (정지가 안 되면 nav 미설정으로 AttributeError가 난다)
        n = scanner._supplement(self.scan_id, (10, 10),
                                np.zeros((11, 11), dtype=bool),
                                until=time.time() - 1)
        self.assertEqual(n, 0)


class AbortOnFailureStreakTest(unittest.TestCase):
    """연속 행 실패·캡처 정지 중단과 체크포인트 무결성 (DCR-006 / AC-D2·D3)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.addCleanup(self.store.close)
        self.scan_id = self.store.create_scan("A2")
        self.scanner = DetailScan.__new__(DetailScan)
        self.scanner.store = self.store
        self.scanner._supplement = mock.Mock(
            side_effect=AssertionError("중단 후 보충 방문 금지"))

    def _fail_rows(self, failing):
        """failing에 든 행 인덱스에서만 실패하는 _run_row를 심는다."""
        self.ran = []

        def run_row(scan_id, row, map_max, covered):
            self.ran.append(row.index)
            if row.index in failing:
                raise NotInMapMode(f"행 {row.index} 강제 실패")

        self.scanner._run_row = run_row

    def _checkpoint(self):
        return self.store.get_scan(self.scan_id)["checkpoint"]

    def test_streak_aborts_and_rewinds_checkpoint(self):
        self._fail_rows(set(range(2, 20)))   # 행 2부터 계속 실패
        s = self.scanner.run(self.scan_id, (100, 100), end_row=30)
        self.assertEqual(self.ran, [0, 1, 2, 3, 4, 5, 6])   # 5연속에서 중단
        self.assertIsNotNone(s["aborted"])
        # 체크포인트가 연속 실패 시작 행(2)으로 되돌아가 다음 실행이 재시도한다
        self.assertEqual(self._checkpoint(), 2)
        self.assertEqual(s["row_failures"], 5)

    def test_isolated_failures_do_not_abort(self):
        # 고립 실패는 기존 동작 유지 — 체크포인트 전진(보충 방문 몫)
        self._fail_rows({1, 3, 5, 7, 9})
        s = self.scanner.run(self.scan_id, (100, 100), end_row=11)
        self.assertEqual(self.ran, list(range(11)))
        self.assertIsNone(s["aborted"])
        self.assertEqual(self._checkpoint(), 11)
        self.assertEqual(s["row_failures"], 5)

    def test_streak_resets_after_success(self):
        # 4연속 실패 후 성공하면 카운트가 풀려 중단되지 않는다
        self._fail_rows({0, 1, 2, 3, 5, 6, 7, 8})
        s = self.scanner.run(self.scan_id, (100, 100), end_row=10)
        self.assertEqual(self.ran, list(range(10)))
        self.assertIsNone(s["aborted"])
        self.assertEqual(self._checkpoint(), 10)

    def test_capture_stalled_aborts_immediately(self):
        def run_row(scan_id, row, map_max, covered):
            if row.index == 3:
                raise CaptureStalled("프레임 정지")
        self.scanner._run_row = run_row
        s = self.scanner.run(self.scan_id, (100, 100), end_row=30)
        self.assertIn("프레임 정지", s["aborted"])
        # 진행 중이던 행부터 다시 하도록 체크포인트를 남긴다
        self.assertEqual(self._checkpoint(), 3)
        self.assertEqual(s["rows"], 3)

    def test_full_run_skips_supplement_after_abort(self):
        # setUp의 _supplement mock(AssertionError)이 호출되면 실패한다
        self._fail_rows(set(range(0, 20)))
        s = self.scanner.run(self.scan_id, (100, 100))
        self.assertIsNotNone(s["aborted"])


class AbortControllerStatusTest(unittest.TestCase):
    """중단 스캔은 재개 가능한 paused로 저장되고 status=aborted로 보고된다."""

    def test_aborted_scan_is_paused_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "t.db"))
            try:
                ctl = ScanController(nav=None, store=store)
                summary = {"rows": 5, "row_failures": 5, "covered": 0,
                           "total": 100, "deadline": False,
                           "aborted": "연속 5행 실패"}
                with mock.patch.object(DetailScan, "__init__",
                                       lambda self, nav, store: None), \
                     mock.patch.object(DetailScan, "run", return_value=summary):
                    s = ctl.run("A2", map_max=(9, 9), resume=False)
                self.assertEqual(s["status"], "aborted")
                self.assertEqual(
                    store.get_scan(s["scan_id"])["status"], "paused")
            finally:
                store.close()


class UntilControllerStatusTest(unittest.TestCase):
    """데드라인 정지는 기존 중단 경로(paused)로 저장돼 재개 가능해야 한다."""

    def _run(self, detail_summary):
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "t.db"))
            try:
                ctl = ScanController(nav=None, store=store)
                with mock.patch.object(DetailScan, "__init__",
                                       lambda self, nav, store: None), \
                     mock.patch.object(DetailScan, "run",
                                       return_value=detail_summary):
                    s = ctl.run("A2", map_max=(9, 9), resume=False)
                return s, store.get_scan(s["scan_id"])["status"]
            finally:
                store.close()

    def test_deadline_marks_scan_paused(self):
        s, db_status = self._run({"rows": 1, "row_failures": 0,
                                  "covered": 10, "total": 100,
                                  "deadline": True})
        self.assertEqual(s["status"], "paused")
        self.assertEqual(db_status, "paused")

    def test_completion_wins_over_deadline(self):
        s, db_status = self._run({"rows": 1, "row_failures": 0,
                                  "covered": 100, "total": 100,
                                  "deadline": True})
        self.assertEqual(s["status"], "done")
        self.assertEqual(db_status, "done")


if __name__ == "__main__":
    unittest.main()
