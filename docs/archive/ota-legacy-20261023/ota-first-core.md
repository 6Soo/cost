# OTA 결제 검토 코어

운영 자료의 읽기 전용 비교와 최종 통합 검사는 [검증 보고서](ota-first-verification-report.md)를 따릅니다. 아래 합성 검증 기록은 코어 담당자의 작업 범위입니다.

## 범위와 실행 경계

이 문서는 코드 전용 격리 작업공간의 코어 API 계약을 기록한다. 운영 레포, 운영 데이터베이스, 고객 원문에는 접근하지 않았다. 검증에는 합성 입력과 이미 존재하는 메일·포털 검증 함수만 사용했다. 운영 패리티와 전체 회귀는 코디네이터가 별도로 실행한다.

코어 구현은 `app/ota_payments.py`, `app/ota_review.py`에 있다. UI 전용 연결 코드는 이 작업에서 수정하지 않았다.

## 결제 이벤트 만들기

`build_ota_payment_events({"mail_directories": ..., "portal_databases": ...})`는 카드 거래를 받지 않고 인증된 메일과 검증된 포털 자료만 읽는다. 예약 참조 하나에 여러 실제 결제 이벤트를 둘 수 있다.

입력에 source registry의 `missing` 또는 `diagnostics`가 있거나, 등록된 경로가 빠졌거나, mail·portal·reference loader가 읽기 오류를 내면 `OtaSourcesError`를 발생시킨다. 이때 일부 source만으로 만든 이벤트 목록을 반환하지 않아 새 자동 연결 후보가 만들어지지 않는다. reference 문서는 결제 근거로 쓰지 않지만, 등록된 문서를 읽지 못하면 inventory가 불완전하므로 같은 가드를 적용한다. 오류로 이벤트 재생성이 중단되어도 검토 DB의 manual·legacy snapshot 링크는 건드리지 않는다.

- 메일 이벤트 ID는 안정된 메일 메시지 ID에서 만든다. 금액, 결제일, 카드 끝자리, 예약 참조, 원문 digest는 이벤트 ID에 넣지 않는다.
- 포털 이벤트 ID는 안정된 원본 레코드 ID와 지급 식별자 또는 레코드 안의 지급 순번에서 만든다. 데이터베이스 경로와 mutable 예약 참조는 ID에 넣지 않는다.
- `identity_source_ids`는 이벤트 정체성에 쓰고, `source_ids`와 정렬된 `source_digests`는 출처와 현재 근거를 기록한다. `source_digest`는 단일 근거 digest이거나 digest 목록의 안정 집계값이다.
- 동일 원본 포털 레코드의 복구 사본은 원본 레코드 ID와 결제 근거가 같을 때만 합친다. 같은 payload hash라도 원본 레코드 ID가 다르면 별도 이벤트로 둔다. 같은 예약·금액만으로는 합치지 않는다.
- 메일·포털 교차 출처는 공통 검증 `payment_id` 또는 명시 `source_binding_ids` 증거가 있을 때만 합친다. 날짜·금액·통화·카드 끝자리 일치만으로는 합치 않고, 두 사건을 보존해 전역 matcher가 충돌로 보류한다. 같은 portal 원본 record ID의 복구 사본 합치는 유지한다.
- 결제일은 원문에 명시된 값만 쓴다. 포털 `observed_at`, 서비스 기간, 카드 승인일로 추정하지 않는다. 외화 금액을 환율로 KRW 환산하지 않는다.
- 예약 확정, 취소 알림, 결제 문의는 `event_type=reservation`, `evidence_status=not_card_charge`로 분류한다. 예정 결제는 `scheduled_charge`와 `scheduled`로 분류한다. 실제 결제는 `charge`와 `paid_verified`, 명시 완료 환불은 별도 `refund`와 `refund_verified`로 표시한다. 취소 알림은 기존 charge를 지우거나 환불로 바꾸지 않는다.
- `ota_mail`의 인증 헤더, 본문, 발송일, 서비스 기간, 통화 금액 검증 헬퍼와 기존 숙박 영수증의 결제 제목·금액 label 정규식을 재사용한다. 조사 포함 `결제가 완료`, 영어 `payment ... received/successful` 제목과 `결제 완료` 금액 label도 합성 fixture로 확인한다. `ota_portal`의 원본 해시·근거 역할·결제 검증기도 재사용한다. 메일 추출에는 카드 목록을 전달하지 않는다.

## 카드 탐색과 자동 연결

`same_date_cards(event, transactions, links=None)`는 merchant와 금액으로 행을 미리 걸러내지 않고 결제일과 같은 날짜의 모든 카드 행을 반환한다. 결과의 `already_linked_event_id`로 기존 점유를 표시한다.

`match_ota_payment_events(events, transactions, existing_links=None, rules=None)`는 전체 입력 안에서 1:1 배정을 확인한다. 모든 기존 링크가 현재 이벤트 목록에 없어도 거래를 점유한다. 중복 점유 링크가 있으면 해당 이벤트를 `HOLD_AMBIGUOUS`로 보낸다.

