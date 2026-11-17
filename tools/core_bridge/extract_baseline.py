"""Capture and verify a reproducible Python OTA extractor baseline.

Customer text stays in a fresh ``<host>/data/backups`` capture directory. Both
live and copied SQLite sources are read through SQLite's read-only backup API;
the original source is never written. A manifest is atomically published last,
so an interrupted capture has no completion marker.

``compare`` classifies the difference between two protected baseline outputs
(SPEC §11.1 M3-3): extraction-content differences are separated from
source-identity differences, and the result carries counts only. The detailed
report is customer text and is written only under the protected backups folder.
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
COMPARE_SCHEMA = "extractor-baseline-compare-v1"
_DEPENDENCY_ROOTS = (
    "tools.core_bridge.extract_baseline",
    "tools.core_bridge.ota_input",
    "tools.core_bridge.commands",
    "app.ota_sources",
    "app.ota_payments",
)
# Fields that name or derive the provenance of an event rather than the extracted
# payment/booking facts. SPEC §11.1 M3-3 requires the two difference classes apart.
SOURCE_IDENTITY_FIELDS = frozenset({
    "ota_event_id", "payment_event_id",
    "source_ids", "identity_source_ids", "source_digest", "source_digests",
    "source_binding_ids", "source_lineage_ids", "observation_ids",
    "source_inventory", "evidence_kind",
    "booking_context_source_ids", "booking_context_source_digests",
    "payment_source_digest", "verified_portal_snapshot",
    "_mail_reservation_provenance", "_portal_reservation_provenance",
    "reservation_identity_attestation",
})


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
    _feed_atom(digest, "sqlite-logical-row-multiset-v1")
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
            _feed_atom(digest, "rows")
            _feed_atom(digest, table)
            # Sorting full mail/portal bodies in SQLite spills large text to
            # disk and repeatedly compares common prefixes. Hash each typed
            # row once, then sort fixed-size digests. Preserve duplicate rows.
            rows = []
            for row in cursor:
                row_digest = hashlib.sha256()
                for value in row:
                    _feed_atom(row_digest, value)
                rows.append(row_digest.digest())
            for row_digest in sorted(rows):
                digest.update(row_digest)
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


def _hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _validated_manifest(raw):
    """Validate the manifest envelope, digest formats, dependency description shape
    and internal consistency.

    Shared by capture verification and compare. Binding artifacts to the current
    checkout (snapshot re-hash, module files, producer equality) stays with
    verify_capture, so compare can bind captures from other producer versions.
    A self-consistent checksum alone never makes a manifest valid: the bundle
    digest must equal the canonical aggregate of the dependency list, and the
    source hash must equal the extractor entry's hash.
    """
    if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "captured_at_utc", "input", "producer", "output", "sources",
            "manifest_sha256"}:
        raise ValueError
    supplied = raw.pop("manifest_sha256")
    if not _hex64(supplied) or supplied != hashlib.sha256(_json_bytes(raw)).hexdigest():
        raise ValueError
    raw["manifest_sha256"] = supplied
    if raw["schema_version"] != MANIFEST_SCHEMA or not isinstance(raw["captured_at_utc"], str):
        raise ValueError
    input_info = raw["input"]
    if not isinstance(input_info, dict) or set(input_info) != {
            "path", "sha256", "size_bytes", "sqlite_logical_fingerprint"}:
        raise ValueError
    if (not isinstance(input_info["path"], str) or not _hex64(input_info["sha256"]) or
            not _hex64(input_info["sqlite_logical_fingerprint"]) or
            type(input_info["size_bytes"]) is not int or input_info["size_bytes"] < 0):
        raise ValueError
    output_info = raw["output"]
    if not isinstance(output_info, dict) or set(output_info) != {
            "path_from_backups", "sha256", "size_bytes", "event_count", "format"}:
        raise ValueError
    if (not isinstance(output_info["path_from_backups"], str) or not _hex64(output_info["sha256"]) or
            output_info["format"] != OUTPUT_FORMAT or
            type(output_info["event_count"]) is not int or output_info["event_count"] < 0 or
            type(output_info["size_bytes"]) is not int or output_info["size_bytes"] < 0):
        raise ValueError
    producer = raw["producer"]
    if not isinstance(producer, dict) or set(producer) != {
            "python_runtime", "python_source_sha256", "production_python_sha256",
            "dependency_modules"}:
        raise ValueError
    if (not isinstance(producer["python_runtime"], str) or
            not _hex64(producer["python_source_sha256"]) or
            not _hex64(producer["production_python_sha256"])):
        raise ValueError
    modules = producer["dependency_modules"]
    if not isinstance(modules, list) or not modules:
        raise ValueError
    for item in modules:
        if (not isinstance(item, dict) or set(item) != {"module", "path", "sha256"} or
                not isinstance(item["module"], str) or not isinstance(item["path"], str) or
                not _hex64(item["sha256"])):
            raise ValueError
    paths = [item["path"] for item in modules]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ValueError
    if producer["production_python_sha256"] != hashlib.sha256(_json_bytes(modules)).hexdigest():
        raise ValueError
    extractor_path = Path(__file__).resolve().relative_to(ROOT.resolve()).as_posix()
    roots = [item for item in modules if item["path"] == extractor_path]
    if len(roots) != 1 or roots[0]["sha256"] != producer["python_source_sha256"]:
        raise ValueError
    if raw["sources"] != {"capture_mode": "sqlite-backup", "external_source_files": False}:
        raise ValueError
    return raw


def verify_capture(manifest_path, *, host_root):
    """Verify manifest integrity and every bound artifact; raise a fixed safe error."""
    try:
        host = Path(host_root)
        backups = host / "data" / "backups"
        manifest_file = Path(manifest_path)
        if (_inside(manifest_file, ROOT) or not _inside(manifest_file, backups) or
                _key(manifest_file) == _key(backups) or manifest_file.is_symlink()):
            raise ValueError
        raw = _validated_manifest(json.loads(manifest_file.read_text(encoding="utf-8")))
        capture_dir = manifest_file.parent
        input_info = raw["input"]
        snapshot = (capture_dir / input_info["path"]).resolve()
        if not _inside(snapshot, backups) or _inside(snapshot, ROOT) or snapshot.is_symlink():
            raise ValueError
        input_hash, input_size = _file_digest(snapshot)
        if input_hash != input_info["sha256"] or input_size != input_info["size_bytes"]:
            raise ValueError
        if sqlite_logical_fingerprint(snapshot) != input_info["sqlite_logical_fingerprint"]:
            raise ValueError
        output_info = raw["output"]
        output = (backups / output_info["path_from_backups"]).resolve()
        if not _inside(output, backups) or _inside(output, ROOT) or output.is_symlink():
            raise ValueError
        output_hash, output_size = _file_digest(output)
        if output_hash != output_info["sha256"] or output_size != output_info["size_bytes"]:
            raise ValueError
        output_value = json.loads(output.read_text(encoding="utf-8"))
        if (not isinstance(output_value, dict) or set(output_value) != {"events"} or
                not isinstance(output_value["events"], list) or
                len(output_value["events"]) != output_info["event_count"]):
            raise ValueError
        producer = raw["producer"]
        modules = producer["dependency_modules"]
        for item in modules:
            if (_module_file(item["module"]) is None or
                    _file_digest(_module_file(item["module"]))[0] != item["sha256"]):
                raise ValueError
        expected_root, expected_bundle, expected_entries = production_module_hashes()
        if (producer["python_source_sha256"] != expected_root or
                producer["production_python_sha256"] != expected_bundle or
                modules != expected_entries):
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


def _content_projection(event):
    return {key: value for key, value in event.items() if key not in SOURCE_IDENTITY_FIELDS}


def _identity_projection(event):
    return {key: value for key, value in event.items() if key in SOURCE_IDENTITY_FIELDS}


def _projection_key(projection):
    from .commands import canonical
    return json.dumps(canonical(projection), ensure_ascii=False, sort_keys=True)


def _text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _business_key(event):
    return (event.get("provider"), event.get("booking_ref"), event.get("event_type"))


def _changed_fields(base, new):
    return sorted({field for field in set(base) | set(new) if base.get(field) != new.get(field)})


def compare_events(base_events, new_events):
    """Classify two event lists into content and source-identity difference classes.

    Events join on their extraction-content projection (a multiset, so duplicate
    content survives). Matched pairs whose identity projections differ are
    source-identity differences; unmatched content is paired once more by the
    business key ``(provider, booking_ref, event_type)`` when unique on both
    sides, and the rest is reported as only-in-base / only-in-new.
    """
    base_groups, new_groups = {}, {}
    for event in base_events:
        base_groups.setdefault(_projection_key(_content_projection(event)), []).append(event)
    for event in new_events:
        new_groups.setdefault(_projection_key(_content_projection(event)), []).append(event)

    identical = 0
    identity_only = []
    identity_field_counts = {}
    only_base, only_new = [], []
    for key in sorted(set(base_groups) | set(new_groups)):
        # Consume exact identity matches first: with duplicate content, a sorted
        # zip would otherwise pair an identical event against a moved one.
        new_by_identity = {}
        for event in new_groups.get(key, []):
            new_by_identity.setdefault(_projection_key(_identity_projection(event)), []).append(event)
        unmatched_base = []
        for event in sorted(base_groups.get(key, []), key=lambda e: _projection_key(_identity_projection(e))):
            bucket = new_by_identity.get(_projection_key(_identity_projection(event)))
            if bucket:
                bucket.pop()
                identical += 1
            else:
                unmatched_base.append(event)
        unmatched_new = [event for bucket in new_by_identity.values() for event in bucket]
        unmatched_base.sort(key=lambda e: _projection_key(_identity_projection(e)))
        unmatched_new.sort(key=lambda e: _projection_key(_identity_projection(e)))
        paired = min(len(unmatched_base), len(unmatched_new))
        for index in range(paired):
            base_identity = _identity_projection(unmatched_base[index])
            new_identity = _identity_projection(unmatched_new[index])
            fields = _changed_fields(base_identity, new_identity)
            for field in fields:
                identity_field_counts[field] = identity_field_counts.get(field, 0) + 1
            identity_only.append({"content_sha256": _text_digest(key), "fields": fields,
                                  "base_identity": base_identity, "new_identity": new_identity})
        only_base.extend(unmatched_base[paired:])
        only_new.extend(unmatched_new[paired:])

    base_by_key, new_by_key = {}, {}
    for event in only_base:
        base_by_key.setdefault(_business_key(event), []).append(event)
    for event in only_new:
        new_by_key.setdefault(_business_key(event), []).append(event)
    content_changed = []
    content_field_counts = {}
    matched_base, matched_new = set(), set()
    for business_key in sorted(set(base_by_key) & set(new_by_key),
                               key=lambda k: json.dumps(k, ensure_ascii=False)):
        base_list, new_list = base_by_key[business_key], new_by_key[business_key]
        if len(base_list) != 1 or len(new_list) != 1:
            continue
        base_event, new_event = base_list[0], new_list[0]
        fields = _changed_fields(_content_projection(base_event), _content_projection(new_event))
        for field in fields:
            content_field_counts[field] = content_field_counts.get(field, 0) + 1
        content_changed.append({
            "business_key": list(business_key), "fields": fields,
            "base_content_sha256": _text_digest(_projection_key(_content_projection(base_event))),
            "new_content_sha256": _text_digest(_projection_key(_content_projection(new_event))),
        })
        matched_base.add(id(base_event))
        matched_new.add(id(new_event))
    only_base = [event for event in only_base if id(event) not in matched_base]
    only_new = [event for event in only_new if id(event) not in matched_new]

    def unmatched(event):
        return {"business_key": list(_business_key(event)),
                "content_sha256": _text_digest(_projection_key(_content_projection(event)))}

    return {
        "identical": identical,
        "source_identity_only": len(identity_only),
        "content_changed": len(content_changed),
        "only_in_base": len(only_base),
        "only_in_new": len(only_new),
        "identity_field_diff_counts": dict(sorted(identity_field_counts.items())),
        "content_field_diff_counts": dict(sorted(content_field_counts.items())),
        "details": {
            "source_identity_only": sorted(identity_only, key=lambda d: d["content_sha256"]),
            "content_changed": content_changed,
            "only_in_base": sorted((unmatched(e) for e in only_base), key=lambda d: d["content_sha256"]),
            "only_in_new": sorted((unmatched(e) for e in only_new), key=lambda d: d["content_sha256"]),
        },
    }


def _compare_binding(manifest_path, side, backups, error):
    manifest_file = Path(manifest_path)
    if (_inside(manifest_file, ROOT) or not _inside(manifest_file, backups) or
            _key(manifest_file) == _key(backups) or manifest_file.is_symlink() or not manifest_file.is_file()):
        raise error("MANIFEST_NOT_PROTECTED", side)
    try:
        manifest = _validated_manifest(json.loads(manifest_file.read_text(encoding="utf-8")))
    except Exception:
        raise error("MANIFEST_INVALID", side) from None
    return {"manifest_path": str(manifest_file), "manifest": manifest}


def compare(request, error):
    """Compare two protected baseline outputs; return counts and write the protected detail report."""
    for key in ("base", "new", "out"):
        if not request.get(key):
            raise error(f"{key.upper()}_REQUIRED")
    host = request.get("host_root") or DEFAULT_HOST
    backups = Path(host) / "data" / "backups"
    paths = {}
    for key in ("base", "new", "out"):
        path = Path(request[key])
        if _inside(path, ROOT):
            raise error("PATH_INSIDE_REPO", key)
        if not _inside(path, backups) or _key(path) == _key(backups) or path.is_symlink():
            raise error("PATH_NOT_PROTECTED", key)
        paths[key] = path
    for key in ("base", "new"):
        if not paths[key].is_file():
            raise error("FILE_NOT_FOUND", key)
    if paths["out"].exists():
        raise error("OUT_EXISTS")

    bindings = {}
    for side in ("base", "new"):
        manifest_path = request.get(f"{side}_manifest")
        bindings[side] = _compare_binding(manifest_path, side, backups, error) if manifest_path else None

    events, digests = {}, {}
    for side in ("base", "new"):
        try:
            value = json.loads(paths[side].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise error("FORMAT_INVALID", side) from None
        if (not isinstance(value, dict) or set(value) != {"events"} or
                not isinstance(value["events"], list) or
                any(not isinstance(event, dict) for event in value["events"])):
            raise error("FORMAT_INVALID", side)
        events[side] = value["events"]
        digests[side] = _file_digest(paths[side])
        if bindings[side]:
            declared = bindings[side]["manifest"]["output"]
            if (declared["sha256"] != digests[side][0] or
                    declared["size_bytes"] != digests[side][1] or
                    declared["event_count"] != len(events[side])):
                raise error("OUTPUT_MANIFEST_MISMATCH", side)

    classification = compare_events(events["base"], events["new"])

    def binding_facts(side):
        if not bindings[side]:
            return None
        manifest = bindings[side]["manifest"]
        return {
            "manifest_sha256": manifest["manifest_sha256"],
            "input_sha256": manifest["input"]["sha256"],
            "sqlite_logical_fingerprint": manifest["input"]["sqlite_logical_fingerprint"],
            "production_python_sha256": manifest["producer"]["production_python_sha256"],
            "python_source_sha256": manifest["producer"]["python_source_sha256"],
            "python_runtime": manifest["producer"]["python_runtime"],
            "event_count": manifest["output"]["event_count"],
        }

    base_binding, new_binding = binding_facts("base"), binding_facts("new")
    same_input = same_code = None
    if base_binding and new_binding:
        same_input = base_binding["sqlite_logical_fingerprint"] == new_binding["sqlite_logical_fingerprint"]
        same_code = base_binding["production_python_sha256"] == new_binding["production_python_sha256"]
    body = {
        "schema_version": COMPARE_SCHEMA,
        "compared_at_utc": _utc_now(),
        "base": {"path": str(paths["base"]), "sha256": digests["base"][0], "size_bytes": digests["base"][1],
                 "event_count": len(events["base"]), "binding": base_binding},
        "new": {"path": str(paths["new"]), "sha256": digests["new"][0], "size_bytes": digests["new"][1],
                "event_count": len(events["new"]), "binding": new_binding},
        "same_input_fingerprint": same_input,
        "same_production_code": same_code,
        "classification": classification,
    }
    body["report_sha256"] = hashlib.sha256(_json_bytes(body)).hexdigest()
    paths["out"].parent.mkdir(parents=True, exist_ok=True)
    with open(paths["out"], "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    _readonly(paths["out"])
    return {
        "base_events": len(events["base"]),
        "new_events": len(events["new"]),
        "identical": classification["identical"],
        "source_identity_only": classification["source_identity_only"],
        "content_changed": classification["content_changed"],
        "only_in_base": classification["only_in_base"],
        "only_in_new": classification["only_in_new"],
        "same_input_fingerprint": same_input,
        "same_production_code": same_code,
        "report_sha256": body["report_sha256"],
    }
