# SW 설계 — 월드맵 토지정보 추출기

- 작업 ID: 20260801-worldmap-land-scan
- 기준선: **v4 (승인됨)** — 승인일 2026-08-02 ([DCR-004](changes/DCR-004-reanchor-coordinate-integrity.md): 좌표 무결성 — 주기 재앵커 + 지연 기록. 이전: v3 [DCR-003](changes/DCR-003-nfr02-final-pan-design.md), v2 [DCR-001](changes/DCR-001-mode-a-zoom-limits.md))
- 대상 요구사항: [requirements.md](requirements.md) v3
- 작성일: 2026-08-01 / 최종 갱신: 2026-08-02 (T14 실측 반영, DCR-004 승인)
- 구현 실측으로 **수단**이 바뀐 항목은 [design-change-log.md](design-change-log.md)의 "경미한 변경" 표에 이유와 함께 기록했다. 아래 본문은 그 결과를 반영한 상태다.

## 1. 설계 개요

화면 캡처 → 타일 인식 → 저장의 파이프라인을 갖는 단일 프로세스 Windows 데스크톱 도구.

- 4개 스캔 모드(MODE-A1/A2/B/C)를 **전략 패턴**으로 수용하고, **v1은 MODE-A2(디테일 줌 전체 스캔)만 구현**한다(DCR-001). 모드별 차이는 "어느 좌표를 방문하고, 방문 지점에서 무엇을 하는가"뿐이며 이동·캡처·인식·저장 서비스는 공유한다.
- 캡처·입력은 인터페이스로 추상화하고 **백그라운드 구현(Windows Graphics Capture + PostMessage)을 사용**한다(NFR-06, ADR-002 — S-1 스파이크 통과). 캡처 세션은 **HWND 기준으로 바인딩**한다.
- 스캔 시작 시 창을 **넓고 낮은 스캔 크기(사분면)로 설정**하고 종료 시 복원한다(FR-12, ADR-005). 가시 타일 수가 종횡비에 비례하므로 스캔 소요가 약 1/3로 줄어든다.
- 수집 데이터는 SQLite를 단일 진실 원천으로 기록하고 완료 시 CSV로 내보낸다(ADR-003).
- 도구는 **관리자 권한으로 실행**해야 한다(게임이 elevated인 환경에서 UIPI가 입력·창 조작을 차단).

