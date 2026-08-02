"""게이트 4 / 2단계 — PostMessage 클릭 반응 검사 (빈 지면 1회, 최소 입력).

nemudisplay → MuMuNxDevice → top 순으로 클릭을 보내 반응(선택 링 + 팝업)을
확인한다. 반응이 확인되는 즉시 중단(추가 클릭 없음). 클릭 전 화면 상태를
PC 기준 UI 패치(지도 버튼)로 검증한다 — 예상 밖 화면이면 입력하지 않는다.

클릭 지점 (600,450): 육안 확인된 빈 잔디(도시·팝업·부대·파란 경로선 밖).
ESC 미사용. MuMu는 비관리자라 일반 셸에서 실행.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.controller import _read_popup_coords
from mapscan.vision import DigitReader
from mapscan.vision.grid import find_selection_highlight
from mapscan.win.input import PostMessageInput

from cap_probe import find_mumu_instances, try_wgc

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work"
CLICK_AT = (600, 450)          # 게임 클라이언트 좌표 — 빈 잔디(육안 확정)
RING_NEAR = (90, 60)           # 링-클릭점 허용 거리(controller와 동일)

PC_FRAME = ROOT / "output" / "probe.png"
PC_ORIGIN = (1, 31)
MAP_BTN = (10, 470, 120, 44)   # '지도' 버튼 — 디테일 뷰 상태 검증 패치


def game_origin(frame):
    """frame_client_offset과 동일 가정(좌·우·하단 동일 테두리) — 실측 (1,40) 확증."""
    border = (frame.shape[1] - 2544) // 2
    return border, frame.shape[0] - 657 - border


def grab_game(top):
    frame, err = try_wgc(top)
    if frame is None:
        raise RuntimeError(f"캡처 실패: {err}")
    ox, oy = game_origin(frame)
    return frame[oy:oy + 657, ox:ox + 2544]


def verify_detail_view(game):
    pc = np.asarray(Image.open(PC_FRAME).convert("RGB"))
    x, y, w, h = MAP_BTN
    tpl = pc[PC_ORIGIN[1] + y:PC_ORIGIN[1] + y + h,
             PC_ORIGIN[0] + x:PC_ORIGIN[0] + x + w]
    region = game[y - 8:y + h + 8, x - 8:x + w + 8]
    score = float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max())
    if score < 0.8:
        raise RuntimeError(f"디테일 뷰 검증 실패(지도 버튼 NCC {score:.3f}) — 입력 중단")
    return score


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = sys.argv[1] if len(sys.argv) > 1 else "용스"
    inst = next((i for i in find_mumu_instances() if i["title"] == want), None)
    if inst is None:
        print(f"인스턴스 '{want}' 미발견")
        return 1
    print(f"'{want}' top={inst['top']:#x} device={inst['device']:#x} "
          f"display={inst['display']:#x}")
    reader = DigitReader(WORK / "digits_mumu")   # MuMu 변형 포함(게이트 5 산출)
    results = {"instance": want, "click_at": CLICK_AT, "targets": []}

    before = grab_game(inst["top"])
    score = verify_detail_view(before)
    print(f"디테일 뷰 검증 OK (지도 버튼 NCC {score:.3f})")
    Image.fromarray(before).save(WORK / "click_before.png")
    ring0 = find_selection_highlight(before)
    print(f"클릭 전 선택 링: {ring0}")

    cx, cy = CLICK_AT
    for name in ("display", "device", "top"):
        hwnd = inst[name]
        # top은 클라이언트 원점이 게임 원점보다 40px 위(탭바)
        y_send = cy + 40 if name == "top" else cy
        print(f"\n[{name}] hwnd={hwnd:#x} 클릭 ({cx},{y_send})")
        PostMessageInput(hwnd).click(cx, y_send)
        time.sleep(1.3)
        after = grab_game(inst["top"])
        ring = find_selection_highlight(after)
        near = (ring is not None and abs(ring[0] - cx) <= RING_NEAR[0]
                and abs(ring[1] - cy) <= RING_NEAR[1])
        coords = _read_popup_coords(reader, after, cx, cy)
        diff = float((np.abs(after.astype(np.int16)
                             - before.astype(np.int16)).sum(axis=2) > 12).mean())
        entry = {"hwnd": hex(hwnd), "ring": ring, "ring_near_click": near,
                 "popup_coords": coords, "changed_fraction": round(diff, 4)}
        results["targets"].append({name: entry})
        print(f"  링 {ring} (클릭점 근접 {near}) | 팝업 판독 {coords} | "
              f"변화율 {diff:.4f}")
        Image.fromarray(after).save(WORK / f"click_after_{name}.png")
        if near:
            results["working_target"] = name
            print(f"  → 반응 확인: {name} 이 입력을 받는다. 추가 클릭 생략")
            break
        before = after   # 다음 대상 판정은 직전 상태 기준

    (WORK / "click_probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과: {WORK / 'click_probe.json'}")
    return 0 if results.get("working_target") else 1


if __name__ == "__main__":
    sys.exit(main())
