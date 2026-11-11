"""Synthetic forest portal ingestion and LINK-002 boundary checks."""
import copy
import json

import pytest

from app.forest_portal_capture import foresttrip_row, sooperang_records
from app.ota_store import OtaStore, connect_read, direct_facts
from app.ota_payments import _forest_portal_events, _attach_forest_portal_periods, pair_check
from tools.import_forest_portal_details import main, plan

OBSERVED = '2031-02-10T12:00:00+09:00'


def row():
    return {'cells':['ORDER-DEMO', '2031-02-01 결제금액12,345 원',
                     '[BOOK-DEMO] 국 가상자연휴양림 객실', '숙소(선착순)',
                     '2031-03-02~2031-03-03', '결제완료'], 'links':[]}


def test_explicit_paid_date_and_stay_are_independent():
    fact = foresttrip_row(row(), 'pay', OBSERVED)
    assert fact['paid_on'] == '2031-02-01'
    assert fact['service_start_on'] == '2031-03-02'
    assert fact['amount_krw'] == 12345
    assert fact['label'] == '가상자연휴양림'


def test_cancellation_does_not_invent_charge_or_bank_refund():
    r = row()
    r['cells'] = [r['cells'][1],r['cells'][2],r['cells'][3],r['cells'][4],'2031-02-02 취소금액12,345 원']
    fact = foresttrip_row(r, 'cancel', OBSERVED)
    assert fact['reservation_status'] == 'cancelled'
    assert fact['paid_on'] is None and fact['payment_status'] == 'unknown'
    assert fact['price_components'] == []


@pytest.mark.parametrize('value',['NaN 원','0 원','-1 원','잘못된 금액'])
def test_bad_payment_never_becomes_zero(value):
    r = row();r['cells'][1] = '2031-02-01 결제금액' + value
    with pytest.raises(ValueError):
        foresttrip_row(r, 'pay', OBSERVED)


def sooperang():
    listing = {'text':'AD99999999001가상산림치유원\n이용날짜 : 2031-03-02~2031-03-03(1박 2일)\n신청날짜 : 2031-02-01\n예약상태 : 이용완료\n결제만기일 : 2031.02.05 12:00:00까지'}
    details = [{'id':'AD99999999001','ok':True,'data':{'useAmtSmmarList':[{'rsrvtAmt':'12345'},{'rsrvtAmt':'0'}]}}]
    return listing, details


def test_application_and_deadline_are_never_paid_dates():
    listing, details = sooperang()
    _, fact = next(sooperang_records(listing, details, OBSERVED))
    assert fact['booked_on'] == '2031-02-01'
    assert fact['paid_on'] is None and fact['card_last4'] is None
    assert fact['payment_status'] == 'unknown'
    assert fact['reservation_amount_krw'] == 12345


def test_detail_requires_bound_list_identity():
    listing, details = sooperang(); details[0]['id'] = 'AD99999999002'
    with pytest.raises(ValueError, match='IDENTITY'):
        list(sooperang_records(listing, details, OBSERVED))


def test_store_to_core_preserves_exact_merchant_date_amount_boundary(tmp_path):
    store = OtaStore(tmp_path/'ota.sqlite')
    fact = foresttrip_row(row(), 'pay', OBSERVED)
    store.import_direct(provider='forest', account_key='synthetic', source_key='demo', snapshot=row(), facts=[fact])
    store.close()
    event = _forest_portal_events([str(tmp_path/'ota.sqlite')])[0]
    card = dict(merchant='가상자연휴양림', amount_krw=12345, approval_date='2031-02-01',
                transaction_direction='purchase', issuer='synthetic', card_tail='9999')
    assert pair_check(event,card) is None
    assert pair_check(event,dict(card,merchant='다른자연휴양림')) == 'provider'
    assert pair_check(event,dict(card,approval_date='2031-02-02')) == 'date'
    assert pair_check(event,dict(card,amount_krw=12346)) == 'amount'


def test_reservation_only_stays_unpaid_and_conflict_stays_blocked(tmp_path):
    listing, details = sooperang()
    _, fact = next(sooperang_records(listing, details, OBSERVED))
    store = OtaStore(tmp_path/'ota.sqlite')
    for n in range(2):
        changed = dict(fact, service_end_on='2031-03-03' if not n else '2031-03-04')
        store.import_direct(provider='forest', account_key='synthetic', source_key=str(n), snapshot=details, facts=[changed])
    store.close()
    event = _forest_portal_events([str(tmp_path/'ota.sqlite')])[0]
    assert event['evidence_status'] == 'conflict'
    assert event['event_type'] == 'reservation' and event['paid_on'] is None


