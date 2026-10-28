# 2026-10-28 병합 후 기존 AGODA 환불 카드 미정리 재현·수정

- 상태: **CODE_REVIEWED / TARGETED_83_AND_ADJACENT_38_PASSED / PR_NOT_DEPLOYED / OWNER_APPLY_NOT_RUN**
- 현상: 사용자 지출정리에서 2026-09-22 AGODA NICE-Agoda +625,280 / -625,280 원결제·취소가 여전히 각각 카드로 나온다. 카카오 미연결 10건은 별도 외부 원결제 증빙 문제다.
- GitHub 확인: PR #295는 2026-10-28 19:23 KST에 main merge (SHA `496cbbe9778e002bc4265f28b50da704d28f042c`). 마지막으로 별도 운영 수락된 Board SHA는 이전 인계에서 `9f6eec7`; 최신 생산 SHA·고객 DB는 이 감사에서 확인할 수 없다.

## 실제 원인

1. 기존 `/import` GET은 `render_expense_cleanup` 읽기만 한다. **과거 미기록 카드를 재분류/전기하지 않는다.**
2. PR #295의 다른 배치에 흩어진 검증 전액 상쇄 원결제+취소 동시 기장 지원은 `flow._auto_record_locked` 또는 관리자 유지관리 적용이 실제로 실행될 때만 사용한다. 병합/브라우저 새로고침만으로 과거 625,280원 두 원행은 기장되지 않는다.
3. 레거시 `/api/imports/reclassify-pending`는 410을 반환하고, 현재 안전한 일괄 유지관리는 **다른 화면에서 미리보기·승인**을 요구한다. 사용자는 과거에 같은 화면에서 바로 행동할 수 없다는 UX 문제를 지적했다.
4. 특히 스크린샷 원결제 행의 **`원결제와 취소·환불 1건의 금액이 전액 상쇄됩니다`** 문구는 `inferred=False`라는 UI 로직에서만 나오므로, 현재 화면상에서는 확정 근거 기반 링크로 인식된 거래다. 다만 실제 DB의 해당 행 원승인번호·수동 보류·원본 충돌·전기 상태는 운영 자료를 봐야 확정할 수 있다.
5. 카카오 PR #295는 같은 카드의 `유페이` 중계 표기를 **원결제 비교 후보**에 추가했을 뿐, 10건의 승인번호/금융 연결 증빙을 만들어서 자동 확정하지 않는다.

## 후속 실제 코드

- `app/ledger.py`: `include_verified_full_refunds=True`의 **원승인번호 검증 전액 0원 묶음**에 한해서 `group_original` 범위를 허용, 기존 group preview/commit의 모든 원본 보호·단일 트랜잭션·idempotency/재검증 유지. 기존 일반 group/단일 batch 계약은 불변.
- `webapp/refund_cleanup_action.py` 신규: owner-only + CSRF, `/api/maintenance/refund-pair/<original_id>/preview` / `apply` 두 단계. `original_id`를 클라이언트가 조작해도 **실제 DB의 원결제+모든 취소·원승인번호·net0·source batch**를 서버에서 다시 결정. preview는 읽기만; apply는 명시적으로 확인된 digest+request ID를 전달받을 때 **해당 묶음만** commit. 타 카드행·이용일·Google 장부·실제 환급 완료 상태는 수정하지 않음. 금액 충돌/추론/보류는 409 또는 차단 사유.
- `webapp/card_flow.py` + `webapp/card_cleanup_ui.py`: 기존 지출정리 AGODA 원결제/취소의 유효한 전액 상쇄 묶음에만 **'전액 상쇄 묶음 기록'** 버튼 하나 표시. 같은 화면에서 읽기 미리보기→확인→안전하게 전기→새로고침. 다른 화면 이동을 강요하지 않는다. 미리보기 보류 사유는 버튼 아래에 표시.
- `webapp/tests/test_inline_refund_cleanup_action.py`: synthetic 다른 2개 배치, 불관련 지출 한 건, read-only preview, 2건 원자 기장, 지출정리 카드 제거, owner/CSRF/stale, 추론/수동 보류/초과환불 차단.

## 검증 및 운영 수락 절차

1. 반드시 checkout 환경에서 다음 명령을 **실제로 실행**하고 로그 첨부: `python -m pytest -q webapp/tests/test_inline_refund_cleanup_action.py webapp/tests/test_verified_cross_batch_refunds.py webapp/tests/test_cleanup_refund_display.py webapp/tests/test_refund_inference_runtime.py tests/card_pipeline/test_partial_refund.py`. 테스트 미실행이면 **병합/배포 준비 완료가 아님**.
2. Windows 운영 외부효과 작업자와 겹치지 않게 파일 소유권·SHA 고정, 보호 13개 테이블/운영 DB 백업+별도 복원 검증 후 배포. 등록된 Windows 서비스와 `ledger.foresttour.kr` 인증 UI의 실제 실행 SHA 확인.
3. 사용자 지출정리 카드에서 해당 버튼 확인 → 먼저 미리보기: **2건, 순액0, 미기록 원행 수, 보호 차단 사유** → 운영 DB/원승인번호 실물 확인 → 사용자 명시 승인 → commit. `ledger_entries`의 원결제·취소 2행과 각 `board_rows` 동시 기록, `SUM(amount_krw)=0`, 변경 이력, 재시도 0과 화면에서 **두 카드 모두 제외** 확인. 사용자 확인 없이 운영 금융 DB에 자동 소급 쓰기 금지.
4. 여전히 버튼이 없으면 (a) 운영 SHA가 최신인지, (b) API `WEBLEDGER_CARD_FLOW` enabled, (c) owner 권한, (d) 확정이 아닌 inferred/서로 다른 날짜 상태, (e) 다른 페이지/현재의 보호 조건을 분리 진단. UI만 보고 원본을 임의 수정하지 않는다.
5. 카카오 미연결 10건은 카드사 원승인번호/누락 구매 원본·사용자 검토가 확보될 때까지 기존 금융 대기열 유지. 후보 표시는 금융 실제 환급 완료가 아니다.

**이 문서 병합도 운영에 자동 반영되지 않는다. PR만으로 실거래 해결을 선언하지 않는다.**
