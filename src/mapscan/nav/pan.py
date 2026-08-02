"""팬 이동 추적 (설계 v3 §4.3 / DCR-003, S-5·S-6 실측 기반).

지면이 원근 틸트로 렌더링되어 팬 이동량이 화면 y에 선형 의존한다(전단 이동장,
S-5 발견 3). 전폭 밴드 3개의 x 이동을 재서 dx(y) = a + b·y 로 적합하고,
셀 위치는 대역별 이동량으로 갱신한다.

눈(겨울) 지형은 추적 NCC가 낮아 간헐 오추적이 있다(S-6 관찰 1, R-12).
밴드 기각은 이중 앵커(T14 튜닝): 게인 기대 ±PAN_GAIN_TOLERANCE_PX **또는**
직전 실측 ±TRACK_TOLERANCE_PX 안이면 유효, 둘 다 밖이거나 저점수면 기각하고
남은 밴드로 적합한다. 유효 밴드가 2개 미만이면 TrackLost — 호출자는
행을 중단하고 점프로 재앵커한다(오염 전파를 행 내로 한정).
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from . import ui

log = logging.getLogger(__name__)

_REVERSE_CMD_PX = -800   # 이보다 큰 좌측 이동은 역방향 매칭(템플릿 폭 확보)
_WIDE_SEARCH = 260       # 행 첫 팬(직전 실측 없음)의 탐색 반경
_NARROW_SEARCH = 200
_MIN_SCORE = 0.08        # 겨울 지형 정상 매칭이 0.11대까지 내려간다(T13 실기)
_B_SANITY = (-1.5, 0.3)  # 좌팬 전단 기울기의 물리 범위(부호 반전 시 대칭)


class TrackLost(RuntimeError):
    """유효 추적 밴드가 부족하다 — 행을 중단하고 재앵커해야 한다."""


def pan_gain(y: float) -> float:
    return ui.PAN_GAIN_AT_Y0 + ui.PAN_GAIN_SLOPE * (y - ui.PAN_GAIN_Y0)


class PanTracker:
    """행 하나의 누적 전단 이동 dx(y) = A + B·y 를 유지한다."""

    def __init__(self, client_offset: tuple[int, int]):
        self.offset = client_offset
        self.A = 0.0
        self.B = 0.0
        # 밴드별 직전 실측. 게인은 드래그 길이에 따라 다르므로(S-6 관찰 2)
        # 명령 길이별로 따로 둔다 — 처음 보는 길이는 캘리브레이션 게인 + 광탐색.
        self._last: dict[int, list[float]] = {}

    def shift_at(self, y_frame: float) -> float:
        return self.A + self.B * y_frame

    def update(self, prev: np.ndarray, cur: np.ndarray, cmd_dx: int) -> dict:
        """팬 전후 프레임으로 이동을 적합해 누적한다. 측정 요약을 반환한다."""
        ox, oy = self.offset
        last = self._last.get(cmd_dx)
        search = _NARROW_SEARCH if last else _WIDE_SEARCH
        pts, raw, rejected, expects = [], [], [], []
        for i, (y0, h) in enumerate(ui.TRACK_BANDS):
            yc = y0 + h / 2
            gain_dx = cmd_dx * pan_gain(yc)
            dx, dy, score = _band_shift(prev, cur, (y0, h), (ox, oy),
                                        last[i] if last else gain_dx, search)
            raw.append((round(dx, 1), round(dy, 1), round(score, 3)))
            expects.append((round(gain_dx), round(last[i]) if last else None))
            # 이중 앵커(T14 튜닝): 게인 기대 근방 또는 직전 실측 근방이면 유효.
            # 직전 팬 단일 앵커는 정상 팬별 변동의 연속 차이를 기각했다(행 150).
            ok_gain = abs(dx - gain_dx) <= ui.PAN_GAIN_TOLERANCE_PX
            ok_last = last is not None and abs(dx - last[i]) <= ui.TRACK_TOLERANCE_PX
            if score < _MIN_SCORE or not (ok_gain or ok_last):
                rejected.append(i)
                continue
            pts.append((yc + oy, dx, i))
        if len(pts) < 2:
            raise TrackLost(f"추적 밴드 부족: raw={raw} "
                            f"expect(게인,직전)={expects} rejected={rejected}")
        # 3밴드면 leave-one-out 검정으로 오염 밴드를 찾는다 — 3점 최소제곱
        # 잔차는 이상치가 적합선을 끌어당겨 판별력이 없다.
        if len(pts) == 3:
            loo = []
            for j in range(3):
                keep = [k for k in range(3) if k != j]
                (y1, x1, _), (y2, x2, _) = pts[keep[0]], pts[keep[1]]
                slope = (x2 - x1) / (y2 - y1)
                loo.append(abs(pts[j][1] - (x1 + slope * (pts[j][0] - y1))))
            worst = int(np.argmax(loo))
            if loo[worst] > ui.TRACK_TOLERANCE_PX / 2:
                rejected.append(pts[worst][2])
                pts.pop(worst)
        ys = np.array([p[0] for p in pts])
        xs = np.array([p[1] for p in pts])
        b, a = np.polyfit(ys, xs, 1)
        lo, hi = (_B_SANITY if cmd_dx < 0 else (-_B_SANITY[1], -_B_SANITY[0]))
        if not (lo <= b <= hi):
            raise TrackLost(f"전단 기울기 이상 b={b:.3f}: raw={raw}")
        self.A += float(a)
        self.B += float(b)
        self._last[cmd_dx] = [float(a + b * (y0 + h / 2 + oy))
                              for y0, h in ui.TRACK_BANDS]
        return {"a": round(float(a), 1), "b": round(float(b), 4),
                "raw": raw, "rejected": rejected, "expect": expects}


def _band_shift(prev, cur, band, offset, expect, search):
    """한 밴드의 x 이동 (dx, dy, NCC). 광폭 좌팬은 역방향 매칭."""
    y0, h = band
    ox, oy = offset
    sy0 = max(0, y0 + oy - 12)
    sy1 = min(cur.shape[0], y0 + h + oy + 12)
    if expect < _REVERSE_CMD_PX:
        # cur 좌측의 신규 진입 구간을 prev 우측에서 찾는다(S-6 검증 방식)
        cx0, w_tpl = 10, 450
        tpl = cur[y0 + oy:y0 + h + oy, cx0 + ox:cx0 + w_tpl + ox]
        ex = cx0 + ox - int(expect)
        sx0 = max(0, ex - search)
        sx1 = min(prev.shape[1], ex + w_tpl + search)
        res = cv2.matchTemplate(prev[sy0:sy1, sx0:sx1], tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, (px, py) = cv2.minMaxLoc(res)
        return (float((cx0 + ox) - (sx0 + px)),
                float((y0 + oy) - (sy0 + py)), float(score))
    x0, x1 = ui.TRACK_X
    if expect < 0:
        x0 = max(x0, int(-expect) + search + 10)
    else:
        x1 = min(x1, prev.shape[1] - int(expect) - search - 10)
    if x1 - x0 < 200:
        raise TrackLost(f"추적 템플릿 구간 부족: expect={expect:.0f}")
    tpl = prev[y0 + oy:y0 + h + oy, x0 + ox:x1 + ox]
    ex = x0 + ox + int(expect)
    sx0 = max(0, ex - search)
    sx1 = min(cur.shape[1], ex + (x1 - x0) + search)
    res = cv2.matchTemplate(cur[sy0:sy1, sx0:sx1], tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (px, py) = cv2.minMaxLoc(res)
    return (float(sx0 + px - (x0 + ox)),
            float(sy0 + py - (y0 + oy)), float(score))
