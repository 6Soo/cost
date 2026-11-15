"""OTA 보고서 규칙 병합이 예전 O(N²) 결과와 같고, 저장 이용기간 읽기 캐시가 변경을 놓치지 않는지 확인한다(합성 자료만)."""
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from app import core_writer
from app import ota_core_projection
from app.ota_core_projection import extend_report


def legacy_extend_report(report, data):
    """예전 구현(사실마다 규칙 목록을 처음부터 거름). 결과 비교용 사본."""
    from app import ota_payments
    from app.normalize import normalize_merchant
    facts = ota_core_projection.card_matches(report.get('matches', []), data)
    existing = report.get('matches', [])
    existing_count = len(existing)
    updated = [fact for index, fact in enumerate(facts) if index >= existing_count or fact != existing[index]]
    if not updated:
        return report
    result = dict(report, matches=facts, rules=list(report.get('rules', [])))
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    for fact in updated:
        card = cards[fact['transaction_id']]
        event = events[str(fact['ota_event_id'])]
        period = fact.get('period') or {}
        if (card.get('ota_inference_eligible') is not True or fact.get('direction') != 'purchase'
                or not ota_payments._event_is_paid(event)
                or fact.get('reservation_status') not in ('confirmed', 'completed', 'observed')
                or not period.get('starts_on') or not period.get('ends_on')
                or not fact.get('source_sha256') or not fact.get('source_hash') or not fact.get('item')):
            continue
        basis = fact.get('allocation_basis')
        label = ('반복 거래 순서 배정 · 개별 결제 근거 미확인' if basis in
                 ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                 else '검증된 OTA 결제 연결')
        result['rules'] = [rule for rule in result['rules']
                           if rule.get('optional', {}).get('source_hash') != fact['source_hash']]
        result['rules'].append({
            'conditions': {'merchant_normalized': normalize_merchant(fact['merchant']),
                           'transaction_direction': 'purchase'},
            'optional': {'source_hash': fact['source_hash']},
            'effects': {'item': fact['item'], 'description': '예약 ' + fact['booking_ref'] + ' · ' + label},
            'origin': 'ota-mail-live', 'note': label,
        })
    return result


def synthetic(count, shared_every=5):
    events, cards, results = [], [], []
    for i in range(count):
        tid = f'card-{i}'
        eid = f'event-{i}'
        cards.append({'transaction_id': tid, 'source_hash': f'hash-{i // shared_every}', 'merchant': 'TRIP.COM',
                      'merchant_normalized': 'TRIP.COM', 'transaction_direction': 'purchase',
                      'ota_inference_eligible': True, 'amount_krw': 1000 + i})
        events.append({'ota_event_id': eid, 'provider': 'trip', 'booking_ref': f'B{i}', 'event_type': 'charge',
                       'paid_on': '2026-09-23', 'payment_status': 'paid', 'evidence_status': 'paid_verified',
                       'reservation_status': 'confirmed', 'item': '숙박비', 'amount_krw': 1000 + i,
                       'source_digest': f'{i:064x}', 'evidence_kind': 'authenticated_payment_mail',
                       'service_period': {'starts_on': '2026-11-06', 'ends_on': '2026-11-07'}})
        results.append({'ota_event_id': eid, 'status': 'MATCHED_AUTO', 'transaction_id': tid,
                        'allocation_basis': 'auto_stable_order' if i % 2 else 'exact'})
    return {'events': events, 'transactions': cards, 'results': results, 'links': {}}


def base_report():
    keep = {'conditions': {'merchant_normalized': 'X'}, 'optional': {'source_hash': 'unrelated'}, 'origin': 'user'}
    plain = {'conditions': {'merchant_normalized': 'Y'}, 'origin': 'user'}
    replaced = {'conditions': {'merchant_normalized': 'Z'}, 'optional': {'source_hash': 'hash-3'}, 'origin': 'old'}
    return {'matches': [], 'rules': [keep, plain, replaced], 'type_only_candidates': []}


@pytest.mark.parametrize('count', [1, 7, 60])
def test_rules_identical_to_legacy_including_order_and_replacements(count):
    data = synthetic(count)
    new = extend_report(base_report(), data)
    old = legacy_extend_report(base_report(), data)
    assert json.dumps(new, ensure_ascii=False, sort_keys=False) == json.dumps(old, ensure_ascii=False, sort_keys=False)
    assert len(new['rules']) > 3 or count == 1
    assert all(rule.get('origin') != 'old' for rule in new['rules']) or count < 16


