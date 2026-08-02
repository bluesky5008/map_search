"""게이트 5 — MuMu 렌더링 변형 글리프 수확·검증 (제품 자산 불변).

육안 확정 스트립 "(350,306)"에서 오판독 글리프('3'→'8')의 MuMu 변형을 수확해
**스파이크 임시 디렉터리**(work/digits_mumu = 제품 글리프 사본 + 변형)에 저장하고,
1) MuMu 스트립이 바르게 읽히는지, 2) 기존 PC 회귀 소스가 그대로 읽히는지(잠식
없음)를 함께 검증한다. 제품 등록은 DCR 승인 후 적응 단계에서 수행한다.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2
import numpy as np
from PIL import Image

from mapscan.vision import DigitReader
from mapscan.vision.digits import (_CHAR_BY_NAME, _TEXT_MAX_SAT,
                                   _TEXT_MIN_VAL, _glyph_clusters)

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).parent / "work"
SRC_DIGITS = ROOT / "assets" / "templates" / "digits"
TMP_DIGITS = WORK / "digits_mumu"
_NAME_BY_CHAR = {v: k for k, v in _CHAR_BY_NAME.items()}

MUMU_SOURCES = [
    ("g5_best_strip.png", "(350,306)"),      # Lv.1 석재 팝업(육안 확정) — '3'→'8'
    ("click_coord_area.png", "(346,313)"),   # 공터 팝업(육안 확정) — ')'→'0'
]

# PC 회귀 소스(tests/test_vision_digits.py와 동일) — 잠식 여부 확인용
PC_SOURCES = [
    ("spikes/s2_zoom_grid/work3/snap_click_R.png", (2100, 210, 2220, 236), (1020, 620)),
    ("image/9목재-내땅.png", (600, 243, 710, 268), (989, 645)),
    ("image/3목재-동맹땅.png", (575, 338, 690, 364), (990, 647)),
    ("image/7목재-적군.png", (600, 236, 722, 262), (1032, 663)),
    ("spikes/t14_pan_tuning/work/ev_r148b.png", (60, 114, 300, 144), (240, 680)),
    ("spikes/t14_pan_tuning/work/ev_r149a.png", (60, 132, 300, 162), (36, 890)),
    ("spikes/t14_pan_tuning/work/ev_r150b.png", (60, 156, 300, 186), (71, 863)),
    ("spikes/t14_pan_tuning/work/ev_r151e.png", (60, 114, 300, 144), (206, 733)),
    ("spikes/t14_pan_tuning/work/ev_r153a.png", (60, 144, 300, 174), (71, 880)),
    ("spikes/t14_pan_tuning/work/ev_r162a.png", (60, 126, 300, 156), (70, 937)),
    ("spikes/t14_pan_tuning/work/ev_r163a.png", (60, 132, 300, 162), (405, 607)),
]


def band_mask(band):
    hsv = cv2.cvtColor(band, cv2.COLOR_RGB2HSV)
    return ((hsv[:, :, 1] < _TEXT_MAX_SAT) &
            (hsv[:, :, 2] >= _TEXT_MIN_VAL)).astype(np.uint8)


def find_coord_line(reader, img, seg):
    """extract_glyphs.py(t14)와 동일한 정렬 탐색."""
    best = None
    for y0 in range(0, img.shape[0] - 30 + 1, 3):
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
    return best if best and best[0] >= len(seg) // 2 else None


def next_suffix(char):
    stem = _NAME_BY_CHAR.get(char, char)
    n = 2
    while (TMP_DIGITS / f"{stem}_{n}.png").exists():
        n += 1
    return TMP_DIGITS / f"{stem}_{n}.png"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if TMP_DIGITS.exists():
        shutil.rmtree(TMP_DIGITS)
    shutil.copytree(SRC_DIGITS, TMP_DIGITS)

    saved = []
    for name, expected in MUMU_SOURCES:
        # 직전 소스의 수확을 반영한 리더로 정렬(잔여 오판독만 수확)
        reader = DigitReader(TMP_DIGITS)
        seg = expected
        img = np.asarray(Image.open(WORK / name).convert("RGB"))
        found = find_coord_line(reader, img, seg)
        if not found:
            print(f"{name}: 좌표 줄 정렬 실패 — 스킵")
            continue
        agree, y0, boxes, band = found
        gray = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        print(f"{name}: 정렬 y={y0}, 일치 {agree}/{len(seg)}")
        if agree < len(seg) - 2:
            print("  정렬 신뢰 부족(일치 < n-2) — 수확 생략(오라벨 방지)")
            continue
        for ch_expect, (cx0, cy0, cx1, cy1) in zip(seg, boxes):
            crop = gray[cy0:cy1, cx0:cx1]
            got = reader._match(crop)
            if got == ch_expect:
                continue
            out = next_suffix(ch_expect)
            Image.fromarray(crop).save(out)
            saved.append(out.name)
            print(f"  '{ch_expect}' (현재 '{got}') → {out.name}")

    print("\n검증 (임시 디렉터리 리더):")
    r2 = DigitReader(TMP_DIGITS)
    ok = True
    for name, expected in MUMU_SOURCES:
        img = np.asarray(Image.open(WORK / name).convert("RGB"))
        want = tuple(int(v) for v in expected.strip("()").split(","))
        got = r2.read_coords(img)
        ok &= got == want
        print(f"  {name}: {got} (기대 {want}) {'OK' if got == want else 'FAIL'}")
    for rel, (x0, y0_, x1, y1), want in PC_SOURCES:
        strip = np.asarray(Image.open(ROOT / rel).convert("RGB"))[y0_:y1, x0:x1]
        got = r2.read_coords(strip)
        mark = "OK" if got == want else "FAIL"
        ok &= got == want
        print(f"  {Path(rel).name}: {got} (기대 {want}) {mark}")
    print(f"\n판정: {'통과 — 변형 ' + str(saved) + ' (임시 디렉터리)' if ok else '실패'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
