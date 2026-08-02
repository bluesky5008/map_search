"""AC-01 검증 — 스캔 DB 기록을 실기 클릭 팝업과 대조한다.

절차: 기록된 타일 밀집 지점으로 좌표 점프(이동 표시 확인) → 화면에 보이는
기록 타일 중 시그니처 안전·팝업 회피 조건을 만족하는 셀을 다양성(분류별)
우선으로 클릭 → 팝업 좌표를 DigitReader로 자동 판독해 DB 좌표와 대조하고,
팝업 스트립을 저장해 종류·점령상태는 수동 대조한다(AC-01의 정의가 수동 대조).

산출: work/ac01_<name>_NN_popup.png + ac01_<name>.json (기록·판독·정합 여부)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.controller import _read_popup_coords                    # noqa: E402
from mapscan.nav import Navigator, ui                                # noqa: E402
from mapscan.vision import DigitReader                               # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"
POPUP_PAD = (-300, -225, 380, 160)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--jump", type=int, nargs=2, required=True,
                    metavar=("MX", "MY"), help="점프 좌표(기록 밀집 지점)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--max-clicks", type=int, default=8)
    ap.add_argument("--targets", nargs="*", default=[],
                    help="우선 클릭할 기록 좌표 목록 'x,y' (가시 범위 안일 때)")
    args = ap.parse_args()
    targets = [tuple(int(v) for v in t.split(",")) for t in args.targets]
    WORK.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    scan_id = conn.execute("SELECT MAX(scan_id) FROM scans").fetchone()[0]
    recs = {(r["x"], r["y"]): dict(r) for r in conn.execute(
        "SELECT * FROM tiles WHERE scan_id=?", (scan_id,))}
    print(f"스캔 {scan_id}: 기록 {len(recs)}건")

    session = WindowSession.attach(args.hwnd)
    out = {"db": args.db, "scan": scan_id, "jump": list(args.jump), "checks": []}
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            reader = DigitReader()
            grid = nav.jump(*args.jump)
            frame = cap.grab_fresh()
            nav.capture_detail_ref(frame)
            ox, oy = nav.client_offset(frame)

            # 점프 팝업 회피 + 화면 내 기록 셀 수집
            anchor_c = (grid.anchor_px[0] - ox, grid.anchor_px[1] - oy)
            popups = ui.popup_rects_at(*anchor_c)
            exclude = [(r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)
                       for r in list(ui.HUD_RECTS_CLIENT) + popups]
            cands = []
            for cell in grid.visible_cells(frame.shape[1::-1], exclude=exclude):
                cx_cli, cy_cli = cell.px - ox, cell.py - oy
                if not (ui.BAND_Y[0] <= cy_cli <= ui.BAND_Y[1]):
                    continue
                if cx_cli < 730 and cy_cli < 340:   # 디테일 뷰 시그니처 가림 방지
                    continue
                rec = recs.get((cell.mx, cell.my))
                if rec is None:
                    continue
                cands.append((cell, rec))
            print(f"화면 내 기록 셀 {len(cands)}개")

            # 표적 좌표 우선, 나머지는 분류 다양성 우선 + 직전 팝업 회피
            by_key: dict[tuple, list] = {}
            hits = []
            for c, r in cands:
                if (c.mx, c.my) in targets:
                    hits.append((c, r))
                    continue
                by_key.setdefault(
                    (r["category"], r["kind"], r["occupancy"]), []).append((c, r))
            if targets:
                miss = set(targets) - {(c.mx, c.my) for c, _ in hits}
                print(f"표적 가시 {len(hits)}/{len(targets)}"
                      + (f" (미가시: {sorted(miss)})" if miss else ""))
            picked, prev = list(hits[:args.max_clicks]), None
            if picked:
                prev = (picked[-1][0].px, picked[-1][0].py)
            pools = sorted(by_key.values(), key=len)
            while len(picked) < args.max_clicks and any(pools):
                for pool in pools:
                    while pool:
                        c, r = pool.pop(0)
                        if prev is not None and \
                                prev[0] + POPUP_PAD[0] <= c.px <= prev[0] + POPUP_PAD[2] and \
                                prev[1] + POPUP_PAD[1] <= c.py <= prev[1] + POPUP_PAD[3]:
                            continue
                        picked.append((c, r))
                        prev = (c.px, c.py)
                        break
                    if len(picked) >= args.max_clicks:
                        break
                if not any(pools):
                    break

            clicked_at = None
            for i, (c, r) in enumerate(picked):
                rec = {k: r[k] for k in
                       ("x", "y", "category", "kind", "occupancy",
                        "center_x", "center_y", "center_estimated")}
                # 직전 클릭 팝업(버튼 영역 포함)이 이 셀을 덮으면 클릭 금지
                if clicked_at is not None and \
                        clicked_at[0] + POPUP_PAD[0] <= c.px <= clicked_at[0] + POPUP_PAD[2] and \
                        clicked_at[1] + POPUP_PAD[1] <= c.py <= clicked_at[1] + POPUP_PAD[3]:
                    print(f"  #{i} ({c.mx},{c.my}) 직전 팝업 영역 — 건너뜀")
                    out["checks"].append({"i": i, "record": rec,
                                          "skipped": "popup-overlap"})
                    continue
                try:
                    nav.verify_detail_view(cap.grab_fresh())
                    inp.click(round(c.px - ox), round(c.py - oy))
                    time.sleep(1.1)
                    after = cap.grab_fresh()
                    got = _read_popup_coords(reader, after,
                                             round(c.px), round(c.py))
                    strip = after[max(0, round(c.py) - 280):round(c.py) + 40,
                                  max(0, round(c.px) - 140):round(c.px) + 340]
                    Image.fromarray(strip).save(
                        WORK / f"ac01_{args.name}_{i:02d}_popup.png")
                    match = (got is not None
                             and got == (rec["x"], rec["y"]))
                    out["checks"].append(
                        {"i": i, "record": rec, "popup_xy": got,
                         "xy_match": match})
                    clicked_at = (c.px, c.py)
                    print(f"  #{i} 기록({rec['x']},{rec['y']}) "
                          f"{rec['kind']}/{rec['occupancy']} → 팝업 {got} "
                          f"{'정합' if match else '불일치'}")
                except Exception as exc:
                    print(f"  #{i} 실패: {exc!r}")
                    out["checks"].append({"i": i, "record": rec,
                                          "error": repr(exc)})
    conn.close()
    (WORK / f"ac01_{args.name}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for c in out["checks"] if c.get("xy_match"))
    print(f"좌표 정합 {n_ok}/{len(out['checks'])} — 종류·점령은 스트립 수동 대조")
    return 0


if __name__ == "__main__":
    sys.exit(main())
