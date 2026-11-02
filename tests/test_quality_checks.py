import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_quality_checks", ROOT / "tools/run_quality_checks.py")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)
SELECTOR_SPEC = importlib.util.spec_from_file_location("select_targeted_tests", ROOT / "tools/select_targeted_tests.py")
selector_tool = importlib.util.module_from_spec(SELECTOR_SPEC)
SELECTOR_SPEC.loader.exec_module(selector_tool)


def selector(paths, status="SELECTED", targets=None):
    return {"status": status, "unknown_files": paths,
            "pytest_commands": [["python", "-m", "pytest", *(targets or ["tests/test_cost_audit.py"]), "-q"]]}


def test_docs_only_and_empty_changes_do_not_schedule_code_checks():
    assert quality.build_plan([], {})["steps"] == []
    docs = quality.build_plan(["docs/specs/change.md"], {})
    assert docs["status"] == "DOCS_ONLY"
    assert docs["steps"] == ["documentation-diff-and-links"]


def test_product_change_uses_existing_impact_group_and_data_protection_gate():
    plan = quality.build_plan(["app/ledger.py"], selector([], targets=[
        "tests/card_pipeline/test_partial_refund.py", "tests/card_pipeline/test_ota_exact_gate.py",
        "tests/card_pipeline/test_google_tsv.py", "webapp/tests/test_priority_trip_assignment.py",
        "webapp/tests/test_access_control_phase7.py"]))
    assert "tracked-data-guard" in plan["steps"]
    assert len(plan["pytest_targets"]) == 5


def test_playwright_detection_uses_ast_not_test_filename():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets, unknown = selector_tool.select_targets(["webapp/static/css/site_shell.css"], impact_map["groups"])
    assert unknown == []
    plan = quality.build_plan(["webapp/static/css/site_shell.css"], selector([], targets=targets))
    assert "webapp.tests.test_expense_copy_states::test_integrated_labels_escape_source_text_and_are_visible_on_mobile" in plan["browser_tests"]
    assert plan["browser_required"] is True
    assert len(plan["browser_tests"]) >= 3
    assert "webapp.tests.test_site_tokens::test_dynamic_override_propagation" in plan["browser_tests"]
    assert "webapp.tests.test_site_tokens::test_chromium_true_baseline_differential_matrix" in plan["browser_tests"]


def test_autonomous_workflow_http_journeys_are_selected_from_the_map():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets, unknown = selector_tool.select_targets(["webapp/tests/test_autonomous_workflows.py"], impact_map["groups"])
    assert unknown == []
    assert "webapp/tests/test_autonomous_workflows.py" in targets
    assert len([target for target in targets if target.startswith("webapp/tests/test_")]) >= 8


def test_scheduled_audit_selects_deduplicated_protection_and_ui_groups():
    plan = quality.audit_plan()
    assert plan["status"] == "AUDIT"
    assert plan["audit"] is True
    assert "tests/card_pipeline/test_partial_refund.py" in plan["pytest_targets"]
    assert "webapp/tests/test_expense_copy_states.py" in plan["pytest_targets"]
    assert len(plan["pytest_targets"]) == len(set(plan["pytest_targets"]))
    assert plan["browser_required"] is True
    assert any("chromium_true_baseline_differential_matrix" in target for target in plan["browser_tests"])


def test_unknown_product_path_fails_closed_without_broad_suite(tmp_path):
    with pytest.raises(ValueError, match="UNKNOWN_IMPACT:1"):
        quality.build_plan(["new/product_area.py"], selector(["new/product_area.py"], "UNKNOWN_IMPACT"), root=tmp_path)


def test_unknown_path_without_any_test_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="UNKNOWN_IMPACT:1"):
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


def test_mixed_code_and_document_changes_keep_document_paths_in_plan():
    result = quality.build_plan(["webapp/ledger_board.py", "docs/specs/change.md"], selector([]))
    assert result["document_paths"] == ["docs/specs/change.md"]


def test_plan_rejects_head_that_differs_from_checked_out_head(monkeypatch):
    shas = iter(["a" * 40, "b" * 40, "c" * 40])
    monkeypatch.setattr(quality, "_git", lambda *args, **kwargs: next(shas))
    with pytest.raises(ValueError, match="HEAD_MISMATCH"):
        quality.plan("base", "different-head")


def test_impact_map_targets_are_all_tracked_for_fresh_checkouts():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets = {target for group in impact_map["groups"] for target in group["tests"]}
    targets.update(impact_map["safe_fallback_tests"])
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                             capture_output=True).stdout.decode("utf-8").split("\0")
    assert not targets - set(tracked)


def test_junit_cannot_pass_zero_tests_or_skipped_browser_cases(tmp_path):
    junit = tmp_path / "junit.xml"
    browser = ["webapp.tests.test_expense_copy_states::test_integrated_labels_escape_source_text_and_are_visible_on_mobile"]
    junit.write_text('<testsuite tests="0"></testsuite>', encoding="utf-8")
    zero = quality.summarize_junit(junit, browser)
    assert zero["test_case_count"] == 0
    assert zero["executed_case_count"] == 0
    assert zero["missing_browser_tests"] == browser
    junit.write_text('<testsuite><testcase classname="webapp.tests.test_expense_copy_states" name="test_integrated_labels_escape_source_text_and_are_visible_on_mobile"><skipped/></testcase></testsuite>', encoding="utf-8")
    skipped = quality.summarize_junit(junit, browser)
    assert skipped["executed_case_count"] == 0
    assert skipped["browser_skipped"] == browser
    assert skipped["missing_browser_tests"] == browser


def test_deleted_paths_are_retained_in_impact_plan():
    assert "app/ledger.py" in quality.build_plan(["app/ledger.py"], selector([]))["changed_paths"]


def test_selector_malformed_and_unknown_status_fail_closed():
    with pytest.raises(ValueError, match="SELECTOR_MALFORMED"):
        quality.build_plan(["app/file.py"], {"status": "SELECTED", "pytest_commands": []})
    with pytest.raises(ValueError, match="SELECTOR_FAILED"):
        quality.build_plan(["app/file.py"], {"status": "ERROR", "unknown_files": [], "pytest_commands": []})
