import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "select_targeted_tests.py"
SPEC = importlib.util.spec_from_file_location("select_targeted_tests", SCRIPT)
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


def test_selector_maps_changes_and_marks_unclassified_files_unknown():
    impact_map = {
        "groups": [
            {"paths": ["webapp/card_flow.py"],
             "tests": ["webapp/tests/test_card_flow.py"]},
            {"paths": ["app/ota_*.py"],
             "tests": ["tests/card_pipeline/test_ota_payments.py"]},
        ]
    }

    targets, unknown = SELECTOR.select_targets(
        ["webapp\\card_flow.py", "app/ota_payments.py", "new/feature.py"], impact_map["groups"])

    assert targets == ["tests/card_pipeline/test_ota_payments.py",
                       "webapp/tests/test_card_flow.py"]
    assert unknown == ["new/feature.py"]


def test_selector_does_not_report_success_when_no_paths_match():
    targets, unknown = SELECTOR.select_targets(["README.md"], [])

    assert targets == []
    assert unknown == ["README.md"]
