"""게이트 5 — 팝업 좌표를 제품과 같은 최빈값 투표로 판독하고 표를 출력한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
from PIL import Image

from mapscan.vision import DigitReader

WORK = Path(__file__).parent / "work"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    game = np.asarray(Image.open(WORK / "game_exact.png").convert("RGB"))
    reader = DigitReader()
    votes: dict[tuple[int, int], int] = {}
    samples: dict[tuple[int, int], tuple[int, int]] = {}
    for x0 in range(1100, 1700, 25):
        for y0 in range(70, 220, 6):
            strip = game[y0:y0 + 34, x0:x0 + 225]
            got = reader.read_coords(strip)
            if got:
                votes[got] = votes.get(got, 0) + 1
                samples.setdefault(got, (x0, y0))
    for got, n in sorted(votes.items(), key=lambda kv: -kv[1]):
        x0, y0 = samples[got]
        print(f"  {got}  표 {n:3d}  (예: x0={x0}, y0={y0})")
    if votes:
        best = max(votes.items(), key=lambda kv: kv[1])[0]
        x0, y0 = samples[best]
        Image.fromarray(game[y0:y0 + 34, x0:x0 + 225]).save(WORK / "g5_best_strip.png")
        # 원시 판독 문자열도 확인(오판독 글리프 위치 파악)
        raw = reader.read(game[y0:y0 + 34, x0:x0 + 225])
        raw_rep = reader.read(game[y0:y0 + 34, x0:x0 + 225], repair=True)
        print(f"최빈값: {best} | 원시 '{raw}' / 복구 '{raw_rep}'")
    else:
        print("판독 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
