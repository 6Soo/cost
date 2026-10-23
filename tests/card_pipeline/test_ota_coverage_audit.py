import json
import sqlite3

from app.reconcile import trace
from tools.audit_ota_card_coverage import main


def test_unknown_ota_date_keeps_candidate_trace_and_redacts_ids(monkeypatch):
    event = {"ota_event_id": "real-booking-event", "provider": "agoda", "event_type": "charge",
             "evidence_status": "paid_verified", "payment_status": "paid", "paid_on": None,
             "amount": "12000", "amount_krw": 12000, "currency": "KRW", "card_last4": "1234"}
    card = {"transaction_id": "real-card-row", "approval_date": "2026-10-01", "amount_krw": 12000,
            "transaction_direction": "purchase", "card_tail": "1234", "issuer": "issuer-x",
            "merchant": "Agoda", "merchant_normalized": "agoda"}
    summary, cases = trace.build_coverage_report(events=[event], cards=[card], run_secret=b"x" * 32)
    assert summary["candidate_recall_proxy"] == 1
    ota_case = next(case for case in cases if case["direction"] == "OTA_TO_CARD")
    assert ota_case["candidate_count"] == 1
    assert ota_case["candidates"][0]["basis"] == "DATE_UNKNOWN_CANDIDATE"
    serialized = json.dumps([summary, cases])
    assert "real-booking-event" not in serialized
    assert "real-card-row" not in serialized
    assert summary["automatic_link_approvals"] == 0


def test_audit_reads_synthetic_board_and_writes_redacted_reports(tmp_path):
    board = tmp_path / "board.sqlite"
    connection = sqlite3.connect(board)
    connection.execute("CREATE TABLE transactions (transaction_id TEXT, merchant TEXT, amount_krw INTEGER)")
    connection.execute("INSERT INTO transactions VALUES ('private-transaction-id', 'Private merchant', 12000)")
    connection.commit()
    connection.close()

    data = tmp_path / "data"
    data.mkdir()
    (data / "ota-mail").mkdir()
    (data / "ota-sources.json").write_text(
        json.dumps({"schema_version": "ota-sources-v1", "mail_directories": [],
                    "portal_databases": [], "reference_documents": []}), encoding="utf-8")
    before = board.read_bytes()
    output = tmp_path / "audit-output"
    assert main(["--read-only", "--board-db", str(board), "--data-dir", str(data),
                 "--output-dir", str(output)]) == 0
    summary = json.loads((output / "coverage-summary.json").read_text(encoding="utf-8"))

    assert summary["status"] == "COMPLETE_INPUTS"
    assert summary["run_mode"] == "READ_ONLY"
    assert summary["automatic_link_approvals"] == 0
    assert summary["snapshot"]["registered_input_version_sha256"]
    assert board.read_bytes() == before
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert "private-transaction-id" not in report_text
    assert "Private merchant" not in report_text
    assert {path.name for path in output.iterdir()} == {
        "coverage-summary.json", "unmatched-cases.jsonl", "legacy-diff.jsonl",
        "reconciliation-diff.jsonl"}


def test_global_matcher_divergence_is_redacted_and_counted():
    event = {"ota_event_id": "private-event", "evidence_status": "paid_verified"}
    card = {"transaction_id": "private-card"}
    summary, _ = trace.build_coverage_report(
        events=[event], cards=[card], legacy_links={"private-event": "private-card"},
        reconciliation_results=[{"ota_event_id": "private-event", "status": "HOLD_AMBIGUOUS"}],
        run_secret=b"y" * 32)
    assert summary["legacy_engine_divergence_count"] == 1
    assert summary["reconciliation_engine_status_counts"] == {"HOLD_AMBIGUOUS": 1}
    assert "private-event" not in json.dumps(summary)
    assert "private-card" not in json.dumps(summary)
