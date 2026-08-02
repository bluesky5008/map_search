"""숫자 글리프 템플릿 판독 (설계 §2 DigitReader / FR-02, P-03).

글리프는 팝업 좌표 문자열(크림색 텍스트)에서 추출했다(assets/templates/digits/).
팝업 좌표 폰트의 픽셀 크기는 창 크기와 무관하게 거의 동일하다(1281/2560 창
캡처 대조, 높이 11~12px). 다만 렌더링(창 크기·계절 테마)에 따라
안티에일리어싱이 달라 교차 소스 매칭이 약하므로, 문자당 소스별 변형 템플릿
(`6.png`, `6_2.png`, ...)을 두고 최대 점수를 취한다.
좌표 입력란 폰트는 미확보이며 S-3(T12 실기)에서 검증·보강한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "assets" / "templates" / "digits"

_CHAR_BY_NAME = {"comma": ",", "paren_l": "(", "paren_r": ")"}
_TEXT_MAX_SAT = 90
_TEXT_MIN_VAL = 170
_MIN_COMPONENT_AREA = 3
_MATCH_THRESHOLD = 0.45
_MAX_DIM_RATIO = 1.4  # 글리프와 템플릿의 폭·높이 비가 이 이상 다르면 후보 제외
_TINY_AREA = 12       # 이하 픽셀 면적이면 초소형 글리프(콤마 등)로 취급


class DigitReader:
    """밝은 텍스트 스트립에서 글리프를 분리해 템플릿 매칭으로 읽는다."""

    def __init__(self, template_dir: Path | str = DEFAULT_DIR):
        self._glyphs: list[tuple[str, np.ndarray]] = []
        for path in sorted(Path(template_dir).glob("*.png")):
            stem = re.sub(r"_\d+$", "", path.stem)  # 변형 접미사(_2 등) 제거
            char = _CHAR_BY_NAME.get(stem, stem)
            self._glyphs.append((char, np.asarray(Image.open(path).convert("L"))))
        if not self._glyphs:
            raise FileNotFoundError(f"글리프 템플릿이 없습니다: {template_dir}")

    def read(self, strip: np.ndarray, repair: bool = False) -> str:
        """스트립(RGB)의 글리프들을 왼쪽부터 읽는다. 인식 실패 글리프는 '?'.

        repair=True면 세그먼테이션 복구 패스(사실 35): 인접 클러스터 병합과
        과폭 클러스터 분할 가설을 매칭 점수로 판정해 채택한다 — '0'의 좌우 획
        분리(내부 간격 = 글리프 간 간격이라 간격 규칙으로는 판정 불가)와
        "(1"·"0)"류 맞닿음 병합이 이 폰트의 실측 실패 모드다.
        """
        hsv = cv2.cvtColor(strip, cv2.COLOR_RGB2HSV)
        mask = ((hsv[:, :, 1] < _TEXT_MAX_SAT) &
                (hsv[:, :, 2] >= _TEXT_MIN_VAL)).astype(np.uint8)
        gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
        clusters = _glyph_clusters(mask)
        if repair:
            return self._read_repaired(gray, mask, clusters)
        return "".join(self._match(gray[y0:y1, x0:x1])
                       for x0, y0, x1, y1 in clusters)

    def read_coords(self, strip: np.ndarray) -> tuple[int, int] | None:
        """"(x,y)" 형식의 좌표 텍스트를 파싱한다. 실패 시 복구 판독 재시도."""
        for repair in (False, True):
            m = re.search(r"\((\d+),(\d+)\)", self.read(strip, repair=repair))
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return None

    # -- 세그먼테이션 복구 (사실 35) ----------------------------------------

    def _read_repaired(self, gray: np.ndarray, mask: np.ndarray,
                       clusters: list) -> str:
        w_digit = max(t.shape[1] for c, t in self._glyphs if c.isdigit())
        out: list[str] = []
        i = 0
        while i < len(clusters):
            c = clusters[i]
            ch, sc = self._match_scored(_crop(gray, c))
            # 병합 가설: 다음 클러스터와 2px 이내 간격 + 병합 폭이 한 글리프 폭
            if i + 1 < len(clusters):
                nxt = clusters[i + 1]
                gap = nxt[0] - c[2]
                union = (c[0], min(c[1], nxt[1]), nxt[2], max(c[3], nxt[3]))
                if 0 <= gap <= 2 and union[2] - union[0] <= w_digit + 1:
                    ch_n, sc_n = self._match_scored(_crop(gray, nxt))
                    ch_m, sc_m = self._match_scored(_crop(gray, union))
                    if ch_m != "?" and sc_m > max(sc, sc_n):
                        out.append(ch_m)
                        i += 2
                        continue
            # 분할 가설: 과폭 클러스터를 마스크 최소 밀도 열에서 이분
            if c[2] - c[0] > w_digit + 1:
                parts = _split_at_valley(mask, c)
                if parts is not None:
                    got = [self._match_scored(_crop(gray, p)) for p in parts]
                    if all(g[0] != "?" for g in got) and \
                            min(g[1] for g in got) > sc:
                        out.extend(g[0] for g in got)
                        i += 1
                        continue
            out.append(ch)
            i += 1
        return "".join(out)

    def _match(self, crop: np.ndarray) -> str:
        return self._match_scored(crop)[0]

    def _match_scored(self, crop: np.ndarray) -> tuple[str, float]:
        ch, cw = crop.shape
        if ch * cw <= _TINY_AREA:
            # 콤마 등 초소형 글리프는 NCC가 불안정하다 — 크기가 가장 가까운
            # 초소형 템플릿으로 판정한다.
            tiny = [(abs(t.shape[0] - ch) + abs(t.shape[1] - cw), c)
                    for c, t in self._glyphs if t.shape[0] * t.shape[1] <= _TINY_AREA]
            return (min(tiny)[1], 0.0) if tiny else ("?", 0.0)
        best_char, best_score = "?", _MATCH_THRESHOLD
        for char, tpl in self._glyphs:
            th, tw = tpl.shape
            if (max(ch, th) > _MAX_DIM_RATIO * min(ch, th) or
                    max(cw, tw) > _MAX_DIM_RATIO * min(cw, tw)):
                continue
            resized = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)
            score = cv2.matchTemplate(resized, tpl, cv2.TM_CCOEFF_NORMED)[0, 0]
            if np.isfinite(score) and score > best_score:
                best_char, best_score = char, score
        return best_char, (best_score if best_char != "?" else 0.0)


def _crop(gray: np.ndarray, box: tuple) -> np.ndarray:
    x0, y0, x1, y1 = box
    return gray[y0:y1, x0:x1]


def _split_at_valley(mask: np.ndarray, box: tuple
                     ) -> list[tuple[int, int, int, int]] | None:
    """과폭 클러스터를 중앙부 마스크 최소 밀도 열에서 둘로 나눈다."""
    x0, y0, x1, y1 = box
    cols = mask[y0:y1, x0:x1].sum(axis=0)
    lo, hi = max(1, (x1 - x0) // 4), (x1 - x0) - max(1, (x1 - x0) // 4)
    if hi <= lo:
        return None
    cut = lo + int(np.argmin(cols[lo:hi]))
    return [(x0, y0, x0 + cut, y1), (x0 + cut, y0, x1, y1)]


def _glyph_clusters(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """연결 성분을 x 구간이 겹치거나 맞닿는 것끼리 글리프로 병합한다.

    글꼴 안티에일리어싱으로 한 글리프가 여러 성분으로 조각나는 경우('0'의 좌우
    획 등)를 흡수한다. 글리프 사이 간격은 2px 이상이라 합쳐지지 않는다.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = sorted(tuple(int(v) for v in stats[i][:4])
                   for i in range(1, n) if stats[i][4] >= _MIN_COMPONENT_AREA)
    clusters: list[list[int]] = []
    for x, y, w, h in comps:
        if clusters and x <= clusters[-1][2]:
            c = clusters[-1]
            c[0], c[1] = min(c[0], x), min(c[1], y)
            c[2], c[3] = max(c[2], x + w), max(c[3], y + h)
        else:
            clusters.append([x, y, x + w, y + h])
    return [tuple(c) for c in clusters]
