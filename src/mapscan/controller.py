"""ScanController — 스캔 수명주기·모드 전략 (설계 §2, §4.3 v3 / DCR-003).

v1은 MODE-A2(DetailScan)만 구현한다(DCR-001). 스캔 루프는 행 기반이다:
행 = 좌표 점프(재앵커) 1회 + 팬 N회. 팬 이동은 PanTracker가 전단 모델로
실측·누적하고, 분류는 y 대역의 신규 진입 셀로 한정한다(커버 비트맵 중복 제거).

행 기하: 화면 y는 49·mx + 45·my 에 비례하므로(기저 E_MX/E_MY의 y성분),
c = 49·mx + 45·my 가 같은 점들이 같은 화면 높이에 놓인다. 행 하나는 분류
대역 높이(280px)만큼의 c 구간을 담당하고, 행 시작은 그 c 선과 맵의 저-mx
경계의 교점이다. 팬은 뷰를 (+mx, −my) 방향으로 밀어 스트라이프를 쓸어 간다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .nav import Navigator, NotDetailView, NotInMapMode, StabilizeTimeout
from .nav import ui
from .nav.pan import PanTracker, TrackLost
from .nav.planner import ScanPlanner
from .store import DataStore, TileRecord
from .vision import TileClassifier
from .vision.grid import GridMapper, _cell_intersects_rect
from .watchdog import Watchdog, WatchdogAlert

log = logging.getLogger(__name__)

C_BAND = ui.BAND_Y[1] - ui.BAND_Y[0]   # 행이 담당하는 c 구간 = 분류 대역 높이(px)
_EDGE_MARGIN = 15        # 뷰 중심이 맵 경계에 이만큼 접근하면 행 종료(잔여는 보충)
_ROW_RETRIES = 2
_MAX_PANS_PER_ROW = 200  # 폭주 방지 상한(1619² 대각 행도 ~120팬이면 끝난다)


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
        popup = (anchor_c[0] + ui.POPUP_RECT_REL[0], anchor_c[1] + ui.POPUP_RECT_REL[1],
                 anchor_c[0] + ui.POPUP_RECT_REL[2], anchor_c[1] + ui.POPUP_RECT_REL[3])
        tracker = PanTracker(offset)
        self._classify_new(scan_id, grid, tracker, frame, map_max, covered,
                           extra_exclude=[popup])
        prev = frame
        max_pans = getattr(self, "_max_pans", _MAX_PANS_PER_ROW)
        for k in range(max_pans):
            src, dst = ui.PAN_SHORT if k == 0 else ui.PAN_WIDE
            frame = self.nav.pan(src, dst, steps=12 if k == 0 else 24)
            self.watchdog.check(frame)
            try:
                info = tracker.update(prev, frame, dst[0] - src[0])
                # raw 텔레메트리 — 기각 규칙 튜닝·사후 원인 분석용(T14)
                log.info("행 %d 팬 #%d: a=%s b=%s raw=%s rejected=%s expect=%s",
                         row.index, k + 1, info["a"], info["b"], info["raw"],
                         info["rejected"], info["expect"])
            except TrackLost as exc:
                # 확보한 타일은 유지된다 — 행을 조기 종료하고 잔여는 다음 행
                # 겹침·보충 방문이 커버한다. 재시도해도 같은 내용이라 무익하다.
                log.warning("행 %d 팬 #%d 추적 손실 — 행 조기 종료: %s",
                            row.index, k + 1, exc)
                return
            self._classify_new(scan_id, grid, tracker, frame, map_max, covered)
            prev = frame
            cx, cy = self._view_center(grid, tracker, offset, frame.shape)
            if cx > map_max[0] - _EDGE_MARGIN or cy < _EDGE_MARGIN:
                return
        if max_pans < _MAX_PANS_PER_ROW:
            return   # 점검용 팬 상한 — 정상 종료(잔여는 보충·재개 대상)
        raise TrackLost(f"행 {row.index}: 팬 상한 초과(뷰가 경계에 닿지 않음)")

    # -- 분류·커버 ----------------------------------------------------------

    def _classify_new(self, scan_id, grid, tracker, frame, map_max, covered,
                      extra_exclude=()) -> int:
        offset = tracker.offset
        exclude = list(ui.HUD_RECTS_CLIENT) + list(extra_exclude)
        records = []
        for mx, my, px, py in _band_cells(grid, tracker, frame.shape[1::-1],
                                          offset, map_max, exclude):
            if covered[my, mx]:
                continue
            r = self.clf.classify(frame, px, py)
            records.append(TileRecord(x=mx, y=my, category=r.category,
                                      kind=r.kind, occupancy=r.occupancy,
                                      confidence=r.confidence))
            covered[my, mx] = True
        if records:
            self.store.upsert_tiles(scan_id, records)
        return len(records)

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
                popup = (anchor_c[0] + ui.POPUP_RECT_REL[0],
                         anchor_c[1] + ui.POPUP_RECT_REL[1],
                         anchor_c[0] + ui.POPUP_RECT_REL[2],
                         anchor_c[1] + ui.POPUP_RECT_REL[3])
                exclude = [(r[0] + offset[0], r[1] + offset[1],
                            r[2] + offset[0], r[3] + offset[1])
                           for r in list(ui.HUD_RECTS_CLIENT) + [popup]]
                records = []
                for cell in grid.visible_cells(frame.shape[1::-1],
                                               exclude=exclude):
                    if not (0 <= cell.mx <= map_max[0]
                            and 0 <= cell.my <= map_max[1]):
                        continue
                    if covered[cell.my, cell.mx]:
                        continue
                    r = self.clf.classify(frame, cell.px, cell.py)
                    records.append(TileRecord(
                        x=cell.mx, y=cell.my, category=r.category, kind=r.kind,
                        occupancy=r.occupancy, confidence=r.confidence))
                    covered[cell.my, cell.mx] = True
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
