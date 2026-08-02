"""T14.3 봄 테마 좌표 글리프 추출 — 오판독("3"→"8" 등) 해소용 변형 템플릿.

지상 진실이 확인된 팝업 스트립에서 좌표 세그먼트의 글리프를 잘라
`assets/templates/digits/`에 다음 빈 접미사로 저장한다. 현재 리더가 이미
바르게 읽는 글리프는 저장하지 않는다(변형 과다는 교차 오판독 위험).

소스(육안 확정):
  pilot_p12_strip.png  — "서량-천수군 (138,795)" (점령형 팝업, 스캔 실기에서
                          (187,793)으로 오판독된 유형)
  survey_center_03_strip.png — "절벽 (1018, 622)" (특수지형 팝업)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mapscan.vision import DigitReader                       # noqa: E402
from mapscan.vision.digits import (_CHAR_BY_NAME, _TEXT_MAX_SAT,  # noqa: E402
                                   _TEXT_MIN_VAL, _glyph_clusters)

WORK = Path(__file__).resolve().parent / "work"
DIGITS_DIR = Path(__file__).resolve().parents[2] / "assets" / "templates" / "digits"
_NAME_BY_CHAR = {v: k for k, v in _CHAR_BY_NAME.items()}

SOURCES = [
    ("pilot_p12_strip.png", "(138,795)"),
    ("survey_center_03_strip.png", "(1018,622)"),
    # 재앵커 실패 증거(controller._save_evidence, 행 151 실기) — '0'→'(' 오인 등
    ("evidence_row151_a.png", "(70,870)"),
    ("evidence_row151_b.png", "(104,836)"),
]


def band_mask(band: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV)
    return ((hsv[:, :, 1] < _TEXT_MAX_SAT) &
            (hsv[:, :, 2] >= _TEXT_MIN_VAL)).astype(np.uint8)


def find_coord_line(reader, img, seg):
    """좌표 줄 y 밴드와 세그먼트 글리프 박스를 찾는다 — 기대 문자열을 클러스터
    열 위로 슬라이딩 정렬해 일치 수가 최대인 밴드·정렬을 택한다(오판독이 많아
    괄호 탐지에 의존할 수 없다). 최종 채택 여부는 호출자의 재검증이 판정한다."""
    h = img.shape[0]
    best = None
    for y0 in range(0, h - 30, 3):
        band = img[y0:y0 + 30]
        clusters = _glyph_clusters(band_mask(band))
        if len(clusters) < len(seg):
            continue
        gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        chars = [reader._match(gray[cy0:cy1, cx0:cx1])
                 for cx0, cy0, cx1, cy1 in clusters]
        for off in range(len(clusters) - len(seg) + 1):
            agree = sum(c == e for c, e in zip(chars[off:off + len(seg)], seg))
            if best is None or agree > best[0]:
                best = (agree, y0, clusters[off:off + len(seg)], band)
    if best and best[0] >= len(seg) // 2:
        return best
    return None


def next_suffix(char: str) -> Path:
    stem = _NAME_BY_CHAR.get(char, char)
    n = 2
    if not (DIGITS_DIR / f"{stem}.png").exists():
        return DIGITS_DIR / f"{stem}.png"
    while (DIGITS_DIR / f"{stem}_{n}.png").exists():
        n += 1
    return DIGITS_DIR / f"{stem}_{n}.png"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    reader = DigitReader()
    saved = []
    for name, expected in SOURCES:
        img = np.asarray(Image.open(WORK / name).convert("RGB"))
        seg = expected.replace(" ", "")
        found = find_coord_line(reader, img, seg)
        if not found:
            # '0'이 두 성분으로 쪼개지는 폰트(evidence_row151_*)는 클러스터 수가
            # 어긋나 정렬 불가 — 세그먼테이션 개선(높이 인지 병합·과폭 분할)
            # 전까지 스킵한다(plan.md 확정 사실 35).
            print(f"{name}: 좌표 줄 정렬 실패 — 스킵(세그먼테이션 한계)")
            continue
        _, y0, boxes, band = found
        gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        assert len(boxes) == len(seg), (name, len(boxes), seg)
        print(f"{name}: 좌표 줄 y={y0}, 기대 '{seg}'")
        for ch_expect, (cx0, cy0, cx1, cy1) in zip(seg, boxes):
            crop = gray[cy0:cy1, cx0:cx1]
            got = reader._match(crop)
            if got == ch_expect:
                continue
            out = next_suffix(ch_expect)
            Image.fromarray(crop).save(out)
            saved.append((name, ch_expect, got, out.name))
            print(f"  '{ch_expect}' (현재 '{got}') → {out.name}")

    print("\n재검증 (새 리더):")
    reader2 = DigitReader()
    ok = True
    for name, expected in SOURCES:
        img = np.asarray(Image.open(WORK / name).convert("RGB"))
        seg = expected.replace(" ", "")
        found = find_coord_line(reader2, img, seg)
        if not found and find_coord_line(reader, img, seg) is None:
            continue   # 추출 단계에서 스킵한 소스는 검증도 스킵
        got = None
        if found:
            _, y0, boxes, band = found
            x0 = min(b[0] for b in boxes)
            x1 = max(b[2] for b in boxes)
            strip = band[:, max(0, x0 - 4):x1 + 4]
            got = reader2.read_coords(strip)
        want = tuple(int(v) for v in re.findall(r"\d+", expected))
        print(f"  {name}: read_coords={got} (기대 {want})")
        ok &= got == want
    if not ok:
        for _, _, _, fname in saved:
            (DIGITS_DIR / fname).unlink(missing_ok=True)
        print(f"검증 실패 — 저장한 변형 {len(saved)}개 롤백")
        return 1
    print(f"저장 {len(saved)}개 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
