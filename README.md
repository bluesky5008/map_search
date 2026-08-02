# map_search — 월드맵 토지정보 추출기

게임 **"삼국지-전략판"** PC 클라이언트의 월드맵 전 좌표를 자동 순회하며 좌표별 토지 정보를 추출해 파일로 저장하는 stand-alone Windows 도구입니다. 게임이 좌표별 토지 데이터를 외부로 제공하지 않으므로, 화면 캡처·이미지 인식·UI 자동 조작으로 정보를 수집합니다.

> **상태 (2026-08-02):** 요구사항 **v3** / 설계 **v4** 승인([DCR-004](docs/work/20260801-worldmap-land-scan/changes/DCR-004-reanchor-coordinate-integrity.md) — 좌표 무결성: 주기 재앵커 + 지연 기록). 전 계층 구현 완료(`mapscan scan` 동작), 검증 T14 대부분 완료 — 지정 영역 스캔(18행 14,972타일)·AC-01/03/06 통과, 처리율 개선 후 완주 행 실측 **21.3~21.9타일/s**.
> **남은 것:** 전체 스캔 1회 완주(예상 38~52시간, 착수는 사용자 지시 대기) → NFR-02(48h) 최종 판정 → AC-02 최종 재대조 → 최종 보고(T15).
> 진행 현황과 재개 지점은 [docs/work/20260801-worldmap-land-scan/plan.md](docs/work/20260801-worldmap-land-scan/plan.md)에서 관리합니다.

## 수집하는 정보

좌표(0,0 ~ 자동 감지된 맵 최대치, 최대 <2000×2000)별로 다음을 수집합니다. **순수 토지 정보만 수집하며** 도적 정보, 점령자 이름 등은 수집하지 않습니다.

| 항목 | 값 | 비고 |
|---|---|---|
| 토지 대분류 | 자원토지 / 1칸건물 / 2칸이상건물 / 이동불가지역 | |
| 세부 종류 | 공터, 목재, 철광, 석재, 식량, 구리 광산 / 망루, 울타리, 막사, 조폐창, 공방, 장군 막사, 창고, 악부, 요새(+미상) / 주성, 분성, 성지, 부두, 군진, 공정영 / 강, 산 | |
| 자원 레벨 | 목재·철광·석재·식량 Lv1~10, 구리 Lv6~10 | 클릭 모드(MODE-B/C, 후속)에서만 |
| 점령상태 | 내땅·동맹원땅·우호동맹땅·적군땅·중립 | 타일 테두리 색상 판별 |
| 2칸이상 건물 중심좌표 | 건물 점유 좌표들을 하나로 묶은 대표 좌표 | 화면인식 모드에서는 추정값 표기 |
| 수집 시각 | 좌표별 ISO8601 | 스캔 결과는 시점 스냅샷 |

## 스캔 모드

게임에는 두 가지 렌더링 모드가 있고 보여주는 정보가 다릅니다. **전략 뷰**는 중립 타일(자원·공터)을 아예 렌더링하지 않고, **디테일 뷰**만 자원 종류를 표시합니다(스파이크 S-2 실측). 이에 따라 화면인식 스캔을 A1/A2로 나눴습니다.

| 모드 | 방식 | 수집 정보 | 전체 맵 예상 소요 | 구현 |
|---|---|---|---|---|
| MODE-A1 | 전략 줌 스캔 | 점령상태·소유 건물·지형 (중립 타일은 미상) | 약 2~4시간(미실측) | 후속 |
| **MODE-A2** | **디테일 줌 스캔** | **A1 전체 + 자원 종류·공터·1칸건물·2칸이상건물** | **38~52시간 (완주 행 21.3~21.9타일/s 실측 외삽)** | **v1** |
| MODE-B | 하이브리드 (A2 + 선별 클릭) | A2 + 선별 대상의 레벨 | — | 후속 |
| MODE-C | 영역 한정 전수 클릭 | 전 항목 (레벨 포함) | — | 후속 |

전 좌표 클릭 방식은 맵 전체 기준 주 단위가 걸려 지원하지 않습니다. 이것이 모드를 분리한 이유입니다.

