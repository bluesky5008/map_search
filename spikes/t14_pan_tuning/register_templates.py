"""T14.3 점령형 템플릿 등록 + 회귀 픽스처 추출.

sample_tiles.py가 남긴 프레임에서, 팝업 진실로 라벨링된 표본 셀을
① 96x64 템플릿(assets/templates/tiles/)과 ② 240x160 회귀 픽스처(work/)로
잘라 저장하고, 분류기로 재검증한다. 좌표·진실 근거는 analyze_tiles.LABELS.

오프라인 전용 — 게임 불필요. 산출물은 커밋 대상.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.vision import TileClassifier  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "work"
TILES = REPO / "assets" / "templates" / "tiles"

# (site, i) → 템플릿 파일명(없으면 픽스처만). 셀 중심은 tiles_{site}.json의 screen.
# 템플릿 96x64는 wood.png와 동일 규격(타일 중심 크롭, 스캔 창 2544x657 기준).
TARGETS = [
    ("occ", 2, (340, 438), "iron_occ"),    # Lv.5 철광 점령형(FIRST) — 정탐 ally
    ("occ", 4, (284, 483), None),          # 절벽·강 인접 — ally 오탐 회귀(중립 기대)
    ("occ", 5, (1902, 339), None),         # 점령 공터(잠봉) — 정탐 enemy
    ("mine", 0, (396, 393), None),         # 무주 공터 — ally 오탐 회귀(중립 기대)
    ("mine", 1, (1957, 294), "food_occ"),  # Lv.5 식량 점령형(밭)
]
TPL_HALF = (48, 32)
FIX_HALF = (120, 80)


def crop(frame: np.ndarray, cx: int, cy: int, half: tuple[int, int]) -> np.ndarray:
    return frame[cy - half[1]:cy + half[1], cx - half[0]:cx + half[0]]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    frames = {s: np.asarray(Image.open(WORK / f"tiles_{s}_frame.png").convert("RGB"))
              for s in ("occ", "mine")}
    for site, i, (cx, cy), tpl_name in TARGETS:
        frame = frames[site]
        fix = crop(frame, cx, cy, FIX_HALF)
        Image.fromarray(fix).save(WORK / f"tiles_{site}_{i:02d}_cell.png")
        if tpl_name:
            Image.fromarray(crop(frame, cx, cy, TPL_HALF)).save(
                TILES / f"{tpl_name}.png")
            print(f"템플릿 {tpl_name}.png <- {site}#{i} ({cx},{cy})")
    # 재검증: 픽스처 중심 셀을 새 분류기로 판정
    clf = TileClassifier()
    for site, i, _, _ in TARGETS:
        fix = np.asarray(Image.open(
            WORK / f"tiles_{site}_{i:02d}_cell.png").convert("RGB"))
        r = clf.classify(fix, FIX_HALF[0], FIX_HALF[1])
        print(f"{site}#{i}: {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
