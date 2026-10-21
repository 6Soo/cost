"""Back up quiescent operational inputs and verify a separate local restore.

The administrator wrapper pauses managed writers. Only aggregate evidence
leaves the protected host directory; every raw copy stays under that root.
"""
import base64
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from webapp.real_review import BoundInputs, load_manifest


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def database_state(path):
    connection = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("DATABASE_INTEGRITY_FAILED")
        states = {}
        tables = connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        for table, schema in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in connection.execute("PRAGMA table_info(" + quoted + ")")]
            rows = []
            for row in connection.execute("SELECT * FROM " + quoted):
                values = [({"bytes": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value) for value in row]
                rows.append(json.dumps(values, ensure_ascii=False, separators=(",", ":")))
            payload = json.dumps([schema, columns, sorted(rows)], ensure_ascii=False, separators=(",", ":"))
            states[table] = {"rows": len(rows), "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
        return states
    finally:
        connection.close()


def backup_database(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        original.backup(copy)
        # Produce a self-contained offline copy. A WAL-mode backup otherwise
        # recreates empty -wal/-shm files during read-only verification and is
        # correctly refused by the isolated migration gate. Never change source.
        if copy.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
            raise RuntimeError('BACKUP_JOURNAL_MODE_FAILED')
    finally:
        copy.close()
        original.close()


def product_files(host):
    """Return private product files for the same backup and restore hash checks."""
    files = {}
    for config_file in sorted((host / 'config').glob('*.json')):
        if config_file.is_symlink():
            raise RuntimeError('SOURCE_LINK_REFUSED')
        files['host-config/' + config_file.name] = config_file
    for kind in ('receipts', 'google-authority'):
        folder = host / 'data' / kind
        if folder.is_symlink():
            raise RuntimeError('SOURCE_LINK_REFUSED')
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('SOURCE_LINK_REFUSED')
            if path.is_file():
                files[kind + '/' + path.relative_to(folder).as_posix()] = path
    return files


def database_inputs(data, manifest, options):
    databases = {'board.sqlite': data / 'board.sqlite'}
    for name in ('board.operator.sqlite', 'real-review.sqlite'):
        if (data / name).is_file():
            databases[name] = data / name
    decisions = Path(manifest['decisions_db_path'])
    decision_name = next((name for name, path in databases.items() if path.resolve() == decisions.resolve()), None)
    if decision_name is None:
        decision_name = 'review-decisions.sqlite'
        databases[decision_name] = decisions
    ota = (options.get('ota_review') or {}).get('review_db')
    if ota and Path(ota).is_file():
        path = Path(ota)
        if path.resolve() not in {p.resolve() for p in databases.values()}:
            databases['ota-review.sqlite'] = path
    sources_path = data / 'ota-sources.json'
    if sources_path.is_file():
        from app import ota_sources
        from app.ota_store import is_store
        sources = ota_sources.read_manifest(sources_path, required=True)
        unified = sources.get('unified_database')
        if unified:
            path = Path(unified)
            if not is_store(path):
                raise RuntimeError('UNIFIED_OTA_BACKUP_INPUT_INVALID')
            databases['ota-evidence.sqlite'] = path
    return databases, decision_name


def main(evidence_out=None):
    host = Path(r"D:\WebLedgerHost")
    data = host / "data"
    config = host / "config/real-review.json"
    inputs = BoundInputs(load_manifest(str(config)))
    manifest = inputs.manifest if hasattr(inputs, "manifest") else load_manifest(str(config))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    bundle = data / "backups" / ("operational-" + stamp)
    restored = data / "restore-verification" / stamp
    bundle.mkdir(parents=True, exist_ok=False)
    restored.mkdir(parents=True, exist_ok=False)
    flow_config = host / 'config/card-flow.json'
    options = json.loads(flow_config.read_text(encoding='utf-8')) if flow_config.is_file() else {}
    databases, decision_name = database_inputs(data, manifest, options)
    before = {name: database_state(path) for name, path in databases.items()}
    for name, path in databases.items():
        backup_database(path, bundle / "databases" / name)
    files = {"config/real-review-original.json": config}
    if (data / 'ota-sources.json').is_file():
        files['data/ota-sources.json'] = data / 'ota-sources.json'
    for kind in ("snapshot", "review", "master"):
        files["review/" + Path(manifest[kind + "_path"]).name] = Path(manifest[kind + "_path"])
    # Optional product stores are as important as SQLite: photos, receipt edits,
    # selected Google generations and launch settings must survive a restore.
    files.update(product_files(host))
    for kind in ("source", "evidence", "exports"):
        if (data / kind).is_symlink():
            raise RuntimeError('SOURCE_LINK_REFUSED')
        for path in sorted((data / kind).rglob("*")):
            if path.is_file():
                if path.is_symlink():
                    raise RuntimeError("SOURCE_LINK_REFUSED")
                files[kind + "/" + path.relative_to(data / kind).as_posix()] = path
    hashes = {name: digest_file(path) for name, path in files.items()}
    for name, path in files.items():
        dest = bundle / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        if digest_file(dest) != hashes[name]:
            raise RuntimeError("BACKUP_FILE_MISMATCH")
    after = {name: database_state(path) for name, path in databases.items()}
    if before != after or hashes != {name: digest_file(path) for name, path in files.items()}:
        raise RuntimeError("LIVE_INPUT_CHANGED_DURING_BACKUP")
    for name in databases:
        path = bundle / "databases" / name
        if database_state(path) != before[name]:
            raise RuntimeError("BACKUP_DATABASE_STATE_MISMATCH")
        dest = restored / "databases" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        if database_state(dest) != before[name]:
            raise RuntimeError("RESTORED_DATABASE_STATE_MISMATCH")
    for name in files:
        dest = restored / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / name, dest)
        if digest_file(dest) != hashes[name]:
            raise RuntimeError("RESTORED_FILE_MISMATCH")
    relocated = dict(manifest)
    for kind in ("snapshot", "review", "master"):
        relocated[kind + "_path"] = str(restored / "review" / Path(manifest[kind + "_path"]).name)
    relocated["decisions_db_path"] = str(restored / 'databases' / decision_name)
    relocated_path = restored / "config/real-review.json"
    relocated_path.write_text(json.dumps(relocated, indent=2) + "\n", encoding="utf-8")
    if BoundInputs(load_manifest(str(relocated_path))).binding != inputs.binding:
        raise RuntimeError("RESTORED_REVIEW_BINDING_MISMATCH")
    protected_manifest = {"binding": inputs.binding, "files": hashes, "databases": before}
    (bundle / "manifest.json").write_text(json.dumps(protected_manifest, indent=2) + "\n", encoding="utf-8")
    result = {
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "backup_directory": str(bundle), "restored_directory": str(restored),
        "database_count": len(databases), "file_count": len(files),
        "all_database_tables_and_columns_compared": True,
        "source_files_hash_compared": True,
        "live_state_unchanged": before == after,
        "restored_review_binding_equal": True,
        "board_rows": before["board.sqlite"]["board_rows"]["rows"],
        "board_requests": before["board.sqlite"]["board_requests"]["rows"],
        "actual_request_replay_executed": False,
        "secrets_copied": False,
        "restored_server_started": False,
        "actual_import_performed": False,
    }
    output = Path(evidence_out) if evidence_out else ROOT / "docs/handoff/2026-10-01/operational-backup-restore-evidence.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-out', type=Path, help='Store aggregate evidence outside the checkout')
    args = parser.parse_args()
    try:
        main(args.evidence_out)
    except Exception:
        print("OPERATIONAL_BACKUP_RESTORE_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
