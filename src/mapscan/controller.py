"""ScanController — 스캔 수명주기·모드 전략 (설계 §2, §4.3 v4 / DCR-003·004).

v1은 MODE-A2(DetailScan)만 구현한다(DCR-001). 스캔 루프는 행 기반이다:
행 = 좌표 점프(재앵커) 1회 + 팬 N회. 팬 이동은 PanTracker가 전단 모델로
실측·누적하고, 분류는 y 대역의 신규 진입 셀로 한정한다(커버 비트맵 중복 제거).

좌표 무결성(DCR-004): 격자 기저의 y-성분이 맵 지역 의존이라 추측항법만으로는
행 이동 중 좌표가 팬당 my 1.3~1.7타일씩 드리프트한다(T14 실측). K팬마다 뷰
중앙 타일을 클릭해 팝업 좌표·선택 링으로 재앵커하고, 분류 레코드는 사이클
단위로 버퍼링했다가 실측 드리프트를 팬별 선형 보간해 보정 후 기록한다.
미보정 꼬리는 기록하지 않는다(오좌표보다 미커버가 안전 — 보충 방문 몫).

행 기하: 화면 y는 49·mx + 45·my 에 비례하므로(기저 E_MX/E_MY의 y성분),
c = 49·mx + 45·my 가 같은 점들이 같은 화면 높이에 놓인다. 행 하나는 분류
대역 높이(280px)만큼의 c 구간을 담당하고, 행 시작은 그 c 선과 맵의 저-mx
경계의 교점이다. 팬은 뷰를 (+mx, −my) 방향으로 밀어 스트라이프를 쓸어 간다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .nav import Navigator, NotDetailView, NotInMapMode, StabilizeTimeout
from .nav import ui
from .nav.pan import PanTracker, TrackLost
from .nav.planner import ScanPlanner
from .store import DataStore, TileRecord
from .vision import DigitReader, TileClassifier
from .vision.grid import GridMapper, _cell_intersects_rect, find_selection_highlight
from .watchdog import Watchdog, WatchdogAlert

log = logging.getLogger(__name__)

C_BAND = ui.BAND_Y[1] - ui.BAND_Y[0]   # 행이 담당하는 c 구간 = 분류 대역 높이(px)
_EDGE_MARGIN = 15        # 뷰 중심이 맵 경계에 이만큼 접근하면 행 종료(잔여는 보충)
_ROW_RETRIES = 2
_MAX_PANS_PER_ROW = 200  # 폭주 방지 상한(1619² 대각 행도 ~120팬이면 끝난다)

# ---- 재앵커 (DCR-004) ------------------------------------------------------
_REANCHOR_EVERY = 4      # K팬마다 클릭 재앵커 — 중부 실제 드리프트(±10~13/사이클)가
                         # K=3 새니티 창(±11)과 충돌해 조기 종료 유발(T14 K튜닝, 사실 46).
                         # K=4(창 ±14)는 K=5와 동속이면서 보정이 더 촘촘하다
_REANCHOR_MAX_MISS = 2   # 연속 실패 사이클 상한 → 행 조기 종료
_MAX_TRACK_LOST = 3      # 사이클 내 추적 손실 상한 → 행 조기 종료
_REANCHOR_SETTLE_S = 1.1
_RING_NEAR_PX = (90, 60)  # 클릭점에서 이 이상 먼 링은 오검출로 무시


def _sanity_window(pans_since: int, losts: int) -> int:
    """재앵커 판독-예측 차 허용(타일). 드리프트는 팬당 1~2타일이고 클릭 y에
    따른 전단 국소차가 더해져 3팬에 9타일 편차가 실측됐다(팬당 3으로 커버).
    TrackLost 팬은 변위(~17 u-스텝) 자체가 유실되므로 그만큼 넓힌다.
    오판독은 글리프 변형·최빈값 투표로 방어하며, 전형적 오판독 거리(≥50)는
    이 창이 여전히 기각한다."""
    return 2 + 3 * pans_since + 15 * losts


def _read_popup_coords(reader, frame, cx, cy):
    """클릭점(프레임 좌표) 위쪽의 팝업 좌표 문자열을 슬라이딩 판독한다.

    좌표 줄 위치는 팝업 구성(타일 종류·배지·이름 접두)에 따라 달라 x·y를
    함께 슬라이딩하고, **모든 파스의 최빈값**을 취한다 — 글리프가 잘린 절단면
    하나가 그럴듯한 오판독을 내는 사례가 있었다(T14 실기, "3"→"8").
    """
    votes: dict[tuple[int, int], int] = {}
    for dx_off in (0, -30, -60, 30, 60, 90, 120):
        for dy in range(-260, -88, 6):
            y0, x0 = cy + dy, cx - 30 + dx_off
            if y0 < 0 or x0 < 0:
                continue
            strip = frame[y0:y0 + 34, x0:x0 + 225]
            if strip.size == 0:
                continue
            got = reader.read_coords(strip)
            if got:
                votes[got] = votes.get(got, 0) + 1
    if not votes:
        return None
    return max(votes.items(), key=lambda kv: kv[1])[0]


@dataclass(frozen=True)
class Row:
    index: int
    start: tuple[int, int]


def plan_rows(map_max: tuple[int, int]) -> list[Row]:
    """c = 49·mx + 45·my 스트라이프의 시작 좌표열(결정적 — 재개는 인덱스로).

    시작점은 경계 교점에서 스트라이프 방향(u ∝ (45,−49))으로 **~15타일 인셋**
    한다 — 경계 시작은 화면 절반이 맵 밖(정적 무지물)이라 팬 추적 템플릿이
    오염되어 TrackLost가 난다(실기 확인). 빠진 경계 구간은 보충 방문이 커버한다.
    """
    rows: list[Row] = []
    c_max = 49 * map_max[0] + 45 * map_max[1]
    for i, c in enumerate(range(0, c_max + 1, C_BAND)):
        if c <= 45 * map_max[1]:
            start = (0, round(c / 45))
        else:
            start = (round((c - 45 * map_max[1]) / 49), map_max[1])
        start = (start[0] + 10, start[1] - 11)   # 인셋 (u 방향 ~15타일)
        rows.append(Row(i, (max(0, min(start[0], map_max[0])),
                            max(0, min(start[1], map_max[1])))))
    return rows


class DetailScan:
    """MODE-A2 — 디테일 줌 행 기반 전체 스캔."""

    MODE = "A2"

    def __init__(self, nav: Navigator, store: DataStore,
                 classifier: TileClassifier | None = None):
        self.nav = nav
        self.store = store
        self.clf = classifier or TileClassifier()
        self.reader = DigitReader()
        self.watchdog = Watchdog()

    # -- 실행 --------------------------------------------------------------

    def run(self, scan_id: int, map_max: tuple[int, int],
            max_rows: int | None = None, start_row: int | None = None,
            max_pans: int | None = None) -> dict:
        rows = plan_rows(map_max)
        scan = self.store.get_scan(scan_id)
        checkpoint = int(scan["checkpoint"]) if start_row is None else start_row
        self._max_pans = max_pans or _MAX_PANS_PER_ROW
        covered = self._covered_bitmap(scan_id, map_max)
        todo = rows[checkpoint:]
        if max_rows is not None:
            todo = todo[:max_rows]
        t0 = time.monotonic()
        done = failed = 0
        for row in todo:
            try:
                self._run_row(scan_id, row, map_max, covered)
            except (NotDetailView, NotInMapMode, StabilizeTimeout,
                    TrackLost, WatchdogAlert) as exc:
                failed += 1
                log.warning("행 %d 실패(보충 대상으로 남김): %s", row.index, exc)
            done += 1
            self.store.set_checkpoint(scan_id, row.index + 1)
            elapsed = time.monotonic() - t0
            eta = elapsed / done * (len(todo) - done)
            log.info("진행 %d/%d행 (커버 %s타일, 경과 %.0fs, ETA %.0f분)",
                     done, len(todo), f"{int(covered.sum()):,}", elapsed, eta / 60)
        summary = {"rows": done, "row_failures": failed,
                   "covered": int(covered.sum()),
                   "total": (map_max[0] + 1) * (map_max[1] + 1)}
        if max_rows is None:
            summary["supplemented"] = self._supplement(scan_id, map_max, covered)
            summary["covered"] = int(covered.sum())
        return summary

    # -- 행 하나 ------------------------------------------------------------

    def _run_row(self, scan_id: int, row: Row, map_max: tuple[int, int],
                 covered: np.ndarray) -> None:
        last_exc: Exception | None = None
        for attempt in range(_ROW_RETRIES + 1):
            try:
                self._row_once(scan_id, row, map_max, covered)
                return
            except (NotDetailView, NotInMapMode, StabilizeTimeout,
                    TrackLost, WatchdogAlert) as exc:
                last_exc = exc
                log.warning("행 %d 시도 %d 실패: %s", row.index, attempt + 1, exc)
        raise last_exc  # type: ignore[misc]

    def _row_once(self, scan_id: int, row: Row, map_max: tuple[int, int],
                  covered: np.ndarray) -> None:
        grid = self.nav.jump(*row.start)
        frame = self.nav.capture.grab_fresh()
        self.watchdog.check(frame)
        if getattr(self.nav, "_detail_ref", None) is None:
            self.nav.capture_detail_ref(frame)
        else:
            self.nav.verify_detail_view(frame)
        offset = self.nav.client_offset(frame)
        anchor_c = (grid.anchor_px[0] - offset[0], grid.anchor_px[1] - offset[1])
        popup = ui.popup_rects_at(*anchor_c)
        tracker = PanTracker(offset)
        # 지연 기록 버퍼(DCR-004): (앵커 이후 팬 서수, records). 어떤 경로로든
        # 버퍼를 버릴 때는 커버 비트맵 표시를 함께 되돌려야 한다(보충 방문 몫).
        buffer: list[tuple[int, list[TileRecord]]] = [
            (0, self._classify_new(grid, tracker, frame, map_max,
                                   covered, extra_exclude=popup))]
        try:
            self._row_pans(scan_id, row, grid, tracker, offset, buffer,
                           covered, map_max)
        except BaseException:
            self._drop_buffer(buffer, covered)
            raise

    def _row_pans(self, scan_id, row, grid, tracker, offset, buffer,
                  covered, map_max) -> None:
        """행의 팬 루프 — 버퍼는 재앵커 성공 시 보정 기록, 실패 시 폐기된다."""
        prev = self.nav.capture.grab_fresh()
        pans_since = losts = misses = 0
        max_pans = getattr(self, "_max_pans", _MAX_PANS_PER_ROW)
        edge_reached = False
        for k in range(max_pans):
            src, dst = ui.PAN_SHORT if k == 0 else ui.PAN_WIDE
            frame = self.nav.pan(src, dst, steps=12 if k == 0 else 24)
            self.watchdog.check(frame)
            pans_since += 1
            try:
                info = tracker.update(prev, frame, dst[0] - src[0])
                # raw 텔레메트리 — 기각 규칙 튜닝·사후 원인 분석용(T14)
                log.info("행 %d 팬 #%d: a=%s b=%s raw=%s rejected=%s expect=%s",
                         row.index, k + 1, info["a"], info["b"], info["raw"],
                         info["rejected"], info["expect"])
                buffer.append((pans_since, self._classify_new(
                    grid, tracker, frame, map_max, covered)))
            except TrackLost as exc:
                # 변위 미상 — 이 팬은 분류를 생략하고 재앵커 복구를 기다린다
                losts += 1
                log.warning("행 %d 팬 #%d 추적 손실(분류 생략, %d회째): %s",
                            row.index, k + 1, losts, exc)
                if losts >= _MAX_TRACK_LOST:
                    self._drop_buffer(buffer, covered)
                    buffer.clear()
                    log.warning("행 %d: 추적 손실 %d회 — 행 조기 종료(미보정 꼬리 폐기)",
                                row.index, losts)
                    return
            prev = frame

            if (k + 1) % _REANCHOR_EVERY == 0:
                res = self._reanchor(row, grid, tracker, frame.shape, offset,
                                     pans_since, losts,
                                     candidates=buffer[-1][1] if buffer else ())
                if res is not None:
                    grid, drift = res
                    self._flush(scan_id, buffer, drift, pans_since, covered,
                                map_max)
                    buffer.clear()
                    tracker.A = tracker.B = 0.0
                    pans_since = losts = misses = 0
                    prev = self.nav.capture.grab_fresh()   # 재앵커 팝업 포함 기준
                else:
                    misses += 1
                    if misses >= _REANCHOR_MAX_MISS:
                        self._drop_buffer(buffer, covered)
                        buffer.clear()
                        log.warning("행 %d: 재앵커 연속 %d회 실패 — 행 조기 종료"
                                    "(미보정 꼬리 폐기)", row.index, misses)
                        return

            cx, cy = self._view_center(grid, tracker, offset, frame.shape)
            if cx > map_max[0] - _EDGE_MARGIN or cy < _EDGE_MARGIN:
                edge_reached = True
                break

        # 행 종료(경계 도달·팬 상한) — 최종 재앵커로 꼬리를 보정 기록한다
        if pans_since > 0 or any(recs for _, recs in buffer):
            res = self._reanchor(row, grid, tracker, prev.shape, offset,
                                 pans_since, losts,
                                 candidates=buffer[-1][1] if buffer else ())
            if res is not None:
                self._flush(scan_id, buffer, res[1], max(pans_since, 1),
                            covered, map_max)
            else:
                n = self._drop_buffer(buffer, covered)
                if n:
                    log.warning("행 %d: 종료 재앵커 실패 — 꼬리 %d타일 폐기(보충 몫)",
                                row.index, n)
            buffer.clear()
        if not edge_reached and max_pans >= _MAX_PANS_PER_ROW:
            raise TrackLost(f"행 {row.index}: 팬 상한 초과(뷰가 경계에 닿지 않음)")

    # -- 재앵커·지연 기록 (DCR-004) ------------------------------------------

    def _reanchor(self, row, grid, tracker, frame_shape, offset,
                  pans_since, losts, candidates=()):
        """뷰 중앙 대역의 타일을 클릭해 (새 그리드, 드리프트)를 얻는다.

        대상은 이번 사이클에 분류된 셀 중 **평지(resource — 공터·자원)**를
        우선한다 — 절벽·산(미상 처리)은 고도 시차로 클릭 피킹이 수 타일
        어긋나 앵커를 오염시킨다(T14 실측: 절벽에서 (−2,+5)타일). 평지 후보가
        없으면 뷰 중앙 기하 선택으로 폴백한다.

        판독 실패·새니티 창 위반이면 None — 호출자가 실패 횟수로 행 지속을
        판단한다. 링이 클릭점 근방이면 앵커 위치로 쓴다(정밀), 아니면 클릭점
        (반 타일 이내 정확)으로 폴백한다.
        """
        h, w = frame_shape[:2]
        ox, oy = offset
        yf = (ui.BAND_Y[0] + ui.BAND_Y[1]) / 2 + oy
        best = None
        for r in candidates:
            if r.category != "resource":
                continue
            x0, y0 = grid.to_screen(r.x, r.y)
            px, py = x0 + tracker.shift_at(y0), y0
            if not (400 <= px <= w - 400):   # 팝업이 화면 밖으로 잘리지 않게
                continue
            d = abs(px - w / 2) + abs(py - yf)
            if best is None or d < best[0]:
                best = (d, r.x, r.y, px, py)
        if best is None:
            ccx, ccy = grid.to_map(w / 2 - tracker.shift_at(yf), yf)
            for dmx in range(-3, 4):
                for dmy in range(-3, 4):
                    mx, my = round(ccx) + dmx, round(ccy) + dmy
                    x0, y0 = grid.to_screen(mx, my)
                    px, py = x0 + tracker.shift_at(y0), y0
                    d = abs(px - w / 2) + abs(py - yf)
                    if best is None or d < best[0]:
                        best = (d, mx, my, px, py)
        _, mx, my, px, py = best
        self.nav.verify_detail_view(self.nav.capture.grab_fresh())
        self.nav.input.click(round(px - ox), round(py - oy))
        time.sleep(_REANCHOR_SETTLE_S)
        after = self.nav.capture.grab_fresh()
        got = _read_popup_coords(self.reader, after, round(px), round(py))
        win = _sanity_window(pans_since, losts)
        if not got or abs(got[0] - mx) > win or abs(got[1] - my) > win:
            log.warning("행 %d 재앵커 실패: 예측(%d,%d) 판독%s 허용창±%d",
                        row.index, mx, my, got, win)
            self._save_evidence(after, px, py, f"reanchor_row{row.index}")
            return None
        ring = find_selection_highlight(after)
        if ring is not None and (abs(ring[0] - px) > _RING_NEAR_PX[0]
                                 or abs(ring[1] - py) > _RING_NEAR_PX[1]):
            ring = None   # 오검출(하단 HUD 등) 방어
        pos = ring if ring is not None else (px, py)
        drift = (got[0] - mx, got[1] - my)
        log.info("행 %d 재앵커: 예측(%d,%d) → 실측%s 드리프트(%+d,%+d)%s",
                 row.index, mx, my, got, drift[0], drift[1],
                 "" if ring is None else " [링]")
        return GridMapper(grid.basis, tuple(pos), tuple(got)), drift

    def _save_evidence(self, frame, px, py, tag: str) -> None:
        """판독 실패 팝업 스트립을 사후 글리프 보강용으로 저장한다(설계 §4.4).

        오판독은 타일별로 결정적이라(사실 32) 실패 표본이 곧 템플릿 소스다.
        저장 실패가 스캔을 막지 않는다."""
        try:
            from PIL import Image
            out = Path("output/evidence")
            out.mkdir(parents=True, exist_ok=True)
            crop = frame[max(0, round(py) - 280):round(py) + 40,
                         max(0, round(px) - 140):round(px) + 340]
            path = out / f"{tag}_{int(time.time())}.png"
            Image.fromarray(crop).save(path)
            log.info("판독 실패 증거 저장: %s", path)
        except Exception as exc:
            log.warning("증거 저장 실패(무시): %r", exc)

    def _flush(self, scan_id, buffer, drift, n, covered, map_max) -> int:
        """버퍼 레코드에 드리프트를 팬별 선형 보간 보정해 기록한다."""
        for _, recs in buffer:
            for r in recs:
                covered[r.y, r.x] = False
        out = []
        for i, recs in buffer:
            cx = round(drift[0] * i / n)
            cy = round(drift[1] * i / n)
            for r in recs:
                nx, ny = r.x + cx, r.y + cy
                if not (0 <= nx <= map_max[0] and 0 <= ny <= map_max[1]):
                    continue
                if covered[ny, nx]:
                    continue
                covered[ny, nx] = True
                if cx or cy:
                    # 건물 중심 참조(FR-07)도 같은 보정을 받는다
                    r = replace(r, x=nx, y=ny) if r.center_x is None else \
                        replace(r, x=nx, y=ny, center_x=r.center_x + cx,
                                center_y=r.center_y + cy)
                out.append(r)
        if out:
            self.store.upsert_tiles(scan_id, out)
        return len(out)

    def _drop_buffer(self, buffer, covered) -> int:
        """미보정 버퍼를 폐기하고 커버 표시를 되돌린다(보충 방문 몫)."""
        n = 0
        for _, recs in buffer:
            for r in recs:
                covered[r.y, r.x] = False
                n += 1
        return n

    # -- 분류·커버 ----------------------------------------------------------

    def _classify_new(self, grid, tracker, frame, map_max, covered,
                      extra_exclude=()) -> list[TileRecord]:
        """대역 내 신규 진입 셀을 분류해 반환한다(기록은 호출자의 몫 — 지연 기록).

        커버 비트맵은 행 내 중복 분류 방지를 위해 즉시 표시한다. 버퍼를
        폐기하는 쪽이 표시를 되돌린다.
        """
        offset = tracker.offset
        exclude = list(ui.HUD_RECTS_CLIENT) + list(extra_exclude)
        cells = [c for c in _band_cells(grid, tracker, frame.shape[1::-1],
                                        offset, map_max, exclude)
                 if not covered[c[1], c[0]]]
        exclude_f = [(r[0] + offset[0], r[1] + offset[1],
                      r[2] + offset[0], r[3] + offset[1]) for r in exclude]
        records = self._classified_records(frame, cells, exclude_f)
        for mx, my, _, _ in cells:
            covered[my, mx] = True
        return records

    def _classified_records(self, frame, cells, exclude_frame) -> list[TileRecord]:
        """셀별 분류 후 2칸이상 건물 멤버를 하나로 묶는다(FR-07, 설계 §4.3).

        같은 배치에서 검출된 건물의 멤버 셀은 category/kind를 건물로 바꾸고
        중심 셀 좌표를 center_x/y(추정 표기)로 공유한다. 점령상태는 셀별
        판정을 유지한다. 이전 팬에서 이미 기록된 멤버 셀은 소급하지 않는다
        (드리프트 보정 일관성 — 미검출분은 미상으로 남는 것이 안전, NFR-04).
        """
        records = []
        for mx, my, px, py in cells:
            r = self.clf.classify(frame, px, py)
            records.append(TileRecord(x=mx, y=my, category=r.category,
                                      kind=r.kind, occupancy=r.occupancy,
                                      confidence=r.confidence))
        if not records:
            return records
        for hit in self.clf.detect_structures(frame, exclude=tuple(exclude_frame)):
            got = self.clf.structure_members(hit, cells)
            if got is None:
                continue
            members, center_i = got
            cmx, cmy = cells[center_i][0], cells[center_i][1]
            log.info("건물 %s(%s) 검출 score=%.2f 멤버 %d셀 중심(%d,%d)",
                     hit.name, hit.kind, hit.score, len(members), cmx, cmy)
            for i in members:
                records[i] = replace(records[i], category=hit.category,
                                     kind=hit.kind, center_x=cmx, center_y=cmy,
                                     center_estimated=True,
                                     confidence=hit.score)
        return records

    def _covered_bitmap(self, scan_id: int,
                        map_max: tuple[int, int]) -> np.ndarray:
        grid = np.zeros((map_max[1] + 1, map_max[0] + 1), dtype=bool)
        for row in self.store.iter_tiles(scan_id):
            grid[row["y"], row["x"]] = True
        return grid

    def _view_center(self, grid, tracker, offset, frame_shape):
        h, w = frame_shape[:2]
        return grid.to_map(w / 2 - tracker.shift_at(h / 2), h / 2)

    # -- 보충 방문 (AC-05, 점프 폴백 경로) -----------------------------------

    def _supplement(self, scan_id: int, map_max: tuple[int, int],
                    covered: np.ndarray) -> int:
        missing = {(int(x), int(y)) for y, x in np.argwhere(~covered)}
        if not missing:
            return 0
        log.info("미커버 %s타일 — 점프 보충 방문 시작", f"{len(missing):,}")
        planner = ScanPlanner(map_max)
        visits = planner.supplemental_visits(missing, start_index=0)
        for v in visits:
            try:
                grid = self.nav.jump(*v.center)
                frame = self.nav.capture.grab_fresh()
                self.watchdog.check(frame)
                offset = self.nav.client_offset(frame)
                anchor_c = (grid.anchor_px[0] - offset[0],
                            grid.anchor_px[1] - offset[1])
                popup = ui.popup_rects_at(*anchor_c)
                exclude = [(r[0] + offset[0], r[1] + offset[1],
                            r[2] + offset[0], r[3] + offset[1])
                           for r in list(ui.HUD_RECTS_CLIENT) + popup]
                cells = [(c.mx, c.my, c.px, c.py)
                         for c in grid.visible_cells(frame.shape[1::-1],
                                                     exclude=exclude)
                         if 0 <= c.mx <= map_max[0] and 0 <= c.my <= map_max[1]
                         and not covered[c.my, c.mx]]
                records = self._classified_records(frame, cells, exclude)
                for mx, my, _, _ in cells:
                    covered[my, mx] = True
                if records:
                    self.store.upsert_tiles(scan_id, records)
            except (NotDetailView, NotInMapMode, StabilizeTimeout,
                    WatchdogAlert) as exc:
                log.warning("보충 방문 %s 실패: %s", v.center, exc)
        return len(visits)


def _band_cells(grid: GridMapper, tracker: PanTracker,
                frame_size: tuple[int, int], offset: tuple[int, int],
                map_max: tuple[int, int], exclude_client) -> list:
    """행 앵커 + 누적 전단 이동을 적용한 분류 대역 내 완전 가시 셀."""
    w, h = frame_size
    hx, hy = grid.basis.half_extents
    ox, oy = offset
    ccx, ccy = grid.to_map(w / 2 - tracker.shift_at(h / 2), h / 2)
    out = []
    for dmx in range(-25, 26):
        for dmy in range(-25, 26):
            mx, my = round(ccx) + dmx, round(ccy) + dmy
            if not (0 <= mx <= map_max[0] and 0 <= my <= map_max[1]):
                continue
            x0, y0 = grid.to_screen(mx, my)
            px = x0 + tracker.shift_at(y0)
            py = y0
            if not (ui.BAND_Y[0] <= py - oy <= ui.BAND_Y[1]):
                continue
            if not (hx <= px <= w - hx and hy <= py <= h - hy):
                continue
            if any(_cell_intersects_rect((px - ox, py - oy), grid.basis, r)
                   for r in exclude_client):
                continue
            out.append((mx, my, px, py))
    return out


class ScanController:
    """모드 전략 선택·스캔 수명주기 (ADR-004). v1은 A2만 실동작."""

    def __init__(self, nav: Navigator, store: DataStore):
        self.nav = nav
        self.store = store

    def run(self, mode: str, map_max: tuple[int, int] | None = None,
            resume: bool = True, max_rows: int | None = None,
            start_row: int | None = None, max_pans: int | None = None) -> dict:
        if mode != "A2":
            raise NotImplementedError(f"MODE-{mode}는 후속 범위입니다(DCR-001)")
        scan_row = self.store.latest_resumable_scan(mode) if resume else None
        if scan_row is not None:
            scan_id = int(scan_row["scan_id"])
            if map_max is None and scan_row["map_max_x"] is not None:
                map_max = (int(scan_row["map_max_x"]), int(scan_row["map_max_y"]))
            log.info("스캔 %d 재개 (체크포인트 %d행)", scan_id, scan_row["checkpoint"])
        else:
            scan_id = self.store.create_scan(mode, zoom_level="detail",
                                             capture_mode="background")
            log.info("스캔 %d 시작", scan_id)
        if map_max is None:
            map_max = self.nav.detect_map_size()
            log.info("맵 크기 감지: %s", map_max)
        self.store.set_map_size(scan_id, *map_max)

        scanner = DetailScan(self.nav, self.store)
        try:
            summary = scanner.run(scan_id, map_max, max_rows=max_rows,
                                  start_row=start_row, max_pans=max_pans)
        except KeyboardInterrupt:
            self.store.finish_scan(scan_id, status="paused")
            log.info("중단 — 체크포인트 저장됨(재실행 시 재개)")
            raise
        except Exception:
            self.store.finish_scan(scan_id, status="paused")
            raise
        complete = summary["covered"] >= summary["total"]
        if max_rows is None and complete:
            self.store.finish_scan(scan_id, status="done")
        summary["scan_id"] = scan_id
        summary["status"] = "done" if (max_rows is None and complete) else "partial"
        return summary
