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
    from . import ops
    from .server import serve

    # The bind address is explicit, not hardcoded. Loopback stays the default
    # and needs no flag: a reverse proxy on this machine terminates HTTPS and
    # forwards here, which is the shape SPEC_REFINEMENT 19.2 asks for. A
    # non-loopback bind has to be stated, because this server does not
    # terminate TLS.
    bind = ops.require_safe_bind(args.host, behind_proxy=args.behind_proxy)

    ledger = OperatorLedger(args.ledger) if args.ledger else None
    app_kwargs = {"include_writes": not args.phase0}
    app = __import__("webapp.server", fromlist=["WebApp"]).WebApp(
        args.snapshot, ledger=ledger, **app_kwargs
    )
    server = serve(app, host=args.host, port=args.port)
    print(f"serving on http://{args.host}:{args.port} "
          f"(phase={'0' if args.phase0 else '1'})")
    print(f"bind shape: {bind['shape']} — {bind['note']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ledger:
            ledger.close()
    return 0


def _ops_config(args, secrets=()):
    from . import ops

    # Only the backup command carries a retention value; the others use the
    # documented default rather than requiring an unused argument.
    return ops.DurableConfig.from_env(
        secrets=secrets,
        keep_backups=getattr(args, "keep_backups", 7),
        environment=args.environment)


def _ops_guard(func):
    """Turn a refused configuration into a reported result, not a crash.

    A fail-closed refusal is an expected outcome of a readiness command, so it
    is printed as JSON with its own code and a non-zero exit, the same shape as
    a failing health check.
    """
    import functools

    @functools.wraps(func)
    def wrapper(args):
        from . import ops

        try:
            return func(args)
        except ops.OpsError as exc:
            print(json.dumps({"ok": False, "code": exc.code,
                              "message": exc.message},
                             ensure_ascii=False, indent=2, sort_keys=True))
            return 2

    return wrapper


@_ops_guard
def cmd_ops_health(args):
    from . import ops

    config = _ops_config(args, secrets=args.secret or ())
    store = None
    if config.db_path.is_file():
        from .ledger_store import LedgerStore

        store = LedgerStore(config.db_path)
    try:
        report = ops.health_check(config, store)
    finally:
        if store is not None:
            store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


@_ops_guard
def cmd_ops_backup(args):
    from . import ops
    from .ledger_store import LedgerStore

    config = _ops_config(args, secrets=args.secret or ())
    store = LedgerStore(config.db_path)
    try:
        manifest = ops.make_backup_bundle(config, store, label=args.label or "")
    finally:
        store.close()
    retention = ops.apply_retention(config)
    print(json.dumps({"backup": manifest, "retention": retention},
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 0


@_ops_guard
def cmd_ops_restore(args):
    from . import ops
    from .ledger_store import LedgerStore

    config = _ops_config(args, secrets=args.secret or ())

    def factory(path):
        store = LedgerStore(path)
        from . import access_control

        access_control.attach_to_ledger_store(store).ensure_schema()
        return store

    result = ops.restore_bundle(config, args.bundle, target_root=args.target,
                                store_factory=factory)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True,
                     default=str))
    return 0 if result["ok"] else 2


@_ops_guard
def cmd_ops_drill(args):
    """Rehearse a restore and report the numbers the cutover needs."""
    from . import ops
    from .ledger_store import LedgerStore

    config = _ops_config(args, secrets=args.secret or ())

    def factory(path):
        store = LedgerStore(path)
        from . import access_control

        access_control.attach_to_ledger_store(store).ensure_schema()
        return store

    store = factory(config.db_path)
    try:
        result = ops.run_restore_drill(
            config, store, target_root=args.target, store_factory=factory)
    finally:
        store.close()
    manifest = ops.build_deploy_manifest(config, bind_host=args.host,
                                         behind_proxy=args.behind_proxy)
    dry = ops.dry_run_deploy(config, manifest)
    unit_path = _write_unit(args, config, manifest)
    if args.runbook:
        ops.write_deploy_runbook(args.runbook, config, manifest, dry,
                                 figures=result["figures"],
                                 unit_path=unit_path)
    print(json.dumps({"drill": {k: v for k, v in result.items()
                                if k != "manifest"},
                      "dry_run": dry, "unit_example": unit_path},
                     ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if result["recoverable"] else 2


@_ops_guard
def cmd_ops_dry_run(args):
    from . import ops

    config = _ops_config(args, secrets=args.secret or ())
    manifest = ops.build_deploy_manifest(config, bind_host=args.host,
                                         behind_proxy=args.behind_proxy)
    run = ops.dry_run_deploy(config, manifest)
    unit_path = _write_unit(args, config, manifest)
    if args.runbook:
        ops.write_deploy_runbook(args.runbook, config, manifest, run,
                                 figures=ops.recovery_figures(config, None),
                                 unit_path=unit_path)
    print(json.dumps({"manifest": manifest, "dry_run": run,
                      "unit_example": unit_path},
                     ensure_ascii=False, indent=2, sort_keys=True))
    # A dry run reports; it never applies. The unmet external conditions stay
    # in the output so a green dry run is not read as a release approval.
    return 0 if run["ok"] else 2


def _write_unit(args, config, manifest):
    """Write the unit example if asked, and never install it."""
    from . import ops

    if not getattr(args, "unit", None):
        return None
    text = ops.service_unit_text(config, manifest, bind_host=args.host,
                                 port=getattr(args, "port", 8751))
    path = Path(args.unit)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


@_ops_guard
def cmd_ops_report(args):
    from . import ops
    from .ledger_store import LedgerStore

    config = _ops_config(args, secrets=args.secret or ())
    store = LedgerStore(config.db_path)
    try:
        report = ops.readiness_report(config, store)
    finally:
        store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


def _add_ops_config(parser, *, with_keep=True):
    parser.add_argument("--environment", default="local-synthetic",
                        help="declared environment; a production value refuses "
                             "a temp-rooted data root")
    parser.add_argument("--secret", action="append", default=[],
                        help="name of a required secret; presence only is read")
    if with_keep:
        parser.add_argument("--keep-backups", type=int, default=7)


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
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address; loopback is the default and is the "
                        "shape 19.2 wants. A non-loopback value is refused "
                        "unless --behind-proxy says a proxy is in front")
    p.add_argument("--behind-proxy", action="store_true",
                   help="state that a TLS-terminating proxy forwards to this "
                        "address; required for a non-loopback bind")
    p.add_argument("--phase0", action="store_true",
                   help="read-only mode: no write routes at all")
    p.set_defaults(func=cmd_serve)

    ops = sub.add_parser("ops", help="local operations readiness commands")
    ops_sub = ops.add_subparsers(dest="ops_command", required=True)

    p = ops_sub.add_parser("health", help="report DB, schema, space and settings")
    _add_ops_config(p, with_keep=False)
    p.set_defaults(func=cmd_ops_health)

    p = ops_sub.add_parser("backup", help="write a backup bundle and apply retention")
    _add_ops_config(p)
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_ops_backup)

    p = ops_sub.add_parser("restore", help="restore a bundle to a separate path")
    _add_ops_config(p, with_keep=False)
    p.add_argument("bundle", help="path of the bundle directory")
    p.add_argument("--target", required=True,
                   help="separate restore target; the live DB is not touched")
    p.set_defaults(func=cmd_ops_restore)

    p = ops_sub.add_parser("dry-run", help="validate a deploy manifest; applies nothing")
    _add_ops_config(p, with_keep=False)
    p.add_argument("--runbook", help="also write the runbook markdown here")
    p.add_argument("--unit", help="also write a systemd unit example here; "
                                  "the file is written, never installed")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address the manifest records; loopback is the "
                        "shape 19.2 wants")
    p.add_argument("--behind-proxy", action="store_true",
                   help="state that a TLS-terminating proxy forwards to this "
                        "address; without it a non-loopback bind fails the "
                        "dry run")
    p.set_defaults(func=cmd_ops_dry_run)

    p = ops_sub.add_parser(
        "drill", help="rehearse a restore and report the 17.2 recovery figures")
    _add_ops_config(p, with_keep=True)
    p.add_argument("--target", required=True,
                   help="separate drill target; the live DB is not touched")
    p.add_argument("--runbook", help="also write the runbook markdown here")
    p.add_argument("--unit", help="also write a systemd unit example here; "
                                  "the file is written, never installed")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address the manifest records")
    p.add_argument("--behind-proxy", action="store_true",
                   help="state that a TLS-terminating proxy forwards to this "
                        "address; without it a non-loopback bind fails the "
                        "dry run")
    p.add_argument("--port", type=int, default=8751,
                   help="port the unit example binds")
    p.set_defaults(func=cmd_ops_drill)

    p = ops_sub.add_parser("readiness", help="measured readiness report")
    _add_ops_config(p, with_keep=False)
    p.set_defaults(func=cmd_ops_report)

    p = ops_sub.add_parser(
        "actions", help="only the states an operator has to act on")
    _add_ops_config(p, with_keep=False)
    p.set_defaults(func=cmd_ops_actions)
    return parser


@_ops_guard
def cmd_ops_actions(args):
    """Print the action-required surface and nothing else.

    It is a separate command because an operator checking "is anything mine to
    fix" should not have to read a whole readiness report to find out.
    """
    from . import ops
    from .ledger_store import LedgerStore

    config = _ops_config(args, secrets=args.secret or ())
    store = LedgerStore(config.db_path)
    try:
        report = ops.action_required_report(config, store)
    finally:
        store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