def test_skipped_facts_do_not_remove_existing_rules():
    data = synthetic(10)
    for card in data['transactions']:
        card['ota_inference_eligible'] = False
    report = base_report()
    new = extend_report(report, data)
    assert json.dumps(new, ensure_ascii=False) == json.dumps(legacy_extend_report(base_report(), data), ensure_ascii=False)
    assert new['rules'] == base_report()['rules']


def test_snapshot_report_is_memoized_per_snapshot_data_object(monkeypatch):
    from webapp import card_flow
    calls = []
    real = ota_core_projection.extend_report

    def counting(report, data):
        calls.append(1)
        return real(report, data)

    monkeypatch.setattr('app.ota_core_projection.extend_report', counting)
    monkeypatch.setitem(card_flow._SNAPSHOT_REPORT_MEMO, 'entry', None)
    flow = card_flow.CardFlow.__new__(card_flow.CardFlow)
    current = {'data': synthetic(20)}
    first = flow._canonical_snapshot_report(current)
    second = flow._canonical_snapshot_report(current)
    assert len(calls) == 1 and first == second and first is not second
    assert first['_reconciliation_authority'] == 'canonical_snapshot'
    flow._canonical_snapshot_report({'data': synthetic(20)})
    assert len(calls) == 2


@pytest.fixture
def core(monkeypatch, tmp_path):
    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / 'core.sqlite'
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('CREATE TABLE decisions(transaction_id TEXT, service_period_json TEXT)')
        conn.execute('INSERT INTO decisions VALUES (?, ?)',
                     ('a', json.dumps({'kind': 'verified', 'starts_on': '2026-10-01', 'ends_on': '2026-10-03'})))
    monkeypatch.setenv(core_writer.CORE_DB_ENV, str(path))
    monkeypatch.setenv(core_writer.WRITER_ENV, 'rust')
    monkeypatch.setitem(core_writer._PERIOD_CACHE, 'entry', None)
    core_writer._LAST_READ['periods'] = None
    return path


def test_stored_periods_read_is_cached_until_core_changes(core, monkeypatch):
    reads = []
    real = sqlite3.connect
    monkeypatch.setattr(core_writer, 'sqlite3', SimpleNamespace(
        Error=sqlite3.Error, connect=lambda *a, **k: (reads.append(1), real(*a, **k))[1]))
    first = core_writer.load_stored_periods()
    assert core_writer.load_stored_periods() == first and len(reads) == 1
    first['a'] = 'mutated by caller'
    assert core_writer.load_stored_periods()['a']['kind'] == 'verified'
    # 같은 크기의 값 수정(행 수·파일 크기 동일)도 놓치지 않는다.
    with closing(sqlite3.connect(core)) as conn, conn:
        conn.execute('UPDATE decisions SET service_period_json=? WHERE transaction_id=?',
                     (json.dumps({'kind': 'verified', 'starts_on': '2026-10-02', 'ends_on': '2026-10-04'}), 'a'))
    changed = core_writer.load_stored_periods()
    assert len(reads) == 2 and changed['a']['starts_on'] == '2026-10-02'
    with closing(sqlite3.connect(core)) as conn, conn:
        conn.execute('INSERT INTO decisions VALUES (?, ?)', ('b', json.dumps({'kind': 'unknown'})))
    assert 'b' in core_writer.load_stored_periods() and len(reads) == 3


def test_stored_periods_cache_sees_wal_mode_writes(core, monkeypatch):
    with closing(sqlite3.connect(core)) as conn, conn:
        conn.execute('PRAGMA journal_mode=WAL')
    first = core_writer.load_stored_periods()
    writer = sqlite3.connect(core)
    try:
        writer.execute('UPDATE decisions SET service_period_json=? WHERE transaction_id=?',
                       (json.dumps({'kind': 'unknown'}), 'a'))
        writer.commit()
        assert first['a']['kind'] == 'verified'
        assert core_writer.load_stored_periods()['a']['kind'] == 'unknown'
    finally:
        writer.close()


def test_stored_periods_cache_does_not_hide_unreadable_core(core, monkeypatch):
    assert core_writer.load_stored_periods()['a']
    core.unlink()
    result = core_writer.load_stored_periods()
    assert result['a'] and core_writer.period_read_status()['stale_read'] is True
