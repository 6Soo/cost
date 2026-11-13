"""TRIP-036: a source-bound reservation period outranks payment-date proximity for new judgements."""
from app import automatic_classification as policy
from webapp.tests.test_automatic_classification_completion import setup  # noqa: F401

TRIPS = [dict(trip_id='A', starts_on='2026-10-01', ends_on='2026-10-05'),
         dict(trip_id='C', starts_on='2026-10-10', ends_on='2026-10-14')]


def _fact(row, trip='C'):
    return {row['transaction_id']: dict(source_hash=row['source_hash'], trip_id=trip,
                                        item='항공료', basis='합성 예약 이용기간')}


def _first(conn):
    cur = conn.execute('SELECT * FROM transactions ORDER BY transaction_id')
    return dict(zip([d[0] for d in cur.description], cur.fetchone()))


def _target(plan, tid):
    return next((t for t in plan['targets'] if t['id'] == tid), None)


def test_evidence_applies_without_reconsider(setup):  # noqa: F811
    conn = setup[0].conn
    row = _first(conn)
    plan = policy.plan(conn, TRIPS, evidence=_fact(row))
    values = dict(zip(policy.FIELDS, _target(plan, row['transaction_id'])['values']))
    assert values['trip_id'] == 'C' and values['display_tab_id'] == 'C'


def test_without_evidence_or_with_stale_hash_keeps_payment_date_rule(setup):  # noqa: F811
    conn = setup[0].conn
    row = _first(conn)
    for evidence in ({}, {row['transaction_id']: dict(_fact(row)[row['transaction_id']], source_hash='stale')}):
        plan = policy.plan(conn, TRIPS, evidence=evidence)
        values = dict(zip(policy.FIELDS, _target(plan, row['transaction_id'])['values']))
        assert values['trip_id'] == 'A'


def test_manual_decision_wins_over_evidence(setup):  # noqa: F811
    conn = setup[0].conn
    row = _first(conn)
    conn.execute("UPDATE transactions SET classification_state='classified',classification_source='user_decision',"
                 "trip_id='A',display_tab_id='A',item='식비',decided_at='2026-10-20' WHERE transaction_id=?",
                 (row['transaction_id'],))
    conn.commit()
    plan = policy.plan(conn, TRIPS, evidence=_fact(row))
    assert _target(plan, row['transaction_id']) is None


def test_closed_period_stays_unchanged_with_evidence(setup):  # noqa: F811
    conn = setup[0].conn
    conn.execute("UPDATE transactions SET classification_state='preserved',approval_date='2025-10-03'")
    conn.commit()
    row = _first(conn)
    plan = policy.plan(conn, TRIPS, evidence=_fact(row))
    assert plan['summary']['to_classify'] == 0