당초 좌표 점프 순회는 실측 약 150시간이 걸렸습니다([DCR-002](docs/work/20260801-worldmap-land-scan/changes/DCR-002-scan-throughput.md)). 이동을 **드래그 팬 행 스캔**으로 바꾸고([DCR-003](docs/work/20260801-worldmap-land-scan/changes/DCR-003-nfr02-final-pan-design.md) — NFR-02를 48시간으로 확정), 좌표 드리프트는 **K=4팬 주기 클릭 재앵커 + 지연 기록**으로 지웁니다([DCR-004](docs/work/20260801-worldmap-land-scan/changes/DCR-004-reanchor-coordinate-integrity.md)). 이후 T14에서 재앵커 판독 보강과 캡처 세션 스레딩 결함 수정(plan.md 사실 45~48)으로 완주 행 21.3~21.9타일/s를 실측했습니다.

## 창 크기가 스캔 속도를 좌우합니다

게임은 월드 렌더링 배율을 **창 높이**에 맞춥니다. 따라서 한 화면에 보이는 타일 수는 창 크기가 아니라 **종횡비(가로/세로)에 비례**합니다. 실측값입니다.

| 클라이언트 크기 | 종횡비 | 가시 타일 수 |
|---|---|---|
| 1278×719 (기본) | 1.78 | 85 |
| 2544×1401 (비율 유지 확대) | 1.82 | 89 |
| **2544×657 (사분면 스냅)** | **3.87** | **246** |

넓고 낮은 창으로 두면 한 화면의 가시 타일이 약 2.9배가 됩니다. 도구는 스캔 시작 시 창을 자동으로 이 크기로 설정하고 종료 시 원래대로 복원합니다(강제 종료 시에도 사이드카 `output/winstate_*.json`으로 다음 실행이 복원).

## 동작 방식

```text
행 시작: 좌표 점프(지도 모드 확인 → 좌표 입력 → 이동) → 디테일 뷰 검증
행 내부: 드래그 팬 반복 → 전단 이동장(dx=a+b·y) 실측 추적 → 대역 내 신규 셀 분류
좌표 무결성: K=4팬마다 타일 클릭 재앵커(팝업 좌표 판독 + 새니티 창)
  → 사이클 버퍼를 드리프트 팬별 보간 보정 후 SQLite 기록(미보정 꼬리는 폐기)
행 종료 → 다음 행 … → 미커버 좌표 점프 보충 방문 → 완료 시 CSV 내보내기
```

- **백그라운드 동작:** 게임 창이 다른 창에 가려져 있어도 스캔이 진행됩니다(Windows Graphics Capture + PostMessage, 실기 검증 완료). 창 **최소화**는 지원하지 않습니다.
- **관리자 권한 필요:** 게임이 관리자 권한으로 실행되면 UIPI가 비관리자 프로세스의 입력·창 조작을 차단합니다. 도구도 관리자 권한으로 실행해야 합니다.
- **맵 크기 자동 감지:** 좌표 입력란에 큰 값을 넣으면 실제 최대 좌표로 강제 변경되는 게임 동작을 이용합니다. 값을 글자로 읽는 대신 **렌더링 이미지를 비교해 이진 탐색**하므로 폰트가 바뀌어도 동작합니다([ADR-006](docs/work/20260801-worldmap-land-scan/decisions/ADR-006-map-size-detection.md)). 실측 대상 서버는 **1619×1619**.
- **오조작 방지:** 지도 UI를 클릭하기 전 매번 화면 상태를 확인하고, 기대한 화면이 아니면 조작하지 않고 중단합니다. 선택 팝업에는 점령·행군처럼 되돌릴 수 없는 버튼이 있어 필요한 장치입니다.
- **중단/재개:** 수집은 SQLite에 좌표 단위로 멱등 기록되며, 강제 종료 후 재시작하면 체크포인트에서 이어서 스캔합니다.
- **이상 복구:** 예기치 못한 게임 팝업·화면 전환 실패를 감지하면 복구를 시도하고, 불가하면 체크포인트를 남기고 안전하게 정지합니다.
- **보수적 분류:** 인식 신뢰도가 낮은 타일은 오분류 대신 `미상`으로 기록하고 증거 이미지를 남깁니다(분류 정확도 목표 99%).

### 인식 현황 (T14 시점)

