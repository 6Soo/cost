# webapp Phase 0~1 계약 (v1.1)

상태: 구현 완료·테스트 통과(2026-08-25, HEAD 3f4997f 기준 신규 경로만 추가).
운영 candidate DB·Google Sheets·기존 파이프라인 코드는 1바이트도 변경하지 않았다.

## 범위

- Phase 0(읽기전용 관제탑): sealed snapshot 계약, ro reader, 큐/상세/게이트/KPI 화면,
  keyed sidecar 대조.
- Phase 1(shadow authoring): append-only 결정원장(operator_ledger.sqlite), 체크포인트
  복구 프로토콜, 변조 탐지, 백업·복원 drill, replay 결정론, CSRF 보호 제안 API.

## Phase 0 계약

### W0.0 sealed snapshot descriptor (`webapp/snapshot_descriptor.py`)

- 봉인: `{descriptor_version, run_id, candidate_db{path,sha256,size_bytes},
  gate_report{path,sha256}, run_report{path,sha256}, candidate_semantic_sha256,
  sealed_at_utc}`. `seal_snapshot(db, gate_report, [run_report])`이 원자적으로
  `<db>.snapshot.json`을 생성한다.
- 검증: `verify_snapshot(path|dict)`은 파일 존재·SHA-256·크기·sidecar(-wal/-shm/-journal)
  부재를 재검사하고 문제 목록을 반환한다. 불일치 시 fail-closed.
- 입력 확보 절차: 정식 run은 실패 시 DB를 삭제하므로(`DIRECT_PROJECTION_KEEP_FAILED_DB=1`
  진단 실행만 보존), 봉인 대상은 해당 환경변수로 확보한 run 산출물이다.

### W0.1 read-only reader (`webapp/candidate_reader.py`)

- `file:...?mode=ro&immutable=1` URI + `PRAGMA query_only=ON`. 쓰기 시도는
  `assert_write_blocked()`로 증명한다.
- 열람 전후 파일 SHA-256 비교(`unchanged_on_disk`)로 무변경을 보장한다.
- 스키마 허용: payments 테이블 후보(card_payments/payments/normalized_payments),
  classification_decisions의 superseded_by_id/status 폴백.
- 게이트 보드는 Gate1~7과 `TRIAGE_PASS/shadow_ready/release_ready`를 **별개 행**으로
  표시한다(단일 진행률로 합치지 않는다).

### W0.3 keyed 대조 (`webapp/comparator.py`)

- baseline = snapshot DB에서 추출한 sidecar(key, amount_krw, lane, sign).
  sign은 음수 결제(취소·환불)에서 -1.
- 대상은 동일 semantic SHA에서 만든 CSV/XLSX만 허용한다. openpyxl(XLSX) 지원.
- 판정: missing/extra/field(amount,sign) mismatch. 사용자용 7열 워크북에는 내부
  event_key가 없으므로 live Sheet v7 대조는 별도 sidecar 산출 후 수행한다(아래 미결).

## Phase 1 계약

### W1.1 결정원장 스키마 (`webapp/operator_ledger.py`)

- `decision_events`: stream별 단조 `sequence_no`, `UNIQUE(stream_id, sequence_no)`,
  `event_id`(content-addressed), strict linear chain(`prev_event_hash`, 첫 행은
  `GENESIS`), `supersedes_event_id`는 반드시 현재 head를 참조한다.
- action: `propose / shadow_review_confirmed / correct / reject / withdraw /
  attach_evidence`. 운영 확정과 혼동되지 않도록 confirm 계열 이름을 shadow로 고정했다.
  stream은 반드시 propose로 시작하고 reject/withdraw 이후에는 추가 금지(terminal).
- payload 해시: domain-separated(`cost-operator-ledger-v1\0` + canonical JSON,
  sort_keys). axes는 `axes-v1` 검증기를 통과해야 하며 account/cost_type/
  allocation_target/vat_tag 외 필드 거부, cost_type은 여행원가/판관비 한정.
  **vat_tag는 제외축으로 유지**(release 완료축으로 승격하지 않는다).
- 멱등: `client_request_id` 부분 UNIQUE 인덱스. 동일 ID 재제출은 기존 이벤트 반환,
  변경 0.
- attach_evidence는 기존 행 수정이 아니라 증거를 병합한 **새 이벤트**(head supersede).

### W1.2 무결성·복구 프로토콜

