"""Synthetic checks for app.core_period_evidence: the verified-only period report.

The bridge computes its ``verified`` map once and hands it to the single report helper, so one screen
index and one walk of every row cover the read. The report stops at what the rule verifies (DATE-109):
no candidates, no screen-only inference, no stored projection, no writes. A person's field (value or
explicit blank) is authoritative, and an unknown evidence state stays 'none'.
"""
from __future__ import annotations

import json

import pytest

from app import core_period_evidence as evidence
import webapp.ledger_stay_evidence as stay
from tools.core_bridge import periods
from tools.core_bridge.cli import handle
from tools.core_bridge.golden import _card, _event


def _snapshot():
    event = _event('syn-e1', item='숙박비', reservation_status='confirmed')
    card = _card('syn-t1', source_hash='syn-hash-syn-t1')
    result = {'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}
    return {'events': [event], 'transactions': [card], 'results': [result], 'links': {}}


def _row(tid='syn-t1', **extra):
    row = {'row_id': 'card-' + tid, 'service_period': '', 'reservation_no': ''}
    row.update(extra)
    return row


def _report(data, rows, manual=()):
    """The reporter over the same per-row map the bridge produces - one index, one hand-off."""
    verified = periods.verified_from_snapshot(data, set(manual), rows)
    return evidence.verified_report(rows, verified, set(manual))


def test_verified_report_names_a_verified_link_without_candidates_or_source_text():
    data = _snapshot()
    rows = [_row()]
    report = _report(data, rows)
    assert report == {'card-syn-t1': {'period': '2026-10-01~2026-10-03', 'state': 'verified'}}
    blob = json.dumps(report, ensure_ascii=False)
    assert 'source_hash' not in blob and 'candidates' not in blob and 'TRIP.COM' not in blob
    assert data == _snapshot() and rows == [_row()]
    assert _report(data, rows) == report


def test_verified_report_keeps_a_persons_field_a_value_or_blank():
    data = _snapshot()
    assert _report(data, [_row()], ['card-syn-t1']) == {
        'card-syn-t1': {'period': '', 'state': 'manual'}}
    typed = _row(service_period='2026-09-01~2026-09-02')
    assert _report(data, [typed], ['card-syn-t1']) == {
        'card-syn-t1': {'period': '2026-09-01~2026-09-02', 'state': 'row'}}
    # another row's field does not blank this one
    assert _report(data, [_row()], ['card-other'])['card-syn-t1']['state'] == 'verified'


def test_verified_report_blank_without_admitted_evidence():
    unconfirmed = _event('syn-e1', item='숙박비', reservation_status='pending')
    card = _card('syn-t1', source_hash='syn-hash-syn-t1')
    result = {'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}
    assert _report({'events': [unconfirmed], 'transactions': [card], 'results': [result], 'links': {}},
                   [_row()]) == {'card-syn-t1': {'period': '', 'state': 'none'}}
    assert _report({'events': [], 'transactions': [], 'results': [], 'links': {}}, [_row()]) == {
        'card-syn-t1': {'period': '', 'state': 'none'}}


def test_verified_report_does_not_absorb_inference():
    receipt = _event('syn-e1', item='', service_period=None, reservation_status='confirmed')
    stated = _event('syn-e2', item='', event_type='reservation', evidence_status='booking_only',
                    payment_status='pending', reservation_status='confirmed')
    data = {'events': [receipt, stated], 'transactions': [_card('syn-t1', source_hash='syn-hash-syn-t1')],
            'results': [{'ota_event_id': 'syn-e1', 'transaction_id': 'syn-t1', 'status': 'MATCHED_AUTO'}], 'links': {}}
    row = _row(item='숙박비')
    found = periods.found_from_snapshot(data, set(), [row])['card-syn-t1']
    assert found['kind'] == 'inferred'
    assert _report(data, [row]) == {'card-syn-t1': {'period': '', 'state': 'none'}}


def test_the_bridge_exposes_the_read_only_report_under_an_explicit_option():
    """The producer is reachable from a real entry point without moving the existing shapes."""
    data = _snapshot()
    rows = [_row()]
    plain = handle('periods', {'data': data, 'manual': [], 'rows': rows}, sha='')
    assert 'period_report' not in plain['result']
    assert set(plain['result']) == {'facts', 'verified'}
    response = handle('periods', {'data': data, 'manual': [], 'rows': rows, 'report': True}, sha='')
    assert response['result']['period_report'] == {
        'card-syn-t1': {'period': '2026-10-01~2026-10-03', 'state': 'verified'}}
    # the option is additive: every other key keeps its shape
    assert response['result']['facts'] == plain['result']['facts']
    assert response['result']['verified'] == plain['result']['verified']


def test_the_bridge_reuses_its_verified_map_and_reports_in_one_pass(monkeypatch):
    data = _snapshot()
    rows = [_row()]
    captured = {}
    real = periods.verified_report

    def spy(rows_arg, verified, manual=None):
        captured['rows'] = rows_arg
        captured['verified'] = verified
        return real(rows_arg, verified, manual)

    monkeypatch.setattr(periods, 'verified_report', spy)
    counts = []
    real_index = stay.index_from_snapshot

    def counting_index(*args, **kwargs):
        counts.append(1)
        return real_index(*args, **kwargs)

    monkeypatch.setattr(stay, 'index_from_snapshot', counting_index)
    response = handle('periods', {'data': data, 'manual': [], 'rows': rows, 'report': True}, sha='')
    # the map the response already carries is the map the report is built from: one index, one hand-off
    assert counts == [1]
    assert captured['rows'] is rows
    assert captured['verified'] == response['result']['verified']
    assert response['result']['period_report'] == {
        'card-syn-t1': {'period': '2026-10-01~2026-10-03', 'state': 'verified'}}
    # and a one-shot iterator still yields the whole report in a single pass
    assert periods.verified_report(iter(rows), {'card-syn-t1': '2026-10-01~2026-10-03'}) == {
        'card-syn-t1': {'period': '2026-10-01~2026-10-03', 'state': 'verified'}}