- **자원 템플릿:** 목재(중립형), 철광(중립 Lv.1 `iron_neu` + 점령형 `iron_occ`), 석재(중립 Lv.3/Lv.5), 식량(점령형 밭 — 중립형 밭에도 정당 매칭). 구리는 표본 미확보로 미상 처리.
- **건물:** 주성 성채(키프) 템플릿 검출 + 지면 중심 반경 멤버 병합(FR-07, `center_x/y` 추정 표기). 다른 스킨·소형 도시는 보수 미상.
- **점령상태:** 타일 경계 색 판별(적 빨강·동맹/우호 파랑·내땅 초록). 파랑·초록은 **마주보는 변 쌍 규칙**으로 강·인접 스프라이트 번짐 오탐을 배제. 내땅·우호는 정탐 표본 미확보로 잠정 임계.
- **팝업 좌표 판독:** 글리프 변형 누적 + 슬라이드 최빈값 투표 + 세그먼테이션 복구 패스. 판독 실패 시 증거를 `output/evidence/`에 자동 축적해 사후 보강.
- 신뢰도 미달 타일은 여전히 `미상` 보수 기록(오분류보다 미상이 안전 — 확보 표본 기준 확정 오분류 0)

## 산출물

- **SQLite** (`*.db`) — 수집 원장. `scans`(스캔 메타·체크포인트), `tiles`(좌표별 레코드, PK=(scan_id,x,y)).
- **CSV** (`scan_<id>_<날짜>.csv`, UTF-8 BOM) — 완료 시 내보내기. 100만 행 단위 분할 옵션(엑셀 호환).

```text
x,y,category,kind,level,occupancy,center_x,center_y,center_estimated,confidence,status,captured_at
```

## 요구 환경

- Windows PC (Windows 11 기준), 디스플레이 배율 100%
- Python 3.12 이상 (개발·실행), 의존성: pillow, numpy, opencv-python, windows-capture
- "삼국지-전략판" PC 클라이언트가 실행·로그인된 상태
- 게임이 관리자 권한으로 실행 중이면 도구도 관리자 권한 필요
- 네트워크 통신 없음, 게임 메모리 접근·패킷 분석 없음 — 화면에 표시되는 정보만 읽습니다

## 사용법

### 창 크기 조절 도구 (독립 실행, 사용 가능)

스캔과 무관하게 클라이언트 창 크기를 조절하는 단독 스크립트입니다. 드래그로는 종횡비가 고정되지만 이 스크립트는 `SetWindowPos`로 직접 설정해 그 제약을 우회합니다.

```powershell
# 실행 중인 클라이언트 목록
.\tools\set-client-quadrant.ps1 -List

# 대화식 선택 → 화면의 1/4 크기(우상단)
.\tools\set-client-quadrant.ps1

# 모든 클라이언트를 1/4 크기로, 사분면에 나누어 배치
.\tools\set-client-quadrant.ps1 -All

# 크기를 직접 지정 (위치는 현재 자리 유지)
.\tools\set-client-quadrant.ps1 -Index 2 -Width 2560 -Height 696

# 원래 크기·위치로 복원
.\tools\set-client-quadrant.ps1 -Restore
```

옵션: `-List` `-Index N` `-All` `-Quadrant TL|TR|BL|BR` `-Width` `-Height` `-Restore` `-TitleMatch`.
관리자 권한이 없으면 자동으로 UAC를 띄우며, **결과는 새로 열리는 관리자 창에 표시**됩니다. 변경 전 배치는 `%LOCALAPPDATA%\mapscan\saved_window_rects.json`에 저장됩니다.

### mapscan

```powershell
# 개발 환경 준비 (한 번만) — 테스트·CLI가 mapscan 패키지를 찾게 합니다
.venv\Scripts\python -m pip install -e . --no-deps

# 대상 창 목록. 같은 제목 창이 여러 개면 --crops로 계정명을 저장해 구분합니다
.venv\Scripts\python -m mapscan.cli windows --crops output

# 전체 스캔 (관리자 권한 필요, 수십 시간 — 재실행하면 체크포인트에서 재개)
.venv\Scripts\python -m mapscan.cli scan --hwnd 0x60042 --db output\full.db --csv output\full_csv

# 부분 실행·점검 (행 150부터 1행, 팬 12회 한도)
.venv\Scripts\python -m mapscan.cli scan --hwnd 0x60042 --start-row 150 --max-rows 1 --max-pans 12

# 스캔 창 설정 → 캡처 → 클릭 → 복원 점검 (관리자 권한 필요)
.\run_elevated.ps1 -Cmd "probe --hwnd 0x503dc --out output\probe.png --click 700 350"

# 캡처 1장의 가시 타일을 분류해 CSV로 (vision 계층 점검)
.venv\Scripts\python -m mapscan.cli classify `
  --image spikes\s2_zoom_grid\work3\snap_tr_base.png `
  --anchor 1020 620 --anchor-image spikes\s2_zoom_grid\work3\snap_click_R.png `
  --csv output\classify.csv
