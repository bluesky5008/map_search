"""T14.3 표본 라벨링 분석 — 경계 밴드 색 분율을 지상 진실과 대조.

sample_tiles.py가 남긴 프레임(tiles_*_frame.png)과 표본 목록(tiles_*.json)에
팝업 판독으로 확정한 지상 진실 라벨을 붙여, 분류기 _occupancy의 색 분율을
표본별로 측정한다. 오탐(절벽·무주 공터 → ally) 억제 임계를 정하는 근거.

오프라인 전용 — 게임 불필요.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.vision import GridBasis  # noqa: E402
from mapscan.vision import classifier as clf_mod  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"

# 팝업 판독 지상 진실 (2026-08-02 라벨링). truth_occ: 기대 점령상태,
# None = 소유 패널이 스트립 밖으로 잘려 불확정(임계 판정에 사용하지 않음).
LABELS = {
    ("occ", 0): ("도시 無名마산동탁 (1016,626) 동맹 FIRST", "ally"),
    ("occ", 1): ("Lv.8 철광 (1023,615) 잠봉", "enemy"),
    ("occ", 2): ("Lv.5 철광 (1017,626) FIRST(행군/주둔)", "ally"),
    ("occ", 3): ("점령 공터 (1023,617) 잠봉", "enemy"),
    ("occ", 4): ("절벽 (1017,627) 점령 불가", "neutral"),
    ("occ", 5): ("점령 공터 (1024,616) 잠봉", "enemy"),
    ("occ", 6): ("Lv.3 철광 (1017,625) 점령버튼·소유 잘림", None),
    ("occ", 7): ("점령 공터 (1024,618) 잠봉", "enemy"),
    ("mine", 0): ("무주 공터 (345,335)", "neutral"),
    ("mine", 1): ("Lv.5 식량 (354,325) 점령형 스프라이트·소유 잘림", None),
}


def band_stats(frame: np.ndarray, px: float, py: float, basis: GridBasis):
    """분류기 _occupancy와 동일한 밴드에서 색 분율 + 변별 통계를 계산한다."""
    m = basis.matrix()
    pts, side = [], []  # side: 0=+v변 1=-v변 2=+u변 3=-u변 (t=변 따라, s=인셋)
    for t in clf_mod._BAND_T:
        for s in clf_mod._BAND_S:
            pts.append((px, py) + m @ (t, s))
            side.append(0 if s > 0 else 1)
            pts.append((px, py) + m @ (s, t))
            side.append(2 if s > 0 else 3)
    pix = np.array(pts).round().astype(int)
    side = np.array(side)
    h, w = frame.shape[:2]
    keep = (pix[:, 0] >= 0) & (pix[:, 0] < w) & (pix[:, 1] >= 0) & (pix[:, 1] < h)
    pix, side = pix[keep], side[keep]
    band = frame[pix[:, 1], pix[:, 0]].reshape(-1, 1, 3)
    hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV).reshape(-1, 3)
    hh, ss, vv = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    n = len(hsv)
    red = ((hh <= 8) | (hh >= 172)) & (ss >= 120) & (vv >= 80)
    blue = (hh >= 90) & (hh <= 130) & (ss >= 70) & (vv >= 90)
    green = (hh >= 40) & (hh <= 75) & (ss >= 150) & (vv >= 170)
    out = {
        "n": n,
        "red": red.sum() / n,
        "blue": blue.sum() / n,
        "green": green.sum() / n,
        "blue_v_med": float(np.median(vv[blue])) if blue.any() else None,
        "blue_s_med": float(np.median(ss[blue])) if blue.any() else None,
        "blue_sides": [float(blue[side == k].sum() / max(1, (side == k).sum()))
                       for k in range(4)],
        "red_sides": [float(red[side == k].sum() / max(1, (side == k).sum()))
                      for k in range(4)],
    }
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    basis = GridBasis()
    clf = clf_mod.TileClassifier()
    for site in ("occ", "mine"):
        frame = np.asarray(Image.open(WORK / f"tiles_{site}_frame.png").convert("RGB"))
        data = json.loads((WORK / f"tiles_{site}.json").read_text(encoding="utf-8"))
        print(f"\n== {site} (점프 {data['jump']}) ==")
        hdr = (f"{'#':>2} {'현재판정':<8} {'기대':<8} {'red%':>6} {'blue%':>6} "
               f"{'grn%':>5} {'bVmed':>5} {'bSmed':>5} 변별(blue측면) 진실")
        print(hdr)
        for s in data["samples"]:
            if "error" in s:
                continue
            key = (site, s["i"])
            truth, want = LABELS[key]
            px, py = s["screen"]
            st = band_stats(frame, px, py, basis)
            cur = clf._occupancy(frame, px, py)
            sides = ",".join(f"{v:.2f}" for v in st["blue_sides"])
            print(f"{s['i']:>2} {cur:<8} {str(want):<8} "
                  f"{st['red'] * 100:>5.1f} {st['blue'] * 100:>5.1f} "
                  f"{st['green'] * 100:>5.1f} "
                  f"{st['blue_v_med'] if st['blue_v_med'] is not None else -1:>5.0f} "
                  f"{st['blue_s_med'] if st['blue_s_med'] is not None else -1:>5.0f} "
                  f"[{sides}] {truth}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
