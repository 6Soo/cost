# Luna refund inline repair handoff

- 작업 기준 SHA: `70518ecd3a7a26f0ca5a853e5f2216f886c58c26` (PR297 checkout)
- `origin/main`: `496cbbe9778e002bc4265f28b50da704d28f042c`
- 목적: PR297의 inline 환불 묶음 구현을 재작성하지 않고 보호 동작을 점검·보강.

## 요구사항 상태

- CODE_WRITTEN: 지정 inline cleanup 테스트에서 DB CHECK 제약에 없는 `manual_hold` 삽입을 허용된 `evidence_pending`으로 교정.
- CODE_WRITTEN: inline 동일 요청 재시도는 stale 응답과 무변경 원장을 확인.
- CODE_WRITTEN: 두 번째 ledger row 쓰기 실패 시 단일 transaction rollback으로 전체 원장이 원상태인지 synthetic DB로 확인.
- TEST_PASSED: 지정 명령 `python -m pytest -q webapp/tests/test_inline_refund_cleanup_action.py webapp/tests/test_verified_cross_batch_refunds.py webapp/tests/test_cleanup_refund_display.py webapp/tests/test_refund_inference_runtime.py tests/card_pipeline/test_partial_refund.py` → `81 passed in 18.28s`.
- TEST_PASSED: `git diff --check`.
- REVIEW: cross-batch 원승인번호 검증, full zero-net 그룹, N:1 환불, 분산 batch, 중복 원결제 차단, 초과 환불/manual hold/inferred 보호는 지정 테스트 경로에서 확인. owner/CSRF/stale, 원자 rollback, inline 재시도도 확인.

## 변경/제한

- 실제 코드 동작 변경 없음. 변경 파일은 `webapp/tests/test_inline_refund_cleanup_action.py`뿐.
- `webapp/card_flow.py`는 소유권에 따라 수정하지 않음.
- 운영 DB, 고객 거래, Google, 인증, 실제 보험/환급은 접근·쓰기하지 않음.
- 실제 운영 검증/배포는 미실행이며 Supervisor 작업으로 남음.
- 제품 전체 완료나 실제 고객 거래 해결을 의미하지 않음.

## 실행 및 커밋

- 필수 테스트 명령: 위 테스트 명령 그대로.
- 기준 커밋: `70518ecd3a7a26f0ca5a853e5f2216f886c58c26`
- 최종 커밋: `94686b1b2d632e9735f57665ae1ab7b0f7fbcc45`.

