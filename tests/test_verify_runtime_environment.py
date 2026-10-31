import json
import importlib.util
from pathlib import Path
import pytest

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_runtime_environment.py"
_SPEC = importlib.util.spec_from_file_location("verify_runtime_environment", _TOOL)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
inspect_catalog = _MODULE.inspect_catalog
status_exit_code = _MODULE.status_exit_code


def _fixture(root, entries, source):
    (root / "config").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "webapp").mkdir()
    (root / "config" / "runtime-environment-catalog.json").write_text(
        json.dumps({"schema": "runtime-environment-catalog-v1", "scope": ["run_candidate.py"],
                    "value_policy": "synthetic values only", "entries": entries}),
        encoding="utf-8")
    (root / "run_candidate.py").write_text(source, encoding="utf-8")


def _entry(name, status="confirmed"):
    return {"name": name, "owner": "synthetic owner", "role": "feature:test",
            "required": "optional", "default": "unknown", "status": status,
            **({"unresolved_reason": "Synthetic dynamic fixture has no static source default."}
               if status == "unknown" else {})}


def test_catalog_matches_literal_and_constant_references_without_environment_values(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_FLAG"), _entry("WEBLEDGER_PATH")],
             'FLAG_ENV = "WEBLEDGER_FLAG"\nos.environ.get(FLAG_ENV)\nos.environ["WEBLEDGER_PATH"]')
    report = inspect_catalog(tmp_path)
    assert report["missing"] == []
    assert report["duplicates"] == []
    assert report["status"] == "MATCH"
    assert status_exit_code(report["status"]) == 0


def test_new_reference_is_reported_as_missing_and_unknown_metadata_remains_visible(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_KNOWN"), _entry("WEBLEDGER_PENDING", "unknown")],
             'os.environ.get("WEBLEDGER_KNOWN")\nos.environ.get("WEBLEDGER_NEW")')
    report = inspect_catalog(tmp_path)
    assert report["missing"] == ["WEBLEDGER_NEW"]
    assert report["unknown"] == [{"name": "WEBLEDGER_PENDING",
                                  "reason": "Synthetic dynamic fixture has no static source default.",
                                  "source_refs": None}]
    assert report["status"] == "DRIFT"


def test_unknown_metadata_is_review_not_match_or_drift(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_PENDING", "unknown")],
             'os.environ.get("WEBLEDGER_PENDING")')
    report = inspect_catalog(tmp_path)
    assert report["status"] == "REVIEW"
    assert report["missing"] == []
    assert status_exit_code(report["status"]) == 3


def test_duplicate_names_and_missing_ownership_metadata_are_reported(tmp_path):
    duplicate = _entry("WEBLEDGER_DUP")
    _fixture(tmp_path, [duplicate, duplicate], 'os.environ.get("WEBLEDGER_DUP")')
    report = inspect_catalog(tmp_path)
    assert report["duplicates"] == ["WEBLEDGER_DUP"]
    assert report["status"] == "DRIFT"
    assert status_exit_code(report["status"]) == 1


def test_entry_missing_required_metadata_is_rejected(tmp_path):
    malformed = {"name": "WEBLEDGER_BAD", "role": "path:test", "status": "confirmed"}
    _fixture(tmp_path, [malformed], 'pass')
    with pytest.raises(ValueError, match="MISSING_TYPED_METADATA"):
        inspect_catalog(tmp_path)


@pytest.mark.parametrize("payload, error", [
    ([], "CATALOG_ROOT_NOT_OBJECT"),
    ({"schema": "runtime-environment-catalog-v1", "scope": ["run_candidate.py"],
      "value_policy": "synthetic only", "entries": [None]}, "CATALOG_ENTRY_INVALID"),
    ({"schema": "runtime-environment-catalog-v1", "scope": ["run_candidate.py"],
      "value_policy": "synthetic only", "entries": [_entry(["bad-name"])]}, "CATALOG_ENTRY_INVALID"),
])
def test_invalid_catalog_shapes_fail_closed(tmp_path, payload, error):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "runtime-environment-catalog.json").write_text(
        json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        inspect_catalog(tmp_path)


def test_stale_only_entry_is_drift(tmp_path):
    _fixture(tmp_path, [_entry("WEBLEDGER_STALE")], 'pass')
    report = inspect_catalog(tmp_path)
    assert report["stale"] == ["WEBLEDGER_STALE"]
    assert report["status"] == "DRIFT"


@pytest.mark.parametrize("source, error", [("def broken(:", "SOURCE_SYNTAX_INVALID"),
                                            (b"\xff", "SOURCE_ENCODING_INVALID")])
def test_source_parse_or_encoding_failure_is_explicit(tmp_path, source, error):
    _fixture(tmp_path, [], "pass")
    target = tmp_path / "app" / "broken.py"
    target.write_bytes(source if isinstance(source, bytes) else source.encode("utf-8"))
    with pytest.raises(ValueError, match=error):
        inspect_catalog(tmp_path)


def test_source_read_failure_is_explicit(tmp_path, monkeypatch):
    _fixture(tmp_path, [], "pass")
    target = tmp_path / "app" / "unreadable.py"
    target.write_text("pass", encoding="utf-8")
    original = Path.read_text

    def fail_target(path, *args, **kwargs):
        if path == target:
            raise OSError("synthetic read refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target)
    with pytest.raises(ValueError, match="SOURCE_READ_FAILED:app"):
        inspect_catalog(tmp_path)
