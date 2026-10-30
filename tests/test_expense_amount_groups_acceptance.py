"""Synthetic acceptance tests for shared expense amount groups API.

Tests reconcile_expense_amount_groups with bounded, independent fixtures.
Uses the integrated pure function. Provider draft reviewed by supervisor.
"""


from copy import deepcopy

import pytest

from app.expense_amount_groups import reconcile_expense_amount_groups


def cost(row_id, amount=50000, **overrides):
    """Build a COST expense row dict."""
    return {
        "row_id": row_id,
        "trip_id": "trip-a",
        "amount_krw": amount,
        "currency": "KRW",
        "date": "2026-01-01",
        "description": "cost",
        **overrides,
    }


def google(ref, amount=50000, **overrides):
    """Build a Google expense row dict."""
    return {
        "ref": ref,
        "trip_id": "trip-a",
        "amount_krw": amount,
        "currency": "KRW",
        "date": "2026-09-09",
        "payee": "other",
        **overrides,
    }


def run(cost_rows, google_rows, **kwargs):
    """Reconcile and return the output dict."""
    return reconcile_expense_amount_groups("trip-a", cost_rows, google_rows, **kwargs)


@pytest.mark.parametrize("m,n,status,candidates", [
    (1, 1, "matched", 1), (3, 3, "matched", 9), (5, 2, "partial", 10),
    (2, 0, "unrecorded", 0), (0, 2, "google_only", 0),
])
def test_cardinality_and_logical_relationship_count(m, n, status, candidates):
    """1:1, 3:3, 5:2, 2:0, 0:2 logical groups with correct candidate counts."""
    out = run([cost(f"c{i}") for i in range(m)], [google(f"g{i}") for i in range(n)])
    group = out["groups"][0]
    assert (group["status"], group["cost_count"], group["google_count"],
            group["candidate_count"]) == (status, m, n, candidates)
    assert len(group["cost_rows"]) == m
    assert len(group["google_rows"]) == n
    assert out["available"] is True


def test_repeated_distinct_rows_survive_but_explicit_same_source_copy_collapses():
    """Same source_identity collapses; distinct rows survive."""
    rows = [cost("c1", source_identity="original-1"),
            cost("c1-copy", source_identity="original-1"), cost("c2")]
    out = run(rows, [google("g1"), google("g2")])
    group = out["groups"][0]
    assert group["cost_count"] == 2
    assert [row["row_id"] for row in group["cost_rows"]] == ["c1", "c2"]
    assert group["status"] == "matched"


def test_equal_amount_date_or_merchant_never_deduplicates_without_identity():
    """Equal amount alone never deduplicates; identity required."""
    out = run([cost("c1"), cost("c2")],
              [google("g1"), google("g2", date="2026-01-01", payee="cost")])
    assert (out["groups"][0]["cost_count"], out["groups"][0]["google_count"]) == (2, 2)


def test_trip_amount_and_signed_refund_are_distinct_groups():
    """Signed amounts and different trips produce distinct groups."""
    out = run([cost("c1"), cost("c2", -50000)],
              [google("g1"), google("g2", trip_id="trip-b")])
    amounts = [(g["amount_krw"], g["cost_count"], g["google_count"])
               for g in out["groups"]]
    assert sorted(amounts) == [(-50000, 1, 0), (50000, 1, 1)]
    assert out["available"] is False


@pytest.mark.parametrize("row", [
    cost("c", currency="USD"), cost("c", amount_krw=True),
    cost("c", amount_krw=1.5), cost("c", amount_krw=float("nan")),
    cost("c", amount_krw="50000"),
])
def test_uncertain_currency_or_amount_fails_closed(row):
    """Uncertain currency/amount fails closed; no green."""
    out = run([row], [google("g")])
    assert out["available"] is False
    assert out["summary"]["unavailable"] == 1
    assert out["groups"][0]["status"] == "unavailable"


def test_source_unavailable_is_not_zero_or_green_and_keeps_context():
    """Unavailable state preserves reason and last_success_at; no green."""
    out = run([cost("c")], [], available=False, reason="STALE", last_success_at="yesterday")
    assert out["available"] is False
    assert out["reason"] == "STALE"
    assert out["last_success_at"] == "yesterday"
    assert out["groups"] == []
    # Summary should have all zeros when groups is empty
    assert all(v == 0 for v in out["summary"].values())