지원 상태는 `MATCHED_AUTO`, `MATCHED_USER`, `HOLD_NO_CARD`, `HOLD_AMBIGUOUS`, `HOLD_AMOUNT_MISMATCH`, `HOLD_DATE_UNKNOWN`, `HOLD_EVIDENCE_CONFLICT`, `PENDING_PAYMENT`, `NOT_CARD_CHARGE`다. 실제 결제일이 확인되지 않은 검증 charge는 `HOLD_DATE_UNKNOWN`이다. 예약·예정 결제는 실제 결제 수로 집계하지 않는다. `_event_is_paid(event)`가 charge와 명시 완료 refund만 실제 금전 이벤트로 판정한다.

KRW charge는 정확 금액만 자동 연결하며, refund는 signed 카드 원금의 절댓값과 refund 방향을 함께 확인한다. 외화는 원문 통화와 카드의 `foreign_currency` 및 `foreign_amount`가 정확히 일치해야 한다. 승인된 좁은 규칙의 `amount_delta_krw`는 부호를 포함한 `card amount - OTA amount`와 정확히 같아야 한다. booking 참조 하나만으로 보조 근거를 만들지 않는다.

## 기존 exact 연결 보존

`bind_legacy_portal_links(events, legacy_links)` 입력은 기존 검증기가 exact로 판정한 binding이어야 한다. binding은 `verified_exact`, `evidence_kind`, `booking_ref`, `source_digest`, `transaction_id`, `card_last4`, `amount`, `currency`를 제공한다. source와 예약·카드·금액이 유일하게 맞는 canonical event만 binding한다. 새 포털 이벤트를 만들거나 결제일을 추정하지 않는다.

matcher의 `existing_links`는 `ota_event_id -> {transaction_id, status, source_digest, legacy_exact, source_digests}` 형태를 받는다. legacy 링크는 현재 이벤트가 실제 결제이고 digest와 source digest가 겹치며 금액·통화·방향·카드 끝자리가 모두 맞을 때만 보존한다. legacy 날짜가 없는 이벤트는 신규 자동 연결 대상이 아니다.

## 수동 검토와 source 변경

`OtaReviewStore(path)`는 호출자가 지정한 별도 검토 데이터베이스만 연다. 파일이 없으면 생성하지 않고, 기존 파일도 `ota_review_` 표 이외의 표가 있으면 거부한다. `links()`, `active_rules()`, `proposals()`, `preview()`는 읽기 전용이며 스키마를 만들지 않는다. `confirm()`, `answer_proposal()` 및 변경 상태를 기록할 필요가 있는 `refresh()`만 초기화를 수행한다.

수동 연결은 이벤트·카드 snapshot과 안정 event ID로 저장한다. 다음 refresh에서 같은 source identity의 금액·날짜·카드·예약 참조 또는 digest가 바뀌어도 `MATCHED_USER`와 카드 점유를 유지하고 `evidence_changed` 경고를 남긴다. 원본이 사라지거나 더는 이벤트를 검증하지 못하면 저장 snapshot을 반환하고 `evidence_missing`을 표시한다. 누락된 manual event의 카드도 다른 이벤트에 배정하지 않는다.

`refresh(..., changed_transaction_ids=..., changed_event_ids=...)`는 바뀐 이벤트, 해당 카드에 이미 연결된 이벤트, 날짜·방향·보조 식별 근거가 맞는 변경 카드 후보만 반환한다. 이는 incremental import와 source-targeted refresh의 계약이다.

`confirm()`은 preview digest가 현재 입력과 다르면 `STALE_PREVIEW`를 돌려준다. 현재 paid 근거와 명시 refund 검증, 안정 ID, 전역 카드 미점유를 요구한다. 호출자는 최신 전체 점유 snapshot을 `allocations`로 반드시 전달한다. 생략하거나 `None`을 전달하면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부하며, 전체 점유를 확인한 뒤 전달한 명시 `{}`는 허용한다. 확인은 한 번의 연결만 만들고 새 규칙은 제안 상태로 둔다.

규칙 레코드는 `rule_id`, `conditions`, `source_event_id`, `source_transaction_id`, `approved_by`, `user_confirmation`, `created_at`, `version`, `active`를 보존한다. `once`는 규칙을 만들지 않는다. 편집은 새 pending 제안만 만들며 자동 활성화하지 않는다. 명시 승인된 좁은 조건만 active 목록에 반환한다. 지원 조건은 provider·item과 merchant 또는 issuer·card 끝자리로 범위를 제한하고, 날짜 차이는 최대 7일, signed KRW 차이는 -10000부터 10000까지 허용한다.

## 인터페이스 변경 기록

