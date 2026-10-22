# OTA 결제 보류 검토 UI

운영 자료의 읽기 전용 비교와 최종 통합 검사는 [검증 보고서](../../../docs/ota-first-verification-report.md)를 따릅니다. 아래 표적 검사 기록은 화면 담당자의 작업 범위입니다.

## 범위와 활성화 조건

이 화면은 기존 카드 가져오기 화면의 opt-in 영역입니다. 다음 설정이 모두 있어야 `/import`에 영역이 나타나고 `/api/imports/ota` 경로가 활성화됩니다.

- `WEBLEDGER_CARD_FLOW=1`
- `WEBLEDGER_OTA_REVIEW_MODE=isolated`
- 절대 경로를 지정한 `WEBLEDGER_OTA_REVIEW_DB`

기본 자료 읽기는 `board.path.parent`에서 `ota-sources.json`을 찾고 기존 `app.ota_sources.resolve_sources` 계약을 사용합니다. 기본 메일 위치는 `WEBLEDGER_OTA_MAIL_DIR` 또는 `ota-mail`, 포털 기본 위치는 기존 `WEBLEDGER_AGODA_PORTAL_DB`와 `evidence_path` 규칙입니다. manifest의 등록 자료와 기존 기본 경로를 함께 사용합니다. `WEBLEDGER_OTA_SOURCES_JSON`은 합성 검증용 명시 override입니다. 키는 `mail_directories`, `portal_databases`, `reference_documents`입니다. UI adapter는 `app.ota_payments.build_ota_payment_events`, `match_ota_payment_events`, `same_date_cards`와 `app.ota_review.OtaReviewStore`를 호출합니다. 검토 DB는 카드 장부 DB와 같은 파일이면 거부합니다.

기본 설정은 기능을 끈 상태입니다. adapter는 일반 카드 흐름과 분리되어 있고 코어 파일을 변경하지 않습니다.

## 읽기와 쓰기 경계

첫 GET과 POST preview는 코어가 기존 검토 DB를 읽기 전용으로 엽니다. DB 파일이 없으면 연결을 만들지 않습니다. UI GET은 `links`, `event_snapshots`, `active_rules`, `proposals` 같은 조회만 사용합니다. `refresh`는 GET에서 호출하지 않으며, 새 근거와 기존 source digest 차이는 현재 읽은 자료로 계산합니다. 근거가 사라지거나 결제 확인이 무효가 된 수동 연결은 저장된 이벤트 snapshot과 `evidence_missing` 경고를 보여 줍니다. 해당 거래의 재선택을 막고, GET 때문에 저장소 디렉터리·DB·스키마를 만들거나 변경하지 않습니다.

POST 쓰기 경로는 명시적 사용자 동작만 처리합니다. 카드 가져오기 뒤에는 해당 가져오기 batch에 새로 생긴 `transaction_id`만 `refresh_after_import`에 전달합니다. 저장된 수동 연결의 source digest가 달라졌다면 관련 `event_id`도 전달합니다. 코어의 `refresh`는 기존 `MATCHED_USER` evidence 변경 상태를 보존합니다. 수동 연결은 분리된 검토 DB에 기록하며 카드 장부 board에는 기록하지 않습니다.

기존 카드 흐름의 읽기 전용 `match_mail` → `extend_report` 비교 결과를 카드 상태가 바뀔 때 한 번 계산해 board 메모리에 exact 연결 snapshot으로 둡니다. 실제 report의 `matches`에는 제공자, 예약 참조, source hash와 digest, 거래 ID, 방향, 항목·기간·근거 종류가 포함될 수 있지만 카드 끝자리·통화·금액은 없을 수 있습니다. 따라서 report에서 카드 사실을 만들어내지 않습니다. report digest와 canonical event digest의 교집합, 제공자·예약 참조·source hash·방향이 맞는지 확인한 뒤, 연결된 원본 거래 행의 직접 필드에서 원화 금액 또는 외화 금액·통화, 카드 끝자리와 방향을 canonical event와 대조합니다. 각 이벤트와 거래의 유일한 연결만 pin합니다. canonical event에 다른 근거 digest가 더 있어도 report digest가 교집합에서 검증되면 기존 exact 연결을 보존합니다. 수동 연결이 우선하며 source 변경 뒤 legacy 거래를 새 카드로 다시 추론하지 않습니다.

