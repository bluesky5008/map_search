# SW 설계 — 월드맵 토지정보 추출기

- 작업 ID: 20260801-worldmap-land-scan
- 기준선: v0.3 (초안, 미승인 — 도적 감지 기능 제외 반영)
- 대상 요구사항: [requirements.md](requirements.md) v0.3
- 작성일: 2026-08-01

## 1. 설계 개요

화면 캡처 → 타일 인식 → 저장의 파이프라인을 갖는 단일 프로세스 Windows 데스크톱 도구.

- 3개 스캔 모드(MODE-A/B/C)를 **전략 패턴**으로 수용하고, v1은 MODE-A(화면인식 전체 스캔)만 구현한다. 모드별 차이는 "어느 좌표를 방문하고, 방문 지점에서 무엇을 하는가"뿐이며 이동·캡처·인식·저장 서비스는 공유한다.
- 캡처·입력은 인터페이스로 추상화하고 **백그라운드 구현(Windows Graphics Capture + PostMessage)을 기본**, 전면 구현(BitBlt/mss + SendInput)을 폴백으로 둔다(NFR-06, ADR-002).
- 수집 데이터는 SQLite를 단일 진실 원천으로 기록하고 완료 시 CSV로 내보낸다(ADR-003).

```text
┌────────────────────────── CLI / Config ──────────────────────────┐
│  ScanController (모드 전략 선택·수명주기·체크포인트)                  │
│   ├── FullSpriteScan (MODE-A, v1)                                │
│   ├── HybridScan     (MODE-B, 후속·스텁)                          │
│   └── RegionClickScan(MODE-C, 후속·스텁)                          │
│        │ 공통 서비스                                               │
│        ├── Navigator ──── InputDriver ──┐                        │
│        ├── ScreenReader ── Capturer ────┼── WindowSession        │
│        │     ├── GridMapper             │   (창 탐색·검증·프로브)   │
│        │     ├── TileClassifier         │                        │
│        │     ├── DigitReader            │                        │
│        │     └── PopupReader(후속)       │                        │
│        ├── Watchdog (이상 화면 감지·복구)                           │
│        └── DataStore (SQLite) ── CsvExporter                     │
└──────────────────────────────────────────────────────────────────┘
```

## 2. 컴포넌트 책임

| 컴포넌트 | 책임 | 주요 의존 |
|---|---|---|
| CLI/Config | 모드·출력 경로·옵션 파싱, 설정 파일(캘리브레이션 값) 로드 | — |
| ScanController | 스캔 수명주기(시작/재개/정지), 모드 전략 실행, 체크포인트 갱신, 진행률 보고 | 모든 서비스 |
| WindowSession | 창 제목 "삼국지-전략판"으로 대상 창 탐색, 크기 1282x752 검증, 시작 시 캡처·입력 프로브(P-04) 수행 및 백그라운드/전면 모드 결정 | Win32 |
| Capturer (ICapture) | 창 이미지 획득. `WgcCapture`(백그라운드, 기본) / `BitBltCapture`(전면 폴백) | WindowSession |
| InputDriver (IInput) | 클릭·텍스트 입력·휠(줌). `PostMessageInput`(백그라운드, 기본) / `SendInput`(전면 폴백) | WindowSession |
| Navigator | 지도 모드 진입, 좌표 입력·이동 실행, 줌 레벨 설정, 이동 후 화면 안정화 대기(연속 프레임 diff), 맵 크기 감지(9999 입력→클램프 값 판독) | InputDriver, Capturer, DigitReader |
| GridMapper | 화면 픽셀 ↔ 맵 좌표 변환. 점프 후 선택 하이라이트 타일을 앵커로 그리드 원점 보정, 줌별 타일 픽셀 치수 상수 관리 | 캘리브레이션 설정 |
| TileClassifier | 타일 셀 이미지 → (대분류, 종류, 점령상태, 신뢰도). 스프라이트 템플릿 매칭 + 테두리 색상 판별. 신뢰도 미달 시 `미상` 처리 + 증거 캡처 저장 | 템플릿 자산 |
| DigitReader | 좌표 입력란·팝업 좌표 등 숫자 텍스트의 글리프 템플릿 판독 | 템플릿 자산 |
| PopupReader (후속) | MODE-B/C: 타일 클릭 후 팝업에서 토지명·레벨 판독. v1은 인터페이스만 정의 | TileClassifier, DigitReader |
| ScanPlanner | 맵 크기·줌별 가시 범위·오클루전 영역으로 방문 좌표열 생성(뱀형 순회, 겹침 마진), 미커버 좌표 잔여 목록 관리 | GridMapper |
| Watchdog | 캡처마다 이상 상태 검사: 예기치 못한 팝업(닫기 버튼 템플릿), 로딩 화면, 창 소실. 복구 시도 후 실패 시 안전 정지 | Capturer, InputDriver |
| DataStore | SQLite(WAL) 기록, 좌표 단위 upsert(멱등), 스캔 메타·체크포인트 저장 | — |
| CsvExporter | 스캔 완료(또는 요청) 시 CSV 내보내기, 100만 행 단위 분할 옵션, UTF-8 BOM | DataStore |

