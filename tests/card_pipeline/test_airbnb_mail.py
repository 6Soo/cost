from app import airbnb_mail, mail_collect, ota_payments


def message(subject, body, sender='automated@airbnb.com', date='Wed, 13 May 2026 02:38:11 +0000'):
    return mail_collect.owner_record('synthetic', {'From': sender, 'Subject': subject, 'Date': date}, body)


def confirmed(code='HMSYNTH001', subject='예약 확정: 5월 16일~17일 여행에 대한 에어비앤비 영수증', **values):
    return message(subject, f'체크인 체크아웃 5월 16일 (토) 5월 17일 (일)\n확인 코드 {code}', **values)


def test_a_confirmation_is_a_reservation_with_its_stay_and_no_payment():
    [event] = airbnb_mail.collect({'m1': confirmed()})
    assert (event['provider'], event['booking_ref'], event['event_type']) == ('airbnb', 'HMSYNTH001', 'reservation')
    assert event['service_period'] == {'starts_on': '2026-05-16', 'ends_on': '2026-05-17'}
    assert event['amount_krw'] is None and event['paid_on'] is None and event['reservation_status'] == 'observed'
    [result] = ota_payments.match_ota_payment_events([event], [dict(
        transaction_id='t1', merchant='AIRBNB * HMSYNTH001', amount_krw=261401, approval_date='2026-05-12',
        transaction_direction='purchase', card_tail='8835')])
    assert result['transaction_id'] is None and result['status'] == 'NOT_CARD_CHARGE'


def test_the_subject_year_follows_the_send_date_and_crosses_month_and_year():
    [event] = airbnb_mail.collect({'m1': confirmed(subject='예약 확정 안내: 3월 2일~5일 예약',
                                                   date='Thu, 16 Jul 2026 20:12:18 +0000')})
    assert event['service_period'] == {'starts_on': '2027-03-02', 'ends_on': '2027-03-05'}
    [event] = airbnb_mail.collect({'m1': confirmed(subject='예약 확정: 12월 30일~1월 2일 여행에 대한 에어비앤비 영수증',
                                                   date='Tue, 01 Dec 2026 01:00:00 +0000')})
    assert event['service_period'] == {'starts_on': '2026-12-30', 'ends_on': '2027-01-02'}


def test_a_cancellation_mail_marks_the_same_code_cancelled():
    events = airbnb_mail.collect({'m1': confirmed(), 'm2': message('에어비앤비 예약이 취소되었습니다', '코드 HMSYNTH001')})
    assert [e['reservation_status'] for e in events] == ['cancelled']


def test_untrusted_or_ambiguous_mails_are_ignored():
    assert airbnb_mail.collect({'m1': confirmed(sender='automated@airbnb.com.example')}) == []
    assert airbnb_mail.collect({'m1': message('예약 확정: 5월 16일~17일 여행에 대한 에어비앤비 영수증',
                                              'HMSYNTH001 HMSYNTH002')}) == []
    assert airbnb_mail.collect({'m1': confirmed(subject='예약 알림 - 2026년 5월 16일')}) == []


def test_two_confirmations_with_different_stays_conflict():
    [event] = airbnb_mail.collect({'m1': confirmed(), 'm2': confirmed(
        subject='예약 확정: 5월 18일~19일 여행에 대한 에어비앤비 영수증')})
    assert event['service_period'] is None and event['service_period_conflict'] is True
