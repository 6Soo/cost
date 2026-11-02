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


def test_changed_test_module_is_executed_even_when_impact_map_omits_it():
    path = "webapp/tests/test_trip_google_income_browser.py"
    plan = quality.build_plan([path], selector([], targets=["tests/test_cost_audit.py"]))
    assert path in plan["pytest_targets"]
    assert plan["browser_required"] is True


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


def test_card_catalog_fixture_browser_tests_are_mapped_and_required():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets, unknown = selector_tool.select_targets(["webapp/card_catalog_assets.py"], impact_map["groups"])
    assert unknown == []
    assert "webapp/tests/test_card_catalog_browser.py" in targets
    plan = quality.build_plan(["webapp/card_catalog_assets.py"], selector([], targets=targets))
    assert set(plan["browser_tests"]) >= {
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_header_buttons_sort_and_filter_without_search_click",
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_menu_search_and_source_review_at_390",
    }


def test_browser_modules_require_every_test_even_when_playwright_is_in_helpers():
    targets = ["webapp/tests/test_card_flow_browser.py", "webapp/tests/test_site_shell_browser.py",
               "webapp/tests/test_expense_copy_states.py", "webapp/tests/test_card_catalog_browser.py"]
    cases = quality.collect_browser_tests(targets)
    expected = {
        "webapp.tests.test_card_flow_browser::CardFlowBrowserTests::test_cleanup_filters_save_stale_empty_and_responsive_browser_contract",
        "webapp.tests.test_site_shell_browser::SiteShellBrowserTests::test_theme_keyboard_motion_and_responsive_contract",
        "webapp.tests.test_expense_copy_states::test_integrated_labels_escape_source_text_and_are_visible_on_mobile",
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_header_buttons_sort_and_filter_without_search_click",
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_menu_search_and_source_review_at_390",
    }
    assert expected <= set(cases)
    assert len([case for case in cases if case.startswith("webapp.tests.test_card_flow_browser::")]) == 16
    assert len([case for case in cases if case.startswith("webapp.tests.test_site_shell_browser::")]) == 7


