"""Run the web-ledger board as a long-lived service.

The bind address is explicit. Loopback is the default and is the shape
SPEC_REFINEMENT 19.2 asks for: a reverse proxy on this machine terminates HTTPS
and forwards to the app, and the SQLite file, the source directories and the
worker port are never opened to the network. A non-loopback bind exists for a
proxy in another network namespace and has to be stated with `--behind-proxy`,
because this process does not terminate TLS.

The data root is explicit too. There is no default inside the source checkout:
18.3 item 2 forbids durable data in a checkout or a working-directory-relative
path, because a redeploy or a checkout wipe takes it along. The rule is not
invented here; `ops.DurableConfig` already refuses relative paths, the historical
development defaults and a temp-rooted production data root, so this entry point
goes through the same check instead of keeping a second one.

This script starts the app and nothing else. It does not install a service, does
not write outside the data root, and does not read a secret value.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from webapp import ops  # noqa: E402

DEFAULT_PORT = 8751


def resolve_data_root(argv_root: str | None) -> pathlib.Path:
    """The durable data root, from --data-root or WEBLEDGER_DATA_ROOT.

    A missing value is a refusal rather than a default. Silently creating
    `<checkout>/runtime` is the behaviour this replaces. The refusal is an
    `OpsError` like every other one here, so the caller turns all of them into
    the same message shape and the same exit code.
    """
    raw = argv_root or os.environ.get("WEBLEDGER_DATA_ROOT")
    if not raw:
        raise ops.OpsError(
            "MISSING_SETTING",
            "WEBLEDGER_DATA_ROOT 가 필요해요 (또는 --data-root).\n"
            "소스 체크아웃 안에 운영 자료를 두지 않아요. 명세 18.3 2항.\n"
            "지속 디스크의 절대 경로를 지정해 주세요. 예: --data-root /srv/web-ledger/data")
    return pathlib.Path(raw)


def connect_runtime_oidc(server, args):
    """Connect a real Google login when the environment configured one.

    Three shapes, in this order:

    * ``--synthetic-sessions`` binds the local header seam. It is refused when a
      real login is configured, because SPEC 16.1 forbids using a development
      switch as operational authentication and running both would leave the
      question of which one decided a request open.
    * a configured environment connects the real flow.
    * neither leaves the board fail-closed, which serves no account rather than
      a weaker one.

    No secret value is read, printed or passed to anything except the flow that
    has to use it.
    """
    from webapp import access_control
    from webapp import google_oidc
    from webapp import ledger_board as board_mod

    access = access_control.attach_to_ledger_store(server.card_store)
    if args.synthetic_sessions:
        if any(os.environ.get(name) for name in google_oidc.REQUIRED_ENV):
            raise ops.OpsError(
                "MIXED_AUTH_PATHS",
                "Google 로그인 설정이 있는데 --synthetic-sessions 도 요청했어요. "
                "둘 중 하나만 써요. 명세 16.1")
        access_control.bind_synthetic_sessions(True)
        return None
    flow = google_oidc.try_connect_from_env(access)
    if flow is not None:
        board_mod.bind_oidc(flow)
    return flow

def describe_oidc(flow) -> str:
    """One line about the login path. Presence and shape, never a value."""
    from webapp import google_oidc

    state = google_oidc.connection_state(flow)
    if not state.get("google_oidc_connected"):
        if state.get("library_available") is False and flow is not None:
            return f"설정됨, 하지만 google-auth 가 없어 로그인 거절 ({state.get('reason')})"
        return f"연결 안 됨 - {state.get('reason')}"
    owner = ("owner sub 설정됨" if state.get("owner_bootstrap_configured")
             else "owner sub 미설정 (첫 로그인은 viewer)")
    return (f"연결됨 (account key = {state.get('account_key')}, "
            f"owner bootstrap: {owner})")


def bind_runtime_access(server):
    """Enable the fail-closed access boundary for a long-lived deployment.

    `ledger_board.serve()` intentionally stays usable by synthetic/local tests,
    where access control is bound explicitly.  The production entry point must
    not inherit that permissive default: it attaches the access tables to the
    same durable SQLite store before the HTTP server starts accepting requests.

    Until a real session adapter (for example Google OIDC) is configured, the
    default unbound adapter returns no session and protected requests answer
    401.  That is the safe deployment posture.
    """
    from webapp import access_control
    from webapp import ledger_board as board_mod

    access_store = access_control.attach_to_ledger_store(server.card_store)
    board_mod.bind_access(access_store)
    return access_store


def resolve_port(argv_port: int | None) -> int:
    """The port to bind: the flag, else the platform's `PORT`, else the default.

    A PaaS assigns the port at start time and tells the process through `PORT`.
    Ignoring it and binding 8751 means the platform's traffic arrives at a
    closed port and the deployment looks like a crash-loop for a reason that has
    nothing to do with the application. The flag still wins, so a person can
    override what the platform asked for.
    """
    if argv_port is not None:
        return int(argv_port)
    raw = os.environ.get("PORT")
    if raw:
        try:
            port = int(raw)
        except (TypeError, ValueError):
            raise ops.OpsError(
                "PORT_NOT_A_NUMBER",
                f"PORT 환경값이 숫자가 아니에요: {raw!r}\n"
                f"플랫폼이 주는 포트 번호여야 합니다. "
                f"--port 로 직접 지정할 수도 있습니다.") from None
        if not 1 <= port <= 65535:
            raise ops.OpsError("PORT_OUT_OF_RANGE",
                               f"PORT 가 범위를 벗어났어요: {port}")
        return port
    return DEFAULT_PORT


def gate_on_readiness(config, *, required: bool) -> str:
    """Run the smoke report and say whether this process may serve.

    A local or synthetic run is not gated: a developer server with no Google
    client and no persistent disk is working as declared, and refusing to start
    it would be noise. A production run is gated, because SPEC_REFINEMENT 18.3
    and 19.4 ask for a deployment to be exercised *before* a cutover rather than
    discovered by a user afterwards.

    Returns a line for the operator to read. Raises only when the gate is
    `required`.

    An earlier version raised in both cases, under a code that said the failure
    was being ignored while the process exited with 2. A code that says
    "ignored" while the process exits is the kind of message an operator learns
    to distrust, and a name that could be misread as a production verdict is
    worse. When the gate is not required, the blockers are printed in full and
    the server starts -- as a local development run, which is all it can be,
    since a missing database or a missing schema is not a running ledger.
    """
    from webapp import ops

    # No store is passed on purpose. `smoke_report` opens the database
    # read-only, so the gate observes what is there instead of creating a
    # healthy-looking database and then reporting on it.
    report = ops.smoke_report(config)
    if report["ok"]:
        return "smoke ok"
    detail = ", ".join(report["blockers"]) or "unknown"
    summary = (f"readiness: NOT READY but not required here "
               f"(environment={config.environment}, "
               f"not an operational verdict) blockers: {detail}")
    if required:
        raise ops.OpsError(
            "SMOKE_FAILED",
            f"운영 준비 검사에서 막혔어요: {detail}\n"
            f"경고: {', '.join(report['warnings']) or '없음'}\n"
            f"먼저 `ops smoke` 의 나머지 항목을 확인해 주세요.")
    return summary


def build_parser():
    """The entry point's own parser, so another module can check a command.

    The deploy manifest records this script as the command a platform would
    run, and the dry run has to know whether that command is complete. Reading
    the arguments from one place is what makes that check possible; parsing them
    against a different module's parser would answer a different question.
    """
    parser = argparse.ArgumentParser(
        description="Run the web-ledger fixed candidate as a service.")
    parser.add_argument("--port", type=int, default=None,
                        help="bind port; defaults to the platform's PORT and "
                             "then to 8751. A PaaS assigns the port at start "
                             "time, so ignoring it would bind a port nothing "
                             "is forwarded to")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address; loopback by default, which is the "
                             "shape 19.2 wants")
    parser.add_argument("--behind-proxy", action="store_true",
                        help="state that a TLS-terminating proxy forwards to "
                             "this address; required for a non-loopback bind")
    parser.add_argument("--data-root", help="durable data root; defaults to "
                                            "WEBLEDGER_DATA_ROOT and is required")
    parser.add_argument("--no-worker", action="store_true",
                        help="do not start the card import worker")
    parser.add_argument("--environment", default="local-synthetic",
                        help="declared environment. A production value refuses a "
                             "temp-rooted or checkout-rooted data root, so the "
                             "serving process is held to the same rules as the "
                             "health, readiness and drill commands")
    parser.add_argument("--synthetic-sessions", action="store_true",
                        help="bind the local header seam instead of a real "
                             "login. Refused when the Google environment is "
                             "also set, and never an operational path")
    parser.add_argument("--require-ready", action="store_true",
                        help="run the production smoke report before serving "
                             "and refuse to start on a blocker. Implied by "
                             "--environment production")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.environment == 'production':
        os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] = 'require'

    try:
        data_root = resolve_data_root(args.data_root)
        port = resolve_port(args.port)
        # The bind is checked before the data root is touched, so an unsafe bind
        # never gets as far as creating a directory. A refusal is a message and
        # an exit code, not a traceback: this file is the first thing an
        # operator runs on a new machine.
        bind = ops.require_safe_bind(args.host,
                                     behind_proxy=args.behind_proxy)
        # The layout comes from the same configuration object the health,
        # readiness and drill commands read, so the service and the checks
        # cannot disagree about where the data lives. Creating the root is what
        # makes the configuration valid, and DurableConfig then applies every
        # refusal: a relative root, a development default, a temp-rooted
        # production root and a root inside this source checkout are all
        # rejected here rather than by a second rule set in this file.
        config = ops.durable_config_for(data_root, environment=args.environment,
                                        create=True)
        if args.environment == 'production' and os.environ.get('WEBLEDGER_CARD_FLOW') == '1':
            from app.db import Store
            try:
                Store.require_existing_schema(config.db_path)
            except Exception:
                raise ops.OpsError('CARD_SCHEMA', '카드 스키마 준비와 복구 검증이 필요합니다') from None
        # The readiness gate runs before anything binds a port, so a
        # misconfigured deployment never accepts a request it cannot serve.
        smoke = gate_on_readiness(
            config,
            required=args.require_ready or args.environment == "production")
    except ops.OpsError as exc:
        print(f"refused [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2

    from webapp import ledger_board as board_mod

    os.environ['WEBLEDGER_DB'] = str(config.db_path)
    server = board_mod.serve(port=port, db_path=config.db_path,
                             with_worker=not args.no_worker, host=args.host,
                             # SPEC_REFINEMENT 18.3 5항: an operational start
                             # never fabricates rows. The demo board stays a
                             # developer default.
                             seed_demo=args.environment == "local-synthetic")
    try:
        bind_runtime_access(server)
        oidc = connect_runtime_oidc(server, args)
    except ops.OpsError as exc:
        server.server_close()
        print(f"refused [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2
    reserve_stop = None
    if os.environ.get('WEBLEDGER_RESERVE_TRIP_SYNC') == '1':
        from app.reserve_trips import start_sync
        reserve_stop = start_sync(server.card_store, os.environ['WEBLEDGER_TRIP_AUTHORITY'],
            config.db_path.parent / 'evidence')
    print(f"serving fixed candidate on http://{args.host}:{port}")
    print(f"bind shape: {bind['shape']} - {bind['note']}")
    print(f"data root: {config.data_root}")
    print(f"db: {config.db_path}")
    print(f"readiness: {smoke}")
    print(f"google login: {describe_oidc(oidc)}")
    print("screens:")
    for path in ("/board", "/import", "/export",
                 "/income/income-demo-i1/split"):
        print(f"  http://{args.host}:{port}{path}")
    print(f"  http://{args.host}:{port}/rules?case=<learning_case_id>   "
          "(needs a case; bare /rules answers 404)")
    print("operations:")
    print(f"  {' '.join([sys.executable, '-m', 'webapp.cli', 'ops', 'health', '--secret', 'MUSE_KEY'])}")
    print(f"  {' '.join([sys.executable, '-m', 'webapp.cli', 'ops', 'actions'])}")
    print(f"  {' '.join([sys.executable, '-m', 'webapp.cli', 'ops', 'drill', '--target', '/var/tmp/web-ledger-drill'])}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if reserve_stop is not None:
            reserve_stop.set()
        worker = getattr(server, "card_worker", None)
        if worker is not None:
            worker.stop(timeout=5)
        from webapp import ota_payment_review
        ota_payment_review.shutdown_snapshot_service(server.card_store)
        server.shutdown()
        server.server_close()
        board_mod.bind_oidc(None)
        board_mod.bind_access(None)
        board_mod.bind_store(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
