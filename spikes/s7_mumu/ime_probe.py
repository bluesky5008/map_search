"""좌표 입력 오버레이(안드로이드 IME 바) 조작 진단 — 현재 열린 오버레이 대상.

단계별로 ① WM_CHAR 백스페이스 ② 숫자 타이핑 ③ Enter 를 보내고 매 단계
프레임을 저장한다. 오버레이 텍스트 영역(상단 바)의 변화로 판정한다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
from PIL import Image

from mapscan.nav import Navigator, ui
from mapscan.win import PostMessageInput, WgcCapture, find_mumu_instance

WORK = Path(__file__).parent / "work"
VK_RETURN = 0x0D
BAR = (30, 35, 1900, 105)   # 오버레이 텍스트 바(프레임 좌표)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    inst = find_mumu_instance("용스", expect_client=ui.CLIENT_SIZE)
    inp = PostMessageInput(inst.device)
    with WgcCapture(inst.top, inst.title) as cap:
        nav = Navigator(cap, inp)

        def shot(tag):
            time.sleep(0.5)
            f = cap.grab_fresh()
            Image.fromarray(f).save(WORK / f"ime_{tag}.png")
            bar = f[BAR[1]:BAR[3], BAR[0]:BAR[2]]
            dark = float((bar.mean(axis=2) < 120).mean())
            print(f"{tag}: 지도마커 {nav.map_mode_score(f):.2f} "
                  f"바 어두운 비율 {dark:.3f}")
            return f

        shot("0_start")
        # ① WM_CHAR 백스페이스(문자 8) — PC 입력란은 무시했지만 IME 에디트는 다를 수 있다
        for _ in range(8):
            inp.type_text("\b")
        shot("1_charbs")
        # ② 숫자 타이핑
        inp.type_text("15")
        shot("2_typed")
        # ③ Enter — 확정(✓ 동등) 기대
        inp.key(VK_RETURN)
        shot("3_enter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
