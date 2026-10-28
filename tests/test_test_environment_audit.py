import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


TOOL = Path(__file__).resolve().parents[1] / "tools" / "audit_test_environment.py"
SPEC = importlib.util.spec_from_file_location("audit_test_environment", TOOL)
audit_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_tool)


def make_repo(tmp_path, files):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", *files], check=True)
    return root


def test_counts_only_module_and_direct_class_test_definitions():
    source = """\
def test_module():
    def test_nested(): pass
class TestGroup:
    def test_one(self):
        def test_nested_method(): pass
    async def test_two(self): pass
    class Nested:
        def test_not_direct(self): pass
"""
    tree = __import__("ast").parse(source)
    assert audit_tool._test_count(tree) == 3


def test_alias_import_markers_and_environment_name_are_safe_metadata(tmp_path):
    root = make_repo(tmp_path, {
        "tests/test_a.py": """\
import playwright.sync_api as browser_api
import os as o
from os import getenv as g, environ as e
import pytest as pt
TOKEN = 'must never appear in report'
@pt.mark.browser
def test_live():
    o.getenv('COST_API_TOKEN')
    o.environ.get('DATABASE_URL')
    o.environ['SECRET_KEY']
    g('GMAIL_USER')
    e['GOOGLE_CREDENTIALS']
    e.get('LIVE_DB')
    g('API...do-not-print-this')
@pt.mark.integration
def test_integration(): pass
@pt.mark.browser
class TestBrowser:
    def test_class_marker(self): pass
pytestmark = pt.mark.browser
def test_keyword_name_is_not_a_marker():
    pt.mark(name='browser')
""",
        "pytest.ini": "[pytest]\nmarkers =\n    browser: browser environment\n    integration: live environment\n",
    })
    report = audit_tool.audit(root, runtime="3.14.7")
    row = next(item for item in report["files"] if item["path"] == "tests/test_a.py")
    codes = {item["reason_code"] for item in row["evidence"]}
    assert {"BROWSER_IMPORT", "ENV_NAME", "BROWSER_MARKER", "LIVE_MARKER"} <= codes
    rendered = json.dumps(report)
    assert "must never appear" not in rendered
    assert "API...do-not-print-this" not in rendered
    assert "COST_API_TOKEN" in rendered
    assert sum(item["reason_code"] == "BROWSER_MARKER" for item in row["evidence"]) == 3
    assert any(item["identifier"] == "LIVE_DB" for item in row["evidence"])


def test_unknown_source_has_unverified_status(tmp_path):
    root = make_repo(tmp_path, {"tests/test_plain.py": "def test_plain(): pass\n"})
    row = audit_tool.audit(root)["files"][0]
    assert row["status"] == "UNVERIFIED"
    assert row["evidence"] == []


def test_parse_path_and_invalid_root_fail_without_source_echo(tmp_path):
    root = make_repo(tmp_path, {
        "tests/test_bad.py": "def test_broken(:\n",
        "tests/test_good.py": "def test_good(): pass\n",
        "app/service.py": "def test_unselected(): pass\n",
    })
    report = audit_tool.audit(root)
    assert report["tracked_python_file_count"] == 2
    assert report["tracked_test_candidate_count"] == 1
    assert report["errors"] == [{"path": "tests/test_bad.py", "reason": "PYTHON_PARSE_FAILED"}]
    assert {row["path"] for row in report["files"]} == {"tests/test_good.py"}

    outside = tmp_path / "outside.py"
    outside.write_text("def test_outside(): pass\n", encoding="utf-8")
    (root / "tests" / "test_bad.py").unlink()
    (root / "tests" / "test_bad.py").symlink_to(outside)
    report = audit_tool.audit(root)
    assert report["errors"] == [{"path": "tests/test_bad.py", "reason": "PATH_OUTSIDE_OR_MISSING"}]

    with pytest.raises(audit_tool.AuditError, match="INVALID_ROOT"):
        audit_tool.audit(tmp_path)


def test_bom_and_cli_summary_aggregate_error_status(tmp_path):
    root = make_repo(tmp_path, {
        "tests/test_bom.py": "def test_bom(): pass\n",
        "tests/test_parse.py": "def test_bad(:\n",
        "app/ordinary.py": "def test_should_not_be_read(:\n",
    })
    target = root / "tests" / "test_bom.py"
    target.write_text("\ufeffimport os as o\no.getenv('API_TOKEN')\ndef test_bom(): pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--", "tests/test_bom.py"], check=True)
    report = audit_tool.audit(root)
    assert len(report["errors"]) == 1
    assert report["errors"][0]["path"] == "tests/test_parse.py"
    assert any(e["reason_code"] == "ENV_NAME" for e in report["files"][0]["evidence"])

    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), "--summary"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 2
    assert "test_bom.py:" not in result.stdout
    assert "ERROR tests/test_parse.py PYTHON_PARSE_FAILED" in result.stdout
    assert "API_TOKEN" not in result.stdout

    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 2
    assert "PYTHON_PARSE_FAILED" in result.stdout


def test_cli_error_is_nonzero_and_does_not_echo_source(tmp_path):
    root = make_repo(tmp_path, {"tests/test_bad.py": "SECRET_SOURCE def test_x(:"})
    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "SECRET_SOURCE" not in result.stdout + result.stderr


def test_real_collection_counts_tests_without_executing_bodies(tmp_path):
    root = make_repo(tmp_path, {'tests/test_sample.py':
        "import pytest\n@pytest.mark.parametrize('value',[1,2,3])\n"
        "def test_body(value):\n    raise AssertionError('BODY_MUST_NOT_RUN')\n"})
    report = audit_tool.collect_baseline(root)
    assert report['status'] == 'COLLECTED'
    assert report['collected'] == 3
    assert report['exit_code'] == 0
    assert report['test_bodies_executed'] is False
    assert report['imports_and_collection_hooks_executed'] is True
    assert len(report['output_sha256']) == 64


def test_failed_collection_never_publishes_import_source_or_false_pass(tmp_path):
    root = make_repo(tmp_path, {'tests/test_private.py':
        "raise RuntimeError('PRIVATE_CUSTOMER_SOURCE')\n"})
    report = audit_tool.collect_baseline(root)
    assert report['status'] == 'COLLECTION_FAILED'
    assert report['exit_code'] != 0
    assert report['tests_executed'] is False
    import json
    assert 'PRIVATE_CUSTOMER_SOURCE' not in json.dumps(report)
    assert str(root) not in json.dumps(report)


def test_collection_timeout_is_not_a_pass_and_does_not_echo_partial_output(tmp_path, monkeypatch):
    root = make_repo(tmp_path, {'tests/test_a.py': 'def test_a(): pass\n'})
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('pytest', 1, output=b'PRIVATE_PARTIAL_OUTPUT')
    monkeypatch.setattr(audit_tool.subprocess, 'run', timeout)
    report = audit_tool.collect_baseline(root, timeout=1)
    assert report['status'] == 'COLLECTION_TIMEOUT'
    assert report['collected'] is None
    assert 'PRIVATE_PARTIAL_OUTPUT' not in str(report)
