"""NFR-02 처리율 — 재앵커 주기 K(3/4/5) 중부 행 실측 (DCR-004 파라미터 튜닝).

제품 경로(ScanController.run) 그대로, K 상수만 케이스별로 패치해 같은 행을
K=3/4/5로 완주시킨다(행별 새 스캔 — 커버 비트맵 독립). 지표: 행 소요, 기록
타일, 팬 수, 재앵커 성공/실패, 추적 손실, 드리프트 크기(좌표 오차 상충 판단).

관리자 권한 인프로세스 실행: 상주 실행기에서
  python spikes/t14_pan_tuning/measure_k.py --hwnd 0x60042 [--rows 100 101]
산출: work/ktune.json + stdout(스캔 로그는 stderr).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import mapscan.controller as controller  # noqa: E402
from mapscan.controller import ScanController  # noqa: E402
from mapscan.nav import Navigator  # noqa: E402
from mapscan.store import DataStore  # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).parent / "work"
MAP_MAX = (1619, 1619)


class EventCounter(logging.Handler):
    """controller 로그에서 케이스별 이벤트·드리프트를 수집한다."""

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.pans = self.lost = self.re_ok = self.re_fail = 0
        self.early = None
        self.drifts: list[tuple[int, int]] = []

    def emit(self, record):
        msg = record.getMessage()
        if re.search(r"팬 #\d+: a=", msg):
            self.pans += 1
        elif "추적 손실" in msg and "조기 종료" not in msg:
            self.lost += 1
        elif "재앵커 실패" in msg:
            self.re_fail += 1
        elif "조기 종료" in msg:
            self.early = msg
        m = re.search(r"드리프트\(([+-]?\d+),([+-]?\d+)\)", msg)
        if m:
            self.re_ok += 1
            self.drifts.append((int(m.group(1)), int(m.group(2))))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--rows", type=int, nargs="+", default=[100, 101])
    ap.add_argument("--ks", type=int, nargs="+", default=[3, 4, 5])
    ap.add_argument("--db", default="output/ktune.db")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    counter = EventCounter()
    logging.getLogger("mapscan.controller").addHandler(counter)

    store = DataStore(args.db)
    session = WindowSession.attach(args.hwnd)
    results = []
    with session:
        client = session.apply_scan_rect()
        print(f"스캔 창: {client[0]}x{client[1]}")
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as capture:
            nav = Navigator(capture, PostMessageInput(session.hwnd))
            ctl = ScanController(nav, store)
            for row in args.rows:
                for k in args.ks:
                    controller._REANCHOR_EVERY = k
                    counter.reset()
                    t0 = time.monotonic()
                    summary = ctl.run("A2", map_max=MAP_MAX, resume=False,
                                      max_rows=1, start_row=row)
                    dt = time.monotonic() - t0
                    tiles = summary["covered"]
                    case = {"row": row, "k": k, "sec": round(dt, 1),
                            "tiles": tiles,
                            "tiles_per_s": round(tiles / dt, 2),
                            "pans": counter.pans, "lost": counter.lost,
                            "re_ok": counter.re_ok, "re_fail": counter.re_fail,
                            "early": counter.early,
                            "drifts": counter.drifts,
                            "row_failures": summary["row_failures"]}
                    results.append(case)
                    print(f"행 {row} K={k}: {dt:.0f}s {tiles}타일 "
                          f"({case['tiles_per_s']}타일/s) 팬 {counter.pans} "
                          f"재앵커 {counter.re_ok}/{counter.re_ok + counter.re_fail} "
                          f"드리프트 {counter.drifts}"
                          f"{' [조기 종료]' if counter.early else ''}")
    store.close()
    WORK.mkdir(exist_ok=True)
    out = WORK / "ktune.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
