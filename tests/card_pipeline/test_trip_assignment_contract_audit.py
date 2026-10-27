"""Synthetic safety and output tests for the source-only trip audit."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "tools" / "audit_trip_assignment_contract.py"
SPEC = importlib.util.spec_from_file_location("trip_assignment_contract_audit", AUDIT_PATH)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_audit_locates_source_and_lists_existing_synthetic_pytest_commands(capsys):
    report = AUDIT.audit()
    output = capsys.readouterr()
    assert output.out == ""
    assert report["mode"] == "source-only-ast"
    assert all(entry["status"] == "SOURCE_LOCATED" for entry in report["entries"])
    assert report["synthetic_pytest_evidence"]["trip_valid"]["tests"]
    assert report["synthetic_pytest_evidence"]["card use date"]["pytest"].endswith(
        "tests/card_pipeline/test_reconciliation_rules.py -q")


def test_missing_source_and_syntax_error_are_structured_without_source_echo(tmp_path, monkeypatch):
    monkeypatch.setattr(AUDIT, "ROOT", tmp_path)
    missing, error = AUDIT._read_source("absent.py")
    assert missing is None
    assert error == {"status": "OPEN_QUESTION", "reason": "MISSING_SOURCE"}

    (tmp_path / "broken.py").write_text("SENTINEL_SECRET\ndef broken(:\n", encoding="utf-8")
    source, error = AUDIT._read_source("broken.py")
    assert source is None
    assert error["reason"] == "SYNTAX_ERROR"
    assert "SENTINEL_SECRET" not in json.dumps(error)


def test_untrusted_path_and_invalid_encoding_are_structured_without_content_echo(tmp_path, monkeypatch):
    monkeypatch.setattr(AUDIT, "ROOT", tmp_path)
    (tmp_path / "invalid.py").write_bytes(b"SENTINEL_SECRET\xff")
    source, error = AUDIT._read_source("invalid.py")
    assert source is None
    assert error["reason"] == "ENCODING_ERROR"
    assert "SENTINEL_SECRET" not in json.dumps(error)
    assert AUDIT._read_source("../outside.py")[1]["reason"] == "UNTRUSTED_PATH"
