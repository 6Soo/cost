"""Shared OTA display labels; no I/O or reconciliation decisions."""

OTA_STATUS = {
    'RESERVATION_ONLY': '예약 근거 · 결제 연결 미확정',
    'HOLD_NO_CARD': '맞는 카드 거래 없음', 'HOLD_AMOUNT_MISMATCH': '금액이 다른 카드 거래만 있음',
    'HOLD_AMOUNT_UNVERIFIED': '금액 대조 근거 부족 · 연결 보류',
    'HOLD_DATE_UNKNOWN': '결제일 미확인', 'HOLD_AMBIGUOUS': '후보 거래가 여러 건',
    'HOLD_PARTIAL_GROUP': '부분 묶음', 'HOLD_EVIDENCE_CONFLICT': '근거 충돌',
    'PENDING_PAYMENT': '결제 대기', 'NOT_CARD_CHARGE': '카드 결제 아님',
}
OTA_REASON = {
    'no_verified_paid_evidence': '예약 확인·이용일·동액만으로 결제를 확정할 수 없습니다. 예약번호가 명시된 인증 결제 완료 근거와 카드 결제 대조가 필요합니다.',
    'RESERVATION_CANCELLED': '동일 호텔·예약번호에 취소 이력이 있어 연결을 보류합니다.',
    'payment_date_not_in_source': 'OTA 결제일이 원본에 없어 결제 연결을 확정하지 않았습니다.',
    'AMOUNT_MISMATCH': '카드 정보는 일부 맞지만 결제 금액이 다릅니다.',
    'CURRENCY_MISMATCH': '카드 정보는 일부 맞지만 결제 통화가 다릅니다.',
    'FX_EVIDENCE_REQUIRED': '카드 원화 청구액과 OTA 외화금액은 직접 비교할 수 없습니다. 카드사의 같은 통화 원금 또는 해당 결제의 검증된 원화 청구 근거가 필요합니다. 추정 환율만으로 연결하지 않습니다.',
    'AMOUNT_EVIDENCE_REQUIRED': '비교 가능한 원본 결제 금액이 없어 연결을 보류합니다. 카드사 청구 내역과 OTA 결제 완료 금액을 확인하세요.',
    'unique_exact_evidence': '결제 완료 근거·카드 금액·결제일과 전역 유일성이 검증된 연결입니다. 여행 배정은 예약 이용기간과 등록 여행을 별도로 대조합니다.',
    'pinned_existing_link': '기존에 저장한 결제 연결을 유지합니다. 여행 배정은 별도입니다.',
    'equal_optimum_global_singleton_allocations': '같은 조건의 카드나 예약이 여러 건이라 개별 결제를 구분할 수 없습니다. 예약별 결제번호 또는 카드 승인 근거가 필요합니다.',
    'global_one_to_one_collision': '카드와 예약의 대응이 유일하지 않습니다. 예약별 결제번호 또는 카드 승인 근거를 확인하세요.',
    'no_exact_amount_date_direction_card': '결제 금액·날짜·방향이 모두 맞는 카드 거래가 없습니다',
    'amount_differs': '같은 날짜의 카드 거래는 있지만 금액이 다릅니다',
    'exact_card_needs_descriptor_approval': '금액·날짜가 같은 카드 거래는 있으나 가맹점 별칭이 승인되지 않아 연결하지 않았습니다',
}
