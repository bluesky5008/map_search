import tempfile
import unittest
from pathlib import Path

from mapscan.store import DataStore, TileRecord, export_csv


def make_store(tmp: str) -> DataStore:
    return DataStore(str(Path(tmp) / "test.db"))


class DataStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = make_store(self.tmp.name)
        self.addCleanup(self.store.close)
        self.scan = self.store.create_scan("A", zoom_level="wide")

    def test_upsert_is_idempotent_and_last_wins(self):
        r1 = TileRecord(x=10, y=20, category="resource", kind="목재",
                        occupancy="neutral")
        self.store.upsert_tiles(self.scan, [r1])
        r2 = TileRecord(x=10, y=20, category="resource", kind="철광",
                        occupancy="enemy")
        self.store.upsert_tiles(self.scan, [r2])

        self.assertEqual(self.store.tile_count(self.scan), 1)
        row = next(iter(self.store.iter_tiles(self.scan)))
        self.assertEqual(row["kind"], "철광")
        self.assertEqual(row["occupancy"], "enemy")
        self.assertTrue(row["captured_at"])  # 자동 기록

    def test_checkpoint_and_scan_lifecycle(self):
        self.store.set_map_size(self.scan, 1599, 1599)
        self.store.set_checkpoint(self.scan, 42)

        resumable = self.store.latest_resumable_scan("A")
        self.assertEqual(resumable["scan_id"], self.scan)
        self.assertEqual(resumable["checkpoint"], 42)
        self.assertEqual(resumable["map_max_x"], 1599)

        self.store.finish_scan(self.scan)
        self.assertIsNone(self.store.latest_resumable_scan("A"))
        self.assertEqual(self.store.get_scan(self.scan)["status"], "done")

    def test_iter_tiles_ordered_by_y_then_x(self):
        recs = [TileRecord(x=x, y=y, category="resource")
                for (x, y) in [(5, 1), (1, 2), (3, 1)]]
        self.store.upsert_tiles(self.scan, recs)
        coords = [(r["x"], r["y"]) for r in self.store.iter_tiles(self.scan)]
        self.assertEqual(coords, [(3, 1), (5, 1), (1, 2)])


class CsvExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = make_store(self.tmp.name)
        self.addCleanup(self.store.close)
        self.scan = self.store.create_scan("A")
        self.store.upsert_tiles(self.scan, [
            TileRecord(x=x, y=0, category="resource", kind="목재")
            for x in range(5)
        ])

    def test_export_single_file_with_bom(self):
        paths = export_csv(self.store, self.scan, self.tmp.name)
        self.assertEqual(len(paths), 1)
        raw = paths[0].read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM
        lines = raw.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(lines), 6)  # header + 5 rows
        self.assertTrue(lines[0].startswith("x,y,category"))

    def test_export_split(self):
        paths = export_csv(self.store, self.scan, self.tmp.name, split_rows=2)
        self.assertEqual(len(paths), 3)  # 2+2+1
        total = 0
        for p in paths:
            lines = p.read_text(encoding="utf-8-sig").strip().splitlines()
            self.assertTrue(lines[0].startswith("x,y,category"))
            total += len(lines) - 1
        self.assertEqual(total, 5)

    def test_export_unknown_scan_raises(self):
        with self.assertRaises(ValueError):
            export_csv(self.store, 999, self.tmp.name)


class MergeScanTest(unittest.TestCase):
    """다계정 병렬 청크 DB 병합(DCR-005) — captured_at 최신 우선."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _part(self, name, tiles, map_size=(100, 100)):
        path = str(Path(self.tmp.name) / name)
        st = DataStore(path)
        sid = st.create_scan("A2")
        st.set_map_size(sid, *map_size)
        st.upsert_tiles(sid, [
            TileRecord(x=x, y=y, category=cat, captured_at=ts)
            for x, y, cat, ts in tiles])
        st.close()
        return path

    def test_latest_captured_at_wins_regardless_of_order(self):
        a = self._part("a.db", [(1, 1, "공터", "2026-08-02T10:00:00+09:00"),
                                (2, 2, "resource", "2026-08-02T10:00:00+09:00")])
        b = self._part("b.db", [(1, 1, "resource", "2026-08-02T11:00:00+09:00"),
                                (3, 3, "공터", "2026-08-02T11:00:00+09:00")])
        for i, order in enumerate(((a, b), (b, a))):
            target = DataStore(str(Path(self.tmp.name) / f"target{i}.db"))
            sid = target.create_scan("A2")
            for part in order:
                result = target.merge_scan_from(sid, part)
                self.assertEqual(result["map_max"], (100, 100))
            self.assertEqual(target.tile_count(sid), 3)
            got = {(r["x"], r["y"]): r["category"]
                   for r in target.iter_tiles(sid)}
            # (1,1)은 어느 순서로 병합해도 최신(11시, resource)이 이긴다
            self.assertEqual(got[(1, 1)], "resource")
            target.close()

    def test_part_without_a2_scan_raises(self):
        path = str(Path(self.tmp.name) / "empty.db")
        DataStore(path).close()
        target = DataStore(str(Path(self.tmp.name) / "t.db"))
        self.addCleanup(target.close)
        sid = target.create_scan("A2")
        with self.assertRaises(ValueError):
            target.merge_scan_from(sid, path)


if __name__ == "__main__":
    unittest.main()
