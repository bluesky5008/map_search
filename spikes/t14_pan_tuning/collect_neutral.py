"""AC-02 중립형 자원 표본 수집 — 좌표를 아는 타일의 스프라이트·팝업 진실 확보.

확정 오분류(중립 철광→공터, 사실 43)와 석재 미상 처리를 해소할 템플릿 소스를
모은다. 표본 좌표는 ac01 대조·팝업 진실로 이미 확정된 지점을 쓴다:

  iron_lv1  (185,794)  "Lv.1 철광" — 공터로 오분류된 확정 사례
  stone_lv3 (175,806)  "Lv.3 석재" (ac01_a_02 팝업)
  stone_lv5 (116,829)  "Lv.5 석재" (ac01_c_07 팝업)

절차: 표본에서 (-4,+4) 떨어진 지점으로 점프(팝업이 표본을 가리지 않도록)
→ 프레임 저장 + 표본 셀 스프라이트 크롭 → 표본 클릭 → 팝업 스트립 저장·판독
(진실 재확인). 산출: work/neutral_{name}_*.png + neutral_samples.json.

관리자 권한: python spikes/t14_pan_tuning/collect_neutral.py --hwnd 0x60042
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.nav import Navigator  # noqa: E402
from mapscan.vision import DigitReader  # noqa: E402
from mapscan.win import PostMessageInput, WgcCapture, WindowSession  # noqa: E402

WORK = Path(__file__).resolve().parent / "work"
# 표본이 앵커 우측 (+620,+16)px에 놓이도록 점프점을 (-4,+4) 이동 —
# 분류 대역 안 + 점프 팝업(+370px) 밖 + 좌상 시그니처 가림 영역 밖.
JUMP_OFF = (-4, +4)
SAMPLES = [
    ("iron_lv1", 185, 794),
    ("stone_lv3", 175, 806),
    ("stone_lv5", 116, 829),
]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)

    session = WindowSession.attach(args.hwnd)
    print(f"대상: {session.info()}")
    reader = DigitReader()
    out = []
    with session:
        session.apply_scan_rect()
        time.sleep(2.0)
        with WgcCapture(session.hwnd, session.info().title) as cap:
            inp = PostMessageInput(session.hwnd)
            nav = Navigator(cap, inp)
            from mapscan.controller import _read_popup_coords
            from mapscan.vision.grid import find_selection_highlight
            for name, mx, my in SAMPLES:
                jump_to = (mx + JUMP_OFF[0], my + JUMP_OFF[1])
                grid = nav.jump(*jump_to)
                frame = cap.grab_fresh()
                if getattr(nav, "_detail_ref", None) is None:
                    nav.capture_detail_ref(frame)
                ox, oy = nav.client_offset(frame)
                # 1차 수집에서 클릭 피킹이 일관되게 my+1로 어긋났다(팝업 진실
                # "공터 (mx,my+1)" 3건) — my-1 위치를 조준해 목표 타일을 픽한다.
                px, py = grid.to_screen(mx, my - 1)
                Image.fromarray(frame).save(WORK / f"neutral_{name}_frame.png")
                nav.verify_detail_view(frame)
                inp.click(round(px - ox), round(py - oy))
                time.sleep(1.1)
                after = cap.grab_fresh()
                strip = after[max(0, round(py) - 280):round(py) + 40,
                              max(0, round(px) - 140):round(px) + 340]
                Image.fromarray(strip).save(WORK / f"neutral_{name}_popup.png")
                got = _read_popup_coords(reader, after, round(px), round(py))
                # 실제 선택된 타일의 화면 위치는 링으로 확정하고, 스프라이트는
                # 팝업·링 오염이 없는 클릭 전 프레임에서 그 위치로 크롭한다.
                ring = find_selection_highlight(after)
                if ring is not None:
                    sx, sy = round(ring[0]), round(ring[1])
                else:
                    sx, sy = round(px), round(py)
                spr = frame[max(0, sy - 80):sy + 80, max(0, sx - 120):sx + 120]
                Image.fromarray(spr).save(WORK / f"neutral_{name}_sprite.png")
                rec = {"name": name, "map": [mx, my], "jump": list(jump_to),
                       "aim": [round(px), round(py)],
                       "ring": None if ring is None else [sx, sy],
                       "popup_read": got}
                out.append(rec)
                print(f"{name} ({mx},{my}): 조준({px:.0f},{py:.0f}) "
                      f"링={None if ring is None else (sx, sy)} 팝업판독={got}")
    (WORK / "neutral_samples.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장: neutral_samples.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
