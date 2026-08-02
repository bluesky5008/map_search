"""S-5 추가 — 광폭 왕복(좌 1900 → 우 1900) 순변위 확인 (w0 vs w2)."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from analyze import shift_subpx  # noqa: E402

WORK = Path(__file__).parent / "work"


def load(name):
    return np.asarray(Image.open(WORK / name).convert("RGB"))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    w0, w2 = load("w0.png"), load("w2.png")
    for p in [("top", 1460, 96, 760, 62), ("mid", 1700, 240, 400, 80),
              ("bot", 1700, 400, 400, 70)]:
        dx, dy, sc = shift_subpx(w0, w2, p, (0, 0), search=260)
        print(f"  {p[0]}: 순변위 ({dx:7.2f},{dy:6.2f}) 점수 {sc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
