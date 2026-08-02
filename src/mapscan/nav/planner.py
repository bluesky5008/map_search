"""방문 계획 생성 (설계 §2 ScanPlanner, §4.3 / AC-03, AC-05).

방문당 커버리지는 GridMapper.visible_cells에서 HUD·선택 팝업 오클루전을 제외한
오프셋 집합이다. 오클루전 구멍 때문에 축정렬 사각형 타일링은 비효율적이므로
**잉여류 타일링**을 쓴다: 보폭 (sx,sy)로 시프트한 오프셋 집합들의 합집합이
평면을 완전히 덮으려면 오프셋들의 (mod sx, mod sy) 잉여류가 sx·sy 전부를
덮으면 된다. 그 조건을 만족하는 최대 면적 보폭을 고른다.

맵 경계에서는 방문 중심을 [0, map_max]로 클램프하면서 위상이 어긋나 구멍이
생길 수 있어, 계획 생성 시 커버리지 비트맵으로 검사해 보충 방문을 덧붙인다
(AC-05와 같은 메커니즘). 계획은 같은 입력에 대해 결정적으로 재생성되므로
체크포인트 인덱스만으로 재개할 수 있다(AC-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

import numpy as np

from ..vision import GridBasis, GridMapper
from . import ui


@dataclass(frozen=True)
class Visit:
    index: int
    center: tuple[int, int]


class ScanPlanner:
    def __init__(self, map_max: tuple[int, int],
                 basis: GridBasis = GridBasis(),
                 client_size: tuple[int, int] = (2544, 657),
                 hud_rects: Iterable[tuple[int, int, int, int]] | None = None,
                 popup_rects: Iterable[tuple[int, int, int, int]] | None = None):
        self.map_max = map_max
        self.basis = basis
        self.client_size = client_size
        hud = list(ui.HUD_RECTS_CLIENT if hud_rects is None else hud_rects)
        popup = list(ui.POPUP_RECTS_REL if popup_rects is None else popup_rects)
        self.offsets = _coverage_offsets(basis, client_size, hud, popup)
        if not self.offsets:
            raise ValueError("커버리지 없음 — 오클루전이 화면 전체를 덮습니다")
        self.stride = _best_stride(self.offsets)
        self._ox = np.array([o[0] for o in sorted(self.offsets)])
        self._oy = np.array([o[1] for o in sorted(self.offsets)])
        self._plan: list[Visit] | None = None

    # -- 방문 좌표열 -------------------------------------------------------

    def visits(self) -> list[Visit]:
        """뱀형 기본 격자 + 경계 보충. 전 좌표 커버가 보장된다."""
        if self._plan is not None:
            return self._plan
        centers = self._snake_centers()
        grid = np.zeros((self.map_max[1] + 1, self.map_max[0] + 1), dtype=bool)
        for c in centers:
            self._mark(grid, c)
        for c in self._fill_gaps(grid):
            centers.append(c)
        self._plan = [Visit(i, c) for i, c in enumerate(centers)]
        return self._plan

    def resume_from(self, checkpoint: int) -> Iterator[Visit]:
        """마지막 완료 인덱스 다음부터. checkpoint=0은 처음부터."""
        return iter(self.visits()[checkpoint:])

    # -- 커버리지 ----------------------------------------------------------

    def covered(self, center: tuple[int, int]) -> Iterator[tuple[int, int]]:
        """방문이 커버하는 맵 좌표들."""
        for ox, oy in self.offsets:
            mx, my = center[0] + ox, center[1] + oy
            if 0 <= mx <= self.map_max[0] and 0 <= my <= self.map_max[1]:
                yield mx, my

    def supplemental_visits(self, missing: set[tuple[int, int]],
                            start_index: int) -> list[Visit]:
        """미커버 좌표를 덮는 보충 방문(AC-05). 결정적 탐욕 선택."""
        grid = np.ones((self.map_max[1] + 1, self.map_max[0] + 1), dtype=bool)
        for mx, my in missing:
            grid[my, mx] = False
        return [Visit(start_index + i, c)
                for i, c in enumerate(self._fill_gaps(grid))]

    # -- 내부 --------------------------------------------------------------

    def _snake_centers(self) -> list[tuple[int, int]]:
        sx, sy = self.stride
        max_ox = max(o[0] for o in self.offsets)
        min_ox = min(o[0] for o in self.offsets)
        max_oy = max(o[1] for o in self.offsets)
        min_oy = min(o[1] for o in self.offsets)
        xs = _dedup(_clamp(v, 0, self.map_max[0]) for v in
                    range(-max_ox, self.map_max[0] - min_ox + sx, sx))
        ys = _dedup(_clamp(v, 0, self.map_max[1]) for v in
                    range(-max_oy, self.map_max[1] - min_oy + sy, sy))
        out: list[tuple[int, int]] = []
        for row, cy in enumerate(ys):
            for cx in (xs if row % 2 == 0 else reversed(xs)):
                out.append((cx, cy))
        return out

    def _mark(self, grid: np.ndarray, center: tuple[int, int]) -> None:
        mx, my = self._ox + center[0], self._oy + center[1]
        ok = ((mx >= 0) & (mx <= self.map_max[0]) &
              (my >= 0) & (my <= self.map_max[1]))
        grid[my[ok], mx[ok]] = True

    def _fill_gaps(self, grid: np.ndarray) -> list[tuple[int, int]]:
        """비트맵에서 False인 좌표가 없어질 때까지 보충 방문을 추가한다."""
        cx_off = (max(o[0] for o in self.offsets) + min(o[0] for o in self.offsets)) // 2
        cy_off = (max(o[1] for o in self.offsets) + min(o[1] for o in self.offsets)) // 2
        out: list[tuple[int, int]] = []
        while True:
            holes = np.argwhere(~grid)
            if len(holes) == 0:
                return out
            my, mx = (int(v) for v in holes[0])  # 결정적 순서 (행 우선)
            center = (_clamp(mx - cx_off, 0, self.map_max[0]),
                      _clamp(my - cy_off, 0, self.map_max[1]))
            if not grid[my, mx] and (mx - center[0], my - center[1]) not in self.offsets:
                # 중앙 정렬로 해당 구멍을 못 덮으면, 구멍을 직접 덮는 오프셋 선택
                for ox, oy in sorted(self.offsets):
                    c = (mx - ox, my - oy)
                    if 0 <= c[0] <= self.map_max[0] and 0 <= c[1] <= self.map_max[1]:
                        center = c
                        break
                else:
                    raise RuntimeError(f"커버 불가 좌표: ({mx},{my})")
            self._mark(grid, center)
            out.append(center)


def _coverage_offsets(basis: GridBasis, client_size: tuple[int, int],
                      hud: list[tuple[int, int, int, int]],
                      popup: list[tuple[int, int, int, int]]) -> set[tuple[int, int]]:
    """화면 중앙에 앵커를 둔 방문 하나가 커버하는 맵 오프셋 집합."""
    cx, cy = client_size[0] / 2, client_size[1] / 2
    grid = GridMapper(basis, (cx, cy), (0, 0))
    exclude = hud + [(cx + x0, cy + y0, cx + x1, cy + y1)
                     for x0, y0, x1, y1 in popup]
    return {(c.mx, c.my) for c in grid.visible_cells(client_size, exclude=exclude)}


def _best_stride(offsets: set[tuple[int, int]]) -> tuple[int, int]:
    """잉여류가 (mod sx, mod sy) 전 클래스를 덮는 최대 면적 보폭."""
    span_x = max(o[0] for o in offsets) - min(o[0] for o in offsets) + 1
    span_y = max(o[1] for o in offsets) - min(o[1] for o in offsets) + 1
    best = (1, 1)
    for sx in range(1, span_x + 1):
        for sy in range(1, span_y + 1):
            if sx * sy <= best[0] * best[1]:
                continue
            residues = {(ox % sx, oy % sy) for ox, oy in offsets}
            if len(residues) == sx * sy:
                best = (sx, sy)
    return best


def _dedup(seq: Iterable[int]) -> list[int]:
    out: list[int] = []
    for v in seq:
        if not out or v != out[-1]:
            out.append(v)
    return out


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
