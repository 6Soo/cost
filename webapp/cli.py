from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .candidate_reader import ReadOnlyCandidate
from .comparator import compare_rows, export_sidecar_rows, read_sidecar, write_csv
from .operator_ledger import OperatorLedger
from .snapshot_descriptor import seal_snapshot, verify_snapshot


def cmd_seal(args):
    descriptor = seal_snapshot(
        args.db,
        gate_report_path=args.gate_report,
        run_report_path=args.run_report,
        output_path=args.output,
    )
    print(json.dumps(descriptor, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_verify(args):
    result = verify_snapshot(args.descriptor)
    if not result["ok"]:
        for problem in result["problems"]:
            print(f"PROBLEM: {problem}", file=sys.stderr)
        return 2
    print("OK")
    return 0


def _open_snapshot(snapshot_path):
    result = verify_snapshot(snapshot_path)
    if not result["ok"]:
        raise SystemExit(f"snapshot verify failed: {result['problems']}")
    base = Path(snapshot_path).parent
    db = base / result["descriptor"]["candidate_db"]["path"]
    descriptor = dict(result["descriptor"])
    descriptor["base_dir"] = str(base)
    reader = ReadOnlyCandidate(db, descriptor=descriptor)
    if reader.integrity_check() != "ok":
        reader.close()
        raise SystemExit("candidate integrity_check failed")
    return reader


def cmd_compare(args):
    reader = _open_snapshot(args.snapshot)
    try:
        baseline = export_sidecar_rows(reader)
    finally:
        reader.close()
    other = read_sidecar(args.other)
    report = compare_rows(baseline, other)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def cmd_export_sidecar(args):
    reader = _open_snapshot(args.snapshot)
    try:
        rows = export_sidecar_rows(reader)
    finally:
        reader.close()
    path = write_csv(rows, args.output)
    print(path)
    return 0


def cmd_ledger_new(args):
    ledger = OperatorLedger.create(
        args.path, base_candidate_semantic_sha256=args.base_semantic or ""
    )
    ledger.close()
    print(f"created {args.path} + checkpoint")
    return 0


def cmd_ledger_append(args):
    ledger = OperatorLedger(args.path)
    try:
        axes = None
        if args.account:
            axes = {
                "account": args.account,
                "cost_type": args.cost_type,
                "allocation_target": args.allocation_target or None,
                "vat_tag": args.vat_tag or None,
            }
        event, created = ledger.append(
            stream_id=args.stream,
            action=args.action,
            target_direct_event_key=args.target,
            expected_source_sha256=args.source_sha,
            axes=axes,
            evidence_refs=json.loads(args.evidence) if args.evidence else None,
            rationale=args.rationale,
            client_request_id=args.client_request_id,
        )
        print(json.dumps({"created": created, "event_id": event["event_id"]}))
        status = ledger.verify_checkpoint()
        print(json.dumps(status, ensure_ascii=False))
    finally:
        ledger.close()
    return 0


def cmd_ledger_verify(args):
    ledger = OperatorLedger(args.path)
    try:
        chain = ledger.verify_chain()
        checkpoint = ledger.verify_checkpoint()
        print(json.dumps({"chain": chain, "checkpoint": checkpoint},
                         ensure_ascii=False, indent=2))
        ok = chain["ok"] and checkpoint["ok"]
    finally:
        ledger.close()
    return 0 if ok else 2


def cmd_ledger_repair(args):
    ledger = OperatorLedger(args.path)
    try:
        status = ledger.repair_checkpoint()
        print(json.dumps(status, ensure_ascii=False))
    finally:
        ledger.close()
    return 0 if status.get("ok") else 2


def cmd_ledger_backup(args):
    ledger = OperatorLedger(args.path)
    try:
        print(json.dumps(ledger.backup(args.backup), ensure_ascii=False))
    finally:
        ledger.close()
    return 0


def cmd_ledger_materialize(args):
    ledger = OperatorLedger(args.path)
    try:
        print(json.dumps(ledger.materialize(), ensure_ascii=False, indent=2))
    finally:
        ledger.close()
    return 0


def cmd_serve(args):
    from .server import serve

    ledger = OperatorLedger(args.ledger) if args.ledger else None
    app_kwargs = {"include_writes": not args.phase0}
    app = __import__("webapp.server", fromlist=["WebApp"]).WebApp(
        args.snapshot, ledger=ledger, **app_kwargs
    )
    server = serve(app, host="127.0.0.1", port=args.port)
    print(f"serving on http://127.0.0.1:{args.port} "
          f"(phase={'0' if args.phase0 else '1'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ledger:
            ledger.close()
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="webapp")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seal-snapshot")
    p.add_argument("--db", required=True)
    p.add_argument("--gate-report")
    p.add_argument("--run-report")
    p.add_argument("--output")
    p.set_defaults(func=cmd_seal)

    p = sub.add_parser("verify-snapshot")
    p.add_argument("descriptor")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("export-sidecar")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_export_sidecar)

    p = sub.add_parser("compare-sidecar")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--other", required=True)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("ledger-new")
    p.add_argument("path")
    p.add_argument("--base-semantic", default="")
    p.set_defaults(func=cmd_ledger_new)

    p = sub.add_parser("ledger-append")
    p.add_argument("path")
    p.add_argument("--stream", required=True)
    p.add_argument("--action", default="propose")
    p.add_argument("--target")
    p.add_argument("--source-sha")
    p.add_argument("--account")
    p.add_argument("--cost-type", default="여행원가")
    p.add_argument("--allocation-target")
    p.add_argument("--vat-tag")
    p.add_argument("--evidence", help="JSON list of refs")
    p.add_argument("--rationale", required=True)
    p.add_argument("--client-request-id")
    p.set_defaults(func=cmd_ledger_append)

    p = sub.add_parser("ledger-verify")
    p.add_argument("path")
    p.set_defaults(func=cmd_ledger_verify)

    p = sub.add_parser("ledger-repair-checkpoint")
    p.add_argument("path")
    p.set_defaults(func=cmd_ledger_repair)

    p = sub.add_parser("ledger-backup")
    p.add_argument("path")
    p.add_argument("backup")
    p.set_defaults(func=cmd_ledger_backup)

    p = sub.add_parser("ledger-materialize")
    p.add_argument("path")
    p.set_defaults(func=cmd_ledger_materialize)

    p = sub.add_parser("serve")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--ledger")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--phase0", action="store_true",
                   help="read-only mode: no write routes at all")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
