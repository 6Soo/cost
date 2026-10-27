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
    entries = {entry["topic"]: entry for entry in report["entries"]}
    assert entries["manual precedence"]["symbol"] == "CardFlow.sync_ledger_rows"
    assert entries["trip period closure"]["symbol"] == "open_trip_end"
    assert entries["Google open-end closure"]["symbol"] == "_close_open_ends"
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


def test_definition_locator_respects_scope_and_rejects_duplicates():
    tree = AUDIT.ast.parse("""
def target(): pass
def outer():
    def nested(): pass
    class Inner:
        def target(self): pass
class Owner:
    def target(self): pass
    def method(self):
        def target(self): pass
class Owner:
    def target(self): pass
""")
    assert AUDIT._definitions(tree, None, "target", "module") == [2]
    assert AUDIT._definitions(tree, "Owner", "target", "class") == []
    assert AUDIT._definitions(tree, "Owner", "method", "class") == []


def test_topic_map_scopes_and_labels_are_unique_and_valid():
    assert len(AUDIT.SYMBOLS) == len(set(AUDIT.SYMBOLS))
    for path, owner, symbol, scope in AUDIT.SYMBOLS.values():
        assert path.endswith(".py") and symbol
        assert (scope == "module" and owner is None) or (scope == "class" and owner)


def test_untrusted_path_and_invalid_encoding_are_structured_without_content_echo(tmp_path, monkeypatch):
    monkeypatch.setattr(AUDIT, "ROOT", tmp_path)
    (tmp_path / "invalid.py").write_bytes(b"SENTINEL_SECRET\xff")
    source, error = AUDIT._read_source("invalid.py")
    assert source is None
    assert error["reason"] == "ENCODING_ERROR"
    assert "SENTINEL_SECRET" not in json.dumps(error)
    assert AUDIT._read_source("../outside.py")[1]["reason"] == "UNTRUSTED_PATH"
