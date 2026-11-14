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
REUSE_SPEC = importlib.util.spec_from_file_location(
    "reuse_quality_evidence", ROOT / "tools/reuse_quality_evidence.py")
reuse_quality = importlib.util.module_from_spec(REUSE_SPEC)
REUSE_SPEC.loader.exec_module(reuse_quality)


def selector(paths, status="SELECTED", targets=None):
    return {"status": status, "unknown_files": paths,
            "pytest_commands": [["python", "-m", "pytest", *(targets or ["tests/test_cost_audit.py"]), "-q"]]}


class _ReuseEvidenceAPI:
    def __init__(self, *, changed_path="webapp/example.py", tree=None, skipped=0, expired=False):
        self.changed_path = changed_path
        self.tree = tree or "b" * 40
        self.skipped = skipped
        self.expired = expired
        self.tested_merge = "a" * 40
        self.plan = {"status": "SELECTED", "head_sha": self.tested_merge, "head_tree_sha": self.tree,
                     "base_sha": "c" * 40,
                     "pytest_targets": ["tests/test_cost_audit.py"], "browser_tests": [],
                     "browser_required": False, "unknown_paths": []}
        self.summary = {"status": "PASSED", "head_sha": self.tested_merge, "head_tree_sha": self.tree,
                        "base_sha": "c" * 40,
                        "browser_required": False,
                        "pytest_targets": self.plan["pytest_targets"], "test_case_count": 4,
                        "executed_case_count": 4, "skip_count": skipped,
                        "skipped_test_cases": [], "nonbrowser_skipped_test_cases": [],
                        "browser_skipped": [], "missing_browser_tests": [], "browser_executed": []}

    def json(self, url):
        if "/commits/merge-1/pulls" in url:
            return [{"number": 42, "merged_at": "2026-11-06T00:00:00Z", "merge_commit_sha": "merge-1",
                     "base": {"ref": "main", "repo": {"full_name": "6Soo/cost"}},
                     "head": {"sha": "head-1", "repo": {"full_name": "6Soo/cost"}}}]
        if "/pulls/42/files" in url:
            return [{"filename": self.changed_path}]
        if "/actions/workflows/quality.yml/runs?" in url:
            return {"workflow_runs": [{"id": 900, "path": ".github/workflows/quality.yml",
                    "head_sha": "head-1", "event": "pull_request", "status": "completed",
                    "conclusion": "success", "run_attempt": 1}]}
        if "/actions/runs/900/artifacts" in url:
            return {"artifacts": [{"name": "quality-evidence-900-1", "expired": self.expired,
                    "created_at": "2026-11-06T00:00:00Z", "archive_download_url": "artifact-1"}]}
        raise AssertionError(url)

    def artifact(self, url):
        import io
        import zipfile
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("quality-plan.json", json.dumps(self.plan))
            archive.writestr("quality-artifacts/run-summary.json", json.dumps(self.summary))
        return payload.getvalue()


def test_main_quality_evidence_reuse_requires_exact_tree_and_complete_pr_proof():
    api = _ReuseEvidenceAPI()
    result = reuse_quality.find_reusable_evidence(api, "6Soo/cost", "merge-1", "b" * 40)
    assert result["status"] == "REUSED_VERIFIED"
    assert result["reuse"]["pull_request"] == 42
    assert result["reuse"]["skipped_test_count"] == 0


@pytest.mark.parametrize("api,tree", [
    (_ReuseEvidenceAPI(), "c" * 40),
    (_ReuseEvidenceAPI(changed_path=".github/workflows/quality.yml"), "b" * 40),
    (_ReuseEvidenceAPI(skipped=1), "b" * 40),
    (_ReuseEvidenceAPI(expired=True), "b" * 40),
])
def test_main_quality_evidence_reuse_fails_closed(api, tree):
    assert reuse_quality.find_reusable_evidence(api, "6Soo/cost", "merge-1", tree) is None


def test_docs_only_and_empty_changes_do_not_schedule_code_checks():
    assert quality.build_plan([], {})["steps"] == []
    docs = quality.build_plan(["docs/specs/change.md"], {})
    assert docs["status"] == "DOCS_ONLY"
    assert docs["steps"] == ["documentation-diff-and-links"]


