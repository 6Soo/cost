"""Paste pack, ledger copy and sheet reconciliation use the screen's verified stay period (synthetic only)."""

from types import SimpleNamespace

from tools.quarter_review import paste_pack
from webapp import ledger_design, ledger_stay_evidence, sheet_expense_reconciliation

VERIFIED = {'booking_ref': 'R1', 'service_period': '2026-08-01~2026-08-03',
            'ota_evidence': {'kind': 'exact', 'payment_verified': True}}
INFERRED = {'booking_ref': '', 'service_period': '2026-08-05~2026-08-06',
            'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
INDEX = {'v': VERIFIED, 'i': INFERRED}


def card(tid, period='', **values):
    return {'transaction_id': tid, 'row_id': 'card-' + tid, 'occurred_on': '2026-08-01',
            'merchant': '합성 숙소', 'item': '숙박비', 'amount_krw': 1000, 'evidence_type': '카드',
            'service_period': period, 'reservation_no': '', 'display_tab_id': 'trip-a', **values}


def test_verified_period_fills_blank_and_inference_stays_blank():
    assert ledger_stay_evidence.verified_period_for(card('v'), INDEX) == '2026-08-01~2026-08-03'
    assert ledger_stay_evidence.verified_period_for(card('i'), INDEX) == ''
    # the screen itself still shows the inference
    assert ledger_stay_evidence.period_for(card('i'), INDEX) == '2026-08-05~2026-08-06'


def test_stored_period_wins_over_evidence():
    assert ledger_stay_evidence.verified_period_for(card('v', '2026-09-01~2026-09-02'), INDEX) == '2026-09-01~2026-09-02'


def test_paste_pack_rows_fill_once_from_batch_index():
    rows = [card('v'), card('i'), card('none'), card('v2', '2026-09-01~2026-09-02')]
    assert paste_pack.apply_verified_periods(rows, INDEX) == 1
    assert [r['service_period'] for r in rows] == ['2026-08-01~2026-08-03', '', '', '2026-09-01~2026-09-02']
    result = paste_pack._export_rows(rows[:1])
    assert result['tsv'].split('\t')[3] == '2026-08-01~2026-08-03'


def test_paste_pack_without_index_is_unchanged():
    rows = [card('v')]
    assert paste_pack.apply_verified_periods(rows, {}) == 0
    assert rows[0]['service_period'] == ''


def test_ledger_copy_uses_verified_period(monkeypatch):
    monkeypatch.setattr(ledger_design, '_ledger_stay_index', lambda: INDEX)
    row = lambda tid, **kw: {'row_id': 'card-' + tid, 'source_event_id': tid, 'item': '숙박비',
                             'occurred_on': '2026-08-01', 'source_merchant': '합성', 'amount_krw': 1000,
                             'evidence_type': '카드', **kw}
    result = ledger_design._trip_expense_tsv('trip-a', [row('v'), row('i')])
    periods = [line.split('\t')[3] for line in result['tsv'].splitlines()]
    assert sorted(periods) == ['', '2026-08-01~2026-08-03']


def test_sheet_export_uses_verified_period(monkeypatch):
    rows = [{**card('v'), 'merchant': '합성', 'evidence': 'card', 'booking_ref': ''},
            {**card('i'), 'merchant': '합성', 'evidence': 'card', 'booking_ref': ''}]
    fresh = {'source_available': True, 'cost_rows': rows, 'results': [
        {'transaction_id': r['transaction_id'], 'status': 'NEW_EXPENSE'} for r in rows]}
    monkeypatch.setattr(sheet_expense_reconciliation, 'preview_for_trip', lambda *a, **k: fresh)
    monkeypatch.setattr(ledger_stay_evidence, 'export_index', lambda store: INDEX)
    result = sheet_expense_reconciliation.export_for_trip(SimpleNamespace(), rows, 'trip-a')
    periods = [line.split('\t')[3] for line in result['tsv'].splitlines()]
    assert sorted(periods) == ['', '2026-08-01~2026-08-03']
