"""Read-only, aggregate-only diagnostics for a versioned pipeline inventory."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sqlite3
import sys
from typing import Any

SCHEMA_VERSION = 1
KINDS = {"current", "candidate", "legacy", "external"}
ARTIFACT_KINDS = {"sqlite", "json", "file"}
POSTING_COLUMNS = {"posting_eligible", "authoritative_posting", "external_posting"}
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class InventoryError(Exception):
    def __init__(self, code: str) -> None: super().__init__(code); self.code = code


def _finding(code: str, severity: str, stage: str | None = None, path: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "severity": severity}
    if stage is not None: item["stage_id"] = stage
    if path is not None: item["path"] = path
    return item


def _keys(obj: dict[str, Any], required: set[str], optional: set[str]) -> None:
    if set(obj) - required - optional or required - set(obj): raise InventoryError("INVENTORY_SCHEMA_INVALID")


def _json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result: raise InventoryError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise InventoryError("JSON_CONSTANT_INVALID")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_json_no_duplicates, parse_constant=_reject_constant)


def _safe_path(root: Path, raw: Any, allow_glob: bool = False) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise InventoryError("INVENTORY_PATH_INVALID")
    windows, posix = PureWindowsPath(raw), PurePosixPath(raw)
    parts = raw.replace("\\", "/").split("/")
    if windows.drive or windows.root or posix.is_absolute() or any(part == ".." for part in parts): raise InventoryError("INVENTORY_PATH_ESCAPE")
    if not allow_glob and any(mark in raw for mark in "*?["): raise InventoryError("INVENTORY_PATH_INVALID")
    candidate = (root / Path(raw)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc: raise InventoryError("INVENTORY_PATH_ESCAPE") from exc
    return candidate


def _expand(root: Path, raw: str, allow_glob: bool = False) -> tuple[Path, list[Path]]:
    base = _safe_path(root, raw, allow_glob)
    if not allow_glob or not any(mark in raw for mark in "*?["): return base, [base]
    try: candidates = list(root.glob(raw))
    except (OSError, RuntimeError, ValueError) as exc: raise InventoryError("INVENTORY_PATH_INVALID") from exc
    resolved: dict[str, Path] = {}
    for candidate in candidates:
        try:
            real = candidate.resolve(strict=True)
            real.relative_to(root)
        except (OSError, ValueError) as exc: raise InventoryError("INVENTORY_PATH_ESCAPE") from exc
        resolved[str(real)] = real
    return base, sorted(resolved.values(), key=str) or [base]


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError: return path.as_posix()


def _read_inventory(root: Path, inventory_path: Path) -> dict[str, Any]:
    try:
        data = _read_json(inventory_path)
    except InventoryError as exc: raise InventoryError("INVENTORY_JSON_INVALID") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise InventoryError("INVENTORY_JSON_INVALID") from exc
    if not isinstance(data, dict): raise InventoryError("INVENTORY_SCHEMA_INVALID")
    _keys(data, {"version", "stages"}, set())
    if (not isinstance(data["version"], int) or isinstance(data["version"], bool) or
            data["version"] != SCHEMA_VERSION):
        raise InventoryError("INVENTORY_VERSION_UNSUPPORTED")
    if not isinstance(data["stages"], list) or not data["stages"]: raise InventoryError("INVENTORY_SCHEMA_INVALID")
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for stage in data["stages"]:
        if not isinstance(stage, dict): raise InventoryError("INVENTORY_SCHEMA_INVALID")
        _keys(stage, {"id", "kind", "entrypoints", "artifacts"}, {"required", "skipped"})
        stage_id, kind = stage["id"], stage["kind"]
        if (not isinstance(stage_id, str) or not stage_id or stage_id in seen or
                not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in stage_id)): raise InventoryError("INVENTORY_STAGE_ID_INVALID")
        if not isinstance(kind, str) or kind not in KINDS: raise InventoryError("INVENTORY_STAGE_KIND_INVALID")
        entrypoints, artifacts = stage["entrypoints"], stage["artifacts"]
        if (not isinstance(entrypoints, list) or not all(isinstance(path, str) and path for path in entrypoints) or
                len(set(entrypoints)) != len(entrypoints) or not isinstance(artifacts, list)): raise InventoryError("INVENTORY_SCHEMA_INVALID")
        required, skipped = stage.get("required", kind != "external"), stage.get("skipped", False)
        if not isinstance(required, bool) or not isinstance(skipped, bool): raise InventoryError("INVENTORY_SCHEMA_INVALID")
        if (kind == "external" and required) or (kind != "external" and skipped): raise InventoryError("INVENTORY_STAGE_FLAGS_INVALID")
        parsed_artifacts: list[dict[str, Any]] = []
        seen_artifacts: set[tuple[str, str]] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict): raise InventoryError("INVENTORY_SCHEMA_INVALID")
            _keys(artifact, {"path", "kind"}, {"audit", "required_tables"})
            path, artifact_kind = artifact["path"], artifact["kind"]
            if not isinstance(path, str) or not path: raise InventoryError("INVENTORY_PATH_INVALID")
            if not isinstance(artifact_kind, str) or artifact_kind not in ARTIFACT_KINDS: raise InventoryError("INVENTORY_ARTIFACT_KIND_INVALID")
            if (path, artifact_kind) in seen_artifacts: raise InventoryError("INVENTORY_DUPLICATE_ARTIFACT")
            seen_artifacts.add((path, artifact_kind))
            tables = artifact.get("required_tables", [])
            if (not isinstance(tables, list) or not all(isinstance(table, str) and table and "\x00" not in table for table in tables) or
                    len(set(tables)) != len(tables)): raise InventoryError("INVENTORY_REQUIRED_TABLES_INVALID")
            if "audit" in artifact and (not isinstance(artifact["audit"], str) or not artifact["audit"]): raise InventoryError("INVENTORY_SCHEMA_INVALID")
            parsed_artifacts.append(dict(artifact))
        seen.add(stage_id)
        parsed.append({"id": stage_id, "kind": kind, "entrypoints": entrypoints, "artifacts": parsed_artifacts,
                       "required": required, "skipped": skipped})
    return {"version": SCHEMA_VERSION, "stages": parsed}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_file(path: Path) -> bool:
    return path.is_file() and not path.is_dir()


def _sidecar_signature(path: Path) -> tuple[Any, ...] | None:
    try:
        stat = os.lstat(path)
        return (stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)
    except FileNotFoundError:
        return None
    except OSError:
        return ("lstat_error",)


def _snapshot(paths: set[Path]) -> dict[Path, Any]:
    result: dict[Path, Any] = {}
    for path in paths:
        try:
            result[path] = (_sidecar_signature(path) if path.name.endswith(("-wal", "-shm", "-journal"))
                            else sha256_file(path) if _is_file(path) else None)
        except OSError: result[path] = None
    return result


def _nonzero(value: Any) -> bool:
    if value is None: return False
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value != 0 or (isinstance(value, float) and math.isnan(value))
    text = str(value).strip().lower()
    if text in {"", "0", "0.0", "false", "no", "off", "null", "none"}: return False
    try:
        return float(text) != 0
    except ValueError:
        return True


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _tables(conn: sqlite3.Connection) -> dict[str, str]:
    return {str(row[0]).lower(): str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {str(row[1]).lower(): str(row[1]) for row in conn.execute(f"PRAGMA table_info({_ident(table)})")}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {_ident(table)}").fetchone()[0])


def _sum(conn: sqlite3.Connection, table: str, column: str) -> int | float | None:
    value = conn.execute(f"SELECT SUM({_ident(column)}) FROM {_ident(table)}").fetchone()[0]
    return value if not isinstance(value, float) or math.isfinite(value) else None


def _signed_amounts(conn: sqlite3.Connection, table: str, column: str) -> tuple[int | float | None, int, int | float]:
    quoted = _ident(column)
    total, negative_count, negative_sum = conn.execute(
        f"SELECT SUM({quoted}), COUNT(CASE WHEN {quoted} < 0 THEN 1 END), "
        f"COALESCE(SUM(CASE WHEN {quoted} < 0 THEN {quoted} ELSE 0 END), 0) FROM {_ident(table)}").fetchone()
    return total, int(negative_count or 0), negative_sum


def _side_amounts(conn: sqlite3.Connection, table: str, side: str, amount: str) -> tuple[int | float, int | float]:
    side_q, amount_q = _ident(side), _ident(amount)
    return conn.execute(
        f"SELECT COALESCE(SUM(CASE WHEN LOWER(CAST({side_q} AS TEXT)) = 'debit' THEN {amount_q} ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN LOWER(CAST({side_q} AS TEXT)) = 'credit' THEN {amount_q} ELSE 0 END), 0) "
        f"FROM {_ident(table)}").fetchone()


def _sqlite_sidecars(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")]


def _shadow_role(table_key: str) -> str | None:
    if "shadow" not in table_key:
        return None
    if table_key.endswith(("_batches", "_batch")):
        return "batches"
    if table_key.endswith(("_lines", "_line")):
        return "lines"
    return None


def _amount_column(columns: dict[str, str], names: tuple[str, ...]) -> str | None:
    return next((columns[name] for name in names if name in columns), None)


def _sqlite_stats(path: Path, required_tables: list[str], candidate: bool,
                  stage_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    stats: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    conn: sqlite3.Connection | None = None
    try:
        if any(os.path.lexists(sidecar) for sidecar in _sqlite_sidecars(path)):
            findings.append(_finding("SQLITE_UNSEALED", "warning", stage_id))
            return stats, findings, False
        conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.execute("PRAGMA query_only=ON")
        quick = conn.execute("PRAGMA quick_check").fetchone()
        if not quick or str(quick[0]).lower() != "ok":
            findings.append(_finding("SQLITE_QUICK_CHECK_FAILED", "error", stage_id)); return stats, findings, True
        tables = _tables(conn)
        missing = [table for table in required_tables if table.lower() not in tables]
        findings.extend(_finding("REQUIRED_TABLE_MISSING", "error", stage_id) for _ in missing)
        if "payment_transactions" in tables:
            table, columns = tables["payment_transactions"], _columns(conn, tables["payment_transactions"])
            result: dict[str, Any] = {"count": _count(conn, table)}
            amount = columns.get("amount_krw")
            if amount:
                result["sum_amount_krw"] = _sum(conn, table, amount)
            else: findings.append(_finding("AGGREGATE_COLUMN_MISSING", "warning", stage_id))
            stats["payment_transactions"] = result
        if "draft_rows" in tables:
            table, columns = tables["draft_rows"], _columns(conn, tables["draft_rows"])
            result = {"count": _count(conn, table)}
            payment_id, status = columns.get("payment_id"), columns.get("target_match_status") or columns.get("status")
            if payment_id:
                result["distinct_payment_id"] = int(conn.execute(
                    f"SELECT COUNT(DISTINCT {_ident(payment_id)}) FROM {_ident(table)}").fetchone()[0])
                duplicate_count = int(conn.execute(
                    f"SELECT COUNT(*) FROM (SELECT {_ident(payment_id)} FROM {_ident(table)} "
                    f"WHERE {_ident(payment_id)} IS NOT NULL GROUP BY {_ident(payment_id)} HAVING COUNT(*) > 1)").fetchone()[0])
                if duplicate_count: findings.append(_finding("DRAFT_PAYMENT_ID_DUPLICATE", "error", stage_id))
            else: findings.append(_finding("AGGREGATE_COLUMN_MISSING", "warning", stage_id))
            if status:
                result["status_counts"] = {"<null>" if value is None else str(value): int(count)
                    for value, count in conn.execute(f"SELECT {_ident(status)}, COUNT(*) FROM {_ident(table)} "
                                                     f"GROUP BY {_ident(status)}")}
            else: findings.append(_finding("AGGREGATE_COLUMN_MISSING", "warning", stage_id))
            amount = columns.get("amount_krw")
            if amount:
                total, negative_count, negative_sum = _signed_amounts(conn, table, amount)
                result.update(sum_amount_krw=total, negative_count=negative_count, negative_sum_krw=negative_sum)
            else: findings.append(_finding("AGGREGATE_COLUMN_MISSING", "warning", stage_id))
            stats["draft_rows"] = result
        shadow: dict[str, dict[str, Any]] = {}
        for table_key, table in tables.items():
            role = _shadow_role(table_key)
            if not role:
                continue
            columns, result = _columns(conn, table), shadow.setdefault(role, {"count": 0})
            result["count"] += _count(conn, table)
            if role != "lines": continue
            side, amount = columns.get("side"), columns.get("amount_krw")
            if side and amount:
                debit_total, credit_total = _side_amounts(conn, table, side, amount)
                result.update(debit_krw=debit_total, credit_krw=credit_total, balance_krw=debit_total - credit_total)
                if debit_total != credit_total: findings.append(_finding("SHADOW_DEBIT_CREDIT_UNBALANCED", "error", stage_id))
            else:
                debit = _amount_column(columns, ("debit_krw", "debit_amount_krw", "debit"))
                credit = _amount_column(columns, ("credit_krw", "credit_amount_krw", "credit"))
                if debit and credit:
                    debit_total, credit_total = _sum(conn, table, debit), _sum(conn, table, credit)
                    result.update(debit_krw=debit_total, credit_krw=credit_total)
                    if debit_total is not None and credit_total is not None:
                        result["balance_krw"] = debit_total - credit_total
                        if debit_total != credit_total: findings.append(_finding("SHADOW_DEBIT_CREDIT_UNBALANCED", "error", stage_id))
            batch = _amount_column(columns, ("batch_id", "batch_key", "journal_batch_id"))
            if batch and int(conn.execute(
                    f"SELECT COUNT(*) FROM (SELECT {_ident(batch)} FROM {_ident(table)} "
                    f"GROUP BY {_ident(batch)} HAVING COUNT(*) <> 2)").fetchone()[0]):
                findings.append(_finding("SHADOW_LINES_PER_BATCH_MISMATCH", "error", stage_id))
        if shadow:
            stats["shadow"] = shadow
        posting_flags: list[dict[str, Any]] = []
        for table_key, table in tables.items():
            for col_key, column in _columns(conn, table).items():
                if col_key not in POSTING_COLUMNS: continue
                count = sum(1 for (value,) in conn.execute(
                    f"SELECT {_ident(column)} FROM {_ident(table)}") if _nonzero(value))
                if count: posting_flags.append({"table": table, "column": column, "count": count})
        if posting_flags:
            stats["posting_flags"] = posting_flags
            if candidate: findings.append(_finding("CANDIDATE_POSTING_FLAG_NONZERO", "error", stage_id))
        error = bool(missing) or any(item["severity"] == "error" for item in findings)
        return stats, findings, error
    except (sqlite3.Error, OSError, ValueError, TypeError):
        findings.append(_finding("SQLITE_INSPECTION_FAILED", "error", stage_id)); return stats, findings, True
    finally:
        if conn is not None:
            try: conn.close()
            except sqlite3.Error: pass


def _audit_digest(root: Path, stage_id: str, db_path: Path, audit_path: Path,
                  before: dict[Path, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result: dict[str, Any] = {"path": _rel(root, audit_path)}
    if not _is_file(audit_path):
        return result, [_finding("AUDIT_MISSING", "warning", stage_id, result["path"])]
    try:
        result["sha256"], data = sha256_file(audit_path), _read_json(audit_path)
    except (InventoryError, OSError, UnicodeError, json.JSONDecodeError):
        return result, [_finding("AUDIT_JSON_INVALID", "error", stage_id, result["path"])]
    if not isinstance(data, dict): return result, [_finding("AUDIT_JSON_NOT_OBJECT", "error", stage_id, result["path"])]
    fields = [(field, data[field]) for field in
              ("database_sha256", "output_database_sha256", "audit_db_sha256") if field in data]
    outputs = data.get("outputs")
    if isinstance(outputs, dict) and "database_sha256" in outputs:
        fields.append(("outputs.database_sha256", outputs["database_sha256"]))
    if not fields: return result, [_finding("AUDIT_DIGEST_MISSING", "warning", stage_id, result["path"])]
    database_hash = before.get(db_path)
    if not database_hash:
        try:
            database_hash = sha256_file(db_path)
        except OSError: return result, [_finding("DATABASE_HASH_UNAVAILABLE", "error", stage_id)]
    findings: list[dict[str, Any]] = []
    for field, value in fields:
        if not isinstance(value, str) or not HEX64.fullmatch(value): findings.append(_finding("AUDIT_DIGEST_INVALID", "error", stage_id, result["path"]))
        elif value.lower() != database_hash.lower(): findings.append(_finding("AUDIT_DATABASE_DIGEST_MISMATCH", "error", stage_id, result["path"]))
    result.update(digest_fields=[field for field, _ in fields], digest_verified=not findings)
    return result, findings


def _prepare(root: Path, stages: list[dict[str, Any]], inventory: Path) -> tuple[list[dict[str, Any]], set[Path], dict[tuple[str, str, str], tuple[Path, ...]]]:
    paths, initial, prepared = {inventory}, {}, []
    for stage in stages:
        item: dict[str, Any] = {**stage, "entry_specs": [], "artifact_specs": []}
        for raw in stage["entrypoints"]:
            _, matches = _expand(root, raw)
            item["entry_specs"].append({"raw": raw, "matches": matches}); paths.update(matches)
            initial[(stage["id"], "entry", raw)] = tuple(matches)
        for artifact in stage["artifacts"]:
            _, matches = _expand(root, artifact["path"], allow_glob=True)
            spec: dict[str, Any] = {**artifact, "matches": matches}
            paths.update(matches)
            if artifact["kind"] == "sqlite":
                spec["sidecars"] = {database: _sqlite_sidecars(database) for database in matches}
                for sidecars in spec["sidecars"].values(): paths.update(sidecars)
            initial[(stage["id"], "artifact", artifact["path"])] = tuple(matches)
            if "audit" in artifact:
                _, audit_matches = _expand(root, artifact["audit"])
                spec["audit_matches"] = audit_matches; paths.update(audit_matches)
                initial[(stage["id"], "audit", artifact["audit"])] = tuple(audit_matches)
            item["artifact_specs"].append(spec)
        prepared.append(item)
    return prepared, paths, initial


def _artifact_report(root: Path, stage: dict[str, Any], artifact: dict[str, Any],
                     before: dict[Path, Any], findings: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    raw, kind, rel = artifact["path"], artifact["kind"], artifact["path"].replace("\\", "/")
    matches = [path for path in artifact["matches"] if _is_file(path)]
    item: dict[str, Any] = {"path": rel, "kind": kind, "exists": bool(matches)}
    if any(mark in raw for mark in "*?["):
        item["matches"] = [_rel(root, path) for path in matches]
    audit_matches = artifact.get("audit_matches", [])
    sidecars = [sidecar for values in artifact.get("sidecars", {}).values() for sidecar in values]
    if sidecars:
        item["sidecars"] = [_rel(root, sidecar) for sidecar in sidecars]
    if audit_matches:
        item["audit"] = {"path": artifact["audit"].replace("\\", "/"), "exists": any(_is_file(path) for path in audit_matches)}
    if not matches:
        return item, not stage["skipped"]
    if len(matches) == 1:
        item["sha256"] = before.get(matches[0])
    else:
        item["sha256"] = {_rel(root, path): before.get(path) for path in matches}
    if stage["kind"] != "external" and kind == "sqlite":
        report_stats: list[dict[str, Any]] = []
        for database in matches:
            stats, errors, _ = _sqlite_stats(database, artifact.get("required_tables", []), stage["kind"] == "candidate", stage["id"])
            findings.extend(errors)
            if stats:
                report_stats.append({"path": _rel(root, database), "stats": stats})
            if audit_matches:
                audit_report, audit_findings = _audit_digest(root, stage["id"], database, audit_matches[0], before)
                item["audit"] = audit_report
                findings.extend(audit_findings)
        if len(report_stats) == 1: item["stats"] = report_stats[0]["stats"]
        elif report_stats: item["stats"] = report_stats
    elif stage["kind"] != "external" and kind == "json":
        for json_path in matches:
            try:
                data = _read_json(json_path)
                if not isinstance(data, (dict, list)): raise ValueError
            except (InventoryError, OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
                findings.append(_finding("JSON_INVALID", "error", stage["id"], rel))
                break
    return item, False


def _stage_report(root: Path, stage: dict[str, Any], before: dict[Path, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []; entrypoints: list[dict[str, Any]] = []
    missing = False
    for entry in stage["entry_specs"]:
        matches = [path for path in entry["matches"] if _is_file(path)]
        item: dict[str, Any] = {"path": entry["raw"].replace("\\", "/"), "exists": bool(matches)}
        if matches:
            item["sha256"] = before.get(matches[0])
        elif not stage["skipped"]:
            missing = True; findings.append(_finding("ENTRYPOINT_MISSING", "warning", stage["id"], item["path"]))
        entrypoints.append(item)
    artifacts: list[dict[str, Any]] = []
    for artifact in stage["artifact_specs"]:
        item, artifact_missing = _artifact_report(root, stage, artifact, before, findings)
        missing = missing or artifact_missing
        if artifact_missing: findings.append(_finding("ARTIFACT_MISSING", "warning", stage["id"], item["path"]))
        artifacts.append(item)
    if stage["kind"] == "external":
        if stage["skipped"]:
            findings.append(_finding("EXTERNAL_STAGE_SKIPPED", "warning", stage["id"])); status = "skipped"
        else:
            findings.append(_finding("EXTERNAL_RUNTIME_UNVERIFIED", "warning", stage["id"])); status = "unverified"
    else:
        errors = any(item["severity"] == "error" for item in findings)
        warnings = any(item["severity"] == "warning" for item in findings)
        status = "blocked" if errors else "missing" if missing else "unverified" if warnings else "ok"
    return {"id": stage["id"], "kind": stage["kind"], "required": stage["required"],
            "skipped": stage["skipped"], "status": status, "entrypoints": entrypoints,
            "artifacts": artifacts, "findings": findings, "_tracked": stage}


def _rescan(root: Path, stages: list[dict[str, Any]], initial: dict[tuple[str, str, str], tuple[Path, ...]],
            paths: set[Path]) -> tuple[set[Path], set[str]]:
    after, changed_stages = set(paths), set()
    for stage in stages:
        for entry in stage["entry_specs"]:
            matches = _expand(root, entry["raw"])[1]
            after.update(matches)
            if tuple(matches) != initial[(stage["id"], "entry", entry["raw"])]: changed_stages.add(stage["id"])
        for artifact in stage["artifact_specs"]:
            matches = _expand(root, artifact["path"], allow_glob=True)[1]
            after.update(matches)
            if artifact["kind"] == "sqlite":
                after.update(sidecar for database in matches for sidecar in _sqlite_sidecars(database))
            if tuple(matches) != initial[(stage["id"], "artifact", artifact["path"] )]: changed_stages.add(stage["id"])
            if "audit" in artifact:
                matches = _expand(root, artifact["audit"])[1]
                after.update(matches)
                if tuple(matches) != initial[(stage["id"], "audit", artifact["audit"] )]: changed_stages.add(stage["id"])
    return after, changed_stages


def _failure(code: str, invalid_inventory: bool = False) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "status": "blocked", "release_eligible": False,
            "findings": [_finding(code, "error")], "summary": {"stage_count": 0, "passed_stage_count": 0,
            "required_stage_count": 0, "required_passed_stage_count": 0},
            **({"invalid_inventory": True} if invalid_inventory else {})}


def audit(root_value: str | os.PathLike[str], inventory_value: str | os.PathLike[str]) -> tuple[dict[str, Any], int]:
    """Run diagnostics without importing or executing project code."""
    try:
        root = Path(root_value).resolve(strict=True)
        if not root.is_dir():
            raise InventoryError("ROOT_INVALID")
        inventory = _safe_path(root, str(inventory_value))
        if not _is_file(inventory):
            raise InventoryError("INVENTORY_MISSING")
        inventory_hash = sha256_file(inventory)
        spec = _read_inventory(root, inventory)
        stages, input_paths, initial = _prepare(root, spec["stages"], inventory)
        before = _snapshot(input_paths)
        reports = [_stage_report(root, stage, before) for stage in stages]
        after_paths, changed_stages = _rescan(root, stages, initial, input_paths)
        after = _snapshot(after_paths)
        changed_paths = {path for path in after_paths if before.get(path) != after.get(path)}
        for report in reports:
            tracked = report.pop("_tracked")
            stage_paths = {path for entry in tracked["entry_specs"] for path in entry["matches"]}
            for artifact in tracked["artifact_specs"]:
                stage_paths.update(artifact["matches"]); stage_paths.update(artifact.get("audit_matches", []))
                stage_paths.update(sidecar for values in artifact.get("sidecars", {}).values() for sidecar in values)
            if report["id"] in changed_stages or changed_paths & stage_paths:
                report["findings"].append(_finding("INPUT_CHANGED_DURING_INSPECTION", "error", report["id"]))
                report["status"] = "blocked"
        global_finding = None if sha256_file(inventory) == inventory_hash else _finding(
            "INVENTORY_CHANGED_DURING_INSPECTION", "error")
        findings = [item for report in reports for item in report["findings"]]
        if global_finding:
            findings.append(global_finding)
        has_error = any(item["severity"] == "error" for item in findings)
        has_warning = any(item["severity"] == "warning" for item in findings)
        status = "blocked" if has_error else "unverified" if has_warning else "ok"
        report = {"schema_version": SCHEMA_VERSION, "inventory": _rel(root, inventory),
                  "status": status, "release_eligible": False, "stages": reports,
                  "findings": findings,
                  "summary": {"stage_count": len(reports),
                              "passed_stage_count": sum(item["status"] == "ok" for item in reports),
                              "required_stage_count": sum(item["required"] for item in reports),
                              "required_passed_stage_count": sum(
                                  item["required"] and item["status"] == "ok" for item in reports)}}
        return report, 1 if has_error else 2 if has_warning else 0
    except InventoryError as exc:
        return _failure(exc.code, True), 2
    except (OSError, ValueError, TypeError):
        return _failure("AUDIT_SETUP_FAILED", True), 2


def _write_exclusive(path: Path, payload: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream: stream.write(payload)


def _output_inputs(root: Path, report: dict[str, Any]) -> set[Path]:
    paths = {root / Path(report["inventory"])} if report.get("inventory") else set()
    for stage in report.get("stages", []):
        paths.update(root / Path(item["path"]) for item in stage.get("entrypoints", []))
        for item in stage.get("artifacts", []):
            paths.add(root / Path(item["path"])); paths.update(root / Path(path) for path in item.get("matches", []))
            paths.update(root / Path(path) for path in item.get("sidecars", []))
            audit = item.get("audit")
            if isinstance(audit, dict) and audit.get("path"): paths.add(root / Path(audit["path"]))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline_audit")
    parser.add_argument("--root", required=True); parser.add_argument("--inventory", required=True); parser.add_argument("--output")
    args = parser.parse_args(argv)
    report, code = audit(args.root, args.inventory)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        try:
            root = Path(args.root).resolve(strict=True)
            output = _safe_path(root, args.output)
            input_paths = _output_inputs(root, report)
            if any(os.path.realpath(output) == os.path.realpath(path) for path in input_paths):
                raise InventoryError("OUTPUT_INPUT_COLLISION")
            logical_output = root / Path(args.output)
            if os.path.islink(logical_output):
                raise InventoryError("OUTPUT_SYMLINK")
            if os.path.lexists(logical_output):
                raise InventoryError("OUTPUT_EXISTS")
            if not output.parent.is_dir():
                raise InventoryError("OUTPUT_PARENT_MISSING")
            _write_exclusive(output, payload)
        except InventoryError as exc:
            report, code = _failure(exc.code), 2
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        except (OSError, ValueError, TypeError):
            report, code = _failure("OUTPUT_UNSAFE"), 2
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(payload, end="")
    print(f"pipeline-audit: status={report['status']} stages={len(report.get('stages', []))} "
          f"findings={len(report.get('findings', []))} release_eligible=false", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
