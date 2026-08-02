"""MuMu 인스턴스 캡처 건강 검사 (읽기 전용) — 원격/모니터 off 운용 점검용.

인스턴스별로 제품 WgcCapture로 프레임 2장을 1초 간격으로 받아
① 프레임 크기·게임 영역, ② 프레임 생동성(게임 상시 애니메이션 → 변화율 > 0),
③ 디테일 뷰 UI 패치(지도 버튼) NCC 를 보고한다. 입력은 보내지 않는다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.win import WgcCapture, find_mumu_instances

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work"
PC_FRAME = ROOT / "output" / "probe.png"
PC_ORIGIN = (1, 31)
MAP_BTN = (10, 470, 120, 44)


def game_crop(frame):
    border = (frame.shape[1] - 2544) // 2
    oy = frame.shape[0] - 657 - border
    return frame[oy:oy + 657, border:border + 2544]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pc = np.asarray(Image.open(PC_FRAME).convert("RGB"))
    x, y, w, h = MAP_BTN
    tpl = pc[PC_ORIGIN[1] + y:PC_ORIGIN[1] + y + h,
             PC_ORIGIN[0] + x:PC_ORIGIN[0] + x + w]
    ok_all = True
    for inst in find_mumu_instances():
        try:
            with WgcCapture(inst.top, inst.title) as cap:
                f1 = cap.grab_fresh()
                time.sleep(1.0)
                f2 = cap.grab_fresh()
        except RuntimeError as exc:
            print(f"'{inst.title}': 캡처 실패 — {exc}")
            ok_all = False
            continue
        g1, g2 = game_crop(f1), game_crop(f2)
        live = float((np.abs(g1.astype(np.int16) - g2.astype(np.int16))
                      .sum(axis=2) > 12).mean())
        region = g2[y - 8:y + h + 8, x - 8:x + w + 8]
        ncc = float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max())
        Image.fromarray(f2).save(WORK / f"health_{inst.title}.png")
        # NCC 기준 0.7: RDP 세션 렌더링은 로컬(0.90) 대비 ~0.75로 미세 저하가
        # 정상이다(실측 — 스캔 전 경로 동작 확인됨). 0.7 미만이면 화면 이상.
        verdict = "정상" if live > 0.001 and ncc >= 0.7 else "확인 필요"
        ok_all &= verdict == "정상"
        print(f"'{inst.title}': 프레임 {f1.shape[1]}x{f1.shape[0]} | "
              f"1초 변화율 {live:.4f} ({'갱신 중' if live > 0.001 else '정지?'}) | "
              f"지도 버튼 NCC {ncc:.3f} | {verdict} → work/health_{inst.title}.png")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
