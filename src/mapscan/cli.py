"""mapscan CLI — 현재는 win·vision 계층 점검 명령만 제공한다(구현 진행 중)."""

from __future__ import annotations

import argparse
import collections
import csv
import logging
import sys
import time

import numpy as np
from PIL import Image

from .win import (PostMessageInput, WgcCapture, WindowSession,
                  find_client_windows, find_mumu_instance, find_mumu_instances)


ACCOUNT_NAME_RECT = (50, 55, 400, 110)  # 프레임 좌상단 계정명 영역


def _resolve_target(args) -> tuple[WindowSession, int, bool]:
    """대상 확정 → (세션[캡처 hwnd], 입력 hwnd, 스캔 창 설정 여부).

    MuMu(DCR-005): 캡처는 top, 입력은 MuMuNxDevice로 분리하고, 창 크기
    설정(apply_scan_rect)은 생략한다 — 자식 클라이언트 = 내부 해상도(1:1)라
    리사이즈가 스케일링을 만든다. 내부 해상도는 UI 상수 전제와 일치해야 한다.
    """
    if getattr(args, "mumu", None):
        from .nav import ui
        inst = find_mumu_instance(args.mumu, expect_client=ui.CLIENT_SIZE)
        session = WindowSession(inst.top)
        session.check_permission()
        print(f"MuMu '{inst.title}': top={inst.top:#x} device={inst.device:#x} "
              f"클라이언트 {inst.client[0]}x{inst.client[1]} (1:1, 창 설정 생략)")
        return session, inst.device, False
    session = WindowSession.attach(args.hwnd)
    return session, session.hwnd, True


def cmd_windows(args) -> int:
    mumu = find_mumu_instances()
    for m in mumu:
        print(f"MuMu '{m.title}': top={m.top:#x} device={m.device:#x} "
              f"client={m.client[0]}x{m.client[1]}")
    found = find_client_windows()
    if not found and not mumu:
        print("대상 창을 찾을 수 없습니다.")
        return 1
    for w in found:
        elev = {True: "elevated", False: "normal", None: "unknown"}[w.elevated]
        print(f"hwnd={w.hwnd:#x} pid={w.pid} rect={w.rect} client={w.client} {elev}")
        if args.crops:
            # HWND는 클라이언트 재시작 시 바뀐다. 어느 창이 어느 계정인지
            # 눈으로 확인할 수 있도록 계정명 영역을 저장한다.
            with WgcCapture(w.hwnd, w.title) as cap:
                x0, y0, x1, y1 = ACCOUNT_NAME_RECT
                path = f"{args.crops}/account_{w.hwnd:#x}.png"
                Image.fromarray(cap.grab_fresh()[y0:y1, x0:x1]).save(path)
                print(f"  계정명 저장: {path}")
    return 0


def cmd_probe(args) -> int:
    """스캔 창 설정 → 캡처 → (선택) 클릭 → 복원까지 실기 점검."""
    session, input_hwnd, apply_rect = _resolve_target(args)
    print(f"대상: {session.info()}")
    with session:
        if apply_rect:
            client = session.apply_scan_rect()
            print(f"스캔 창 클라이언트: {client[0]}x{client[1]} "
                  f"(종횡비 {client[0] / client[1]:.2f})")
            time.sleep(args.settle)

        capture = WgcCapture(session.hwnd, session.info().title)
        with capture:
            frame = capture.grab_fresh()
            Image.fromarray(frame).save(args.out)
            print(f"프레임 저장: {args.out} ({frame.shape[1]}x{frame.shape[0]})")

            if args.click:
                x, y = args.click
                before = capture.grab_fresh()
                PostMessageInput(input_hwnd).click(x, y)
                time.sleep(1.0)
                after = capture.grab_fresh()
                changed = int((before != after).sum())
                Image.fromarray(after).save(args.out.replace(".png", "_after.png"))
                print(f"클릭 ({x},{y}) 후 변경 픽셀 {changed:,}개: "
                      f"{'반응 확인' if changed > 10000 else '반응 없음'}")
    print("창 배치 복원 완료")
    return 0


