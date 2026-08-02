"""T14.1 팬 추적 원인 규명 캡처 — 팬 프레임·NCC 피크 구조·클릭 지상 진실.

행 150 중앙부에서 간헐 TrackLost(plan.md 확정 사실 25)와 밴드 이동 이중 상태
(~100px 간격 진동, T14 텔레메트리)가 관찰되었다. 원인 후보(격자 주기 거짓 피크
vs 실제 이동 변동)를 가리려면 팬 전후 프레임 원본과 상관 곡선의 경쟁 피크
구조가 필요하다.

절차: 점프 → 소폭 팬 1 + 광폭 팬 N-1 (프레임 저장 + 밴드별 상위 피크 기록)
→ 상단 밴드·하단 밴드 예측 타일 2개 클릭 → 팝업 좌표 판독(누적 전단의 지상
진실 2점) + 스트립 저장(겨울 팝업 글리프 템플릿 소스 겸용, T14.3).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.controller import plan_rows                     # noqa: E402
from mapscan.nav import Navigator, ui                        # noqa: E402
from mapscan.nav.pan import PanTracker, TrackLost, pan_gain  # noqa: E402
from mapscan.vision import DigitReader                       # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"


def band_peaks(prev, cur, band, offset, expect, search=450, n=5):
    """_band_shift와 같은 기하로 상관 곡선을 만들고 상위 n개 피크를 반환한다.

    탐색 반경을 넓혀(±450) 격자 주기(~100·155px) 간격의 경쟁 피크가 보이게 한다.
    """
    y0, h = band
    ox, oy = offset
    sy0 = max(0, y0 + oy - 12)
    sy1 = min(cur.shape[0], y0 + h + oy + 12)
    if expect < -800:   # 광폭 좌팬 — 역방향 매칭(cur 좌측 신규 구간을 prev에서 찾기)
        cx0, w_tpl = 10, 450
        tpl = cur[y0 + oy:y0 + h + oy, cx0 + ox:cx0 + w_tpl + ox]
        ex = cx0 + ox - int(expect)
        sx0 = max(0, ex - search)
        sx1 = min(prev.shape[1], ex + w_tpl + search)
        res = cv2.matchTemplate(prev[sy0:sy1, sx0:sx1], tpl, cv2.TM_CCOEFF_NORMED)
        def to_shift(px, py):
            return (float((cx0 + ox) - (sx0 + px)),
                    float((y0 + oy) - (sy0 + py)))
    else:
        x0, x1 = ui.TRACK_X
        if expect < 0:
            x0 = max(x0, int(-expect) + search + 10)
        else:
            x1 = min(x1, prev.shape[1] - int(expect) - search - 10)
        tpl = prev[y0 + oy:y0 + h + oy, x0 + ox:x1 + ox]
        ex = x0 + ox + int(expect)
        sx0 = max(0, ex - search)
        sx1 = min(cur.shape[1], ex + (x1 - x0) + search)
        res = cv2.matchTemplate(cur[sy0:sy1, sx0:sx1], tpl, cv2.TM_CCOEFF_NORMED)
        def to_shift(px, py):
            return (float(sx0 + px - (x0 + ox)), float(sy0 + py - (y0 + oy)))

    peaks = []
    r = res.copy()
    for _ in range(n):
        _, score, _, (px, py) = cv2.minMaxLoc(r)
        dx, dy = to_shift(px, py)
        peaks.append((round(dx, 1), round(dy, 1), round(float(score), 3)))
        x_lo, x_hi = max(0, px - 25), min(r.shape[1], px + 26)
        r[:, x_lo:x_hi] = -1.0   # 같은 피크 재검출 억제
    return peaks


def read_popup(reader, frame, cx, cy):
    """클릭점(프레임 좌표) 위쪽의 좌표 문자열을 슬라이딩 밴드로 판독한다.

    좌표 줄 위치는 팝업 구성에 따라 변하고(S-5), 실제 선택 타일이 예측에서
    반 타일쯤 어긋날 수 있어 x도 슬라이딩한다.
    """
    for dx_off in (0, -30, -60, 30, 60):
        for dy in range(-230, -100, 6):
            strip = frame[cy + dy:cy + dy + 34,
                          cx - 30 + dx_off:cx + 195 + dx_off]
            got = reader.read_coords(strip)
            if got:
                return got, (dx_off, dy)
    return None, None


def click_truth(nav, inp, cap, grid, tracker, offset, y_client, name, work, reader):
    """대역 y의 뷰 중앙 예측 타일을 클릭하고 팝업 좌표(지상 진실)를 얻는다."""
    frame = cap.grab_fresh()
    nav.verify_detail_view(frame)
    w = frame.shape[1]
    ox, oy = offset
    yf = y_client + oy
    # 화면 (w/2, yf)에 가장 가까운 격자 셀 — 예측 이동(shift_at)을 적용해 찾는다
    ccx, ccy = grid.to_map(w / 2 - tracker.shift_at(yf), yf)
    best = None
    for dmx in range(-3, 4):
        for dmy in range(-3, 4):
            mx, my = round(ccx) + dmx, round(ccy) + dmy
            x0, y0 = grid.to_screen(mx, my)
            px, py = x0 + tracker.shift_at(y0), y0
            d = abs(px - w / 2) + abs(py - yf)
            if best is None or d < best[0]:
                best = (d, mx, my, px, py)
    _, mx, my, px, py = best
    inp.click(round(px - ox), round(py - oy))
    time.sleep(1.2)
    after = cap.grab_fresh()
    Image.fromarray(after).save(work / f"click_{name}.png")
    crop = after[max(0, round(py) - 260):round(py) + 40,
                 max(0, round(px) - 120):round(px) + 320]
    Image.fromarray(crop).save(work / f"click_{name}_strip.png")
    got, at = read_popup(reader, after, round(px), round(py))
    print(f"  클릭 {name}: 예측 ({mx},{my}) @화면({px:.0f},{py:.0f}) → "
          f"판독 {got} (밴드 {at})")
    return {"name": name, "predicted": [mx, my], "screen": [round(px), round(py)],
            "read": list(got) if got else None, "band_at": at}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--row", type=int, default=150)
    ap.add_argument("--pans", type=int, default=10, help="소폭 1 + 광폭 pans-1")
    ap.add_argument("--work", default=str(WORK))
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    telemetry = {"row": args.row, "pans": []}
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            row = plan_rows((1619, 1619))[args.row]
            print(f"행 {args.row} 시작 {row.start}")
            t0 = time.monotonic()
            grid = nav.jump(*row.start)
            frame = cap.grab_fresh()
            nav.capture_detail_ref(frame)
            offset = nav.client_offset(frame)
            tracker = PanTracker(offset)
            Image.fromarray(frame).save(work / "f000_jump.png")
            print(f"점프 완료 {time.monotonic() - t0:.1f}s, 오프셋 {offset}")

            prev = frame
            for k in range(args.pans):
                src, dst = ui.PAN_SHORT if k == 0 else ui.PAN_WIDE
                cmd = dst[0] - src[0]
                frame = nav.pan(src, dst, steps=12 if k == 0 else 24)
                Image.fromarray(frame).save(work / f"f{k + 1:03d}.png")
                last = tracker._last.get(cmd)
                entry = {"pan": k + 1, "cmd": cmd,
                         "expect_last": [round(v) for v in last] if last else None}
                peaks = []
                for i, (y0, h) in enumerate(ui.TRACK_BANDS):
                    yc = y0 + h / 2
                    center = last[i] if last else cmd * pan_gain(yc)
                    peaks.append(band_peaks(prev, frame, (y0, h), offset, center))
                entry["peaks"] = peaks
                try:
                    info = tracker.update(prev, frame, cmd)
                    entry["update"] = info
                    print(f"팬 #{k + 1}: a={info['a']} b={info['b']} "
                          f"rejected={info['rejected']} raw={info['raw']}")
                except TrackLost as exc:
                    entry["track_lost"] = str(exc)
                    print(f"팬 #{k + 1}: TrackLost {exc} — 캡처는 계속")
                telemetry["pans"].append(entry)
                prev = frame

            # 지상 진실: 상단 밴드·하단 밴드 예측 타일 클릭 → 팝업 좌표
            reader = DigitReader()
            truths = []
            for y_client, name in ((215, "top"), (425, "bottom")):
                try:
                    truths.append(click_truth(nav, inp, cap, grid, tracker,
                                              offset, y_client, name, work, reader))
                except Exception as exc:   # 클릭 실패가 캡처 자산을 잃게 하지 않도록
                    print(f"  클릭 {name} 실패: {exc!r}")
                    truths.append({"name": name, "error": repr(exc)})
            telemetry["truths"] = truths

    (work / "telemetry.json").write_text(
        json.dumps(telemetry, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {work}\\telemetry.json + 프레임 {args.pans + 1}장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
