"""AC-02 중립형 자원 템플릿 등록 — collect_neutral.py 산출물에서.

neutral_{name}_frame.png의 표본 셀(neutral_samples.json의 screen 좌표)을
① 96x64 템플릿(assets/templates/tiles/{tpl}.png)과 ② 240x160 회귀 픽스처
(work/neutral_{name}_cell.png)로 잘라 저장하고, 분류기로 재검증한다.

전제: classifier.TEMPLATE_KINDS에 iron_neu/stone_neu3/stone_neu5가 등록되어
있어야 한다(이 스크립트 실행 전에 코드 수정). 오프라인 전용.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.vision import TileClassifier  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "work"
TILES = REPO / "assets" / "templates" / "tiles"

TPL_HALF = (48, 32)
FIX_HALF = (120, 80)
# name(collect_neutral) → (템플릿 파일명, 기대 kind, 스프라이트 중심 프레임 좌표).
# 중심은 v2 수집 프레임의 육안 확정값 — 링 검출이 철광·석재3에서 실패했고,
# 스프라이트는 타일 중심에서 수십 px 어긋나게 그려진다(매칭은 셀 중심 ±(37,23)
# 탐색 창이라 스프라이트 중심 템플릿으로 충분). 팝업 진실은 v2 팝업 캡처.
TARGETS = {
    "iron_lv1": ("iron_neu", "철광", (1912, 359)),   # 작은 광석(사실 43)
    "stone_lv3": ("stone_neu3", "석재", (1928, 356)),
    "stone_lv5": ("stone_neu5", "석재", (1939, 360)),  # 링 검출값과 일치
}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    samples = json.loads((WORK / "neutral_samples.json").read_text(encoding="utf-8"))
    for s in samples:
        name = s["name"]
        tpl_name, kind, (cx, cy) = TARGETS[name]
        frame = np.asarray(Image.open(
            WORK / f"neutral_{name}_frame.png").convert("RGB"))
        fix = frame[cy - FIX_HALF[1]:cy + FIX_HALF[1],
                    cx - FIX_HALF[0]:cx + FIX_HALF[0]]
        Image.fromarray(fix).save(WORK / f"neutral_{name}_cell.png")
        tpl = frame[cy - TPL_HALF[1]:cy + TPL_HALF[1],
                    cx - TPL_HALF[0]:cx + TPL_HALF[0]]
        Image.fromarray(tpl).save(TILES / f"{tpl_name}.png")
        print(f"템플릿 {tpl_name}.png <- {name} 화면({cx},{cy}) "
              f"팝업판독={s['popup_read']}")

    clf = TileClassifier()
    ok = True
    for s in samples:
        name = s["name"]
        _, kind, _ = TARGETS[name]
        fix = np.asarray(Image.open(
            WORK / f"neutral_{name}_cell.png").convert("RGB"))
        r = clf.classify(fix, FIX_HALF[0], FIX_HALF[1])
        good = r.kind == kind and r.occupancy == "neutral"
        ok &= good
        print(f"{name}: {r} {'OK' if good else '!! 기대 ' + kind}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
