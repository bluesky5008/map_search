# 구현 계획 — 월드맵 토지정보 추출기 v1 (MODE-A2)

- 작업 ID: 20260801-worldmap-land-scan
- 기준선: **요구사항 v2 / 설계 v2 (2026-08-02 승인, DCR-001)**
- 최종 갱신: 2026-08-02
- 이 문서는 wf-implement의 작업 기록이며 진행 상태를 여기서 갱신한다. **세션을 새로 시작하면 이 문서를 가장 먼저 읽는다.**

## 현재 상태 요약 (재개 지점)

| 구분 | 상태 |
|---|---|
| 요구사항·설계 | v2 승인 완료. 추가 승인 대기 항목 없음 |
| 스파이크 | S-1(백그라운드 캡처·입력) 통과, S-2(줌·자원·종횡비) 완료. S-3·S-4는 T12에서 확인 |
| 구현 완료 | T8 골격, T10 store 계층, T9 win 계층, **T11 vision 계층**, 부가 도구(창 크기 조절 스크립트) |
| **다음 작업** | **T12 nav 계층** (Navigator, ScanPlanner). T11 실측 발견(아래 "T11 결과") 반영 필요 |
| 테스트 | `python -m unittest discover -s tests` — 40건 전부 통과 (환경 주의: `.venv`에 `pip install -e . --no-deps` 필요) |
| 커밋 | main 브랜치. T11까지 로컬 커밋 완료 — push는 사용자 요청 시 수행 |

실행 전제: 게임 클라이언트가 관리자 권한으로 실행 중이므로 **도구도 관리자 권한 필요**. 스캔 창은 종횡비 3 이상(사분면)으로 맞춘다.

## 기준선

- 관련 요구사항: [requirements.md](requirements.md) v2 — FR-01, FR-02, FR-03b, FR-05, FR-07~12, NFR-01~06
- 관련 설계: [design.md](design.md) v2
- 관련 ADR: ADR-001(스택), ADR-002(캡처·입력, S-1 통과), ADR-003(저장), ADR-004(모드 구조), ADR-005(창 종횡비)
- 관련 DCR: [DCR-001](changes/DCR-001-mode-a-zoom-limits.md) 승인 — v1 구현 범위는 **MODE-A2만**

## 스파이크 확정 사실 (구현 제약)

| # | 사실 | 근거 |
|---|---|---|
| 1 | WGC로 가림 상태 캡처 가능. PrintWindow는 검은 프레임(사용 불가) | S-1a |
| 2 | 게임이 elevated면 도구도 관리자 권한 필요(PostMessage/SetWindowPos) | S-1b |
| 3 | 캡처 세션은 **HWND 바인딩** 필수(동일 제목 다중 창) | S-1a |
| 4 | 전략 뷰는 중립 타일 미렌더링 → 자원 종류는 디테일 뷰에서만 | S-2 |
| 5 | 가시 타일 수 ∝ 창 종횡비. 사분면(2544x657)에서 246타일 | S-2c |
| 6 | 스캔 창에서 디테일 줌 최종 단계 = 최대 축소(한 노치 더 = 전략 뷰) | S-2c |
| 7 | 클릭↔좌표 대응 데이터: (700,350)→(1012,629), (2100,350)→(1020,620) @2544x657 | S-2c |

## 계획

### 1부 — 스파이크 (완료)

- [x] T1. 개발 환경 준비 (.venv, pillow/numpy/opencv/windows-capture)
- [x] T2. S-1a 백그라운드 캡처 — 성공(WGC)
- [x] T3. S-1b 백그라운드 입력 — 성공(관리자 권한 필요)
- [x] T4. S-1 판정 기록 + ADR-002 확정
- [x] T5. S-2 줌·자원 식별·그리드 → P-01 실패, DCR-001 발행·승인
- [x] T5b. S-2b/c 창 크기·종횡비 → ADR-005
- [ ] T6. S-3 좌표 입력란 숫자 판독 — 구현 중 T12에서 확인
- [ ] T7. S-4 팝업 오클루전 — 구현 중 T12에서 확인

### 2부 — 제품 구현 (MODE-A2)

