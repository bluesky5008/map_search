"""MuMu 처리율 실측 (DCR-005) — 행 100·101을 제품 경로로 완주.

measure_k(t14)와 동일 지표·동일 행으로 PC 실측(21.3~21.9타일/s, K=4)과 직접
비교한다. 배선만 MuMu: 캡처 top / 입력 device, 창 설정 생략, 비관리자 실행.

  python spikes/s7_mumu/measure_mumu.py --mumu 용스 [--rows 100 101]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "t14_pan_tuning"))

from measure_k import EventCounter  # noqa: E402

import mapscan.controller as controller  # noqa: E402
from mapscan.controller import ScanController  # noqa: E402
from mapscan.nav import Navigator, ui  # noqa: E402
from mapscan.store import DataStore  # noqa: E402
from mapscan.win import (PostMessageInput, WgcCapture, WindowSession,  # noqa: E402
                         find_mumu_instance)

WORK = Path(__file__).parent / "work"
MAP_MAX = (1619, 1619)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mumu", default="용스")
    ap.add_argument("--rows", type=int, nargs="+", default=[100, 101])
    ap.add_argument("--db", default="output/mumu_rate.db")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    counter = EventCounter()
    logging.getLogger("mapscan.controller").addHandler(counter)

    inst = find_mumu_instance(args.mumu, expect_client=ui.CLIENT_SIZE)
    session = WindowSession(inst.top)
    session.check_permission()
    print(f"MuMu '{inst.title}': top={inst.top:#x} device={inst.device:#x} "
          f"{inst.client[0]}x{inst.client[1]} (창 설정 생략)")
    store = DataStore(args.db)
    results = []
    with session, WgcCapture(inst.top, inst.title) as capture:
        nav = Navigator(capture, PostMessageInput(inst.device), ime_overlay=True)
        ctl = ScanController(nav, store)
        for row in args.rows:
            counter.reset()
            t0 = time.monotonic()
            summary = ctl.run("A2", map_max=MAP_MAX, resume=False,
                              max_rows=1, start_row=row)
            dt = time.monotonic() - t0
            tiles = summary["covered"]
            case = {"row": row, "k": controller._REANCHOR_EVERY,
                    "sec": round(dt, 1), "tiles": tiles,
                    "tiles_per_s": round(tiles / dt, 2),
                    "pans": counter.pans, "lost": counter.lost,
                    "re_ok": counter.re_ok, "re_fail": counter.re_fail,
                    "early": counter.early, "drifts": counter.drifts,
                    "row_failures": summary["row_failures"]}
            results.append(case)
            print(f"행 {row}: {dt:.0f}s {tiles}타일 ({case['tiles_per_s']}타일/s) "
                  f"팬 {counter.pans} 재앵커 {counter.re_ok}/"
                  f"{counter.re_ok + counter.re_fail} 드리프트 {counter.drifts}"
                  f"{' [조기 종료]' if counter.early else ''}")
    store.close()
    WORK.mkdir(exist_ok=True)
    out = WORK / "mumu_rate.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
