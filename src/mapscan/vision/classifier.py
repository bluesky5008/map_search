"""타일 셀 분류 (설계 §2 TileClassifier / FR-03b, FR-05, FR-08).

파이프라인: ① 경계 밴드 색 → 점령상태 ② 스프라이트 템플릿 매칭(NCC) → 종류
③ 중립 지형 휴리스틱(공터·강) ④ 그 외는 보수적으로 미상(FR-08, NFR-04).

임계값 실측 근거(스캔 창 캡처 edge-band·interior 통계, 2026-08-02):
- 적군 빨강 테두리: 해당 색 분율 2~3% vs 비점령 타일 0.0%
- 파랑 계열 테두리: 7~11% vs 비점령 0.0~0.3% (동맹/우호 V 분리는 잠정)
- 내땅 초록 테두리는 표본 미확보 — 잔디(H 35~85, S 중앙값 ~100)와 겹치지
  않도록 고채도·고명도 잠정 임계. T14 실기 표본으로 확정한다.
- 점령된 자원 타일은 스프라이트가 생산 시설(밭 등)로 바뀜을 확인 —
  점령형 템플릿 미확보 상태에서는 종류를 미상으로 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .grid import GridBasis

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "assets" / "templates" / "tiles"

# 템플릿 파일명(ASCII) → (category, kind)
TEMPLATE_KINDS: dict[str, tuple[str, str]] = {
    "wood": ("resource", "목재"),
}
MATCH_THRESHOLD = 0.5
_MATCH_SLACK = 8  # 그리드 오차 허용 탐색 여유(px)

# 경계 밴드 표본 위치: 변 안쪽 0.30~0.42, 변 방향 ±0.42.
# 바깥쪽(>=0.44)은 이웃 타일 테두리가 번져 판별 불가(실측). 반대로 테두리
# 인셋이 깊은 일부 점령 스프라이트(빈 밭 등)는 이 밴드를 벗어나 놓칠 수 있다
# — 알려진 한계, T14 실기 표본으로 재조정한다.
_BAND_T = np.arange(-0.42, 0.421, 0.02)
_BAND_S = np.concatenate([np.arange(0.30, 0.421, 0.02),
                          np.arange(-0.42, -0.299, 0.02)])

_RED_MIN_FRACTION = 0.015
_BLUE_MIN_FRACTION = 0.03
_GREEN_MIN_FRACTION = 0.03      # 잠정(표본 미확보)
_BLUE_ALLY_MAX_VAL = 170        # 잠정: 짙은파랑(동맹) V<170, 하늘색(우호) V>=170

_INTERIOR_SCALE = 0.7
_PLAIN_MIN_GRASS = 0.75
_PLAIN_MAX_LOWSAT = 0.10
_PLAIN_MAX_LAPLACIAN = 22.0
_WATER_MIN_FRACTION = 0.5


@dataclass(frozen=True)
class TileResult:
    category: str    # resource|building1|building2|impassable|unknown
    kind: str
    occupancy: str   # mine|ally|friendly|enemy|neutral
    confidence: float


class TileClassifier:
    def __init__(self, basis: GridBasis = GridBasis(),
                 template_dir: Path | str = DEFAULT_DIR):
        self.basis = basis
        self._templates: dict[str, np.ndarray] = {}
        for path in sorted(Path(template_dir).glob("*.png")):
            if path.stem in TEMPLATE_KINDS:
                self._templates[path.stem] = np.asarray(Image.open(path).convert("RGB"))

    def classify(self, frame: np.ndarray, px: float, py: float) -> TileResult:
        """프레임(RGB)에서 중심 (px,py)인 타일 하나를 분류한다."""
        occupancy = self._occupancy(frame, px, py)
        name, score = self._best_template(frame, px, py)
        if name is not None and score >= MATCH_THRESHOLD:
            category, kind = TEMPLATE_KINDS[name]
            return TileResult(category, kind, occupancy, round(float(score), 3))
        if occupancy != "neutral":
            # 점령 타일은 스프라이트가 생산 시설로 바뀐다 — 점령형 템플릿 확보 전까지 미상
            return TileResult("unknown", "미상", occupancy, 0.3)
        grass, lowsat, water, lap_energy = self._interior_stats(frame, px, py)
        if water >= _WATER_MIN_FRACTION:
            return TileResult("impassable", "강", occupancy, 0.55)
        if (grass >= _PLAIN_MIN_GRASS and lowsat <= _PLAIN_MAX_LOWSAT
                and lap_energy <= _PLAIN_MAX_LAPLACIAN):
            return TileResult("resource", "공터", occupancy, 0.6)
        return TileResult("unknown", "미상", occupancy, 0.2)

    # -- 내부 단계 ---------------------------------------------------------

    def _occupancy(self, frame: np.ndarray, px: float, py: float) -> str:
        m = self.basis.matrix()
        pts = []
        for t in _BAND_T:
            for s in _BAND_S:
                pts.append((px, py) + m @ (t, s))
                pts.append((px, py) + m @ (s, t))
        pix = np.array(pts).round().astype(int)
        h, w = frame.shape[:2]
        pix = pix[(pix[:, 0] >= 0) & (pix[:, 0] < w) &
                  (pix[:, 1] >= 0) & (pix[:, 1] < h)]
        if len(pix) < 100:  # 셀이 프레임을 벗어나 표본이 부족하면 판정 보류
            return "neutral"
        band = frame[pix[:, 1], pix[:, 0]].reshape(-1, 1, 3)
        hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV).reshape(-1, 3)
        hh, ss, vv = hsv[:, 0], hsv[:, 1], hsv[:, 2]
        n = len(hsv)
        red = ((hh <= 8) | (hh >= 172)) & (ss >= 120) & (vv >= 80)
        blue = (hh >= 90) & (hh <= 130) & (ss >= 70) & (vv >= 90)
        green = (hh >= 40) & (hh <= 75) & (ss >= 150) & (vv >= 170)
        scores = {
            "enemy": red.sum() / n / _RED_MIN_FRACTION,
            "mine": green.sum() / n / _GREEN_MIN_FRACTION,
        }
        blue_frac = blue.sum() / n / _BLUE_MIN_FRACTION
        if blue_frac >= 1:
            label = "ally" if np.median(vv[blue]) < _BLUE_ALLY_MAX_VAL else "friendly"
            scores[label] = blue_frac
        best = max(scores, key=scores.get)
        return best if scores[best] >= 1 else "neutral"

    def _best_template(self, frame: np.ndarray, px: float, py: float
                       ) -> tuple[str | None, float]:
        hx, hy = self.basis.half_extents
        x0 = max(0, int(px - hx) - _MATCH_SLACK)
        y0 = max(0, int(py - hy) - _MATCH_SLACK)
        x1 = min(frame.shape[1], int(px + hx) + _MATCH_SLACK)
        y1 = min(frame.shape[0], int(py + hy) + _MATCH_SLACK)
        crop = frame[y0:y1, x0:x1]
        best_name, best_score = None, -1.0
        for name, tpl in self._templates.items():
            if crop.shape[0] < tpl.shape[0] or crop.shape[1] < tpl.shape[1]:
                continue
            score = float(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best_name, best_score = name, score
        return best_name, best_score

    def _interior_stats(self, frame: np.ndarray, px: float, py: float
                        ) -> tuple[float, float, float, float]:
        """중앙 평행사변형 내부의 잔디/저채도/수면 분율과 라플라시안 에너지."""
        hx, hy = self.basis.half_extents
        x0, y0 = max(0, int(px - hx)), max(0, int(py - hy))
        x1, y1 = min(frame.shape[1], int(px + hx) + 1), min(frame.shape[0], int(py + hy) + 1)
        crop = frame[y0:y1, x0:x1]
        inv = np.linalg.inv(self.basis.matrix())
        ys, xs = np.mgrid[y0:y1, x0:x1]
        d = np.stack([xs - px, ys - py], axis=-1) @ inv.T
        mask = (np.abs(d[..., 0]) <= _INTERIOR_SCALE / 2) & \
               (np.abs(d[..., 1]) <= _INTERIOR_SCALE / 2)
        if not mask.any():
            return 0.0, 0.0, 0.0, 0.0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        hh, ss = hsv[..., 0][mask], hsv[..., 1][mask]
        n = mask.sum()
        grass = float(((hh >= 35) & (hh <= 85) & (ss >= 60)).sum() / n)
        lowsat = float((ss < 75).sum() / n)
        water = float(((hh >= 90) & (hh <= 135) & (ss >= 40)).sum() / n)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        return grass, lowsat, water, float(lap[mask].mean())
