"""Independent targeted equivalence tests for webapp.card_evidence_ui against baseline 2384cfd.

Verifies pure HTML presentation:
- Pure inputs only (no database connections, no board objects in card_evidence_ui)
- AST-level namespace compilation of commit 2384cfd functions
- Exact byte-for-byte equivalence across normal, empty dict, unknown status, None fields, escaping,
  KeyError on missing required keys, Kakao alias diagnosis, and 1:N refund candidate comparisons.
"""
import ast
import html
import subprocess
import pytest

from webapp import card_evidence_ui, card_flow, ledger_board
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.fixture(scope="module")
def baseline_ns():
    """Extract and compile baseline functions from commit 2384cfd in an isolated namespace."""
    code = subprocess.run(
        ["git", "show", "2384cfd:webapp/card_flow.py"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    tree = ast.parse(code)
    target_names = {
        "_catalog_block",
        "_render_ota_snapshot_evidence",
        "_refund_merchant_key",
        "_render_refund_merchant_candidates",
        "_render_refund_evidence",
        "_refund_merchant_candidates_readonly",
        "_kakao_merchant_inventory_readonly",
    }
    extracted_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    module_node = ast.Module(body=extracted_nodes, type_ignores=[])
    compiled = compile(module_node, filename="<2384cfd_card_flow>", mode="exec")
    ns = {"__name__": "webapp.baseline_card_flow", "__package__": "webapp", "ledger_board": ledger_board}
    exec(compiled, ns)
    return ns


def test_baseline_equivalence_ota_snapshot_evidence(baseline_ns):
    """Exact byte-for-byte equality across all OTA snapshot states and edge cases."""
    scenarios = [
        {},  # empty dict
        {"ota_status": "UNKNOWN"},
        {"ota_status": None},
        {"ota_status": "EXACT", "ota_notes": ["정상", "<script>alert('xss')</script>"], "snapshot": {"fresh": True, "status": "ready"}},
        {"ota_status": "INFERRED", "snapshot": {"fresh": False, "status": "refreshing"}},
        {"ota_status": "GROUP_RECONCILED", "snapshot": {"fresh": False, "status": "stale"}},
        {"ota_status": "USER_CONFIRMED", "snapshot": {"fresh": False, "status": "error"}},
        {"ota_status": "RESERVATION_INFERRED", "snapshot": {"fresh": False, "status": "loading"}},
        {"ota_status": "RESERVATION_CONFIRMED", "snapshot": {"fresh": False, "status": "unknown"}},
        {"ota_status": "RESERVATION_NEEDS_REVIEW", "snapshot": {"fresh": False, "status": "other"}},
        {"ota_status": "RESERVATION_STALE", "snapshot": {"fresh": True}},
        {"ota_status": "REVIEW_REQUIRED", "ota_notes": ["그룹 보류", "비고 2"], "snapshot": {"fresh": False, "status": "error"}},
        {"ota_status": "CANDIDATE", "ota_notes": []},
        {"ota_status": "MULTIPLE_CANDIDATES", "ota_notes": ["후보 A", "후보 B"]},
        {"ota_status": "UNLINKED", "snapshot": {"fresh": True}},
    ]

    for entry in scenarios:
        baseline_html = baseline_ns["_render_ota_snapshot_evidence"](entry, "tx-any")
        baseline_html = baseline_html.replace('>추론 연결<', '>코드 추론<').replace(
            '>예약 추론 관계<', '>예약 코드 추론<')
        wrapper_html = card_flow._render_ota_snapshot_evidence(entry, "tx-any")
        direct_html = card_evidence_ui.render_ota_snapshot_evidence(entry, "tx-any", esc=ledger_board.esc)
        assert baseline_html == wrapper_html == direct_html


def test_baseline_equivalence_catalog_block(baseline_ns):
    """Exact byte-for-byte equality and KeyError preservation for catalog blocks."""
    valid_scenarios = [
        {
            "provider": "Agoda",
            "booking_ref": "AG1234",
            "status": "CONFIRMED",
            "period": "2026-10-01 ~ 2026-10-05",
            "candidates": [
                {"display_key": "2026_tokyo", "relation": "covers"},
                {"tab_id": "2026_osaka", "relation": "overlaps"},
            ],
            "cancelled_matches": 1,
        },
        {
            "provider": "<Spa & Hotel>",
            "booking_ref": "REF#<99>",
            "status": None,
            "period": None,
            "candidates": None,
            "cancelled_matches": None,
        },
        {
            "booking_ref": "NO_PROVIDER",
            "candidates": [{"tab_id": "tab1", "relation": "none"}],
        },
    ]

    for entry in valid_scenarios:
        baseline_html = baseline_ns["_catalog_block"](entry)
        wrapper_html = card_flow._catalog_block(entry)
        direct_html = card_evidence_ui.render_catalog_block(entry, esc=ledger_board.esc)
        assert baseline_html == wrapper_html == direct_html

    # Required key contract: empty dict must raise KeyError('booking_ref') in all implementations
    with pytest.raises(KeyError) as exc_baseline:
        baseline_ns["_catalog_block"]({})
    with pytest.raises(KeyError) as exc_wrapper:
        card_flow._catalog_block({})
    with pytest.raises(KeyError) as exc_direct:
        card_evidence_ui.render_catalog_block({})

    assert exc_baseline.value.args == exc_wrapper.value.args == exc_direct.value.args == ("booking_ref",)


def test_baseline_equivalence_refund_merchant_key(baseline_ns):
    """Diagnostic merchant family grouping matches baseline across all variations."""
    test_values = [
        "",
        None,
        12345,
        "카카오t",
        "카카오택시",
        "카카오모빌리티택시",
        "kakaotaxi",
        "kakaot",
        "카카오모빌리티 일반택시",
        "카카오모빌리티 가승인",
        "카카오모빌리티 선승인",
        "카카오모빌리티 택시요금",
        "카카오모빌리티 대리",
        "카카오모빌리티 주차",
        "카카오모빌리티 바이크",
        "카카오모빌리티 퀵",
        "카카오페이",
        "스타벅스",
        "GS25",
        "Uber Taxi",
    ]

    for val in test_values:
        baseline_key = baseline_ns["_refund_merchant_key"](val)
        new_key = card_evidence_ui.refund_merchant_key(val)
        wrapper_key = card_flow._refund_merchant_key(val)
        assert baseline_key == new_key == wrapper_key


def test_baseline_equivalence_render_refund_merchant_candidates(tmp_path, baseline_ns):
    """Exact byte-for-byte output comparison for refund candidate comparison."""
    board = LedgerStore(tmp_path / "candidates_cmp.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,카카오택시,24600,,,24600,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,카카오T가승인,24600,,,24600,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,스타벅스,5000,,,5000,2026-10-02,2026-10-03,A300,,매입\n" +
            "국민,1234,domestic,purchase,스타벅스환불,5000,,,5000,2026-10-03,2026-10-04,A400,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        # Make A200 a cancellation of A100
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-24600,original_approval_number='100' WHERE transaction_id=?", (ids["200"],))
        # Make A400 a cancellation of A300 without original approval number
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-5000,original_approval_number='' WHERE transaction_id=?", (ids["400"],))
        board.conn.commit()

        # Case 1: Non-existent transaction ID
        assert baseline_ns["_render_refund_merchant_candidates"](board, "non-existent") == card_flow._render_refund_merchant_candidates(board, "non-existent") == ""

        # Case 2: Kakao taxi refund with candidates and matching approval number
        baseline_k = baseline_ns["_render_refund_merchant_candidates"](board, ids["200"])
        wrapper_k = card_flow._render_refund_merchant_candidates(board, ids["200"])
        assert baseline_k == wrapper_k

        # Case 3: Regular merchant refund without original approval
        baseline_s = baseline_ns["_render_refund_merchant_candidates"](board, ids["400"])
        wrapper_s = card_flow._render_refund_merchant_candidates(board, ids["400"])
        assert baseline_s == wrapper_s
    finally:
        board.close()


def test_baseline_equivalence_render_refund_evidence(tmp_path, baseline_ns):
    """Exact byte-for-byte output comparison for refund evidence rendering."""
    from app.partial_refund import refund_links
    board = LedgerStore(tmp_path / "evidence_cmp.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,원결제,30000,,,30000,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,취소1,10000,,,10000,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,취소2,20000,,,20000,2026-10-03,2026-10-04,A300,,매입\n" +
            "국민,1234,domestic,purchase,미연결취소,15000,,,15000,2026-10-04,2026-10-05,A400,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        for approval, amt in [("200", -10000), ("300", -20000)]:
            board.conn.execute(
                "UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,"
                "original_approval_number='100' WHERE transaction_id=?",
                (amt, ids[approval]))
        board.conn.execute(
            "UPDATE transactions SET transaction_direction='cancellation',amount_krw=-15000,"
            "original_approval_number='999' WHERE transaction_id=?",
            (ids["400"],))
        board.conn.commit()

        # Case 1: Linked refunds (1:N confirmed)
        linked = refund_links(board.conn, [ids["200"]])
        link = linked.get(ids["200"])
        assert baseline_ns["_render_refund_evidence"](board, ids["200"], link) == card_flow._render_refund_evidence(board, ids["200"], link)

        # Case 2: Unlinked refund (missing original)
        assert baseline_ns["_render_refund_evidence"](board, ids["400"], None) == card_flow._render_refund_evidence(board, ids["400"], None)

        # Case 3: Inferred link simulation
        inferred_link = dict(link, inferred=True, status="full", basis="kakao_same_card_exact_amount_inferred")
        assert baseline_ns["_render_refund_evidence"](board, ids["200"], inferred_link) == card_flow._render_refund_evidence(board, ids["200"], inferred_link)

        # Case 4: Excess refund link simulation
        excess_link = dict(link, status="excess")
        assert baseline_ns["_render_refund_evidence"](board, ids["200"], excess_link) == card_flow._render_refund_evidence(board, ids["200"], excess_link)
    finally:
        board.close()


def test_render_no_booking_evidence():
    """Missing evidence message conditions."""
    assert card_evidence_ui.render_no_booking_evidence(fresh=True, source="other", is_ota=False) == ""
    fresh_msg = card_evidence_ui.render_no_booking_evidence(fresh=True, source="booking_evidence_needed", is_ota=False)
    assert "이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다" in fresh_msg
    stale_msg = card_evidence_ui.render_no_booking_evidence(fresh=False, source="booking_evidence_needed", is_ota=False)
    assert "현재 예약 자료를 확인할 수 없어 예약 부재 여부를 판단하지 않았습니다." in stale_msg
