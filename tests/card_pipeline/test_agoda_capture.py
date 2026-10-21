"""수집 원문·실제 결제일·식별자·반복 적재를 합성 자료로 확인한다."""
import copy
import json

import pytest

from app.agoda_capture import CaptureStore, parse_detail
from app.ota_payments import _portal_events, pair_check
from app.ota_portal import collect_portal_facts


def capture(booking='1234567890', **changes):
    text = f'''- text: "투숙 완료 예약 번호: {booking} 참조 코드: 1111111111"
- text: "체크인 2026년 8월 1일 토요일 15:00 1박 체크아웃 2026년 8월 2일 일요일 11:00"
- heading "결제 정보" [level=5]
- text: "객실 1개 x 1박 KRW 25,000 세금 및 봉사료 KRW 5,000 오늘 결제됨 KRW 30,000"
- text: "총 금액 KRW 30,000 세금 및 제반요금 포함"
- heading "결제 방법" [level=6]
- text: "카드 종류 MasterCard 카드 번호•••• •••• •••• 1234"
'''
    value = {'schema_version': 'agoda-aside-capture-v1', 'kind': 'detail',
             'account_key': 'aside-u0', 'booking_number': booking,
             'observed_at': '2026-10-20T08:00:00Z', 'list_status': 'completed', 'list_page': 1,
             'entry_proof': {'booking_number': booking, 'button_name': '예약 확인/변경하기 ' + booking},
             'snapshot_text': text}
    value.update(changes)
    return value


def test_explicit_charge_without_date_never_uses_capture_day_and_is_stable(tmp_path):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    item = capture()
    try:
        fact = parse_detail(item)
        assert fact['paid_on'] is None and fact['payment_status'] == 'paid'
        assert store.ingest(item)
        before = store.summary()
        assert not store.ingest({**item, 'observed_at': '2026-10-21T08:00:00Z'})
        assert store.summary() == before
        events = _portal_events([store.path])
        assert len(events) == 1 and events[0]['paid_on'] is None
        assert pair_check(events[0], {'transaction_direction': 'purchase'}) == 'payment_date_unknown'
        assert 'aside-v1:' in events[0]['source_ids'][0]
        assert collect_portal_facts([store.path])['rejected']['1234567890']['reason'] == 'payment_date_unknown'
    finally:
        store.close()


def test_pay_at_property_and_explicit_cancel_date_are_not_paid_ota_charges(tmp_path):
    property_capture = capture()
    property_capture['snapshot_text'] = property_capture['snapshot_text'].replace(
        '오늘 결제됨 KRW 30,000', '체크인 시 Example Hotel에서 결제 KRW 30,000')
    fact = parse_detail(property_capture)
    assert fact['payment_status'] == 'pay_at_property'
    assert [p['minor_units'] for p in fact['price_components'] if p['kind']=='property_due'] == [30000]
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        store.ingest(property_capture)
        assert _portal_events([store.path]) == []
    finally:
        store.close()
    cancelled = capture()
    cancelled['snapshot_text'] = cancelled['snapshot_text'].replace('투숙 완료', '예약 취소일: 2026년 7월 31일')
    fact = parse_detail(cancelled)
    assert fact['reservation_status'] == 'cancelled' and fact['refund_status'] == 'none_displayed'
    policy = capture()
    policy['snapshot_text'] += '- text: "예약 취소 시 예약 금액의 100%가 부과됩니다"\n'
    assert parse_detail(policy)['reservation_status'] == 'completed'


def test_cash_only_usage_and_gel_property_amount_remain_separate_from_card_payment():
    from app.ota_cash_use import agoda_cash_use
    raw = capture()
    raw['snapshot_text'] = raw['snapshot_text'].replace('오늘 결제됨 KRW 30,000', 'AgodaCash-KRW 30,000').replace(
        '총 금액 KRW 30,000', '총 금액 KRW 0').replace('카드 종류 MasterCard 카드 번호•••• •••• •••• 1234', '')
    fact = parse_detail(raw)
    assert fact['payment_status'] == 'cash_only' and fact['card_last4'] is None
    assert agoda_cash_use(fact)['cash_krw'] == 30000
    assert not any(c['kind']=='paid_today' for c in fact['price_components'])
    zero_card = {**raw, 'snapshot_text':raw['snapshot_text'].replace(
        'AgodaCash-KRW 30,000', 'AgodaCash-KRW 30,000 오늘 결제됨 KRW 0')}
    assert parse_detail(zero_card)['payment_status'] == 'cash_only'
    property_raw = capture()
    property_raw['snapshot_text'] = property_raw['snapshot_text'].replace(
        '오늘 결제됨 KRW 30,000', '체크인 시 Example Hotel에서 결제 GEL 396.00')
    fact = parse_detail(property_raw)
    assert fact['payment_status'] == 'pay_at_property'
    component = next(c for c in fact['price_components'] if c['kind']=='property_due')
    assert component['currency'] == 'GEL' and component['minor_units'] == 39600


