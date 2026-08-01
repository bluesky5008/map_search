# 구현 계획 — 월드맵 토지정보 추출기 v1

- 작업 ID: 20260801-worldmap-land-scan
- 기준선: 요구사항 v1 / 설계 v1 (2026-08-01 승인)
- 이 문서는 wf-implement의 작업 기록이며 진행 상태를 여기서 갱신한다.

## 기준선

- 관련 요구사항: [requirements.md](requirements.md) v1 (FR-01~03, FR-05, FR-07~11, NFR-01~06)
- 관련 설계: [design.md](design.md) v1
- 관련 ADR: ADR-001(스택), ADR-002(캡처·입력, S-1 게이트), ADR-003(저장), ADR-004(모드 구조)

## 현재 상태 확인 (2026-08-01)

- 게임 클라이언트 실행 중: `S3Client` PID 9876, 26412 — 창 제목 "삼국지-전략판 113.554" 2개(다중 실행 가능성, 스파이크에서 창 선택 확인)
- Python 3.13.1 설치됨 (ADR-001은 3.12 기준 — 상위 버전 사용, 경미한 차이로 기록만 남김)
- git: main 클린, 원격 push 완료 상태

## 계획

### 1부 — 기술 검증 스파이크 (설계 §9)

- [ ] T1. 개발 환경 준비: `.venv` 생성, pillow 설치(캡처 저장용). opencv-python·numpy는 S-2부터.
- [x] T2. S-1a 백그라운드 캡처 검증 — **완료(성공).** PrintWindow는 검은 프레임(실패), WGC는 가림 상태에서도 유효 프레임 확인. 추가 발견: 동일 제목 창 2개 환경에서 제목 매칭은 z순서 의존으로 불가 → 제품은 HWND 기반 캡처 필수(T9에 반영). 증거: `spikes/s1_background_io/findings.md`
- [x] T3. S-1b 백그라운드 입력 검증 — **완료(성공).** 관리자 권한 헬퍼(UAC 승인)로 가림 상태에서 PostMessage 클릭 → 타일 팝업 등장 확인. 도구 관리자 권한 실행 필요(제약 확정).
- [x] T4. S-1 판정 기록 — **완료.** findings.md 최종 판정 작성, ADR-002 유지 확정(전면 폴백 불필요).
- [ ] T5. S-2 광역 줌 자원 종류 식별 + 그리드 캘리브레이션(P-01, P-05): 줌 제어(휠) 가능 여부, 줌별 타일 픽셀 치수 실측, 자원 스프라이트 구분 가능성 판정.
- [ ] T6. S-3 좌표 입력란 숫자 판독(P-03): 9999 입력→클램프 값 글리프 판독 검증.
- [ ] T7. S-4 팝업 오클루전 커버(P-06): 점프 직후 팝업 고정 영역 실측, 겹침 마진 산정.

### 2부 — 제품 구현 (스파이크 결과 반영 후 상세화)

- [x] T8. 프로젝트 골격 — **완료.** `src/mapscan/` 패키지, `pyproject.toml`, `tests/`. (설정 로더는 T13 CLI와 함께)
- [ ] T9. win 계층: WindowSession(창 탐색·검증·프로브·**권한 검사**·**창 크기 재설정**), ICapture(**HWND 바인딩 필수**) 2구현, IInput 2구현
- [x] T10. store 계층 — **완료.** DataStore(WAL, (scan_id,x,y) PK upsert, 체크포인트, 재개 조회), export_csv(UTF-8 BOM, 분할). 단위 테스트 6건 통과.
- [ ] T11. vision 계층: GridMapper, DigitReader, TileClassifier + 템플릿 자산 추출 — 스크린샷 회귀 테스트
- [ ] T12. nav 계층: Navigator(지도 진입·좌표 점프·안정화 대기·맵 크기 감지), ScanPlanner(뱀형 순회·오클루전 겹침) — 단위 테스트(Planner 커버리지)
- [ ] T13. controller/cli: ScanController + FullSpriteScan(MODE-A), Watchdog, 진행률·재개
- [ ] T14. 검증: AC-01/02/03/05/06 절차 수행·기록, NFR-02 처리량 실측
- [ ] T15. 통합·자체 리뷰·최종 보고, README 실행 방법 확정

## 작업 상세 (1부)

### T2~T4. 스파이크 S-1 — 백그라운드 캡처·입력

- 목표: NFR-06(백그라운드 동작) 실현 가능성 판정, ADR-002 확정
- 관련 요구사항: NFR-06, AC-06 / 관련 설계: §4.1 프로브, ADR-002
- 변경 대상: `spikes/s1_background_io/` (제품 코드에 미포함)
- 위험: 게임이 raw input 전용이면 PostMessage 무반응 → 전면 폴백(합의됨). 클릭 지점은 맵 중앙(타일 선택만 발생, 게임 상태 변경 없음)으로 한정하고, 클릭 전 프레임을 육안 확인한다.
- 검증 방법: 가림 상태 캡처 PNG 육안·통계 확인, 클릭 전후 diff에서 팝업 영역 변화 확인
- 완료 조건: findings.md에 성공/실패 판정과 증거(캡처 파일) 기록

## 검증

| 대상 | 방법 | 결과 | 증거 |
|---|---|---|---|
| S-1a 가림 캡처 (NFR-06 절반) | 마젠타 오버레이로 창 전체 가림 + WGC 프레임 검사, 실사용(브라우저 겹침) 조건 재확인 | **성공** | `spikes/s1_background_io/evidence/` (screen_during_overlay.png=마젠타, cap_wgc_occluded.png=정상 게임 프레임·시계 갱신) |
| S-1b 백그라운드 입력 | PostMessage 반환값·GetLastError 검사 | **차단** — 게임 elevated + 도구 비관리자 → error 5. UAC 승인 거부로 보류 | findings.md |
| T10 store 계층 | `python -m unittest discover -s tests` (6 tests) | **전부 통과** (upsert 멱등·last-wins, 체크포인트/재개 조회, 정렬 반환, CSV BOM·분할·오류) | 테스트 출력 "Ran 6 tests ... OK" |

## 완료

(최종 보고 시 작성)
