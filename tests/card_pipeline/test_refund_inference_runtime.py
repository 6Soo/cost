"""Entirely synthetic refund evidence, independent of customer files and databases."""
from contextlib import nullcontext

import pytest

from app.partial_refund import refund_links, refund_group, read_only_scope, kakao_refund_candidates
from tests.card_pipeline.test_kakao_amount_inferred import database, row


@pytest.fixture(params=[False, True], ids=['direct', 'cached'])
def scope(request):
    with read_only_scope() if request.param else nullcontext():
        yield


def pair(db, *, merchant='카카오택시', refund_merchant='카카오T가승인', day='2026-10-03'):
    row(db, 'synthetic-p', 'purchase', merchant, 24600)
    row(db, 'synthetic-r', 'cancellation', refund_merchant, -24600, day=day)


def test_link_group_and_candidate_share_global_readonly_evidence(scope):
    db = database()
    pair(db)
    before = list(db.iterdump())
    link = refund_links(db, ['synthetic-r'])['synthetic-r']
    assert link['original_id'] == 'synthetic-p' and link['inferred'] is True
    assert refund_group(db, 'synthetic-p') == ['synthetic-p', 'synthetic-r']
    assert kakao_refund_candidates(db, {'synthetic-r'}) == {'synthetic-r': link}
    copy = refund_links(db, ['synthetic-r'])
    copy['synthetic-r']['net_krw'] = 99
    assert refund_links(db, ['synthetic-r'])['synthetic-r']['net_krw'] == 0
    assert list(db.iterdump()) == before
    row(db, 'synthetic-competitor', 'purchase', '카카오택시', 24600)
    assert refund_links(db, ['synthetic-r']) == {}
    assert refund_group(db, 'synthetic-p') == ['synthetic-p']


@pytest.mark.parametrize('day,linked', [('2026-10-16', True), ('2026-10-17', False),
                                      ('2026-10-01', False)])
def test_kakao_window_is_inclusive_and_never_matches_future_purchase(scope, day, linked):
    db = database()
    pair(db, day=day)
    assert bool(refund_links(db, ['synthetic-r'])) is linked


@pytest.mark.parametrize('scenario', ['purchase', 'refund', 'asymmetric'])
def test_all_competing_edges_block_even_when_only_one_refund_is_requested(scope, scenario):
    db = database()
    pair(db)
    if scenario == 'purchase':
        row(db, 'synthetic-p2', 'purchase', '카카오쇼핑', 24600)
    elif scenario == 'refund':
        row(db, 'synthetic-r2', 'cancellation', '카카오택시', -24600)
    else:
        row(db, 'synthetic-p2', 'purchase', '카카오택시', 24600, day='2026-10-15')
        row(db, 'synthetic-r2', 'cancellation', '카카오택시', -24600, day='2026-10-15')
    assert refund_links(db, ['synthetic-r']) == {}


@pytest.mark.parametrize('column,value', [('issuer', '다른발급사'), ('card_tail', '7777'),
    ('merchant', '일반택시'), ('merchant', '카카오쇼핑'), ('approval_date', 'invalid'),
    ('original_approval_number', 'unresolved-reference'), ('amount_krw', -12300),
    ('foreign_currency', 'USD'), ('foreign_amount', '18.7')])
def test_nonexact_or_different_identity_never_infers(scope, column, value):
    db = database()
    pair(db)
    db.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?', (value, 'synthetic-r'))
    assert refund_links(db, ['synthetic-r']) == {}


@pytest.mark.parametrize('target', ['synthetic-p', 'synthetic-r', 'competitor'])
@pytest.mark.parametrize('column,value', [('duplicate_of', 'duplicate-source'),
    ('conflict_reason', 'synthetic-conflict'), ('parse_error', 'synthetic-parse')])
def test_source_errors_never_disappear_from_ambiguity_checks(scope, target, column, value):
    db = database()
    pair(db)
    if target == 'competitor':
        row(db, target, 'purchase', '카카오택시', 24600)
    db.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?', (value, target))
    assert refund_links(db, ['synthetic-r']) == {}


@pytest.mark.parametrize('competitor', [False, True])
def test_numbered_original_is_reserved_globally_without_hiding_competition(scope, competitor):
    db = database()
    pair(db)
    db.execute("UPDATE transactions SET approval_number='REF-A' WHERE transaction_id='synthetic-p'")
    row(db, 'synthetic-numbered-r', 'cancellation', '別名取消', -4100, original='REF-A')
    if competitor:
        row(db, 'synthetic-free-p', 'purchase', '카카오택시', 24600)
    assert refund_links(db, ['synthetic-r']) == {}
    link = refund_links(db, ['synthetic-numbered-r'])['synthetic-numbered-r']
    assert link['net_krw'] == 20500 and not link.get('inferred')