def test_expected_card_refund_is_pending_and_never_a_completed_refund(tmp_path):
    raw = capture()
    raw['snapshot_text'] = raw['snapshot_text'].replace('투숙 완료', '예약 취소됨').replace(
        '총 금액 KRW 30,000', '신용카드 환불 KRW 30,000 환불될 금액 KRW 30,000')
    fact = parse_detail(raw)
    assert fact['refund_status'] == 'refund_pending'
    assert next(c for c in fact['price_components'] if c['kind']=='refund_expected')['minor_units'] == 30000
    zero = {**raw, 'snapshot_text':raw['snapshot_text'].replace('환불될 금액 KRW 30,000', '환불될 금액 KRW 0')}
    assert parse_detail(zero)['refund_status'] == 'refund_expected_zero'
    store = CaptureStore(tmp_path / 'refund.sqlite')
    try:
        store.ingest(raw)
        assert _portal_events([store.path]) == []
    finally:
        store.close()


def test_paid_claim_without_card_is_preserved_but_never_becomes_a_card_payment(tmp_path):
    raw = capture()
    raw['snapshot_text'] = raw['snapshot_text'].replace('카드 종류 MasterCard 카드 번호•••• •••• •••• 1234', '')
    fact = parse_detail(raw)
    assert fact['payment_status'] == 'paid_observed_without_card'
    assert fact['portal_payment_state'] == 'paid_observed'
    assert 'card_observation_missing' in fact['diagnostics']
    assert next(c for c in fact['price_components'] if c['kind']=='paid_today')['minor_units'] == 30000
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        store.ingest(raw)
        assert _portal_events([store.path]) == []
    finally:
        store.close()


def test_upcoming_header_without_colon_and_failed_payment_deadline_are_separate_facts(tmp_path):
    raw = capture()
    raw['snapshot_text'] = raw['snapshot_text'].replace(
        '투숙 완료 예약 번호: 1234567890 참조 코드: 1111111111',
        '고객님의 예약은  확정되었으며 결제가 성공적으로 처리되었습니다 예약 번호 1234567890 '
        '숙박 날짜 2026년 10월 23일 금요일 - 2026년 10월 24일 토요일 객실 1')
    labelled = '- text: "체크인 2026년 8월 1일 토요일 15:00 1박 체크아웃 2026년 8월 2일 일요일 11:00"\n'
    raw['snapshot_text'] = raw['snapshot_text'].replace(labelled, '')
    fact = parse_detail(raw)
    assert fact['reservation_status'] == 'confirmed'
    assert (fact['service_start_on'], fact['service_end_on']) == ('2026-10-23', '2026-10-24')
    failed = {**raw, 'snapshot_text':raw['snapshot_text'] + '- text: "[결제 관련 문제 발생] 신용카드 결제 거부 문제. '
        '예약이 취소되지 않도록 10월 21일 21:43 전에 본 예약에 대한 결제를 완료하시기 바랍니다."\n'}
    fact = parse_detail(failed)
    assert fact['reservation_status'] == 'confirmed' and fact['payment_status'] == 'failed'
    assert fact['payment_deadline_display'] == '10월 21일 21:43'
    store = CaptureStore(tmp_path / 'failed.sqlite')
    try:
        store.ingest(failed)
        assert _portal_events([store.path]) == []
    finally:
        store.close()
    conflicting = {**raw, 'snapshot_text':raw['snapshot_text'] + labelled}
    assert parse_detail(conflicting)['service_start_on'] is None
    assert 'service_period_conflict' in parse_detail(conflicting)['diagnostics']


@pytest.mark.parametrize('changes', [
    {'entry_proof': {'booking_number': '1234567890', 'button_name': '아고다 고객센터에 연락하기'}},
    {'snapshot_text': '- text: "예약 번호: 9999999999"'},
    {'account_key': 'other-account'},
])
def test_wrong_button_identity_or_account_cannot_be_inserted(tmp_path, changes):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        with pytest.raises(ValueError): store.ingest(capture(**changes))
        assert store.summary()['bookings'] == 0
    finally:
        store.close()


