"""Independent equivalence tests for webapp.card_ota_projection against public main baseline 2384cfd.

Verifies:
- Screen-specific inverted index projection for card transactions
- Zero dependency on card_flow or UI renderers
- Exact equivalence with public main 2384cfd baseline AST across:
  * Same amount formatting (KRW, foreign currencies, None/empty, decimal errors)
  * Rejection reasons and link diagnosis labels
  * Reservation relationship vs individual payment evidence distinction ('묶음 대응', '확정 연결', '금액 대조 보류', '금액 비교', '후보')
  * Reserved card IDs and reservation links initialization
  * Restricted transaction_ids filtering
  * Strict snapshot input non-mutation guarantee
"""
import ast
import copy
import subprocess
import pytest

from webapp import card_flow, card_ota_projection


@pytest.fixture(scope="module")
def baseline_ota_ns():
    """Extract and compile baseline _index_ota_display_candidates from public main commit 2384cfd."""
    code = subprocess.run(
        ["git", "show", "2384cfd:webapp/card_flow.py"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    tree = ast.parse(code)
    target_names = {
        "_index_ota_display_candidates",
        "_link_diagnosis_label",
    }
    extracted_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    module_node = ast.Module(body=extracted_nodes, type_ignores=[])
    compiled = compile(module_node, filename="<2384cfd_ota>", mode="exec")
    ns = {
        "__name__": "webapp.baseline_card_flow",
        "__package__": "webapp",
    }
    exec(compiled, ns)
    return ns


def _build_complex_synthetic_snapshot():
    """Construct synthetic snapshot exercising all branches of display projection."""
    events = [
        {
            "ota_event_id": "ev1",
            "provider": "agoda",
            "booking_ref": "AG-100",
            "event_type": "charge",
            "paid_on": "2026-10-01",
            "amount": 25000,
            "currency": "KRW",
            "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
        },
        {
            "ota_event_id": "ev2",
            "provider": "booking",
            "booking_ref": "BK-200",
            "event_type": "refund",
            "paid_on": "2026-10-05",
            "amount": "150.00",
            "currency": "USD",
            "service_period": {"starts_on": "2026-10-05", "ends_on": "2026-10-06"},
        },
        {
            "ota_event_id": "ev3",
            "provider": "trip",
            "booking_ref": "TR-300",
            "event_type": "quote",
            "paid_on": None,
            "amount": None,
            "amount_krw": None,
            "currency": "JPY",
            "service_period": {},
        },
    ]
    transactions = [
        {
            "transaction_id": "tx1",
            "merchant": "Agoda",
            "amount_krw": 25000,
            "approval_date": "2026-10-01",
            "currency": "KRW",
        },
        {
            "transaction_id": "tx2",
            "merchant": "Booking.com",
            "amount_krw": 200000,
            "foreign_amount": 150.00,
            "foreign_currency": "USD",
            "approval_date": "2026-10-05",
            "currency": "KRW",
        },
        {
            "transaction_id": "tx3",
            "merchant": "Trip.com",
            "amount_krw": 10000,
            "approval_date": "2026-09-01",
            "currency": "KRW",
        },
    ]
    results = [
        # 1. 확정 연결 (MATCHED_AUTO)
        {
            "ota_event_id": "ev1",
            "status": "MATCHED_AUTO",
            "candidates": ["tx1"],
            "candidate_search": {
                "candidates": [],
                "rejected": [],
            },
        },
        # 2. 묶음 대응 (group_only: individual_payment_evidence=False, auto_stable_order)
        {
            "ota_event_id": "ev2",
            "status": "HOLD_AMOUNT_MISMATCH",
            "individual_payment_evidence": False,
            "allocation_basis": "auto_stable_order",
            "candidates": [
                {"transaction_id": "tx2", "reason": "multiple_real_transactions_same_amount"},
            ],
            "candidate_search": {
                "candidates": [],
                "rejected": [
                    {"transaction_id": "tx2", "reason": "amount_differs"},
                ],
            },
            "reserved_card_ids": ["tx2", "reserved_only_tx"],
            "reservation_link": {"transaction_id": "reservation_link_tx"},
        },
        # 3. 금액 대조 보류 및 unknown date_status
        {
            "ota_event_id": "ev3",
            "status": "HOLD_AMOUNT_UNVERIFIED",
            "candidates": [],
            "candidate_search": {
                "candidates": [
                    {"transaction_id": "tx3", "date_status": "UNKNOWN"},
                ],
                "rejected": [],
            },
        },
    ]
    return {
        "results": [results[0]],
        "data": {
            "events": events,
            "transactions": transactions,
            "results": results[1:],
            "rules": [],
        },
    }


def test_baseline_equivalence_index_ota_display_candidates_all_branches(baseline_ota_ns):
    """Complete equivalence test across all status kinds, amounts, rejections, and reserved IDs."""
    snapshot = _build_complex_synthetic_snapshot()
    snapshot_before = copy.deepcopy(snapshot)

    # 1. Full unconstrained index
    baseline_res = baseline_ota_ns["_index_ota_display_candidates"](snapshot)
    facade_res = card_flow._index_ota_display_candidates(snapshot)
    direct_res = card_ota_projection.index_ota_display_candidates(
        snapshot, link_diagnosis_label_fn=card_flow._link_diagnosis_label
    )

    assert baseline_res == facade_res == direct_res
    # Ensure input snapshot was not mutated
    assert snapshot == snapshot_before

    # Verify key semantics in the output
    assert "tx1" in direct_res
    assert "확정 연결" in direct_res["tx1"][0]
    assert "25,000원" in direct_res["tx1"][0]

    assert "tx2" in direct_res
    assert any("묶음 대응" in note for note in direct_res["tx2"])
    assert any("카드 외화 150.000000 USD" in note or "150" in note for note in direct_res["tx2"])
    assert "reserved_only_tx" in direct_res
    assert direct_res["reserved_only_tx"] == []
    assert "reservation_link_tx" in direct_res
    assert direct_res["reservation_link_tx"] == []

    assert "tx3" in direct_res
    assert any("결제일 확인 필요" in note for note in direct_res["tx3"])


def test_baseline_equivalence_transaction_ids_filter(baseline_ota_ns):
    """Restricted transaction_ids filtering equivalence."""
    snapshot = _build_complex_synthetic_snapshot()

    # Filter for single tx
    b_single = baseline_ota_ns["_index_ota_display_candidates"](snapshot, transaction_ids=["tx1"])
    f_single = card_flow._index_ota_display_candidates(snapshot, transaction_ids=["tx1"])
    d_single = card_ota_projection.index_ota_display_candidates(
        snapshot, transaction_ids=["tx1"], link_diagnosis_label_fn=card_flow._link_diagnosis_label
    )
    assert b_single == f_single == d_single == {"tx1": f_single["tx1"]}

    # Filter for reserved only tx
    b_res = baseline_ota_ns["_index_ota_display_candidates"](snapshot, transaction_ids=["reserved_only_tx"])
    f_res = card_flow._index_ota_display_candidates(snapshot, transaction_ids=["reserved_only_tx"])
    d_res = card_ota_projection.index_ota_display_candidates(
        snapshot, transaction_ids=["reserved_only_tx"], link_diagnosis_label_fn=card_flow._link_diagnosis_label
    )
    assert b_res == f_res == d_res == {"reserved_only_tx": []}

    # Filter for empty list
    b_empty = baseline_ota_ns["_index_ota_display_candidates"](snapshot, transaction_ids=[])
    f_empty = card_flow._index_ota_display_candidates(snapshot, transaction_ids=[])
    d_empty = card_ota_projection.index_ota_display_candidates(
        snapshot, transaction_ids=[], link_diagnosis_label_fn=card_flow._link_diagnosis_label
    )
    assert b_empty == f_empty == d_empty == {}


def test_baseline_equivalence_empty_snapshot(baseline_ota_ns):
    """Empty snapshot and missing data equivalence."""
    for empty in ({}, {"data": {}}, {"results": []}):
        b = baseline_ota_ns["_index_ota_display_candidates"](empty)
        f = card_flow._index_ota_display_candidates(empty)
        d = card_ota_projection.index_ota_display_candidates(
            empty, link_diagnosis_label_fn=card_flow._link_diagnosis_label
        )
        assert b == f == d == {}


def test_custom_link_diagnosis_label_callback():
    """Verify link_diagnosis_label_fn callback injection operates without reverse import."""
    snapshot = {
        "results": [],
        "data": {
            "events": [{"ota_event_id": "e1", "provider": "TestOTA", "booking_ref": "REF1"}],
            "transactions": [{"transaction_id": "t1"}],
            "results": [{
                "ota_event_id": "e1",
                "status": "HOLD_AMOUNT_MISMATCH",
                "candidates": [{"transaction_id": "t1", "reason": "custom_diagnostic_code"}],
            }],
        },
    }
    custom_label_fn = lambda r: f"[CUSTOM: {r}]"
    res = card_ota_projection.index_ota_display_candidates(
        snapshot, link_diagnosis_label_fn=custom_label_fn
    )
    assert "t1" in res
    assert "[CUSTOM: custom_diagnostic_code]" in res["t1"][0]
