"""S-5 추가 — 광폭 드래그(±1900px) 이동량 측정 (w0→w1→w2).

이동량이 커서 패치가 프레임 밖으로 나가지 않도록 방향별로 배치한다.
기대 게인(스파이크 실측): top 0.853 / mid 0.928 / bot ~1.0 × 1900px.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from analyze import shift_subpx  # noqa: E402  (사후 분석 헬퍼 재사용)

WORK = Path(__file__).parent / "work"
LEFT_PATCHES = [
    ("top", 1750, 96, 470, 62),
    ("mid", 1900, 240, 300, 80),
    ("bot", 1950, 400, 300, 70),
]
RIGHT_PATCHES = [  # 좌측 HUD(아이콘 그리드 y55~175, 좌하 버튼 y440~)를 피한 배치
    ("mid", 60, 240, 300, 80),
    ("bot", 60, 390, 300, 50),
]


def load(name):
    return np.asarray(Image.open(WORK / name).convert("RGB"))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    w0, w1, w2 = load("w0.png"), load("w1.png"), load("w2.png")
    for lbl, a, b, sign, patches in [("좌 1900", w0, w1, -1, LEFT_PATCHES),
                                     ("우 1900", w1, w2, +1, RIGHT_PATCHES)]:
        row = []
        for p in patches:
            gain = {"top": 0.853, "mid": 0.928, "bot": 1.0}[p[0]]
            dcmd = (round(sign * 1900 * gain), 0)
            dx, dy, sc = shift_subpx(a, b, p, dcmd, search=200)
            row.append(f"{p[0]} ({dx:8.2f},{dy:6.2f}) s{sc}")
        print(f"  {lbl}: " + " | ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