def cmd_classify(args) -> int:
    """캡처 1장에서 가시 타일의 분류·점령상태를 산출한다 (vision 계층 점검)."""
    from .vision import GridMapper, TileClassifier

    frame = np.asarray(Image.open(args.image).convert("RGB"))
    anchor_frame = frame if args.anchor_image is None else \
        np.asarray(Image.open(args.anchor_image).convert("RGB"))
    grid = GridMapper.from_frame(anchor_frame, tuple(args.anchor))
    print(f"앵커: 맵 {grid.anchor_map} = 픽셀 "
          f"({grid.anchor_px[0]:.0f},{grid.anchor_px[1]:.0f})")

    clf = TileClassifier(grid.basis)
    cells = grid.visible_cells(frame.shape[1::-1])
    results = [(c, clf.classify(frame, c.px, c.py)) for c in cells]

    counts = collections.Counter(
        (r.category, r.kind, r.occupancy) for _, r in results)
    print(f"가시 타일 {len(results)}개:")
    for (cat, kind, occ), n in counts.most_common():
        print(f"  {cat:10s} {kind:4s} {occ:8s} {n:4d}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["x", "y", "category", "kind", "occupancy", "confidence"])
            for c, r in sorted(results, key=lambda t: (t[0].my, t[0].mx)):
                w.writerow([c.mx, c.my, r.category, r.kind, r.occupancy, r.confidence])
        print(f"CSV 저장: {args.csv}")
    return 0


def cmd_scan(args) -> int:
    """MODE-A2 행 기반 전체 스캔 (설계 v3 §4.3). 재실행 시 체크포인트에서 재개."""
    from .controller import ScanController, parse_until
    from .nav import Navigator
    from .store import DataStore, export_csv

    until_ts = None
    if args.until:
        try:
            deadline = parse_until(args.until)
        except ValueError as exc:
            raise SystemExit(str(exc))
        until_ts = deadline.timestamp()
        print(f"정지 예정 시각: {deadline:%Y-%m-%d %H:%M} (행 경계에서 정지)")
    store = DataStore(args.db)
    session, input_hwnd, apply_rect = _resolve_target(args)
    print(f"대상: {session.info()}")
    with session:
        if apply_rect:
            client = session.apply_scan_rect()
            print(f"스캔 창: {client[0]}x{client[1]} "
                  f"(종횡비 {client[0] / client[1]:.2f})")
            time.sleep(args.settle)
        with WgcCapture(session.hwnd, session.info().title) as capture:
            nav = Navigator(capture, PostMessageInput(input_hwnd),
                            ime_overlay=bool(getattr(args, "mumu", None)))
            ctl = ScanController(nav, store)
            map_max = tuple(args.map_size) if args.map_size else None
            summary = ctl.run("A2", map_max=map_max,
                              resume=not args.new, max_rows=args.max_rows,
                              start_row=args.start_row, max_pans=args.max_pans,
                              end_row=args.end_row, until=until_ts)
    print(f"스캔 {summary['scan_id']} {summary['status']}: "
          f"{summary['covered']:,}/{summary['total']:,}타일, "
          f"행 {summary['rows']}개(실패 {summary['row_failures']})")
    if summary["status"] == "paused":
        print("정지 시각 도달 — 체크포인트 저장됨, 다음 실행에서 재개")
    if args.csv and summary["status"] == "done":
        for path in export_csv(store, summary["scan_id"], args.csv):
            print(f"CSV 저장: {path}")
    store.close()
    if summary["status"] == "aborted":
        # 종료 코드 2 = 계통적 고장으로 중단(DCR-006). 스케줄 태스크의 결과
        # 코드와 래퍼 로그에 비정상이 드러나야 무인 운용에서 인지된다.
        print(f"스캔 중단: {summary['aborted']}\n"
              "  대상 클라이언트(에뮬레이터·게임) 상태를 확인하세요. "
              "체크포인트는 재시도 지점으로 저장됐습니다.")
        return 2
    return 0


def cmd_chunks(args) -> int:
    """다계정 병렬 청크 분할 안내 — 행 범위와 실행 명령을 출력한다(DCR-005)."""
    from .controller import plan_rows

    total = len(plan_rows(tuple(args.map_size)))
    n = args.accounts
    bounds = [round(i * total / n) for i in range(n + 1)]
    print(f"전체 {total}행을 {n}청크로 분할 (맵 {args.map_size[0]}x{args.map_size[1]}):")
    for i in range(n):
        a, b = bounds[i], bounds[i + 1]
        print(f"  청크 {i + 1}: 행 [{a}, {b})  — 최초 실행:\n"
              f"    mapscan scan --mumu <인스턴스{i + 1}> --db output/part{i + 1}.db "
              f"--map-size {args.map_size[0]} {args.map_size[1]} "
              f"--new --start-row {a} --end-row {b}\n"
              f"    (중단 후 재개는 --new/--start-row 없이 --end-row {b}만)")
    print("전 청크 완료 후:\n"
          "  mapscan merge --db output/full.db --parts "
          + " ".join(f"output/part{i + 1}.db" for i in range(n))
          + "\n  mapscan scan --mumu <아무 인스턴스> --db output/full.db "
            "--csv output/full_csv   # 병합분 재개 → 보충 방문만 수행 → 완료·CSV")
    return 0


def cmd_merge(args) -> int:
    """청크 DB들을 하나의 스캔으로 병합한다(같은 좌표는 captured_at 최신 우선).

    병합 스캔의 체크포인트를 전체 행 수로 설정해, 이후 `scan --db <대상>`
    재개가 곧바로 보충 방문 단계로 진입하게 한다.
    """
    from .controller import plan_rows
    from .store import DataStore

    store = DataStore(args.db)
    scan_id = store.create_scan("A2", zoom_level="detail",
                                capture_mode="background")
    map_max = None
    for part in args.parts:
        result = store.merge_scan_from(scan_id, part)
        got = result["map_max"]
        if got != (None, None):
            if map_max is not None and got != map_max:
                raise SystemExit(f"맵 크기 불일치: {part} {got} ≠ {map_max} — "
                                 "다른 월드의 청크가 섞였는지 확인하세요")
            map_max = got
        print(f"병합: {part} (스캔 {result['source_scan_id']}) → "
              f"{result['merged']:,}건 반영")
    if map_max is None:
        raise SystemExit("병합할 타일이 없습니다")
    store.set_map_size(scan_id, *map_max)
    store.set_checkpoint(scan_id, len(plan_rows(tuple(map_max))))
    total = store.tile_count(scan_id)
    print(f"병합 완료: 스캔 {scan_id}, 총 {total:,}타일, 맵 {map_max[0]}x{map_max[1]}")
    print(f"다음: mapscan scan --mumu <인스턴스> --db {args.db} --csv <경로> "
          "(재개 → 보충 방문 → 완료·CSV)")
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    # 콘솔 기본 코드페이지(cp949)로는 출력할 수 없는 문자가 있어 UTF-8로 고정한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="mapscan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    windows = sub.add_parser("windows", help="대상 창 목록")
    windows.add_argument("--crops", metavar="DIR",
                         help="창별 계정명 영역을 이 디렉터리에 저장(창 식별용)")
    windows.set_defaults(func=cmd_windows)

    probe = sub.add_parser("probe", help="스캔 창 설정·캡처·클릭·복원 점검")
    ptarget = probe.add_mutually_exclusive_group()
    ptarget.add_argument("--hwnd", type=lambda s: int(s, 0))
    ptarget.add_argument("--mumu", metavar="인스턴스명",
                         help="MuMu 인스턴스 대상(캡처 top·입력 device, 창 설정 생략)")
    probe.add_argument("--out", default="probe.png")
    probe.add_argument("--settle", type=float, default=2.0)
    probe.add_argument("--click", type=int, nargs=2, metavar=("X", "Y"))
    probe.set_defaults(func=cmd_probe)

    classify = sub.add_parser("classify", help="캡처 1장 타일 분류(vision 점검)")
    classify.add_argument("--image", required=True, help="분류할 캡처 PNG")
    classify.add_argument("--anchor", type=int, nargs=2, required=True,
                          metavar=("MX", "MY"), help="선택 하이라이트 타일의 맵 좌표")
    classify.add_argument("--anchor-image",
                          help="하이라이트가 있는 프레임(기본: --image)")
    classify.add_argument("--csv", help="타일별 결과 CSV 저장 경로")
    classify.set_defaults(func=cmd_classify)

    scan = sub.add_parser("scan", help="MODE-A2 전체 스캔 (행 기반, 재개 가능)")
    target = scan.add_mutually_exclusive_group(required=True)
    target.add_argument("--hwnd", type=lambda s: int(s, 0),
                        help="대상 창 HWND (mapscan windows --crops 로 확인)")
    target.add_argument("--mumu", metavar="인스턴스명",
                        help="MuMu 인스턴스 대상(캡처 top·입력 device, 창 설정 생략)")
    scan.add_argument("--db", default="output/mapscan.db")
    scan.add_argument("--map-size", type=int, nargs=2, metavar=("MX", "MY"),
                      help="맵 최대 좌표(생략 시 자동 감지 또는 재개 스캔 값)")
    scan.add_argument("--max-rows", type=int,
                      help="이번 실행에서 처리할 최대 행 수(부분 실행·점검용)")
    scan.add_argument("--start-row", type=int,
                      help="체크포인트 대신 이 행부터 시작(점검·지정 영역용)")
    scan.add_argument("--end-row", type=int,
                      help="이 행 직전까지만 처리(다계정 병렬 청크 상한 — "
                           "보충 방문 생략, 병합 후 일괄 보충)")
    scan.add_argument("--max-pans", type=int,
                      help="행당 팬 횟수 상한(점검용 — 잔여는 보충·재개 대상)")
    scan.add_argument("--until", metavar="HH:MM",
                      help="이 시각 도달 시 행 경계에서 체크포인트 저장 후 정지"
                           "(현재보다 과거면 익일로 해석 — 예약 무인 운용)")
    scan.add_argument("--new", action="store_true",
                      help="재개하지 않고 새 스캔 시작")
    scan.add_argument("--settle", type=float, default=2.0)
    scan.add_argument("--csv", help="완료 시 CSV 내보내기 경로")
    scan.set_defaults(func=cmd_scan)

    chunks = sub.add_parser("chunks", help="다계정 병렬 청크 분할 안내(DCR-005)")
    chunks.add_argument("--map-size", type=int, nargs=2, metavar=("MX", "MY"),
                        default=[1619, 1619])
    chunks.add_argument("--accounts", type=int, required=True,
                        help="병렬 계정(MuMu 인스턴스) 수")
    chunks.set_defaults(func=cmd_chunks)

    merge = sub.add_parser("merge", help="청크 DB 병합(최신 captured_at 우선)")
    merge.add_argument("--db", required=True, help="병합 대상 DB(새 스캔 생성)")
    merge.add_argument("--parts", nargs="+", required=True,
                       help="청크 DB 경로들")
    merge.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