```text
┌────────────────────────── CLI / Config ──────────────────────────┐
│  ScanController (모드 전략 선택·수명주기·체크포인트)                  │
│   ├── DetailScan     (MODE-A2, v1)                               │
│   ├── StrategicScan  (MODE-A1, 후속·스텁)                         │
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
| WindowSession | 대상 창 탐색(제목 + HWND 확정), 관리자 권한 점검, **스캔 창 크기 설정·종료 시 복원**(FR-12, ADR-005), 실제 클라이언트 크기 측정, 시작 시 캡처·입력 프로브 | Win32 |
| Capturer (ICapture) | 창 이미지 획득. `WgcCapture`(**HWND 직접 바인딩** — `window_hwnd`. 제목 매칭은 같은 크기의 다른 창을 조용히 잡는다, T12 실측) / `BitBltCapture`(전면 폴백) | WindowSession |
| InputDriver (IInput) | 클릭·더블클릭·드래그·가상 키·텍스트 입력·휠. `PostMessageInput`(백그라운드, 기본) / `SendInput`(전면 폴백) | WindowSession |
| Navigator | 지도 모드 진입·**상태 검증**, 좌표 입력·이동(점프 = 행 시작 재앵커), **드래그 팬(행 내 주 이동, DCR-003)**, 이동 후 화면 안정화 대기(연속 프레임 diff), 맵 크기 감지(클램프 렌더링 이미지 비교, [ADR-006](decisions/ADR-006-map-size-detection.md)). **지도 UI 클릭 전에는 지도 모드 마커**, **팬·디테일 뷰 조작 전에는 디테일 뷰 시그니처(계정 HUD)**를 확인하고 불일치 시 중단한다 — 점프 완료 후 게임은 지도 UI를 닫고 디테일 뷰로 복귀한다(S-5) | InputDriver, Capturer |
| GridMapper | 화면 픽셀 ↔ 맵 좌표 변환(**일반 평행사변형 격자**, 기저 `E_MX`/`E_MY`). 앵커는 점프 후 대상 타일이 놓이는 **고정 화면 위치**. 가시 셀 열거 시 오클루전 사각형과의 교차를 분리축 정리로 판정. ⚠ **기저는 국소값**(지면이 원근 틸트로 렌더링, S-5)이며 **y-성분은 맵 지역 의존**(u-스텝당 ~2.5px, T14 실측) — 셀 좌표 계산은 앵커 y 근방 대역으로 한정하고, 행 이동 누적 오차는 주기 재앵커로 지운다(DCR-004) | 캘리브레이션 설정(`nav/ui.py`) |
| TileClassifier | 타일 셀 이미지 → (대분류, 종류, 점령상태, 신뢰도). 경계 밴드 색상으로 점령상태 → 스프라이트 템플릿 매칭 → 중립 지형 휴리스틱 → 그 외 `미상`(보수적) | 템플릿 자산 |
| DigitReader | **팝업** 좌표 등 숫자 텍스트의 글리프 템플릿 판독. 좌표 입력란 폰트는 글자가 붙어 있어 적용 불가(P-03 실패) — v1에서는 MODE-B/C용으로만 유지 | 템플릿 자산 |
| PopupReader (후속) | MODE-B/C: 타일 클릭 후 팝업에서 토지명·레벨 판독. v1은 인터페이스만 정의 | TileClassifier, DigitReader |
| ScanPlanner | 맵 크기·가시 범위·오클루전으로 **행 기반 방문 계획** 생성(DCR-003): 행 = 점프 1회 + 팬 N회, 행 간 간격은 분류 대역 높이의 화면 수직 이동에 해당하는 맵 증분. 팬당 이동량은 계획값이 아니라 실행 시 실측·누적하므로 계획은 행 시작 좌표열과 종료 조건만 정한다. 커버 구멍은 커버리지 비트맵 검사로 보충 방문(점프)을 덧붙인다(AC-05). 잉여류 타일링은 점프 전용 폴백 경로에 유지 | GridMapper |
| Watchdog | 캡처마다 이상 상태 검사: 예기치 못한 팝업(닫기 버튼 템플릿), 로딩 화면, 창 소실. 복구 시도 후 실패 시 안전 정지 | Capturer, InputDriver |
| DataStore | SQLite(WAL) 기록, 좌표 단위 upsert(멱등), 스캔 메타·체크포인트 저장 | — |
| CsvExporter | 스캔 완료(또는 요청) 시 CSV 내보내기, 100만 행 단위 분할 옵션, UTF-8 BOM | DataStore |

## 3. 데이터 설계

### SQLite 스키마

```sql
CREATE TABLE scans (
  scan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  mode         TEXT NOT NULL,              -- 'A1' | 'A2' | 'B' | 'C'
  started_at   TEXT NOT NULL,              -- ISO8601
  finished_at  TEXT,
  map_max_x    INTEGER,                    -- 감지된 맵 최대 좌표
  map_max_y    INTEGER,
  zoom_level   TEXT,                       -- 'strategic' | 'detail'
  client_w     INTEGER,                    -- 스캔 시 클라이언트 크기 (캘리브레이션 근거)
  client_h     INTEGER,
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

### 4.2 맵 크기 감지 (FR-02, [ADR-006](decisions/ADR-006-map-size-detection.md))

1. 지도 버튼 클릭 → 월드맵 모드 진입, **지도 모드 마커 템플릿으로 진입 확인**(불일치 시 재시도 후 중단).
2. 좌표 입력란에 값을 넣고 **반대 필드를 클릭해 블러**시킨다 — 클램프는 포커스가 빠질 때 적용된다(실측).
3. 값을 판독하지 않고 **렌더링 이미지를 비교**한다. `clamp(v)=min(v,max)`이므로 v의 렌더링이 상한(9999)의 렌더링과 같아지는 최소 v가 곧 `map_max`다. 0~2047 이진 탐색 11회, 축당 약 20초.
4. 입력란 조작 제약(실측): `WM_CHAR` 백스페이스는 무시되므로 `WM_KEYDOWN/UP`+`VK_BACK`을 쓰고, 커서 왼쪽만 지워지므로 **`VK_END`를 먼저** 보낸다.
5. 실패 시 사용자 수동 입력으로 대체(폴백 유지).

> 글리프 OCR(P-03)은 입력란 폰트의 숫자가 붙어 있어 실패했다. 팝업 좌표 폰트에는 `DigitReader`가 동작하므로 MODE-B/C용으로 유지한다.

### 4.3 MODE-A2 스캔 루프 (v1, DCR-003 행 기반 + DCR-004 재앵커)

```text
planner = ScanPlanner(map_max, ...)                # 행 시작 좌표열
for row in planner.resume_from(checkpoint):
    grid = Navigator.jump(row.start)               # 재앵커: 지도 UI → 이동 → 디테일 뷰 복귀
    buffer += classify_new_cells(frame, band, exclude=HUD+popup)  # 지연 기록(팬 0)
    A, B = 0, 0                                    # 누적 이동 dx(y) = A + B·y
    for k in range(row.pans):                      # 행 내 팬 방문
        verify_detail_view(frame)                  # 계정 HUD 시그니처 + 지도 모드 아님
        InputDriver.drag(PAN_PATH[k])              # 1회차: 팝업 밖 짧은 팬, 이후: 전폭
        frame = settle_and_grab()                  # 정착 0.6s — 관성 없음(S-5)
        a, b = track_shift(prev, frame)            # 전폭 밴드 3개 → dx(y) 선형 적합,
        A += a; B += b                             #   이중 앵커 기각(TrackLost면 분류 생략)
        buffer += classify_new_cells(frame, band, shift=(A, B))  # 대역 내 신규 진입 셀만
        Watchdog.check(frame)
        if k % K == K-1:                           # K=3팬마다 클릭 재앵커(DCR-004)
            drift = click_reanchor(grid, tracker)  #   팝업 좌표 판독 + 선택 링
            flush(buffer, drift)                   #   드리프트 팬별 보간 보정 후 upsert
    final_reanchor_and_flush_or_drop(buffer)       # 행 종료: 꼬리 보정 기록(실패 시 폐기)
    DataStore.set_checkpoint(row.index)
```

- **앵커 확정:** `Navigator.jump`이 대상 타일의 화면 위치를 아는 `GridMapper`를 돌려준다. 좌표 점프 후에는 선택 하이라이트 링이 신뢰할 수 없어(약하거나 지연) 게임이 대상 타일을 놓는 **고정 화면 위치**(`nav/ui.py: JUMP_ANCHOR`)를 쓴다. 템플릿 매칭 교차 검증에서 오차 1px 미만.
- **팬 이동 추적(S-5 발견 3, T14 튜닝):** 지면이 원근 틸트로 렌더링되어 **팬 이동량이 화면 y에 선형 의존**한다(전단 이동장). 전폭 밴드 3개의 x 이동을 `dx(y)=a+b·y`로 적합해 누적하고, 셀 위치는 대역별 이동량으로 갱신한다. 밴드 기각은 **이중 앵커**(게인 기대 ±250px **또는** 직전 실측 ±150px 안이면 유효, 저점수 기각) — 직전 팬 단일 앵커는 정상 팬별 변동(±100px대)의 연속 차이를 기각해 행을 조기 종료시켰다(T14 실측). 수면(강)·저대비 지형은 NCC가 낮아 간헐 TrackLost가 남는데, 해당 팬은 **분류를 생략**하고(변위 미상) 다음 재앵커 성공 시 행을 계속한다. dx(y)는 지형 고도(시차 레이어)로 ~±100px 계단 불연속이 있어(T14 실측) 선형 적합은 근사임을 전제한다 — 누적 오차는 재앵커가 지운다.
- **좌표 무결성 — 주기 재앵커 + 지연 기록(DCR-004):** 격자 기저의 y-성분은 맵 지역 의존이라(u-스텝당 ~2.5px) 추측항법만으로는 행 이동 중 좌표가 팬당 my 1.3~1.7타일씩 드리프트한다(T14 실측 — 10팬 후 최대 21타일). **K=3팬마다** 뷰 중앙 대역의 타일 — 이번 사이클에 분류된 **평지(resource) 셀 우선**(절벽·산은 고도 시차로 클릭 피킹이 수 타일 어긋난다, T14 실측) — 을 클릭해 팝업 좌표(슬라이드 **최빈값 투표** 판독, 새니티 창: `2+3·경과팬+15·유실팬` 타일)와 선택 링(폴백: 클릭점)으로 그리드를 재앵커하고 전단 누적을 리셋한다. 분류 레코드는 재앵커 사이클 단위로 버퍼링했다가 실측 드리프트를 **팬별 선형 보간**으로 보정한 뒤 upsert한다(잔여 ≤1타일). 재앵커 실패는 다음 사이클로 이월(창 확대)하고 **연속 2사이클 실패 시 행 조기 종료** — 미보정 꼬리 레코드는 기록하지 않는다(오좌표 기록보다 미커버가 안전, NFR-04 — 보충 방문 몫). 행 종료 시에도 최종 재앵커로 꼬리를 보정 기록한다.
- **분류 대역 한정:** 분류는 y 대역(기본 클라이언트 180~460)의 **신규 진입 셀**만 수행한다(커버 집합 중복 제거). 대역 한정은 국소 기저 오차(위 GridMapper ⚠)와 전단 누적 오차를 동시에 통제한다. 대역 확대는 기저 y-의존 실측(T14) 후 판단한다.
- **오클루전 처리(P-06):** HUD 사각형은 실측 불투명 영역으로 축소했다(S-6 `HUD_REFINED` → `nav/ui.py` 반영). **선택 팝업은 행 시작 프레임과 재앵커 클릭 직후에만 존재**하고 다음 팬에서 사라진다(S-5 G1) — 팝업 사각형(타일 중심 상대 −290,−215 ~ +370,+150 실측)은 해당 프레임의 분류에서만 제외한다(재앵커 클릭은 분류 후에 수행하므로 실제로는 행 시작 프레임만 해당). 팝업은 닫을 수 없고(S-4), **팝업이 열린 채의 좌표 점프는 GO 클릭이 무시되므로 GO를 재클릭한다**(T14 실측 — Navigator.jump에 구현). 스캔 종료 시 미커버 좌표가 남으면 보충 방문을 생성한다(AC-05).
- **안전 규칙:** 지도 UI를 클릭하기 전 매번 지도 모드 마커를 확인한다. **드래그 전에는 디테일 뷰 시그니처를 확인**한다(예상 밖 화면에서의 드래그·릴리스는 UI 오조작이 된다). 드래그 시작·종점은 팝업 버튼 영역(타일 우측 +355px의 점령·행군 버튼 포함)과 HUD 밖에 둔다. `ESC`는 어떤 경로에서도 쓰지 않는다.
- **2칸이상 건물(FR-07):** 연속한 동일 건물 스프라이트 영역을 하나의 건물로 묶고, 스프라이트 바운딩 중심을 `center_x/y`로 기록하되 `center_estimated=1`로 표기한다.
- **줌 제어:** 스캔 창 크기에서는 디테일 줌의 최종 단계가 곧 최대 축소이며, 한 노치 더 축소하면 전략 뷰로 전환된다(S-2c). 좌표 점프는 줌 단계를 바꾸지 않으므로 v1은 시작 시 상태를 그대로 쓴다.
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

- **성능(NFR-02) — S-6 재측정으로 확정([DCR-003](changes/DCR-003-nfr02-final-pan-design.md)):** 행 기반 팬 스캔 방문 99회 실측 — **광폭 팬(1900px) 방문당 2.95초·신규 68.2타일**(23.1타일/s), 행 시작 점프 6.70초·51타일. 맵 1620² 외삽 **33~36시간**(행당 팬 10회 기준 36.4h, 행 연장 상각 33.1h). 재앵커(DCR-004, 3팬당 클릭 1회 ≈1.5~2s)로 **39~43시간**. NFR-02는 **48시간 이내**(기준선 + 중단·복구 마진)로 확정. 미실증 개선 여지(분류 소요 17ms/타일 → 5.5ms 수준, 대역 확대)는 T13/T14에서 검증 후 반영한다. 좌표 점프 단독 경로(150시간)는 폴백으로 유지.
- **정확도(NFR-04):** 템플릿 매칭 임계값·색상 판별 기준은 제공 스크린샷 + 실캡처 표본으로 회귀 테스트를 구성해 99% 목표를 검증. 미달 분류는 `미상`으로 보수적으로 처리(오분류보다 미상이 안전).
- **관측성(FR-11):** 콘솔 진행률(처리 좌표/전체, ETA) + 파일 로그(조작·감지 이벤트) + 증거 캡처 아카이브.
- **보안·프라이버시:** 네트워크 통신 없음, 계정 정보 미저장, 산출물은 로컬 파일. 게임 메모리 접근·패킷 분석을 하지 않고 화면 표시 정보만 읽는다(A-05 위험 고지 유지).

## 6. 안드로이드 이식 고려 (NFR-05)

인식 로직(TileClassifier, GridMapper, DigitReader)과 저장(DataStore)은 캡처·입력 인터페이스에만 의존하도록 분리한다. 안드로이드 단계에서는 ICapture/IInput을 해당 플랫폼 구현으로 교체하는 구조를 전제로 하되, v1에서 크로스플랫폼 프레임워크를 도입하지는 않는다(ADR-001).

## 7. 프로젝트 구조 (제안)

```text
map_search/
├── src/mapscan/
│   ├── cli.py              # ✅ 진입점·설정 (windows/probe/classify)
│   ├── controller.py       # ⬜ ScanController, 모드 전략
│   ├── win/                # ✅ WindowSession, WgcCapture, PostMessageInput
│   ├── nav/                # ✅ Navigator, ScanPlanner, ui.py(캘리브레이션 상수)
│   ├── vision/             # ✅ GridMapper, TileClassifier, DigitReader, (PopupReader 후속)
│   ├── store/              # ✅ DataStore, CsvExporter
│   └── watchdog.py         # ⬜
├── assets/templates/       # 스프라이트·글리프·UI 마커 템플릿 (출처는 README.md)
├── tests/                  # 단위·회귀(스크린샷 기반) — 64건
└── docs/work/20260801-worldmap-land-scan/
```

UI 캘리브레이션 상수(HUD 오클루전 사각형, 지도 모드 버튼·좌표 입력란·이동 버튼,
점프 앵커)는 `nav/ui.py` 한 곳에 모은다. 창 크기를 바꾸면 이 파일만 다시 잰다.

## 8. 검증 전략과 추적성

| 요구사항 | 설계 요소 | 인수 조건 | 검증 방법 |
|---|---|---|---|
| FR-01 | Navigator, InputDriver | AC-01 | 실기 E2E: 지정 좌표 이동 후 화면 확인 → **T12 통과**(점프 3.1~4.3초, 앵커 검증) |
| FR-02 | Navigator.detect_map_size (ADR-006) | AC-05 | 실기: 감지 값 = 수동 확인 값 → **T12 통과**((1619,1619), 계정 2개 재현) |
| FR-03b | Capturer, GridMapper, TileClassifier | AC-01, AC-02 | 스크린샷 회귀 + 실기 표본 수동 대조 → **T11 부분**(회귀 통과, 표본 대조는 템플릿 확보 후 T14) |
| FR-03a | StrategicScan(후속) | — | 후속 단계(MODE-A1)에서 검증 |
| FR-12 | WindowSession(창 설정·복원) | AC-07 | 정상·중단·오류 3경로에서 복원 확인 |
| FR-05 | TileClassifier(색상 판별) | AC-02 | 점령상태 5종 표본 대조 |
| FR-07 | ScanPlanner(건물 병합) | AC-02 | 2칸 건물 표본 대조(추정 중심 표기 확인) |
| FR-08 | TileClassifier(미상 처리) | AC-02 | 미정의 건물 셀 입력 시 미상 기록 확인 |
| FR-09 | DataStore, CsvExporter | AC-05 | 산출물 존재·행 수·스키마 검사 |
| FR-10 | 체크포인트+upsert | AC-03 | 강제 종료→재시작 E2E, 중복·누락 카운트 |
| FR-11 | ProgressReporter, 로그 | — | 실행 로그 검사 |
| NFR-02 | ScanPlanner(행 기반)·Navigator(팬)·스캔 창 크기 | — | 방문당 소요 실측 → 총 소요 산출 → **S-6 실측 33~36시간, DCR-003으로 48시간 확정.** 최종 판정은 T14 전체 스캔 완주 |
| NFR-01 | WindowSession(크기 설정) | AC-07 | 스캔 창 종횡비 ≥3 확인 |
| NFR-03 | Watchdog | — | 팝업 주입·창 가림 시나리오 테스트 |
| NFR-04 | TileClassifier 회귀 테스트 | AC-02 | 표본 정확도 측정 |
| NFR-06 | WgcCapture, PostMessageInput, 프로브 | AC-06 | P-04 스파이크 + 가림 상태 E2E |
| FR-04 | PopupReader(후속 인터페이스) | — | 후속 단계(MODE-B/C)에서 검증 |

## 9. 스파이크 결과 (프로토타입 게이트)

| 스파이크 | 검증 | 결과 |
|---|---|---|
| S-1 (P-04) | WGC 가림 캡처 + PostMessage 클릭이 실제 클라이언트에서 동작 | **통과.** 단 도구 관리자 권한 필요, HWND 바인딩 필수 (`spikes/s1_background_io/findings.md`) |
| S-2 (P-01, P-05) | 광역 줌에서 자원 종류 식별 + 그리드 캘리브레이션 | **P-01 실패** → DCR-001로 MODE-A1/A2 분리. 그리드 캘리브레이션은 실현 가능 |
| S-2b/c | 창 크기·종횡비가 가시 타일 수에 미치는 영향 | **가시 타일 수 ∝ 종횡비** 확정 → ADR-005 (`spikes/s2_zoom_grid/findings.md`) |
| S-3 (P-03) | 좌표 입력란 숫자 판독 | **P-03 실패** — 입력란 폰트는 숫자가 붙어 있어 글리프 분리 불가. 대신 클램프 렌더링 이미지 비교로 **FR-02 자동 감지 달성**(맵 1619² 실측). ADR-006 (`spikes/s3_nav_ui/findings.md`) |
| S-4 (P-06) | 선택 팝업 오클루전을 겹침 방문으로 커버 | **겹침 커버는 성립, 팝업 닫기는 불가.** ESC는 게임 종료 확인 창을 띄운다. 겹침 비용이 커서 DCR-002의 주원인 (`spikes/s3_nav_ui/findings.md`) |
| S-5 | 드래그 팬으로 이동 가능 여부·이동량 재현성·누적 드리프트 | **통과** — 팬 동작·선택 미유발·관성 없음. 이동장은 화면 y에 선형(원근 지면), 드리프트는 대역별 추적으로 모델링 가능. 팝업은 첫 팬에서 소멸 (`spikes/s5_drag_pan/findings.md`) |
| S-6 | 최적화 3종 적용 방문 99회 재측정 | **완료** — 광폭 팬 2.95s/68.2타일, 총 33~36시간 산출 → DCR-003 (`spikes/s6_remeasure/findings.md`) |

스파이크 코드는 `spikes/` 아래 격리하고 제품 코드에 포함하지 않는다.

## 10. 설계 결정 (ADR)

| ADR | 제목 | 상태 |
|---|---|---|
| [ADR-001](decisions/ADR-001-tech-stack.md) | 구현 언어·스택: Python + OpenCV | 승인 (v1) |
| [ADR-002](decisions/ADR-002-capture-input.md) | 캡처·입력: WGC+PostMessage 기본, 전면 폴백 | 승인 (v1, S-1 통과로 확정) |
| [ADR-003](decisions/ADR-003-storage.md) | 저장: SQLite 원장 + CSV 내보내기 | 승인 (v1) |
| [ADR-004](decisions/ADR-004-scan-mode-architecture.md) | 스캔 모드 전략 패턴 구조 | 승인 (v1) |
| [ADR-005](decisions/ADR-005-window-aspect-ratio.md) | 창 크기·종횡비: 넓고 낮은 창으로 설정 | 승인 (v2) |
| [ADR-006](decisions/ADR-006-map-size-detection.md) | 맵 크기 감지: 글리프 OCR 대신 클램프 렌더링 이미지 비교 | 승인 (v2 구현, T12 검증) |

## 11. 위험 목록

| ID | 위험 | 영향 | 대응 |
|---|---|---|---|
| ~~R-01~~ | ~~백그라운드 캡처/입력 미동작~~ | — | **해소(S-1 통과).** 잔여: 도구 관리자 권한 실행 필요 |
| ~~R-02~~ | ~~광역 줌에서 자원 종류 식별 불가~~ | — | **현실화 후 해소(DCR-001 승인, MODE-A2 채택)** |
| R-07 | 스캔 창 크기 변경이 사용자 작업을 방해하거나 복원 실패 | 사용자 창 배치 손실 | 시작 시 안내, 정상·중단·오류 3경로 복원(AC-07), 복원 실패 로그 |
| R-08 | 작은 타일에서 분류 정확도 저하 | NFR-04 미달 | 실제 스캔 창 크기에서 표본 검증(AC-02), 미달 시 종횡비 완화. **T11 현황:** 중립형 목재·공터만 판별 가능, 점령형 스프라이트·기타 자원·건물 템플릿 미확보 → 보수적 `미상` 처리 중. T14에서 표본 수집 |
| ~~R-09~~ | ~~실측 처리량이 NFR-02에 미달~~(150시간) | — | **해소** — DCR-002 안 (d) → 팬 전환으로 33~36시간(S-6 실측), NFR-02를 48시간으로 확정([DCR-003](changes/DCR-003-nfr02-final-pan-design.md)) |
| R-10 | 오클릭으로 되돌릴 수 없는 게임 행위(점령·행군) 실행 | 계정 상태 변경 | **모든 지도 UI 클릭 전 화면 상태 검증**(T12 도입) + **드래그 전 디테일 뷰 시그니처 검증, 드래그 경로는 팝업 버튼 영역(우측 +355px 포함) 밖**(S-5 도입 — 초기 드래그 경로가 행군 버튼 위에서 릴리스되도록 설계된 것을 사전 검증이 차단한 사례 있음) |
| R-12 | 저대비(눈)·수면(강) 지형에서 팬 추적 NCC 저하 → 간헐 오추적·TrackLost | 타일 좌표 오염·커버 손실 | **이중 앵커 기각**(게인 ±250 또는 직전 ±150, T14 튜닝) + LOO·기울기 안전망. TrackLost 팬은 분류 생략, 재앵커 성공 시 행 계속(DCR-004). 잔여 미커버는 보충 방문 |
| R-13 | 기저 y-성분의 지역 의존으로 추측항법 좌표 드리프트(팬당 my 1.3~1.7타일, T14 실측) | 기록 좌표 오염(10팬에 최대 21타일) | **해소 경로 확정(DCR-004)** — K=3팬 주기 클릭 재앵커 + 지연 기록(드리프트 팬별 보간 보정). 파일럿 실증: 재앵커 적용 시 잔여 ≤1타일. 잔여 위험: 팝업 판독 신뢰도(~85~90%) — 새니티 창 + 글리프 보강(T14.3) |
| R-11 | 동일 제목 창 다중 실행 시 캡처·입력 대상 불일치 | 조작이 다른 창에 적용 | HWND 직접 바인딩(`window_hwnd`). 창 식별은 `mapscan windows --crops`의 계정명 크롭으로 확인 |
| R-03 | 게임 업데이트로 UI·스프라이트 변경 | 템플릿 전면 재캘리브레이션 | 템플릿 자산 분리·버전 표기, 검증 실패 시 조기 감지 |
| R-04 | 자동화에 따른 계정 제재 가능성 | 계정 이용 제한 | 사용자 고지(A-05), 조작 최소화·지연 지터 |
| R-05 | 스캔 중 맵 상태 변동 | 스냅샷 불일치 | 좌표별 수집 시각 기록(A-01) |
| R-06 | 400만 좌표 규모의 성능 병목(인식·DB) | 스캔 시간 초과 | 배치 upsert, 프레임 단위 병렬 분류, 실측 후 튜닝 |
