"""UI 상수 실사 (오프라인) — probe 전후 프레임에서 팝업 기하·링 검출 측정.

클릭 (600,450) 전후 diff의 큰 연결 성분으로 클릭 팝업의 실제 범위를 재고,
선택 타일 중심 상대 범위를 POPUP_RECT_REL과 대조한다. 링 검출도 확인한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.nav import ui
from mapscan.vision.grid import find_selection_highlight

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work"
CLICK = (600, 450)
TILE_CENTER = (600, 409)   # 선택 타일 중심(클릭 검사에서 육안 실측 — 픽 my-1)


def game_crop(path):
    frame = np.asarray(Image.open(path).convert("RGB"))
    border = (frame.shape[1] - 2544) // 2
    oy = frame.shape[0] - 657 - border
    return frame[oy:oy + 657, border:border + 2544]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    before = game_crop(ROOT / "output" / "mumu_probe.png")
    after = game_crop(ROOT / "output" / "mumu_probe_after.png")

    diff = (np.abs(after.astype(np.int16) - before.astype(np.int16))
            .sum(axis=2) > 30).astype(np.uint8)
    diff = cv2.morphologyEx(diff, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
    cx, cy = TILE_CENTER
    print(f"선택 타일 중심 가정 {TILE_CENTER} (클릭 {CLICK})")
    print(f"POPUP_RECTS_REL 현행 {ui.POPUP_RECTS_REL}")
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 3000:
            continue
        boxes.append((x, y, x + w, y + h, area))
        rel = (x - cx, y - cy, x + w - cx, y + h - cy)
        print(f"  변화 성분 abs=({x},{y})-({x + w},{y + h}) 면적={area:6d} "
              f"rel={rel}")
    # 신규 팝업(클릭점 주변 성분들)의 합집합 rel 범위
    near = [b for b in boxes
            if b[0] - cx < 600 and b[2] - cx > -600 and abs((b[1] + b[3]) / 2 - cy) < 350]
    if near:
        u = (min(b[0] for b in near), min(b[1] for b in near),
             max(b[2] for b in near), max(b[3] for b in near))
        rel = (u[0] - cx, u[1] - cy, u[2] - cx, u[3] - cy)
        print(f"클릭점 주변 합집합 abs={u} → rel={rel}")

    ring = find_selection_highlight(after)
    print(f"링 검출: {ring}")
    Image.fromarray((diff * 255)).save(WORK / "ui_survey_diff.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
