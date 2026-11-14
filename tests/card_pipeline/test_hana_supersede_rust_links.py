"""A Hana acquired-view upload that supersedes an approval row reads refund pairs inside its own write transaction.

An earlier row of the same file is already inserted (uncommitted) when the guard asks for the pairs. With
WEBLEDGER_LINKS_PRODUCER=rust that used to roll back the whole file (CORE_LINKS_UNCOMMITTED_ROWS); the result must be
the same as with the Python derivation. Needs the real costcore (COSTCORE_TEST_BIN), see the `costcore_bin` marker.
"""
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import Pipeline, core_links
from app.card_export_profiles import HANA_FOREIGN
from .fixtures import make_csv

REAL = os.environ.get('COSTCORE_TEST_BIN', '')


def _approval_source():
    return make_csv([['하나', '2026-10-09', '****1234', '00001111', '합성상점', 10000, '100']],
                    headers=['카드사', '이용일', '카드번호', '승인번호', '가맹점명', '승인금액', '가맹점번호'])


def _acquired_two_rows():
    other = [1, '2026-10-08', '****1234', '2222', '다른상점', 20.0, 3000, 7, 100, 10, '일본', 3110]
    same = [2, '2026-10-09', '****1234', '1111', '합성상점', 1000.5, 10000, 7, 1300, 300, '일본', 10300]
    return make_csv([other, same], headers=HANA_FOREIGN)


def _import(path):
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        pipe = Pipeline(conn)
        pipe.receive(_approval_source(), 'approval.csv')
        # a cancellation makes the guard ask for the pairs (with none, the analysis is skipped)
        conn.execute(
            "INSERT INTO transactions(transaction_id, source_hash, batch_id, issuer, card_tail, card_kind,"
            " transaction_direction, transaction_kind, approval_number, original_approval_number, approval_date,"
            " posting_date, merchant, merchant_normalized, amount_krw, foreign_amount, foreign_currency,"
            " description_raw, row_index, raw_row_json, parse_error, classification_state, classification_basis,"
            " created_at) SELECT 'syn-cancel', 'h', batch_id, issuer, card_tail, card_kind, 'cancellation', '취소',"
            " '', '9999', approval_date, posting_date, merchant, merchant_normalized, -500, foreign_amount,"
            " foreign_currency, description_raw, 99, raw_row_json, '', classification_state, classification_basis,"
            " created_at FROM transactions LIMIT 1")
        result = pipe.receive(_acquired_two_rows(), 'acquired.csv')
        rows = conn.execute('SELECT transaction_id, amount_krw, duplicate_of, conflict_reason FROM transactions '
                            'ORDER BY transaction_id').fetchall()
    return result['inserted'], rows


@pytest.mark.costcore_bin
def test_the_superseding_upload_is_not_rolled_back_and_equals_python(monkeypatch, tmp_path):
    if not REAL or not Path(REAL).is_file():
        pytest.skip('COSTCORE_TEST_BIN not set')
    monkeypatch.delenv(core_links.PRODUCER_ENV, raising=False)
    expected = _import(tmp_path / 'python.sqlite')
    assert expected[0] == 2 and any(row[2] for row in expected[1])  # the approval row was set aside as a duplicate
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    monkeypatch.setenv(core_links.BIN_ENV, REAL)
    core_links.clear_cache()
    sent = []
    original = core_links._run
    monkeypatch.setattr(core_links, '_run', lambda binary, path, rows=None: (sent.append(rows), original(binary, path, rows))[1])
    got = _import(tmp_path / 'rust.sqlite')
    assert got == expected
    assert any(rows is not None for rows in sent)  # the uncommitted rows travelled on stdin
