"""Phase 6C follow-up: who owns a pending turn, and when it is written.

The earlier implementation treated a new LedgerStore instance as a new process
and abandoned every pending turn of a different run id. That killed turns owned
by another connection in the same process and turns owned by a live process.
Ownership is now process-wide with a lease, and a turn is stored as pending
before the provider is called.

The restart boundary is checked with a real subprocess on a real temporary
database, not with injected SQL. The short lease window is the only test knob.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.ledger_store import (
    _PROCESS_PID,
    _PROCESS_RUN_ID,
    LedgerStore,
    _process_alive,
)
from webapp.tests.test_dialog_turns import (
    GEMINI_MODEL,
    MUSE_MODEL,
    SyntheticAdapter,
    learning_case,
    make_store,
    open_ready_dialog,
)

#: The child is a module in this repository, not a path on one machine. Run as
#: `-m` from the checkout root, so the restart boundary is checked with the same
#: files whoever runs the suite.
CHILD_MODULE = "webapp.tests.ownership_child"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHORT_LEASE = "1"


def child_env():
    env = dict(os.environ)
    env["WEBLEDGER_RULE_LEASE_TTL"] = SHORT_LEASE
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def start_child(db_path, mode, tag):
    proc = subprocess.Popen(
        [sys.executable, "-m", CHILD_MODULE, str(db_path), mode, tag],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=child_env(), text=True, encoding="utf-8", errors="replace",
        cwd=str(PROJECT_ROOT),
    )
    try:
        line = proc.stdout.readline()
        if not line:
            proc.wait(timeout=10)
            raise AssertionError(f"child produced no result: {proc.stderr.read()}")
        return proc, json.loads(line)
    except BaseException:
        close_child(proc)
        raise


def close_child(proc):
    try:
        if proc.poll() is None:
            try:
                proc.stdin.write("x\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
    finally:
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()


def wait_lease_to_age(seconds):
    time.sleep(seconds + 0.4)


class PendingIsDurableBeforeTheSendTests(unittest.TestCase):
    """The outstanding request must be on record before the adapter runs."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store, request_id="p7-case")
        open_ready_dialog(self.store, self.case, "p7-dialog")
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p7-open")["conversation_id"]

    def tearDown(self):
        self.store.close()

    def test_pending_row_and_owner_exist_while_the_adapter_is_still_running(self):
        seen = {}

        class InspectingAdapter:
            name = "muse"
            model_id = MUSE_MODEL
            is_real_call = False

            def send(self, request):
                # the send is in flight, so whatever a restart would find must
                # already be committed
                row = self_store.conn.execute(
                    "SELECT state, process_run_id, summary_json FROM rule_turns"
                    " WHERE turn_id=?", (request["turn_id"],)).fetchone()
                seen["row"] = row
                seen["context_present"] = bool(request.get("conversation_id"))
                from webapp.dialog_turn import ProviderResult

                return ProviderResult("pending", "muse", MUSE_MODEL)

        self_store = self.store
        result = self_store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p7-turn",
            muse=InspectingAdapter(),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        self.assertIsNotNone(seen["row"])
        self.assertEqual(seen["row"][0], "pending")
        self.assertEqual(seen["row"][1], _PROCESS_RUN_ID)
        self.assertEqual(json.loads(seen["row"][2])["phase"], "sending")
        self.assertTrue(seen["context_present"])
        self.assertEqual(result["turns"][-1]["state"], "pending")
        # the send finished without an answer, so the turn still waits
        stored = self_store.conversation_state(self.conversation)["turns"][-1]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["state_label"], "응답 대기 중")

    def test_an_answer_to_a_send_that_never_finished_is_refused(self):
        class InspectingAdapter:
            name = "muse"
            model_id = MUSE_MODEL
            is_real_call = False

            def send(self, request):
                from webapp.dialog_turn import ProviderResult

                return ProviderResult("pending", "muse", MUSE_MODEL)

        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p7-turn-2",
            muse=InspectingAdapter(),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        turn = result["turns"][-1]
        late = self.store.adopt_late_response(
            conversation_id=self.conversation, turn_id=turn["turn_id"],
            attempt_id="attempt-from-the-crashed-send",
            client_request_id="p7-late-crashed")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "unknown_attempt")


