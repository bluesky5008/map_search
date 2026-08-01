"""CSV 내보내기 (설계 §3, ADR-003). UTF-8 BOM, 분할 저장 옵션."""

from __future__ import annotations

import csv
from pathlib import Path

from .datastore import DataStore

CSV_HEADER = [
    "x", "y", "category", "kind", "level", "occupancy",
    "center_x", "center_y", "center_estimated", "confidence", "status",
    "captured_at",
]


def export_csv(store: DataStore, scan_id: int, out_dir: str,
               split_rows: int = 1_000_000) -> list[Path]:
    """스캔 데이터를 CSV 파일(들)로 내보내고 생성 경로 목록을 반환한다."""
    scan = store.get_scan(scan_id)
    if scan is None:
        raise ValueError(f"scan {scan_id} not found")
    date = scan["started_at"][:10].replace("-", "")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    writer = None
    fh = None
    rows_in_file = 0

    def open_next() -> None:
        nonlocal writer, fh, rows_in_file
        if fh:
            fh.close()
        part = f"_p{len(paths) + 1:02d}" if split_rows else ""
        path = out / f"scan_{scan_id}_{date}{part}.csv"
        fh = open(path, "w", newline="", encoding="utf-8-sig")
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        rows_in_file = 0
        paths.append(path)

    open_next()
    for row in store.iter_tiles(scan_id):
        if split_rows and rows_in_file >= split_rows:
            open_next()
        writer.writerow(tuple(row))
        rows_in_file += 1
    fh.close()

    # 단일 파일이면 _p01 접미사를 제거한 이름으로 정리한다.
    if len(paths) == 1 and split_rows:
        plain = out / f"scan_{scan_id}_{date}.csv"
        paths[0].replace(plain)
        paths[0] = plain
    return paths
