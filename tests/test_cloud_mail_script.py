"""Run the synthetic Apps Script collector contract in the normal impact gate."""
from pathlib import Path
import re
import subprocess


def test_cloud_mail_script_contract():
    result = subprocess.run(['node', '--test', 'tests/apps_script/cloud_mail.test.cjs'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        encoding='utf-8', timeout=60)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r'(?:#|ℹ) tests [1-9]\d*', output), output
    assert re.search(r'(?:#|ℹ) skipped 0', output), output
