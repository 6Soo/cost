"""Targeted authenticated projection tests for the Plush API."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from webapp import access_control
from webapp import ledger_board
from webapp import plush_api
from webapp.ledger_store import LedgerStore


class Handler:
    command = "GET"

    def __init__(self, user: str | None):
        self.headers = {}
        if user:
            self.headers[access_control.SyntheticSessionAdapter.HEADER] = user
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


@pytest.fixture()
def bound_store(tmp_path):
    store = LedgerStore(tmp_path / "plush.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0], query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


def test_bootstrap_and_ledger_are_structured_and_use_string_amounts(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/bootstrap", "syn-owner", store)
    assert status == 200
    assert body["role"] == "owner"
    assert body["trips"]
    assert all(isinstance(item["expense"], str) for item in body["trips"])

    status, ledger = call("/api/plush/ledger?tab=trip-demo-a&page_size=2&sort=amount_desc", "syn-owner", store)
    assert status == 200
    assert ledger["page_size"] == 2
    assert all(isinstance(item["amount"], str) for item in ledger["rows"])
    assert "operator_note" not in json.dumps(ledger, ensure_ascii=False)


def test_row_detail_has_owner_actions_but_no_legacy_html_href(bound_store):
    store, _ = bound_store
    status, detail = call("/api/plush/row?id=expense-demo-c1", "syn-owner", store)
    assert status == 200
    assert detail["actions"]
    assert all(action["href"].startswith("/api/") for action in detail["actions"])
    assert detail["expected_revision"]
    assert detail["expected_revision"] == detail["row"]["revision"]
    assert {field["name"] for field in detail["edit_fields"]} == {
        "display_tab_id", "item", "description", "operator_note",
    }
    save = next(action for action in detail["actions"] if action["id"] == "row-save")
    revision_field = next(field for field in save["fields"] if field["name"] == "expected_revision")
    assert revision_field["type"] == "hidden"
    assert revision_field["value"] == detail["expected_revision"]
    trip_field = next(field for field in save["fields"] if field["name"] == "display_tab_id")
    assert trip_field["options"]


def test_row_detail_uses_display_correction_and_keeps_raw_detail(bound_store, monkeypatch):
    store, _ = bound_store
    raw = store.get_row("expense-demo-c1")
    assert raw is not None
    original_projected = store.projected

    def project_with_manual_correction(row):
        projected = original_projected(row)
        if row["row_id"] == raw["row_id"]:
            projected["display_amount_krw"] = 76543
            projected["display_occurred_on"] = "2026-11-16"
        return projected

    monkeypatch.setattr(store, "projected", project_with_manual_correction)
    status, ledger = call(f"/api/plush/ledger?tab={raw['display_tab_id']}", "syn-owner", store)
    assert status == 200
    listed = next(row for row in ledger["rows"] if row["id"] == raw["row_id"])

    status, detail = call(f"/api/plush/row?id={raw['row_id']}", "syn-owner", store)
    assert status == 200
    assert detail["row"]["amount"] == listed["amount"] == "76543"
    assert detail["row"]["date"] == listed["date"] == "2026-11-16"
    assert detail["row"]["currency"] == "KRW"
    assert detail["detail"]["amount_krw"] == raw["amount_krw"]
    assert detail["detail"]["occurred_on"] == raw["occurred_on"]


def test_ledger_category_and_totals_follow_kind_and_search(bound_store, monkeypatch):
    store, _ = bound_store
    rows = [
        {"row_id": "expense-a", "row_kind": "expense", "display_tab_id": "trip-demo-a",
         "occurred_on": "2026-11-10", "amount_krw": 1200, "item": "식비",
         "classification_state": "classified", "revision": 3},
        {"row_id": "income-a", "row_kind": "income", "display_tab_id": "trip-demo-a",
         "occurred_on": "2026-11-11", "amount_krw": 5000, "income_kind": "가이드비",
         "customer_name": "합성 고객", "classification_state": "classified", "revision": 4},
        {"row_id": "expense-b", "row_kind": "expense", "display_tab_id": "trip-demo-a",
         "occurred_on": "2026-11-12", "amount_krw": 800, "item": "교통비",
         "classification_state": "classified", "revision": 2},
    ]
    monkeypatch.setattr(store, "list_tab_rows", lambda _tab: rows)
    monkeypatch.setattr(store, "projected", lambda row: row)

    status, expense = call(
        "/api/plush/ledger?tab=trip-demo-a&kind=expense&q=%EC%8B%9D%EB%B9%84",
        "syn-owner", store,
    )
    assert status == 200
    assert [row["category"] for row in expense["rows"]] == ["식비"]
    assert expense["filtered_total"] == "1200"
    assert expense["total"] == "2000"

    status, all_expenses = call("/api/plush/ledger?tab=trip-demo-a&kind=expense", "syn-owner", store)
    assert status == 200
    assert {row["category"] for row in all_expenses["rows"]} == {"식비", "교통비"}
    assert all_expenses["total_count"] == 2
    assert all_expenses["filtered_total"] == "2000"
    assert all_expenses["total"] == "2000"

    status, income = call("/api/plush/ledger?tab=trip-demo-a&kind=income", "syn-owner", store)
    assert status == 200
    assert [row["category"] for row in income["rows"]] == ["가이드비"]
    assert income["total_count"] == 1
    assert income["filtered_total"] == "5000"
    assert income["total"] == "5000"


def test_viewer_does_not_receive_receipt_capability(bound_store, monkeypatch):
    store, access = bound_store
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER)
    monkeypatch.setattr("webapp.receipt_review.enabled", lambda: True)

    status, owner = call("/api/plush/bootstrap", "syn-owner", store)
    assert status == 200
    assert owner["receipt_enabled"] is True

    status, viewer = call("/api/plush/bootstrap", "syn-viewer", store)
    assert status == 200
    assert viewer["receipt_enabled"] is False
    assert "receipt.read" not in viewer["capabilities"]


def test_card_transactions_keep_krw_amount_and_follow_all_cursor_pages(
    bound_store, monkeypatch,
):
    store, _ = bound_store
    all_items = [
        {
            "transaction_id": f"card-{index:03d}",
            "approval_date": f"2026-11-{1 + index // 50:02d}",
            "amount_krw": 135000 if index == 500 else 1000 + index,
            "foreign_amount": "100.00" if index == 500 else None,
            "foreign_currency": "USD" if index == 500 else None,
            "merchant": "합성 가맹점",
            "description": "합성 거래",
            "classification_state": "classified",
        }
        for index in range(550)
    ]
    calls = []

    monkeypatch.setattr(
        "webapp.ledger_board._get_card_db_path", lambda: "synthetic-card-db",
    )
    monkeypatch.setattr(
        "webapp.card_transactions.year_summary",
        lambda **_kwargs: {"months": {"11": 550}},
    )

    def list_for_month(*, cursor, per_page, **_kwargs):
        offset = int(cursor) if cursor else 0
        calls.append((cursor, per_page))
        items = all_items[offset:offset + per_page]
        end = offset + len(items)
        return {
            "items": items,
            "has_more": end < len(all_items),
            "cursor": str(end) if end < len(all_items) else None,
        }

    monkeypatch.setattr("webapp.card_transactions.list_for_month", list_for_month)
    status, result = call(
        "/api/plush/transactions?view=cards&year=2026&month=11&page=11&page_size=50",
        "syn-owner", store,
    )
    assert status == 200
    assert result["total_count"] == 550
    assert [row["id"] for row in result["rows"]] == [
        f"card-{index:03d}" for index in range(500, 550)
    ]
    assert calls == [(None, 500), ("500", 50)]
    first = result["rows"][0]
    assert first["amount"] == first["amount_krw"] == "135000"
    assert first["currency"] == "KRW"
    assert first["foreign_amount"] == "100.00"
    assert first["foreign_currency"] == "USD"


def test_ledger_row_does_not_pair_krw_display_amount_with_source_currency():
    row = plush_api.projection.ledger_row({
        "row_id": "card-usd",
        "row_kind": "expense",
        "occurred_on": "2026-11-16",
        "amount_krw": 135000,
        "display_amount_krw": 135000,
        "foreign_amount": "100",
        "foreign_currency": "USD",
        "currency": "USD",
    })
    assert row["amount"] == "135000"
    assert row["currency"] == "KRW"
    assert row["source_amount"] == "100"
    assert row["source_currency"] == "USD"


def test_viewer_projection_uses_access_allowlist(bound_store, monkeypatch):
    store, access = bound_store
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER)
    monkeypatch.setattr(access, "visible_tabs", lambda user_id: {"trip-demo-a"})
    status, body = call("/api/plush/bootstrap", "syn-viewer", store)
    assert status == 200
    assert body["role"] == "viewer"
    assert [trip["id"] for trip in body["trips"]] == ["trip-demo-a"]
    status, _ = call("/api/plush/ledger?tab=trip-demo-b", "syn-viewer", store)
    assert status == 404


def test_viewer_without_a_valid_session_cannot_fallback_to_owner(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/bootstrap", "unknown-user", store)
    assert status == 401
    assert body["code"] == access_control.AUTH_REQUIRED


def test_non_plush_path_is_left_for_the_board_dispatch(bound_store):
    store, _ = bound_store
    handler = Handler("syn-owner")
    assert plush_api.dispatch(handler, SimpleNamespace(path="/board", query=""), board=store) is False
    assert not handler.responses


def test_transactions_without_a_card_source_report_unavailable_not_fake_rows(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/transactions?view=cards", "syn-owner", store)
    assert status == 200
    assert body["rows"] == []
    assert body["status"]["code"] == "SOURCE_UNAVAILABLE"


def test_card_query_period_filters_and_cursor_contract(bound_store, monkeypatch):
    store, _ = bound_store
    calls = {"summary": [], "year": [], "month": [], "undated": []}
    monkeypatch.setattr("webapp.ledger_board._get_card_db_path", lambda: "synthetic-card-db")

    def summary(*, year, **filters):
        calls["summary"].append((year, filters))
        return {"months": {"05": 4, "06": 2}, "undated_count": 3}

    monkeypatch.setattr("webapp.card_transactions.year_summary", summary)

    def search_for_year(*, year, cursor, per_page, known_total, **filters):
        calls["year"].append((year, cursor, per_page, known_total, filters))
        return {"items": [{"transaction_id": "year-result", "amount_krw": 1000}],
                "has_more": False, "cursor": None}

    def list_for_month(*, year, month, cursor, per_page, **filters):
        calls["month"].append((year, month, cursor, per_page, filters))
        return {"items": [{"transaction_id": "month-result", "amount_krw": 2000}],
                "has_more": False, "cursor": None}

    undated_items = [
        {"transaction_id": f"undated-{index}", "amount_krw": 3000 + index}
        for index in range(3)
    ]

    def undated_list(*, year, cursor, per_page, known_total, **filters):
        calls["undated"].append((year, cursor, per_page, known_total, filters))
        if cursor is None:
            offset = 0
        elif cursor == "0000-00-00|after-id":
            offset = 1
        else:
            offset = int(cursor.split("|", 1)[1]) + 1
        items = undated_items[offset:offset + per_page]
        end = offset + len(items)
        has_more = end < len(undated_items)
        return {"items": items, "has_more": has_more,
                "cursor": f"0000-00-00|{end - 1}" if items and has_more else None}

    monkeypatch.setattr("webapp.card_transactions.search_for_year", search_for_year)
    monkeypatch.setattr("webapp.card_transactions.list_for_month", list_for_month)
    monkeypatch.setattr("webapp.card_transactions.undated_list", undated_list)

    status, all_year = call(
        "/api/plush/transactions?view=cards&period=2026&card=card-key&card_kind=legacy&q=meal&cursor=2026-05-05%7Cafter-id&page_size=2",
        "syn-owner", store,
    )
    assert status == 200
    assert all_year["total_count"] == 6
    assert [row["id"] for row in all_year["rows"]] == ["year-result"]
    assert calls["summary"][-1] == (
        2026, {"db_path": "synthetic-card-db", "card": "card-key", "search": "meal"},
    )
    assert calls["year"][-1] == (
        2026, "2026-05-05|after-id", 2, 6,
        {"db_path": "synthetic-card-db", "card": "card-key", "search": "meal"},
    )

    status, month = call(
        "/api/plush/transactions?view=cards&period=2026-05&page_size=2",
        "syn-owner", store,
    )
    assert status == 200
    assert month["total_count"] == 4
    assert calls["month"][-1] == (
        2026, 5, None, 2, {"db_path": "synthetic-card-db", "card": "", "search": ""},
    )

    status, undated = call(
        "/api/plush/transactions?view=cards&year=2026&month=5&undated=1&undated_cursor=0000-00-00%7Cafter-id&page_size=2",
        "syn-owner", store,
    )
    assert status == 200
    assert undated["total_count"] == 3
    assert [row["id"] for row in undated["rows"]] == ["undated-1", "undated-2"]
    assert calls["undated"][-1] == (
        2026, "0000-00-00|after-id", 2, 3,
        {"db_path": "synthetic-card-db", "card": "", "search": ""},
    )

    status, undated_page_two = call(
        "/api/plush/transactions?view=cards&year=2026&undated=1&page=2&page_size=2",
        "syn-owner", store,
    )
    assert status == 200
    assert undated_page_two["total_count"] == 3
    assert [row["id"] for row in undated_page_two["rows"]] == ["undated-2"]


def test_row_save_descriptor_matches_store_allowlist_and_revision(bound_store, monkeypatch):
    store, _ = bound_store
    rows = {
        "card-expense": {
            "row_id": "card-expense", "row_kind": "expense", "source_kind": "카드",
            "display_tab_id": "trip-demo-a", "occurred_on": "2026-11-16",
            "amount_krw": 1234, "item": "교통", "description": "카드 내역",
            "operator_note": "메모", "revision": 7,
        },
        "bank-income": {
            "row_id": "bank-income", "row_kind": "income", "source_kind": "은행",
            "display_tab_id": "trip-demo-a", "occurred_on": "2026-11-16",
            "amount_krw": 4321, "customer_id": "cust-1", "customer_name": "합성 고객",
            "nickname": "가명", "income_kind": "잔금", "revision": 8,
        },
        "allocation": {
            "row_id": "allocation", "row_kind": "income", "source_kind": "배분",
            "is_allocation": True, "display_tab_id": "trip-demo-a",
            "customer_id": "cust-2", "customer_name": "합성 배분", "nickname": "별칭",
            "income_kind": "예약금", "revision": 9,
        },
        "cash-expense": {
            "row_id": "cash-expense", "row_kind": "expense", "source_kind": "수기",
            "display_tab_id": "trip-demo-a", "occurred_on": "2026-11-01",
            "amount_krw": 1000, "item": "교통비", "revision": 10,
        },
    }
    monkeypatch.setattr(store, "get_row", lambda row_id: rows.get(row_id))

    def projected(row):
        if row["row_id"] == "cash-expense":
            return {**row, "display_occurred_on": "2026-11-02", "display_amount_krw": 2000}
        return row

    monkeypatch.setattr(store, "projected", projected)

    expected = {
        "card-expense": {"display_tab_id", "item", "description", "operator_note"},
        "bank-income": {"customer_id", "customer_name", "nickname", "display_tab_id",
                        "operator_note", "income_kind"},
        "allocation": {"customer_id", "customer_name", "nickname", "display_tab_id",
                       "income_kind"},
        "cash-expense": {"display_tab_id", "item", "description", "operator_note",
                         "occurred_on", "amount_krw"},
    }
    for row_id, allowed in expected.items():
        status, detail = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
        assert status == 200
        assert {field["name"] for field in detail["edit_fields"]} == allowed
        action = next(item for item in detail["actions"] if item["id"] == "row-save")
        fields = {field["name"]: field for field in action["fields"]}
        assert fields["expected_revision"]["value"] == rows[row_id]["revision"]
        assert fields["change_mode"]["options"] == [
            {"value": "exception", "label": "예외 사항"},
            {"value": "rule_change", "label": "규칙 변경"},
        ]
        assert len(fields["client_request_id"]["value"]) == 32
        assert allowed <= set(fields)
        if row_id == "cash-expense":
            assert fields["occurred_on"]["value"] == "2026-11-02"
            assert fields["amount_krw"]["value"] == 2000
        else:
            assert "occurred_on" not in fields
            assert "amount_krw" not in fields


def test_profile_auxiliary_forms_rules_and_card_upload_descriptors(bound_store, monkeypatch):
    store, _ = bound_store

    status, profile = call("/api/plush/admin?view=profile", "syn-owner", store)
    assert status == 200
    profile_fields = {field["name"]: field for field in profile["fields"]}
    assert "assignee_name" in profile_fields
    assert "default_assignee" not in profile_fields
    assert len(profile_fields["client_request_id"]["value"]) == 32
    assert profile_fields["expected_revision"]["value"] == profile["data"]["revision"]

    status, expense = call("/api/plush/auxiliary?view=expense-new", "syn-owner", store)
    assert status == 200
    expense_action = expense["actions"][0]
    assert expense_action["href"] == "/api/expenses/manual"
    assert expense_action["method"] == "POST"
    assert expense_action["encoding"] == "json"
    assert expense_action["csrf"] == "header"
    expense_fields = {field["name"]: field for field in expense_action["fields"]}
    assert set(expense_fields) == {
        "display_tab_id", "occurred_on", "pay_method", "item", "description",
        "amount_krw", "operator_note", "client_request_id",
    }
    assert expense_fields["display_tab_id"]["options"]
    assert len(expense_fields["client_request_id"]["value"]) == 32

    status, income = call("/api/plush/auxiliary?view=income-new", "syn-owner", store)
    assert status == 200
    income_action = income["actions"][0]
    assert income_action["href"] == "/api/income"
    assert income_action["method"] == "POST"
    assert income_action["encoding"] == "json"
    assert income_action["csrf"] == "header"
    income_fields = {field["name"]: field for field in income_action["fields"]}
    assert set(income_fields) == {
        "display_tab_id", "occurred_on", "amount_krw", "income_kind", "customer_name",
        "nickname", "operator_note", "client_request_id",
    }
    assert {option["value"] for option in income_fields["income_kind"]["options"]} == {
        "deposit", "balance", "additional",
    }

    monkeypatch.setattr(store, "list_rules", lambda: [{
        "rule_id": "rule-synthetic", "version": 2, "status": "active",
        "rule": {"conditions": {"merchant_normalized": "합성 상점", "card_kind": "국내"},
                 "effects": {"item": "교통비"}},
        "apply_existing": False, "apply_future": True,
    }])
    def dialog_page_state(case_id):
        return {
            "case_id": case_id, "row_id": "expense-demo-c1", "row_revision": 4,
            "dialog_state": "open", "questions": [{
                "question_id": "q-1", "question_key": "scope", "prompt": "어디에 적용할까요?",
                "options": ["이 행만", "기존과 미래"], "answer": None, "answered": False,
                "source_raw": "RAW-SOURCE",
            }], "answers": {"scope": "이 행만"}, "open_questions": ["scope"],
            "note": "safe note", "should_not_create_rule": False, "one_off": False,
            "provider": {"provider": "synthetic-fixture", "is_real_call": False,
                         "api_token": "SECRET-TOKEN"},
            "conversation": {
                "conversation_id": "conv-case-1", "case_id": case_id, "state": "answered",
                "active_provider": "synthetic-fixture", "active_model_id": "fixture-model",
                "turn_count": 1, "handoff_summary": "RAW-SOURCE",
                "turns": [{"turn_id": "turn-1", "state": "answered",
                           "state_label": "완료", "adopted_provider": "synthetic-fixture",
                           "reason_code": "OK", "is_real_call": False, "switch_count": 0,
                           "created_at": "2026-11-16", "attempts": [{"send_error": "SECRET-TOKEN"}],
                           "draft": {"source": "RAW-SOURCE"}}],
            },
            "pending_draft": {"rule_id": "rule-1", "turn_id": "turn-1", "confirmed": False,
                              "rule": {"conditions": {"merchant_normalized": "합성 가맹점"},
                                       "effects": {"item": "교통비"}},
                              "draft_error": {"code": "INVALID_VALUE", "message": "RAW-SOURCE"}},
            "rule": {"rule_id": "rule-1", "version": 1, "status": "draft",
                     "rule": {"conditions": {"merchant_normalized": "합성 가맹점"},
                              "effects": {"item": "교통비"}, "raw_json": "RAW-SOURCE"}},
            "last_preview": {"preview_id": "preview-1", "rule_id": "rule-1",
                             "apply_existing": True, "apply_future": False,
                             "plan": {"counts": {"matched_rows": 2, "included_rows": 1,
                                                 "excluded_rows": 1},
                                      "candidates": [{"row_id": "row-a", "from_tab_id": "trip-a",
                                                      "to_tab_id": "trip-b", "amount_krw": 1000,
                                                      "source_raw": "RAW-SOURCE"}],
                                      "excluded": [{"row_id": "row-b", "reason": "RULE_CONFLICT",
                                                    "source_raw": "RAW-SOURCE"}],
                                      "amounts": {"trip-a": {"before": 2000, "moving_out": 1000,
                                                             "moving_in": 0, "after": 1000,
                                                             "source_raw": "RAW-SOURCE"}},
                                      "condition_source_contract": {"token": "SECRET-TOKEN"}}},
        }

    monkeypatch.setattr(store, "dialog_page_state", dialog_page_state)
    status, rules = call("/api/plush/auxiliary?view=rules&case=case-1", "syn-owner", store)
    assert status == 200
    assert rules["rows"] == [{
        "rule_id": "rule-synthetic", "version": 2, "status": "active",
        "merchant": "합성 상점", "card_kind": "국내", "transaction_direction": "",
        "item": "교통비", "apply_existing": False, "apply_future": True,
    }]
    assert rules["actions"][0]["href"] == "/api/classification/rules"
    assert rules["actions"][0]["method"] == "GET"
    assert rules["actions"][0]["csrf"] == "none"
    assert rules["data"]["case_id"] == "case-1"
    case_dialog = rules["data"]["case_dialog"]
    assert case_dialog["case_id"] == "case-1"
    assert case_dialog["row_revision"] == 4
    assert case_dialog["dialog_state"] == "open"
    assert case_dialog["questions"][0]["question_key"] == "scope"
    assert case_dialog["answers"] == {"scope": "이 행만"}
    assert case_dialog["one_off"] is False
    assert case_dialog["pending_draft"]["rule"]["effects"]["item"] == "교통비"
    assert case_dialog["last_preview"]["plan"]["counts"]["included_rows"] == 1
    assert case_dialog["row_id"] == "expense-demo-c1"
    assert set(case_dialog["row"]) <= {"item", "description"}
    serialized_dialog = json.dumps(case_dialog, ensure_ascii=False)
    assert "RAW-SOURCE" not in serialized_dialog
    assert "SECRET-TOKEN" not in serialized_dialog
    assert "attempts" not in case_dialog["conversation"]["turns"][0]
    assert "handoff_summary" not in case_dialog["conversation"]
    dialog_action = next(action for action in rules["actions"]
                         if action["id"] == "classification-rule-dialog-state")
    assert dialog_action["href"] == "/api/classification/dialog?case_id=case-1"

    monkeypatch.setattr(store, "dialog_page_state", lambda case_id: {
        "case_id": case_id, "row_id": None, "row_revision": None,
        "dialog_state": "not_started", "questions": [], "answers": {},
        "open_questions": [], "provider": {}, "conversation": None,
        "pending_draft": {"rule_id": None, "rule": None, "turn_id": None,
                          "confirmed": False},
    })
    status, missing = call("/api/plush/auxiliary?view=rules&case=missing-case", "syn-owner", store)
    assert status == 200
    assert missing["data"]["case_dialog"]["case_exists"] is False
    assert missing["data"]["case_dialog"]["row"] is None

    status, cards = call("/api/plush/transactions?view=cards", "syn-owner", store)
    assert status == 200
    upload = next(action for action in cards["actions"] if action["id"] == "card-upload-batch")
    assert upload["href"] == "/api/imports/upload-batch"
    assert upload["encoding"] == "multipart"
    assert upload["csrf"] == "header"
    assert upload["fields"] == [{
        "name": "files", "label": "카드 파일", "type": "file",
        "accept": ".xls,.xlsx,.csv", "multiple": True, "required": True,
    }]


def test_admin_review_projects_only_existing_state_payload(bound_store, monkeypatch):
    store, _ = bound_store

    class ReviewState:
        def state_only_payload(self):
            return {"state_only": True, "binding": "synthetic-binding", "revision": 4,
                    "updated_at": "2026-11-16T00:00:00Z", "counts": {"total": 4}}

    monkeypatch.setattr("webapp.real_review.active_service", lambda: ReviewState())
    status, review = call("/api/plush/admin?view=review", "syn-owner", store)
    assert status == 200
    assert review["data"]["available"] is True
    assert review["data"]["state_only"] is True
    assert "choices" not in review["data"]
    assert review["actions"][0]["href"] == "/api/review/model?state_only=1"
    assert review["actions"][0]["csrf"] == "none"
