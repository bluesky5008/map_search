"""팬 사이클 시간 내역 프로파일 — S-6(2.95s/팬) 대비 +1.7s의 소재 규명.

행 1개를 제품 경로로 돌리며 주요 단계(pan/classify/구조물 검출/재앵커/워치독)
호출 시간을 몽키패치 타이머로 집계한다. 산출: stdout 표.

관리자 권한: python spikes/t14_pan_tuning/profile_row.py --hwnd 0x60042
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import mapscan.controller as controller  # noqa: E402
from mapscan.controller import DetailScan, ScanController  # noqa: E402
from mapscan.nav import Navigator  # noqa: E402
from mapscan.store import DataStore  # noqa: E402
from mapscan.vision import TileClassifier  # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

TIMES: dict[str, list[float]] = defaultdict(list)


def timed(name, fn):
    @functools.wraps(fn)
    def wrap(*a, **kw):
        t0 = time.monotonic()
        try:
            return fn(*a, **kw)
        finally:
            TIMES[name].append(time.monotonic() - t0)
    return wrap


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--row", type=int, default=102)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--max-pans", type=int, default=12)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    controller._REANCHOR_EVERY = args.k

    store = DataStore("output/profile_row.db")
    session = WindowSession.attach(args.hwnd)
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as capture:
            nav = Navigator(capture, PostMessageInput(session.hwnd))
            nav.pan = timed("nav.pan", nav.pan)
            nav.jump = timed("nav.jump", nav.jump)
            DetailScan._classify_new = timed(
                "classify_new", DetailScan._classify_new)
            DetailScan._reanchor = timed("reanchor", DetailScan._reanchor)
            DetailScan._flush = timed("flush", DetailScan._flush)
            TileClassifier.detect_structures = timed(
                "detect_structures", TileClassifier.detect_structures)
            TileClassifier.classify = timed("clf.classify", TileClassifier.classify)
            TileClassifier._occupancy = timed("clf._occupancy", TileClassifier._occupancy)
            TileClassifier._best_template = timed("clf._best_tpl", TileClassifier._best_template)
            controller._band_cells = timed("band_cells", controller._band_cells)

            orig_grab = capture.grab_fresh

            def grab_probe(*a, **kw):
                f = orig_grab(*a, **kw)
                if not TIMES.get("_frame_info"):
                    TIMES["_frame_info"].append(0.0)
                    print(f"frame: shape={f.shape} dtype={f.dtype} "
                          f"contig={f.flags['C_CONTIGUOUS']}", file=sys.stderr)
                return f
            capture.grab_fresh = timed("grab_fresh", grab_probe)
            ctl = ScanController(nav, store)
            t0 = time.monotonic()
            summary = ctl.run("A2", map_max=(1619, 1619), resume=False,
                              max_rows=1, start_row=args.row,
                              max_pans=args.max_pans)
            total = time.monotonic() - t0
    store.close()
    print(f"\n행 {args.row} K={args.k} 팬≤{args.max_pans}: "
          f"{total:.1f}s {summary['covered']}타일")
    print(f"{'단계':<18}{'횟수':>5}{'합(s)':>8}{'평균(s)':>9}")
    for name, vals in sorted(TIMES.items(), key=lambda kv: -sum(kv[1])):
        print(f"{name:<18}{len(vals):>5}{sum(vals):>8.1f}{sum(vals) / len(vals):>9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
