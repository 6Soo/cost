from copy import deepcopy

from app import core_writer
from webapp import ledger_stay_evidence, plush_periods, plush_projection


def test_ledger_period_projection_preserves_manual_and_saved_status_precedence(monkeypatch):
    records = {
        "manual-value": {
            "kind": "inferred", "starts_on": "2026-10-01", "ends_on": "2026-10-02",
            "basis": "저장 추정", "source_hash": "manual-value-hash", "revision": 1,
        },
        "manual-empty": {
            "kind": "inferred", "starts_on": "2026-10-03", "ends_on": "2026-10-04",
            "basis": "오래된 추정", "source_hash": "old-manual-hash", "revision": 1,
        },
        "verified": {
            "kind": "verified", "starts_on": "2026-10-05", "ends_on": "2026-10-06",
            "source_hash": "verified-hash", "revision": 2,
        },
        "inferred": {
            "kind": "inferred", "starts_on": "2026-10-07", "ends_on": "2026-10-08",
            "basis": "예약 자료 연결", "source_hash": "inferred-hash", "revision": 3,
        },
        "unknown": {
            "kind": "unknown", "reason": "근거 없음",
            "source_hash": "unknown-hash", "revision": 4,
        },
        "stale": {
            "kind": "verified", "starts_on": "2026-10-09", "ends_on": "2026-10-10",
            "source_hash": "old-source-hash", "revision": 1,
        },
    }
    rows = [
        {"row_id": "card-manual-value", "source_event_id": "manual-value",
         "service_period": "2026-09-01~2026-09-02", "amount_krw": 1000},
        {"row_id": "card-manual-empty", "source_event_id": "manual-empty",
         "service_period": "", "amount_krw": 1000},
        {"row_id": "card-verified", "source_event_id": "verified", "service_period": "", "amount_krw": 1000},
        {"row_id": "card-inferred", "source_event_id": "inferred", "service_period": "", "amount_krw": 1000},
        {"row_id": "card-unknown", "source_event_id": "unknown", "service_period": "", "amount_krw": 1000},
        {"row_id": "card-stale", "source_event_id": "stale", "service_period": "", "amount_krw": 1000},
    ]
    before = deepcopy(rows)
    identities = {
        transaction_id: {"source_hash": record["source_hash"], "revision": record["revision"]}
        for transaction_id, record in records.items()
    }
    identities["stale"] = {"source_hash": "new-source-hash", "revision": 2}

    monkeypatch.setattr(core_writer, "load_stored_period_records", lambda: records)
    monkeypatch.setattr(core_writer, "note_period_source", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ledger_stay_evidence, "manual_period_rows",
                        lambda _board: {"card-manual-value", "card-manual-empty"})
    monkeypatch.setattr(plush_periods, "_current_source_identities",
                        lambda _board, _ids: identities)

    projected = plush_periods.annotate(rows, board=object())
    by_id = {row["row_id"]: row for row in projected}

    assert by_id["card-manual-value"]["_plush_period"] == "2026-09-01~2026-09-02"
    assert "_plush_period_status" not in by_id["card-manual-value"]
    assert by_id["card-manual-empty"]["_plush_period"] == ""
    assert by_id["card-manual-empty"]["_plush_period_status"] == "unknown"
    assert by_id["card-manual-empty"]["_plush_period_manual_blank"] is True
    assert by_id["card-verified"]["_plush_period"] == "2026-10-05~2026-10-06"
    assert by_id["card-verified"]["_plush_period_status"] == "verified"
    assert by_id["card-inferred"]["_plush_period"] == "2026-10-07~2026-10-08"
    assert by_id["card-inferred"]["_plush_period_status"] == "inferred"
    assert by_id["card-inferred"]["_plush_period_basis"] == "예약 자료 연결"
    assert by_id["card-unknown"]["_plush_period"] == ""
    assert by_id["card-unknown"]["_plush_period_status"] == "unknown"
    assert by_id["card-stale"]["_plush_period"] == ""
    assert by_id["card-stale"]["_plush_period_status"] == "stale"
    assert rows == before

    inferred_dto = plush_projection.ledger_row(by_id["card-inferred"])
    assert inferred_dto["period"] == "2026-10-07~2026-10-08"
    assert inferred_dto["period_status"] == "inferred"
    assert inferred_dto["period_basis"] == "예약 자료 연결"
    manual_blank_dto = plush_projection.ledger_row(by_id["card-manual-empty"])
    assert manual_blank_dto["period_status"] == "unknown"
    assert manual_blank_dto["period_manual_blank"] is True
