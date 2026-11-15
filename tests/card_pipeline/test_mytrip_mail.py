from app import mail_collect, mytrip_mail


def message(subject, body, sender='no-reply@support.kr.mytrip.com', date='Wed, 19 Aug 2026 13:49:53 +0000'):
    return mail_collect.owner_record('synthetic', {'From': sender, 'Subject': subject, 'Date': date}, body)


def confirmed(order='1111-222-333', total='224,682.00', legs=('2026년9월18일',), **values):
    body = ''.join(f'가는 편 • {leg}\n' for leg in legs * 2)
    return message(f'여행이 확정되었습니다. 주문 번호 {order}',
                   f'예약이 확인되었습니다!\n주문 번호\n {order} \n{body}합계\n  {total} KRW\n', **values)


def test_a_confirmation_is_a_reservation_with_its_flight_dates_and_total():
    [event] = mytrip_mail.collect({'m1': confirmed(legs=('2026년9월18일', '2026년9월21일'))})
    assert (event['provider'], event['booking_ref'], event['event_type']) == ('gotogate', '1111-222-333', 'reservation')
    assert event['service_period'] == {'starts_on': '2026-09-18', 'ends_on': '2026-09-21'}
    assert event['amount_krw'] == 224682 and event['paid_on'] is None and event['reservation_status'] == 'observed'
    assert event['reservation_observed_on'] == ['2026-08-19']


def test_a_withdrawal_mail_naming_the_order_marks_it_cancelled():
    refund = message('[No Reply] 환불 영수증', '주문 1111-222-333 환불')
    [event] = mytrip_mail.collect({'m1': confirmed(), 'm2': refund})
    assert event['reservation_status'] == 'cancelled'


def test_untrusted_or_unreadable_mails_are_ignored():
    assert mytrip_mail.collect({'m1': confirmed(sender='no-reply@mytrip.com.example')}) == []
    assert mytrip_mail.collect({'m1': confirmed(total='224,682.00 USD')}) == []
    assert mytrip_mail.collect({'m1': message('여행이 확정되었습니다. 주문 번호 1111-222-333', '합계 5,000.00 KRW')}) == []
    assert mytrip_mail.collect({'m1': message('여행이 확정되었습니다. 주문 번호 1111-222-333',
                                              '1111-222-444 가는 편 • 2026년9월18일 합계 5,000.00 KRW')}) == []


def test_two_confirmations_with_different_totals_conflict():
    [event] = mytrip_mail.collect({'m1': confirmed(), 'm2': confirmed(total='230,000.00')})
    assert event['service_period'] is None and event['service_period_conflict'] is True and event['amount_krw'] is None