## 3. 데이터 설계

### SQLite 스키마

```sql
CREATE TABLE scans (
  scan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  mode         TEXT NOT NULL,              -- 'A' | 'B' | 'C'
  started_at   TEXT NOT NULL,              -- ISO8601
  finished_at  TEXT,
  map_max_x    INTEGER,                    -- 감지된 맵 최대 좌표
  map_max_y    INTEGER,
  zoom_level   TEXT,                       -- 'wide' | 'near'
  capture_mode TEXT,                       -- 'background' | 'foreground'
  checkpoint   INTEGER NOT NULL DEFAULT 0, -- 마지막 완료 방문 인덱스
  status       TEXT NOT NULL DEFAULT 'running'  -- running|paused|done|aborted
);

CREATE TABLE tiles (
  scan_id      INTEGER NOT NULL REFERENCES scans(scan_id),
  x            INTEGER NOT NULL,
  y            INTEGER NOT NULL,
  category     TEXT NOT NULL,  -- resource|building1|building2|impassable|unknown|fail
  kind         TEXT,           -- 공터|목재|철광|석재|식량|구리|망루|...|주성|분성|성지|부두|군진|공정영|강|산|미상
  level        INTEGER,        -- 자원·성지·군진 레벨 (MODE-B/C)
  occupancy    TEXT,           -- mine|ally|friendly|enemy|neutral|unknown
  center_x     INTEGER,        -- 2칸이상 건물 중심좌표 참조
  center_y     INTEGER,
  center_estimated INTEGER NOT NULL DEFAULT 0,  -- MODE-A 추정 중심이면 1 (FR-07)
  confidence   REAL,           -- 분류 신뢰도 0~1
  status       TEXT NOT NULL DEFAULT 'ok',      -- ok|fail
  captured_at  TEXT NOT NULL,
  PRIMARY KEY (scan_id, x, y)
) WITHOUT ROWID;

CREATE INDEX idx_tiles_kind ON tiles(scan_id, category, kind);
```

- `tiles`의 PK가 (scan_id,x,y)이므로 재방문·재개 시 upsert로 중복이 발생하지 않는다(FR-10, AC-03).
- 체크포인트는 `scans.checkpoint`(방문 인덱스) + upsert 멱등성의 조합으로 구현한다. 재개 시 마지막 완료 인덱스 다음부터 방문을 재생성한다.

### CSV 스키마

`scan_<scan_id>_<YYYYMMDD>.csv` (UTF-8 BOM, 옵션 `--split-rows N`으로 분할):

```text
x,y,category,kind,level,occupancy,center_x,center_y,center_estimated,confidence,status,captured_at
```

## 4. 주요 동작

### 4.1 초기화와 프로브

1. 대상 창 탐색·크기 검증(불일치 시 안내 후 종료).
2. **캡처 프로브:** WGC로 1프레임 획득 → 검은 화면/실패 검사. **입력 프로브:** 무해한 위치(빈 지도 영역)에 PostMessage 클릭 → 화면 반응(팝업 등장) 확인.
3. 프로브 실패 시: 사용자에게 폴백(전면 제어) 여부 확인 후 전면 구현으로 전환(§9 예외 표).

### 4.2 맵 크기 감지 (FR-02)

1. 지도 버튼 클릭 → 월드맵 모드 진입(화면 템플릿으로 진입 확인).
2. 좌표 입력란에 `9999`, `9999` 입력 → 입력란이 클램프한 값을 DigitReader로 판독 → `map_max_x/y` 확정.
3. 판독 실패 시(P-03 실패) 사용자 수동 입력으로 대체.

### 4.3 MODE-A 스캔 루프

```text
plan = ScanPlanner.build(map_max, zoom, occlusion_zones)   # 뱀형 방문 좌표열
for visit in plan.resume_from(checkpoint):
    Navigator.jump(visit.center)          # 지도 모드 → 좌표 입력 → 이동
    Navigator.wait_stable()               # 프레임 diff < 임계값
    frame = Capturer.grab()
    Watchdog.check(frame)                 # 이상 화면이면 복구 루틴
    origin = GridMapper.anchor(frame, visit.center)  # 선택 타일로 그리드 보정
    for cell in GridMapper.cells(frame, origin, exclude=occlusion_zones):
        result = TileClassifier.classify(cell)
        DataStore.upsert(tile_record(result, cell.map_xy))
    DataStore.set_checkpoint(visit.index)
```

