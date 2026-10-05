"""Start only the restored copy on loopback and compare durable state."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_operational_backup_restore import database_state
from webapp import ops


def business_state(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return ops.business_state_digest(SimpleNamespace(conn=connection))["digest"]
    finally:
        connection.close()


def status(path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8974" + path, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return None


def main():
    evidence = ROOT / "docs/handoff/2026-10-01"
    record = json.loads((evidence / "operational-backup-restore-evidence.json").read_text(encoding="utf-8"))
    restored = Path(record["restored_directory"])
    protected_root = Path(r"D:\WebLedgerHost\data\restore-verification").resolve()
    if not restored.resolve().is_relative_to(protected_root):
        raise RuntimeError("RESTORE_ROOT_REFUSED")
    data = restored / "databases"
    board = data / "board.sqlite"
    before = database_state(board)
    choices = data / "real-review.sqlite"
    operator = data / "board.operator.sqlite"
    choices_before = database_state(choices)
    operator_before = database_state(operator)
    meaningful = business_state(board)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8974)) == 0:
            raise RuntimeError("RESTORE_PORT_ALREADY_OCCUPIED")
    environment = dict(os.environ)
    environment["WEBLEDGER_REVIEW_CONFIG"] = str(restored / "config/real-review.json")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    command = [r"D:\WebLedgerHost\venv\Scripts\python.exe", "-u", r"D:\WebLedgerHost\bin\launch_web_ledger.py", "--checkout", str(ROOT), "--data-root", str(data), "--oauth-file", r"D:\WebLedgerHost\secrets\google-oauth-pc-client.json", "--session-secret-file", r"D:\WebLedgerHost\secrets\session-secret.txt", "--port", "8974"]
    with (restored / "host.out.log").open("wb") as out, (restored / "host.err.log").open("wb") as err:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=out, stderr=err, startupinfo=startup)
        try:
            health = None
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("RESTORED_HOST_EXITED")
                health = status("/healthz")
                if health == 200:
                    break
                time.sleep(0.5)
            readiness = status("/readyz")
            anonymous = status("/api/review/model?state_only=1")
            if (health, readiness, anonymous) != (200, 200, 401):
                raise RuntimeError("RESTORED_HOST_PROBE_FAILED")
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                process.wait(timeout=10)
    after = database_state(board)
    changed_tables = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    if set(changed_tables) - {"rule_process_leases"}:
        raise RuntimeError("RESTORED_DATABASE_CONTENT_CHANGED")
    if choices_before != database_state(choices) or operator_before != database_state(operator):
        raise RuntimeError("RESTORED_ASSOCIATED_DATABASE_CHANGED")
    access_before = {name: value for name, value in before.items() if name.startswith("access_")}
    access_after = {name: value for name, value in after.items() if name.startswith("access_")}
    if access_before != access_after or meaningful != business_state(board):
        raise RuntimeError("RESTORED_DURABLE_STATE_CHANGED")
    if status("/healthz") is not None:
        raise RuntimeError("RESTORED_HOST_STILL_LISTENING")
    result = {"restored_server_started": True, "restored_server_stopped": True,
              "loopback_port": 8974, "health_status": health,
              "readiness_status": readiness, "anonymous_review_status": anonymous,
              "business_content_preserved": True,
              "all_access_tables_content_preserved": True,
              "all_durable_tables_content_preserved": True,
              "runtime_tables_changed": changed_tables,
              "review_and_operator_databases_preserved": True,
              "real_google_login_executed_on_copy": False,
              "secrets_reused_from_original_protected_files": True,
              "actual_request_replay_executed": False,
              "actual_import_performed": False}
    (evidence / "restored-host-runtime-evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("RESTORED_HOST_VERIFICATION_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