class SameProcessOwnershipTests(unittest.TestCase):
    """A second connection in this process is not a restart."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store, request_id="p7-case-2")
        open_ready_dialog(self.store, self.case, "p7-dialog-2")
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case,
            client_request_id="p7-open-2")["conversation_id"]

    def tearDown(self):
        self.store.close()

    def _pending_turn(self, request_id):
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id=request_id,
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="pending"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        self.assertEqual(result["turns"][-1]["state"], "pending")
        return result["turns"][-1]["turn_id"]

    def test_a_second_store_in_this_process_keeps_the_pending_turn(self):
        turn_id = self._pending_turn("p7-pending-a")
        second = LedgerStore(self.path)
        try:
            # any mutating call replays the pending work
            second.open_conversation(
                learning_case_id=self.case, client_request_id="p7-open-second")
            state = second.conversation_state(self.conversation)
            stored = [t for t in state["turns"] if t["turn_id"] == turn_id][0]
            self.assertEqual(stored["state"], "pending")
            self.assertEqual(stored["abandoned_reason"], "")
            self.assertIsNone(stored["owner_review"])
            # and the first connection still sees it as pending
            self.assertEqual(
                self.store.conversation_state(self.conversation)["turns"][-1]["state"],
                "pending")
        finally:
            second.close()

    def test_the_two_connections_share_one_process_run_id(self):
        second = LedgerStore(self.path)
        try:
            self.assertEqual(second._process_run_id, self.store._process_run_id)
            self.assertEqual(
                second.conn.execute(
                    "SELECT COUNT(*) FROM rule_process_leases WHERE run_id=?",
                    (_PROCESS_RUN_ID,)).fetchone()[0], 1)
        finally:
            second.close()

    def test_the_lease_heartbeat_moves_forward_on_every_use(self):
        before = self.store.conn.execute(
            "SELECT heartbeat_at FROM rule_process_leases WHERE run_id=?",
            (_PROCESS_RUN_ID,)).fetchone()[0]
        time.sleep(1.05)
        self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p7-open-heartbeat")
        after = self.store.conn.execute(
            "SELECT heartbeat_at FROM rule_process_leases WHERE run_id=?",
            (_PROCESS_RUN_ID,)).fetchone()[0]
        self.assertNotEqual(before, after)
        self.assertGreater(after, before)

    def test_a_pending_turn_of_this_process_survives_its_own_replay(self):
        turn_id = self._pending_turn("p7-pending-b")
        self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p7-open-replay")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == turn_id][0]
        self.assertEqual(stored["state"], "pending")


class LiveChildProcessTests(unittest.TestCase):
    """A pending turn owned by a running process is not touched."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = Path(self.directory) / "owner.sqlite"
        self.proc = None
        self.store = None

    def tearDown(self):
        try:
            if self.proc is not None:
                close_child(self.proc)
        finally:
            if self.store is not None:
                self.store.close()

    def test_a_running_child_keeps_its_pending_turn_and_its_own_answer(self):
        self.proc, info = start_child(self.path, "live", "p7-live")
        self.assertEqual(info["state"], "pending")
        self.assertTrue(_process_alive(info["pid"]))
        # a different process opens the same database
        self.store = LedgerStore(self.path)
        self.store.open_conversation(
            learning_case_id=info["case_id"], client_request_id="p7-live-other")
        state = self.store.conversation_state(info["conversation_id"])
        stored = [t for t in state["turns"] if t["turn_id"] == info["turn_id"]][0]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["abandoned_reason"], "")
        self.assertIsNone(stored["owner_review"])
        # the child's own answer is still adoptable from the other connection,
        # because the owner is still running
        late = self.store.adopt_late_response(
            conversation_id=info["conversation_id"], turn_id=info["turn_id"],
            attempt_id=info["attempt_id"], client_request_id="p7-live-late")
        self.assertEqual(late["late"]["status"], "adopted")
        self.assertEqual(
            [t for t in late["turns"] if t["turn_id"] == info["turn_id"]][0]["state"],
            "answered")
        # the child is still running and its lease is still being held
        self.assertIsNone(self.proc.poll())