def test_selected_browser_module_parse_error_fails_closed(tmp_path):
    module = tmp_path / "test_broken_browser.py"
    module.write_text("\ufeffdef test_broken(:\n    pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="BROWSER_TEST_PARSE_FAILED:test_broken_browser.py"):
        quality.collect_browser_tests(["test_broken_browser.py"], root=tmp_path)


def test_autonomous_workflow_http_journeys_are_selected_from_the_map():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets, unknown = selector_tool.select_targets(["webapp/tests/test_autonomous_workflows.py"], impact_map["groups"])
    assert unknown == []
    assert "webapp/tests/test_autonomous_workflows.py" in targets
    assert len([target for target in targets if target.startswith("webapp/tests/test_")]) >= 8


def test_upload_queue_regression_selected_for_source_and_test_changes():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    for path in ("webapp/card_flow.py", "webapp/tests/test_multi_upload_queue.py"):
        targets, unknown = selector_tool.select_targets([path], impact_map["groups"])
        assert unknown == []
        assert "webapp/tests/test_multi_upload_queue.py" in targets


def test_receipt_review_journeys_are_selected_for_targeted_qa_and_scheduled_audit():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    targets, unknown = selector_tool.select_targets(["webapp/receipt_review.py"], impact_map["groups"])
    assert unknown == []
    required_modules = {
        "webapp/tests/test_receipt_review.py",
        "webapp/tests/test_receipt_page_flow.py",
        "webapp/tests/test_receipt_krw.py",
    }
    assert required_modules <= set(targets)

    plan = quality.build_plan(["webapp/receipt_review.py"], selector([], targets=targets))
    assert required_modules <= set(plan["pytest_targets"])
    required_browser_cases = {
        "webapp.tests.test_receipt_page_flow::ReceiptPageFlowTests::test_three_photos_are_analysed_registered_and_refreshed",
        "webapp.tests.test_receipt_review::ReceiptReviewTests::test_receipt_copy_refuses_unsaved_review_changes",
        "webapp.tests.test_receipt_review::ReceiptReviewTests::test_receipt_save_locks_controls_and_restores_inputs_after_error",
        "webapp.tests.test_receipt_review::ReceiptReviewTests::test_receipt_save_retry_after_lost_response_preserves_one_history_entry",
        "webapp.tests.test_receipt_review::ReceiptReviewTests::test_saving_one_receipt_preserves_other_receipts_unsaved_inputs",
    }
    assert required_browser_cases <= set(plan["browser_tests"])
    assert plan["browser_required"] is True

    audit = quality.audit_plan()
    assert "receipt-review" in impact_map["audit_groups"]
    assert required_modules <= set(audit["pytest_targets"])
    assert required_browser_cases <= set(audit["browser_tests"])
    assert audit["browser_required"] is True


def test_core_business_acceptance_is_targeted_and_audited_with_browser_cases_required():
    impact_map = json.loads((ROOT / "config/test-impact-map.json").read_text(encoding="utf-8"))
    required = {
        "webapp/tests/test_insurance_income_match_http.py",
        "webapp/tests/test_insurance_income_match_browser.py",
        "webapp/tests/test_owner_metadata.py",
        "webapp/tests/test_flight_booking_name_search.py",
        "webapp/tests/test_rule_review.py",
        "webapp/tests/test_rule_dialog_screen.py",
        "webapp/tests/test_trip_history_browser.py",
        "webapp/tests/test_trip_expense_copy_button.py",
    }
    group = next(group for group in impact_map["groups"]
                 if group["name"] == "core-business-acceptance")
    assert "core-business-acceptance" in impact_map["audit_groups"]
    assert required == set(group["tests"])
    assert required <= set(group["paths"])

    source_routes = {
        "webapp/ledger_board.py": {
            "webapp/tests/test_insurance_income_match_http.py",
            "webapp/tests/test_owner_metadata.py",
            "webapp/tests/test_trip_history_browser.py",
            "webapp/tests/test_trip_expense_copy_button.py",
        },
        "webapp/ledger_store.py": {"webapp/tests/test_owner_metadata.py"},
        "webapp/flight_passenger_page.py": {"webapp/tests/test_flight_booking_name_search.py"},
        "app/review.py": {"webapp/tests/test_rule_review.py"},
    }
    for source, expected in source_routes.items():
        selected, unknown = selector_tool.select_targets([source], impact_map["groups"])
        assert unknown == []
        assert expected <= set(selected), source

    plan = quality.build_plan(["webapp/owner_metadata.py"], selector([], targets=sorted(required)))
    assert required <= set(plan["pytest_targets"])
    required_browser_cases = {
        "webapp.tests.test_insurance_income_match_browser::test_candidate_selection_stays_in_its_row_and_narrow_page_does_not_overflow",
        "webapp.tests.test_flight_booking_name_search::test_browser_name_search_renders_verified_itinerary_and_secondary_participant_flow",
        "webapp.tests.test_rule_review::RuleReviewTests::test_browser_reports_committed_approval_when_refresh_fails",
        "webapp.tests.test_rule_dialog_screen::RuleDialogScreenTests::test_full_flow_at_1440",
        "webapp.tests.test_trip_history_browser::TripHistoryBrowserTests::test_previous_trips_open_and_link_to_existing_ledger_at_both_widths",
        "webapp.tests.test_trip_expense_copy_button::TripExpenseCopyBrowserTests::test_browser_copy_trip_expenses_interaction",
    }
    assert required_browser_cases <= set(plan["browser_tests"])
    assert plan["browser_required"] is True

    audit = quality.audit_plan()
    assert required <= set(audit["pytest_targets"])
    assert required_browser_cases <= set(audit["browser_tests"])
    assert audit["browser_required"] is True


def test_scheduled_audit_selects_deduplicated_protection_and_ui_groups():
    plan = quality.audit_plan()
    assert plan["status"] == "AUDIT"
    assert plan["audit"] is True
    assert "tests/card_pipeline/test_partial_refund.py" in plan["pytest_targets"]
    assert "webapp/tests/test_expense_copy_states.py" in plan["pytest_targets"]
    assert len(plan["pytest_targets"]) == len(set(plan["pytest_targets"]))
    assert plan["browser_required"] is True
    assert any("chromium_true_baseline_differential_matrix" in target for target in plan["browser_tests"])
    assert {
        "webapp/tests/test_autonomous_workflows.py",
        "webapp/tests/test_card_upload_jobs.py",
        "webapp/tests/test_export_page_performance.py",
    } <= set(plan["pytest_targets"])


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
    assert skipped["skip_count"] == 1
    assert skipped["nonbrowser_skipped_test_cases"] == []
    fixture_browser = ["webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_header_buttons_sort_and_filter_without_search_click"]
    junit.write_text('<testsuite><testcase classname="webapp.tests.test_card_catalog_browser.CardCatalogBrowserTests" name="test_header_buttons_sort_and_filter_without_search_click"/></testsuite>', encoding="utf-8")
    fixture_result = quality.summarize_junit(junit, fixture_browser)
    assert fixture_result["browser_executed"] == fixture_browser
    assert fixture_result["missing_browser_tests"] == []


def test_missing_junit_reports_zero_cases_and_missing_required_browser_tests(tmp_path):
    browser = ["webapp.tests.required_browser::test_required"]
    result = quality.summarize_junit(tmp_path / "missing.xml", browser)

    assert result["test_case_count"] == 0
    assert result["executed_case_count"] == 0
    assert result["browser_executed"] == []
    assert result["browser_skipped"] == browser
    assert result["missing_browser_tests"] == browser
    assert result["skipped_test_cases"] == []
    assert result["nonbrowser_skipped_test_cases"] == []
    assert result["skip_count"] == 0


def test_malformed_junit_reports_zero_cases_and_missing_required_browser_tests(tmp_path):
    junit = tmp_path / "malformed.xml"
    junit.write_text("<testsuite>", encoding="utf-8")
    browser = ["webapp.tests.required_browser::test_required"]

    result = quality.summarize_junit(junit, browser)

    assert result["test_case_count"] == 0
    assert result["executed_case_count"] == 0
    assert result["browser_executed"] == []
    assert result["browser_skipped"] == browser
    assert result["missing_browser_tests"] == browser
    assert result["skipped_test_cases"] == []
    assert result["nonbrowser_skipped_test_cases"] == []
    assert result["skip_count"] == 0


def test_malformed_junit_fails_run_and_preserves_failure_artifacts(tmp_path):
    from unittest.mock import patch

    def run(command, **kwargs):
        if any("check_tracked_data.py" in str(arg) for arg in command):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema_version": 1, "blocked_count": 0, "files": []}), "")
        if "py_compile" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        junit = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        Path(junit).write_text("<testsuite>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    browser = ["webapp.tests.required_browser::test_required"]
    with patch.object(quality.subprocess, "run", side_effect=run):
        result = quality._write_run_artifacts([], browser, "a" * 40, "b" * 40, root=tmp_path)

    artifacts = tmp_path / "quality-artifacts"
    summary = json.loads((artifacts / "run-summary.json").read_text(encoding="utf-8"))
    assert result == 1
    assert summary["status"] == "FAILED"
    assert summary["test_case_count"] == 0
    assert summary["executed_case_count"] == 0
    assert summary["browser_skipped"] == browser
    assert summary["missing_browser_tests"] == browser
    assert summary["pytest_exit_code"] == 0
    assert (artifacts / "junit.xml").read_text(encoding="utf-8") == "<testsuite>"
    assert (artifacts / "pytest.log").exists()


def test_selected_nonbrowser_skip_fails_quality_run_even_when_another_case_passes(tmp_path):
    from unittest.mock import patch

    def run(command, **kwargs):
        if any("check_tracked_data.py" in str(arg) for arg in command):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema_version": 1, "blocked_count": 0, "files": []}), "")
        if "py_compile" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        junit = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        Path(junit).write_text(
            '<testsuite tests="2" skipped="1">'
            '<testcase classname="synthetic.required" name="passed"/>'
            '<testcase classname="synthetic.required" name="skipped"><skipped message="not run"/>'
            '</testcase></testsuite>', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch.object(quality.subprocess, "run", side_effect=run):
        result = quality._write_run_artifacts([], [], "a" * 40, "b" * 40, root=tmp_path)
    assert result == 1
    summary = json.loads((tmp_path / "quality-artifacts/run-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FAILED"
    assert summary["test_case_count"] == 2
    assert summary["executed_case_count"] == 1
    assert summary["skip_count"] == 1
    assert summary["nonbrowser_skipped_test_cases"] == ["synthetic.required::skipped"]


def test_deleted_paths_are_retained_in_impact_plan():
    assert "app/ledger.py" in quality.build_plan(["app/ledger.py"], selector([]))["changed_paths"]


def test_redirected_pytest_uses_utf8_and_keeps_failure_artifacts(tmp_path, monkeypatch):
    """Exercise a real child stream under a legacy Windows encoding setting."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp949")
    real_run = subprocess.run

    def run(command, **kwargs):
        if any("check_tracked_data.py" in str(arg) for arg in command):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema_version": 1, "blocked_count": 0, "files": []}), "")
        if "py_compile" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        junit = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        Path(junit).write_text('<testsuite><testcase classname="synthetic" name="failure"><failure message="synthetic"/></testcase></testsuite>', encoding="utf-8")
        return real_run([quality.sys.executable, "-c", "print('검사 실패');raise SystemExit(1)"], **kwargs)

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality._write_run_artifacts([], [], "a" * 40, "b" * 40, root=tmp_path) == 1
    artifacts = tmp_path / "quality-artifacts"
    assert "검사 실패" in (artifacts / "pytest.log").read_text(encoding="utf-8")
    summary = json.loads((artifacts / "run-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FAILED"
    assert summary["pytest_exit_code"] == 1
    assert summary["test_case_count"] == 1


def test_selector_malformed_and_unknown_status_fail_closed():
    with pytest.raises(ValueError, match="SELECTOR_MALFORMED"):
        quality.build_plan(["app/file.py"], {"status": "SELECTED", "pytest_commands": []})
    with pytest.raises(ValueError, match="SELECTOR_FAILED"):
        quality.build_plan(["app/file.py"], {"status": "ERROR", "unknown_files": [], "pytest_commands": []})
