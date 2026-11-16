"""Production host launcher for the web-ledger board.

Existing runtime wiring only. No new judgement, no spec change.

* Does not bypass the existing production readiness gate.
  It pre-binds a real Google OIDC flow and then delegates to
  ``run_candidate.main`` with ``--environment production``.
* No seed, no migration, no auto-approval.
* Never prints a secret value or an exception body. Fixed messages only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")

DEFAULT_PORT = 8751
PUBLIC_BASE_URL = "https://ledger.foresttour.kr"


class _Refused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind OAuth from files and run run_candidate as production."
    )
    parser.add_argument(
        "--checkout",
        required=True,
        help="Source checkout absolute path. Added to sys.path.",
    )
    parser.add_argument(
        "--data-root",
        required=True,
        help="Durable data root absolute path.",
    )
    parser.add_argument(
        "--oauth-file",
        required=True,
        help="Google OAuth JSON absolute path (web.client_id/client_secret).",
    )
    parser.add_argument(
        "--session-secret-file",
        required=True,
        help="Session secret file absolute path.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Bind port. Default 8751.",
    )
    return parser


def _require_absolute(raw: str, label: str) -> pathlib.Path:
    p = pathlib.Path(raw)
    if not p.is_absolute():
        raise _Refused(label)
    # Real file parent integration: canonicalize first, then touch parents.
    return p.resolve()


def _read_oauth_file(real: pathlib.Path) -> tuple[str, str]:
    parent = real.parent
    if not parent.is_dir():
        raise _Refused("OAUTH_FILE")
    if not real.is_file():
        raise _Refused("OAUTH_FILE")
    try:
        data = json.loads(real.read_text(encoding="utf-8"))
        web = data.get("web") if isinstance(data, dict) else None
        if not isinstance(web, dict):
            raise _Refused("OAUTH_FILE")
        client_id = web.get("client_id")
        client_secret = web.get("client_secret")
        if not isinstance(client_id, str) or not client_id.strip():
            raise _Refused("OAUTH_FILE")
        if not isinstance(client_secret, str) or not client_secret.strip():
            raise _Refused("OAUTH_FILE")
        return client_id.strip(), client_secret.strip()
    except _Refused:
        raise
    except Exception:
        raise _Refused("OAUTH_FILE")


def _read_session_secret_file(real: pathlib.Path) -> str:
    # Required parent creation before read.
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        raise _Refused("SESSION_SECRET_FILE")
    if not real.is_file():
        raise _Refused("SESSION_SECRET_FILE")
    try:
        value = real.read_text(encoding="utf-8").strip()
    except Exception:
        raise _Refused("SESSION_SECRET_FILE")
    if not value:
        raise _Refused("SESSION_SECRET_FILE")
    return value


def apply_ota_review(options: dict) -> None:
    """OTA review mode comes only from card-flow.json. Absent means legacy, so inherited variables are cleared."""
    ota = options.get('ota_review') or {}
    mode = ota.get('mode', 'legacy')
    for name in ('WEBLEDGER_OTA_REVIEW_MODE', 'WEBLEDGER_OTA_REVIEW_DB', 'WEBLEDGER_OTA_AUTHORITY'):
        os.environ.pop(name, None)
    if mode == 'legacy':
        return
    if mode not in ('isolated', 'authority'):
        raise _Refused("OTA_REVIEW_MODE")
    review_db = pathlib.Path(str(ota.get('review_db', '')))
    if not review_db.is_absolute():
        raise _Refused("OTA_REVIEW_DB")
    os.environ['WEBLEDGER_OTA_REVIEW_MODE'] = 'isolated'
    os.environ['WEBLEDGER_OTA_REVIEW_DB'] = str(review_db)
    if mode == 'authority':
        os.environ['WEBLEDGER_OTA_AUTHORITY'] = 'authority'


def apply_product_features(options: dict, root: pathlib.Path) -> None:
    """Explicit opt-ins use durable paths under the existing host data root."""
    for name in ('WEBLEDGER_RECEIPTS_STORE', 'WEBLEDGER_RECEIPT_OCR',
                 'WEBLEDGER_RECEIPT_WORKFLOW_ENABLED',
                 'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', 'WEBLEDGER_GOOGLE_LEDGER_ROWS',
                 'WEBLEDGER_LOCAL_RULE_AI', 'WEBLEDGER_FLIGHT_PASSENGER_MATCHING',
                 'WEBLEDGER_FLIGHT_PASSENGER_DB', 'WEBLEDGER_INSURANCE_REVIEW_MANIFEST'):
        os.environ.pop(name, None)
    receipts = options.get('receipts') or {}
    if receipts.get('enabled') is True:
        os.environ['WEBLEDGER_RECEIPTS_STORE'] = str(root / 'receipts' / 'receipts.json')
        engine = receipts.get('ocr')
        if engine not in (None, 'windows'):
            raise _Refused('RECEIPT_OCR')
        if engine:
            os.environ['WEBLEDGER_RECEIPT_OCR'] = engine
        if receipts.get('workflow') is True:
            os.environ['WEBLEDGER_RECEIPT_WORKFLOW_ENABLED'] = '1'
    if (options.get('google_ledger') or {}).get('enabled') is True:
        os.environ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT'] = str(root / 'google-authority' / 'snapshot.json')
        os.environ['WEBLEDGER_GOOGLE_LEDGER_ROWS'] = str(root / 'google-authority' / 'rows.json')
    if options.get('local_rule_ai') is True:
        os.environ['WEBLEDGER_LOCAL_RULE_AI'] = '1'
    if (options.get('flight_passengers') or {}).get('enabled') is True:
        os.environ['WEBLEDGER_FLIGHT_PASSENGER_MATCHING'] = '1'
        os.environ['WEBLEDGER_FLIGHT_PASSENGER_DB'] = str(root / 'flight-passenger.sqlite')
    review = options.get('insurance_review') or {}
    if review.get('enabled') is True:
        manifest = pathlib.Path(str(review.get('manifest_path') or ''))
        if not manifest.is_absolute() or not manifest.is_file() or manifest.is_symlink():
            raise _Refused('INSURANCE_REVIEW_MANIFEST')
        os.environ['WEBLEDGER_INSURANCE_REVIEW_MANIFEST'] = str(manifest)


def apply_core_switches(options: dict, root: pathlib.Path) -> None:
    """Writer switches come only from card-flow.json and reach only this launched process."""
    from app import core_switch_config

    try:
        core_switch_config.apply(options, root)
    except core_switch_config.CoreSwitchRefused as exc:
        raise _Refused(exc.code) from None


def require_card_schema(path: pathlib.Path) -> None:
    """Production never authorizes CardFlow's automatic schema creation.

    Check before LedgerStore opens the database, using a read-only connection.
    The environment also keeps later Store construction in check-only mode.
    """
    from app.db import Store

    os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] = 'require'
    try:
        Store.require_existing_schema(path)
    except Exception:
        raise _Refused('CARD_SCHEMA') from None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] = 'require'
    # Only this launch's explicit card-flow.json opt-in may start the sync.
    os.environ.pop('WEBLEDGER_RESERVE_TRIP_SYNC', None)

    try:
        checkout = _require_absolute(args.checkout, "CHECKOUT")
        root = _require_absolute(args.data_root, "DATA_ROOT")
        oauth_path = _require_absolute(args.oauth_file, "OAUTH_FILE")
        session_path = _require_absolute(args.session_secret_file, "SESSION_SECRET_FILE")
        port = int(args.port)
        if not 1 <= port <= 65535:
            raise _Refused("PORT")
        if not checkout.is_dir():
            raise _Refused("CHECKOUT")
        flow_config = root.parent / 'config' / 'card-flow.json'
        checkout_str = str(checkout)
        if checkout_str not in sys.path:
            sys.path.insert(0, checkout_str)
        from app import core_switch_config
        apply_product_features({}, root)
        apply_core_switches({}, root)
        if flow_config.is_file():
            options = core_switch_config.read_options(flow_config.parent)
            apply_product_features(options, root)
            apply_core_switches(options, root)
            if options.get('enabled') is True:
                os.environ['WEBLEDGER_UNIFIED_DB'] = '1'
                os.environ['WEBLEDGER_CARD_FLOW'] = '1'
                os.environ['WEBLEDGER_TRIP_AUTHORITY'] = options['trip_authority_path']
                if options.get('ota_mail_dir'):
                    os.environ['WEBLEDGER_OTA_MAIL_DIR'] = options['ota_mail_dir']
                if options.get('reserve_trip_sync') is True:
                    os.environ['WEBLEDGER_RESERVE_TRIP_SYNC'] = '1'
                if options.get('review_from'):
                    datetime.date.fromisoformat(options['review_from'])
                    os.environ['WEBLEDGER_REVIEW_FROM'] = options['review_from']
                apply_ota_review(options)
        try:
            core_switch_config.record_applied('board', flow_config.parent, checkout.name)
        except OSError:
            pass  # the deploy check then fails on the missing record
    except _Refused as exc:
        print(f"refused [{exc.code}]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
        return 2
    except Exception:
        print("refused [ARG]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
        return 2

    try:
        client_id, client_secret = _read_oauth_file(oauth_path)
        os.environ["WEBLEDGER_GOOGLE_CLIENT_ID"] = client_id
        os.environ["WEBLEDGER_GOOGLE_CLIENT_SECRET"] = client_secret

        session_secret = _read_session_secret_file(session_path)
        os.environ["WEBLEDGER_SESSION_SECRET"] = session_secret
        os.environ["WEBLEDGER_PUBLIC_BASE_URL"] = PUBLIC_BASE_URL

        checkout_str = str(checkout)
        if checkout_str not in sys.path:
            sys.path.insert(0, checkout_str)

        from webapp import access_control
        from webapp import google_oidc
        from webapp import ledger_board
        from webapp import ops
        from webapp.ledger_store import LedgerStore

        config = ops.durable_config_for(root, environment="production", create=True)
        from run_candidate import validate_optional_data_paths
        validate_optional_data_paths(config)
        if os.environ.get('WEBLEDGER_CARD_FLOW') == '1':
            require_card_schema(config.db_path)
        store = LedgerStore(config.db_path, seed_demo=False)
    except _Refused as exc:
        print(f"refused [{exc.code}]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
        return 2
    except Exception:
        print("refused [PREPARE]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
        return 2

    try:
        try:
            access = access_control.attach_to_ledger_store(store)
        except Exception:
            print("refused [ACCESS]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
            return 2
        try:
            flow = google_oidc.try_connect_from_env(access)
        except Exception:
            print("refused [OIDC]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
            return 2
        if flow is None:
            print("refused [OIDC]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
            return 2
        try:
            ledger_board.bind_oidc(flow)
        except Exception:
            print("refused [OIDC]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
            return 2

        try:
            import run_candidate
        except Exception:
            print("refused [ENTRY]: 실행 조건을 만족하지 않아요.", file=sys.stderr)
            return 2

        rc = run_candidate.main(
            [
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--data-root",
                str(root),
                "--environment",
                "production",
                "--no-worker",
            ]
        )
        try:
            return int(rc)
        except Exception:
            return 0 if rc is None else 2
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