def test_foreign_reservation_applies_outside_requested_page_and_cannot_be_overridden(scope):
    db = database()
    pair(db, refund_merchant='카카오택시')
    db.execute("UPDATE transactions SET foreign_amount='21.25',foreign_currency='USD' "
               "WHERE transaction_id='synthetic-p'")
    row(db, 'synthetic-foreign-r', 'cancellation', '카카오택시', -24600)
    db.execute("UPDATE transactions SET foreign_amount='21.25',foreign_currency='USD' "
               "WHERE transaction_id='synthetic-foreign-r'")
    assert refund_links(db, ['synthetic-r']) == {}
    assert refund_links(db, ['synthetic-foreign-r'])['synthetic-foreign-r']['basis'] == 'merchant_card_foreign_amount'


@pytest.mark.parametrize('amounts,status', [([-4100, -6200], 'partial'),
    ([-12300, -12300], 'full'), ([-24600, -4100], 'excess')])
def test_authoritative_one_to_many_ignores_names_amounts_and_inference_window(scope, amounts, status):
    db = database()
    row(db, 'synthetic-p', 'purchase', '원가맹점', 24600, approval='REF-A')
    for index, amount in enumerate(amounts):
        row(db, f'synthetic-r{index}', 'cancellation', '다른가맹점', amount,
            original='REF-A', day='2026-10-25')
    links = refund_links(db, ['synthetic-r0', 'synthetic-r1'])
    assert len(links) == 2
    assert {x['status'] for x in links.values()} == {status}
    assert all(x['refund_count'] == 2 and not x.get('inferred') for x in links.values())
    assert refund_group(db, 'synthetic-p') == ['synthetic-p', 'synthetic-r0', 'synthetic-r1']


@pytest.mark.parametrize('scenario', ['unique', 'two-purchases', 'two-refunds', 'partial',
    'different-day', 'different-merchant', 'different-card', 'different-issuer'])
def test_generic_same_day_exact_amount_has_strict_one_to_one_identity(scope, scenario):
    db = database()
    pair(db, merchant='합성고속버스', refund_merchant='합성고속버스', day='2026-10-02')
    if scenario == 'two-purchases':
        row(db, 'synthetic-p2', 'purchase', '합성고속버스', 24600)
    elif scenario == 'two-refunds':
        row(db, 'synthetic-r2', 'cancellation', '합성고속버스', -24600)
    elif scenario != 'unique':
        column, value = {'partial': ('amount_krw', -12300), 'different-day': ('approval_date', '2026-10-03'),
            'different-merchant': ('merchant_normalized', '다른가맹점'),
            'different-card': ('card_tail', '7777'), 'different-issuer': ('issuer', '다른발급사')}[scenario]
        db.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?', (value, 'synthetic-r'))
    links = refund_links(db, ['synthetic-r'])
    assert bool(links) is (scenario == 'unique')
    if links:
        assert links['synthetic-r']['basis'] == 'same_card_merchant_day_exact_amount_inferred'


def test_display_cache_observes_another_connection_commit(tmp_path):
    source = database()
    pair(source)
    source.commit()
    import sqlite3
    db = sqlite3.connect(tmp_path / 'synthetic.sqlite')
    source.backup(db)
    other = sqlite3.connect(tmp_path / 'synthetic.sqlite')
    try:
        with read_only_scope():
            assert refund_links(db, ['synthetic-r'])
            other.execute("UPDATE transactions SET conflict_reason='changed' WHERE transaction_id='synthetic-p'")
            other.commit()
            assert refund_links(db, ['synthetic-r']) == {}
    finally:
        other.close()
        db.close()


@pytest.mark.parametrize('column,value', [('duplicate_of', 'synthetic-duplicate'),
    ('conflict_reason', 'synthetic-conflict'), ('parse_error', 'synthetic-error')])
def test_numbered_link_cannot_hide_a_second_broken_original(scope, column, value):
    db = database()
    row(db, 'synthetic-p1', 'purchase', '합성가맹점', 24600, approval='REF-A')
    row(db, 'synthetic-p2', 'purchase', '합성가맹점', 24600, approval='REF-A')
    row(db, 'synthetic-r', 'cancellation', '다른가맹점', -4100, original='REF-A')
    db.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?', (value, 'synthetic-p2'))
    assert refund_links(db, ['synthetic-r']) == {}


@pytest.mark.parametrize('column,value', [('issuer', ''), ('card_tail', ''),
    ('issuer', '다른발급사'), ('card_tail', '7777')])
def test_original_reference_requires_known_same_card_and_issuer(scope, column, value):
    db = database()
    row(db, 'synthetic-p', 'purchase', '합성가맹점', 24600, approval='REF-A')
    row(db, 'synthetic-r', 'cancellation', '다른가맹점', -4100, original='REF-A')
    if not value:
        db.execute(f'UPDATE transactions SET {column}=?', (value,))
    else:
        db.execute(f'UPDATE transactions SET {column}=? WHERE transaction_id=?', (value, 'synthetic-r'))
    assert refund_links(db, ['synthetic-r']) == {}
