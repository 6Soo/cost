import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_quality_checks", ROOT / "tools/run_quality_checks.py")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def selector(paths, status="SELECTED", targets=None):
    return {"status": status, "unknown_files": paths,
            "pytest_commands": [["python", "-m", "pytest", *(targets or ["tests/test_cost_audit.py"]), "-q"]]}


def test_docs_only_and_empty_changes_do_not_schedule_code_checks():
    assert quality.build_plan([], {})["steps"] == []
    docs = quality.build_plan(["docs/specs/change.md"], {})
    assert docs["status"] == "DOCS_ONLY"
    assert docs["steps"] == ["documentation-diff-and-links"]


def test_product_change_always_includes_financial_protection_tests():
    plan = quality.build_plan(["app/ledger.py"], selector([]))
    assert set(quality.FINANCIAL_GUARD_TESTS) <= set(plan["pytest_targets"])
    assert "tracked-data-guard" in plan["steps"]


def test_shared_css_change_selects_cross_screen_browser_contracts():
    plan = quality.build_plan(["webapp/static/css/site_shell.css"], selector([]))
    assert quality.GLOBAL_UI_TESTS[0] in plan["pytest_targets"]
    assert plan["browser_required"] is True


def test_unknown_product_path_falls_back_to_all_existing_pytest_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_one.py").write_text("def test_one(): pass\n", encoding="utf-8")
    (tmp_path / "tests/test_cost_audit.py").write_text("def test_mapped(): pass\n", encoding="utf-8")
    for target in quality.FINANCIAL_GUARD_TESTS:
        path = tmp_path / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_synthetic_guard(): pass\n", encoding="utf-8")
    result = quality.build_plan(["new/product_area.py"], selector(["new/product_area.py"], "UNKNOWN_IMPACT"), root=tmp_path)
    assert result["status"] == "UNKNOWN_BROAD"
    assert "tests/test_one.py" in result["pytest_targets"]
    assert result["fallback"] == "all-existing-pytest-files"


def test_unknown_path_without_any_test_fails_closed(tmp_path):
    (tmp_path / "tests").mkdir()
    with pytest.raises(ValueError, match="UNKNOWN_PATH_WITHOUT_FALLBACK"):
        quality.build_plan(["new/product_area.py"], selector(["new/product_area.py"], "UNKNOWN_IMPACT"), root=tmp_path)


def test_documentation_check_rejects_broken_local_link(tmp_path):
    doc = tmp_path / "docs/change.md"
    doc.parent.mkdir()
    doc.write_text("[missing](../absent.md)\n", encoding="utf-8")
    class Completed:
        returncode = 0
    from unittest.mock import patch
    with patch.object(quality.subprocess, "run", return_value=Completed()):
        with pytest.raises(ValueError, match="DOCUMENTATION_LINK_BROKEN"):
            quality.check_documentation("a" * 40, "b" * 40, ["docs/change.md"], root=tmp_path)


def test_deleted_paths_are_retained_in_impact_plan():
    assert "app/ledger.py" in quality.build_plan(["app/ledger.py"], selector([]))["changed_paths"]


def test_selector_malformed_and_unknown_status_fail_closed():
    with pytest.raises(ValueError, match="SELECTOR_MALFORMED"):
        quality.build_plan(["app/file.py"], {"status": "SELECTED", "pytest_commands": []})
    with pytest.raises(ValueError, match="SELECTOR_FAILED"):
        quality.build_plan(["app/file.py"], {"status": "ERROR", "unknown_files": [], "pytest_commands": []})
