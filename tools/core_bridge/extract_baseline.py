"""Capture and verify a reproducible Python OTA extractor baseline.

Customer text stays in a fresh ``<host>/data/backups`` capture directory. Both
live and copied SQLite sources are read through SQLite's read-only backup API;
the original source is never written. A manifest is atomically published last,
so an interrupted capture has no completion marker.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sqlite3
import stat
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .ota_input import DEFAULT_HOST, ROOT, _inside, _key, _sources, is_live


MANIFEST_SCHEMA = "extractor-baseline-v1"
OUTPUT_FORMAT = "cost-extractor-events-canonical-json-v1"
_DEPENDENCY_ROOTS = (
    "tools.core_bridge.extract_baseline",
    "tools.core_bridge.ota_input",
    "tools.core_bridge.commands",
    "app.ota_sources",
    "app.ota_payments",
)


def _backup(live, workdir):
    """Create a consistent snapshot through a read-only SQLite source connection."""
    dst = Path(workdir) / "ota-evidence.sqlite"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError("snapshot target exists")
    source_uri = Path(live).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as src:
        src.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(str(dst))) as dst_conn:
            src.backup(dst_conn)
    return dst


def write_baseline(out, events):
    """Write the unchanged canonical output format, refusing to overwrite it."""
    from .commands import canonical
    text = json.dumps(canonical({"events": events}), ensure_ascii=False, sort_keys=True)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return {"events": len(events), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _feed_atom(digest, value):
    if value is None:
        payload = b"N"
    elif type(value) is int:
        payload = b"I" + str(value).encode("ascii")
    elif type(value) is float:
        payload = b"F" + value.hex().encode("ascii")
    elif isinstance(value, str):
        payload = b"T" + value.encode("utf-8", "surrogatepass")
    elif isinstance(value, (bytes, bytearray, memoryview)):
        payload = b"B" + bytes(value)
    else:
        raise TypeError("unsupported SQLite value")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def sqlite_logical_fingerprint(path):
    """Hash SQLite schema and typed row values independently of page layout."""
    digest = hashlib.sha256()
    target = Path(path).resolve()
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        schema = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE type IN ('table','index','trigger','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
        tables = []
        for row in schema:
            for value in row:
                _feed_atom(digest, value)
            if row[0] == "table":
                tables.append(row[1])
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            cursor = conn.execute(f"SELECT * FROM {quoted}")
            columns = len(cursor.description or ())
            if columns:
                order = ", ".join(str(index) for index in range(1, columns + 1))
                cursor = conn.execute(f"SELECT * FROM {quoted} ORDER BY {order}")
            _feed_atom(digest, "rows")
            _feed_atom(digest, table)
            for row in cursor:
                _feed_atom(digest, "row")
                for value in row:
                    _feed_atom(digest, value)
            _feed_atom(digest, "table-end")
    return digest.hexdigest()


def _file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _module_file(module_name):
    parts = module_name.split(".")
    if not parts or parts[0] not in {"app", "tools"}:
        return None
    base = ROOT.joinpath(*parts)
    candidates = (base.with_suffix(".py"), base / "__init__.py")
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(ROOT.resolve())
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return candidate
    return None


def _import_names(module_name, module_path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    package = module_name if module_path.name == "__init__.py" else module_name.rpartition(".")[0]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package)
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call):
            function = node.func
            is_import_module = (isinstance(function, ast.Attribute) and function.attr == "import_module")
            is_dunder_import = isinstance(function, ast.Name) and function.id == "__import__"
            if (is_import_module or is_dunder_import) and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    names.add(node.args[0].value)
    return names


def production_module_hashes():
    """Return hashes for the local Python import closure of the production path."""
    pending = list(_DEPENDENCY_ROOTS)
    found = {}
    while pending:
        name = pending.pop()
        path = _module_file(name)
        if path is None:
            continue
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        if relative in found:
            continue
        digest, _size = _file_digest(path)
        found[relative] = {"module": name, "path": relative, "sha256": digest}
        pending.extend(_import_names(name, path))
    entries = [found[key] for key in sorted(found)]
    aggregate = hashlib.sha256(_json_bytes(entries)).hexdigest()
    root = next(item for item in entries if item["path"] == Path(__file__).resolve().relative_to(ROOT.resolve()).as_posix())
    return root["sha256"], aggregate, entries


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _exclusive_manifest(path, payload):
    """Publish a complete manifest in one filesystem operation without overwrite."""
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "xb", buffering=0) as handle:
            handle.write(payload)
            os.fsync(handle.fileno())
        os.link(temporary, path)
        temporary.unlink()
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _readonly(path):
    try:
        Path(path).chmod(stat.S_IREAD)
    except OSError:
        # Protection comes from the designated backups root and exclusive creation;
        # read-only attributes are an additional convenience on supported filesystems.
        pass


def _build_manifest(capture_dir, backups, out, snapshot, output_result, input_hash,
                    input_size, logical_fingerprint, producer_before, producer_after):
    if producer_before != producer_after:
        raise RuntimeError("PRODUCTION_CODE_CHANGED")
    root_sha, production_sha, modules = producer_after
    output_hash, output_size = _file_digest(out)
    if output_hash != output_result["sha256"]:
        raise RuntimeError("OUTPUT_HASH_MISMATCH")
    relative_output = Path(os.path.relpath(Path(out).resolve(), Path(backups).resolve())).as_posix()
    body = {
        "schema_version": MANIFEST_SCHEMA,
        "captured_at_utc": _utc_now(),
        "input": {
            "path": "inputs/ota-evidence.sqlite",
            "sha256": input_hash,
            "size_bytes": input_size,
            "sqlite_logical_fingerprint": logical_fingerprint,
        },
        "producer": {
            "python_runtime": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_source_sha256": root_sha,
            "production_python_sha256": production_sha,
            "dependency_modules": modules,
        },
        "output": {
            "path_from_backups": relative_output,
            "sha256": output_hash,
            "size_bytes": output_size,
            "event_count": output_result["events"],
            "format": OUTPUT_FORMAT,
        },
        "sources": {"capture_mode": "sqlite-backup", "external_source_files": False},
    }
    body["manifest_sha256"] = hashlib.sha256(_json_bytes(body)).hexdigest()
    return body


def verify_capture(manifest_path, *, host_root):
    """Verify manifest integrity and every bound artifact; raise a fixed safe error."""
    try:
        host = Path(host_root)
        backups = host / "data" / "backups"
        manifest_file = Path(manifest_path)
        if (_inside(manifest_file, ROOT) or not _inside(manifest_file, backups) or
                _key(manifest_file) == _key(backups) or manifest_file.is_symlink()):
            raise ValueError
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
                "schema_version", "captured_at_utc", "input", "producer", "output", "sources",
                "manifest_sha256"}:
            raise ValueError
        supplied_digest = raw.pop("manifest_sha256")
        if supplied_digest != hashlib.sha256(_json_bytes(raw)).hexdigest():
            raise ValueError
        raw["manifest_sha256"] = supplied_digest
        if raw["schema_version"] != MANIFEST_SCHEMA:
            raise ValueError
        capture_dir = manifest_file.parent
        input_info = raw["input"]
        if set(input_info) != {"path", "sha256", "size_bytes", "sqlite_logical_fingerprint"}:
            raise ValueError
        snapshot = (capture_dir / input_info["path"]).resolve()
        if not _inside(snapshot, backups) or _inside(snapshot, ROOT) or snapshot.is_symlink():
            raise ValueError
        input_hash, input_size = _file_digest(snapshot)
        if input_hash != input_info["sha256"] or input_size != input_info["size_bytes"]:
            raise ValueError
        if sqlite_logical_fingerprint(snapshot) != input_info["sqlite_logical_fingerprint"]:
            raise ValueError
        output_info = raw["output"]
        if set(output_info) != {"path_from_backups", "sha256", "size_bytes", "event_count", "format"}:
            raise ValueError
        output = (backups / output_info["path_from_backups"]).resolve()
        if not _inside(output, backups) or _inside(output, ROOT) or output.is_symlink():
            raise ValueError
        output_hash, output_size = _file_digest(output)
        if (output_hash != output_info["sha256"] or output_size != output_info["size_bytes"] or
                output_info["format"] != OUTPUT_FORMAT or type(output_info["event_count"]) is not int or
                output_info["event_count"] < 0):
            raise ValueError
        output_value = json.loads(output.read_text(encoding="utf-8"))
        if (not isinstance(output_value, dict) or set(output_value) != {"events"} or
                not isinstance(output_value["events"], list) or
                len(output_value["events"]) != output_info["event_count"]):
            raise ValueError
        producer = raw["producer"]
        if set(producer) != {"python_runtime", "python_source_sha256", "production_python_sha256",
                             "dependency_modules"}:
            raise ValueError
        modules = producer["dependency_modules"]
        if not isinstance(modules, list) or not modules:
            raise ValueError
        for item in modules:
            if (not isinstance(item, dict) or set(item) != {"module", "path", "sha256"} or
                    _module_file(item["module"]) is None or
                    _file_digest(_module_file(item["module"]))[0] != item["sha256"]):
                raise ValueError
        expected_root, expected_bundle, expected_entries = production_module_hashes()
        if (producer["python_source_sha256"] != expected_root or
                producer["production_python_sha256"] != expected_bundle or
                modules != expected_entries):
            raise ValueError
        if raw["sources"] != {"capture_mode": "sqlite-backup", "external_source_files": False}:
            raise ValueError
        return {"ok": True, "manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
                "events": output_info["event_count"]}
    except Exception:
        raise ValueError("CAPTURE_INVALID") from None


def capture(request, error):
    """Write the protected extractor output, snapshot, and one verifiable manifest."""
    for key in ("ota_evidence", "out"):
        if not request.get(key):
            raise error(f"{key.upper()}_REQUIRED")
    host = request.get("host_root") or DEFAULT_HOST
    out = Path(request["out"])
    data = Path(host) / "data"
    backups = data / "backups"
    if _inside(out, ROOT):
        raise error("OUT_INSIDE_REPO")
    if not _inside(out, backups) or _key(out) == _key(backups):
        raise error("OUT_NOT_PROTECTED")
    if out.exists():
        raise error("OUT_EXISTS")
    evidence = Path(request["ota_evidence"])
    if not evidence.is_file():
        raise error("DB_NOT_FOUND", "ota_evidence")

    backups.mkdir(parents=True, exist_ok=True)
    capture_root = backups / "extractor-baseline-captures"
    capture_root.mkdir(parents=True, exist_ok=True)
    capture_dir = capture_root / uuid.uuid4().hex
    capture_dir.mkdir(exist_ok=False)
    input_dir = capture_dir / "inputs"
    input_dir.mkdir(exist_ok=False)
    snapshot = _backup(evidence, input_dir)
    input_hash, input_size = _file_digest(snapshot)
    logical_fingerprint = sqlite_logical_fingerprint(snapshot)

    producer_before = production_module_hashes()
    # The source registry is explicitly bound to this snapshot. It cannot discover
    # neighboring customer files, and the event builder receives only this DB.
    with tempfile.TemporaryDirectory(prefix="extract-baseline-work-", dir=str(backups)) as work:
        sources = _sources(snapshot, work)
        from app import ota_payments
        events = ota_payments.build_ota_payment_events(sources)
    output_result = write_baseline(out, events)
    producer_after = production_module_hashes()
    manifest = _build_manifest(capture_dir, backups, out, snapshot, output_result, input_hash,
                               input_size, logical_fingerprint, producer_before, producer_after)
    manifest_path = capture_dir / "manifest.json"
    _exclusive_manifest(manifest_path, _json_bytes(manifest))
    _readonly(snapshot)
    _readonly(manifest_path)
    _readonly(out)
    manifest_sha, _manifest_size = _file_digest(manifest_path)
    return {
        **output_result,
        "manifest_sha256": manifest_sha,
        "manifest_path": str(manifest_path),
    }