def test_new_observations_keep_event_identity_and_conflicting_amount_is_held(tmp_path):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        original = capture()
        store.ingest(original)
        identity = _portal_events([store.path])[0]['ota_event_id']
        enriched = copy.deepcopy(original)
        enriched['observed_at'] = '2026-10-21T08:00:00Z'
        enriched['snapshot_text'] += '- text: "결제일 2026년 7월 1일"\n'
        # The date belongs to the payment section; a date elsewhere is not a paid date.
        store.ingest(enriched)
        assert _portal_events([store.path])[0]['ota_event_id'] == identity
        changed = {**original, 'observed_at': '2026-10-22T08:00:00Z',
                   'snapshot_text': original['snapshot_text'].replace('30,000', '31,000')}
        store.ingest(changed)
        assert store.summary()['source_observations'] == 3
        assert store.summary()['conflicting_bookings'] == 1
        assert _portal_events([store.path]) == []
    finally:
        store.close()


def test_progression_and_late_file_do_not_restore_old_reservation_state(tmp_path):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        done = capture()
        old = {**done, 'observed_at': '2026-10-19T08:00:00Z',
               'snapshot_text': done['snapshot_text'].replace('투숙 완료', '예약은 확정되었습니다')}
        store.ingest(done)
        store.ingest(old)
        row = store.conn.execute('SELECT status FROM bookings').fetchone()
        assert row[0] == 'completed' and store.summary()['conflicting_bookings'] == 0
        cancelled = {**done, 'observed_at': '2026-10-21T08:00:00Z',
                     'snapshot_text': done['snapshot_text'].replace('투숙 완료', '예약이 취소되었습니다')}
        store.ingest(cancelled)
        assert store.conn.execute('SELECT status FROM bookings').fetchone()[0] == 'cancelled'
        assert store.summary()['source_observations'] == 3
    finally:
        store.close()


def test_list_records_no_year_and_requires_exact_list_members(tmp_path):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    page = {'schema_version': 'agoda-aside-capture-v1', 'kind': 'list', 'account_key': 'aside-u0',
            'observed_at': '2026-10-20T08:00:00Z', 'list_status': 'completed', 'list_page': 1,
            'snapshot_text': '- heading "ID 1234567890" [level=2]\n- text: "10월 18일"',
            'booking_numbers': ['1234567890'], 'next_disabled': True}
    try:
        store.ingest(page, run_id='synthetic')
        assert store.conn.execute('SELECT service_start_on FROM bookings').fetchone()[0] is None
        with pytest.raises(ValueError): store.ingest({**page, 'booking_numbers': []})
    finally:
        store.close()


def test_mail_join_is_repeatable_and_same_id_changed_content_is_rolled_back(tmp_path):
    from tests.card_pipeline.test_booking_mail import message
    directory = tmp_path / 'mail'
    directory.mkdir()
    path = directory / 'gmail-synthetic.json'
    mail = message('예약 번호: 1234567890\n총 금액 KRW 30,000',
                   subject='결제가 완료되었습니다', domain='agoda.com')
    path.write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        assert store.ingest_mail([directory]) == 1
        store.ingest(capture())
        baseline = store.summary()
        assert baseline['booking_mail_links'] == 1
        assert store.ingest_mail([directory]) == 0
        assert store.summary() == baseline
        mail['payload']['body']['content'] += '\n다른 원문'
        path.write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
        with pytest.raises(ValueError, match='MAIL_CONTENT_CONFLICT'):
            store.ingest_mail([directory])
        assert store.summary() == baseline
    finally:
        store.close()


@pytest.mark.parametrize('replacement', ['KRW 1,23', 'KRW 30,000.5'])
def test_invalid_or_fractional_won_is_not_verified(replacement):
    item = capture()
    item['snapshot_text'] = item['snapshot_text'].replace('KRW 30,000', replacement)
    if replacement.endswith('.5'):
        with pytest.raises(ValueError, match='INVALID_MONEY'): parse_detail(item)
    else:
        assert parse_detail(item)['payment_status'] == 'unknown'


def test_interactive_only_snapshot_cannot_be_published_as_complete_evidence(tmp_path):
    store = CaptureStore(tmp_path / 'capture.sqlite')
    try:
        item = capture()
        item['snapshot_text'] = '# note: interactive (clickable / focusable) elements only.\n' + item['snapshot_text']
        with pytest.raises(ValueError, match='FULL_SNAPSHOT_REQUIRED'): store.ingest(item)
        assert store.summary()['bookings'] == 0
    finally:
        store.close()