```

`--anchor`는 프레임 안에서 좌표를 아는 타일(선택 하이라이트가 있는 타일)의 맵 좌표입니다. 스캔 중에는 `Navigator.jump`이 이 앵커를 자동으로 확정합니다.

### 실기 검증 (스파이크)

```powershell
# 지도 모드 진입 → 맵 크기 자동 감지 → 좌표 점프 → 분류까지 (UAC 1회)
powershell -ExecutionPolicy Bypass -File spikes\s3_nav_ui\run_live.ps1 -Hwnd 0x60042
```

### 테스트

```powershell
.venv\Scripts\python -m unittest discover -s tests   # 현재 100건
```

## 프로젝트 구조

```text
map_search/
├── README.md
├── 요구사항.md                  # 원본 요구사항 (사용자 작성)
├── image/                       # 게임 화면 참고 이미지 (분류 근거·템플릿 원천)
├── docs/work/20260801-worldmap-land-scan/
│   ├── plan.md                  # 구현 진행 상황·재개 지점  ← 세션 시작 시 먼저 읽기
│   ├── requirements.md          # 요구사항 명세 (기준선 v3)
│   ├── design.md                # SW 설계 (기준선 v4)
│   ├── design-change-log.md     # 설계 변경 이력 (DCR + 경미 변경)
│   ├── changes/DCR-001~004      # 설계 변경 요청 (전부 승인·반영)
│   └── decisions/ADR-001~006    # 설계 결정 기록
├── spikes/                      # 기술 검증 스파이크 + 판정 기록 (제품 코드 아님)
│   ├── s1_background_io/        # 백그라운드 캡처·입력 검증
│   ├── s2_zoom_grid/            # 줌·자원 식별·창 종횡비 측정
│   ├── s3_nav_ui/               # 지도 모드 UI·맵 크기 감지·팝업 오클루전
│   ├── s5_drag_pan/             # 드래그 팬 실현 가능성 (3게이트 통과)
│   ├── s6_remeasure/            # DCR-002 안(d) 처리율 재측정 (방문 99회)
│   └── t14_pan_tuning/          # T14 검증 도구·표본·증거 (K 튜닝, 템플릿 수집 등)
├── assets/templates/            # 스프라이트·글리프·UI 마커 (출처는 README.md)
├── src/mapscan/
│   ├── cli.py                   # ✅ 진입점 (windows / probe / classify / scan)
│   ├── win/                     # ✅ WindowSession, WgcCapture, PostMessageInput
│   ├── store/                   # ✅ DataStore(SQLite), CSV 내보내기
│   ├── vision/                  # ✅ GridMapper, TileClassifier, DigitReader
│   ├── nav/                     # ✅ Navigator, ScanPlanner, PanTracker, ui.py(캘리브레이션)
│   ├── controller.py            # ✅ ScanController, DetailScan(A2, 재앵커·지연 기록)
│   └── watchdog.py              # ✅ 프레임 이상 감시
├── tools/set-client-quadrant.ps1  # ✅ 창 크기 조절 (독립 실행)
├── tools/agent_shell.ps1        # 상주 관리자 실행기 (UAC 1회로 명령 파일 순차 실행)
├── run_elevated.ps1             # 관리자 권한 실행 러너
└── tests/                       # 단위·회귀 테스트 (현재 100건)
```

## 문서

| 문서 | 내용 |
|---|---|
| [plan.md](docs/work/20260801-worldmap-land-scan/plan.md) | **구현 진행 상황·다음 작업·검증 결과 — 작업 재개 지점** |
| [requirements.md](docs/work/20260801-worldmap-land-scan/requirements.md) | 요구사항 명세 v3 — FR/NFR, 인수 조건, 결정 기록 |
| [design.md](docs/work/20260801-worldmap-land-scan/design.md) | SW 설계 v4 — 컴포넌트, DB 스키마, 행 기반 팬 스캔·재앵커, 추적표, 위험 |
| [design-change-log.md](docs/work/20260801-worldmap-land-scan/design-change-log.md) | 설계 변경 이력 — DCR과 "경미한 변경"(구현 중 수단이 바뀐 항목) |
| [DCR-002](docs/work/20260801-worldmap-land-scan/changes/DCR-002-scan-throughput.md) | 스캔 소요 초과 대응 — 안 (d) 최적화 후 재측정 채택(반영 완료) |
| [DCR-003](docs/work/20260801-worldmap-land-scan/changes/DCR-003-nfr02-final-pan-design.md) | NFR-02 48시간 확정 + 팬 이동 설계 (승인) |
| [DCR-004](docs/work/20260801-worldmap-land-scan/changes/DCR-004-reanchor-coordinate-integrity.md) | 좌표 무결성 — 주기 재앵커 + 지연 기록 (승인) |
| [ADR-001](docs/work/20260801-worldmap-land-scan/decisions/ADR-001-tech-stack.md) | 구현 스택: Python + OpenCV |
| [ADR-002](docs/work/20260801-worldmap-land-scan/decisions/ADR-002-capture-input.md) | 캡처·입력: WGC + PostMessage (HWND 바인딩·입력 제약 실측 포함) |
| [ADR-003](docs/work/20260801-worldmap-land-scan/decisions/ADR-003-storage.md) | 저장: SQLite 원장 + CSV 내보내기 |
| [ADR-004](docs/work/20260801-worldmap-land-scan/decisions/ADR-004-scan-mode-architecture.md) | 스캔 모드 전략 패턴 구조 |
| [ADR-005](docs/work/20260801-worldmap-land-scan/decisions/ADR-005-window-aspect-ratio.md) | 창 크기·종횡비 정책 (실측 보완 포함) |
| [ADR-006](docs/work/20260801-worldmap-land-scan/decisions/ADR-006-map-size-detection.md) | 맵 크기 감지: 글리프 OCR 대신 클램프 렌더링 이미지 비교 |
| [S-1 findings](spikes/s1_background_io/findings.md) | 백그라운드 캡처·입력 검증 결과 |
| [S-2 findings](spikes/s2_zoom_grid/findings.md) | 줌·자원 식별·창 종횡비 측정 결과 |
| [S-3/S-4 findings](spikes/s3_nav_ui/findings.md) | 지도 모드 UI 좌표, 맵 크기 감지, 팝업 오클루전 판정 |
| [assets/templates/README.md](assets/templates/README.md) | 템플릿 자산의 출처와 미확보 목록 |

## 로드맵

1. **v1 (마무리 단계):** MODE-A2 디테일 줌 전체 스캔
   - ✅ 저장(SQLite+CSV), 창/캡처/입력, 인식(격자·분류·글리프), 순회(팬·재앵커·방문 계획), 컨트롤러·워치독·진행률
   - ✅ T14 검증 대부분 — 지정 영역 스캔(18행 14,972타일), AC-01/03/06 통과, 처리율 개선(21.3~21.9타일/s)
   - ⬜ 전체 스캔 1회 완주(사용자 지시 대기) → NFR-02 최종 판정 → AC-02 최종 재대조 → 최종 보고(T15)
2. **v2:** MODE-A1(전략 줌 빠른 점령 지도), MODE-B/C(레벨 정보 수집)
3. **이후:** 안드로이드 환경 프로그램 (인식 로직은 캡처·입력 인터페이스와 분리되어 재사용 대비)

## 주의사항

- 스캔 결과는 **스캔 시점의 스냅샷**입니다. 점령 상태 등은 스캔 중에도 계속 변합니다.
- 게임 클라이언트 업데이트로 UI·그래픽이 바뀌면 템플릿 재캘리브레이션이 필요할 수 있습니다. 창 크기를 바꿔도 UI 좌표를 다시 재야 합니다(`src/mapscan/nav/ui.py`).
- 화면 자동 조작 도구이므로 게임 이용약관과의 관계는 사용자 본인의 책임입니다. 본 도구는 정보 열람 목적의 조작(화면 이동)만 수행하며 점령·행군 등 게임 행위는 하지 않습니다. 그 보장을 위해 지도 UI 클릭 전 화면 상태를 검증하고, `ESC` 키는 어떤 경로에서도 쓰지 않습니다(일반 화면에서 게임 종료 확인 창을 띄우기 때문).
- 같은 제목의 클라이언트를 여러 개 실행 중이라면 대상 창을 HWND로 지정하세요. `mapscan windows --crops <디렉터리>`가 창별 계정명을 저장해 줍니다.