카드 연결은 미리 보기와 명시적 확정의 두 단계입니다. 확정 때 최신 이벤트, 카드 점유, preview digest를 다시 검사하고, 코어 `confirm`에 현재의 모든 자동·수동·legacy 점유를 `allocations`로 전달합니다. 점유가 없어도 `allocations={}`를 명시합니다. 자동 일치 또는 기존 수동 연결 거래는 목록에 남기되 이유를 표시하고 선택을 막습니다. 비어 있는 CSRF 설정이나 요청 헤더는 OTA POST에서 허용하지 않습니다.

## 표시 및 개인정보

API snapshot은 allowlist로 만듭니다. 카드 거래는 `transaction_id`, `issuer`, `card_kind`, `card_tail`, `approval_date`, `posting_date`, `merchant`, `amount_krw`, `foreign_amount`, `currency`, `approval_number`, `direction`, 환불·취소 상태, 연결 ID와 안전한 연결 사유만 내보냅니다. OTA 이벤트는 제공자, 예약 참조, 이벤트 종류, 결제일, 금액·통화, 이용 기간, 항목, 상태·사유, 환불 상태와 `evidence_changed`, `evidence_missing`만 내보냅니다. 원본 row JSON, 비공개 분류 자료, 경로, source inventory, source digest는 내보내지 않습니다.

OTA 원본에 결제일이 없으면 화면에 `미확인`으로 표시하고 카드 선택·미리 보기·확정에 사용하지 않습니다. 날짜 검색값을 결제일로 추정하거나 저장하지 않습니다. 같은 결제일의 카드 거래는 가맹점이나 금액으로 숨기지 않습니다.

제안 질문은 실제 조건의 제공자·항목·가맹점 또는 카드 식별값, signed `amount_delta_krw`, `date_lag_days`를 보여 줍니다. 예를 들어 카드 금액이 OTA 금액보다 4,000원 적은 조건이면 할인이라고 단정하지 않고 그 차이와 조건을 다음 결제에도 적용할지 묻습니다. 원화 금액이 없으면 0원이 아니라 `미확인`으로 표시합니다. 제안은 `이번 건만`, `규칙 저장`, `조건 수정`으로 답할 수 있습니다. 승인·수정 규칙에는 제공자와 항목, 그리고 가맹점 정규형 또는 카드사와 카드 끝 네 자리가 필요합니다. `amount_delta_krw`는 부호 있는 정수이며 -10000부터 10000까지 허용합니다. 예를 들어 카드 275013원에서 OTA 279013원을 뺀 -4000원도 허용합니다. `date_lag_days`는 별도 정수로 0부터 7까지 허용합니다. 불리언, 실수, 숫자 문자열은 허용하지 않습니다.

## HTTP 경로

- `GET /api/imports/ota`: allowlist snapshot을 읽습니다.
- `POST /api/imports/ota/preview`: 선택 후보의 차이를 미리 봅니다.
- `POST /api/imports/ota/confirm`: 최신 preview를 명시적으로 확정합니다.
- `POST /api/imports/ota/proposal`: 제안에 답합니다.
- `POST /api/imports`: 기존 카드 가져오기가 성공한 뒤 새 거래 ID만 검토 adapter에 알려줍니다.

모든 POST는 로그인한 owner와 일치하는 비어 있지 않은 CSRF token이 필요합니다. stale preview는 409로 응답합니다.

## Targeted 검증

격리 체크아웃 루트에서 다음 명령만 실행합니다. 전체 회귀는 실행하지 않습니다.

```powershell
python -m unittest webapp.tests.test_ota_payment_review
python -m unittest webapp.tests.test_ota_payment_review_browser
```

브라우저 검증은 로컬 합성 HTTP server와 Playwright Chromium을 사용합니다. 390x844와 1440x900에서 합성 카드 12건, 승인일·매입일·승인 번호·환불 상태, 이미 연결된 거래의 선택 차단과 사유, 차이 preview, 수동 확정, 대기 제안을 확인하고 가로 넘침이 0인지 확인합니다. 별도 실 브라우저 경로는 실제 기본 adapter와 실제 검토 store로 수동 확정, 이번 건만 처리, 규칙 승인을 거친 뒤 카드 입력 DB와 source-gone GET의 검토 DB hash가 유지되는지 확인합니다. 캡처와 자료는 합성 데이터만 포함합니다.

- [모바일 합성 화면](../../../docs/ota-first-ui-mobile.png)
- [데스크톱 합성 화면](../../../docs/ota-first-ui-desktop.png)
