"""T14.1 오프라인 분석 — 캡처 자산으로 오추적 원인을 정량화한다.

입력: work/ 의 f000..f010.png, click_top/bottom.png, telemetry.json
출력(콘솔):
  1) 팬·밴드별 NCC 상위 피크 구조(경쟁 피크 간격 — 격자 주기/수면 주기 가설)
  2) 얇은 밴드(22px) dx(y) 프로파일 — 전단 이동장의 실제 형태(선형성) 확인
  3) 밴드별 물(수면) 비율 — 애니메이션 수면과 저점수·슬립의 상관
  4) 클릭 프레임 선택 링 검출 → 지상 진실 좌표의 정밀 화면 위치
     → 누적 모델(적합 누적 vs 밴드 raw 합산) 오차의 정확한 분해
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.nav import ui                                   # noqa: E402
from mapscan.nav.pan import pan_gain                         # noqa: E402
from mapscan.vision.grid import (GridBasis, GridMapper,      # noqa: E402
                                 find_selection_highlight)

WORK = Path(__file__).resolve().parent / "work"
OFFSET = (1, 31)
ROW_START = (10, 922)
ANCHOR_PX = (1225 + OFFSET[0], 337 + OFFSET[1])


def load(name: str) -> np.ndarray:
    return np.asarray(Image.open(WORK / name).convert("RGB"))


def thin_band_shift(prev, cur, y0f, h, expect, search=450):
    """프레임 y0f부터 h 높이 밴드의 역방향 매칭 dx (광폭 좌팬 전용)."""
    cx0, w_tpl, ox = 10, 450, OFFSET[0]
    tpl = cur[y0f:y0f + h, cx0 + ox:cx0 + w_tpl + ox]
    sy0, sy1 = max(0, y0f - 10), min(prev.shape[0], y0f + h + 10)
    ex = cx0 + ox - int(expect)
    sx0 = max(0, ex - search)
    sx1 = min(prev.shape[1], ex + w_tpl + search)
    res = cv2.matchTemplate(prev[sy0:sy1, sx0:sx1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (px, py) = cv2.minMaxLoc(res)
    return float((cx0 + ox) - (sx0 + px)), float(sy0 + py - y0f), float(score)


def water_fraction(band: np.ndarray) -> float:
    """황토색 수면 비율 — R>G>B이고 R-B가 큰 픽셀."""
    r = band[:, :, 0].astype(int)
    g = band[:, :, 1].astype(int)
    b = band[:, :, 2].astype(int)
    return float(((r > g) & (g > b) & (r - b > 40)).mean())


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    tel = json.loads((WORK / "telemetry.json").read_text(encoding="utf-8"))

    print("=" * 72)
    print("1) NCC 상위 피크 구조 (팬·밴드별, dx/dy/score — 1위와의 간격 주목)")
    for entry in tel["pans"]:
        if entry["cmd"] > -800:
            continue
        print(f"팬 #{entry['pan']}:")
        for i, peaks in enumerate(entry["peaks"]):
            p0 = peaks[0]
            gaps = [round(p[0] - p0[0]) for p in peaks[1:]]
            print(f"  밴드{i}: " + " | ".join(
                f"({p[0]:7.1f},{p[1]:5.1f},{p[2]:6.3f})" for p in peaks)
                + f"  간격{gaps}")

    print("=" * 72)
    print("2) 얇은 밴드 dx(y) 프로파일 + 3) 물 비율 (광폭 팬만)")
    frames = {0: load("f000_jump.png")}
    for i in range(1, len(tel["pans"]) + 1):
        frames[i] = load(f"f{i:03d}.png")
    y0s = list(range(90, 520, 22))
    hdr = "  y_cli: " + " ".join(f"{y - OFFSET[1]:5d}" for y in y0s)
    for entry in tel["pans"]:
        k = entry["pan"]
        if entry["cmd"] > -800:
            continue
        prev, cur = frames[k - 1], frames[k]
        line_dx, line_sc = [], []
        for y0f in y0s:
            yc_cli = y0f + 11 - OFFSET[1]
            expect = entry["cmd"] * pan_gain(yc_cli)
            dx, dy, sc = thin_band_shift(prev, cur, y0f, 22, expect)
            line_dx.append(dx)
            line_sc.append(sc)
        wf = [water_fraction(cur[y0f:y0f + 22, 11:461]) for y0f in y0s]
        print(f"팬 #{k}:")
        print(hdr)
        print("  dx  : " + " ".join(f"{v:5.0f}" for v in line_dx))
        print("  점수: " + " ".join(f"{v:5.2f}" for v in line_sc))
        print("  물  : " + " ".join(f"{v:5.2f}" for v in wf))

    print("=" * 72)
    print("4) 클릭 지상 진실 vs 누적 모델")
    A = sum(e["update"]["a"] for e in tel["pans"] if "update" in e)
    B = sum(e["update"]["b"] for e in tel["pans"] if "update" in e)
    print(f"적합 누적: A={A:.1f} B={B:.4f} "
          f"(TrackLost 팬 {[e['pan'] for e in tel['pans'] if 'track_lost' in e]})")
    grid = GridMapper(GridBasis(), ANCHOR_PX, ROW_START)

    # 밴드 raw 합산 대안 (기각 무시, 슬립 포함): 밴드별 Σdx → 3점 직선 적합
    sums = [0.0, 0.0, 0.0]
    for e in tel["pans"]:
        if "update" not in e:
            continue   # TrackLost 팬은 두 누적 모두에서 빠진다(실이동 유실)
        for i in range(3):
            sums[i] += e["update"]["raw"][i][0]
    ys_f = [y0 + h / 2 + OFFSET[1] for y0, h in ui.TRACK_BANDS]
    b_raw, a_raw = np.polyfit(ys_f, sums, 1)
    print(f"raw 합산: 밴드Σ={[round(s) for s in sums]} → A'={a_raw:.1f} B'={b_raw:.4f}")

    for name, truth in (("top", tel["truths"][0]), ("bottom", tel["truths"][1])):
        frame = load(f"click_{name}.png")
        ring = find_selection_highlight(frame)
        pred = truth["predicted"]
        print(f"클릭 {name}: 예측타일 {pred} 화면 {truth['screen']} 링 {ring}")
        if ring is None:
            continue
        # 실제 타일(팝업 판독값을 코드에 기록)의 모델 화면 위치와 링 비교
        actual = {"top": (114, 815), "bottom": (116, 818)}[name]
        base = grid.to_screen(*actual)
        for label, (aa, bb) in (("적합", (A, B)), ("raw합", (a_raw, b_raw))):
            mx_px = base[0] + aa + bb * base[1]
            err = (ring[0] - mx_px, ring[1] - base[1])
            print(f"  {label}: 모델({mx_px:7.1f},{base[1]:6.1f}) "
                  f"링({ring[0]:7.1f},{ring[1]:6.1f}) 오차 x={err[0]:+7.1f} "
                  f"y={err[1]:+6.1f}px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
