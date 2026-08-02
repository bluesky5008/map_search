"""게이트 4/5 오프라인 분석 — 캡처 프레임만 사용(입력 없음).

1) 게임 영역 원점 정밀 산출: PC 기준 프레임의 고정 UI 패치(지도·전보 버튼 등)를
   MuMu top 프레임에서 전역 탐색해 원점을 역산한다. NCC가 높으면 UI 1:1 스케일도
   함께 확증된다(게이트 3·5 보조).
2) 게이트 5: 프레임의 선택 팝업 좌표 문자열을 제품 DigitReader로 판독한다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.vision import DigitReader

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work"

# PC 기준 프레임(디테일 뷰, 클라이언트 2544x657, 프레임 내 원점 (1,31))
PC_FRAME = ROOT / "output" / "probe.png"
PC_ORIGIN = (1, 31)

# 계정 무관·정적 UI 패치 (클라이언트 좌표 x, y, w, h) — 좌하단 버튼열·우하단 도위
PATCHES = {
    "map_btn": (10, 470, 120, 44),      # '지도' 버튼
    "jeonbo_btn": (10, 528, 120, 44),   # '전보' 버튼
    "seosin_btn": (10, 640, 120, 16),   # '서신' 버튼(하단 절반만)
}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mumu = np.asarray(Image.open(WORK / "cap_top.png").convert("RGB"))
    pc = np.asarray(Image.open(PC_FRAME).convert("RGB"))
    results = {}

    origins = []
    for name, (x, y, w, h) in PATCHES.items():
        tpl = pc[PC_ORIGIN[1] + y:PC_ORIGIN[1] + y + h,
                 PC_ORIGIN[0] + x:PC_ORIGIN[0] + x + w]
        res = cv2.matchTemplate(mumu, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        origin = (loc[0] - x, loc[1] - y)
        origins.append((origin, score))
        results[name] = {"found": loc, "ncc": round(float(score), 4),
                         "implied_origin": origin}
        print(f"패치 {name:12s} NCC {score:.4f} → 게임 원점 추정 {origin}")

    good = [o for o, s in origins if s >= 0.8]
    origin = good[0] if good else None
    agree = len(set(good)) == 1 if good else False
    results["game_origin"] = {"value": origin, "all_agree": agree,
                              "n_good": len(good)}
    print(f"게임 원점 판정: {origin} (고신뢰 {len(good)}/{len(origins)}, "
          f"전원 일치 {agree})")

    if origin:
        ox, oy = origin
        game = mumu[oy:oy + 657, ox:ox + 2544]
        Image.fromarray(game).save(WORK / "game_exact.png")
        # 게이트 5: 팝업 좌표 문자열 판독 — 팝업 상단 중앙 부근을 슬라이딩 탐색
        reader = DigitReader()
        found = None
        for y0 in range(80, 200, 6):
            for x0 in range(1150, 1600, 50):
                strip = game[y0:y0 + 34, x0:x0 + 380]
                got = reader.read_coords(strip)
                if got:
                    found = {"coords": got, "strip_at": [x0, y0]}
                    Image.fromarray(strip).save(WORK / "g5_strip.png")
                    break
            if found:
                break
        results["gate5_read"] = found
        print(f"게이트 5 판독: {found}")

    (WORK / "analyze_frame.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
