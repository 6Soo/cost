from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp.operator_ledger import OperatorLedger

from .fixtures import demo_axes


class TamperBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cost-tamper-"))
        self.path = self.tmp / "ledger.sqlite"
        self.ledger = OperatorLedger.create(self.path)

    def tearDown(self):
        try:
            self.ledger.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_two(self):
        self.ledger.append(stream_id="T", action="propose", rationale="one")
        self.ledger.append(
            stream_id="T",
            action="shadow_review_confirmed",
            axes=demo_axes(),
            rationale="two",
        )

    def _copy_ledger(self, dest: Path):
        self.ledger.close()
        self.ledger.conn = None
        shutil.copy2(self.path, dest)
        shutil.copy2(
            Path(f"{self.path}.checkpoint.json"),
            Path(f"{dest}.checkpoint.json"),
        )
        self.ledger = OperatorLedger(self.path)

    def _open_raw(self, db_path: Path):
        conn = sqlite3.connect(str(db_path), isolation_level=None)
        conn.execute("DROP TRIGGER IF EXISTS decision_events_no_update")
        conn.execute("DROP TRIGGER IF EXISTS decision_events_no_delete")
        return conn


class CheckpointCrashTests(TamperBase):
    def test_missing_checkpoint_detected_and_repaired(self):
        self._seed_two()
        self.ledger.checkpoint_path.unlink()
        status = self.ledger.verify_checkpoint()
        self.assertEqual(status["status"], "missing_checkpoint")
        self.assertFalse(status["ok"])
        repaired = self.ledger.repair_checkpoint()
        self.assertEqual(repaired["status"], "ok")

    def test_stale_checkpoint_after_crash_before_write(self):
        self._seed_two()
        stale_bytes = self.ledger.checkpoint_path.read_bytes()
        self.ledger.append(stream_id="U", action="propose", rationale="u1")
        self.ledger.checkpoint_path.write_bytes(stale_bytes)
        status = self.ledger.verify_checkpoint()
        self.assertEqual(status["status"], "checkpoint_stale")
        self.assertTrue(status.get("repairable"))
        repaired = self.ledger.repair_checkpoint()
        self.assertEqual(repaired["status"], "ok")

    def test_tail_delete_detected_by_checkpoint(self):
        self._seed_two()
        copy_db = self.tmp / "copy.sqlite"
        self._copy_ledger(copy_db)
        raw = self._open_raw(copy_db)
        try:
            raw.execute(
                "DELETE FROM decision_events WHERE sequence_no=2"
            )
        finally:
            raw.close()
        copied = OperatorLedger(copy_db)
        try:
            chain = copied.verify_chain()
            self.assertTrue(chain["ok"])
            status = copied.verify_checkpoint()
            self.assertEqual(status["status"], "mismatch")
            self.assertFalse(status["ok"])
        finally:
            copied.close()

    def test_field_tamper_breaks_hash(self):
        self._seed_two()
        copy_db = self.tmp / "tampered.sqlite"
        self._copy_ledger(copy_db)
        raw = self._open_raw(copy_db)
        try:
            raw.execute(
                "UPDATE decision_events SET rationale='forged' "
                "WHERE sequence_no=1"
            )
        finally:
            raw.close()
        forged = OperatorLedger(copy_db)
        try:
            chain = forged.verify_chain()
            self.assertFalse(chain["ok"])
            self.assertTrue(
                any("hash mismatch" in p for p in chain["problems"])
            )
        finally:
            forged.close()

    def test_sequence_reorder_detected(self):
        self._seed_two()
        copy_db = self.tmp / "reordered.sqlite"
        self._copy_ledger(copy_db)
        raw = self._open_raw(copy_db)
        try:
            raw.execute(
                "UPDATE decision_events SET sequence_no=-1 WHERE sequence_no=1"
            )
            raw.execute(
                "UPDATE decision_events SET sequence_no=1 WHERE sequence_no=2"
            )
            raw.execute(
                "UPDATE decision_events SET sequence_no=2 WHERE sequence_no=-1"
            )
        finally:
            raw.close()
        reordered = OperatorLedger(copy_db)
        try:
            chain = reordered.verify_chain()
            self.assertFalse(chain["ok"])
        finally:
            reordered.close()

    def test_backup_restore_drill(self):
        self._seed_two()
        backup = self.tmp / "backup.sqlite"
        report = self.ledger.backup(backup)
        self.assertTrue(Path(report["backup_db"]).is_file())
        self.assertTrue(Path(report["backup_checkpoint"]).is_file())
        self.ledger.append(
            stream_id="AFTER", action="propose", rationale="post-backup"
        )
        self.ledger.close()
        os.replace(backup, self.path)
        os.replace(
            Path(f"{backup}.checkpoint.json"),
            Path(f"{self.path}.checkpoint.json"),
        )
        restored = OperatorLedger(self.path)
        try:
            self.assertTrue(restored.verify_chain()["ok"])
            self.assertEqual(restored.verify_checkpoint()["status"], "ok")
            streams = restored.streams()
            self.assertIn("T", streams)
            self.assertNotIn("AFTER", streams)
        finally:
            restored.close()


if __name__ == "__main__":
    unittest.main()