def test_import_preview_append_replay_and_conflict_never_overwrite(tmp_path,capsys):
    captures = tmp_path/'capture';captures.mkdir()
    path = captures/'pay-demo.json'
    path.write_text(json.dumps({'url':'https://foresttrip.go.kr/synthetic','rows':[row()]}),encoding='utf8')
    db = tmp_path/'ota.sqlite'
    args = ['--directory',str(captures),'--store',str(db),'--observed-at',OBSERVED]
    assert main(args) == 0
    assert not db.exists()
    assert main(args+['--apply']) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['inserted'] == 1
    before = db.read_bytes()
    assert main(args+['--apply']) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['duplicate'] == 1 and summary['inserted'] == 0
    assert before == db.read_bytes()
    changed = row();changed['cells'][4] = '2031-03-04~2031-03-05'
    path.write_text(json.dumps({'url':'https://foresttrip.go.kr/synthetic','rows':[changed]}),encoding='utf8')
    assert main(args+['--apply']) == 0
    assert json.loads(capsys.readouterr().out)['conflict'] == 1
    assert before == db.read_bytes()


def test_invalid_capture_aborts_entire_batch(tmp_path,capsys):
    r = row();r['cells'][1]='bad'
    (tmp_path/'pay-demo.json').write_text(json.dumps({'url':'https://foresttrip.go.kr/synthetic','rows':[row(),r]}),encoding='utf8')
    db = tmp_path/'ota.sqlite'
    assert main(['--directory',str(tmp_path),'--store',str(db),'--observed-at',OBSERVED,'--apply']) == 1
    assert not db.exists()


def test_nice_exact_order_attaches_period_without_duplicate_charge(tmp_path):
    store = OtaStore(tmp_path/'ota.sqlite')
    fact = foresttrip_row(row(),'pay',OBSERVED)
    store.import_direct(provider='forest',account_key='synthetic',source_key='demo',snapshot=row(),facts=[fact])
    store.close()
    portal = _forest_portal_events([str(tmp_path/'ota.sqlite')])[0]
    receipt = dict(portal,evidence_kind='authenticated_forest_pg_card_receipt',
                   service_period=None,booking_ref=None,ota_event_id='original-payment-id',
                   approval_number='999999',authorization_scheme='issuer_card_approval')
    result = _attach_forest_portal_periods([receipt],[portal])
    assert len(result) == 1 and result[0]['ota_event_id'] == 'original-payment-id'
    assert result[0]['service_period'] == portal['service_period']
    for change in [dict(order_number='OTHER-ORDER'),dict(paid_on='2031-02-02'),dict(amount_krw=12346)]:
        unmatched = dict(receipt,service_period=None,**change)
        assert len(_attach_forest_portal_periods([unmatched],[portal])) == 2
        assert unmatched['service_period'] is None


def test_paid_and_cancel_observations_preserve_original_charge(tmp_path):
    paid = row()
    cancelled = {'cells':[paid['cells'][1],paid['cells'][2],paid['cells'][3],paid['cells'][4],
                          '2031-02-02 취소금액12,345 원'],'links':[]}
    for kind, value in [('pay',paid),('cancel',cancelled)]:
        (tmp_path/(kind+'-demo.json')).write_text(json.dumps({'url':'https://foresttrip.go.kr/synthetic',
            'rows':[value]}),encoding='utf8')
    summary, pending = plan(tmp_path,OBSERVED)
    assert summary['additional'] == 1 and summary['conflict'] == 0
    snapshot, fact = pending[0]
    assert len(snapshot['observations']) == 2
    assert fact['reservation_status'] == 'cancelled'
    assert fact['payment_status'] == 'paid' and fact['paid_on'] == '2031-02-01'
    assert fact['amount_krw'] == 12345 and fact['order_number'] == 'ORDER-DEMO'
    assert fact['price_components'][0]['kind'] == 'paid_today'
    store = OtaStore(tmp_path/'ota.sqlite')
    store.import_direct(provider='forest',account_key='synthetic',source_key='demo',snapshot=snapshot,facts=[fact])
    store.close()
    event = _forest_portal_events([str(tmp_path/'ota.sqlite')])[0]
    assert event['event_type'] == 'charge' and event['evidence_status'] == 'paid_verified'
    assert event['reservation_status'] == 'cancelled' and event['refund_status'] == 'none_displayed'


def test_distinct_payment_orders_are_not_collapsed(tmp_path):
    first, second = row(), row()
    second['cells'][0] = 'ANOTHER-DEMO-ORDER'
    (tmp_path/'pay-demo.json').write_text(json.dumps({'url':'https://foresttrip.go.kr/synthetic',
        'rows':[first,second]}),encoding='utf8')
    summary, pending = plan(tmp_path,OBSERVED)
    assert summary['conflict'] == 1 and summary['additional'] == 0 and pending == []
