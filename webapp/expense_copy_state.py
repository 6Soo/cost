"""Safe, shared explanations for a blocked expense export."""

RETRY_WITH_BUTTONS = '장부 동기화 후 다시 확인해 주세요. 같으면 Google 시트에 이 여행 탭이 있는지 확인해 주세요.'
RETRY_NEUTRAL = '잠시 뒤 다시 열어 주세요. 같으면 Google 시트에 이 여행 탭이 있는지 확인해 주세요.'


def source_message(reason, actions=False):
    """`actions` is True only where the 장부 동기화 / 다시 확인 buttons are rendered."""
    retry = RETRY_WITH_BUTTONS if actions else RETRY_NEUTRAL
    return {
        'SOURCE_EXPENSE_TOTAL_MISMATCH': 'Google 시트의 지출 합계와 행 합계가 다릅니다. 원본의 지출 합계 수식과 범위를 확인해 주세요.',
        'SOURCE_EXPENSE_UNVERIFIED': 'Google 시트의 지출 금액 또는 합계 수식을 검증하지 못했습니다. 원본의 지출 금액과 수식을 확인해 주세요.',
        'SOURCE_LAYOUT_UNSUPPORTED': '이 여행의 Google 시트는 표준 지출 양식이 아닙니다. 원본을 표준 지출 양식으로 정리해 주세요.',
        'TRIP_MAPPING_UNAVAILABLE': '이 여행의 Google 장부 연결을 확인하지 못했습니다. ' + retry,
        'SOURCE_NOT_SELECTED': '이 여행의 Google 원본을 찾지 못했습니다. ' + retry,
        'SOURCE_NOT_VERIFIED': 'Google 원본이 최신 상태가 아니거나 확인이 필요합니다. ' + retry,
    }.get(reason, 'Google 장부를 불러오지 못해 중복 여부를 확인할 수 없습니다. ' + retry)
