"""P1/P2 final destinations retain original, manual and refund protections."""
import pytest
from app import automatic_classification as policy
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore


@pytest.fixture
def destination_store(tmp_path):
    store = LedgerStore(tmp_path / 'destinations.sqlite', seed_demo=False)
    flow = CardFlow(store)
    flow.pipeline.receive(make_csv([domestic_row(merchant='SYNTHETIC OPAQUE',
        amount=12000, date='2026-11-08', approval='DESTINATION-1')]), 'synthetic.csv')
    yield store
    store.close()


def test_p1_p2_without_a_real_trip_uses_observed_quarter_and_is_idempotent(destination_store):
    store = destination_store
    before = list(store.conn.iterdump())
    preview = policy.plan(store.conn, [])
    assert list(store.conn.iterdump()) == before
    assert len(preview['targets']) == 1
    target = dict(zip(policy.FIELDS, preview['targets'][0]['values']))
    assert target['classification_state'] == 'classified'
    assert target['display_tab_id'] == 'quarter:2026:4' and not target['trip_id']
    assert target['item'] and '실제 여행 후보 없음' in target['classification_basis']
    original = store.conn.execute('SELECT source_hash,amount_krw FROM transactions').fetchall()
    policy.apply(store.conn, preview, [])
    assert policy.plan(store.conn, [])['targets'] == []
    assert store.conn.execute('SELECT source_hash,amount_krw FROM transactions').fetchall() == original


def test_real_trip_still_precedes_quarter(destination_store):
    preview = policy.plan(destination_store.conn, [dict(trip_id='REAL', starts_on='2026-11-01', ends_on='2026-11-10')])
    target = dict(zip(policy.FIELDS, preview['targets'][0]['values']))
    assert target['trip_id'] == 'REAL' and target['display_tab_id'] == 'REAL'


@pytest.mark.parametrize('field,value', [('parse_error','unreadable amount'),
    ('conflict_reason','source conflict'), ('duplicate_of','synthetic-original')])
def test_source_protections_cannot_receive_quarter_destinations(destination_store, field, value):
    destination_store.conn.execute(f'UPDATE transactions SET {field}=?', (value,))
    assert policy.plan(destination_store.conn, [])['targets'] == []


def test_invalid_date_never_invents_the_current_quarter():
    for raw in ('', '2026-02-31', 'not-a-date'):
        assert policy._quarter_destination({'transaction_direction':'purchase', 'approval_date':raw, 'amount_krw':12000}) is None
    assert policy._quarter_destination({'transaction_direction':'refund', 'approval_date':'2026-11-08', 'amount_krw':12000}) is None

    assert policy._quarter_destination({'transaction_direction':'purchase', 'approval_date':'2026-11-08', 'amount_krw':12000})
