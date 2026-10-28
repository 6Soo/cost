# Luna refund inline repair handoff

- 작업 기준 SHA: `70518ecd3a7a26f0ca5a853e5f2216f886c58c26` (PR297 checkout)
- `origin/main`: `496cbbe9778e002bc4265f28b50da704d28f042c`
- 목적: PR297의 inline 환불 묶음 구현을 재작성하지 않고 보호 동작을 점검·보강.

## 요구사항 상태

- CODE_WRITTEN: cleanup 보호 테스트의 DB CHECK 제약에 없는 `manual_hold` 삽입을 허용된 `evidence_pending`으로 교정.
- CODE_WRITTEN: route가 최신 preview digest 비교로 선차단하지 않고, 검증된 서버 선택 scope를 기존 `ledger.commit`에 전달해 replay 검사 우선 순서를 보존.
- CODE_WRITTEN: 동일 request ID·동일 scope 재요청은 동일 성공 결과로 replay되고 DB 전체가 불변임을 검증.
- CODE_WRITTEN: 같은 request ID·다른 digest는 `REQUEST_ID_REUSED`, 새 request ID·기존 digest는 `PREVIEW_STALE`임을 검증.
- CODE_WRITTEN: 두 번째 ledger row 쓰기 실패 시 단일 transaction rollback으로 전체 원장이 원상태인지 synthetic DB로 확인.
- TEST_PASSED: 필수 명령 `python -m pytest -q webapp/tests/test_inline_refund_cleanup_action.py webapp/tests/test_verified_cross_batch_refunds.py webapp/tests/test_cleanup_refund_display.py webapp/tests/test_refund_inference_runtime.py tests/card_pipeline/test_partial_refund.py` → `83 passed in 16.87s`.
- TEST_PASSED: `git diff --check`.
- REVIEW: cross-batch 원승인번호 검증, full zero-net 그룹, N:1 환불, 분산 batch, 중복 원결제 차단, 초과 환불/manual hold/inferred 보호 및 owner/CSRF/stale 경로를 지정 검사에서 확인.

## 변경/제한

- 변경 파일: `webapp/refund_cleanup_action.py`, `webapp/tests/test_inline_refund_cleanup_action.py`, 이 핸드오프.
- `webapp/card_flow.py`는 소유권에 따라 수정하지 않음.
- 운영 DB, 고객 거래, Google, 인증, 실제 보험/환급은 접근·쓰기하지 않음.
- 운영 검증/배포는 미실행이며 Supervisor 작업으로 남음. PR297 merge 수락 전 상태.
- 제품 전체 완료나 실제 고객 거래 해결을 의미하지 않음.

## 실행 및 커밋

- 필수 테스트 명령: 위 테스트 명령 그대로.
- 최종 커밋: 기록 예정.
