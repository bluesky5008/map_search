"""SQLite 수집 원장 (설계 §3, ADR-003).

(scan_id, x, y) PK에 대한 upsert로 재방문·재개 시 중복이 발생하지 않는다(FR-10).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
  scan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  mode         TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  map_max_x    INTEGER,
  map_max_y    INTEGER,
  zoom_level   TEXT,
  capture_mode TEXT,
  checkpoint   INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS tiles (
  scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
  x            INTEGER NOT NULL,
  y            INTEGER NOT NULL,
  category     TEXT NOT NULL,
  kind         TEXT,
  level        INTEGER,
  occupancy    TEXT,
  center_x     INTEGER,
  center_y     INTEGER,
  center_estimated INTEGER NOT NULL DEFAULT 0,
  confidence   REAL,
  status       TEXT NOT NULL DEFAULT 'ok',
  captured_at  TEXT NOT NULL,
  PRIMARY KEY (scan_id, x, y)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_tiles_kind ON tiles(scan_id, category, kind);
"""

_TILE_COLUMNS = (
    "scan_id", "x", "y", "category", "kind", "level", "occupancy",
    "center_x", "center_y", "center_estimated", "confidence", "status",
    "captured_at",
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class TileRecord:
    x: int
    y: int
    category: str
    kind: str | None = None
    level: int | None = None
    occupancy: str | None = None
    center_x: int | None = None
    center_y: int | None = None
    center_estimated: bool = False
    confidence: float | None = None
    status: str = "ok"
    captured_at: str = ""


class DataStore:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- scans -------------------------------------------------------------

    def create_scan(self, mode: str, zoom_level: str | None = None,
                    capture_mode: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO scans (mode, started_at, zoom_level, capture_mode)"
            " VALUES (?, ?, ?, ?)",
            (mode, _now(), zoom_level, capture_mode))
        self._conn.commit()
        return cur.lastrowid

    def get_scan(self, scan_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM scans WHERE scan_id=?", (scan_id,)).fetchone()

    def latest_resumable_scan(self, mode: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM scans WHERE mode=? AND status IN ('running','paused')"
            " ORDER BY scan_id DESC LIMIT 1", (mode,)).fetchone()

    def set_map_size(self, scan_id: int, max_x: int, max_y: int) -> None:
        self._conn.execute(
            "UPDATE scans SET map_max_x=?, map_max_y=? WHERE scan_id=?",
            (max_x, max_y, scan_id))
        self._conn.commit()

    def set_checkpoint(self, scan_id: int, index: int) -> None:
        self._conn.execute(
            "UPDATE scans SET checkpoint=? WHERE scan_id=?", (index, scan_id))
        self._conn.commit()

    def finish_scan(self, scan_id: int, status: str = "done") -> None:
        self._conn.execute(
            "UPDATE scans SET status=?, finished_at=? WHERE scan_id=?",
            (status, _now(), scan_id))
        self._conn.commit()

    # -- tiles -------------------------------------------------------------

    def upsert_tiles(self, scan_id: int, records: list[TileRecord]) -> None:
        now = _now()
        rows = [
            (scan_id, r.x, r.y, r.category, r.kind, r.level, r.occupancy,
             r.center_x, r.center_y, int(r.center_estimated), r.confidence,
             r.status, r.captured_at or now)
            for r in records
        ]
        self._conn.executemany(
            f"INSERT OR REPLACE INTO tiles ({','.join(_TILE_COLUMNS)})"
            f" VALUES ({','.join('?' * len(_TILE_COLUMNS))})", rows)
        self._conn.commit()

    def tile_count(self, scan_id: int) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM tiles WHERE scan_id=?", (scan_id,)).fetchone()[0]

    def iter_tiles(self, scan_id: int):
        yield from self._conn.execute(
            "SELECT x, y, category, kind, level, occupancy, center_x, center_y,"
            " center_estimated, confidence, status, captured_at"
            " FROM tiles WHERE scan_id=? ORDER BY y, x", (scan_id,))

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DataStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
