"""Card detail information, independent of the retired human action queue."""
from urllib.parse import urlencode

GROUP_LABELS = {'booked': '완료', 'excluded': '제외'}
GROUP_OF_STATUS = {'기록 완료': 'booked', '기존 기록': 'booked',
                   '중복 제외': 'excluded', '회사 경비 제외': 'excluded', '전액 환불': 'excluded'}
REASON_LABELS = {'evidence': '원본 정보', 'finance': '결제·환불 정보'}


def reason_category(row, preview=None, hold=None):
    preview = preview or {}
    if (row.get('transaction_direction') in ('refund', 'cancellation')
            or str(preview.get('blocked') or '').startswith('refund_')):
        return 'finance'
    return 'evidence' if row.get('parse_error') or row.get('conflict_reason') or preview.get('blocked') else ''


def next_action(row, preview=None, extra_hold=None, *, user_action_required=None):
    """Describe existing facts, never require a classification answer.

    The old user_action_required argument is ignored. Financial preview/commit
    protection remains authoritative and is never relaxed by this projection.
    """
    preview = preview or {}
    href = '/import?' + urlencode({'batch': row['batch_id'], 'transaction': row['transaction_id']})

    def info(status='', label='거래 상세', reason='', target=None, protection=''):
        from app.classification_provenance import origin, LABELS
        group = GROUP_OF_STATUS.get(status, '')
        return dict(status=status, label=label, reason=reason, required=False,
                    href=target or href, group=group, state=group,
                    state_label=GROUP_LABELS.get(group, status),
                    reason_category=reason_category(row, preview, extra_hold), reason_label='',
                    protection=protection, source=origin(row), source_label=LABELS[origin(row)])

    if preview.get('already_booked'):
        return info('기록 완료', '장부 보기', target='/board?' + urlencode({
            'tab':row.get('display_tab_id') or '', 'row':'card-' + row['transaction_id']}))
    if row.get('duplicate_of'):
        return info('중복 제외', reason='같은 원거래는 한 번만 집계합니다.', protection='duplicate')
    if row.get('company_excluded') or preview.get('excluded_from_company'):
        return info('회사 경비 제외')
    if row.get('conflict_reason') or row.get('parse_error'):
        return info('원본 오류', reason='원본 값의 오류로 금융 기록에 반영하지 않습니다.', protection='source_conflict')
    blocked = str(preview.get('blocked') or '')
    refund_link = preview.get('refund_link') or {}
    refund_basis = str(refund_link.get('basis') or '')
    refund_inferred = (bool(refund_link.get('inferred')) or refund_basis.endswith('_inferred')
                       or blocked == 'refund_inferred')
    refund_net = refund_link.get('net_krw', preview.get('net_krw'))
    if refund_inferred:
        balance = f"순액 {int(refund_net):,}원" if refund_net is not None else '순액 미확인'
        return info('환불 추론 연결', '환불 내역',
                    reason=f'저장된 연결은 추론 상태입니다 · {balance} · 기록 전 근거 확인이 필요합니다.',
                    target='/board?tab=refunds', protection=blocked or 'refund_inferred')
    if blocked == 'refund_exceeds_original':
        return info('환불 금액 불일치', reason='환불 합계가 원결제 금액을 초과합니다.', target=href+'#preview', protection=blocked)
    if blocked.startswith('refund_'):
        balance = f"순액 {int(refund_net):,}원" if refund_net is not None else '순액 미확인'
        return info('환불 연결 근거', '환불 기록 확인',
                    reason=f'원결제·취소 관계와 실제 환급은 별개의 정보입니다 · {balance}.',
                    target=href+'#preview', protection=blocked)
    if (row.get('trip_name') == '환불' and refund_link.get('status') == 'full'
            and refund_net == 0 and not blocked):
        return info('전액 환불', '환불 내역', target='/board?tab=refunds')
    if row.get('trip_name') == '환불':
        balance = f"순액 {int(refund_net):,}원" if refund_net is not None else '순액 미확인'
        return info('환불 상태 확인', '환불 내역',
                    reason=f'환불 연결 상태와 순액을 확인할 수 없습니다 · {balance}.',
                    target='/board?tab=refunds', protection=blocked)
    hold = row.get('review_hold') or preview.get('review_hold') or extra_hold or {}
    if hold.get('kind') == 'existing_ledger':
        return info('기존 기록', '장부 보기', target='/board?' + urlencode({'tab':row.get('display_tab_id') or ''}))
    if blocked:
        return info('원본 정보', reason='금융 기록의 원본 보호 조건이 적용됩니다.', protection=blocked)
    return info()