- **오클루전 처리(P-06):** 점프 직후 뜨는 선택 팝업·우측 부대 패널·상단 자원바 등 고정 UI 영역은 분류에서 제외하고, ScanPlanner가 인접 방문의 겹침으로 해당 좌표를 커버한다. 스캔 종료 시 미커버 좌표가 남으면 보충 방문을 생성한다(AC-05).
- **2칸이상 건물(FR-07):** 연속한 동일 건물 스프라이트 영역을 하나의 건물로 묶고, 스프라이트 바운딩 중심을 `center_x/y`로 기록하되 `center_estimated=1`로 표기한다.
- **지연 정책:** 조작 간 지연에 무작위 지터를 삽입한다(범위는 설정값, 기본 0.3~0.8s).

### 4.4 예외와 복구 (NFR-03)

| 감지 | 복구 |
|---|---|
| 예기치 못한 팝업(이벤트 창 등) | 닫기 버튼 템플릿 클릭 → 실패 시 체크포인트 저장 후 정지·알림 |
| 이동 후 안정화 시간 초과 | 재시도 3회 → 실패 시 해당 방문의 좌표들을 `fail` 기록 후 다음 방문 |
| 창 소실·크기 변경 | 즉시 정지, 체크포인트 보존, 재실행 시 재개 안내 |
| 분류 신뢰도 미달 | `미상` 기록 + 셀 이미지를 `evidence/`에 저장(사후 템플릿 보강용) |
| 백그라운드 동작 이상(검은 프레임 등) | 프로브 재실행 → 전면 폴백 확인 요청 |

### 4.5 완료 처리

전 좌표 커버 확인(감지된 맵 크기 대비 레코드 수) → `scans.status='done'` → CSV 내보내기 → 요약 보고(분류별 통계, `미상`/`fail` 수, 소요 시간).

## 5. 품질 속성

- **성능(NFR-02):** 광역 줌 기준 화면당 유효 타일 약 300~500개(오클루전 제외), 방문당 약 2.5초(이동+안정화+처리) 가정 시 2000×2000 맵 ≈ 6~9시간. 근접 줌 폴백 시 약 6배. 실측은 P-01/P-05 스파이크에서 확정.
- **정확도(NFR-04):** 템플릿 매칭 임계값·색상 판별 기준은 제공 스크린샷 + 실캡처 표본으로 회귀 테스트를 구성해 99% 목표를 검증. 미달 분류는 `미상`으로 보수적으로 처리(오분류보다 미상이 안전).
- **관측성(FR-11):** 콘솔 진행률(처리 좌표/전체, ETA) + 파일 로그(조작·감지 이벤트) + 증거 캡처 아카이브.
- **보안·프라이버시:** 네트워크 통신 없음, 계정 정보 미저장, 산출물은 로컬 파일. 게임 메모리 접근·패킷 분석을 하지 않고 화면 표시 정보만 읽는다(A-05 위험 고지 유지).

## 6. 안드로이드 이식 고려 (NFR-05)

인식 로직(TileClassifier, GridMapper, DigitReader)과 저장(DataStore)은 캡처·입력 인터페이스에만 의존하도록 분리한다. 안드로이드 단계에서는 ICapture/IInput을 해당 플랫폼 구현으로 교체하는 구조를 전제로 하되, v1에서 크로스플랫폼 프레임워크를 도입하지는 않는다(ADR-001).

## 7. 프로젝트 구조 (제안)

```text
map_search/
├── src/mapscan/
│   ├── cli.py              # 진입점·설정
│   ├── controller.py       # ScanController, 모드 전략
│   ├── win/                # WindowSession, capture/, input/
│   ├── nav/                # Navigator, ScanPlanner
│   ├── vision/             # GridMapper, TileClassifier, DigitReader, (PopupReader)
│   ├── store/              # DataStore, CsvExporter
│   └── watchdog.py
├── assets/templates/       # 스프라이트·글리프·UI 템플릿
├── tests/                  # 단위·회귀(스크린샷 기반)
└── docs/work/20260801-worldmap-land-scan/
```

## 8. 검증 전략과 추적성

