# 영수증 Paseo 병렬 구현 계약

2026-11-16 사용자가 설계 구현·다수 Luna xhigh 병렬 위임을 승인했다. 통합 감독은 주 세션이며 배포는 이번 요청에 포함하지 않는다. 실행 정본은 SPEC §7.1과 [승인 설계](../../design/receipt-paseo-workflow-20261116.md), 금융 보호는 규칙집이다. 아래는 작업자 간 파일 소유권·API 계약이다. 재귀 위임·고객 자료·운영 포트/DB 사용은 금지한다.

## 소유권

- A runtime: `app/receipt_paseo.py`, `tools/receipt_paseo_bridge*`, 필요 시 `tools/receipt_paseo_plugin/`, `tests/card_pipeline/test_receipt_paseo_runtime.py` 및 해당 신규 helper/fixture만. 실제 설치 Paseo SDK/CLI를 조사해 사진 첨부·동적 목록·공식 결과 회수·도구 차단을 구현한다. 플러그인은 공식 문서·타입으로 기능을 확인하고 영수증 실행에만 범위를 제한한다. 다른 에이전트나 전역 제공자 설정을 변경하지 않는다.
- B backend: `webapp/receipt_workflow_store.py`, `webapp/receipt_ledger.py`, `webapp/receipt_workflow.py`, `webapp/tests/test_receipt_workflow*.py`, `webapp/tests/test_receipt_ledger*.py`. 필요한 `ledger_store_schema.py`/`ledger_store*.py` 변경과 `ledger_board.py`의 서버 시작 worker hook도 B 소유. 영속화·재연결·검수·멱등/원자적 장부 반영·인증 API 담당. 기존 구현의 실제 모듈 위치를 유지한다.
- C UI: `webapp/receipt_review.py`, `webapp/receipt_workflow_ui.py`, `webapp/static/js/receipt_workflow.js`, `webapp/static/css/receipt_workflow.css`, UI 전용 신규 검사. 기존 원본 업로드·수동 입력·후보 보호는 유지하고 신규 흐름을 기본 화면으로 연결한다.
- 통합 감독: docs·test-impact-map·통합 검사·독립 검수·브랜치 통합/정리. 같은 파일에 동시 작성하지 않는다. 계약 변경은 먼저 감독과 관련 작업자에게 알린다.

## runtime Python 계약(A→B)

`app.receipt_paseo`: `PaseoError(code)`, `catalog(provider=None)` → `{connected,host_label,checked_at,providers:[{id,label,available}],models:[{provider,id,label,selectable,reason,thinking_options,default_thinking}]}`.

`start(image_path, provider, model, *, run_key)` → 영속 가능한 handle `{agent_id,workspace_id,provider,model,...}`. 고정 관리 프롬프트와 실제 사진을 전송하고 신속 반환한다. `inspect_run(handle)` → `{status:'running'|'done'|'failed',result?:<기존 validate_response 호환 결과>,code?}`. `find_run(run_key)` → handle 또는 None(실제 없음); 통신 실패는 None 대신 예외. `archive_run(handle)`은 해당 작업 자원만 공식 정리한다. 이미지를 모르는 모델/OCR·자동 모델 대체·프롬프트 자유 편집 없음. 사진 hash는 런타임이 계산해 결과 원본 대응을 검증한다. 필요하면 handle에 원본 hash를 보존한다.

감독 검수 후 추가 계약: `prompt_metadata()`는 `{prompt_version,prompt_sha256,schema_version,schema_sha256}`를 반환한다. `managed_prompt()`는 실제 전송하는 `SYSTEM_PROMPT + '\n\n' + managed_user_prompt()` 문자열을 반환한다. 새 관리 wrapper는 단일 JSON 객체 출력을 지시하며, user prompt는 관리 playbook의 StructuredOutput 지시를 JSON 객체 지시로 바꾸고 원본 스키마 텍스트를 포함한다. prompt 해시는 이 결합 문자열의 UTF-8 SHA-256, schema 해시는 원본 schema 파일 바이트의 SHA-256이다. 기존 단독 CLI의 system prompt는 변경하지 않는다.

`start`는 `expected_prompt_metadata=None,thinking=None` 키워드를 추가로 받는다. B는 배치 생성 시 관리 지시·스키마 해시와 목록의 기본 추론 옵션을 고정하고 재시도에도 보존한다. A는 실행 직전 실제 관리 파일 해시·실제 추론 옵션을 검증하며, 변경된 지시를 조용히 보내지 않고 `PASEO_PROMPT_CHANGED`로 종료한다. handle에 실제 해시·추론 옵션을 기록한다. 이미 시작된 실행의 재조회에는 최신 파일과의 불일치를 이유로 원래 결과를 버리지 않는다. 프롬프트가 변경돼 접수 작업을 실행할 수 없으면 명시적인 새 분석으로 처리한다.

## 인증 HTTP 계약(B→C)

기존 owner·CSRF·사진 소유 검증을 서버에서 유지한다. 경로:

- GET `/api/receipts/paseo/models?provider=...` → 위 catalog 객체.
- POST `/api/receipts/workflow/batches` `{images:[sha],provider,model,request_id}` → `{batch:<아래 배치>}` HTTP202.
- GET `/api/receipts/workflow` → `{batches:[<배치>]}`. 복귀 시 전체 상태를 서버에서 읽는다.
- POST `/api/receipts/workflow/review` `{candidate_id,expected_revision,changes,selected?}` → `{candidate:<후보>}`.
- POST `/api/receipts/workflow/apply` `{request_id,selections:[{candidate_id,expected_revision}]}` → 실제 반영 결과.
- POST `/api/receipts/workflow/retry` `{job_id,request_id}` → `{batch:<배치>}`. 이전 실행 종료 확인 없이 중복 호출하지 않는다.

배치: `{batch_id,created_at,provider,model,status,jobs:[{job_id,image,status,code?}],candidates:[<후보>]}`.
후보: `{candidate_id,image,revision,selected:false,merchant,date,amount,currency,payment,trip_id,category,box,applied:false,ledger_id?,company_expense?}`. 결제수단은 기존 `cash/private_card/corporate_card`를 사용한다. corporate_card는 증빙 연결만, private_card는 회사 비용 인정 필요. 실제 카드 모델의 `card`는 검수 전 결제수단 미지정으로 둔다. revision 동시성 보호와 기존 원본/card/refund/closed-period 보호 필수.

C는 `receipt_review.dispatch`의 기존 enabled/owner 검증과 함께 신규 경로를 `receipt_workflow.dispatch(handler,parsed,raw=raw,csrf=csrf,board=board,is_owner=is_owner,query=query)`에 전달한다. B는 기존 receipt store helper를 함수 안에서 lazy import하여 원본·여행/카드를 검사할 수 있다. 신규 API 경로의 GET/POST 구분도 서버에서 강제한다. 새 저장소는 receipt store 옆 `receipt-workflow.sqlite`를 기본으로 하고 `WEBLEDGER_RECEIPT_WORKFLOW_DB`로 합성 격리 가능하다.

## 완료 조건

각 작업자는 소유 파일만 커밋하고 SHA·표적 검사·남은 사항을 보고한다. 테스트는 합성·임시 경로만 사용한다. 0건/skip은 통과가 아니다. 운영 코드 기대값을 낮추는 기존 테스트 수정은 하지 않는다. 통합 감독이 A1~A15에 맞춰 직접 검사하고 최종 별도 sol medium 이상 검수를 받는다. 코드/검사 실패를 기록만 하고 완료 처리하지 않는다.
