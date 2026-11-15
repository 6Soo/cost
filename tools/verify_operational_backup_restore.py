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
        # Gateway telemetry is regenerated every few seconds, not restore input.
        if config_file.name == 'ledger-gateway-status.json':
            continue
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
    # 기능을 나중에 꺼도 기존 사용자 연결과 이력은 계속 복구 대상이다.
    passenger_db = data / 'flight-passenger.sqlite'
    if passenger_db.is_file():
        databases['flight-passenger.sqlite'] = passenger_db
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


SCOPE_ALIASES = {'board': ['board.sqlite']}
OUT_OF_SCOPE_FOLDERS = ('source', 'evidence', 'exports')


def core_database(data, databases):
    """Add core.sqlite when it exists; the default inputs predate the core store."""
    if (data / 'core.sqlite').is_file():
        databases.setdefault('core.sqlite', data / 'core.sqlite')
    return databases


def backup_covers(saved, host, database_names):
    """Whether backup evidence verified these databases (and core.sqlite when the host has one)."""
    needed = list(database_names)
    if (Path(host) / 'data/core.sqlite').is_file():
        needed.append('core.sqlite')
    if saved.get('backup_scope_kind') == 'scoped':
        return (saved.get('out_of_scope_unchanged') is True
                and all(name in saved.get('backup_scope', ()) for name in needed))
    if saved.get('all_database_tables_and_columns_compared') is not True:
        return False
    if 'backup_scope' not in saved:
        return 'core.sqlite' not in needed
    return all(name in saved['backup_scope'] for name in needed)


def resolve_scope(databases, data, names):
    """Pick the databases this window writes. `board` means board.sqlite; core.sqlite may be named too."""
    wanted = []
    for name in names:
        wanted.extend(SCOPE_ALIASES.get(name, [name]))
    candidates = core_database(data, dict(databases))
    if not wanted or any(name not in candidates for name in wanted):
        raise RuntimeError('BACKUP_SCOPE_UNKNOWN_DATABASE')
    # The Rust writer changes core.sqlite and period-facts.json; a window that has one must back it up.
    if 'core.sqlite' in candidates and 'core.sqlite' not in wanted:
        raise RuntimeError('BACKUP_SCOPE_MISSING_CORE_DB')
    inside = {name: candidates[name] for name in candidates if name in wanted}
    outside = {name: path for name, path in databases.items() if name not in inside}
    return inside, outside


def database_fingerprint(path):
    """File-level hash of a database and its WAL; no row serialization. Any committed write changes it."""
    path = Path(path)
    result = {}
    for suffix in ('', '-wal'):
        part = Path(str(path) + suffix)
        if part.is_file():
            digest = hashlib.sha256()
            with part.open('rb') as handle:
                for block in iter(lambda: handle.read(1 << 20), b''):
                    digest.update(block)
            result[part.name] = [part.stat().st_size, digest.hexdigest()]
    return result


def folder_fingerprint(folder):
    """Relative path, size and mtime of every file; enough to detect a write without reading content."""
    folder = Path(folder)
    if folder.is_symlink():
        raise RuntimeError('SOURCE_LINK_REFUSED')
    result = {}
    if folder.is_dir():
        for path in sorted(folder.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('SOURCE_LINK_REFUSED')
            if path.is_file():
                stat = path.stat()
                result[path.relative_to(folder).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    return result


def outside_state(data, outside_databases):
    return {
        'databases': {name: database_fingerprint(path) for name, path in outside_databases.items()},
        'folders': {kind: folder_fingerprint(data / kind) for kind in OUT_OF_SCOPE_FOLDERS},
    }


def main(evidence_out=None, scope=None, host=None):
    host = Path(host) if host else Path(r"D:\WebLedgerHost")
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
    databases = core_database(data, databases)
    outside_before = None
    if scope:
        databases, outside = resolve_scope(databases, data, scope)
        if decision_name not in databases:
            raise RuntimeError('BACKUP_SCOPE_MISSING_DECISIONS_DB')
        outside_before = outside_state(data, outside)
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
    if (data / 'period-facts.json').is_file():
        files['core-facts/period-facts.json'] = data / 'period-facts.json'
    for kind in (() if scope else OUT_OF_SCOPE_FOLDERS):
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
    if scope and outside_state(data, outside) != outside_before:
        raise RuntimeError("OUT_OF_SCOPE_INPUT_CHANGED_DURING_BACKUP")
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
        "all_database_tables_and_columns_compared": not scope,
        "source_files_hash_compared": not scope,
        "backup_scope_kind": "scoped" if scope else "full",
        "backup_scope": sorted(databases),
        "live_state_unchanged": before == after,
        "restored_review_binding_equal": True,
        "board_rows": before["board.sqlite"]["board_rows"]["rows"] if "board.sqlite" in before else None,
        "board_requests": before["board.sqlite"]["board_requests"]["rows"] if "board.sqlite" in before else None,
        "actual_request_replay_executed": False,
        "secrets_copied": False,
        "restored_server_started": False,
        "actual_import_performed": False,
    }
    if scope:
        result["out_of_scope_databases"] = sorted(outside)
        result["out_of_scope_folders"] = list(OUT_OF_SCOPE_FOLDERS)
        result["out_of_scope_unchanged"] = True
    output = Path(evidence_out) if evidence_out else ROOT / "docs/handoff/2026-10-01/operational-backup-restore-evidence.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-out', type=Path, help='Store aggregate evidence outside the checkout')
    parser.add_argument('--scope', nargs='+', metavar='DB',
                        help='Back up and verify only these databases (e.g. board, or board.sqlite core.sqlite); '
                             'others and source/evidence/exports folders are only checked for being unchanged. Default: everything')
    args = parser.parse_args()
    try:
        main(args.evidence_out, args.scope)
    except Exception:
        print("OPERATIONAL_BACKUP_RESTORE_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
