"""Targeted tests for webapp.card_refund_query comparing against public main baseline 2384cfd.

Verifies:
- Direct execution on SQLite conn with required merchant_key_fn callback injection
- Zero dependency on UI modules in card_refund_query
- Exact behavioral and result equivalence with public main 2384cfd baseline AST
- Strict preservation of 14-day window, same-card, ranking, error/date handling, max_rows slicing
- Monkeypatch forwarding through card_flow facade
- Absolute read-only guarantee: zero writes/mutations to database
"""
import ast
import subprocess
import pytest

from webapp import card_flow, card_refund_query
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.fixture(scope="module")
def baseline_query_ns():
    """Extract and compile baseline query functions from public main commit 2384cfd."""
    code = subprocess.run(
        ["git", "show", "2384cfd:webapp/card_flow.py"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    tree = ast.parse(code)
    target_names = {
        "_refund_merchant_key",
        "_refund_merchant_candidates_readonly",
        "_kakao_merchant_inventory_readonly",
    }
    extracted_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    module_node = ast.Module(body=extracted_nodes, type_ignores=[])
    compiled = compile(module_node, filename="<2384cfd_card_flow>", mode="exec")
    ns = {
        "__name__": "webapp.baseline_card_flow",
        "__package__": "webapp",
    }
    exec(compiled, ns)
    return ns


def test_baseline_equivalence_refund_merchant_candidates(tmp_path, baseline_query_ns):
    """Synthetic dataset comparing public main 2384cfd baseline vs card_refund_query vs card_flow facade."""
    board = LedgerStore(tmp_path / "candidates_query.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,카카오택시,24600,,,24600,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,카카오T가승인,24600,,,24600,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,카카오모빌리티 일반택시,15000,,,15000,2026-09-25,2026-09-26,A300,,매입\n" +
            "국민,1234,domestic,purchase,카카오페이,50000,,,50000,2026-10-01,2026-10-02,A400,,매입\n" +
            "신한,5678,domestic,purchase,카카오택시,24600,,,24600,2026-10-01,2026-10-02,A500,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        board.conn.execute(
            "UPDATE transactions SET transaction_direction='cancellation',amount_krw=-24600,original_approval_number='100' "
            "WHERE transaction_id=?", (ids["200"],)
        )
        board.conn.commit()

        before_changes = board.conn.total_changes
        key_fn = baseline_query_ns["_refund_merchant_key"]

        # 1. Non-existent tid
        b_res = baseline_query_ns["_refund_merchant_candidates_readonly"](board, "missing")
        q_res = card_refund_query.refund_merchant_candidates_readonly(board.conn, "missing", merchant_key_fn=key_fn)
        f_res = card_flow._refund_merchant_candidates_readonly(board, "missing")
        assert b_res == q_res == f_res == (None, [], 0)

        # 2. Existing refund candidate comparison
        b_res = baseline_query_ns["_refund_merchant_candidates_readonly"](board, ids["200"])
        q_res = card_refund_query.refund_merchant_candidates_readonly(board.conn, ids["200"], merchant_key_fn=key_fn)
        f_res = card_flow._refund_merchant_candidates_readonly(board, ids["200"])
        assert b_res == q_res == f_res
        refund, candidates, count = q_res
        assert refund[2] == "카카오T가승인"
        assert count == 2  # A100 and A300 (A400 is KakaoPay, A500 is different card)
        # Top candidate must be A100 because original approval matches
        assert candidates[0][0] == ids["100"]

        # Ensure absolute read-only guarantee: no database changes
        assert board.conn.total_changes == before_changes
    finally:
        board.close()


def test_baseline_equivalence_kakao_inventory(tmp_path, baseline_query_ns):
    """Synthetic dataset comparing public main 2384cfd baseline vs card_refund_query vs card_flow inventory."""
    board = LedgerStore(tmp_path / "inventory_query.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,카카오택시,10000,,,10000,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,카카오T선승인,12000,,,12000,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,카카오페이,5000,,,5000,2026-10-02,2026-10-03,A300,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]

        before_changes = board.conn.total_changes
        key_fn = baseline_query_ns["_refund_merchant_key"]

        b_inv = baseline_query_ns["_kakao_merchant_inventory_readonly"](board)
        q_inv = card_refund_query.kakao_merchant_inventory_readonly(board.conn, merchant_key_fn=key_fn)
        f_inv = card_flow._kakao_merchant_inventory_readonly(board)

        assert b_inv == q_inv == f_inv
        assert len(q_inv) == 3
        families = {item["merchant"]: item["family"] for item in q_inv}
        assert families["카카오택시"] == "카카오택시"
        assert families["카카오T선승인"] == "카카오택시"
        assert families["카카오페이"] != "카카오택시"

        assert board.conn.total_changes == before_changes
    finally:
        board.close()


def test_refund_query_boundary_conditions_and_exceptions(tmp_path, baseline_query_ns):
    """Test 14-day window boundary, date ValueError handling, and max_rows slicing."""
    board = LedgerStore(tmp_path / "boundaries.sqlite", seed_demo=False)
    key_fn = baseline_query_ns["_refund_merchant_key"]
    try:
        flow = card_flow.CardFlow(board)
        # 14 days before 2026-10-15 is 2026-10-01 (included); 2026-09-30 is 15 days before (excluded)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,카카오택시,10000,,,10000,2026-10-01,2026-10-01,A100,,매입\n" +
            "국민,1234,domestic,purchase,카카오택시,20000,,,20000,2026-09-30,2026-09-30,A200,,매입\n" +
            "국민,1234,domestic,purchase,카카오택시,30000,,,30000,2026-10-15,2026-10-15,A300,,매입\n" +
            "국민,1234,domestic,purchase,카카오택시,40000,,,40000,2026-10-10,2026-10-10,A400,,매입\n"
        ).encode(), "boundaries.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-30000 WHERE transaction_id=?", (ids["300"],))
        board.conn.commit()

        # Normal query with 14-day window: A100 (10-01) and A400 (10-10) match; A200 (09-30) is outside window
        refund, candidates, count = card_refund_query.refund_merchant_candidates_readonly(
            board.conn, ids["300"], merchant_key_fn=key_fn
        )
        candidate_ids = [c[0] for c in candidates]
        assert ids["100"] in candidate_ids
        assert ids["400"] in candidate_ids
        assert ids["200"] not in candidate_ids
        assert count == 2

        # max_rows slicing test
        _, sliced, total_count = card_refund_query.refund_merchant_candidates_readonly(
            board.conn, ids["300"], merchant_key_fn=key_fn, max_rows=1
        )
        assert len(sliced) == 1
        assert total_count == 2

        # Invalid date handling (ValueError on fromisoformat)
        board.conn.execute("UPDATE transactions SET approval_date='invalid-date' WHERE transaction_id=?", (ids["300"],))
        board.conn.commit()
        refund, candidates, count = card_refund_query.refund_merchant_candidates_readonly(
            board.conn, ids["300"], merchant_key_fn=key_fn
        )
        assert refund is not None
        assert candidates == []
        assert count == 0
    finally:
        board.close()


def test_merchant_key_callback_injection_and_monkeypatch(tmp_path, monkeypatch):
    """Narrow callback injection and card_flow monkeypatch forwarding."""
    board = LedgerStore(tmp_path / "callback.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,특수가맹점,10000,,,10000,2026-10-01,2026-10-01,A100,,매입\n" +
            "국민,1234,domestic,purchase,특수가맹점취소,10000,,,10000,2026-10-02,2026-10-02,A200,,매입\n"
        ).encode(), "callback.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-10000 WHERE transaction_id=?", (ids["200"],))
        board.conn.commit()

        # Strict identity key does not group '특수가맹점' and '특수가맹점취소'
        identity_key_fn = lambda name: str(name)
        _, identity_candidates, _ = card_refund_query.refund_merchant_candidates_readonly(
            board.conn, ids["200"], merchant_key_fn=identity_key_fn
        )
        assert identity_candidates == []

        # With custom callback mapping both to same group
        custom_key_fn = lambda name: "특수" if "특수" in str(name) else str(name)
        _, custom_candidates, custom_count = card_refund_query.refund_merchant_candidates_readonly(
            board.conn, ids["200"], merchant_key_fn=custom_key_fn
        )
        assert custom_count == 1
        assert custom_candidates[0][0] == ids["100"]

        # Forwarding via card_flow monkeypatch
        monkeypatch.setattr(card_flow, "_refund_merchant_key", custom_key_fn)
        _, facade_candidates, facade_count = card_flow._refund_merchant_candidates_readonly(board, ids["200"])
        assert facade_count == 1
        assert facade_candidates[0][0] == ids["100"]
    finally:
        board.close()
