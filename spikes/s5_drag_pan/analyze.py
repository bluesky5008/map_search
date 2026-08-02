"""S-5 사후 분석 — 저장된 프레임만으로 팬 이동의 성질을 판별한다 (게임 비접촉).

질문 1: 팬 이동량이 화면 높이(상/중/하 패치)에 따라 다른가? (시차 가설)
질문 2: 팬 사이·클릭 전 늦은 정착(late drift)이 있는가?
질문 3: 우측 드래그 게인 이상(0.62)은 우측 HUD 패널 가림 아티팩트인가?
"""

import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

WORK = Path(__file__).parent / "work"
OFF = (1, 31)   # 프레임 내 클라이언트 원점 (2546x689 실측)

# (이름, 클라이언트 x, y, w, h) — 팝업·HUD와 겹치지 않는 세 높이
PATCHES = [
    ("top", 1460, 96, 760, 62),
    ("mid", 1700, 240, 400, 80),
    ("bot", 1700, 400, 400, 70),
]


def load(name):
    return np.asarray(Image.open(WORK / name).convert("RGB"))


def cap_map():
    """agent_status.txt에서 명령 번호 → 캡처 파일명 대응을 만든다."""
    m = {}
    for line in (WORK / "agent_status.txt").read_text(encoding="utf-8").splitlines():
        g = re.search(r"#(\d+) cap (f_\d+\.png)", line)
        if g:
            m[int(g.group(1))] = g.group(2)
    return m


def shift_subpx(before, after, patch, dcmd, search=280):
    """패치의 이동량을 서브픽셀(포물선 보간)로 측정한다."""
    _, x, y, w, h = patch
    x, y = x + OFF[0], y + OFF[1]
    tpl = before[y:y + h, x:x + w]
    ex, ey = x + dcmd[0], y + dcmd[1]
    x0, y0 = max(0, ex - search), max(0, ey - search)
    x1 = min(after.shape[1], ex + w + search)
    y1 = min(after.shape[0], ey + h + search)
    res = cv2.matchTemplate(after[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (px, py) = cv2.minMaxLoc(res)

    def para(v_m, v_0, v_p):
        d = v_m - 2 * v_0 + v_p
        return 0.0 if d == 0 else 0.5 * (v_m - v_p) / d

    sx = para(*res[py, px - 1:px + 2]) if 0 < px < res.shape[1] - 1 else 0.0
    sy = para(*(res[py - 1:py + 2, px])) if 0 < py < res.shape[0] - 1 else 0.0
    return (x0 + px + sx - x, y0 + py + sy - y, round(float(score), 3))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    caps = cap_map()

    print("== 질문 1: G3 좌측 팬 10회 — 상/중/하 패치 이동량 비교")
    g3_drags = list(range(134, 162, 3))
    sums = {n: [0.0, 0.0] for n, *_ in PATCHES}
    for i, cmd in enumerate(g3_drags):
        before, after = load(caps[cmd - 1]), load(caps[cmd + 1])
        row = []
        for p in PATCHES:
            dx, dy, sc = shift_subpx(before, after, p, (-444, 0))
            sums[p[0]][0] += dx
            sums[p[0]][1] += dy
            row.append(f"{p[0]} ({dx:7.2f},{dy:6.2f}) s{sc}")
        print(f"  팬#{i + 1:2d}: " + " | ".join(row))
    for name, (tx, ty) in sums.items():
        print(f"  누적 {name}: ({tx:.1f}, {ty:.1f})")

    print("\n== 질문 2: 늦은 정착 — 팬10 후 → 클릭 전 → 클릭 후(1.2s)")
    a10, pre, ver = load(caps[162]), load(caps[163]), load(caps[165])
    for lbl, f1, f2 in [("after10->pre", a10, pre), ("pre->ver(클릭)", pre, ver)]:
        dx, dy, sc = shift_subpx(f1, f2, PATCHES[2], (0, 0), search=150)
        print(f"  {lbl}: ({dx:.2f},{dy:.2f}) s{sc}")

    print("\n== 질문 3: G2 드래그를 세 패치로 재측정 (좌#58, 우#63)")
    for cmd, dcmd, lbl in [(58, (-444, 0), "left"), (63, (444, 0), "right"),
                           (63, (324, -22), "right(주창)")]:
        before, after = load(caps[cmd - 1]), load(caps[cmd + 1])
        row = []
        for p in PATCHES:
            # 우측 드래그는 상단 스트립이 우측 패널 밑으로 들어가므로
            # 좌측에 둔 보조 패치도 함께 확인한다
            dx, dy, sc = shift_subpx(before, after, p, dcmd)
            row.append(f"{p[0]} ({dx:7.2f},{dy:6.2f}) s{sc}")
        aux = ("aux", 900, 96, 700, 62)
        dx, dy, sc = shift_subpx(before, after, aux, dcmd)
        row.append(f"aux ({dx:7.2f},{dy:6.2f}) s{sc}")
        print(f"  {lbl} #{cmd}: " + " | ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
