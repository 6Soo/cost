import json
import subprocess
import sys
from pathlib import Path

from tools.classify_regression_failures import classify_lines


def test_classifies_representative_known_failures_without_raw_text():
    result = classify_lines([
        "FAILED tests/card_pipeline/test_ota_inference.py::test_inferred_link - KeyError: result",
        "FAILED webapp/tests/test_signed_session_http.py::test_session - private token",
        "FAILED webapp/tests/test_participant_income.py::test_asset - customer@example.invalid",
        "FAILED webapp/tests/test_card_flow.py::test_refund - private amount",
        "4 passed, 4 failed",
        "collected 8 items",
    ], exit_code=1)
    assert result["status"] == "FAILED"
    assert result["failure_count"] == 4
    assert set(result["categories"]) == {"ota_inferred_link", "signed_session", "google_asset", "card_flow"}
    assert result["known_failures_are_not_passes"] is True
    assert "private" not in json.dumps(result)
    assert "customer" not in json.dumps(result)


def test_unknown_and_duplicate_failures_are_safe():
    result = classify_lines(["FAILED weird.py::test_x - secret", "FAILED weird.py::test_x - other"], exit_code=1)
    assert result["failure_count"] == 1
    assert result["failed"][0]["category"] == "other"


def test_cli_is_preview_only(tmp_path: Path):
    log = tmp_path / "pytest.log"
    log.write_text("FAILED tests/test_x.py::test_a - secret\n", encoding="utf-8")
    completed = subprocess.run([sys.executable, "tools/classify_regression_failures.py",
                                "--input", str(log), "--exit-code", "1"],
                               capture_output=True, text=True, check=True)
    output = json.loads(completed.stdout)
    assert output["status"] == "FAILED"
    assert output["raw_log_included"] is False


def test_missing_execution_and_collection_only_are_not_passes():
    assert classify_lines([])['status'] == 'UNVERIFIED'
    assert classify_lines([], exit_code=0)['status'] == 'UNVERIFIED'
    assert classify_lines(['collected 8 items'], exit_code=0)['status'] == 'COLLECTION_ONLY'
    assert classify_lines(['2 failed, 3 passed'], exit_code=1)['passed'] == 3


def test_parameter_names_and_collection_errors_are_never_disclosed():
    report = classify_lines(['ERROR tests/test_example.py::test_case[PRIVATE_PERSON_123] - secret'], exit_code=2)
    assert report['status'] == 'FAILED'
    assert report['failed'][0]['nodeid'] == 'tests/test_example.py::test_case'
    assert 'PRIVATE_PERSON' not in json.dumps(report)
    report = classify_lines(['FAILED tests/test_example.py::test_case[PRIVATE_A]',
                             'FAILED tests/test_example.py::test_case[PRIVATE_B]'], exit_code=1)
    assert report['failure_count'] == 2
    assert 'PRIVATE_' not in json.dumps(report)
