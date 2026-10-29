"""카드 거래의 실제 다음 행동을 같은 기준으로 표시한다."""
from urllib.parse import urlencode
from app import quarter_costs


#: The visible states a person sees for a card row, whichever screen shows it.
GROUP_LABELS = {'review': '확인 필요', 'booked': '기록 완료', 'excluded': '기록 제외'}
GROUP_OF_STATUS = {'기록 완료': 'booked', '기존 기록': 'booked',
                   '기록 준비': 'booked', '중복 제외': 'excluded',
                   '회사 경비 제외': 'excluded', '전액 환불': 'excluded'}


def next_action(row, preview=None, extra_hold=None):
    preview = preview or {}
    href = '/import?' + urlencode({'batch': row['batch_id'], 'transaction': row['transaction_id']})
    def action(status, label, reason='', required=True, target=None):
        result = dict(status=status, label=label, reason=reason, required=required, href=target or href)
        group = GROUP_OF_STATUS.get(status, 'review' if required else None)
        if group:
            result['group'] = group
        return result
    if preview.get('already_booked'):
        return action('기록 완료', '장부 보기', required=False,
                      target='/board?' + urlencode({'tab': row.get('display_tab_id') or 'unclassified',
                                                    'row': 'card-' + row['transaction_id']}))
    if row.get('duplicate_of'):
        return action('중복 제외', '중복 내역 확인', '같은 거래가 이미 있어 추가로 기록하지 않습니다.', False)
    if row.get('company_excluded') or preview.get('excluded_from_company'):
        return action('회사 경비 제외', '제외 내역 보기', required=False)
    if row.get('conflict_reason') or row.get('parse_error'):
        return action('원본 확인 필요', '원본 확인', row.get('conflict_reason') or row.get('parse_error'))
    if (preview.get('refund_link') or {}).get('basis', '').endswith('_inferred') and not preview.get('blocked'):
        return action('기록 준비', '자동 기록 대기',
                      '동일 카드·동액의 유일한 원결제와 연결되어 자동 기록할 수 있습니다. 실제 환급 완료 여부는 별도입니다.',
                      required=False, target=href + '#preview')
    if preview.get('blocked') == 'refund_inferred':
        return action('환불 추론 연결', '환불 근거 확인',
                      preview.get('reason') or '원결제 추론 연결은 별도 근거 검증 전 장부 기록을 보류합니다. 환급 완료 아님.',
                      target=href + '#preview')
    if row.get('trip_name') == '환불':
        return action('전액 환불', '환불 보기', required=False, target='/board?tab=refunds')
    if preview.get('blocked') in ('refund_pair_partially_booked', 'refund_original_missing', 'refund_pair_incomplete', 'refund_pair_mismatch', 'refund_exceeds_original'):
        return action('환불 기록 확인 필요', '환불 기록 확인',
                      '원결제와 환불의 기록 상태를 함께 확인해 주세요. 일부만 기록돼 있거나 서로 맞지 않아 자동 반영하지 않습니다.',
                      target=href + '#preview')
    hold = row.get('review_hold') or preview.get('review_hold') or extra_hold
    if hold and hold.get('kind') == 'existing_ledger':
        return action('기존 기록', '장부 보기', hold['reason'], False,
                      '/board?' + urlencode({'tab': row.get('display_tab_id') or 'unclassified'}))
    if hold and hold.get('kind') not in ('trip_needed', 'classification_needed'):
        if 'OTA-first' in (hold.get('reason') or ''):
            return action('예약 연결 확인 필요', '예약 연결 확인',
                          '이 결제가 어느 예약인지 아직 확인되지 않았습니다. 예약번호와 이용일을 확인해 주세요.', target=href + '#ota-review')
        return action('확인 필요', '사유 확인', hold.get('reason') or '예약과 결제 근거를 확인해 주세요.')
    if not row.get('item'):
        return action('비용 항목 선택 필요', '비용 항목 선택', '이 거래의 비용 항목을 선택해 주세요.')
    if row.get('display_tab_id') in (None, '', 'unclassified') and not quarter_costs.destination(row):
        return action('여행 지정 필요', '여행 지정', '예약 이용일과 숙소를 확인하고 여행을 선택해 주세요.')
    if preview.get('blocked'):
        return action('확인 필요', '문제 확인', preview.get('reason') or '배정 내용을 확인해 주세요.')
    if row.get('classification_state') not in ('classified',):
        return action('분류 확인 필요', '분류 확인', '비용 항목과 배정 내용을 확인해 주세요.')
    return action('', '처리 결과 확인', required=False)
