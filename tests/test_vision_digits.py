import unittest
from pathlib import Path

import cv2
import numpy as np

from mapscan.vision import DigitReader

REPO = Path(__file__).resolve().parent.parent

# (이미지, 스트립 사각형, 기대 문자열) — 글리프 추출과 같은 팝업 좌표 소스지만
# read()는 세그먼트·크기 정규화·매칭 전체 경로를 거친다 (교차 소스 폰트 11~12px 포함)
STRIPS = [
    ("spikes/s2_zoom_grid/work3/snap_click_R.png", (2100, 210, 2220, 236), "(1020,620)"),
    ("image/9목재-내땅.png", (600, 243, 710, 268), "(989,645)"),
    ("image/3목재-동맹땅.png", (575, 338, 690, 364), "(990,647)"),
    ("image/7목재-적군.png", (600, 236, 722, 262), "(1032,663)"),
    # 봄 테마(T14.3 보강) — 실기에서 오판독("3"→"8")·판독 실패가 났던 팝업 유형
    ("spikes/t14_pan_tuning/work/pilot_p12_strip.png",
     (121, 150, 194, 180), "(138,795)"),
    ("spikes/t14_pan_tuning/work/survey_center_03_strip.png",
     (122, 132, 203, 162), "(1018,622)"),
]


def load_strip(rel: str, rect) -> np.ndarray:
    data = np.fromfile(str(REPO / rel), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"픽스처 없음: {rel}"
    x0, y0, x1, y1 = rect
    return cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)


class DigitReaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = DigitReader()

    def test_reads_popup_coordinate_strings(self):
        for rel, rect, expected in STRIPS:
            with self.subTest(src=rel):
                self.assertEqual(self.reader.read(load_strip(rel, rect)), expected)

    def test_read_coords_parses_pair(self):
        rel, rect, _ = STRIPS[0]
        self.assertEqual(self.reader.read_coords(load_strip(rel, rect)), (1020, 620))

    def test_blank_strip_reads_empty(self):
        blank = np.zeros((20, 100, 3), dtype=np.uint8)
        self.assertEqual(self.reader.read(blank), "")
        self.assertIsNone(self.reader.read_coords(blank))


if __name__ == "__main__":
    unittest.main()
