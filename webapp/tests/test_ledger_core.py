from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp.operator_ledger import ChainViolation, LedgerError, OperatorLedger

from .fixtures import demo_axes


class LedgerCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cost-ledger-"))
        self.path = self.tmp / "operator_ledger.sqlite"
        self.ledger = OperatorLedger.create(
            self.path, base_candidate_semantic_sha256="b" * 64
        )

    def tearDown(self):
        self.ledger.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_and_chain_verify_ok(self):
        first, created = self.ledger.append(
            stream_id="TX-0001",
            action="propose",
            target_direct_event_key="TX-0001",
            axes=demo_axes(allocation_target="0417_아오모리"),
            rationale="portal evidence",
        )
        self.assertTrue(created)
        second, _ = self.ledger.append(
            stream_id="TX-0001",
            action="shadow_review_confirmed",
            axes=demo_axes(allocation_target="0417_아오모리", vat_tag="불공제_해외"),
            rationale="review ok",
        )
        self.assertEqual(second["supersedes_event_id"], first["event_id"])
        result = self.ledger.verify_chain()
        self.assertTrue(result["ok"], result["problems"])
        checkpoint = self.ledger.verify_checkpoint()
        self.assertEqual(checkpoint["status"], "ok")

    def test_first_action_must_be_propose(self):
        with self.assertRaises(ChainViolation):
            self.ledger.append(
                stream_id="S1",
                action="correct",
                axes=demo_axes(),
                rationale="bad start",
            )

    def test_axes_validation_rejects_bad_cost_type(self):
        from webapp.contracts import AxesError

        with self.assertRaises(AxesError):
            self.ledger.append(
                stream_id="S2",
                action="propose",
                axes={"account": "식비", "cost_type": "기타"},
                rationale="bad axis",
            )

    def test_strict_supersedes_must_reference_head(self):
        first, _ = self.ledger.append(
            stream_id="S3", action="propose", rationale="a"
        )
        second, _ = self.ledger.append(
            stream_id="S3", action="correct", rationale="b"
        )
        with self.assertRaises(ChainViolation):
            self.ledger.append(
                stream_id="S3",
                action="correct",
                rationale="c",
                supersedes_event_id=first["event_id"],
            )

    def test_terminal_stream_blocked_after_withdraw(self):
        self.ledger.append(stream_id="S4", action="propose", rationale="a")
        self.ledger.append(stream_id="S4", action="withdraw", rationale="bye")
        with self.assertRaises(ChainViolation):
            self.ledger.append(
                stream_id="S4", action="propose", rationale="again"
            )

    def test_client_request_idempotency(self):
        kwargs = dict(
            stream_id="S5",
            action="propose",
            axes=demo_axes(),
            rationale="once",
            client_request_id="req-777",
        )
        first, created1 = self.ledger.append(**kwargs)
        before = len(self.ledger.all_events())
        second, created2 = self.ledger.append(**kwargs)
        after = len(self.ledger.all_events())
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(before, after)

    def test_attach_evidence_is_new_superseding_event(self):
        head, _ = self.ledger.append(
            stream_id="S6",
            action="propose",
            axes=demo_axes(),
            evidence_refs=[{"kind": "mail", "key": "m1", "sha256": "c" * 64}],
            rationale="initial",
        )
        merged, created = self.ledger.attach_evidence(
            stream_id="S6",
            added_refs=[{"kind": "mail", "key": "m2", "sha256": "d" * 64}],
            rationale="attach more proof",
        )
        self.assertTrue(created)
        self.assertEqual(merged["supersedes_event_id"], head["event_id"])
        refs = json_refs = __import__("json").loads(merged["evidence_refs_json"])
        self.assertEqual(len(refs), 2)
        chain = self.ledger.verify_chain()
        self.assertTrue(chain["ok"])

    def test_triggers_block_update_and_delete(self):
        self.ledger.append(stream_id="S7", action="propose", rationale="keep")
        with self.assertRaises(sqlite3.Error) as ctx:
            self.ledger.conn.execute(
                "UPDATE decision_events SET rationale='tampered'"
            )
        self.assertIn("append_only_violation", str(ctx.exception))
        with self.assertRaises(sqlite3.Error) as ctx:
            self.ledger.conn.execute("DELETE FROM decision_events")
        self.assertIn("append_only_violation", str(ctx.exception))

    def test_materialize_active_and_terminal(self):
        self.ledger.append(
            stream_id="S8",
            action="propose",
            axes=demo_axes(),
            rationale="live",
        )
        self.ledger.append(stream_id="S9", action="propose", rationale="drop")
        self.ledger.append(stream_id="S9", action="reject", rationale="nope")
        view = self.ledger.materialize()
        self.assertIn("S8", view["active"])
        self.assertNotIn("S9", view["active"])
        self.assertEqual(view["resolved_out"][0]["stream_id"], "S9")


if __name__ == "__main__":
    unittest.main()
