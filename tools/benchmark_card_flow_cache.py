"""Synthetic-only baseline for CardFlow's existing OTA report caches.

This benchmark uses a temporary LedgerStore and an explicit empty OTA source
manifest. It does not discover or open configured/customer sources.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.request_metrics import percentile


def _report_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str).encode("utf-8"))


def run(*, repeats=7, rows=40):
    if type(repeats) is not int or not 1 <= repeats <= 50:
        raise ValueError("repeats must be between 1 and 50")
    if type(rows) is not int or not 0 <= rows <= 500:
        raise ValueError("rows must be between 0 and 500")

    # Import only after the environment is pinned to a temporary synthetic root.
    with tempfile.TemporaryDirectory(prefix="cost-card-flow-benchmark-") as temp:
        root = Path(temp)
        mail_fixture = root / "synthetic-mail"
        mail_fixture.mkdir()
        source_manifest = root / "ota-sources.json"
        source_manifest.write_text(json.dumps({
            "schema_version": "ota-sources-v1", "mail_directories": [str(mail_fixture)],
            "portal_databases": [], "reference_documents": []}), encoding="utf-8")
        old_sources = os.environ.get("WEBLEDGER_OTA_SOURCES")
        old_unified = os.environ.get("WEBLEDGER_UNIFIED_DB")
        board = None
        old_mail_memo = None
        query_log = []
        query_count = 0

        def trace(_statement):
            nonlocal query_count
            query_count += 1
            query_log.append(_statement)

        try:
            os.environ["WEBLEDGER_OTA_SOURCES"] = str(source_manifest)
            os.environ["WEBLEDGER_UNIFIED_DB"] = "1"
            from unittest.mock import patch
            from webapp.ledger_store import LedgerStore
            from webapp.card_flow import CardFlow
            from webapp import ota_payment_review
            from app import ota_exact, ota_mail, ota_payments, ota_portal

            old_mail_memo = dict(ota_mail._MAIL_SIDE_MEMO)
            board = LedgerStore(root / "synthetic-ledger.sqlite", seed_demo=False)
            board.conn.set_trace_callback(trace)
            flow = CardFlow(board)
            timings = {"cold": [], "warm": [], "request_memo_cold": [], "request_memo_hit": []}
            cache_sizes = []
            report_bytes = 0
            query_counts = {}
            query_shapes = {}
            open_ids_equivalent = None
            stage_calls = {"cold": {}, "warm": {}, "request_memo_cold": {}, "request_memo_hit": {}}
            counters = {"match_mail": 0, "payment_events": 0, "portal_extend": 0,
                        "reference_load": 0, "snapshot_service": 0}

            def counted(name, callback):
                def invoke(*args, **kwargs):
                    counters[name] += 1
                    return callback(*args, **kwargs)
                return invoke

            # Add synthetic rows only. Each row has no merchant/customer/source text.
            for index in range(rows):
                classification_source = "owner_card_residual" if index == 0 else ""
                board.conn.execute(
                    "INSERT INTO transactions(transaction_id,source_hash,batch_id,issuer,card_tail,card_kind,"
                    "transaction_direction,transaction_kind,approval_number,original_approval_number,approval_date,"
                    "posting_date,merchant,merchant_normalized,amount_krw,foreign_amount,foreign_currency,row_index,"
                    "raw_row_json,conflict_reason,parse_error,classification_state,classification_source,item,description,"
                    "display_tab_id,trip_id,revision,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"tx-{index:04d}", f"hash-{index:04d}", "synthetic-batch", "synthetic", "0000", "domestic",
                     "purchase", "purchase", f"approval-{index:04d}", "", "2026-10-01", "2026-10-02",
                     "synthetic-store", "synthetic-store", 100 + index, "", "KRW", index, "{}", "", "",
                     "needs_review", classification_source, "", "", "", "", 1,
                     "2026-10-30T00:00:00Z"))
            if rows > 1:
                board.conn.execute(
                    "INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) "
                    "VALUES(?,?,?,?,?)", ("card-tx-0001", "expense", "trip-synthetic", 1, "{}"))
            board.conn.commit()
            board.conn.set_trace_callback(None)
            expected_open_ids = sorted(ota_exact.open_transaction_ids(board.conn))
            protected_sources = ','.join("'" + source.replace("'", "''") + "'"
                                         for source in ota_exact.PROTECTED_SOURCES)
            actual_open_ids = [row[0] for row in board.conn.execute(
                'SELECT t.transaction_id FROM transactions t WHERE '
                't.classification_source NOT IN ('+protected_sources+') AND NOT EXISTS('
                "SELECT 1 FROM board_rows b WHERE b.row_kind='expense' "
                "AND b.row_id='card-' || t.transaction_id) ORDER BY t.transaction_id").fetchall()]
            open_ids_equivalent = actual_open_ids == expected_open_ids
            assert open_ids_equivalent
            board.conn.set_trace_callback(trace)

            with ExitStack() as stack:
                stack.enter_context(patch.object(ota_mail, "match_mail",
                                                   counted("match_mail", ota_mail.match_mail)))
                stack.enter_context(patch.object(ota_payments, "build_ota_payment_events",
                                                   counted("payment_events", ota_payments.build_ota_payment_events)))
                stack.enter_context(patch.object(ota_portal, "extend_report",
                                                   counted("portal_extend", ota_portal.extend_report)))
                stack.enter_context(patch.object(ota_mail, "load_reference_documents",
                                                   counted("reference_load", ota_mail.load_reference_documents)))
                stack.enter_context(patch.object(ota_payment_review, "enabled", return_value=False))
                stack.enter_context(patch.object(
                    ota_payment_review, "snapshot_service",
                    counted("snapshot_service", ota_payment_review.snapshot_service)))

                for index in range(repeats):
                    # Clear nested mail memo so each cold pass measures parsing/matching work.
                    ota_mail._MAIL_SIDE_MEMO.clear()
                    counters.update({key: 0 for key in counters})
                    board._card_review_mail_cache = None
                    before_queries = query_count
                    started = time.perf_counter()
                    report = flow._compute_ota_report()
                    timings["cold"].append((time.perf_counter() - started) * 1000)
                    query_counts["cold"] = query_count - before_queries
                    query_shapes["cold"] = query_log[before_queries:]
                    stage_calls["cold"] = dict(counters)
                    report_bytes = _report_bytes(report)
                    cache = board._card_review_mail_cache
                    cache_sizes.append(_report_bytes(cache) if cache else 0)

                    # Warm cache path still builds the source/card fingerprint via SQL.
                    counters.update({key: 0 for key in counters})
                    before_queries = query_count
                    started = time.perf_counter()
                    warm = flow._compute_ota_report()
                    timings["warm"].append((time.perf_counter() - started) * 1000)
                    query_counts["warm"] = query_count - before_queries
                    query_shapes["warm"] = query_log[before_queries:]
                    stage_calls["warm"] = dict(counters)
                    assert warm is report

                    # Existing per-request memo path: first call computes once, later call reuses.
                    board._card_review_mail_cache = None
                    ota_mail._MAIL_SIDE_MEMO.clear()
                    with flow._ota_request_scope():
                        counters.update({key: 0 for key in counters})
                        before_queries = query_count
                        started = time.perf_counter()
                        first_memo = flow._ota_report()
                        timings["request_memo_cold"].append((time.perf_counter() - started) * 1000)
                        query_counts["request_memo_cold"] = query_count - before_queries
                        query_shapes["request_memo_cold"] = query_log[before_queries:]
                        stage_calls["request_memo_cold"] = dict(counters)
                        counters.update({key: 0 for key in counters})
                        before_queries = query_count
                        started = time.perf_counter()
                        second_memo = flow._ota_report()
                        timings["request_memo_hit"].append((time.perf_counter() - started) * 1000)
                        query_counts["request_memo_hit"] = query_count - before_queries
                        query_shapes["request_memo_hit"] = query_log[before_queries:]
                        stage_calls["request_memo_hit"] = dict(counters)
                        assert first_memo is not None and second_memo is not None
                        assert _report_bytes(first_memo) == _report_bytes(second_memo)
                        assert query_count - before_queries == 0
                        assert board._card_review_mail_cache is not None

            return {
                "scope": "synthetic_only_no_customer_source_access_snapshot_service_disabled",
                "fixture_rows": rows, "repeats": repeats,
                "measurement_kind": "actual_card_flow_compute_with_temp_sqlite_and_empty_source_manifest",
                "cache_report_bytes": {"samples": len(cache_sizes), "max": max(cache_sizes, default=0),
                                       "mean": round(sum(cache_sizes) / len(cache_sizes), 1)},
                "query_count_per_call": query_counts,
                "query_shape_counts": {name: {statement: statements.count(statement)
                                               for statement in sorted(set(statements))}
                                       for name, statements in query_shapes.items()},
                "expensive_stage_calls_per_call": stage_calls,
                "latency_ms": {name: {"p50": percentile(values, 50), "p95": percentile(values, 95),
                                       "samples": len(values)} for name, values in timings.items()},
                "report_bytes": report_bytes,
                "open_ids_equivalent_to_existing_helper": open_ids_equivalent,
                "optimization_status": "synthetic_duplicate_query_consolidation",
            }
        finally:
            if board is not None:
                board.conn.set_trace_callback(None)
                board.close()
            if old_mail_memo is not None and "ota_mail" in locals():
                ota_mail._MAIL_SIDE_MEMO.clear()
                ota_mail._MAIL_SIDE_MEMO.update(old_mail_memo)
            if old_sources is None:
                os.environ.pop("WEBLEDGER_OTA_SOURCES", None)
            else:
                os.environ["WEBLEDGER_OTA_SOURCES"] = old_sources
            if old_unified is None:
                os.environ.pop("WEBLEDGER_UNIFIED_DB", None)
            else:
                os.environ["WEBLEDGER_UNIFIED_DB"] = old_unified


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--rows", type=int, default=40)
    args = parser.parse_args(argv)
    print(json.dumps(run(repeats=args.repeats, rows=args.rows),
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
