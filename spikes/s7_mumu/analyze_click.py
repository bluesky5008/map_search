"""클릭 반응 자동 검출 실패 원인 분석 (오프라인) — 링 후보·팝업 판독."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.vision import DigitReader
from mapscan.vision.grid import (GridBasis, _HIGHLIGHT_MAX_SAT,
                                 _HIGHLIGHT_MIN_VAL, find_selection_highlight)

WORK = Path(__file__).parent / "work"
CLICK_AT = (600, 450)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    game = np.asarray(Image.open(WORK / "click_after_device.png").convert("RGB"))

    # 1) 하이라이트 마스크의 연결 성분을 클릭점 주변에서 나열
    hsv = cv2.cvtColor(game, cv2.COLOR_RGB2HSV)
    mask = ((hsv[:, :, 1] < _HIGHLIGHT_MAX_SAT) &
            (hsv[:, :, 2] > _HIGHLIGHT_MIN_VAL)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    hx, hy = GridBasis().half_extents
    print(f"타일 half_extents=({hx:.1f},{hy:.1f}) — 기대 bbox ~({2*hx:.0f}x{2*hy:.0f})")
    cx, cy = CLICK_AT
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        mx, my = cents[i]
        if abs(mx - cx) < 300 and abs(my - cy) < 300 and area > 40:
            fill = area / (w * h)
            print(f"  성분 bbox=({x},{y},{w}x{h}) 중심=({mx:.0f},{my:.0f}) "
                  f"면적={area} 채움={fill:.2f}")
    print(f"find_selection_highlight → {find_selection_highlight(game)}")

    # 2) 팝업 좌표 강제 판독 — 넓은 영역 전수 + 원시 문자열 출력
    reader = DigitReader(WORK / "digits_mumu")
    hits = {}
    for x0 in range(400, 900, 25):
        for y0 in range(150, 320, 6):
            strip = game[y0:y0 + 34, x0:x0 + 225]
            got = reader.read_coords(strip)
            if got:
                hits[got] = hits.get(got, 0) + 1
    print(f"전수 판독 결과: {sorted(hits.items(), key=lambda kv: -kv[1])}")
    # 육안 좌표줄 부근 원시 판독
    for y0 in (248, 254, 260):
        strip = game[y0:y0 + 34, 620:845]
        print(f"  y0={y0} 원시 '{reader.read(strip)}' / 복구 "
              f"'{reader.read(strip, repair=True)}'")
    Image.fromarray(game[240:290, 500:900]).save(WORK / "click_coord_area.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
