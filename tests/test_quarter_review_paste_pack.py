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
        "service_period": "",
        "reservation_no": "",
        "classification_source": "user_decision",
        "display_tab_id": "trip-a",
        **values,
    }


def test_exports_existing_seven_column_contract_and_allowlisted_empty_values():
    result = paste_pack._export_rows([row()])
    assert result["tsv"] == "2026-07-01\t합성 거래처\t식비\t\t\t카드\t1200\n"
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


def test_weak_inference_does_not_create_optional_period_or_reference_values():
    result = paste_pack._export_rows([row(classification_source="ai_inference")])
    assert result["row_count"] == 1
    assert result["tsv"].splitlines()[0].split("\t")[3:5] == ["", ""]
    assert result["held_reason_counts"] == {}


def test_date_109_allows_unknown_lodging_and_airfare_periods():
    result = paste_pack._export_rows([row("stay", item="숙박비"), row("flight", item="항공료")])
    assert result["row_count"] == 2
    assert all(line.split("\t")[3] == "" for line in result["tsv"].splitlines())
    assert paste_pack.EMPTY_PERIOD_CATEGORIES == ("숙박비", "항공료")


def test_lodging_period_blank_requires_the_policy_allowlist(monkeypatch):
    monkeypatch.setattr(paste_pack, "EMPTY_FIELD_ALLOWLIST", {
        "period": (), "reservation_no": ("DATE-032",),
    })
    result = paste_pack._export_rows([row(item="숙박비")])
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
    summary = paste_pack.build_paste_pack({"manual_fields": {}}, 2026, 3, tmp_path)
    assert summary["trip_count"] == 2
    assert [trip["row_count"] for trip in summary["trips"]] == [1, 1]
    assert summary["quarter_other"]["row_count"] == 1
    assert summary["quarter_other"]["total_krw"] == -100
    assert summary["completeness"] == "complete"
    assert summary["held_status"] == "보류 0 달성"
    assert (tmp_path / "trip-001.tsv").exists()
    assert (tmp_path / "trip-002.tsv").exists()
    assert (tmp_path / "quarter-2026Q3-other.tsv").exists()
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8")) == summary


def test_held_rows_make_tab_total_mismatch_and_record_reason(tmp_path, monkeypatch):
    trips = [{"tab_id": "trip-a", "display_key": "synthetic trip A"}]
    rows = [row("a", 1200), row("unknown", 300, evidence_type=None, transaction_id=None)]
    monkeypatch.setattr(paste_pack, "prepare_rows", lambda *_args: (trips, rows, {}))
    summary = paste_pack.build_paste_pack({"manual_fields": {}}, 2026, 3, tmp_path)
    assert summary["held_reason_counts"] == {"EVIDENCE_UNKNOWN": 1}
    assert summary["held_status"] == "보류 0 미달"
    assert summary["completeness"] == "mismatch"
    assert summary["mismatch_count"] == 1
    assert summary["trips"][0]["total_krw"] == 1200
    assert summary["trips"][0]["ledger_total_krw"] == 1500


def test_duplicate_identity_is_not_exported_twice():
    result = paste_pack._export_rows([row("dup"), row("dup")])
    assert result["row_count"] == 0
    assert result["held_reason_counts"] == {"DUPLICATE_ID": 2}
