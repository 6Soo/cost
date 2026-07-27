from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "ledger"
CANONICAL = LEDGER / "data/classified_v14.csv"


class PatchV14VersioningTest(unittest.TestCase):
    def test_patch_writes_new_file_without_mutating_input(self) -> None:
        before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "candidate.csv"
            subprocess.run(
                [
                    sys.executable,
                    "patch_v14.py",
                    "--input",
                    str(CANONICAL),
                    "--output",
                    str(output),
                ],
                cwd=LEDGER,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(output.exists())
            self.assertEqual(
                hashlib.sha256(CANONICAL.read_bytes()).hexdigest(),
                before,
            )
            replay = subprocess.run(
                [
                    sys.executable,
                    "patch_v14.py",
                    "--input",
                    str(CANONICAL),
                    "--output",
                    str(output),
                ],
                cwd=LEDGER,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(replay.returncode, 0)
            self.assertIn("기존 후보를 덮어쓰지 않습니다", replay.stderr)

    def test_in_place_output_is_rejected(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "patch_v14.py",
                "--input",
                str(CANONICAL),
                "--output",
                str(CANONICAL),
            ],
            cwd=LEDGER,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("인플레이스 덮어쓰기", result.stderr)


if __name__ == "__main__":
    unittest.main()
