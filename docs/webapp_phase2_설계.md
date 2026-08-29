# webapp Phase 2 설계 (운영 승격 / Operational Promotion)

상태: 설계 초안. 구현 전 사용자 승인 필요. Phase 0·1은 완료·테스트 통과(32/32).

## 목표

Phase 1의 shadow 결정을 **운영 상태로 승격**한다. 승격은 별도 승인 경계를 가지며,
모든 변경은 부록불변(audit)·결정론·장애복구 가능하게 기록된다. shadow(Phase 1)와
applied(Phase 2)를 명확히 분리한다.

## 승격 경로와 원천 우선순위

확정된 선행 규칙(webapp_phase01_계약.md W1.4):
`shadow operator ledger > current_owner_decisions_v1.json > legacy JSONL`.

따라서 **승격 = ledger 확정 결정을 `current_owner_decisions_v1.json`(중간 계층)에
병합**하는 것. 하류 소비자(파이프라인)는 ledger > current_owner > legacy 순으로 읽는다.

승격 대상 3종:
1. **Authoritative 분류 원천**: `ledger/data/current_owner_decisions_v1.json`에 운영자
   오버라이드로 병합(히스토리 보존: `_operator_overrides[]` 배열에 추가 또는
   supersede 엔트리). 기존 항목을 파괴하지 않는다.
2. **live candidate DB의 `classification_decisions`**: 봉인된 snapshot DB는 읽기전용이므로
   승격 대상은 **live 작업 DB**의 classification_decisions(행 supersede)다. snapshot은
   입력으로만 사용.
3. **P26 v7 Google Sheet**: 사용자용 7열 워크북. stdlib 환경에는 Sheets 클라이언트가
   없으므로 **생성된 XLSX/CSV export를 Apps Script 엔진이 수령**하는 형태(기존 DB→XLSX
   엔진과 동일 산출물 형상)로 설계. 라이브 API 푸시는 범위 밖(필요 시 MCP/Apps Script).

## 게이트 재계산

스트림 승격은 `shadow_ready → release_ready → TRIAGE_PASS` 전이를 변경한다. 게이트
재계산은 결정론적이며 replay로 재현 가능해야 한다(Phase 1 replay UI와 동일 기준).

## 안전 불변식

- 승격은 **새 append-only 이벤트**로만 기록. 기존 이벤트 절대 수정 안 함.
- strict linear chain 계속. 승격 이벤트는 승격하는 shadow 이벤트를 참조(supersedes).
- 멱등: 동일 `client_request_id` → 중복 적용 금지.
- 장애 안전: live 대상 변경은 원자적(임시파일 → fsync → os.replace) + 완료 후에만 ledger
  성공 기록. 대상 확정 전 crash는 ledger에 미기록 → 재시도 가능.
- **소프트 supersede 복원**: true revert(대상 재작성) 대신 void 마킹으로 감사 보존.
  `revert` 이벤트는 해당 승격을 void 처리하고 다운스트림을 이전 상태로 재결정.
- 자동 적용 없음: 명시적 운영자 액션 + CSRF+Origin에서만 승격.
- 2단 승인(결재 의미): `promote`는 shadow가 `shadow_review_confirmed` head일 때만 허용,
  `release`는 별도 명시 확인(별도 토큰/액션) 필요. UI는 기본 비활성(--allow-promotion
  명시 플래그 있어야 라우트 등록 — 쓰기 모드여도 기본 off).

## 새 ledger 액션 (operator_ledger.py 확장)

- `promote`: 선행 head가 `shadow_review_confirmed`여야 함. 대상 shadow 이벤트 참조.
- `release`: 선행 head가 `promote`여야 함. 실제 live 대상 적용 트리거.
- `revert`: 선행 head가 `release`여야 함. 해당 승격 void 처리.

체인 검증기(`_head`, `append`)는 새 액션들의 선행 제약을 강제한다.

## 신규/변경 모듈

- `webapp/promoter.py`(신규):
  - `apply_to_json(target_path, event)` — current_owner_decisions_v1.json에 병합(원자 교체).
  - `apply_to_candidate(db_path, event)` — live DB classification_decisions 행 supersede.
  - `build_sheets_export(events)` — P26 v7 형상 XLSX/CSV 산출(comparator/export 재사용).
  - `recompute_gates(events)` — release_ready/TRIAGE_PASS 결정론 재계산.
- `webapp/operator_ledger.py`: 액션 3종 + 선행 제약 + `revert` 복원 로직.
- `webapp/server.py`: POST `/api/promote`,`/api/release`,`/api/revert`(플래그 게이팅).
  게이트 화면에 shadow_ready→release_ready 전이 표시.
- `webapp/cli.py`: `ledger-promote`,`ledger-release`,`ledger-revert`,`export-promoted-sheets`.

## 미해결 결정 (사용자 승인 필요)

1. **승격 기록 위치**: `current_owner_decisions_v1.json`(중간 계층)에 병합하는 것이
   맞는지 확인. (대안: live candidate DB classification_decisions 직접 supersede만.)
2. **Sheets 푸시 방식**: 생성된 export + Apps Script 수령(권장, stdlib 한계) vs
   라이브 API(MCP/Apps Script). 
3. **복원 정책**: 소프트 supersede(void 마킹, 권장) vs 하드 재작성.

## 테스트 계획 (Phase 2)

- promote/release/revert 선행 제약(잘못된 선행 액션 거부).
- apply_to_json 원자 교체 + crash 중 생성 파일 정리.
- release 후 current_owner 갱신 + 게이트 release_ready/TRIAGE_PASS 전이 결정론.
- revert 후 void 처리 + 다운스트림 롤백 결정론.
- 멱등(client_request_id 중복 무효).
- --allow-promotion 미설정 시 승격 라우트 미등록(라우트표 검사).

## 범위 밖

- 실제 라이브 Sheets API 푸시(별도 MCP/Apps Script 연동 작업).
- 여행기간/행사기간 권위 원천(trip_schedule) 편집 — 본 앱은 분류 결정만 다룸.
- 기존 파이프라인(ledger/) 코드 변경 — 승격은 current_owner_decisions_v1.json과
  live DB에만 작용하며, 파이프라인 소스는 그대로 둔다.
