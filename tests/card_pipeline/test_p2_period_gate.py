"""Synthetic checks for the M2 P1-to-P2 period gate (DECISION_POLICY 3.0.2, DATE-109).

A lodging/airfare row whose item and trip were settled by an automatic data rule
but which has no recorded service period must still reach P2's evidence check.
Every manual and exact authority must stay protected. No live database, no
customer data, no model call, no network.
"""
import json
from pathlib import Path

import pytest

from app import ai_classification
from webapp.card_flow import CardFlow
from webapp.card_classification_completion import context
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.fixtures import domestic_row, make_csv


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'legacy')
    monkeypatch.delenv('WEBLEDGER_AUTONOMOUS_AI_REVIEW', raising=False)
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: True)
    store = LedgerStore(tmp_path / 'period-gate.sqlite', seed_demo=False)
    yield store
    store.close()


def _row(store, *, item, source, basis='데이터 규칙 · 자동 분류', trip_tab=True, suffix=''):
    trip = store.create_trip(starts_on='2026-10-01', ends_on='2026-10-05', destination='합성여행',
                             client_request_id='gate' + item + source + suffix)['tab_id']
    flow = CardFlow(store)
    batch = flow.pipeline.receive(make_csv([domestic_row(
        merchant='AGODA.COM', amount=30000, approval='GATE' + item + source + suffix,
        date='2026-10-03', posting='2026-10-03', issuer='국민',
        card='****-****-****-1234')]), 'gate.csv')['batch_id']
    tid = flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
    store.conn.execute(
        "UPDATE transactions SET classification_state='classified', classification_source=?,"
        " item=?, trip_id=?, display_tab_id=?, classification_basis=? WHERE transaction_id=?",
        (source, item, trip if trip_tab else '', trip if trip_tab else 'quarter:2026:4', basis, tid))
    store.conn.commit()
    return tid, trip


def _prepare(store, tid, *, reconsider=False):
    trips, nets = context(CardFlow(store))
    return ai_classification.prepare(store.conn, trips, [tid], nets=nets, reconsider=reconsider)


# --- the gap this change closes ---------------------------------------------

@pytest.mark.parametrize('item', ['숙박비', '항공료'])
@pytest.mark.parametrize('source', ['rule', 'auto'])
def test_automatic_rule_lodging_without_a_period_reaches_p2(board, item, source):
    tid, trip = _row(board, item=item, source=source, suffix=item + source)
    request = _prepare(board, tid)
    assert len(request['cases']) == 1
    assert request['protected'] == 0
    case = request['cases'][0]
    assert case['transaction_id'] == tid
    # P2 sees the trip P1 chose and the quarter alternative; it decides, not this gate.
    assert {t['trip_id'] for t in case['trips']} >= {trip, 'quarter:2026:4'}


@pytest.mark.parametrize('item', ['숙박비', '항공료'])
@pytest.mark.parametrize('source', ['inference', 'pattern', 'card_category', 'provider_default'])
def test_weaker_code_sources_keep_reaching_p2_as_before(board, item, source):
    tid, _ = _row(board, item=item, source=source, suffix=item + source)
    assert len(_prepare(board, tid)['cases']) == 1


# --- no widening -----------------------------------------------------------

@pytest.mark.parametrize('item', ['식비', '교통비', '기타경비', '현지경비', '렌터카', '입장료', '주차비'])
def test_other_items_by_a_data_rule_stay_in_p1(board, item):
    tid, _ = _row(board, item=item, source='rule', suffix=item)
    request = _prepare(board, tid)
    assert request['cases'] == [] and request['protected'] == 1


@pytest.mark.parametrize('item', ['숙박비', '항공료'])
@pytest.mark.parametrize('source', ['user_decision', 'user_exception', 'manual', 'manual_hold',
                                    'refund_original', 'guide_airfare_evidence', 'owner_booking'])
def test_manual_and_exact_authority_is_never_reopened(board, item, source):
    tid, _ = _row(board, item=item, source=source, suffix=item + source)
    request = _prepare(board, tid)
    assert request['cases'] == [] and request['protected'] == 1


@pytest.mark.parametrize('item', ['숙박비', '항공료'])
def test_a_recorded_period_is_not_reopened(board, item):
    basis = '데이터 규칙 · P2_METADATA ' + json.dumps(
        {'service_start': '2026-10-01', 'service_end': '2026-10-05'}, ensure_ascii=False)
    tid, _ = _row(board, item=item, source='rule', basis=basis, suffix=item)
    request = _prepare(board, tid)
    assert request['cases'] == [] and request['protected'] == 1


def test_reconsider_still_reaches_the_rule_row(board):
    tid, _ = _row(board, item='숙박비', source='rule', suffix='reconsider')
    assert len(_prepare(board, tid, reconsider=True)['cases']) == 1


def test_quarter_tab_rule_row_is_published_by_p1_first(board):
    """P1 publishes before P2: the gate must say so, not silently skip the row."""
    tid, _ = _row(board, item='숙박비', source='rule', trip_tab=False, suffix='quarter')
    with pytest.raises(ValueError, match='CODE_STAGE_REQUIRED'):
        _prepare(board, tid)
