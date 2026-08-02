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

from .win import PostMessageInput, WgcCapture, WindowSession, find_client_windows


def cmd_windows(_args) -> int:
    found = find_client_windows()
    if not found:
        print("대상 창을 찾을 수 없습니다.")
        return 1
    for w in found:
        elev = {True: "elevated", False: "normal", None: "unknown"}[w.elevated]
        print(f"hwnd={w.hwnd:#x} pid={w.pid} rect={w.rect} client={w.client} {elev}")
    return 0


def cmd_probe(args) -> int:
    """스캔 창 설정 → 캡처 → (선택) 클릭 → 복원까지 실기 점검."""
    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    with session:
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
                PostMessageInput(session.hwnd).click(x, y)
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


def main(argv: list[str] | None = None) -> int:
    # 콘솔 기본 코드페이지(cp949)로는 출력할 수 없는 문자가 있어 UTF-8로 고정한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="mapscan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("windows", help="대상 창 목록").set_defaults(func=cmd_windows)

    probe = sub.add_parser("probe", help="스캔 창 설정·캡처·클릭·복원 점검")
    probe.add_argument("--hwnd", type=lambda s: int(s, 0))
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
