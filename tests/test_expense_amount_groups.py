from copy import deepcopy

import pytest

from app.expense_amount_groups import reconcile_expense_amount_groups


def cost(row_id, amount=50000, **overrides):
    return {"row_id": row_id, "trip_id": "trip-a", "amount_krw": amount,
            "currency": "KRW", "date": "2026-01-01", "description": "cost", **overrides}


def google(ref, amount=50000, **overrides):
    return {"ref": ref, "trip_id": "trip-a", "amount_krw": amount,
            "currency": "KRW", "date": "2026-09-09", "payee": "other", **overrides}


def run(cost_rows, google_rows, **kwargs):
    return reconcile_expense_amount_groups("trip-a", cost_rows, google_rows, **kwargs)


@pytest.mark.parametrize("m,n,status,candidates", [
    (1, 1, "matched", 1), (3, 3, "matched", 9), (5, 2, "partial", 10),
    (2, 0, "unrecorded", 0), (0, 2, "google_only", 0),
])
def test_cardinality_and_logical_relationship_count(m, n, status, candidates):
    out = run([cost(f"c{i}") for i in range(m)], [google(f"g{i}") for i in range(n)])
    group = out["groups"][0]
    assert (group["status"], group["cost_count"], group["google_count"],
            group["candidate_count"]) == (status, m, n, candidates)
    assert len(group["cost_rows"]) == m
    assert len(group["google_rows"]) == n
    assert out["available"] is True


def test_repeated_distinct_rows_survive_but_explicit_same_source_copy_collapses():
    rows = [cost("c1", source_identity="original-1"),
            cost("c1-copy", source_identity="original-1"), cost("c2")]
    out = run(rows, [google("g1"), google("g2")])
    group = out["groups"][0]
    assert group["cost_count"] == 2
    assert [row["row_id"] for row in group["cost_rows"]] == ["c1", "c2"]
    assert group["status"] == "matched"
    assert out["by_cost_id"]["c1-copy"] == out["by_cost_id"]["c1"]


@pytest.mark.parametrize("conflict", [
    {"amount_krw": 49000}, {"trip_id": "trip-b"}, {"currency": "USD"},
    {"amount_krw": True},
])
def test_conflicting_or_invalid_duplicate_projection_cannot_hide_behind_identity(conflict):
    out = run([cost("c1", source_identity="same"),
               cost("c2", source_identity="same", **conflict)], [google("g1")])
    assert out["available"] is False
    assert out["groups"][0]["status"] == "unavailable"


def test_empty_source_identity_does_not_collapse_rows():
    out = run([cost("c1", source_identity=""), cost("c2", source_identity="")],
              [google("g1")])
    assert out["groups"][0]["cost_count"] == 2
    assert out["groups"][0]["status"] == "partial"


@pytest.mark.parametrize("row_id", [None, "", 0, False, [], {}])
def test_invalid_row_ids_fail_closed_without_raising(row_id):
    out = run([cost(row_id)], [google("g1")])
    assert out["available"] is False


def test_equal_amount_date_or_merchant_never_deduplicates_without_identity():
    out = run([cost("c1"), cost("c2")],
              [google("g1"), google("g2", date="2026-01-01", payee="cost")])
    assert (out["groups"][0]["cost_count"], out["groups"][0]["google_count"]) == (2, 2)


def test_trip_amount_and_signed_refund_are_distinct_groups():
    out = run([cost("c1"), cost("c2", -50000)],
              [google("g1"), google("g2", trip_id="trip-b")])
    assert [(g["amount_krw"], g["cost_count"], g["google_count"])
            for g in out["groups"]] == [(50000, 1, 1), (-50000, 1, 0)]
    assert out["available"] is False


@pytest.mark.parametrize("row", [
    cost("c", currency="USD"), cost("c", amount_krw=True),
    cost("c", amount_krw=1.5), cost("c", amount_krw=float("nan")),
    cost("c", amount_krw="50000"),
])
def test_uncertain_currency_or_amount_fails_closed(row):
    out = run([row], [google("g")])
    assert out["available"] is False
    assert out["summary"]["unavailable"] == 1
    assert out["groups"][0]["status"] == "unavailable"


def test_source_unavailable_is_not_zero_or_green_and_keeps_context():
    out = run([cost("c")], [], available=False, reason="STALE", last_success_at="yesterday")
    assert out["available"] is False
    assert out["reason"] == "STALE"
    assert out["last_success_at"] == "yesterday"
    assert out["groups"] == []
    assert not any(out["summary"].values())


def test_annotations_are_small_and_inputs_are_not_mutated():
    costs, google_rows = [cost("c1"), cost("c2")], [google("g1"), google("g2")]
    before = deepcopy((costs, google_rows))
    out = run(costs, google_rows)
    assert costs == before[0] and google_rows == before[1]
    annotation = out["by_cost_id"]["c1"]
    assert annotation == {"group_id": "trip-a:50000", "status": "matched",
                          "cost_count": 2, "google_count": 2, "candidate_count": 4}
    assert "google_rows" not in annotation


@pytest.mark.parametrize("value", [50000.0, 2**53 * 1.0, float("inf"), float("nan")])
def test_amounts_require_exact_integer_representation(value):
    out = run([cost("c", amount=value)], [google("g", amount=50000)])
    assert out["available"] is False
