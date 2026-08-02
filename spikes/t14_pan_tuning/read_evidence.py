"""재앵커 판독 실패 증거(output/evidence/*.png)를 현재 리더로 재현 분석.

증거 스트립은 controller._save_evidence가 저장한 (py-280..py+40, px-140..px+340)
크롭이므로 클릭점이 (140, 280)이다. _read_popup_coords와 같은 슬라이드로
판독을 재현하고, 실패 소스는 세그먼테이션 단계(클러스터 폭·간격)를 덤프한다.

세그먼테이션 개선(높이 인지 병합·과폭 분할)의 근거·회귀 코퍼스로 쓴다. 오프라인 전용.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.controller import _read_popup_coords   # noqa: E402
from mapscan.vision import DigitReader              # noqa: E402

EVID = Path(__file__).resolve().parents[2] / "output" / "evidence"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    reader = DigitReader()
    files = sorted(EVID.glob("reanchor_*.png"))
    ok = 0
    for path in files:
        frame = np.asarray(Image.open(path).convert("RGB"))
        got = _read_popup_coords(reader, frame, 140, 280)
        # 슬라이드 없이 고정 위치의 원시 판독도 함께(실패 모드 관찰용)
        raws = []
        for dy in (-148, -130, -112):
            strip = frame[280 + dy:280 + dy + 34, 0:340]
            raws.append(reader.read(strip))
        status = "OK " if got else "FAIL"
        if got:
            ok += 1
        print(f"{status} {path.name}: 투표={got} 원시={raws}")
    print(f"\n판독 성공 {ok}/{len(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
