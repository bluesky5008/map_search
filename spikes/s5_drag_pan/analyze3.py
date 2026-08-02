"""S-5 사후 분석 3 — G3 팝업 좌표 판독 실패 원인 (DigitReader 진단)."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.vision import DigitReader

WORK = Path(__file__).parent / "work"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ver = np.asarray(Image.open(WORK / "g3_click.png").convert("RGB"))
    reader = DigitReader()
    # 드라이버와 같은 기준점: 링 중심 (예측 (1809,311) + 링 오차 (51,7))
    cx, cy = 1860, 318
    for dy in range(-205, -119, 8):
        strip = ver[cy + dy:cy + dy + 34, cx - 30:cx + 195]
        text = reader.read(strip)
        if text:
            print(f"  dy={dy:4d}: {text!r} -> coords={reader.read_coords(strip)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
