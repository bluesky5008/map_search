# 구현 계획 — 월드맵 토지정보 추출기 v1 (MODE-A2)

- 작업 ID: 20260801-worldmap-land-scan
- 기준선: **요구사항 v2 / 설계 v2 (2026-08-02 승인, DCR-001)**
- 이 문서는 wf-implement의 작업 기록이며 진행 상태를 여기서 갱신한다.

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
- [ ] T11. vision 계층 — GridMapper(등각 변환·앵커 보정), TileClassifier(스프라이트·점령색), DigitReader + 템플릿 자산
- [ ] T12. nav 계층 — Navigator(지도 진입·좌표 점프·안정화·줌 맞춤·맵 크기 감지), ScanPlanner(뱀형 순회·오클루전 겹침)
- [ ] T13. controller/cli — ScanController + DetailScan(A2), Watchdog, 진행률·재개. A1/B/C는 스텁
- [ ] T14. 검증 — AC-01/02/03/05/06/07 수행·기록, 방문당 소요 실측 → NFR-02 확정
- [ ] T15. 통합·자체 리뷰·최종 보고, README 갱신

### 작업 상세 — T9 (다음 작업)

- 목표: 대상 창을 확정하고, 스캔 창 크기로 설정하며, 가림 상태 캡처·입력을 제공한다
- 관련 요구사항: FR-12, NFR-01, NFR-06 / 설계: §2, §4.1, ADR-002, ADR-005
- 변경 대상: `src/mapscan/win/` (session.py, capture.py, input.py)
- 위험: WGC HWND 바인딩 — `windows-capture`는 제목 매칭만 제공하므로 z-raise 후 첫 프레임 검증으로 보완하거나 winsdk interop 사용
- 검증: 창 설정·복원 3경로 테스트, 가림 상태 캡처·클릭 E2E
- 완료 조건: 관리자 권한 실행 시 지정 HWND의 프레임을 가림 상태에서 획득하고 클릭이 전달됨

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

## 완료

(최종 보고 시 작성)
