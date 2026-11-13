"""Synthetic-only quarter paste-pack completeness tests."""

import json

from tools.quarter_review import paste_pack


def row(identity="a", amount=1200, **values):
    return {
        "transaction_id": identity,
        "row_id": f"card-{identity}",
        "occurred_on": "2026-07-01",
        "merchant": "합성 거래처",
        "item": "식비",
        "amount_krw": amount,
        "evidence_type": "카드",
        "service_period": "2026-07-01",
        "reservation_no": "",
        "classification_source": "user_decision",
        "display_tab_id": "trip-a",
        **values,
    }


def test_exports_existing_seven_column_contract_and_allowlisted_empty_values():
    result = paste_pack._export_rows([row()])
    assert result["tsv"] == "2026-07-01\t합성 거래처\t식비\t2026-07-01\t\t카드\t1200\n"
    assert result["row_count"] == 1
    assert result["total_krw"] == 1200
    assert result["held"] == []
    assert paste_pack.EMPTY_FIELD_ALLOWLIST["period"] == ("DATE-109",)
    assert paste_pack.EMPTY_FIELD_ALLOWLIST["reservation_no"] == ("DATE-032",)


def test_required_item_evidence_and_amount_are_held():
    result = paste_pack._export_rows([
        row("item", item=""), row("evidence", evidence_type="unknown"), row("amount", amount=None),
    ])
    assert result["row_count"] == 0
    assert result["held_reason_counts"] == {
        "AMOUNT_INVALID": 1,
        "EVIDENCE_UNKNOWN": 1,
        "FIELD_MISSING": 1,
    }


def test_card_source_is_evidence_when_projected_type_is_absent():
    result = paste_pack._export_rows([row(evidence_type=None)])
    assert result["row_count"] == 1
    assert result["held_reason_counts"] == {}


def test_cash_evidence_labels_are_preserved_and_card_receipt_contract_is_unchanged():
    from app.google_tsv import expense_tsv

    for label in ("클룩 포인트", "아고다캐시", "트립코인"):
        cash = paste_pack._export_rows([row(evidence_type=label)])
        assert cash["row_count"] == 1
        assert cash["tsv"].splitlines()[0].split("\t")[5] == label
    assert expense_tsv([{
        "transaction_id": "card", "date": "2026-07-01", "payee": "상점",
        "category": "식비", "evidence": "card", "amount_krw": 100, "status": "ready",
    }], layout="rev")["tsv"].split("\t")[5] == "카드"
    assert expense_tsv([{
        "transaction_id": "receipt", "date": "2026-07-01", "payee": "상점",
        "category": "식비", "evidence": "receipt", "amount_krw": 100, "status": "ready",
    }], layout="rev")["tsv"].split("\t")[5] == "영수증"


def test_weak_inference_does_not_create_optional_period_or_reference_values():
    result = paste_pack._export_rows([row(classification_source="ai_inference", service_period="")])
    assert result["row_count"] == 0
    assert result["held_reason_counts"] == {"FIELD_MISSING": 1}


def test_date_109_allows_unknown_lodging_and_airfare_periods():
    result = paste_pack._export_rows([row("stay", item="숙박비", service_period=""),
                                      row("flight", item="항공료", service_period="")])
    assert result["row_count"] == 2
    assert all(line.split("\t")[3] == "" for line in result["tsv"].splitlines())
    assert paste_pack.EMPTY_PERIOD_CATEGORIES == ("숙박비", "항공료")
    assert paste_pack._export_rows([row("meal", item="식비", service_period="")])["held_reason_counts"] == {
        "FIELD_MISSING": 1,
    }
    assert paste_pack._empty_allowed({"category": "식비"}, "period") is False
    assert paste_pack._empty_allowed({"category": "숙박비"}, "period") is True


def test_lodging_period_blank_requires_the_policy_allowlist(monkeypatch):
    monkeypatch.setattr(paste_pack, "EMPTY_FIELD_ALLOWLIST", {
        "period": (), "reservation_no": ("DATE-032",),
    })
    result = paste_pack._export_rows([row(item="숙박비", service_period="")])
    assert result["row_count"] == 0
    assert result["held_reason_counts"] == {"FIELD_MISSING": 1}


def test_per_tab_and_quarter_other_summaries_and_files(tmp_path, monkeypatch):
    trips = [
        {"tab_id": "trip-a", "display_key": "synthetic trip A"},
        {"tab_id": "trip-b", "display_key": "synthetic trip B"},
    ]
    rows = [row("a", 1200), row("b", 700, display_tab_id="trip-b"),
            row("c", -100, display_tab_id="quarter:2026:3")]
    monkeypatch.setattr(paste_pack, "prepare_rows", lambda *_args: (trips, rows, {}))
    summary = paste_pack.build_paste_pack({"manual_fields": {}, "tab_expense_totals": {
        "trip-a": 1200, "trip-b": 700, "quarter:2026:3": -100,
    }}, 2026, 3, tmp_path)
    assert summary["trip_count"] == 2
    assert [trip["row_count"] for trip in summary["trips"]] == [1, 1]
    assert summary["quarter_other"]["row_count"] == 1
    assert summary["quarter_other"]["total_krw"] == -100
    assert summary["completeness"] == "complete"
    assert summary["held_status"] == "보류 0 달성"
    assert summary["tab_totals_match_count"] == summary["tab_total_count"] == 3
    assert (tmp_path / "trip-001.tsv").exists()
    assert (tmp_path / "trip-002.tsv").exists()
    assert (tmp_path / "quarter-2026Q3-other.tsv").exists()
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8")) == summary


