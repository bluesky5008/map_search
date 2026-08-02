# S-7 — MuMu 에뮬레이터(B안) 게이트 4·5 스파이크 판정

- 일자: 2026-08-02 (밤)
- 대상: MuMu 인스턴스 '용스' (top `0x1b1ee2`, MuMuNxDevice `0xa03b6`, nemudisplay `0xba0076` — 실행 시점 재확인, 재시작 시 변동)
- 결론: **게이트 4 통과, 게이트 5 통과.** B안 정식 전환의 기술 차단 요소 없음 → DCR-005 기안.

## 게이트 4 — WGC 캡처 + PostMessage 입력: 통과

| 항목 | 결과 | 증거 |
|---|---|---|
| WGC 바인딩 | **top(Qt 창)만 가능** — 프레임 2546×698. 자식(MuMuNxDevice/nemudisplay)은 `GraphicsCaptureItem` 변환 실패(WGC는 최상위 창만) | `cap_probe.py`, work/cap_probe.json |
| 게임 영역 원점 | **프레임 (1,40), 2544×657 @1:1** — PC 기준 UI 패치(지도·전보 버튼) 전역 매칭 NCC 0.88~0.90으로 역산, 두 패치 일치. `frame_client_offset(frame, (2544,657))`이 정확히 (1,40)을 산출 → **제품 client_offset 무변경 성립** | `analyze_frame.py`, work/analyze_frame.json |
| PostMessage 클릭 | **MuMuNxDevice가 수신**(빈 지면 클릭 → 팝업 "공터 (346,313)" 전환·육안 확인). nemudisplay는 무반응. top은 미확정(선행 클릭과 동일 타일이라 판별 불가) — 입력 대상은 device로 확정 | `click_probe.py`, work/click_after_*.png |
| 격자 기하 | 클릭 변위 역산 예측 (345,314) vs 팝업 진실 (346,313) — **PC 기저(E_MX/E_MY)와 ±1타일 정합**(픽 오차 범위, 사실 42) | 본 문서 산출 |
| 드래그 팬 | 소폭 (-300,0) → **-258px**(PC -256과 동일 게인 0.86). 좌팬 3회 **-443.0 σ0.0**(PC -443.7±0.5), 우팬 2회 **+446 σ0**(보조 패치 — 기본 패치 저점수는 S-5와 동일한 우측 HUD 가림 아티팩트). **관성 0px**(+0.5s 잔여) | `drag_probe.py`·`drag_verify2.py`, work/drag_*.json |
| 수직 팬 | 하팬 (0,+250) 전후 같은 화면점 클릭 좌표 진실 대조: 실측 (-3,-3) vs 예측 (-1.7,-3.0) — 정합 | `drag_vertical.py`, work/drag_vertical.json |
| 팝업 거동 | 첫 팬에서 선택 팝업 소멸(팝업 영역 변화율 0.884) — S-5 사실 16과 동일 | work/drag_g1_*.png |
| 권한 | MuMu는 **비관리자** — 일반 셸에서 직접 실행, UAC·상주 실행기 불필요 | 전 스크립트 비상승 실행 |

## 게이트 5 — 좌표 글리프 DigitReader 1:1 재사용: 통과

- 글리프 절대 크기 **1:1 확정** — 육안 확정 스트립 "(350,306)"의 9글자 중 7자가
  PC 템플릿과 즉시 정합(정렬 성공 자체가 크기 동일의 증거).
- 잔여 오판독은 **소스별 변형**(확립 메커니즘, 사실 19·32와 동일 유형):
  '3'→'8' 2건, ')'→'0' 1건 → MuMu 변형 3종 수확(`3_2.png`, `3_3.png`, `paren_r_4.png`).
- 변형 포함 검증: MuMu 2소스 정판독 + **PC 회귀 11소스 전부 무잠식**
  (`harvest_glyphs.py` — 임시 디렉터리 `work/digits_mumu/`, 제품 자산은 DCR 승인 후 등록).
- 현장 추가 검증: 수직 팬 검사의 (350,305)·(347,302) 판독 성공 — '2','4','5','7'도 정판독.
- 링 검출(`find_selection_highlight`)은 이 장면에서 미검출(타일 크기 성분 부재) —
  제품 재앵커는 클릭점 폴백이 있어 치명적이지 않으나 **적응 후 실사 필요**(아래).

## 관찰·제약 (적응 단계 반영)

1. **캡처 = top, 입력 = MuMuNxDevice** — 캡처/입력 HWND 분리 필요(현행은 단일 hwnd).
2. **`apply_scan_rect` 생략 필수** — 자식 클라이언트 2544×657 = 내부 해상도(1:1).
   리사이즈 시 스케일링으로 1:1 파괴. 창 종횡비 경고도 부적용.
3. MuMu 창 발견: 제목 필터 미검출 — **Qt top + MuMuNxDevice/nemudisplay 자식 구조**로
   판별(`cap_probe.find_mumu_instances` 참조 구현).
4. `client_offset`: top 프레임에 CLIENT_SIZE=(2544,657) 적용 시 기존 공식이 (1,40)을
   산출 — 탭바 40px가 자연 흡수돼 **무변경**. 단 `_verify_binding`의 창 외곽 대조
   (2546×698 vs 2552×701)는 허용 오차 24px 이내라 이 역시 무변경 성립.
5. 선택 팝업에 **"군사 스킬" 칩이 선택 타일 아래(~+150px)에 부착**(계정/콘텐츠 차이
   추정) + 링 미검출 장면 존재 — 커버 오프셋·재앵커 링 신뢰도 실사 필요.
6. 게이트 2(에뮬레이터 허용) 감시: 스파이크 전 과정에서 경고 팝업 등 이상 징후 없음
   (검증은 아니며 장시간 운용에서 계속 감시).
7. 스파이크는 그랩마다 WGC 세션을 새로 열었다(1회성 프로브 편의). 제품은 기존
   상시 세션(free-threaded) 그대로.

## 재현 순서

```
python spikes/s7_mumu/enum_windows.py            # 읽기 전용 열거
python spikes/s7_mumu/cap_probe.py 용스          # WGC 바인딩 (캡처만)
python spikes/s7_mumu/analyze_frame.py           # 원점 역산 + 판독 시험 (오프라인)
python spikes/s7_mumu/harvest_glyphs.py          # 변형 수확 + 검증 (오프라인)
python spikes/s7_mumu/click_probe.py 용스        # 클릭 1~3회
python spikes/s7_mumu/drag_probe.py 용스         # 팬 반응·재현성
python spikes/s7_mumu/drag_verify2.py 용스       # 우팬·수직 보조 재측정
python spikes/s7_mumu/drag_vertical.py 용스      # 수직 팬 좌표 진실 대조
```