- UPDATE/DELETE 차단 trigger(RAISE(ABORT,'append_only_violation')).
- WAL + busy_timeout 5000ms + BEGIN IMMEDIATE 단일 writer. 커넥션은
  check_same_thread=False + RLock 직렬화(HTTP 워커 스레드 안전).
- 체크포인트: commit마다 heads({stream: seq+event_hash})를 임시파일→fsync→
  os.replace로 원자 기록. 검증 상태: ok / checkpoint_stale(repairable) /
  mismatch(fail-closed) / missing_checkpoint(fail-closed).
- 복구 순서: `verify_chain` 선 통과 없이는 repair 금지. repair는 chain 전수 재계산 후
  체크포인트 재기록. crash 창(commit 후 checkpoint 전)은 stale로 감지·복구된다.
- 알려진 한계(Sol 지적 유지): checkpoint가 DB와 동일 권한·디스크에 있어 악의적
  전체 재해시(재작성)에는 강하지 않다. 위협모델은 "실수·부분 손상·crash"까지 방어,
  적대적 로컬 관리자는 범위 밖.

### W1.5 전송 보호 (`webapp/server.py`)

- 127.0.0.1 바인딩 고정. 모든 POST는 서버 발행 CSRF 토큰 요구 + Origin 헤더 존재 시
  Host와 일치 검사(불일치 403). body 상한 1MB.
- phase0 모드(--phase0)에서는 POST 라우트 자체가 등록되지 않는다(테스트가 라우트표를
  검사). include_writes=False면 ledger가 있어도 쓰기 불가.

### W1.6 검증 결과 (unittest 32건, 전부 PASS)

- descriptor: seal/verify, DB 1바이트 변조 탐지, gate report 변조 탐지, WAL sidecar
  봉인 거부.
- reader: query_only 쓰기 차단, 디스크 무변경, active decision(superseded 제외),
  gate/readiness 집계.
- comparator: CSV/XLSX roundtrip 일치, 금액·누락·초과 mismatch 탐지.
- ledger: strict chain, terminal 차단, 잘못된 supersedes 거부, 멱등, attach_evidence
  새 이벤트화, trigger 차단, materialize 결정론.
- tamper/recovery: 단일 필드 위조→hash mismatch, tail 삭제→checkpoint mismatch
  ("checkpoint ahead"), sequence 재배치→탐지, checkpoint 소실/stale→repair 복구,
  backup(SQLite backup API+wal_checkpoint TRUNCATE)→restore→검증 PASS.
- server: phase0 무쓰기 라우트, HTTP 스모크(큐/게이트), CSRF 부재·위조 Origin 403,
  유효 토큰 200+이벤트 기록, 축 검증 실패 400, shadow preview diff.

## 결정원천 우선순위 (W1.4)

shadow operator ledger > current_owner_decisions_v1.json > legacy JSONL
ledger_change_events. Phase 1 어디에도 운영 promotion 경로가 없으며, shadow 결과는
candidate/Sheets/Gate에 반영되지 않는다. promotion은 별도 승인 단계에서 설계한다.

## 실행 방법

```
python -m webapp.cli seal-snapshot --db <run.sqlite> --gate-report <report.json>
python -m webapp.cli verify-snapshot <snapshot.json>
python -m webapp.cli export-sidecar --snapshot <snapshot.json> --output sidecar.csv
python -m webapp.cli compare-sidecar --snapshot <snapshot.json> --other sidecar.csv
python -m webapp.cli ledger-new op.sqlite --base-semantic <sha>
python -m webapp.cli ledger-append op.sqlite --stream TX-0001 --action propose \
  --target TX-0001 --account 숙박비 --cost-type 여행원价 --rationale "..."
python -m webapp.cli ledger-verify op.sqlite
python -m webapp.cli serve --snapshot <snapshot.json> [--ledger op.sqlite] [--phase0]
python -m unittest discover -s webapp/tests -t .
```

## 편차·미결

- FastAPI/Jinja2/HTMX → 미설치 환경이라 stdlib http.server 구현(라우트 표·CSRF·
  페이지 렌더 동일 구조). 프레임워크 교체는 기계적 이관 가능.
- live P26 v7 Google Sheet와의 전수 대조는 실제 artifact 확보 후 compare-sidecar로
  수행 예정(현재는 동일 DB roundtrip으로 대조기 검증).
- 실제 5,328건 candidate run 봉인은 DIRECT_PROJECTION_KEEP_FAILED_DB=1 진단 run 또는
  staged inputs 환경에서 다음 단계로 수행.