class DeadOwnerRecoveryTests(unittest.TestCase):
    """Only a confirmed dead owner is recovered."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = Path(self.directory) / "dead.sqlite"
        import webapp.ledger_store as store_mod

        # Both the environment value and the module constant are process-wide, so
        # both are restored to what they were, through addCleanup rather than
        # tearDown: a failing assertion in the test body still restores them, and
        # a short lease cannot outlive this class and reach a later test.
        previous_env = os.environ.get("WEBLEDGER_RULE_LEASE_TTL")
        previous_ttl = store_mod.LEASE_TTL_SECONDS
        self.addCleanup(self._restore, previous_env, previous_ttl)
        os.environ["WEBLEDGER_RULE_LEASE_TTL"] = SHORT_LEASE
        store_mod.LEASE_TTL_SECONDS = float(SHORT_LEASE)
        self.store = None

    @staticmethod
    def _restore(previous_env, previous_ttl):
        import webapp.ledger_store as store_mod

        if previous_env is None:
            os.environ.pop("WEBLEDGER_RULE_LEASE_TTL", None)
        else:
            os.environ["WEBLEDGER_RULE_LEASE_TTL"] = previous_env
        store_mod.LEASE_TTL_SECONDS = previous_ttl

    def tearDown(self):
        if self.store is not None:
            self.store.close()

    def test_a_turn_of_a_process_that_exited_is_recovered(self):
        proc, info = start_child(self.path, "exit", "p7-dead")
        self.addCleanup(close_child, proc)
        proc.wait(timeout=15)
        self.assertIsNotNone(proc.returncode)
        self.assertFalse(_process_alive(info["pid"]))
        # Pin the age at the inclusive one-second boundary: scheduler delays
        # must not turn this assertion into the expired-lease case. PID checks
        # and the child's persisted lease remain real; expiry below uses time.
        self.store = LedgerStore(self.path)
        with patch("webapp.ledger_store._lease_age_seconds", return_value=float(SHORT_LEASE)):
            self.store.open_conversation(
                learning_case_id=info["case_id"], client_request_id="p7-dead-early")
            state = self.store.conversation_state(info["conversation_id"])
        stored = [t for t in state["turns"] if t["turn_id"] == info["turn_id"]][0]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["owner_review"]["reason"], "owner_still_leased")

        owner = self.store.conn.execute(
            "SELECT process_run_id FROM rule_turns WHERE turn_id=?",
            (info["turn_id"],)).fetchone()[0]
        for age, expected in ((1.0, ("preserve", "owner_still_leased")),
                              (1.000001, ("abandon", "process_restart"))):
            with self.subTest(age=age):
                with patch("webapp.ledger_store._lease_age_seconds", return_value=age):
                    self.assertEqual(self.store._turn_owner_state(owner), expected)

        # after the lease window the owner is confirmed gone
        wait_lease_to_age(float(SHORT_LEASE))
        self.store.open_conversation(
            learning_case_id=info["case_id"], client_request_id="p7-dead-late")
        state = self.store.conversation_state(info["conversation_id"])
        stored = [t for t in state["turns"] if t["turn_id"] == info["turn_id"]][0]
        self.assertEqual(stored["state"], "abandoned")
        self.assertEqual(stored["abandoned_reason"], "process_restart")
        self.assertIsNone(stored["owner_review"])
        # the recovered turn refuses a late answer
        late = self.store.adopt_late_response(
            conversation_id=info["conversation_id"], turn_id=info["turn_id"],
            attempt_id=info["attempt_id"], client_request_id="p7-dead-late-answer")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "process_restart")
        # and the conversation continues on a new turn
        following = self.store.run_dialog_turn(
            conversation_id=info["conversation_id"],
            client_request_id="p7-dead-following",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="connection_refused"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL,
                                    draft={"conditions": {"merchant_normalized": "예시 이동"},
                                           "effects": {"item": "교통비"}}))
        self.assertEqual(following["turns"][-1]["adopted_provider"], "gemini")
        self.assertNotEqual(following["turns"][-1]["turn_id"], info["turn_id"])
        self.assertEqual(len(following["turns"]), 2)


class UnknownOwnershipTests(unittest.TestCase):
    """Unproven ownership is preserved and flagged, never resolved on a guess."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store, request_id="p7-case-3")
        open_ready_dialog(self.store, self.case, "p7-dialog-3")
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case,
            client_request_id="p7-open-3")["conversation_id"]
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p7-pending-3",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="pending"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        self.turn_id = result["turns"][-1]["turn_id"]

    def tearDown(self):
        self.store.close()

    def _replay(self, request_id):
        self.store.open_conversation(
            learning_case_id=self.case, client_request_id=request_id)

    def test_a_turn_with_no_owner_at_all_is_kept_for_review(self):
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='' WHERE turn_id=?", (self.turn_id,))
        self._replay("p7-replay-no-owner")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == self.turn_id][0]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["owner_review"]["reason"], "unknown_owner")

    def test_a_turn_whose_owner_had_no_lease_is_kept_for_review(self):
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='run-that-never-registered'"
            " WHERE turn_id=?", (self.turn_id,))
        self._replay("p7-replay-no-lease")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == self.turn_id][0]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["owner_review"]["reason"], "unknown_owner")

    def test_a_reused_pid_keeps_the_turn_because_aliveness_comes_first(self):
        # a lease that points at a live process but stopped heartbeating is what a
        # recycled pid looks like
        self.store.conn.execute(
            "INSERT OR REPLACE INTO rule_process_leases(run_id, pid, started_at,"
            " heartbeat_at) VALUES ('run-of-recycled-pid', ?, '2020-01-01T00:00:00+00:00',"
            " '2020-01-01T00:00:00+00:00')", (_PROCESS_PID,))
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='run-of-recycled-pid'"
            " WHERE turn_id=?", (self.turn_id,))
        self._replay("p7-replay-recycled-pid")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == self.turn_id][0]
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(stored["owner_review"]["reason"], "owner_pid_reused")

    def test_a_live_owner_inside_its_window_is_left_alone(self):
        self.store.conn.execute(
            "INSERT OR REPLACE INTO rule_process_leases(run_id, pid, started_at,"
            " heartbeat_at) VALUES ('run-of-a-live-process', ?, ?, ?)",
            (_PROCESS_PID, "2020-01-01T00:00:00+00:00", _now()))
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='run-of-a-live-process'"
            " WHERE turn_id=?", (self.turn_id,))
        self._replay("p7-replay-live-owner")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == self.turn_id][0]
        self.assertEqual(stored["state"], "pending")
        self.assertIsNone(stored["owner_review"])

    def test_an_owner_it_cannot_inspect_is_not_treated_as_dead(self):
        """An unreadable owner state is unknown, and unknown means keep."""
        self.store.conn.execute(
            "INSERT OR REPLACE INTO rule_process_leases(run_id, pid, started_at,"
            " heartbeat_at) VALUES ('run-of-an-unreadable-owner', 424242,"
            " '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00')")
        decision, reason = self.store._turn_owner_state(
            "run-of-an-unreadable-owner", alive_probe=lambda pid: None)
        self.assertEqual(decision, "preserve")
        self.assertEqual(reason, "owner_state_unknown")

    def test_the_decision_keeps_every_unproven_owner_and_recovers_only_the_dead_one(self):
        cases = (
            (True, True, ("preserve", "owner_alive")),
            (True, False, ("preserve", "owner_pid_reused")),
            (False, True, ("preserve", "owner_still_leased")),
            (False, False, ("abandon", "process_restart")),
            (None, True, ("preserve", "owner_state_unknown")),
            (None, False, ("preserve", "owner_state_unknown")),
        )
        for alive, fresh, expected in cases:
            with self.subTest(alive=alive, fresh=fresh):
                self.store.conn.execute(
                    "INSERT OR REPLACE INTO rule_process_leases(run_id, pid,"
                    " started_at, heartbeat_at) VALUES ('run-probe', 1, ?, ?)",
                    ("2020-01-01T00:00:00+00:00",
                     _now() if fresh else "2020-01-01T00:00:00+00:00"))
                got = self.store._turn_owner_state("run-probe", alive_probe=lambda pid: alive)
                self.assertEqual(got, expected)

    def test_the_review_is_cleared_once_the_owner_is_confirmed_gone(self):
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='' WHERE turn_id=?", (self.turn_id,))
        self._replay("p7-replay-review-1")
        self.assertIsNotNone(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_orphan_reviews WHERE turn_id=?",
                (self.turn_id,)).fetchone()[0])
        # hand the turn to a confirmed dead owner
        import webapp.ledger_store as store_mod

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.01)"])
        proc.wait(timeout=10)
        self.store.conn.execute(
            "INSERT OR REPLACE INTO rule_process_leases(run_id, pid, started_at,"
            " heartbeat_at) VALUES ('run-of-a-dead-process', ?, '2020-01-01T00:00:00+00:00',"
            " '2020-01-01T00:00:00+00:00')", (proc.pid,))
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='run-of-a-dead-process'"
            " WHERE turn_id=?", (self.turn_id,))
        previous_ttl = store_mod.LEASE_TTL_SECONDS
        store_mod.LEASE_TTL_SECONDS = 0.0
        try:
            self._replay("p7-replay-review-2")
        finally:
            store_mod.LEASE_TTL_SECONDS = previous_ttl
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == self.turn_id][0]
        self.assertEqual(stored["state"], "abandoned")
        self.assertIsNone(stored["owner_review"])
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_orphan_reviews WHERE turn_id=?",
                (self.turn_id,)).fetchone()[0], 0)


