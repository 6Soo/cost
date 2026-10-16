"""같은 결제일·금액의 숙박 결제 묶음은 예약번호를 고르지 않고 공통 이용기간만 제안한다."""
import datetime
import json
from decimal import Decimal
from email.utils import format_datetime

from app.ota_mail import match_mail, shared_lodging_stay

STAY = ('2026-07-22', '2026-07-25')


def paid_message(ref, *, stay=STAY, amount=48000, sent='2026-05-01', subject='결제가 완료되었습니다', identity=None):
    when = datetime.datetime.fromisoformat(sent + 'T12:00:00+09:00')
    body = f'예약번호: {ref}\n총 금액 KRW {amount:,}\n체크인: {stay[0]}\n체크아웃: {stay[1]}'
    return {'id': identity or ref, 'internal_date': str(int(when.timestamp() * 1000)),
            'payload': {'headers': [{'name': 'From', 'value': 'noreply@agoda.com'},
                                    {'name': 'Subject', 'value': subject},
                                    {'name': 'Date', 'value': format_datetime(when)},
                                    {'name': 'Authentication-Results', 'value': 'mx.google.com; dkim=pass header.i=@agoda.com'}],
                        'mime_type': 'text/plain', 'body': {'content': body}, 'parts': None}}


def row(tid, amount=48000, day='2026-05-01'):
    return dict(transaction_id=tid, source_hash=tid * 64, merchant='AGODA_NICE-Agoda', merchant_normalized='아고다',
                approval_date=day, transaction_direction='purchase', amount_krw=amount, card_kind='국내')


def write(tmp_path, messages):
    (tmp_path / 'gmail-synthetic.json').write_text(json.dumps({'responses': messages}), encoding='utf-8')


def fact(ref, **changes):
    base = dict(provider='agoda', booking_ref=ref, paid=True, cancelled=False, paid_on=datetime.date(2026, 5, 1),
                period=dict(starts_on=STAY[0], ends_on=STAY[1]), amounts={('KRW', Decimal('48000'))},
                source_sha256=ref * 64)
    base.update(changes)
    return base


def test_same_day_and_amount_bookings_with_one_stay_suggest_the_shared_period_without_a_booking_number(tmp_path):
    write(tmp_path, [paid_message('1738864710'), paid_message('1738864711')])
    result = match_mail(tmp_path, [row('a'), row('b')])
    assert result['exact_matches'] == 0
    assert len(result['type_only_candidates']) == 2
    for candidate in result['type_only_candidates']:
        assert candidate['shared_period'] == dict(starts_on=STAY[0], ends_on=STAY[1])
        assert candidate['booking_count'] == 2
        assert candidate['item'] == '숙박비'
        assert 'booking_ref' not in candidate


def test_different_stays_on_the_same_day_are_not_grouped(tmp_path):
    write(tmp_path, [paid_message('1738864710'), paid_message('1738864711', stay=('2026-08-01', '2026-08-02'))])
    assert match_mail(tmp_path, [row('a'), row('b')])['type_only_candidates'] == []


def test_more_payments_than_bookings_do_not_share_a_period(tmp_path):
    write(tmp_path, [paid_message('1738864710'), paid_message('1738864711')])
    assert match_mail(tmp_path, [row('a'), row('b'), row('c')])['type_only_candidates'] == []


def test_a_same_amount_cancellation_on_another_date_blocks_the_group(tmp_path):
    cancel = paid_message('1738864799', subject='예약 취소 완료', sent='2026-06-01', identity='cancel')
    write(tmp_path, [paid_message('1738864710'), paid_message('1738864711'), cancel])
    assert match_mail(tmp_path, [row('a'), row('b')])['type_only_candidates'] == []


def test_a_single_booking_keeps_the_exact_path(tmp_path):
    write(tmp_path, [paid_message('1738864710')])
    result = match_mail(tmp_path, [row('a')])
    assert result['exact_matches'] == 1
    assert result['type_only_candidates'] == []


def test_shared_stay_ignores_scheduled_charges_and_other_providers():
    facts = [fact('a'), fact('b', paid=False, evidence_kind='scheduled_charge')]
    result = shared_lodging_stay(facts, provider='agoda', paid_on=datetime.date(2026, 5, 1), amount_krw=48000)
    assert result['booking_count'] == 1
    assert shared_lodging_stay([fact('a', provider='booking')], provider='agoda',
                               paid_on=datetime.date(2026, 5, 1), amount_krw=48000) is None


def test_shared_stay_is_refused_for_a_cancelled_candidate_with_the_same_amount():
    facts = [fact('a'), fact('b'), fact('c', paid=False, cancelled=True, paid_on=datetime.date(2026, 6, 1))]
    assert shared_lodging_stay(facts, provider='agoda', paid_on=datetime.date(2026, 5, 1), amount_krw=48000) is None
