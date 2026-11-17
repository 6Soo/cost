"""Synthetic M4 acceptance probe for the 1,000-row transaction API path."""

from __future__ import annotations

from collections import Counter
from math import ceil
from time import perf_counter_ns

from webapp.tests.test_plush_api import bound_store, call as plush_call


def test_p08_synthetic_1000_rows_are_server_paged_filtered_and_under_200ms(
    bound_store, monkeypatch,
):
    store, _ = bound_store
    items = [
        {
            "transaction_id": f"m4-synthetic-{index:04d}",
            "approval_date": f"2026-11-{1 + index % 28:02d}",
            "amount_krw": -(index + 1) if index % 7 == 0 else index + 1,
            "merchant": "합성 가맹점",
            "description": "식사 synthetic-match" if index % 10 == 0 else "교통 synthetic-other",
            "classification_state": "classified",
        }
        for index in range(1000)
    ]
    source_calls = []

    def matching(search):
        return [
            item for item in items
            if not search or search.casefold() in item["description"].casefold()
        ]

    monkeypatch.setattr(
        "webapp.ledger_board._get_card_db_path", lambda: "m4-synthetic-card-db",
    )

    def year_summary(*, year, search, **_kwargs):
        rows = matching(search)
        return {"months": {11: len(rows)}, "undated_count": 0}

    def list_for_month(*, year, month, cursor, per_page, search, **_kwargs):
        rows = matching(search)
        offset = int(cursor) if cursor else 0
        page = rows[offset:offset + per_page]
        end = offset + len(page)
        source_calls.append((search, cursor, per_page, len(rows)))
        return {
            "items": page,
            "has_more": end < len(rows),
            "cursor": str(end) if end < len(rows) else None,
        }

    monkeypatch.setattr("webapp.card_transactions.year_summary", year_summary)
    monkeypatch.setattr("webapp.card_transactions.list_for_month", list_for_month)

    observed_ids = []
    durations_ns = []
    for page in range(1, 11):
        started = perf_counter_ns()
        status, body = plush_call(
            f"/api/plush/transactions?view=cards&period=2026-11&page={page}&page_size=100",
            "syn-owner",
            store,
        )
        durations_ns.append(perf_counter_ns() - started)
        assert status == 200
        assert body["total_count"] == 1000
        assert body["page"] == page
        assert body["page_size"] == 100
        assert len(body["rows"]) == 100
        observed_ids.extend(row["id"] for row in body["rows"])

    expected_ids = [item["transaction_id"] for item in items]
    assert observed_ids == expected_ids
    assert all(count == 1 for count in Counter(observed_ids).values())

    filtered_ids = []
    for page in (1, 2):
        status, body = plush_call(
            f"/api/plush/transactions?view=cards&period=2026-11&page={page}&page_size=50&q=synthetic-match",
            "syn-owner",
            store,
        )
        assert status == 200
        assert body["total_count"] == 100
        assert body["page"] == page
        assert len(body["rows"]) == 50
        filtered_ids.extend(row["id"] for row in body["rows"])

    expected_filtered_ids = [
        item["transaction_id"] for item in items
        if "synthetic-match" in item["description"]
    ]
    assert filtered_ids == expected_filtered_ids
    assert all(count == 1 for count in Counter(filtered_ids).values())
    assert all(call[0] == "synthetic-match" for call in source_calls if call[3] == 100)

    p95_ms = sorted(durations_ns)[ceil(0.95 * len(durations_ns)) - 1] / 1_000_000
    print(
        "P08 synthetic API probe: rows=1000, page_size=100, pages=10, "
        f"filtered_rows={len(filtered_ids)}, p95_api_ms={p95_ms:.3f}; "
        "in-process handler only, excluding HTTP network and browser rendering"
    )
    assert p95_ms < 200
