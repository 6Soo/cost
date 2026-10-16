"""Cancellations without an approval number pair with a purchase by merchant, card, currency and foreign amount."""
import sqlite3

import pytest

from app import partial_refund
from app.partial_refund import refund_group, refund_links


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.execute("""CREATE TABLE transactions(transaction_id TEXT PRIMARY KEY, transaction_direction TEXT, issuer TEXT,
        card_tail TEXT, merchant_normalized TEXT, amount_krw INTEGER, foreign_amount TEXT, foreign_currency TEXT,
        approval_date TEXT, posting_date TEXT, approval_number TEXT, original_approval_number TEXT,
        duplicate_of TEXT, conflict_reason TEXT, parse_error TEXT)""")
    return db


def add(conn, tid, direction, amount, day, *, merchant='AGODA X', foreign='1,000.000', currency='JPY',
        number='', original='', card='1234'):
    conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,'','')",
                 (tid, direction, 'KB', card, merchant, amount, foreign, currency, day, day, number, original))


def test_a_unique_purchase_pairs_by_merchant_card_and_foreign_amount(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01', number='A1')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    link = refund_links(conn, ['C'])['C']
    assert link['original_id'] == 'P' and link['status'] == 'full' and link['net_krw'] == 0


def test_a_krw_difference_from_the_rate_stays_in_the_net(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01')
    add(conn, 'C', 'cancellation', -11900, '2026-04-05')
    link = refund_links(conn, ['C'])['C']
    assert link['status'] == 'partial' and link['net_krw'] == 100


def test_two_identical_purchases_are_not_guessed(conn):
    add(conn, 'P1', 'purchase', 12000, '2026-04-01')
    add(conn, 'P2', 'purchase', 12000, '2026-04-02')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    assert refund_links(conn, ['C']) == {}


def test_two_refunds_for_one_purchase_are_not_paired(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01')
    add(conn, 'C1', 'cancellation', -6000, '2026-04-05', foreign='500.000')
    add(conn, 'C2', 'cancellation', -6000, '2026-04-06', foreign='500.000')
    assert refund_links(conn, ['C1', 'C2']) == {}


def test_a_refund_before_the_purchase_is_not_paired(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-10')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    assert refund_links(conn, ['C']) == {}


def test_a_refund_outside_the_window_is_not_paired(conn):
    add(conn, 'P', 'purchase', 12000, '2025-01-01')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    assert refund_links(conn, ['C']) == {}


@pytest.mark.parametrize('changes', [
    {'merchant': 'AGODA Y'}, {'currency': 'USD'}, {'foreign': '999.000'}, {'card': '9999'},
])
def test_another_merchant_currency_amount_or_card_is_not_paired(conn, changes):
    add(conn, 'P', 'purchase', 12000, '2026-04-01')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05', **changes)
    assert refund_links(conn, ['C']) == {}


def test_a_numbered_refund_keeps_the_approval_number_rule(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01', number='A1', foreign='')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05', original='A1', foreign='')
    link = refund_links(conn, ['C'])['C']
    assert link['original_id'] == 'P' and link['status'] == 'full'


def test_a_purchase_already_paired_by_number_is_not_reused(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01', number='A1', foreign='')
    add(conn, 'C1', 'cancellation', -12000, '2026-04-05', original='A1', foreign='')
    add(conn, 'C2', 'cancellation', -12000, '2026-04-06')
    assert refund_links(conn, ['C2']) == {}


def test_the_rule_can_be_switched_off(conn, monkeypatch):
    add(conn, 'P', 'purchase', 12000, '2026-04-01')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    monkeypatch.setattr(partial_refund, '_settings',
                        lambda: {'enabled': False, 'max_days_after_purchase': 365})
    assert refund_links(conn, ['C']) == {}


def test_a_group_does_not_collect_unrelated_blank_number_cancellations(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01', merchant='AGODA X')
    add(conn, 'OTHER', 'cancellation', -5000, '2026-04-05', merchant='TRIP Y', foreign='50.000', currency='USD')
    assert refund_group(conn, 'P') == ['P']


def test_a_group_includes_the_foreign_pair(conn):
    add(conn, 'P', 'purchase', 12000, '2026-04-01')
    add(conn, 'C', 'cancellation', -12000, '2026-04-05')
    assert refund_group(conn, 'P') == ['P', 'C']