- [x] T8. 프로젝트 골격 (src/mapscan, pyproject, tests)
- [x] T10. store 계층 — DataStore(WAL, upsert, 체크포인트), export_csv. 테스트 6건 통과
- [x] T9. win 계층 — **완료.** WindowSession(HWND 확정·권한 점검·스캔 창 설정/복원), WgcCapture(z-raise 바인딩 + 첫 프레임 크기 검증), PostMessageInput(클릭·휠·문자). CLI `windows`/`probe` 점검 명령과 `run_elevated.ps1` 러너 포함. 단위 테스트 14건 + 실기 probe 통과
- [x] T9b. 부가 도구 — `tools/set-client-quadrant.ps1` (독립 실행형 창 크기 조절: 사분면/지정 크기/전체 일괄/복원). 요구사항 산출물은 아니며 수동 운용 편의용
- [x] T11. vision 계층 — **완료.** GridMapper(평행사변형 격자·하이라이트 앵커·가시 셀 열거), TileClassifier(점령색 판별 + 템플릿 매칭 + 지형 휴리스틱 + 미상 보수 처리), DigitReader(글리프 판독), 템플릿 자산(`assets/templates/`), CLI `classify` 점검 명령. 단위·회귀 테스트 20건 추가(총 40건). 상세는 아래 "작업 결과 — T11"
- [ ] T12. nav 계층 — Navigator(지도 진입·좌표 점프·안정화·줌 맞춤·맵 크기 감지), ScanPlanner(뱀형 순회·오클루전 겹침)
- [ ] T13. controller/cli — ScanController + DetailScan(A2), Watchdog, 진행률·재개. A1/B/C는 스텁
- [ ] T14. 검증 — AC-01/02/03/05/06/07 수행·기록, 방문당 소요 실측 → NFR-02 확정
- [ ] T15. 통합·자체 리뷰·최종 보고, README 갱신

### 작업 결과 — T11 (완료, 2026-08-02)

- 산출물: `src/mapscan/vision/` (grid.py, classifier.py, digits.py), `assets/templates/` (tiles/wood.png, digits/ 글리프 + README에 출처 기록), CLI `classify`, 테스트 3파일 20건
- 완료 조건 실증: `mapscan classify --image snap_tr_base.png --anchor 1020 620 --anchor-image snap_click_R.png` → 가시 타일 200개 분류·CSV 산출(1.1초). 지상 진실 5개 좌표 스팟 체크 전부 일치

**구현 중 실측으로 확정된 사실 (T12 이후 반영 필수):**

| # | 사실 | 영향 |
|---|---|---|
| 8 | 타일 격자는 2:1 등각 마름모가 아니라 **일반 평행사변형 격자**. 스캔 창 실측 기저 `E_MX=(99.5,49.0)`(+mx=우하), `E_MY=(−55.5,45.0)`(+my=좌하). 계획서의 `a≈82.4, b≈a/2` 공식은 폐기 | GridMapper는 일반 기저로 구현(설계 §2 책임은 불변 — 경미 변경). 기저는 창·줌별로 달라지므로 T12에서 2회 점프 자기 캘리브레이션 권장 |
| 9 | **선택 하이라이트(크림색 링, HSV S<100·V>195) = 타일 경계와 정확히 일치**(인셋 없음). 앵커에서 1900px 거리의 도시 타일 테두리와도 수 px 정합 | 앵커 보정 신뢰 가능. `find_selection_highlight` 구현 완료 |
| 10 | **점령된 자원 타일은 스프라이트가 생산 시설(밭·목장·채석 시설 등)로 바뀐다** — 중립형(나무 군락 등)과 완전히 다름 | 템플릿을 중립형·점령형 2벌 수집해야 함(T14). 확보 전에는 점령 타일 종류=미상 |
| 11 | 점령 테두리 색 실측(edge-band 분율): 빨강(적군) 2~3% vs 비점령 0%, 파랑 계열 7~11% vs 0%. 단 **테두리 인셋이 스프라이트마다 달라(0.36~0.46)** 내측 밴드(0.30~0.42)로는 일부 점령 타일(빈 밭 등)을 놓침 | 알려진 한계로 기록. T14 표본으로 밴드·임계 재조정 |
| 12 | 절벽(특수 지형) 클릭 좌표는 지형 고도 시차로 화면상 격자보다 1타일 어긋날 수 있음(클릭L 실측). 팝업 좌표 폰트는 창 크기와 무관하게 동일하나 렌더링별 AA 차이로 글리프 교차 매칭 약함 → 소스별 변형 템플릿 | DigitReader는 변형 최대 점수 방식. 좌표 입력란 폰트는 S-3(T12)에서 수집 |
| 13 | 내땅(초록) 테두리 표본 미확보 — 잔디(H35~85, S중앙값~100)와 혼동 위험이 있어 고채도·고명도 잠정 임계. 동맹/우호 파랑 분리(V 170)도 잠정 | T14 점령상태 5종 표본 대조(AC-02)에서 확정 |
| 14 | 산(절벽)은 상부가 잔디라 색 구성만으로 판별 불가, 모래 평지는 지상 진실 미확인 → 모두 **미상으로 보수 처리** | 오분류보다 미상이 안전(NFR-04). T14에서 실기 클릭 표본으로 휴리스틱 확정 |

- v1 분류 능력: 목재(중립형)·공터·강(잠정)은 종류 판별, 점령상태는 빨강/파랑 계열 검출. 그 외 미상 + 신뢰도. 템플릿 잔여 목록은 `assets/templates/README.md`
- 성능: 프레임당(가시 200타일) 분류 약 1.1초 — 방문당 예산(2.5~4초) 내

