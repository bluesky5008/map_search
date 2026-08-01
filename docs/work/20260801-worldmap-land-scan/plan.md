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
| 구현 완료 | T8 골격, T10 store 계층, T9 win 계층, 부가 도구(창 크기 조절 스크립트) |
| **다음 작업** | **T11 vision 계층** (GridMapper → TileClassifier → DigitReader) |
| 테스트 | `python -m unittest discover -s tests` — 20건 전부 통과 |
| 커밋 | main 브랜치, origin 푸시 완료 (최신 `6fa804c`) |

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
- [ ] T11. vision 계층 — GridMapper(등각 변환·앵커 보정), TileClassifier(스프라이트·점령색), DigitReader + 템플릿 자산
- [ ] T12. nav 계층 — Navigator(지도 진입·좌표 점프·안정화·줌 맞춤·맵 크기 감지), ScanPlanner(뱀형 순회·오클루전 겹침)
- [ ] T13. controller/cli — ScanController + DetailScan(A2), Watchdog, 진행률·재개. A1/B/C는 스텁
- [ ] T14. 검증 — AC-01/02/03/05/06/07 수행·기록, 방문당 소요 실측 → NFR-02 확정
- [ ] T15. 통합·자체 리뷰·최종 보고, README 갱신

### 작업 상세 — T11 (다음 작업)

- 목표: 캡처 프레임에서 타일 격자를 잡고 각 타일을 분류한다
- 관련 요구사항: FR-03b, FR-05, FR-07, FR-08 / 설계: §2 vision, §4.3
- 변경 대상: `src/mapscan/vision/` (grid.py, classifier.py, digits.py), `assets/templates/`
- 착수 순서
  1. **GridMapper** — 등각 변환 `screen_x=(mx−my)·a`, `screen_y=(mx+my)·b`. 스파이크 확정 사실 #7의 클릭↔좌표 2점으로 `a≈82.4px`(스캔 창 2544x657)를 얻었고 `b≈a/2` 가정. 앵커는 좌표 점프 후 선택 하이라이트 타일. **순수 계산이라 게임 없이 단위 테스트 가능 — 여기부터 시작**
  2. **TileClassifier** — 자원 스프라이트 템플릿 매칭 + 점령 테두리 색상 판별. 템플릿은 `image/` 참고 이미지와 스파이크 캡처(`spikes/s2_zoom_grid/work*/`)에서 추출
  3. **DigitReader** — 좌표 입력란 숫자 글리프 판독 (S-3 확인 겸용)
- 위험: 스캔 창(타일 스텝 82px)은 참고 이미지보다 타일이 작아 템플릿을 **실제 스캔 창 크기에서 다시 수집**해야 한다(R-08). 자원 종류 중 철광·식량·구리 스프라이트 표본 미확보 — 실기 수집 필요
- 검증: 스크린샷 회귀 테스트(고정 캡처 → 기대 분류), 실기 표본 수동 대조(AC-02)
- 완료 조건: 스캔 창 캡처 1장에서 가시 타일의 대분류·자원 종류·점령상태를 신뢰도와 함께 산출

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