def test_held_rows_make_tab_total_mismatch_and_record_reason(tmp_path, monkeypatch):
    trips = [{"tab_id": "trip-a", "display_key": "synthetic trip A"}]
    rows = [row("a", 1200), row("unknown", 300, evidence_type=None, transaction_id=None)]
    monkeypatch.setattr(paste_pack, "prepare_rows", lambda *_args: (trips, rows, {}))
    summary = paste_pack.build_paste_pack({"manual_fields": {}, "tab_expense_totals": {
        "trip-a": 1500, "quarter:2026:3": 0,
    }}, 2026, 3, tmp_path)
    assert summary["held_reason_counts"] == {"EVIDENCE_UNKNOWN": 1}
    assert summary["held_status"] == "보류 0 미달"
    assert summary["completeness"] == "mismatch"
    assert summary["mismatch_count"] == 1
    assert summary["trips"][0]["total_krw"] == 1200
    assert summary["trips"][0]["ledger_total_krw"] == 1500
    assert summary["trips"][0]["difference_causes"] == {"EVIDENCE_UNKNOWN": 1}


def test_screen_refund_rows_are_not_moved_to_trip_and_no_ledger_cards_are_counted(tmp_path, monkeypatch):
    from tools.quarter_review.pack import prepare_rows

    trips = [{"tab_id": "trip-a", "display_key": "synthetic trip A", "starts_on": "2026-07-01"}]
    def transaction(identity, amount, **values):
        return {"transaction_id": identity, "amount_krw": amount, "approval_date": "2026-07-01",
                "posting_date": "2026-07-01", "display_tab_id": "trip-a", "trip_id": "trip-a",
                "classification_state": "classified", "classification_source": "user_decision",
                "item": "식비", "merchant": "합성 거래처", "evidence_type": "카드", **values}
    refund = transaction("refund", -200, display_tab_id="refunds")
    no_ledger = transaction("no-ledger", 300)
    normal = transaction("normal", 100, service_period="2026-07-01")
    saved_normal = {**normal, "row_id": "card-normal", "row_kind": "expense",
                    "display_amount_krw": 100, "display_occurred_on": "2026-07-01"}
    saved_refund = {**refund, "row_id": "card-refund", "row_kind": "expense",
                    "display_amount_krw": -200, "display_occurred_on": "2026-07-01"}
    data = {"trip_tabs": trips, "transactions": [refund, no_ledger, normal],
            "board_projected": [saved_refund, saved_normal], "change_log": [],
            "manual_fields": {}, "manual_ids": set(), "company_exclusions": set()}
    selected_trips, selected_rows, excluded = prepare_rows(data, 2026, 3)
    assert selected_trips == trips
    assert [item["transaction_id"] for item in selected_rows] == ["normal"]
    assert excluded["refund_tab"] == 1
    assert excluded["no_ledger_row"] == 1
    assert excluded["no_ledger_by_tab"] == {"trip-a": 1}

    monkeypatch.setattr(paste_pack, "prepare_rows", lambda *_args: (
        trips, selected_rows, excluded
    ))
    summary = paste_pack.build_paste_pack({"tab_expense_totals": {"trip-a": 300,
        "quarter:2026:3": 0}}, 2026, 3, tmp_path)
    assert summary["trips"][0]["total_krw"] == 100
    assert summary["trips"][0]["ledger_total_krw"] == 300
    assert summary["trips"][0]["difference_causes"] == {"NO_LEDGER_ROW": 1}
    assert summary["excluded_reason_counts"] == {"NO_LEDGER_ROW": 1, "REFUND_TAB_ROW": 1}


def test_period_blank_cause_counts_are_by_item_and_evidence_signal():
    assert paste_pack._period_blank_counts([
        row("unknown", item="숙박비", service_period=""),
        row("tool", item="숙박비", booking_ref="SYNTHETIC", service_period=""),
        row("air", item="항공료", service_period_conflict=True, service_period=""),
    ]) == {
        "숙박비": {"근거 없음": 1, "도구가 근거를 읽지 못함": 1},
        "항공료": {"도구가 근거를 읽지 못함": 1},
    }


def test_duplicate_identity_is_not_exported_twice():
    result = paste_pack._export_rows([row("dup"), row("dup")])
    assert result["row_count"] == 0
    assert result["held_reason_counts"] == {"DUPLICATE_ID": 2}