- 서로 다른 원본의 mail·portal 이벤트는 공통 검증 `payment_id` 또는 명시 `source_binding_ids` 증거가 있을 때만 합친다. 날짜·금액·통화·카드 끝자리가 같다는 조건만으로는 합치지 않으며, 두 이벤트를 보존해 전역 matcher가 충돌로 보류한다. 같은 portal 원본 record ID의 복구 사본 병합은 유지한다.
- `OtaReviewStore.event_snapshots()`는 GET용 읽기 전용 API다. 반환값은 `{event_id: event_snapshot}`이고 각 snapshot에 `_evidence_missing`, `_evidence_changed`를 붙인다. `links()`의 점유 상태와 조합해 sourcegone 경고를 그린다. GET에서 `refresh()`를 호출하지 않는다.
- `confirm(..., allocations=...)`에는 전체 최신 자동·기존·수동 점유 snapshot을 반드시 전달한다. 인자를 생략하거나 `None`이면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부한다. 호출자가 전체 현재 점유를 확인한 뒤 보낸 명시 빈 `{}`는 유효하다.
- `confirm()` 응답과 `proposals()`는 `proposal_conditions` 또는 `conditions`, `proposal_review_warnings` 또는 `review_warnings`를 제공한다. 검증된 KRW charge의 제안은 signed `amount_delta_krw = card - OTA`와 양방향 절댓값 날짜 간격 `date_lag_days`를 담는다. 범위 밖 금액·날짜, 외화, 또는 검증되지 않은 값은 warning을 반환하고 승인 전에 편집을 요구한다. `once`는 다음 이벤트에 규칙을 적용하지 않는다.

- 카드 검색 API는 전체 같은 날짜 행을 반환하고 기존 점유 event ID를 추가한다. 이전 UI의 금액·merchant 사전 필터 가정은 사용할 수 없다.
- 이벤트 결과에는 `identity_source_ids`, `source_digests`, `evidence_status`, `event_type`을 제공한다. `ota_event_id`는 mutable 증거 값과 분리했다.
`confirm()`은 preview digest가 현재 입력과 다르면 `STALE_PREVIEW`를 돌려준다. 현재 paid 근거와 명시 refund 검증, 안정 ID, 전역 카드 미점유를 요구한다. 호출자는 최신 전체 점유 snapshot을 `allocations`로 반드시 전달한다. 생략하거나 `None`을 전달하면 `GLOBAL_ALLOCATIONS_REQUIRED`로 거부하며, 전체 점유를 확인한 뒤 전달한 명시 `{}`는 허용한다. 확인은 한 번의 연결만 만들고 새 규칙은 제안 상태로 둔다.
- `links()`는 기존 `transaction_id`와 `status`에 evidence warning 필드를 보탠다. `event_snapshots()`는 저장 event와 warning bit를 읽기 전용으로 제공한다.
- 규칙 조건 이름은 UI가 보내는 `amount_delta_krw`를 사용한다. 제안 질문은 조건과 warning을 `confirm()` 응답 또는 `proposals()`에서 읽을 수 있다.

## 합성 검증

matcher는 `active=False` 또는 `status=inactive|revoked`인 규칙을 승인자 기록보다 우선해 거부한다. `approved_by`가 있어도 비활성 규칙은 적용되지 않는다.

규칙은 `approved_by`, `user_confirmation`, `approved=True` 가운데 명시 승인 증거가 있어야 한다. `status=active`만으로 승인으로 보지 않는다. 검토 제안과 matcher는 같은 내부 범위 검사기를 사용하며, provider·item에 merchant 또는 issuer·card 끝자리가 있어야 한다.

최종 보완에서 실행한 좁은 회귀:

```powershell
python -m pytest tests/card_pipeline/test_ota_review.py -q
python -m pytest tests/card_pipeline/test_ota_payments.py::test_signed_approved_amount_delta_matches_but_absolute_or_unapproved_delta_does_not tests/card_pipeline/test_ota_payments.py::test_same_date_and_amount_mail_portal_claims_without_identity_proof_stay_separate tests/card_pipeline/test_ota_payments.py::test_mail_and_portal_same_payment_id_merge_source_digests_once tests/card_pipeline/test_ota_payments.py::test_portal_snapshot_copies_with_only_observed_at_change_deduplicate -q
python -m py_compile app/ota_payments.py app/ota_review.py
```

이 targeted 검증은 review 25개와 payment 관련 4개가 통과했다. 운영 자료 패리티와 전체 회귀는 실행하지 않았다.

핵심 targeted 테스트 명령:

```powershell
python -m pytest tests/card_pipeline/test_ota_payments.py tests/card_pipeline/test_ota_review.py -q
```

검증기 재사용 호환 확인:

```powershell
python -m pytest tests/card_pipeline/test_ota_portal.py::test_source_hash_and_evidence_roles_are_required tests/card_pipeline/test_booking_mail.py::test_duplicate_message_enrichment_is_allowed_but_changed_body_is_rejected -q
python -m py_compile app/ota_payments.py app/ota_review.py
```

위 targeted 테스트는 source inventory 누락과 mail·portal·reference loader 오류에서 새 이벤트 권한이 막히는지, 기존 manual snapshot 보존, source 변경·삭제·결제 근거 상실 후 카드 점유, 원본 복구 사본 중복, 여러 결제, 결제일 미확인, 외화 정확 비교, signed refund/delta, 규칙 승인, preview stale, incremental refresh, Booking 결제 영수증의 16가지 합성 제목·금액 label 조합을 확인한다. 운영 자료 패리티, 실제 old 200 연결 결과, 전체 회귀는 이 작업에서 실행하지 않았다.
