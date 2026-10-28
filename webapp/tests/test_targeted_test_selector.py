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


def test_selector_supports_recursive_globs_and_rejects_unsafe_patterns():
    assert SELECTOR.path_matches("webapp/deep/module.py", "webapp/**/*.py")
    try:
        SELECTOR.path_matches("anything.py", "../**/*.py")
    except ValueError:
        pass
    else:
        raise AssertionError("parent traversal pattern must fail closed")


def test_impact_map_validation_rejects_missing_groups_and_unsafe_targets():
    import pytest
    with pytest.raises(ValueError):
        SELECTOR.validate_impact_map({"schema": "cost-test-impact-map-v1", "groups": [],
                                      "safe_fallback_tests": ["tests/safe.py"]})
    with pytest.raises(ValueError):
        SELECTOR.validate_impact_map({"schema": "cost-test-impact-map-v1",
            "groups": [{"name": "bad", "paths": ["src/*.py"], "tests": ["../test.py"]}],
            "safe_fallback_tests": ["tests/safe.py"]})


def test_selector_does_not_report_success_when_no_paths_match():
    targets, unknown = SELECTOR.select_targets(["README.md"], [])

    assert targets == []
    assert unknown == ["README.md"]


def test_repository_map_recognizes_feature_tests_as_well_as_implementation_files():
    import json

    impact_map = json.loads((SCRIPT.parents[1] / "config" / "test-impact-map.json").read_text(
        encoding="utf-8"))
    targets, unknown = SELECTOR.select_targets(
        ["webapp/tests/test_card_flow_browser.py", "webapp/tests/test_ota_payment_review.py",
         "webapp/tests/test_flight_passenger_page.py"], impact_map["groups"])

    assert unknown == []
    assert "webapp/tests/test_card_flow_browser.py" in targets
    assert "webapp/tests/test_ota_payment_review.py" in targets
    assert "webapp/tests/test_flight_passenger_page.py" in targets


def test_unknown_files_keep_error_status_but_receive_safe_commands(monkeypatch, capsys):
    import json
    monkeypatch.setattr(SELECTOR, 'changed_paths', lambda _: ['new/feature.py'])
    assert SELECTOR.main(['--base', 'synthetic']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'UNKNOWN_IMPACT'
    assert result['fallback_selected'] and result['pytest_commands']
    assert not result['tests_executed']
    assert 'tests/card_pipeline/test_partial_refund.py' in result['pytest_commands'][0]


def test_document_only_and_empty_diffs_never_schedule_code_tests(monkeypatch, capsys):
    import json
    for paths, expected in [(['docs/session_handoff.md'], 'DOCS_ONLY'), ([], 'NO_CHANGES')]:
        monkeypatch.setattr(SELECTOR, 'changed_paths', lambda _, p=paths: p)
        assert SELECTOR.main(['--base', 'synthetic']) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['status'] == expected and result['pytest_commands'] == []


def test_core_modules_have_real_safety_targets():
    import json
    config = json.loads(SELECTOR.MAP_PATH.read_text(encoding='utf-8'))
    targets, unknown = SELECTOR.select_targets([
        'app/db.py', 'app/partial_refund.py', 'webapp/access_control.py',
        'webapp/ledger_board.py', 'app/google_authority.py', 'ledger/domain/synthetic.py',
    ], config['groups'])
    assert unknown == []
    assert all((SELECTOR.ROOT / target).is_file() for target in targets)
    assert all((SELECTOR.ROOT / target).is_file() for group in config['groups'] for target in group['tests'])


def test_missing_target_is_structured_error(monkeypatch, tmp_path, capsys):
    import json
    policy = tmp_path / 'map.json'
    policy.write_text(json.dumps({'schema': 'cost-test-impact-map-v1', 'groups': [
        {'paths': ['synthetic.py'], 'tests': ['missing_test.py']}]}), encoding='utf-8')
    monkeypatch.setattr(SELECTOR, 'MAP_PATH', policy)
    monkeypatch.setattr(SELECTOR, 'changed_paths', lambda _: ['synthetic.py'])
    assert SELECTOR.main(['--base', 'synthetic']) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'ERROR'


def test_real_selector_cli_reports_unknown_impact_in_synthetic_git_repo(tmp_path):
    import json
    import subprocess
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    (repo / 'tools').mkdir()
    (repo / 'config').mkdir()
    script = repo / 'tools' / 'select_targeted_tests.py'
    script.write_text(SCRIPT.read_text(encoding='utf-8'), encoding='utf-8')
    (repo / 'config' / 'test-impact-map.json').write_text(json.dumps({
        'schema': 'cost-test-impact-map-v1',
        'groups': [{'name': 'synthetic', 'paths': ['known.py'], 'tests': ['tests/safe.py']}],
        'safe_fallback_tests': ['tests/safe.py'],
    }), encoding='utf-8')
    (repo / 'tests').mkdir()
    (repo / 'tests' / 'safe.py').write_text('def test_safe(): pass\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c',
                    'user.email=synthetic@example.invalid', 'commit', '-qm', 'initial'], check=True)
    base = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()
    (repo / 'unmapped.py').write_text('VALUE = 1\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'change'], check=True)
    proc = subprocess.run([__import__('sys').executable, str(script), '--base', base], cwd=repo,
                          check=False, capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert payload['status'] == 'UNKNOWN_IMPACT'
    assert payload['unknown_files'] == ['unmapped.py']


def test_extracted_runtime_modules_keep_their_feature_contract_tests():
    import json

    config = json.loads(SELECTOR.MAP_PATH.read_text(encoding='utf-8'))
    cases = {
        'webapp/ledger_store_read.py': 'webapp/tests/test_ledger_store.py',
        'webapp/ledger_store_records.py': 'webapp/tests/test_refund_group_commit.py',
        'webapp/board_read_projection.py': 'webapp/tests/test_ledger_server_store_isolation.py',
        'webapp/board_render_helpers.py': 'webapp/tests/test_ledger_board.py',
        'webapp/ledger_design_assets.py': 'webapp/tests/test_ledger_design.py',
        'webapp/ledger_assets.py': 'webapp/tests/test_manual_theme.py',
        'webapp/card_evidence_ui.py': 'webapp/tests/test_cleanup_refund_display.py',
        'webapp/card_refund_ui.py': 'webapp/tests/test_refund_inference_runtime.py',
    }
    for path, expected in cases.items():
        targets, unknown = SELECTOR.select_targets([path], config['groups'])
        assert unknown == [], path
        assert expected in targets, path


def test_rf001_call_map_paths_have_a_specific_test_target():
    import json

    config = json.loads(SELECTOR.MAP_PATH.read_text(encoding='utf-8'))
    targets, unknown = SELECTOR.select_targets([
        'config/refactor-call-map.json',
        'tools/refactor_call_map.py',
        'tests/test_refactor_call_map.py',
    ], config['groups'])
    assert unknown == []
    assert 'tests/test_refactor_call_map.py' in targets