| 요구사항 | 설계 요소 | 인수 조건 | 검증 방법 |
|---|---|---|---|
| FR-01 | Navigator, InputDriver | AC-01 | 실기 E2E: 지정 좌표 이동 후 화면 확인 |
| FR-02 | Navigator.detect_map_size, DigitReader | AC-05 | 실기: 클램프 값 판독 = 수동 확인 값 |
| FR-03 | Capturer, GridMapper, TileClassifier | AC-01, AC-02 | 스크린샷 회귀 + 실기 표본 수동 대조 |
| FR-05 | TileClassifier(색상 판별) | AC-02 | 점령상태 5종 표본 대조 |
| FR-07 | ScanPlanner(건물 병합) | AC-02 | 2칸 건물 표본 대조(추정 중심 표기 확인) |
| FR-08 | TileClassifier(미상 처리) | AC-02 | 미정의 건물 셀 입력 시 미상 기록 확인 |
| FR-09 | DataStore, CsvExporter | AC-05 | 산출물 존재·행 수·스키마 검사 |
| FR-10 | 체크포인트+upsert | AC-03 | 강제 종료→재시작 E2E, 중복·누락 카운트 |
| FR-11 | ProgressReporter, 로그 | — | 실행 로그 검사 |
| NFR-02 | ScanPlanner·줌 전략 | — | 스파이크 실측 처리량 |
| NFR-03 | Watchdog | — | 팝업 주입·창 가림 시나리오 테스트 |
| NFR-04 | TileClassifier 회귀 테스트 | AC-02 | 표본 정확도 측정 |
| NFR-06 | WgcCapture, PostMessageInput, 프로브 | AC-06 | P-04 스파이크 + 가림 상태 E2E |
| FR-04 | PopupReader(후속 인터페이스) | — | 후속 단계(MODE-B/C)에서 검증 |

## 9. 구현 착수 전 스파이크 (프로토타입 게이트)

승인 후 wf-implement 1단계로 아래 스파이크를 수행하고, 결과에 따라 ADR-002 상태를 확정한다. 각 항목은 검증 가설·판정 기준이 requirements.md §13에 정의되어 있다.

| 스파이크 | 검증 | 실패 시 경로 |
|---|---|---|
| S-1 (P-04) | WGC 가림 캡처 + PostMessage 클릭이 실제 클라이언트에서 동작 | 전면 제어 폴백(사용자 합의됨) |
| S-2 (P-01, P-05) | 광역 줌에서 자원 종류 식별 + 그리드 캘리브레이션 | 근접 줌 순회(시간 6배) 또는 자원 종류 생략 결정 요청 |
| S-3 (P-03) | 좌표 입력란 숫자 판독 | 맵 크기 수동 입력 |
| S-4 (P-06) | 선택 팝업 오클루전을 겹침 방문으로 커버 | 팝업 닫기 조작 추가 |

스파이크 코드는 `spikes/` 아래 격리하고 제품 코드에 포함하지 않는다. 판정 결과는 본 문서와 ADR-002에 기록한다.

## 10. 설계 결정 (ADR)

| ADR | 제목 | 상태 |
|---|---|---|
| [ADR-001](decisions/ADR-001-tech-stack.md) | 구현 언어·스택: Python + OpenCV | 제안 |
| [ADR-002](decisions/ADR-002-capture-input.md) | 캡처·입력: WGC+PostMessage 기본, 전면 폴백 | 제안(스파이크 게이트) |
| [ADR-003](decisions/ADR-003-storage.md) | 저장: SQLite 원장 + CSV 내보내기 | 제안 |
| [ADR-004](decisions/ADR-004-scan-mode-architecture.md) | 스캔 모드 전략 패턴 구조 | 제안 |

## 11. 위험 목록

| ID | 위험 | 영향 | 대응 |
|---|---|---|---|
| R-01 | 백그라운드 캡처/입력이 이 클라이언트에서 미동작 | 백그라운드 요구(NFR-06) 미충족 | S-1 스파이크 조기 판정, 전면 폴백 합의 확보됨 |
| R-02 | 광역 줌에서 자원 종류 식별 불가 | 스캔 시간 6배 또는 정보 축소 | S-2 판정 후 사용자 결정 요청(DCR) |
| R-03 | 게임 업데이트로 UI·스프라이트 변경 | 템플릿 전면 재캘리브레이션 | 템플릿 자산 분리·버전 표기, 검증 실패 시 조기 감지 |
| R-04 | 자동화에 따른 계정 제재 가능성 | 계정 이용 제한 | 사용자 고지(A-05), 조작 최소화·지연 지터 |
| R-05 | 스캔 중 맵 상태 변동 | 스냅샷 불일치 | 좌표별 수집 시각 기록(A-01) |
| R-06 | 400만 좌표 규모의 성능 병목(인식·DB) | 스캔 시간 초과 | 배치 upsert, 프레임 단위 병렬 분류, 실측 후 튜닝 |
