"""화면 픽셀 ↔ 맵 좌표 변환과 선택 하이라이트 앵커 (설계 §2 GridMapper, §4.3).

스캔 창 캡처 정밀 실측(2026-08-02, spikes/s2_zoom_grid/work3/snap_click_R.png):

- 타일 격자는 2:1 등각 마름모가 아니라 **일반 평행사변형 격자**다.
  +mx는 화면 우하 방향(E_MX), +my는 화면 좌하 방향(E_MY)으로 진행한다.
- 좌표 점프·클릭 후 표시되는 선택 하이라이트(크림색 링)는 타일 경계와 정확히
  일치한다(인셋 없음). 앵커에서 1900px 떨어진 도시 타일 테두리와도 수 px 이내로
  정합함을 오버레이로 확인했다.

기저 벡터는 창 크기·줌 단계에 따라 달라진다. 아래 상수는 표준 스캔 창
(클라이언트 2544x657, 디테일 줌 최대 축소) 실측값이며 생성자에서 교체할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

# 표준 스캔 창(2544x657) 실측 기저: 하이라이트 링 4변의 Hough 직선 교점에서 산출
SCAN_E_MX = (99.5, 49.0)
SCAN_E_MY = (-55.5, 45.0)

# 선택 하이라이트 링 색: 크림색(저채도·고명도). 실측 HSV ≈ (27, 55~75, 200~255)
_HIGHLIGHT_MAX_SAT = 100
_HIGHLIGHT_MIN_VAL = 195
_RING_SIZE_TOL = 0.3   # 링 bbox가 타일 bbox와 이 비율 이내로 일치해야 한다
_RING_MAX_FILL = 0.3   # 링은 속이 빈 외곽선이다 (실측 채움비 ~0.02)


class AnchorNotFound(RuntimeError):
    """프레임에서 선택 하이라이트를 찾지 못했다."""


@dataclass(frozen=True)
class GridBasis:
    """타일 한 칸 이동에 대응하는 화면 픽셀 기저 벡터."""

    e_mx: tuple[float, float] = SCAN_E_MX
    e_my: tuple[float, float] = SCAN_E_MY

    @property
    def half_extents(self) -> tuple[float, float]:
        """타일 평행사변형의 축 정렬 반폭·반높이(px)."""
        return ((abs(self.e_mx[0]) + abs(self.e_my[0])) / 2,
                (abs(self.e_mx[1]) + abs(self.e_my[1])) / 2)

    def matrix(self) -> np.ndarray:
        """열벡터 [e_mx e_my]의 2x2 행렬 (맵 증분 → 화면 증분)."""
        return np.array([[self.e_mx[0], self.e_my[0]],
                         [self.e_mx[1], self.e_my[1]]], dtype=np.float64)


@dataclass(frozen=True)
class Cell:
    """가시 타일 하나: 맵 좌표와 화면(프레임) 중심 픽셀."""

    mx: int
    my: int
    px: float
    py: float


class GridMapper:
    """앵커(맵 좌표를 아는 화면 지점) 기준의 맵 ↔ 프레임 픽셀 변환."""

    def __init__(self, basis: GridBasis, anchor_px: tuple[float, float],
                 anchor_map: tuple[int, int]):
        self.basis = basis
        self.anchor_px = anchor_px
        self.anchor_map = anchor_map
        self._m = basis.matrix()
        self._inv = np.linalg.inv(self._m)

    @classmethod
    def from_frame(cls, frame: np.ndarray, anchor_map: tuple[int, int],
                   basis: GridBasis = GridBasis()) -> "GridMapper":
        """프레임의 선택 하이라이트를 앵커 타일로 삼아 그리드를 확정한다."""
        center = find_selection_highlight(frame, basis)
        if center is None:
            raise AnchorNotFound("선택 하이라이트를 찾지 못했습니다")
        return cls(basis, center, anchor_map)

    def to_screen(self, mx: float, my: float) -> tuple[float, float]:
        d = self._m @ (mx - self.anchor_map[0], my - self.anchor_map[1])
        return self.anchor_px[0] + d[0], self.anchor_px[1] + d[1]

    def to_map(self, px: float, py: float) -> tuple[float, float]:
        d = self._inv @ (px - self.anchor_px[0], py - self.anchor_px[1])
        return self.anchor_map[0] + d[0], self.anchor_map[1] + d[1]

    def nearest_tile(self, px: float, py: float) -> tuple[int, int]:
        """픽셀을 포함하는 타일의 맵 좌표."""
        mx, my = self.to_map(px, py)
        return round(mx), round(my)

    def visible_cells(self, frame_size: tuple[int, int],
                      exclude: Iterable[tuple[int, int, int, int]] = ()
                      ) -> list[Cell]:
        """셀 전체가 프레임 안에 있고 제외 영역과 겹치지 않는 타일들.

        exclude: (x0, y0, x1, y1) 사각형 목록 — HUD·팝업 등 오클루전 영역.
        프레임 경계는 셀 bbox 기준(템플릿 탐색 여유 포함), 제외 영역은 셀의
        실제 평행사변형 기준으로 판정한다(bbox 후광으로 커버리지가 줄지 않도록).
        """
        w, h = frame_size
        hx, hy = self.basis.half_extents
        excl = list(exclude)
        corners = [self.to_map(x, y) for x, y in
                   ((0, 0), (w, 0), (0, h), (w, h))]
        mxs = [c[0] for c in corners]
        mys = [c[1] for c in corners]
        cells = []
        for mx in range(round(min(mxs)) - 1, round(max(mxs)) + 2):
            for my in range(round(min(mys)) - 1, round(max(mys)) + 2):
                px, py = self.to_screen(mx, my)
                if not (hx <= px <= w - hx and hy <= py <= h - hy):
                    continue
                if any(_cell_intersects_rect((px, py), self.basis, r) for r in excl):
                    continue
                cells.append(Cell(mx, my, px, py))
        return cells


def _cell_intersects_rect(center: tuple[float, float], basis: GridBasis,
                          rect: tuple[float, float, float, float]) -> bool:
    """타일 평행사변형과 축정렬 사각형의 교차 여부 (분리축 정리).

    분리축 후보: 사각형의 x·y축 + 평행사변형 두 변의 법선.
    """
    cx, cy = center
    x0, y0, x1, y1 = rect
    e1 = np.array(basis.e_mx)
    e2 = np.array(basis.e_my)
    # 축 1·2: x, y (사각형 법선) — 평행사변형의 축상 반경은 half_extents
    hx, hy = basis.half_extents
    if cx + hx <= x0 or x1 <= cx - hx or cy + hy <= y0 or y1 <= cy - hy:
        return False
    # 축 3·4: 평행사변형 변의 법선
    rect_pts = np.array([(x0, y0), (x1, y0), (x0, y1), (x1, y1)], dtype=np.float64)
    for ev in (e1, e2):
        axis = np.array([-ev[1], ev[0]])
        para_r = abs(axis @ e1) / 2 + abs(axis @ e2) / 2
        para_c = axis @ (cx, cy)
        proj = rect_pts @ axis
        if para_c + para_r <= proj.min() or proj.max() <= para_c - para_r:
            return False
    return True


def find_selection_highlight(frame: np.ndarray,
                             basis: GridBasis = GridBasis()
                             ) -> tuple[float, float] | None:
    """프레임(RGB)에서 선택 하이라이트 링의 중심 픽셀을 찾는다.

    크림색 저채도·고명도 마스크의 연결 성분 중 bbox가 타일 크기와 맞고 속이
    빈(링) 것을 고른다. 후보가 여럿이면 크기가 가장 잘 맞는 것을 반환한다.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    mask = ((hsv[:, :, 1] < _HIGHLIGHT_MAX_SAT) &
            (hsv[:, :, 2] > _HIGHLIGHT_MIN_VAL)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    hx, hy = basis.half_extents
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best: tuple[float, int] | None = None  # (크기 오차, 성분 번호)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        err = max(abs(w - 2 * hx) / (2 * hx), abs(h - 2 * hy) / (2 * hy))
        if err > _RING_SIZE_TOL or area / (w * h) > _RING_MAX_FILL:
            continue
        if best is None or err < best[0]:
            best = (err, i)
    if best is None:
        return None
    ys, xs = np.nonzero(labels == best[1])
    return _parallelogram_center(np.stack([xs, ys], axis=1).astype(np.float64), basis)


def _parallelogram_center(pts: np.ndarray, basis: GridBasis) -> tuple[float, float]:
    """링 픽셀들을 두 변의 법선 방향으로 사영해 평행사변형 중심을 구한다.

    bbox 중심과 달리 모서리 일부가 가려져도 평행한 두 변이 남아 있으면 정확하다.
    """
    normals = []
    for ex, ey in (basis.e_mx, basis.e_my):
        n = np.array([-ey, ex], dtype=np.float64)
        normals.append(n / np.linalg.norm(n))
    mids = []
    for n in normals:
        t = pts @ n
        mids.append((t.min() + t.max()) / 2)
    center = np.linalg.solve(np.stack(normals), np.array(mids))
    return float(center[0]), float(center[1])
