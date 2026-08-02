"""드래그 검증 보강 — 우팬·수직팬을 좌측 보조 패치로 재측정 (S-5와 동일 기법).

우팬은 기본 패치(x1460~2220)가 이동 후 부대 패널 아래로 들어가 저점수 오매칭이
난다(S-5 실측 동일). 보조 패치(x700~1460, HUD 밖)로 실제 이동량을 잰다.
"""

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PIL import Image

from mapscan.win.input import PostMessageInput

from cap_probe import find_mumu_instances, try_wgc
from click_probe import game_origin, verify_detail_view
from drag_probe import H_FROM, H_TO, V_FROM, V_TO, find_shift

WORK = Path(__file__).parent / "work"
AUX_STRIP = (700, 96, 760, 62)   # 좌측 보조 패치 — HUD 아이콘열(x<620) 밖


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    want = sys.argv[1] if len(sys.argv) > 1 else "용스"
    inst = next((i for i in find_mumu_instances() if i["title"] == want), None)
    if inst is None:
        print(f"인스턴스 '{want}' 미발견")
        return 1
    inp = PostMessageInput(inst["device"])

    def grab():
        frame, err = try_wgc(inst["top"])
        if frame is None:
            raise RuntimeError(f"캡처 실패: {err}")
        ox, oy = game_origin(frame)
        return frame[oy:oy + 657, ox:ox + 2544]

    results = {}
    plan = [("right", H_TO, H_FROM), ("left", H_FROM, H_TO),
            ("right", H_TO, H_FROM), ("down", V_FROM, V_TO),
            ("up", V_TO, V_FROM)]
    moves: dict = {}
    for i, (name, src, dst) in enumerate(plan):
        before = grab()
        verify_detail_view(before)
        inp.drag(*src, *dst, steps=12)
        time.sleep(0.8)
        after = grab()
        dcmd = (dst[0] - src[0], dst[1] - src[1])
        dx, dy, score = find_shift(before, after, dcmd, rect=AUX_STRIP)
        moves.setdefault(name, []).append((dx, dy, score))
        print(f"  #{i + 1} {name:5s} 보조 패치 이동 ({dx:5d},{dy:4d}) 점수 {score}")
        if i == 3:
            Image.fromarray(after).save(WORK / "drag_v_down.png")
    for name, vals in moves.items():
        xs, ys = [v[0] for v in vals], [v[1] for v in vals]
        results[name] = {"raw": vals,
                         "mean": [statistics.mean(xs), statistics.mean(ys)]}
    (WORK / "drag_verify2.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {WORK / 'drag_verify2.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