def test_quality_plan_records_exact_checked_out_tree():
    plan = quality.plan("HEAD", "HEAD")
    expected = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    assert plan["head_tree_sha"] == expected


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
    assert "webapp.tests.test_site_shell_browser::SiteShellBrowserTests::test_theme_keyboard_motion_and_responsive_contract" in plan["browser_tests"]
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
               "webapp/tests/test_card_history_upload_feedback.py", "webapp/tests/test_card_catalog_browser.py"]
    cases = quality.collect_browser_tests(targets)
    expected = {
        "webapp.tests.test_card_flow_browser::CardFlowBrowserTests::test_legacy_cleanup_links_migrate_to_actions_and_history",
        "webapp.tests.test_site_shell_browser::SiteShellBrowserTests::test_theme_keyboard_motion_and_responsive_contract",
        "webapp.tests.test_card_history_upload_feedback::test_upload_with_legacy_gap_needs_no_period_confirmation",
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_header_buttons_sort_and_filter_without_search_click",
        "webapp.tests.test_card_catalog_browser::CardCatalogBrowserTests::test_menu_search_and_source_review_at_390",
    }
    assert expected <= set(cases)
    assert len([case for case in cases if case.startswith("webapp.tests.test_card_flow_browser::")]) == 16
    assert len([case for case in cases if case.startswith("webapp.tests.test_site_shell_browser::")]) == 9
    assert len([case for case in cases if case.startswith("webapp.tests.test_card_history_upload_feedback::")]) == 3


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
        "webapp.tests.test_insurance_income_match_browser::test_name_action_keeps_income_and_never_guesses_ambiguous_identity",
        "webapp.tests.test_flight_booking_name_search::test_browser_name_search_renders_verified_itinerary_and_secondary_participant_flow",
        "webapp.tests.test_rule_review::RuleReviewTests::test_browser_reports_saved_rule_when_followup_state_request_fails",
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


