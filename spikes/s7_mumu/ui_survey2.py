"""UI 실사 2 — Lv.4 식량 팝업(4버튼+4아이콘)의 정밀 rel 범위 + 링 후보 치수.

선택 타일 중심을 하이라이트 마스크 성분에서 직접 구해(육안 추정 배제)
팝업 rel 범위와 링 검출 실패 원인(성분 치수)을 기록한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.nav import ui
from mapscan.vision.grid import (GridBasis, _HIGHLIGHT_MAX_SAT,
                                 _HIGHLIGHT_MIN_VAL)

ROOT = Path(__file__).resolve().parents[2]
CLICK = (600, 450)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    frame = np.asarray(Image.open(ROOT / "output" / "mumu_probe_after.png")
                       .convert("RGB"))
    border = (frame.shape[1] - 2544) // 2
    oy = frame.shape[0] - 657 - border
    game = frame[oy:oy + 657, border:border + 2544]

    hsv = cv2.cvtColor(game, cv2.COLOR_RGB2HSV)
    mask = ((hsv[:, :, 1] < _HIGHLIGHT_MAX_SAT) &
            (hsv[:, :, 2] > _HIGHLIGHT_MIN_VAL)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    hx, hy = GridBasis().half_extents
    print(f"기대 링 bbox ~({2 * hx:.0f}x{2 * hy:.0f}), 클릭 {CLICK}")
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        mx, my = cents[i]
        if abs(mx - CLICK[0]) < 200 and abs(my - CLICK[1]) < 200 and area > 100:
            fill = area / (w * h)
            print(f"  성분 bbox=({x},{y},{w}x{h}) 중심=({mx:.0f},{my:.0f}) "
                  f"면적={area} 채움={fill:.2f}")
            if best is None or area > best[4]:
                best = (x, y, w, h, area, mx, my)
    if best is None:
        print("클릭 주변 하이라이트 성분 없음")
        return 1
    x, y, w, h, area, mx, my = best
    cx, cy = mx, my
    print(f"\n타일 중심(최대 성분 중심) = ({cx:.0f},{cy:.0f})")

    # 팝업 요소 절대 좌표(위 프레임 육안 실측 game 좌표) → rel
    parts = {
        "정찰 패널": (226, 304, 419, 425),
        "제목/좌표": (436, 278, 648, 325),
        "아이콘 4": (457, 348, 637, 380),
        "버튼 4열": (673, 310, 855, 522),
        "군사스킬 칩": (508, 571, 598, 628),
    }
    lo_x = lo_y = 10 ** 9
    hi_x = hi_y = -10 ** 9
    for name, (x0, y0, x1, y1) in parts.items():
        rel = (round(x0 - cx), round(y0 - cy), round(x1 - cx), round(y1 - cy))
        lo_x, lo_y = min(lo_x, rel[0]), min(lo_y, rel[1])
        hi_x, hi_y = max(hi_x, rel[2]), max(hi_y, rel[3])
        print(f"  {name:8s} rel=({rel[0]:4d},{rel[1]:4d})-({rel[2]:4d},{rel[3]:4d})")
    print(f"합집합 rel=({lo_x},{lo_y})-({hi_x},{hi_y}) | 현행 {ui.POPUP_RECTS_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
