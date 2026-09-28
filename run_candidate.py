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

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the web-ledger fixed candidate as a service.")
    parser.add_argument("--port", type=int, default=8751)
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
    args = parser.parse_args(argv)

    try:
        data_root = resolve_data_root(args.data_root)
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
    except ops.OpsError as exc:
        print(f"refused [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2

    from webapp import ledger_board as board_mod

    server = board_mod.serve(port=args.port, db_path=config.db_path,
                             with_worker=not args.no_worker, host=args.host)
    print(f"serving fixed candidate on http://{args.host}:{args.port}")
    print(f"bind shape: {bind['shape']} — {bind['note']}")
    print(f"data root: {config.data_root}")
    print(f"db: {config.db_path}")
    print("screens:")
    for path in ("/board", "/import", "/export",
                 "/income/income-demo-i1/split"):
        print(f"  http://{args.host}:{args.port}{path}")
    print(f"  http://{args.host}:{args.port}/rules?case=<learning_case_id>   "
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
        worker = getattr(server, "card_worker", None)
        if worker is not None:
            worker.stop(timeout=5)
        server.shutdown()
        server.server_close()
        board_mod.bind_store(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