def _git_repo_with_deletion(tmp_path, monkeypatch, *, delete, add=()):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    for name in ("gone/old.py", "app/mapped.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
                          capture_output=True, text=True).stdout.strip()
    for name in delete:
        (tmp_path / name).unlink()
    for name in add:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("y = 2\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "change")
    monkeypatch.setattr(selector_tool, "ROOT", tmp_path)
    return base


def _selector_with_map(tmp_path, monkeypatch, base, capsys):
    (tmp_path / "tests").mkdir(exist_ok=True)
    for name in ("test_a.py", "test_b.py"):
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")
    impact = tmp_path / "map.json"
    impact.write_text(json.dumps({
        "schema": "cost-test-impact-map-v1", "safe_fallback_tests": ["tests/test_b.py"],
        "groups": [{"name": "g", "paths": ["app/mapped.py"], "tests": ["tests/test_a.py"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(selector_tool, "MAP_PATH", impact)
    code = selector_tool.main(["--base", base])
    return code, json.loads(capsys.readouterr().out)


def test_deleted_unmapped_only_diff_is_not_unknown_impact(tmp_path, monkeypatch, capsys):
    base = _git_repo_with_deletion(tmp_path, monkeypatch, delete=["gone/old.py"])
    code, payload = _selector_with_map(tmp_path, monkeypatch, base, capsys)
    assert code == 0 and payload["unknown_files"] == []
    assert payload["deleted_unmapped_files"] == ["gone/old.py"]
    (tmp_path / "tests" / "test_quality_checks.py").write_text("", encoding="utf-8")
    plan = quality.build_plan(["gone/old.py"], payload, root=tmp_path)
    assert plan["status"] == "SELECTED"
    assert plan["pytest_targets"] == ["tests/test_quality_checks.py"]


def test_deleted_mapped_file_still_selects_its_group(tmp_path, monkeypatch, capsys):
    base = _git_repo_with_deletion(tmp_path, monkeypatch, delete=["app/mapped.py"])
    code, payload = _selector_with_map(tmp_path, monkeypatch, base, capsys)
    assert code == 0 and payload["unknown_files"] == []
    assert payload["deleted_unmapped_files"] == []
    assert payload["pytest_commands"][0][3:-1] == ["tests/test_a.py"]


def test_added_unmapped_file_is_still_unknown_impact(tmp_path, monkeypatch, capsys):
    base = _git_repo_with_deletion(tmp_path, monkeypatch, delete=["gone/old.py"],
                                   add=["new/product.py"])
    code, payload = _selector_with_map(tmp_path, monkeypatch, base, capsys)
    assert code == 2 and payload["unknown_files"] == ["new/product.py"]
    with pytest.raises(ValueError, match="UNKNOWN_IMPACT:1"):
        quality.build_plan(["gone/old.py", "new/product.py"], payload, root=tmp_path)


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


def test_parameterized_browser_cases_are_counted_and_skips_remain_blocking(tmp_path):
    junit = tmp_path / "junit.xml"
    browser = ["webapp.tests.test_refund::test_review"]
    junit.write_text('<testsuite><testcase classname="webapp.tests.test_refund" name="test_review[complete]"/><testcase classname="webapp.tests.test_refund" name="test_review[pending]"><skipped/></testcase><testcase classname="webapp.tests.test_refund" name="test_review_other"/></testsuite>', encoding="utf-8")
    result = quality.summarize_junit(junit, browser)
    assert result["browser_executed"] == browser
    assert result["browser_skipped"] == browser
    assert result["missing_browser_tests"] == []
    assert result["skip_count"] == 1


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
        result = quality._write_run_artifacts([], browser, "a" * 40, "b" * 40,
                                              head_tree_sha="c" * 40, root=tmp_path)

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
        result = quality._write_run_artifacts([], [], "a" * 40, "b" * 40,
                                              head_tree_sha="c" * 40, root=tmp_path)
    assert result == 1
    summary = json.loads((tmp_path / "quality-artifacts/run-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "FAILED"
    assert summary["test_case_count"] == 2
    assert summary["executed_case_count"] == 1
    assert summary["skip_count"] == 1
    assert summary["nonbrowser_skipped_test_cases"] == ["synthetic.required::skipped"]


@pytest.mark.parametrize(("failed_name", "expected_status", "expected_exit"), [
    ("known", "PASSED", 0),
    ("new", "FAILED", 1),
])
def test_quality_run_accepts_only_baseline_failures(tmp_path, capsys, failed_name,
                                                   expected_status, expected_exit):
    from unittest.mock import patch

    config = tmp_path / "config"
    config.mkdir()
    (config / "known-test-failures.txt").write_text(
        "# baseline sha: " + "a" * 40 + "\nsynthetic.test::known\n", encoding="utf-8")

    def run(command, **kwargs):
        if any("check_tracked_data.py" in str(arg) for arg in command):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema_version": 1, "blocked_count": 0, "files": []}), "")
        if "py_compile" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        junit = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        Path(junit).write_text(
            f'<testsuite><testcase classname="synthetic.test" name="{failed_name}">'
            '<failure message="synthetic"/></testcase></testsuite>', encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, "", "")

    with patch.object(quality.subprocess, "run", side_effect=run):
        result = quality._write_run_artifacts([], [], "a" * 40, "b" * 40,
                                              head_tree_sha="c" * 40, root=tmp_path)
    summary = json.loads((tmp_path / "quality-artifacts/run-summary.json").read_text(encoding="utf-8"))
    assert result == expected_exit
    assert summary["status"] == expected_status
    assert summary["known_failure_count"] == (1 if failed_name == "known" else 0)
    assert ("알려진 실패 1건" in capsys.readouterr().out) is (failed_name == "known")


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
    assert quality._write_run_artifacts([], [], "a" * 40, "b" * 40,
                                        head_tree_sha="c" * 40, root=tmp_path) == 1
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


def test_known_failure_classification_allows_only_failures_in_baseline():
    result = quality.classify_known_failures(
        {"tests/test_old.py::test_known"}, {"tests/test_old.py::test_known"},
        {"tests/test_old.py::test_known"})
    assert result == {"known_failed_test_cases": ["tests/test_old.py::test_known"],
                      "new_failed_test_cases": [], "resolved_known_test_cases": [],
                      "known_failure_count": 1}


def test_known_failure_classification_rejects_one_failure_outside_baseline():
    result = quality.classify_known_failures(
        {"tests/test_old.py::test_known"}, {"tests/test_old.py::test_known",
                                             "tests/test_new.py::test_regression"}, set())
    assert result["new_failed_test_cases"] == ["tests/test_new.py::test_regression"]


def test_known_failure_classification_reports_resolved_executed_items():
    result = quality.classify_known_failures(
        {"tests/test_old.py::test_fixed"}, set(), {"tests/test_old.py::test_fixed"})
    assert result["known_failed_test_cases"] == []
    assert result["resolved_known_test_cases"] == ["tests/test_old.py::test_fixed"]


def test_empty_known_failure_list_does_not_hide_a_failure(tmp_path):
    config = tmp_path / "known-test-failures.txt"
    config.write_text("# baseline sha: abc\n", encoding="utf-8")
    known = quality.load_known_failures(config)
    result = quality.classify_known_failures(known, {"tests/test_new.py::test_new"}, set())
    assert known == set()
    assert result["new_failed_test_cases"] == ["tests/test_new.py::test_new"]


def test_known_failure_list_accepts_intermittent_marker_and_comments(tmp_path):
    config = tmp_path / "known-test-failures.txt"
    config.write_text("# baseline\ntests/a.py::A::test_one\ntests/b.py::test_two  # 간헐\n",
                      encoding="utf-8")
    assert quality.load_known_failures(config) == {"tests/a.py::A::test_one", "tests/b.py::test_two"}


def test_committed_known_failure_list_is_sorted_and_marks_baseline():
    path = quality.ROOT / "config" / "known-test-failures.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "기준 SHA" in lines[0]
    names = [line.split("  # ", 1)[0] for line in lines if not line.startswith("#")]
    assert names == sorted(names) and len(names) == len(set(names))


def test_known_failure_inventory_change_selects_its_quality_gate():
    plan = quality.build_plan(["config/known-test-failures.txt"],
                              selector(["config/known-test-failures.txt"]))
    assert "tests/test_quality_checks.py" in plan["pytest_targets"]


def test_core_change_requires_cargo_steps():
    plan = quality.build_plan(["core/Cargo.toml"], selector([], targets=["tests/test_quality_checks.py"]))
    assert plan["rust_required"] is True
    assert {"cargo-fmt", "cargo-clippy", "cargo-test"} <= set(plan["steps"])
    other = quality.build_plan(["app/ledger.py"], selector([]))
    assert other["rust_required"] is False and "cargo-test" not in other["steps"]


def test_missing_cargo_fails_instead_of_skipping(monkeypatch, tmp_path):
    monkeypatch.setattr(quality, "find_cargo", lambda: None)
    with (tmp_path / "log.txt").open("w", encoding="utf-8") as log:
        result = quality.run_cargo_steps(log, root=tmp_path)
    assert result["status"] == "FAILED" and result["reason"] == "CARGO_NOT_FOUND"


def _fake_cargo(monkeypatch, failing_step):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command[1:])
        code = 1 if command[1] == failing_step else 0
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(quality, "find_cargo", lambda: "cargo")
    monkeypatch.setattr(quality.subprocess, "run", fake_run)
    return calls


@pytest.mark.parametrize("failing", ["fmt", "clippy", "test", None])
def test_cargo_step_failure_marks_run_failed(monkeypatch, tmp_path, failing):
    calls = _fake_cargo(monkeypatch, failing)
    with (tmp_path / "log.txt").open("w", encoding="utf-8") as log:
        result = quality.run_cargo_steps(log, root=tmp_path)
    assert [c[0] for c in calls] == ["fmt", "clippy", "test"]
    assert result["status"] == ("FAILED" if failing else "PASSED")
    if failing:
        failed = [s["step"] for s in result["steps"] if s["exit_code"] != 0]
        assert failed == [f"cargo-{failing}"]


def test_cargo_target_dir_is_per_worktree_on_windows(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(quality, "find_cargo", lambda: "cargo")
    monkeypatch.setattr(quality.os, "name", "nt")
    monkeypatch.setattr(quality, "DEFAULT_WINDOWS_TARGET_DIR", tmp_path / "cargo-target")
    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    monkeypatch.setattr(quality.subprocess, "run", lambda command, **kw: (
        seen.append(kw["env"].get("CARGO_TARGET_DIR")) or subprocess.CompletedProcess(command, 0)))
    work = tmp_path / "wt-a"
    work.mkdir()
    with (tmp_path / "log.txt").open("w", encoding="utf-8") as log:
        result = quality.run_cargo_steps(log, root=work)
    assert result["target_dir"] == str(tmp_path / "cargo-target" / "wt-a")
    assert set(seen) == {result["target_dir"]}


def test_quality_run_records_policy_and_guard_changes_without_failing(tmp_path, capsys):
    from unittest.mock import patch

    def run(command, **kwargs):
        if any("check_tracked_data.py" in str(arg) for arg in command):
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "schema_version": 1, "blocked_count": 0, "files": []}), "")
        if command[0] == "git":
            return subprocess.CompletedProcess(
                command, 0, "config/tracked-data-policy.json\ntools/check_tracked_data.py\nREADME.md\n", "")
        if "py_compile" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        junit = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        Path(junit).write_text('<testsuite><testcase classname="s" name="ok"/></testsuite>',
                               encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch.object(quality.subprocess, "run", side_effect=run):
        result = quality._write_run_artifacts([], [], "a" * 40, "b" * 40,
                                              head_tree_sha="c" * 40, root=tmp_path)
    assert result == 0
    summary = json.loads((tmp_path / "quality-artifacts/run-summary.json").read_text(encoding="utf-8"))
    assert summary["policy_changed"] is True
    assert summary["policy_changed_files"] == [
        "config/tracked-data-policy.json", "tools/check_tracked_data.py"]
    assert "정책·가드 변경 — opus 검수 필요" in capsys.readouterr().out
