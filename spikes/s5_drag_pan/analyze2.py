"""S-5 사후 분석 2 — 팬이 화면 콘텐츠를 비강체(전단)로 움직이는지 확증한다.

세로로 긴 패치는 전단 시 어느 단일 위치에서도 정합하지 않는다(낮은 NCC).
상/하 절반을 따로 매칭하면 서로 다른 x 이동을 보인다.
"""

import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

WORK = Path(__file__).parent / "work"
OFF = (1, 31)


def load(name):
    return np.asarray(Image.open(WORK / name).convert("RGB"))


def cap_map():
    m = {}
    for line in (WORK / "agent_status.txt").read_text(encoding="utf-8").splitlines():
        g = re.search(r"#(\d+) cap (f_\d+\.png)", line)
        if g:
            m[int(g.group(1))] = g.group(2)
    return m


def match(before, after, rect, dcmd, search=280):
    x, y, w, h = rect
    x, y = x + OFF[0], y + OFF[1]
    tpl = before[y:y + h, x:x + w]
    ex, ey = x + dcmd[0], y + dcmd[1]
    x0, y0 = max(0, ex - search), max(0, ey - search)
    x1 = min(after.shape[1], ex + w + search)
    y1 = min(after.shape[0], ey + h + search)
    res = cv2.matchTemplate(after[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (px, py) = cv2.minMaxLoc(res)
    return (x0 + px - x, y0 + py - y, round(float(score), 3))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    caps = cap_map()
    # G3 팬#5 (cmd #146): 팝업 없음, 점수 양호했던 프레임 쌍
    before, after = load(caps[145]), load(caps[147])
    tall = (1900, 150, 300, 320)
    top_half = (1900, 150, 300, 160)
    bot_half = (1900, 310, 300, 160)
    for name, rect in [("tall(320px)", tall), ("top_half", top_half),
                       ("bot_half", bot_half)]:
        dx, dy, sc = match(before, after, rect, (-480, 0))
        print(f"  {name:12s}: ({dx:5d},{dy:4d}) 점수 {sc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