def _now():
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


class LeaseHelperTests(unittest.TestCase):
    def test_child_cleanup_reaps_the_process_and_closes_every_pipe(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.readline()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        try:
            self.assertIsNone(proc.poll())
        finally:
            close_child(proc)
        self.assertIsNotNone(proc.returncode)
        self.assertTrue(all(pipe.closed for pipe in (proc.stdin, proc.stdout, proc.stderr)))

    def test_dead_owner_cleanup_restores_absent_and_existing_ttl_values(self):
        import webapp.ledger_store as store_mod

        original_env = os.environ.get("WEBLEDGER_RULE_LEASE_TTL")
        original_ttl = store_mod.LEASE_TTL_SECONDS
        try:
            for previous_env in (None, "137.25"):
                with self.subTest(previous_env=previous_env):
                    DeadOwnerRecoveryTests._restore(previous_env, 137.25)
                    fixture = DeadOwnerRecoveryTests()
                    try:
                        fixture.setUp()
                        self.assertEqual(os.environ["WEBLEDGER_RULE_LEASE_TTL"], SHORT_LEASE)
                        self.assertEqual(store_mod.LEASE_TTL_SECONDS, float(SHORT_LEASE))
                    finally:
                        fixture.doCleanups()
                    self.assertEqual(os.environ.get("WEBLEDGER_RULE_LEASE_TTL"), previous_env)
                    self.assertEqual(store_mod.LEASE_TTL_SECONDS, 137.25)
        finally:
            DeadOwnerRecoveryTests._restore(original_env, original_ttl)

    def test_a_dead_pid_is_never_reported_alive(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.01)"])
        proc.wait(timeout=10)
        self.assertIs(_process_alive(proc.pid), False)
        self.assertIs(_process_alive(_PROCESS_PID), True)
        # a pid this process cannot judge is unknown, never "dead"
        for value in (0, -1, "not-a-pid", None):
            self.assertIsNone(_process_alive(value), value)
        # a pid that does not exist is the only confirmed death
        self.assertIs(_process_alive(0x7FFFFFF0), False)

    def test_the_default_window_is_not_a_short_one(self):
        import webapp.ledger_store as store_mod

        self.assertGreaterEqual(store_mod.LEASE_TTL_SECONDS, 60)


if __name__ == "__main__":
    unittest.main()
