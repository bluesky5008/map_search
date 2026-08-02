"""수직 팬 결정 검증 — 팝업 좌표 진실 대조 (클릭 2회 + 하팬 1회).

같은 화면점을 팬 전후로 클릭해 팝업 좌표 차를 격자 기저 예측과 대조한다.
하팬 Δcmd=(0,+250)·게인 0.86 → 콘텐츠 +215px ↓ → 고정 화면점의 타일 변화
예측 ≈ (mx −1.7, my −3.0). 드래그 경로는 팝업(클릭점 주변)과 겹치지 않는
좌측 x=800 수직선을 쓴다.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.controller import _read_popup_coords
from mapscan.vision import DigitReader
from mapscan.win.input import PostMessageInput

from cap_probe import find_mumu_instances, try_wgc
from click_probe import game_origin, verify_detail_view

WORK = Path(__file__).parent / "work"
CLICK_AT = (1800, 300)
V_FROM, V_TO = (800, 160), (800, 410)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = sys.argv[1] if len(sys.argv) > 1 else "용스"
    inst = next((i for i in find_mumu_instances() if i["title"] == want), None)
    if inst is None:
        print(f"인스턴스 '{want}' 미발견")
        return 1
    inp = PostMessageInput(inst["device"])
    reader = DigitReader(WORK / "digits_mumu")

    def grab():
        frame, err = try_wgc(inst["top"])
        if frame is None:
            raise RuntimeError(f"캡처 실패: {err}")
        ox, oy = game_origin(frame)
        return frame[oy:oy + 657, ox:ox + 2544]

    def click_read(tag):
        frame = grab()
        verify_detail_view(frame)
        inp.click(*CLICK_AT)
        time.sleep(1.3)
        after = grab()
        coords = _read_popup_coords(reader, after, *CLICK_AT)
        from PIL import Image
        Image.fromarray(after).save(WORK / f"vpan_{tag}.png")
        print(f"  {tag}: 클릭 {CLICK_AT} → 팝업 좌표 {coords}")
        return coords

    c1 = click_read("before")
    frame = grab()
    verify_detail_view(frame)
    inp.drag(*V_FROM, *V_TO, steps=12)
    time.sleep(0.8)
    c2 = click_read("after")
    diff = None if (c1 is None or c2 is None) else (c2[0] - c1[0], c2[1] - c1[1])
    print(f"타일 변위 실측 {diff} | 예측 (-1.7, -3.0) ± 픽 오차")
    ok = diff is not None and abs(diff[0] + 1.7) <= 1.5 and abs(diff[1] + 3.0) <= 1.5
    (WORK / "drag_vertical.json").write_text(json.dumps(
        {"c1": c1, "c2": c2, "diff": diff, "ok": ok},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"판정: {'수직 팬 정상' if ok else '불일치 — 프레임 육안 확인 필요'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
