"""A repository-owned child process for the turn-ownership tests.

This file is the whole reason it exists. The parent used to launch a script by an
absolute path under one person's temporary directory, so the test could only pass
on the machine that person wrote it on: everywhere else the child was a missing
file and every restart-boundary test failed before it tested anything.

So the child lives in the repository, next to the test that starts it, and is run
as a module (`python -m webapp.tests.ownership_child`). No absolute path, no
per-user directory, nothing outside the checkout.

What it does is deliberately the smallest thing that owns a turn:

* it opens a real LedgerStore on a real SQLite file the parent named,
* it creates a learning case, opens the dialog and opens a conversation,
* it runs one turn whose primary adapter never answers, so the turn is stored as
  pending with this process's run id and a real attempt row, and
* it prints one JSON line naming what the parent needs to look at.

`live` then waits on stdin, so the process is provably running while the parent
checks that its pending turn is left alone. `exit` returns immediately, so the
owner is provably gone. Both are synthetic: the adapter reports
`is_real_call = False` and no provider is contacted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover - direct-execution guard
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp.dialog_turn import SyntheticAdapter
from webapp.ledger_store import LedgerStore

MUSE_MODEL = "opencode/muse-spark-1.3-contributor-free"
GEMINI_MODEL = "synthetic-gemini-placeholder"
ROW_ID = "expense-demo-c3"


def build_pending_turn(db_path, tag):
    """Leave one pending turn owned by this process, and describe it."""
    store = LedgerStore(db_path)
    try:
        case = store.save(
            row_id=ROW_ID,
            expected_revision=store.get_row(ROW_ID)["revision"],
            client_request_id=f"{tag}-case",
            change_mode="rule_change",
            changes={"display_tab_id": "trip-demo-b"},
        )["learning_case_id"]
        store.open_rule_dialog(
            learning_case_id=case,
            draft={"learning_case_id": case,
                   "conditions": {"merchant_normalized": "예시 이동"},
                   "effects": {"item": "교통비확인"}},
            client_request_id=f"{tag}-dialog")
        conversation = store.open_conversation(
            learning_case_id=case, client_request_id=f"{tag}-open")["conversation_id"]
        result = store.run_dialog_turn(
            conversation_id=conversation, client_request_id=f"{tag}-turn",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="pending"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        turn = result["turns"][-1]
        if turn["state"] != "pending":
            raise SystemExit(f"child turn is {turn['state']}, not pending")
        if turn["attempts"][0]["is_real_call"]:
            raise SystemExit("child turn claims a real provider call")
        return {
            "pid": os.getpid(),
            "mode": tag,
            "case_id": case,
            "conversation_id": conversation,
            "turn_id": turn["turn_id"],
            "attempt_id": turn["attempts"][0]["attempt_id"],
            "state": turn["state"],
        }
    finally:
        store.close()


def main(argv):
    if len(argv) != 4:
        raise SystemExit("usage: ownership_child <db> <live|exit> <tag>")
    db_path, mode, tag = argv[1], argv[2], argv[3]
    if mode not in ("live", "exit"):
        raise SystemExit(f"unknown mode {mode}")
    info = build_pending_turn(db_path, tag)
    # One line, flushed, because the parent reads a single line before it does
    # anything else: a child that reported nothing would look like a child that
    # could not start, which is a different failure.
    sys.stdout.write(json.dumps(info, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    if mode == "live":
        # Stay alive until the parent says so. Holding stdin open is what makes
        # "the owner is still running" a fact rather than an assumption.
        try:
            sys.stdin.readline()
        except (KeyboardInterrupt, ValueError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