## 검증

| 대상 | 방법 | 결과 | 증거 |
|---|---|---|---|
| S-1a 가림 캡처 | 오버레이로 창 전체 가림 + WGC 프레임 검사 | **성공** | `spikes/s1_background_io/evidence/` |
| S-1b 백그라운드 입력 | 관리자 권한 + 가림 상태 PostMessage 클릭 → 팝업 등장 | **성공** | before2.png / after2.png / screen_during_click.png |
| S-2 자원 식별 | 디테일·전략 뷰 클릭 판독 대조 | **P-01 실패**(전략 뷰 중립 미표시), 디테일 뷰는 가능 | `spikes/s2_zoom_grid/findings.md` |
| S-2c 종횡비 효과 | 3개 창 구성에서 클릭 좌표 폭 측정 | **가시 타일 85 / 89 / 246** | work3/snap_click_L,R.png |
| T10 store 계층 | `python -m unittest discover -s tests` (6 tests) | **전부 통과** | "Ran 6 tests ... OK" |
| T9 win 계층 (단위) | `python -m unittest discover -s tests` (20 tests: 사분면 계산, 권한 판정, 창 설정·복원 6경로, 창 확정 3경우) | **전부 통과** | "Ran 20 tests ... OK" |
| T9 win 계층 (실기) | 관리자 권한 `mapscan.cli probe --hwnd 0x503dc --click 700 350` | **통과** — 스캔 창 2544x657(종횡비 3.87) 설정, 캡처 바인딩 검증 2546x689, 클릭 후 변경 픽셀 4,695,626개(반응 확인), 창 배치 1244x730 복원 | `output/mapscan_run.log`, `output/probe.png`, `output/probe_after.png` |
| AC-07 오류 경로 복원 | 1차 실행에서 예외(UnicodeEncodeError) 발생 시에도 복원 동작 확인 | **통과**(의도치 않은 실증) | 1차 로그의 "창 배치 복원: 1244x730" |
| T9b 창 도구 | `-All`, `-Width/-Height`, `-Restore` 실기 + JSON 왕복 단위 5케이스 | **전부 통과** — `-All` 두 창을 (0,0)·(2560,0) 분배, `-Width 1600 -Height 900` 위치 유지 리사이즈, `-Restore` 복원·상태파일 삭제 | 커밋 `6fa804c` |
| T11 GridMapper (단위) | `tests/test_vision_grid.py` 11건 — 변환 왕복, 이웃 스텝, 셀 열거·제외, 실캡처 하이라이트 검출(중심 ±5px)·클릭→타일 매핑 | **전부 통과** | "Ran 40 tests ... OK" |
| T11 TileClassifier (회귀) | `tests/test_vision_classifier.py` 6건 — 고정 캡처(snap_tr_base, 같은 뷰 snap_click_R 앵커)에서 목재/공터/적군 2좌표/도시 파랑 2좌표/절벽·모래 미상/전체 셀 형식 | **전부 통과** | 동일 |
| T11 DigitReader | `tests/test_vision_digits.py` 3건 — 팝업 좌표 스트립 4소스 "(1020,620)" 등 완전 판독, read_coords 파싱, 빈 스트립 | **전부 통과** | 동일 |
| T11 완료 조건 | `mapscan.cli classify` — snap_tr_base 1장 → 가시 200타일 분류 CSV(미상 109·ally 61·enemy 25·공터 4·목재 1), 지상 진실 5좌표 대조 | **통과** (1.1초/프레임) | `output/classify_tr_base.csv` |

## 구현 중 확정된 환경 제약 (재발 방지)

| 항목 | 내용 |
|---|---|
| PowerShell 스크립트 인코딩 | Windows PowerShell 5.1은 BOM 없는 `.ps1`을 ANSI(cp949)로 읽어 한글 리터럴이 깨지고 파싱이 실패한다. **한글이 들어간 `.ps1`은 UTF-8 BOM으로 저장** |
| Python 콘솔 출력 | 콘솔 기본 코드페이지(cp949)로 출력할 수 없는 문자가 있어 `cli.main()`에서 stdout/stderr을 UTF-8로 재설정한다 |
| PowerShell 배열 반환 | 함수가 단일 원소 배열을 반환하면 스칼라로 풀려 `+=`가 `op_Addition` 예외를 낸다. `return , $array` 로 고정 |
| PowerShell 파라미터명 | `-Args`는 자동 변수 `$Args`와 충돌해 값이 비워진다 |
| git 커밋 메시지 | 본문에 `$`·백틱이 있으면 PowerShell 히어독이 깨진다. 긴 메시지는 `git commit -F <파일>` 사용 |

## 완료

(최종 보고 시 작성 — 현재 진행 중)
