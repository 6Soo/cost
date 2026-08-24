import unittest

try:
    from tools.agoda_windows_cdp_capture import SHARDS, shard_for
    from tools.agoda_windows_cdp_detail import _synthetic_detail_tree, _worker_plan

    _IMPORT_ERROR = None
except ImportError as _e:  # retired dependencies
    _IMPORT_ERROR = str(_e)
    SHARDS = []  # type: ignore[assignment]

    def _missing(*_a, **_kw):  # type: ignore[no-redef]
        raise unittest.SkipTest(f"retired tool missing: {_IMPORT_ERROR}")

    shard_for = _missing  # type: ignore[assignment]
    _synthetic_detail_tree = _missing  # type: ignore[assignment]
    _worker_plan = _missing  # type: ignore[assignment]


def test_logical_worker_plan_has_one_upcoming_and_nine_completed_slots():
    key = b"k" * 32
    cards = [
        {
            "tab_name": "Upcoming",
            "booking_id": "100000001",
            "booking_pseudonym_hmac": "u",
            "shard_label": "U01",
        },
        {
            "tab_name": "Completed",
            "booking_id": "100000002",
            "booking_pseudonym_hmac": "c",
            "shard_label": shard_for("Completed", "100000002", key),
        },
    ]
    plan = _worker_plan(cards)
    assert list(plan) == list(SHARDS)
    assert plan["U01"]["tab_name"] == "Upcoming"
    assert all(plan[label]["tab_name"] == "Completed" for label in SHARDS[1:])
    assert sum(item["assignment_count"] for item in plan.values()) == 2


def test_synthetic_detail_tree_contains_only_parser_nodes():
    tree = _synthetic_detail_tree(["Booking ID", "100000001", "USD 10.00"])
    assert tree.splitlines() == [
        "0 텍스트 Booking ID",
        "1 텍스트 100000001",
        "2 텍스트 USD 10.00",
    ]
    assert "manage_href" not in tree
