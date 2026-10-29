import json
import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_runtime_environment.py"
_SPEC = importlib.util.spec_from_file_location("verify_runtime_environment", _TOOL)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
inspect_catalog = _MODULE.inspect_catalog


def _fixture(root, entries, source):
    (root / "config").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "webapp").mkdir()
    (root / "config" / "runtime-environment-catalog.json").write_text(
        json.dumps({"schema": "runtime-environment-catalog-v1", "entries": entries}),
        encoding="utf-8")
    (root / "run_candidate.py").write_text(source, encoding="utf-8")


def _entry(name, status="confirmed"):
    return {"name": name, "owner": "synthetic owner", "role": "feature:test",
            "required": "optional", "default": "unknown", "status": status}


def test_catalog_matches_literal_and_constant_references_without_environment_values(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_FLAG"), _entry("WEBLEDGER_PATH")],
             'FLAG_ENV = "WEBLEDGER_FLAG"\nos.environ.get(FLAG_ENV)\nos.environ["WEBLEDGER_PATH"]')
    report = inspect_catalog(tmp_path)
    assert report["missing"] == []
    assert report["duplicates"] == []
    assert report["status"] == "MATCH"


def test_new_reference_is_reported_as_missing_and_unknown_metadata_remains_visible(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_KNOWN"), _entry("WEBLEDGER_PENDING", "unknown")],
             'os.environ.get("WEBLEDGER_KNOWN")\nos.environ.get("WEBLEDGER_NEW")')
    report = inspect_catalog(tmp_path)
    assert report["missing"] == ["WEBLEDGER_NEW"]
    assert report["unknown"] == ["WEBLEDGER_PENDING"]
    assert report["status"] == "DRIFT"


def test_duplicate_names_and_missing_ownership_metadata_are_reported(tmp_path):
    duplicate = _entry("WEBLEDGER_DUP")
    malformed = {"name": "WEBLEDGER_BAD", "role": "path:test", "status": "confirmed"}
    _fixture(tmp_path, [duplicate, duplicate, malformed], 'os.environ.get("WEBLEDGER_DUP")')
    report = inspect_catalog(tmp_path)
    assert report["duplicates"] == ["WEBLEDGER_DUP"]
    assert report["malformed"] == ["WEBLEDGER_BAD"]
