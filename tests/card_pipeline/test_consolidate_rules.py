"""규칙 정리는 다시 작동할 수 없는 규칙과 기본 규칙과 같은 규칙만 고르고, 되돌릴 수 있다."""
import sqlite3

from app import Pipeline
from tools import consolidate_rules
from .fixtures import make_csv, domestic_row


def _setup(tmp_path):
    conn = sqlite3.connect(tmp_path / 'cost.sqlite', isolation_level=None)
    pipe = Pipeline(conn)
    pipe.receive(make_csv([domestic_row(merchant='OPEN', amount=100, approval='one'),
                           domestic_row(merchant='DONE', amount=200, approval='two')]), 'synthetic.csv')
    source = dict(conn.execute('SELECT merchant, source_hash FROM transactions'))
    conn.execute("UPDATE transactions SET decided_at='2026-10-01' WHERE merchant='DONE'")
    for merchant in ('OPEN', 'DONE'):
        pipe.save_rule({'conditions': {'merchant_normalized': merchant}, 'effects': {'item': '숙박비'},
                        'optional': {'source_hash': source[merchant]}, 'rule_id': 'bound-' + merchant})
    local = {'optional': {'travel_country': 'local'}, 'effects': {'item': '현지경비'}}
    pipe.save_rule(dict(local, conditions={'merchant_normalized': '*', 'transaction_direction': 'purchase'},
                        rule_id='default'))
    for merchant, item in (('CAFE ROMA', '현지경비'), ('TRATTORIA', '식비'), ('택시', '현지경비')):
        pipe.save_rule({'conditions': {'merchant_normalized': merchant, 'transaction_direction': 'purchase'},
                        'optional': {'travel_country': 'local'}, 'effects': {'item': item},
                        'rule_id': 'local-' + merchant})
    return conn


def test_only_closed_transaction_rules_and_default_equivalents_are_chosen(tmp_path):
    conn = _setup(tmp_path)
    found = {(rule_id, reason) for rule_id, reason, _ in consolidate_rules.candidates(conn)}
    # 식비 규칙은 기본 규칙과 결과가 다르고, 택시는 가맹점 패턴이 기본 규칙보다 먼저 적용된다.
    assert found == {('bound-DONE', consolidate_rules.CLOSED_TRANSACTION),
                     ('local-CAFE ROMA', consolidate_rules.SAME_AS_LOCAL_DEFAULT)}


def test_apply_retires_without_deleting_and_restore_brings_the_rules_back(tmp_path):
    conn = _setup(tmp_path)
    found = consolidate_rules.candidates(conn)
    consolidate_rules.apply(conn, found, 'run-1')
    status = dict(conn.execute('SELECT rule_id, status FROM cost_classification_rules'))
    assert {rule_id for rule_id, value in status.items() if value == 'retired'} == {r for r, _, _ in found}
    assert len(status) == 6
    assert consolidate_rules.candidates(conn) == []
    assert consolidate_rules.restore(conn, 'run-1') == len(found)
    assert set(dict(conn.execute('SELECT rule_id, status FROM cost_classification_rules')).values()) == {'active'}