def test_annotations_are_small_and_inputs_are_not_mutated():
    """by_cost_id has small annotations; inputs not mutated."""
    costs, google_rows = [cost("c1"), cost("c2")], [google("g1"), google("g2")]
    before = deepcopy((costs, google_rows))
    out = run(costs, google_rows)
    assert costs == before[0] and google_rows == before[1]
    annotation = out["by_cost_id"]["c1"]
    assert annotation == {"group_id": "trip-a:50000", "status": "matched",
                          "cost_count": 2, "google_count": 2, "candidate_count": 4}
    assert "google_rows" not in annotation


def test_cost_and_google_amounts_must_be_exact_integer_types():
    """A float cannot establish an exact integer accounting amount."""
    out = run([cost("c", amount=50000.0)], [google("g", amount=50000)])
    assert out['available'] is False
    assert out["groups"][0]["status"] == "unavailable"


def test_large_repeated_groups_no_physical_pair_explosion():
    """Many repeated rows: candidate_count = m*n but no physical cross-product."""
    m, n = 1000, 1500
    out = run([cost(f"c{i}") for i in range(m)], [google(f"g{i}") for i in range(n)])
    group = out["groups"][0]
    assert group["cost_count"] == m
    assert group["google_count"] == n
    assert group["candidate_count"] == m * n
    assert len(group['cost_rows']) + len(group['google_rows']) == m + n
    # by_cost_id should have one small annotation per cost row
    assert len(out["by_cost_id"]) == m
    for ann in out["by_cost_id"].values():
        assert ann["candidate_count"] == m * n
        # Annotation must not contain embedded cross-products
        assert "google_rows" not in ann
    assert out["available"] is True


def test_different_merchant_different_date_same_amount_stay_same_group():
    """Different merchant/date do not break the trip+amount group."""
    out = run(
        [cost("c1", description="dinner", date="2026-01-01"),
         cost("c2", description="lunch", date="2026-02-01")],
        [google("g1", payee="rest", date="2026-03-01"),
         google("g2", payee="cafe", date="2026-04-01")]
    )
    assert len(out["groups"]) == 1
    g = out["groups"][0]
    assert g["status"] == "matched"
    assert g["cost_count"] == 2
    assert g["google_count"] == 2
    assert g["candidate_count"] == 4


def test_refund_sign_separates_groups():
    """Positive and negative same-amount are distinct groups."""
    out = run(
        [cost("c1", amount=50000), cost("c2", amount=-50000)],
        [google("g1", amount=50000)]
    )
    # Two groups: one for +50000, one for -50000 (google-only for negative)
    assert len(out["groups"]) == 2
    # Find the +50000 group
    pos_group = [g for g in out["groups"] if g["amount_krw"] == 50000][0]
    neg_group = [g for g in out["groups"] if g["amount_krw"] == -50000][0]
    assert pos_group["cost_count"] == 1
    assert pos_group["google_count"] == 1
    assert pos_group["status"] == "matched"
    assert neg_group["cost_count"] == 1
    assert neg_group["google_count"] == 0
    assert neg_group["status"] == "unrecorded"


def test_unavailable_never_green_no_mutation():
    """When unavailable, no groups, no green status, inputs unchanged."""
    costs_orig = [cost("c1", amount=50000), cost("c2", amount=50000)]
    google_orig = [google("g1", amount=50000)]
    before = deepcopy((costs_orig, google_orig))
    out = run(costs_orig, google_orig, available=False, reason="STALE_API")
    assert out["available"] is False
    assert out["reason"] == "STALE_API"
    assert out["groups"] == []
    assert all(v == 0 for v in out["summary"].values())
    assert costs_orig == before[0] and google_orig == before[1]


def test_summary_counts_all_statuses():
    """Summary reflects all group statuses correctly across mixed groups."""
    out = run(
        [cost("c1"), cost("c2"), cost("c3", -50000)],  # 3 cost rows
        [google("g1"), google("g2"), google("g3", trip_id="trip-b")]  # 2 cost-match + 1 diff trip
    )
    # Should have groups for: matched (2:2), unrecorded (1:0), google_only (0
