# -*- coding: utf-8 -*-
"""Read-only shadow gate for OTA-first authority.

Matches the registered OTA events against the current card rows with the
approved defaults and compares the result with what is already decided: the
exact legacy links, the manual links of the review database, and the ledger.
Nothing is written. Exit code 0 only when every hard gate passes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ota_payments as payments  # noqa: E402

PAID = ("MATCHED_AUTO", "MATCHED_USER")
# Written by the running server itself, not business data.
OPERATIONAL_TABLES = {"rule_process_leases"}


def tables_digest(conn):
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: hashlib.sha256("\n".join(sorted(repr(tuple(r)) for r in conn.execute(f'SELECT * FROM "{t}"'))).encode()).hexdigest()
            for t in names}


def run_gate(db_path, exact_pairs, events, manual_links=None, frozen_groups=None):
    """Return the gate report. `exact_pairs` maps event id -> transaction id."""
    uri = Path(db_path).as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    cards = [dict(r) for r in conn.execute("SELECT * FROM transactions")]
    before = tables_digest(conn)
    ledger_rows = conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0]
    decisions = conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    holds = conn.execute("SELECT COUNT(*) FROM transaction_review_holds").fetchone()[0]
    manual_links = dict(manual_links or {})
    links = {e: {"transaction_id": t, "status": "MATCHED_AUTO"} for e, t in exact_pairs.items()}
    links.update(manual_links)
    inputs = hashlib.sha256(json.dumps([events, cards, links], sort_keys=True, default=str).encode()).hexdigest()
    results = payments.match_ota_payment_events(copy.deepcopy(events), cards, existing_links=links,
                                                rules=[], frozen_groups=frozen_groups or [])
    by_id = {r["ota_event_id"]: r for r in results}
    paid = [r for r in results if r["status"] in PAID and r.get("transaction_id")]
    owners = Counter(r["transaction_id"] for r in paid)
    new_auto = [r for r in results if r["status"] == "MATCHED_AUTO" and r["ota_event_id"] not in exact_pairs
                and r["ota_event_id"] not in manual_links]
    report = {
        "exact_expected": len(exact_pairs),
        "exact_same": sum(by_id.get(e, {}).get("transaction_id") == t for e, t in exact_pairs.items()),
        "exact_changed": sum(e in by_id and by_id[e].get("transaction_id") != t for e, t in exact_pairs.items()),
        "exact_missing": sum(e not in by_id for e in exact_pairs),
        "duplicate_assignment": sum(n - 1 for n in owners.values() if n > 1),
        "manual_overwrite": sum(by_id.get(e, {}).get("transaction_id") != v["transaction_id"] for e, v in manual_links.items()),
        "new_auto": len(new_auto),
        "new_auto_reasons": dict(Counter(r.get("reason") for r in new_auto)),
        "hold": dict(Counter(r["status"] for r in results if r["status"].startswith("HOLD"))),
        "ledger_rows": ledger_rows, "user_decisions": decisions, "review_holds": holds,
        "inputs_unchanged": hashlib.sha256(json.dumps([events, cards, links], sort_keys=True, default=str).encode()).hexdigest() == inputs,
    }
    after = tables_digest(conn)
    report["tables_changed_during_gate"] = sorted(t for t in after if after[t] != before.get(t))
    report["db_unchanged"] = set(report["tables_changed_during_gate"]) <= OPERATIONAL_TABLES
    conn.close()
    report["gate_pass"] = (report["exact_same"] == report["exact_expected"] and report["exact_changed"] == 0
                           and report["exact_missing"] == 0 and report["duplicate_assignment"] == 0
                           and report["manual_overwrite"] == 0 and report["inputs_unchanged"] and report["db_unchanged"])
    return report


def protected_from_host(db_path, review_path):
    """The protected set as it stands now: legacy exact links plus manual links, derived read only.

    Nothing is fixed here. Every run recomputes the set from the current sources, the card board and the
    review database, so the expected count is whatever is protected today.
    """
    import os
    import threading
    from types import SimpleNamespace
    from webapp import ota_payment_review as review

    conn = sqlite3.connect(Path(db_path).as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    board = SimpleNamespace(conn=conn, path=Path(db_path), _lock=threading.RLock())
    previous = os.environ.get("WEBLEDGER_OTA_REVIEW_DB")
    os.environ["WEBLEDGER_OTA_REVIEW_DB"] = str(review_path)
    try:
        backend = review.CoreOtaPaymentBackend.from_host(board, read_only=True)
        try:
            events, transactions, _links, _results = backend._data()
            legacy = backend._legacy_exact_snapshot(events, transactions)
            manual = backend.store.links()
            protected = {str(event): review._link_transaction_id(link) for event, link in legacy.items()
                         if review._link_transaction_id(link)}
            protected.update({str(event): review._link_transaction_id(link) for event, link in manual.items()
                              if review._link_transaction_id(link)})
            manual_links = {str(event): {"transaction_id": review._link_transaction_id(link)}
                            for event, link in manual.items() if review._link_transaction_id(link)}
            return events, protected, manual_links, len(legacy), len(manual_links)
        finally:
            backend.close()
    finally:
        conn.close()
        if previous is None:
            os.environ.pop("WEBLEDGER_OTA_REVIEW_DB", None)
        else:
            os.environ["WEBLEDGER_OTA_REVIEW_DB"] = previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="D:/WebLedgerHost/data/board.sqlite")
    parser.add_argument("--events", default="", help="optional JSON with events and results; default derives "
                                                    "the protected set from the current sources")
    parser.add_argument("--review-db", default="")
    parser.add_argument("--expect-ledger", type=int, default=None)
    parser.add_argument("--expect-decisions", type=int, default=None)
    parser.add_argument("--expect-holds", type=int, default=None)
    args = parser.parse_args(argv)
    if args.events:
        source = json.loads(Path(args.events).read_text(encoding="utf-8"))
        exact = {r["ota_event_id"]: r["transaction_id"] for r in source["results"]
                 if r.get("transaction_id") and r["status"] in PAID}
        manual = {}
        if args.review_db:
            from app.ota_review import OtaReviewStore
            store = OtaReviewStore(Path(args.review_db))
            manual = store.links()
            store.close()
        events = source["events"]
        legacy_count = len(exact)
        manual_count = len(manual)
    else:
        if not args.review_db:
            parser.error("--review-db is required when --events is not given")
        events, exact, manual, legacy_count, manual_count = protected_from_host(args.db, args.review_db)
    report = run_gate(args.db, exact, events, manual)
    report["protected_legacy_exact"] = legacy_count
    report["protected_manual"] = manual_count
    report["protected_expected"] = len(exact)
    if args.expect_ledger is not None:
        report["ledger_unchanged"] = report["ledger_rows"] == args.expect_ledger
    if args.expect_decisions is not None:
        report["decisions_unchanged"] = report["user_decisions"] == args.expect_decisions
    if args.expect_holds is not None:
        report["holds_unchanged"] = report["review_holds"] == args.expect_holds
    report["gate_pass"] = report["gate_pass"] and all(
        report.get(k, True) for k in ("ledger_unchanged", "decisions_unchanged", "holds_unchanged"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
