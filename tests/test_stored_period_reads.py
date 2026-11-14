"""Screens, copies, the paste pack and sheet reconciliation read the stored period; they never recompute it (synthetic only)."""
import json
import sqlite3

import pytest

from app import core_writer
from tools.quarter_review import paste_pack
from webapp import ledger_design, ledger_stay_evidence, read_scope

KNOWN = {'kind': 'known', 'starts_on': '2026-10-01', 'ends_on': '2026-10-03'}
UNKNOWN = {'kind': 'unknown', 'reason': 'no_evidence'}
COMPUTED = {'booking_ref': 'R1', 'service_period': '2026-08-01~2026-08-03',
            'ota_evidence': {'kind': 'exact', 'payment_verified': True}}


def card(tid, period='', **values):
    return {'transaction_id': tid, 'row_id': 'card-' + tid, 'source_event_id': tid, 'occurred_on': '2026-10-01',
            'merchant': '합성 숙소', 'item': '숙박비', 'amount_krw': 1000, 'evidence_type': '카드',
            'service_period': period, 'reservation_no': '', 'display_tab_id': 'trip-a', **values}


@pytest.fixture
def core(monkeypatch, tmp_path):
    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV, core_writer.CORE_DB_ENV):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / 'core.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)')
        conn.executemany('INSERT INTO decisions VALUES (?, ?)',
                         [('known', json.dumps(KNOWN)), ('unknown', json.dumps(UNKNOWN))])
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(path))
    core_writer._FALLBACK.clear()
    core_writer._LAST_READ['periods'] = None
    core_writer._PUBLISHED['key'] = None
    return monkeypatch


def rust(monkeypatch):
    monkeypatch.setenv(core_writer.WRITER_ENV, 'rust')


def counting(calls):
    def compute():
        calls.append(1)
        return '2026-08-01~2026-08-03'
    return compute


def test_rust_decision_is_read_and_the_computation_is_not_called(core):
    rust(core)
    calls = []
    stored = core_writer.load_stored_periods()
    assert ledger_stay_evidence.read_period(card('known'), stored, set(), counting(calls)) == ('2026-10-01~2026-10-03', 'decision')
    assert ledger_stay_evidence.read_period(card('unknown'), stored, set(), counting(calls)) == ('', 'decision')
    assert calls == []
    assert core_writer.period_read_status() == {'mode': 'stored', 'missing_decision_count': 0, 'not_judged_count': 0,
                                                'core_read_error': '', 'stale_read': False}


def test_card_without_decision_falls_back_and_is_counted_until_backfilled(core):
    rust(core)
    calls = []
    stored = core_writer.load_stored_periods()
    assert ledger_stay_evidence.read_period(card('new'), stored, set(), counting(calls)) == ('2026-08-01~2026-08-03', 'computed')
    assert calls == [1]
    assert core_writer.period_read_status()['missing_decision_count'] == 1
    with sqlite3.connect(core_writer.os.environ[core_writer.CORE_DB_ENV]) as conn:
        conn.execute('INSERT INTO decisions VALUES (?, ?)', ('new', json.dumps(KNOWN)))
    ledger_stay_evidence.read_period(card('new'), core_writer.load_stored_periods(), set(), counting(calls))
    assert core_writer.period_read_status()['missing_decision_count'] == 0


def test_python_writer_is_unchanged(core):
    calls = []
    assert core_writer.load_stored_periods() is None
    assert ledger_stay_evidence.read_period(card('known'), None, set(), counting(calls)) == ('2026-08-01~2026-08-03', 'computed')
    assert calls == [1]
    assert core_writer.period_read_status()['mode'] == 'computed'


def test_manual_period_wins_over_the_stored_decision(core):
    rust(core)
    stored = core_writer.load_stored_periods()
    calls = []
    # a value a person typed after the decision was stored
    assert ledger_stay_evidence.read_period(card('known', '2026-12-01~2026-12-02'), stored, set(), counting(calls)) == (
        '2026-12-01~2026-12-02', 'row')
    # a person cleared the period: unknown, not the older stored value and not a recomputation
    assert ledger_stay_evidence.read_period(card('known'), stored, {'card-known'}, counting(calls)) == ('', 'manual')
    assert calls == []


def test_unreadable_core_is_a_visible_fallback_not_a_silent_one(core, tmp_path):
    rust(core)
    core.setenv(core_writer.CORE_DB_ENV, str(tmp_path / 'missing.sqlite'))
    stored = core_writer.load_stored_periods()
    assert stored == {}
    calls = []
    assert ledger_stay_evidence.read_period(card('known'), stored, set(), counting(calls))[1] == 'computed'
    assert core_writer.period_read_status()['core_read_error']


def test_screen_labels_read_the_decision_and_never_build_the_evidence_index(core, monkeypatch):
    rust(core)
    monkeypatch.setattr(ledger_design, '_ledger_stay_index', lambda: pytest.fail('index built'))
    monkeypatch.setattr(ledger_design, '_manual_period_rows', lambda: set())
    monkeypatch.setattr(ledger_design, '_preauthorization_labels', lambda row: None)
    labels = read_scope.scoped(lambda: (ledger_design._service_date_labels(card('known')),
                                        ledger_design._service_date_labels(card('unknown')),
                                        ledger_design._export_period(card('known'))))()
    assert labels[0][0].startswith('10.01–10.03')
    assert '추론' not in labels[0][0]
    assert labels[1][0] == '이용일 확인 필요'
    assert labels[2] == '2026-10-01~2026-10-03'


def test_screen_python_writer_still_uses_the_index(core, monkeypatch):
    monkeypatch.setattr(ledger_design, '_ledger_stay_index', lambda: {'known': COMPUTED})
    monkeypatch.setattr(ledger_design, '_preauthorization_labels', lambda row: None)
    assert read_scope.scoped(lambda: ledger_design._export_period(card('known', reservation_no='R1')))() == '2026-08-01~2026-08-03'


def test_paste_pack_reads_stored_periods_without_evidence(core):
    rust(core)
    rows = [card('known'), card('unknown'), card('new'), card('man')]
    stored = core_writer.load_stored_periods()
    assert paste_pack.apply_verified_periods(rows, {}, stored, {'card-man'}) == 1
    assert [r['service_period'] for r in rows] == ['2026-10-01~2026-10-03', '', '', '']


def test_fallback_is_split_into_not_judged_and_missing_and_published_without_ids(core, tmp_path):
    rust(core)
    stored = core_writer.load_stored_periods()
    never = [card('closed', occurred_on='2025-05-01'), card('wait', display_tab_id=None),
             card('flagged', classification_state='unclassified')]
    for row in never + [card('lost')]:
        ledger_stay_evidence.read_period(row, stored, set(), lambda: '')
    status = core_writer.period_read_status()
    assert (status['not_judged_count'], status['missing_decision_count']) == (3, 1)
    published = json.loads((tmp_path / core_writer.STATUS_FILE).read_text(encoding='utf-8'))
    assert (published['not_judged_count'], published['missing_decision_count']) == (3, 1)
    assert 'lost' not in json.dumps(published)


def test_busy_core_reuses_the_last_successful_read_and_says_so(core, monkeypatch):
    rust(core)
    first = core_writer.load_stored_periods()
    assert 'known' in first

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(core_writer, 'stored_service_periods', busy)
    assert core_writer.load_stored_periods() == first
    status = core_writer.period_read_status()
    assert status['stale_read'] and 'locked' in status['core_read_error']
    assert core_writer.READ_TIMEOUT <= 1
