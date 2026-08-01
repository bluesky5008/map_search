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


if __name__ == "__main__":
    unittest.main()
