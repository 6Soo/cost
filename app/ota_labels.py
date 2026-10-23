"""Shared OTA display labels; no I/O or reconciliation decisions."""

OTA_STATUS = {
    'HOLD_NO_CARD': '맞는 카드 거래 없음', 'HOLD_AMOUNT_MISMATCH': '금액이 다른 카드 거래만 있음',
    'HOLD_DATE_UNKNOWN': '결제일 미확인', 'HOLD_AMBIGUOUS': '후보 거래가 여러 건',
    'HOLD_PARTIAL_GROUP': '부분 묶음', 'HOLD_EVIDENCE_CONFLICT': '근거 충돌',
    'PENDING_PAYMENT': '결제 대기', 'NOT_CARD_CHARGE': '카드 결제 아님',
}
OTA_REASON = {
    'payment_date_not_in_source': 'OTA 결제일이 원본에 없어 결제 연결을 확정하지 않았습니다.',
    'AMOUNT_MISMATCH': '카드 정보는 일부 맞지만 결제 금액이 다릅니다.',
    'CURRENCY_MISMATCH': '카드 정보는 일부 맞지만 결제 통화가 다릅니다.',
    'no_exact_amount_date_direction_card': '결제 금액·날짜·방향이 모두 맞는 카드 거래가 없습니다',
    'amount_differs': '같은 날짜의 카드 거래는 있지만 금액이 다릅니다',
    'exact_card_needs_descriptor_approval': '금액·날짜가 같은 카드 거래는 있으나 가맹점 별칭이 승인되지 않아 연결하지 않았습니다',
}
