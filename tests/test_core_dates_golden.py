"""M3 U7: the committed Rust golden must equal what the current Python date functions produce."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dates_golden_matches_current_python():
    result = subprocess.run(
        [sys.executable, '-I', str(ROOT / 'tools' / 'core_dates_golden.py'),
         '--out', str(ROOT / 'core' / 'golden' / 'synthetic' / 'dates.jsonl'), '--check'],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr