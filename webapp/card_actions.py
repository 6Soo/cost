"""카드 거래의 실제 다음 행동을 같은 기준으로 표시한다."""
from urllib.parse import urlencode
from app import quarter_costs


def next_action(row, preview=None, extra_hold=None):
    preview = preview or {}
    href = '/import?' + urlencode({'batch': row['batch_id'], 'transaction': row['transaction_id']})
    def action(status, label, reason='', required=True, target=None):
        return dict(status=status, label=label, reason=reason, required=required, href=target or href)
    if preview.get('already_booked') or row.get('classification_state') == 'booked':
        return action('기록 완료', '장부 보기', required=False,
                      target='/board?' + urlencode({'tab': row.get('display_tab_id') or 'unclassified',
                                                    'row': 'card-' + row['transaction_id']}))
    if row.get('duplicate_of'):
        return action('중복 제외', '중복 내역 확인', '같은 거래가 이미 있어 추가로 기록하지 않습니다.', False)
    if row.get('company_excluded') or preview.get('excluded_from_company'):
        return action('회사 경비 제외', '제외 내역 보기', required=False)
    if row.get('trip_name') == '환불':
        return action('전액 환불', '환불 보기', required=False, target='/board?tab=refunds')
    if row.get('conflict_reason') or row.get('parse_error'):
        return action('원본 확인 필요', '원본 확인', row.get('conflict_reason') or row.get('parse_error'))
    hold = row.get('review_hold') or preview.get('review_hold') or extra_hold
    if hold and hold.get('kind') == 'existing_ledger':
        return action('기존 기록', '장부 보기', hold['reason'], False,
                      '/board?' + urlencode({'tab': row.get('display_tab_id') or 'unclassified'}))
    if hold and hold.get('kind') not in ('trip_needed', 'classification_needed'):
        return action('보류 중', '보류 사유 확인', hold.get('reason') or '예약과 결제 근거를 확인해 주세요.')
    if not row.get('item'):
        return action('비용 항목 선택 필요', '비용 항목 선택', '이 거래의 비용 항목을 선택해 주세요.')
    if row.get('display_tab_id') in (None, '', 'unclassified') and not quarter_costs.destination(row):
        return action('여행 지정 필요', '여행 지정', '예약 이용일과 숙소를 확인하고 여행을 선택해 주세요.')
    if preview.get('blocked'):
        return action('확인 필요', '문제 확인', preview.get('reason') or '배정 내용을 확인해 주세요.')
    if row.get('classification_state') not in ('classified', 'confirmed'):
        return action('분류 확인 필요', '분류 확인', '비용 항목과 배정 내용을 확인해 주세요.')
    return action('자동 반영 대기', '처리 결과 확인', required=False)
