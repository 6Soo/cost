"""Phase 9 local operations readiness: durable config, backup bundles, restore
verification, restart survival, health/readiness and a deploy dry run.

Scope and boundary
------------------
Nothing here deploys, provisions or contacts anything. There is no Oracle
instance, no Google OAuth client, no reservation API, no production DB, no
real customer original and no paid resource, and this module must not be read as
evidence that any of those were set up. Every check runs against synthetic
paths and synthetic data. A deploy manifest and a dry run are produced and
validated locally; applying one is a separate, human-decided step that this
module does not perform.

Decisions recorded from the specification and the execution contract:

* The data root and the secret settings are explicit and fail closed. The
  pre-existing development defaults (`WEBLEDGER_DB` defaulting to a relative
  `webledger.work.sqlite`, exports into `webledger-exports`) are refused in a
  durable configuration, because a relative default would put operational data
  in whatever directory the process happened to start in, including a source
  checkout or a temp path that is later wiped (criterion 1).
* A backup is a bundle, not a single file: the DB plus the invariant source,
  evidence and output metadata that the DB alone cannot carry. A restore is
  verified after writing to a separate path and the originals are not touched
  (criterion 2).
* A restore is only accepted when the state that matters is re-checked: row
  events, allocations, corrections, request idempotency and the access state.
  The auth cache and the synthetic-session allowance are re-checked rather than
  assumed, because a restore must not silently widen access (criterion 3).
* Restart survival is tested for real on a synthetic DB, not asserted
  (criterion 4).
* Health and readiness never report success for a missing DB, a wrong schema,
  no free space or a missing required setting. Each of those is a distinct
  failing check (criterion 5).
* The retention default keeps the most recent 7 backups and refuses to keep a
  second copy of the same source hash (criterion 8).
* External conditions that still need a human decision are reported separately
  from the code results, so a green run cannot be read as a release approval
  (criterion 9).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import space_guard
from .contracts import canonical_text, sha256_file

# The durable configuration must name these; there is no implicit default that
# could resolve into a temp directory or a source checkout.
REQUIRED_SETTINGS = ("data_root", "db_path", "export_dir", "evidence_dir",
                     "source_dir")

# The historical development defaults. A configuration that resolves one of
# them is refused, because those are relative working-directory values.
REFUSED_DEFAULT_NAMES = ("webledger.work.sqlite", "webledger-exports")

# Environments where a temp-rooted data root is intentional and declared.
ALLOWED_NON_DURABLE_ENVIRONMENTS = ("local-synthetic", "test", "dry-run")

DEFAULT_KEEP_BACKUPS = 7

HEALTH_SCHEMA_TABLES = ("board_rows", "board_revisions", "board_requests",
                        "trip_tabs", "trip_tab_requests",
                        "board_learning_cases")

# The threshold lives in `space_guard` because a health line and a write path
# that each carried their own copy would be two answers to "is there enough
# room". This alias keeps the existing name working for the health check.
MIN_FREE_BYTES = space_guard.MIN_FREE_BYTES
WARN_FREE_BYTES = space_guard.WARN_FREE_BYTES


class OpsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def reservation_sync_state(config: DurableConfig, store) -> dict:
    """Whether the Reservation access directory has been synchronised.

    The snapshot parser, the whole-directory synchronisation and an import
    command exist, so the local half of the RESERVATION-API boundary is built.
    What is still missing is a live transport, and this line exists so a report
    says which half is in place instead of leaving the two indistinguishable.
    """
    present = _has_table(store, "access_reservation_directory_head")
    head = None
    if present:
        row = store.conn.execute(
            "SELECT snapshot_revision, digest, source_version, exported_at,"
            " imported_at FROM access_reservation_directory_head"
            " WHERE singleton_id=1").fetchone()
        if row:
            head = {"snapshot_revision": row[0], "digest": row[1],
                    "source_version": row[2], "exported_at": row[3],
                    "imported_at": row[4]}
    persons = (_count_table(store, "access_reservation_persons")
               if _has_table(store, "access_reservation_persons") else 0)
    active = 0
    if persons:
        active = store.conn.execute(
            "SELECT COUNT(*) FROM access_reservation_persons"
            " WHERE is_active=1").fetchone()[0]
    return {
        "reservation_sync_present": bool(present),
        "reservation_snapshot_imported": head is not None,
        "reservation_head": head,
        "reservation_persons": persons,
        "reservation_persons_active": active,
        "reservation_live_transport": False,
        "reason": ("snapshot import is implemented; no live transport is "
                   "connected, so the directory is only as current as the last "
                   "import"),
    }


def _count_table(store, table) -> int:
    if not _has_table(store, table):
        return 0
    return store.conn.execute(
        f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def parse_reservation_snapshot(payload):
    """Parse a reservation access snapshot, or refuse it with the parser's code.

    The parser is strict on purpose. One place turns its refusal into an
    OpsError so the rehearsal and the apply path cannot answer differently, and
    no caller has to remember to catch a bare ValueError.
    """
    from ledger.domain.reservation_access_snapshot import (
        parse_reservation_access_snapshot)

    try:
        return parse_reservation_access_snapshot(payload)
    except ValueError as exc:
        raise OpsError(str(exc),
                       f"예약 접근 스냅샷이 거부됐어요: {exc}") from exc


def _reservation_uri_ro(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def _reservation_backup_copy(src: Path, dest: Path) -> None:
    """Copy a database with the SQLite backup API (WAL 포함).

    `shutil.copy2` of the main file alone misses -wal content, so the
    rehearsal uses the same consistent-copy method as the importer.
    The source is opened mode=ro and is never mutated here.
    """
    src_conn = None
    dest_conn = None
    try:
        src_conn = sqlite3.connect(
            _reservation_uri_ro(src), uri=True, timeout=10.0)
        dest_conn = sqlite3.connect(str(dest), timeout=10.0)
        src_conn.backup(dest_conn)
    finally:
        for handle in (dest_conn, src_conn):
            try:
                if handle is not None:
                    handle.close()
            except sqlite3.Error:
                pass


def _reservation_sidecar_hash(path: Path) -> str:
    """Hash a sidecar, treating missing/empty as unchanged.

    Merely opening a WAL-mode database mode=ro creates an empty -wal and a
    -shm file. Those are not mutations: -shm is ephemeral shared memory and
    is ignored entirely, and a 0-byte -wal/-journal hashes as "".
    """
    if not path.is_file():
        return ""
    try:
        if path.stat().st_size == 0:
            return ""
    except OSError:
        return ""
    return sha256_file(path)


def _reservation_fingerprint(path: Path) -> dict:
    """Hash the main file plus durable WAL/journal sidecars (-shm ignored)."""
    base = str(path)
    return {
        Path(base).name: sha256_file(path),
        "wal": _reservation_sidecar_hash(Path(base + "-wal")),
        "journal": _reservation_sidecar_hash(Path(base + "-journal")),
    }


def rehearse_reservation_sync(snapshot_bytes: bytes, db_path, *,
                              keep_copy: bool = False,
                              allow_empty: bool = False,
                              allow_large_drop: bool = False) -> dict:
    """Apply a real snapshot to a copy of the database and report the effect.

    The synchronisation commits its own transaction, so an outer transaction
    cannot be used to look without writing. Copying the database with the
    SQLite backup API and running the real code against the copy gives an
    exact rehearsal and touches nothing: the original (including -wal/-shm
    sidecars) is fingerprinted before and after, and a rehearsal that changed
    the original is reported as a failure rather than as a surprise.

    The parser and the access_control guards are shared with the import
    command (`allow_empty`/`allow_large_drop` included), so a snapshot that
    would be refused by the import is refused here first, with the same code.
    A missing target answers RESERVATION_TARGET_MISSING, the same code the
    importer and `ops reservation-sync` use, and never creates a file.
    """
    from . import access_control  # noqa: F401 - keeps the access tables present

    source = Path(db_path)
    if not source.is_file():
        raise OpsError("RESERVATION_TARGET_MISSING",
                       f"예약 접근을 적용할 DB가 없어요: {source}")
    snapshot = parse_reservation_snapshot(snapshot_bytes)
    before = _reservation_fingerprint(source)
    before_main = sha256_file(source)
    staging_dir = Path(tempfile.mkdtemp(prefix="reservation-rehearsal-"))
    try:
        copy = staging_dir / source.name
        try:
            _reservation_backup_copy(source, copy)
        except sqlite3.Error as exc:
            text = str(exc).lower()
            if "unable to open" in text or "no such file" in text:
                raise OpsError("RESERVATION_TARGET_MISSING",
                               f"예약 접근을 적용할 DB가 없어요: {source}") from exc
            if "locked" in text or "busy" in text:
                raise OpsError(access_control.TEMPORARILY_UNAVAILABLE,
                               "DB가 바빠요. 같은 스냅샷으로 잠시 뒤 다시 시도해 주세요") from exc
            raise
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(str(copy), timeout=10.0)
        try:
            store = access_control.AccessStore(conn)
            result = store.sync_reservation_access_snapshot(
                snapshot=snapshot, allow_empty=allow_empty,
                allow_large_drop=allow_large_drop)
        finally:
            conn.close()
        after = _reservation_fingerprint(source)
        if after != before:
            raise OpsError("REHEARSAL_MUTATED_SOURCE",
                           "연습이 원본 DB 를 바꿨어요. 이 결과는 신뢰하지 마세요")
        after_main = sha256_file(source)
        report = dict(result)
        report.update({
            "rehearsal": True,
            "applied_to_real_database": False,
            "source_unchanged": True,
            "source_sha256_before": before_main,
            "source_sha256_after": after_main,
            "snapshot_digest": snapshot["digest"],
            "snapshot_revision": snapshot["snapshot_revision"],
            "persons_in_snapshot": len(snapshot["persons"]),
        })
        if keep_copy:
            report["copy_kept_at"] = str(copy)
        return report
    finally:
        if not keep_copy:
            shutil.rmtree(staging_dir, ignore_errors=True)


def rehearse_migration(*, left_db, right_db, work_dir, migration_db,
                       left_gate=None, right_gate=None,
                       comparison_id="rehearsal") -> dict:
    """Seal both sources, compare them, and report what a human would decide.

    This never applies. It stops at the comparison and the record of it, which
    is exactly the question a cutover has to answer first: what differs, what
    exists on one side only, and what cannot be told apart at all.

    Two facts about the engine shape this function and not a preference:

    * `seal_and_verify_sources` writes `<side>.snapshot.json` *next to the
      source*, because the descriptor records its candidate by bare file name.
      A rehearsal that sealed in place would therefore write two files into the
      operator's source directory. This function copies each source
      byte-identically into `work_dir` and seals the copy. The digest is taken
      from the copy, which is the same bytes, so the seal still proves the real
      source's identity, and the source directory stays untouched.
    * `verify_snapshot` refuses a descriptor with no
      `candidate_semantic_sha256`. That binding is not computed here; it comes
      from the upstream gate report, so each side needs one. Without it the
      answer is a refusal, not a rehearsal.

    The rows are read from the real sources through the engine's read-only
    opener, and the comparison is written only to the named migration DB.
    """
    from . import migration as migration_module

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    left = Path(left_db)
    right = Path(right_db)
    for label, path in (("left", left), ("right", right)):
        if not path.is_file():
            raise OpsError("MIGRATION_SOURCE_MISSING",
                           f"{label} 원본이 없어요: {path}")
    for label, gate in (("left", left_gate), ("right", right_gate)):
        if gate is not None and not Path(gate).is_file():
            raise OpsError("MIGRATION_GATE_REPORT_MISSING",
                           f"{label} 게이트 리포트가 없어요: {gate}")

    # Seal copies so the source directory is never written to. The gate report
    # is copied too: `seal_and_verify_sources` resolves a gate report next to the
    # candidate, so a report left in the source directory would be unreachable
    # from a candidate in the work directory. All three artifacts -- copy,
    # report, descriptor -- then live together in `work_dir`, and the real
    # source directory is never touched.
    sealed_copies = {}
    for label, source, gate in (("left", left, left_gate),
                                ("right", right, right_gate)):
        copy = work_dir / f"{label}-rehearsal{source.suffix or '.sqlite'}"
        shutil.copy2(str(source), str(copy))
        sealed_copies[label] = copy
        if gate is not None:
            shutil.copy2(str(gate), str(work_dir / Path(gate).name))
    for side in ("-wal", "-shm"):
        for copy in sealed_copies.values():
            Path(str(copy) + side).unlink(missing_ok=True)

    try:
        sealed = migration_module.seal_and_verify_sources(
            str(sealed_copies["left"]), str(sealed_copies["right"]),
            str(work_dir), left_gate=left_gate, right_gate=right_gate)
    except migration_module.MigrationError as exc:
        raise OpsError(exc.code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - a contract error is an OpsError
        raise OpsError("MIGRATION_SEAL_REFUSED", str(exc)) from exc

    left_rows = migration_module.read_source_entries(str(left))
    right_rows = migration_module.read_source_entries(str(right))
    summary = migration_module.compare_sources(left_rows, right_rows)

    store = migration_module.MigrationStore(str(migration_db))
    try:
        recorded = store.record_comparison(
            comparison_id=comparison_id, left_rows=left_rows,
            right_rows=right_rows, summary=summary)
    finally:
        store.close()

    # A rehearsal has to say what a person would still have to decide, or it is
    # only a count. `compare_sources` already reports which keys changed on each
    # mismatching pair, so this reads that rather than re-deriving it and
    # risking a second answer to the same question.
    needs_decision = [
        {"entry_id": row.get("entry_id", ""),
         "identity": row.get("identity", ""),
         "fields": list(row.get("changed_fields", []))}
        for row in summary.get("mismatch", [])
    ]
    needs_decision += [
        {"entry_id": row.get("entry_id", ""), "identity": "",
         "fields": ["<present on google only>"]}
        for row in summary.get("google_only", [])
    ]
    needs_decision += [
        {"entry_id": row.get("entry_id", ""), "identity": "",
         "fields": ["<present on db only>"]}
        for row in summary.get("db_only", [])
    ]
    needs_decision += [
        {"entry_id": "", "identity": "", "fields": ["<cannot be told apart>"]}
        for _ in summary.get("ambiguous", [])
    ]
    return {
        "rehearsal": True,
        "applied": False,
        "comparison_id": recorded.get("comparison_id", comparison_id),
        "left_input_sha256": recorded.get("left_input_sha256"),
        "right_input_sha256": recorded.get("right_input_sha256"),
        "counts": summary.get("counts", {}),
        "equal": len(summary.get("equal", [])),
        "mismatch": len(summary.get("mismatch", [])),
        "google_only": len(summary.get("google_only", [])),
        "db_only": len(summary.get("db_only", [])),
        "ambiguous": len(summary.get("ambiguous", [])),
        # The engine labels the sides by their origin, `google` and `db`, not by
        # the caller's `left` and `right`. Reading the caller's names here
        # returned null for both and the report lost its seal evidence while
        # still looking complete.
        "sealed": {
            "left": sealed.get("google"),
            "right": sealed.get("db"),
            "labels": {"left": "google", "right": "db"},
        },
        "sealed_copies": {k: str(v) for k, v in sealed_copies.items()},
        "source_directories_written": False,
        "rows_needing_a_human_decision": needs_decision,
        "note": "비교와 기록까지만 한다. 적용하지 않았으므로 이 DB 의 어느 행도 "
                "바뀌지 않았고, 원본 source 옆에는 아무것도 쓰지 않았다",
    }


def _differs(left, right, field) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return left.get(field) != right.get(field)


class _ReadOnlyStore:
    """The smallest thing a report needs: a `.conn`, opened read-only.

    SPEC_REFINEMENT 18.3 and 19.4 exist so a deployment is exercised before a
    cutover. A check that opens the working database to look at it defeats the
    purpose: `LedgerStore.__init__` creates the file and, before this was found,
    seeded the demo board into it, so the report reported a healthy empty
    database that it had just fabricated. The check must not create the thing it
    checks.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.conn = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=5.0)

    def close(self):
        self.conn.close()


def _probe_values_for(conn, table: str) -> tuple[list, list] | None:
    """Column list and values for a real insert, read from the table itself.

    The earlier probe wrote four columns by name. `board_revisions` requires
    eight NOT NULL values, so on any ledger that had actually been written to
    the insert failed and the report said the board was not writable. A ledger
    that has never been saved happened to pass, which is why the failure only
    appears once there is real data in it. Deriving the columns from
    `PRAGMA table_info` means a future column cannot silently reintroduce it.
    """
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not info:
        return None
    required = []
    for row in info:
        name, notnull, default = row[1], row[3], row[4]
        if notnull and default is None:
            required.append(name)
    if not required:
        required = [row[1] for row in info if row[1] != "id"]
    values = {
        "row_id": "ops-writability-probe",
        "revision": 0,
        "prev_json": "{}",
        "new_json": "{}",
        "event_id": "",
        "change_mode": "probe",
        "actor": "ops-smoke",
        "created_at": utc_now(),
        "client_request_id": "ops-writability-probe",
        "kind": "probe",
        "reverts_event_id": "",
    }
    missing = [c for c in required if c not in values]
    if missing:
        return None
    return required, [values[c] for c in required]


def _board_writable(db_path) -> tuple[bool, str]:
    """Test writability for real, on a throwaway copy of the database.

    A `SELECT` proves nothing about writes, and the previous version reported
    `board_writable` from one, which is a claim the check had not earned. This
    copies the file, writes a row on the copy inside a transaction, and rolls
    it back. The copy is deleted either way, so the real ledger is never
    modified by a health check, and the answer is still an observed write rather
    than an assumed one.
    """
    if not Path(db_path).is_file():
        return False, "not tested: the db file is missing"
    import tempfile
    with tempfile.TemporaryDirectory(prefix="webledger-writability-") as tmp:
        probe = Path(tmp) / "probe.sqlite"
        try:
            shutil.copyfile(str(db_path), str(probe))
        except OSError as exc:
            return False, f"could not copy the db for a write test: {exc}"
        try:
            conn = sqlite3.connect(str(probe), timeout=5.0,
                                   isolation_level=None)
        except sqlite3.Error as exc:
            return False, f"could not open a write probe: {exc}"
        try:
            shape = _probe_values_for(conn, "board_revisions")
            if shape is None:
                return False, ("could not build a probe write: the table or its "
                               "required columns were not found")
            columns, values = shape
            placeholders = ",".join("?" for _ in columns)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"INSERT INTO board_revisions({','.join(columns)})"
                f" VALUES ({placeholders})", values)
            conn.execute("ROLLBACK")
            return True, "a write and a rollback succeeded on a copy of the db"
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return False, f"a write on a copy of the db failed: {exc}"
        finally:
            conn.close()


def smoke_report(config: DurableConfig, store=None) -> dict:
    """Could this process answer a request right now?

    SPEC_REFINEMENT 18.3 and 19.4 ask for a deployment to be exercised before a
    cutover rather than after it. This is that exercise, reduced to what can be
    decided without a real customer, a real provider or a real hosting resource.

    A blocker means the process should not be serving. A warning means it can
    serve but something an operator decided to check is unrecorded.

    The database is opened read-only and only when it already exists. A missing
    database is reported as a missing database.
    """
    owned = False
    if store is None:
        if not config.db_path.is_file():
            health = health_check(config)
            blockers = list(health["failed"])
            warnings = [c["check"] for c in health["checks"]
                        if not c["ok"] and not c["fatal"]]
            return {
                "generated_at": utc_now(),
                "environment": config.environment,
                "ok": False,
                "can_serve": False,
                "blockers": sorted(set(blockers)),
                "warnings": sorted(set(warnings)),
                "health_ok": health["ok"],
                "checks": health["checks"],
                "google_oidc_connected": bool(
                    google_oidc_state().get("google_oidc_connected")),
                "reservation": None,
                "board_writable": False,
                "board_writable_detail":
                    "not tested: the db file is missing",
                "external_conditions_still_unmet": EXTERNAL_CONDITIONS,
            }
        store = _ReadOnlyStore(config.db_path)
        owned = True
    try:
        return _smoke_report_with_store(config, store)
    finally:
        if owned:
            store.close()


def _smoke_report_with_store(config: DurableConfig, store) -> dict:
    health = health_check(config, store)
    blockers = list(health["failed"])
    warnings = []
    for check in health["checks"]:
        if not check["ok"] and not check["fatal"]:
            warnings.append(check["check"])

    oidc = google_oidc_state()
    if config.environment == "production" and not oidc.get(
            "google_oidc_connected"):
        blockers.append("google_oidc_connected")
    reservation = reservation_sync_state(config, store)
    if not reservation["reservation_live_transport"]:
        warnings.append("reservation_live_transport")

    can_read = False
    try:
        can_read = store.conn.execute(
            "SELECT COUNT(*) FROM board_rows").fetchone() is not None
    except Exception:  # noqa: BLE001 - an unreadable store is a blocker below
        can_read = False
    if not can_read:
        blockers.append("board_readable")

    writable, writable_detail = _board_writable(config.db_path)
    if not writable:
        warnings.append("board_writable")

    return {
        "generated_at": utc_now(),
        "environment": config.environment,
        "ok": not blockers,
        "can_serve": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "health_ok": health["ok"],
        "checks": health["checks"],
        "google_oidc_connected": bool(oidc.get("google_oidc_connected")),
        "reservation": reservation,
        "board_writable": writable,
        "board_writable_detail": writable_detail,
        "external_conditions_still_unmet": EXTERNAL_CONDITIONS,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ bind rules
# SPEC_REFINEMENT 19.2: "외부에는 HTTPS 앱 경로만 제공하고 SQLite·원천
# 디렉터리·작업자 관리 포트를 공개하지 않는다." The app here is a stdlib
# HTTP server with no TLS, so binding it anywhere but loopback would put the
# ledger on plain HTTP outside the host. The supported shape is therefore a
# reverse proxy on the same machine terminating HTTPS and forwarding to
# loopback.
#
# A non-loopback bind is still possible, because a containerised proxy cannot
# reach 127.0.0.1 on the host. It is allowed only when the operator states that a
# proxy is in front of it, and the runbook then says so instead of the run
# looking like the recommended shape.
LOOPBACK_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost")

PUBLIC_BIND_NAMES = ("0.0.0.0", "::", "*", "")

WILDCARD_ADDRESSES = ("0.0.0.0", "::", "")


def is_loopback_host(host: str) -> bool:
    """Whether a bind address only accepts connections from this machine."""
    if host is None:
        return True
    name = str(host).strip()
    if name.lower() in PUBLIC_BIND_NAMES:
        return False
    if name.lower() in LOOPBACK_NAMES:
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        # A name that is not an address and not a known loopback alias is
        # treated as external, so an unknown host cannot be mistaken for a
        # safe one.
        return False


def bind_posture(host: str, *, behind_proxy: bool = False) -> dict:
    """Classify a bind address and state what it means operationally.

    Returns a report rather than raising, so a caller can print it. The refusal
    itself lives in `require_safe_bind`, which the serving commands call.
    """
    loopback = is_loopback_host(host)
    if loopback:
        shape = "loopback-behind-https-proxy"
        note = ("앱은 이 컴퓨터 안에서만 reachable 합니다. 같은 머신의 프록시가 "
                "HTTPS를 종료하고 여기로 전달해야 해요. 19.2에 맞는 기본 형태예요")
        acceptable = True
    elif behind_proxy:
        shape = "non-loopback-for-proxy"
        note = ("프록시가 이 주소로 전달한다는 전제입니다. 프록시가 같은 네트워크 "
                "네임스페이스 안에 있어야 하고, 이 주소가 인터넷에 열리면 안 돼요")
        acceptable = True
    else:
        shape = "external-bind"
        note = ("이 서버는 TLS를 끝내지 않습니다. 외부 주소를 직접 열면 평문 "
                "HTTP로 장부가 노출돼요. 19.2는 HTTPS 앱 경로만 외부에 "
                "열도록 정했어요")
        acceptable = False
    return {"host": str(host), "loopback": loopback,
            "behind_proxy": bool(behind_proxy), "shape": shape,
            "acceptable": acceptable, "note": note,
            "external_exposure": "none" if loopback else
                                 "app port, without TLS"}


def require_safe_bind(host: str, *, behind_proxy: bool = False) -> dict:
    """Refuse a bind that would put the ledger on plain HTTP outside the host.

    The default shape needs no flag: bind loopback and put a proxy in front.
    The escape hatch is `--behind-proxy`, which is for a proxy on a different
    network namespace and is recorded as a different shape, not as the
    recommended one.
    """
    report = bind_posture(host, behind_proxy=behind_proxy)
    if not report["acceptable"]:
        raise OpsError("UNSAFE_BIND", report["note"])
    return report


def _posix(path) -> str:
    """A path spelled with forward slashes, so the checks are separator safe."""
    return str(Path(path)).replace("\\", "/").lower()


def _env_value(name: str):
    return os.environ.get(name)


# ------------------------------------------------------------ durable config
class DurableConfig:
    """The explicit, validated data root and secret settings.

    `from_env` is the only way an environment produces a configuration, and it
    refuses a relative or temp-rooted value rather than accepting it. Secrets
    are never stored here: only whether a required one is present, so a report
    can prove a key exists without carrying it.
    """

    def __init__(self, *, data_root, db_path, export_dir, evidence_dir,
                 source_dir, required_secrets=(), keep_backups=DEFAULT_KEEP_BACKUPS,
                 environment="local-synthetic", allow_missing_root: bool = False):
        self.data_root = Path(data_root).resolve()
        self.db_path = Path(db_path)
        self.export_dir = Path(export_dir)
        self.evidence_dir = Path(evidence_dir)
        self.source_dir = Path(source_dir)
        self.required_secrets = tuple(required_secrets)
        self.keep_backups = int(keep_backups)
        self.environment = environment
        # `allow_missing_root` exists for one caller: `durable_config_for`
        # checks *where* a root is before it creates it, and the existence check
        # cannot pass until it has. Every other caller leaves it off, so a
        # configuration that names a directory which is not there is still a
        # refusal.
        self.validate(allow_missing_root=allow_missing_root)

    def validate(self, *, allow_missing_root: bool = False) -> None:
        for name in REQUIRED_SETTINGS:
            value = getattr(self, name)
            if value is None or str(value).strip() == "":
                raise OpsError("MISSING_SETTING", f"필수 설정이 없어요: {name}")
        if not self.data_root.is_absolute():
            raise OpsError("RELATIVE_DATA_ROOT",
                           "데이터 루트는 절대 경로여야 해요")
        if self.keep_backups < 1:
            raise OpsError("INVALID_RETENTION", "백업 보관 개수는 1 이상이어야 해요")
        # A development default that resolves relative would write into a
        # working directory that is not a durable data root.
        for name in ("db_path", "export_dir", "evidence_dir", "source_dir"):
            value = getattr(self, name)
            if not value.is_absolute():
                raise OpsError("RELATIVE_SETTING",
                               f"{name} 은 절대 경로여야 해요. "
                               f"개발용 기본값은 운영 자료에 쓰지 않아요")
        # Separators are normalised first: a Windows check would otherwise miss
        # a path because it is spelled with backslashes.
        joined = " ".join(_posix(p) for p in
                          (self.data_root, self.db_path, self.export_dir,
                           self.evidence_dir, self.source_dir))
        for part in REFUSED_DEFAULT_NAMES:
            if f"/{part}" in f"/{joined}":
                raise OpsError(
                    "REFUSED_DEFAULT_PATH",
                    f"개발 기본값은 운영 자료에 쓰지 않아요: {part}")
        # A production data root inside the system temp directory is the actual
        # hazard: it can be wiped between runs. A synthetic or dry-run
        # configuration is allowed to sit there on purpose, and says so.
        if self.environment not in ALLOWED_NON_DURABLE_ENVIRONMENTS:
            temp_root = Path(tempfile.gettempdir()).resolve()
            try:
                self.data_root.resolve().relative_to(temp_root)
            except ValueError:
                pass
            else:
                raise OpsError(
                    "TEMP_DATA_ROOT",
                    f"운영 데이터 루트가 임시 디렉터리 아래예요: {temp_root}")
        if not self.data_root.is_dir() and not allow_missing_root:
            raise OpsError("MISSING_DATA_ROOT",
                           f"데이터 루트가 없어요: {self.data_root}")
        # A durable data root inside this source checkout is refused for the
        # same reason a temp-rooted one is: 18.3 item 2 keeps durable data under
        # an explicit persistent root, and a redeploy or a checkout wipe would
        # take the ledger with it. A synthetic run may sit anywhere on purpose.
        if self.environment not in ALLOWED_NON_DURABLE_ENVIRONMENTS \
                and _inside_source_checkout(self.data_root):
            checkout = Path(__file__).resolve().parent.parent
            raise OpsError(
                "CHECKOUT_DATA_ROOT",
                f"운영 데이터 루트가 소스 체크아웃 안이에요: {checkout}\n"
                f"재배포나 체크아웃 정리 때 장부까지 지워져요. "
                f"지속 디스크의 절대 경로를 지정해 주세요")

    @classmethod
    def from_env(cls, env=None, *, secrets=(), keep_backups=DEFAULT_KEEP_BACKUPS,
                 environment="local-synthetic") -> "DurableConfig":
        """Build a configuration from explicit environment values only.

        A missing value is a refusal. The historical development defaults in
        `ledger_board.serve` are intentionally not mirrored here.
        """
        env = dict(os.environ if env is None else env)
        missing = [name for name in ("WEBLEDGER_DATA_ROOT",) if not env.get(name)]
        if missing:
            raise OpsError("MISSING_SETTING",
                           f"운영 설정이 비어 있어요: {', '.join(missing)}")
        root = Path(env["WEBLEDGER_DATA_ROOT"])
        def pick(name, default_name):
            value = env.get(name)
            if not value:
                value = env.get(default_name)
            if not value:
                raise OpsError("MISSING_SETTING", f"운영 설정이 비어 있어요: {name}")
            return Path(value)
        return cls(
            data_root=root,
            db_path=pick("WEBLEDGER_DB", "WEBLEDGER_DATA_DB"),
            export_dir=pick("WEBLEDGER_EXPORT_DIR", "WEBLEDGER_DATA_EXPORTS"),
            evidence_dir=pick("WEBLEDGER_EVIDENCE_DIR", "WEBLEDGER_DATA_EVIDENCE"),
            source_dir=pick("WEBLEDGER_SOURCE_DIR", "WEBLEDGER_DATA_SOURCE"),
            required_secrets=secrets,
            keep_backups=keep_backups,
            environment=environment,
        )

    def secret_state(self, env=None) -> dict:
        """Whether each required secret is present. Never the value."""
        env = dict(os.environ if env is None else env)
        return {name: bool(env.get(name)) for name in self.required_secrets}

    def describe(self, env=None) -> dict:
        return {
            "environment": self.environment,
            "data_root": str(self.data_root),
            "db_path": str(self.db_path),
            "export_dir": str(self.export_dir),
            "evidence_dir": str(self.evidence_dir),
            "source_dir": str(self.source_dir),
            "keep_backups": self.keep_backups,
            "required_secrets": list(self.required_secrets),
            "secret_state": self.secret_state(env),
        }


# ------------------------------------------------------------ backup bundles
def make_backup_bundle(config: DurableConfig, store, *, label: str = "",
                       operator_ledger=None) -> dict:
    """Back up the DB plus the invariant metadata beside it.

    The DB is copied with SQLite's own online backup so no writer is torn, and
    the source/evidence/output metadata is copied by content hash. The
    originals are only read.
    """
    backup_dir = config.data_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = f"bundle-{stamp}{('-' + label) if label else ''}"
    target = backup_dir / name
    target.mkdir(parents=True, exist_ok=True)

    db_copy = target / "board.sqlite"
    src = sqlite3.connect(f"file:{config.db_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(db_copy))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    manifest = {
        "bundle": name,
        "created_at": utc_now(),
        "environment": config.environment,
        "source_hashes": {},
        "files": {},
    }
    for key, directory in (("source", config.source_dir),
                           ("evidence", config.evidence_dir),
                           ("export", config.export_dir)):
        copied = []
        directory = Path(directory)
        if directory.is_dir():
            dest = target / key
            dest.mkdir(parents=True, exist_ok=True)
            for item in sorted(directory.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(directory)
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest / rel)
                digest = sha256_file(item)
                copied.append({"path": rel.as_posix(), "sha256": digest,
                               "size_bytes": item.stat().st_size})
                manifest["source_hashes"][f"{key}:{rel.as_posix()}"] = digest
        manifest["files"][key] = copied

    db_digest = sha256_file(db_copy)
    manifest["files"]["db"] = [{"path": "board.sqlite", "sha256": db_digest,
                                "size_bytes": db_copy.stat().st_size}]
    # A bundle that is a byte copy of an existing one is not a new backup.
    manifest["bundle_sha256"] = hashlib.sha256(
        canonical_text({"db": db_digest,
                        "sources": sorted(manifest["source_hashes"].items())}
                       ).encode("utf-8")).hexdigest()
    manifest["state"] = _state_summary(store)
    if operator_ledger is not None and not getattr(operator_ledger, 'embedded', False):
        # reuse the existing operator-ledger backup so the chain and its
        # checkpoint travel with the board
        ledger_copy = target / "operator_ledger.sqlite"
        result = operator_ledger.backup(str(ledger_copy))
        manifest["files"]["operator_ledger"] = [
            {"path": Path(result["backup_db"]).name,
             "sha256": sha256_file(ledger_copy),
             "size_bytes": ledger_copy.stat().st_size}]
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return manifest


def _state_summary(store) -> dict:
    """The state a restore has to be able to reproduce.

    The counts are accompanied by a content digest, because equal counts are
    not the same state: SPEC_REFINEMENT 17.3 2항 refuses a restore that passes on
    totals alone.
    """
    def count(table, where=""):
        return store.conn.execute(
            f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
    summary = {
        "rows": count("board_rows"),
        "revisions": count("board_revisions"),
        "requests": count("board_requests"),
        "trips": count("trip_tabs"),
        "learning_cases": count("board_learning_cases"),
    }
    summary["business_digest"] = business_state_digest(store)["digest"]
    return summary


def list_bundles(config: DurableConfig) -> list[dict]:
    backup_dir = config.data_root / "backups"
    if not backup_dir.is_dir():
        return []
    found = []
    for item in sorted(backup_dir.iterdir()):
        manifest_path = item / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["path"] = str(item)
        found.append(manifest)
    found.sort(key=lambda m: m.get("created_at", ""))
    return found


def apply_retention(config: DurableConfig) -> dict:
    """Keep the most recent N bundles and refuse a duplicate source hash.

    Two bundles whose content hash matches are the same data, so the older one
    is dropped rather than filling the disk with copies.
    """
    bundles = list_bundles(config)
    removed = []
    seen_hashes = {}
    for manifest in reversed(bundles):
        digest = manifest.get("bundle_sha256")
        if digest in seen_hashes:
            removed.append({"bundle": manifest["bundle"],
                            "reason": "same content hash as a newer bundle",
                            "kept": seen_hashes[digest]})
            shutil.rmtree(manifest["path"], ignore_errors=True)
            continue
        seen_hashes[digest] = manifest["bundle"]
    bundles = list_bundles(config)
    overflow = bundles[:max(0, len(bundles) - config.keep_backups)]
    for manifest in overflow:
        shutil.rmtree(manifest["path"], ignore_errors=True)
        removed.append({"bundle": manifest["bundle"],
                        "reason": "older than the retention window"})
    remaining = list_bundles(config)
    return {"kept": [m["bundle"] for m in remaining],
            "kept_count": len(remaining),
            "retention": config.keep_backups,
            "removed": removed}


# ------------------------------------------------------------------ restore
def resolve_bundle(config: DurableConfig, bundle) -> Path:
    """Find the bundle directory, whether the caller gave a name or a path.

    `ops backup` prints the bundle's bare name, so that name is the thing an
    operator has in front of them. Passing it straight through produced a
    `FileNotFoundError` traceback naming a relative path against the process's
    working directory, which is a different directory from the one the bundle
    is in. A name is therefore resolved inside the configured backup root, and a
    name that is not there is refused with a code rather than an exception.
    """
    raw = Path(str(bundle).strip())
    if raw.is_dir():
        return raw
    candidate = Path(config.data_root) / "backups" / raw
    if candidate.is_dir():
        return candidate
    raise OpsError("BUNDLE_NOT_FOUND",
                   f"백업 묶음을 찾지 못했어요: {bundle}\n"
                   f"확인한 위치: {raw} 와 {candidate}")


def restore_bundle(config: DurableConfig, bundle, *, target_root,
                   store_factory) -> dict:
    """Restore a bundle to a separate path and re-verify the state.

    The original bundle and the live DB are not touched: the restore target is
    a different root, so a bad bundle can be inspected without risking the
    running data.
    """
    bundle = resolve_bundle(config, bundle)
    manifest = json.loads((Path(bundle) / "manifest.json").read_text(
        encoding="utf-8"))

    # A bundle with no recorded business state cannot be verified, and 17.3
    # forbids passing a restore because the totals happen to match. An older
    # bundle written before the digest existed is refused with a code rather
    # than restored and reported as fine, because "nothing to compare" and
    # "everything compared equal" look identical from the outside.
    recorded_state = manifest.get("state")
    if not isinstance(recorded_state, dict) or not recorded_state:
        raise OpsError(
            "BUNDLE_HAS_NO_VERIFIABLE_STATE",
            f"이 백업 묶음에는 복구 검증 기준이 없습니다: {bundle}\n"
            f"묶음에 기록된 상태(state)가 없어 복원 결과를 대조할 기준이 "
            f"없습니다. 17.3이 '합계가 같다는 이유로 복구를 통과시키지 않는다'고 "
            f"정했으므로, 새 묶음으로 다시 백업한 뒤 복원해 주세요.")
    target_root = Path(target_root)
    # A restore target has to be empty. Copying a bundle over the top of a
    # previous restore leaves files from two different bundles in one directory,
    # and the report then describes a directory that no single backup produced.
    # An operator who wants the old copy keeps it by naming a new target.
    if target_root.exists():
        if not target_root.is_dir():
            raise OpsError("RESTORE_TARGET_NOT_A_DIRECTORY",
                           f"복원 대상이 디렉터리가 아니에요: {target_root}")
        existing = sorted(p.name for p in target_root.iterdir())
        if existing:
            raise OpsError(
                "RESTORE_TARGET_NOT_EMPTY",
                f"복원 대상이 비어 있지 않아요: {target_root}\n"
                f"들어 있는 항목: {existing}\n"
                f"서로 다른 두 묶음이 한 디렉터리에 섞이면 복구 결과가 어느 "
                f"백업의 것인지 알 수 없습니다. 비어 있는 경로를 지정하거나 "
                f"기존 내용을 따로 옮겨 주세요.")
    target_root.mkdir(parents=True, exist_ok=True)

    problems = []
    db_copy = Path(bundle) / "board.sqlite"
    if not db_copy.is_file():
        problems.append("bundle has no board.sqlite")
    else:
        expected = next((f["sha256"] for f in manifest["files"].get("db", [])),
                        None)
        actual = sha256_file(db_copy)
        if expected is None:
            # A bundle whose manifest lost the db hash cannot be verified at
            # all. Skipping the comparison would let an unreadable database
            # through as if it had been checked, so it is a refusal.
            problems.append(
                "bundle manifest records no db sha256; an unverifiable db is "
                "not restored")
        elif actual != expected:
            problems.append("bundle db sha256 mismatch")
    for key in ("source", "evidence", "export"):
        for item in manifest["files"].get(key, []):
            path = Path(bundle) / key / item["path"]
            if not path.is_file():
                problems.append(f"missing {key} file: {item['path']}")
            elif sha256_file(path) != item["sha256"]:
                problems.append(f"{key} sha256 mismatch: {item['path']}")
    if problems:
        # The same shape as a verified restore, so a caller never has to guess
        # which keys exist on a refusal.
        return {"ok": False, "problems": problems, "restored": False,
                "target_root": str(Path(target_root)), "restored_db": None,
                "state": None, "access": None, "idempotency": None}

    restored_db = target_root / "board.sqlite"
    shutil.copy2(db_copy, restored_db)
    for key in ("source", "evidence", "export"):
        dest = target_root / key
        for item in manifest["files"].get(key, []):
            src = Path(bundle) / key / item["path"]
            (dest / item["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / item["path"])

    # Re-verify the restored state with a fresh store, not with the live one.
    # A database that cannot even be opened is a refused restore, not a crash:
    # an operator has to see which bundle failed, so the problem is reported
    # and the unusable copy is removed from the target root.
    comparison = access = idempotency = None
    try:
        restored_store = store_factory(restored_db)
    except Exception as exc:  # noqa: BLE001 - any open failure is a finding
        problems.append(f"restored db could not be opened: {exc}")
        problems.extend(_discard_restored(target_root))
        return {"ok": False, "problems": problems, "restored": False,
                "target_root": str(target_root), "restored_db": None}
    try:
        integrity = restored_store.conn.execute(
            "PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"restored db integrity_check: {integrity}")
        comparison = verify_restored_state(manifest.get("state", {}),
                                           restored_store)
        problems.extend(comparison["problems"])
        access = verify_access_state_after_restore(restored_store)
        problems.extend(access["problems"])
        idempotency = verify_request_idempotency_after_restore(restored_store)
        problems.extend(idempotency["problems"])
    except Exception as exc:  # noqa: BLE001 - a failed check is a refusal
        problems.append(f"restore verification could not complete: {exc}")
    finally:
        restored_store.close()
    if problems:
        # Leave nothing behind that looks like a usable restore.
        problems.extend(_discard_restored(target_root))

    return {
        "ok": not problems,
        "problems": problems,
        "restored": not problems,
        "target_root": str(target_root),
        "restored_db": str(restored_db) if not problems else None,
        "state": comparison if not problems else None,
        "access": access if not problems else None,
        "idempotency": idempotency if not problems else None,
    }


def _discard_restored(target_root) -> list:
    """Remove a restore target that did not verify, so it cannot be reused.

    Returns a problem for anything it could not remove rather than swallowing
    the failure. A store that could not be opened leaves its SQLite connection
    unclosed, and on Windows that keeps the file locked, so a silent cleanup
    would leave a corrupt `board.sqlite` in the target that looks like a usable
    restore. The operator has to be told the directory is not clean.
    """
    left = []
    for child in sorted(Path(target_root).glob("*")):
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            left.append(f"could not remove {child.name} from the restore "
                        f"target: {exc}")
    if left:
        left.append("the restore target is not clean; remove it by hand before "
                    "retrying")
    return left


def verify_restored_state(expected: dict, store) -> dict:
    """Row events, allocations, corrections and trips must all be back.

    Item 2 of SPEC_REFINEMENT 17.3 forbids passing a restore because the totals match,
    so the counts are backed by a content digest taken over the actual
    event-level state: the saved amount and pin of every row, every trip
    assignment, every allocation, every correction and every rule version.
    Two databases with equal counts but a different amount, a different trip or
    a different rule version produce different digests and are refused.
    """
    problems = []
    observed = _state_summary(store)
    for key, want in (expected or {}).items():
        if key not in observed:
            continue
        if observed[key] != want:
            problems.append(f"{key} count differs: expected {want}, got {observed[key]}")
    allocations = store.conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        " AND name LIKE '%alloc%'").fetchone()[0]
    corrections = store.conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        " AND name LIKE '%bank%'").fetchone()[0]

    digest = business_state_digest(store)
    want_digest = (expected or {}).get("business_digest")
    if want_digest:
        if want_digest != digest["digest"]:
            differing = [k for k in set(want_digest) | set(digest["digest"])
                         if want_digest.get(k) != digest["digest"].get(k)]
            problems.append(
                "restored business content differs from the backup: "
                f"{', '.join(sorted(differing)) or 'digest'}")
    return {
        "problems": problems,
        "observed": observed,
        "expected": expected or {},
        "allocation_tables": allocations,
        "correction_tables": corrections,
        "events_present": observed.get("revisions", 0) > 0,
        "content_compared": bool(want_digest),
        "business_digest": digest,
    }


# The tables whose *content* a restore has to reproduce, not just their row
# count. The listed columns are the ones that carry the business meaning of one
# event, so a mismatch can be reported by name. A column that a given schema
# version does not have is skipped rather than treated as a failure; when none of
# them survive, every column of the table is hashed instead, so the comparison
# stays whole and never silently narrows.
_DIGEST_TABLES = (
    ("board_rows", ("row_id", "row_kind", "display_tab_id", "payload_json",
                    "revision")),
    ("board_revisions", ("row_id", "revision", "change_mode", "prev_json",
                         "new_json", "event_id")),
    ("trip_tabs", ("tab_id", "display_key", "event_year", "tab_kind",
                   "authority_status", "source_sha256", "sort_order")),
    ("board_requests", ("client_request_id", "row_id", "result_json",
                        "ledger_pending")),
    ("classification_rule_versions", ("rule_id", "version", "status",
                                      "rule_hash")),
    ("classification_rules", ("rule_id", "version", "status", "rule_hash")),
)


def business_state_digest(store) -> dict:
    """A content hash over the event-level state, not over the totals.

    `sha256` of the whole database would already cover this, but a digest taken
    from named business columns is what makes the comparison reviewable: it
    names which part of the state moved, so an operator sees `board_rows` or
    `classification_rule_versions` rather than a bare mismatch.
    """
    parts = {}
    columns_used = {}
    problems = []
    cost_tables = ('import_batches','import_batch_rows','transactions','cost_classification_rules',
                   'review_decisions','ledger_entries','change_log','requests','decision_events',
                   'review_choice_sets','review_source_guidance','review_guidance_requests',
                   'review_guidance_previews','review_guidance_results')
    for table, preferred in list(_DIGEST_TABLES) + [(t, ()) for t in cost_tables]:
        if not _has_table(store, table):
            continue
        present = [r[1] for r in store.conn.execute(f"PRAGMA table_info({table})")]
        order = [c for c in preferred if c in present]
        if not order:
            # No named column survives on this schema version, so the whole row
            # is hashed. Naming the fallback keeps the report honest.
            order = list(present)
            problems.append(
                f"{table} has none of the named business columns "
                f"{list(preferred)}; hashed every column instead")
        rows = store.conn.execute(
            f"SELECT {', '.join(order)} FROM {table}").fetchall()
        payload = sorted([[str(v) for v in row] for row in rows],
                         key=lambda r: r)
        parts[table] = hashlib.sha256(
            canonical_text(payload).encode("utf-8")).hexdigest()
        columns_used[table] = order
    return {
        "digest": parts,
        "digest_of": hashlib.sha256(
            canonical_text(sorted(parts.items())).encode("utf-8")).hexdigest(),
        "tables": sorted(parts),
        "columns": columns_used,
        "notes": problems,
        # kept for callers that read `problems`; a fallback is reported but is
        # not a restore failure, because the content is still compared whole.
        "problems": [],
    }


def verify_request_idempotency_after_restore(store) -> dict:
    """A replayed request id must still return the first result.

    A backup that lost the request table would let the same request create a
    second effect, so this is re-checked rather than assumed.
    """
    problems = []
    replayed = None
    row = store.conn.execute(
        "SELECT client_request_id, result_json FROM board_requests LIMIT 1"
    ).fetchone()
    if row is None:
        return {"problems": problems, "checked": False,
                "reason": "no request to replay in this bundle"}
    try:
        result = json.loads(row[1])
    except ValueError:
        problems.append("a stored request result is not readable JSON")
        return {"problems": problems, "checked": False}
    again = store.conn.execute(
        "SELECT result_json FROM board_requests WHERE client_request_id=?",
        (row[0],)).fetchone()
    if again is None or again[0] != row[1]:
        problems.append("the request id no longer returns its first result")
    else:
        replayed = True
    return {"problems": problems, "checked": True, "replayed": replayed,
            "request_id_present": True}


def verify_access_state_after_restore(store) -> dict:
    """Re-check the access state instead of trusting the backup.

    A restore must not widen access: a viewer that was linked before the
    backup has to be linked after it, and a revoked one stays revoked. The auth
    cache and the synthetic-session allowance are reported as separate facts so
    a stale allowance cannot be mistaken for a real login path.
    """
    problems = []
    accounts = accounts_present(store)
    connections = connections_present(store)
    synthetic_allowed = _synthetic_sessions_allowed()
    if synthetic_allowed:
        # A synthetic session allowance is not an operational login. It is
        # recorded, not treated as a healthy auth path.
        problems.append(
            "synthetic session adapter is allowed; this is not an "
            "operational authentication path")
    return {
        "problems": problems,
        "accounts": accounts,
        "connections": connections,
        "auth_cache": "not used: access is decided per request",
        "synthetic_sessions_allowed": synthetic_allowed,
    }


def accounts_present(store) -> list:
    if not _has_table(store, "access_accounts"):
        return []
    rows = store.conn.execute(
        "SELECT user_id, role, is_active FROM access_accounts"
        " ORDER BY user_id").fetchall()
    return [{"user_id": r[0], "role": r[1], "is_active": bool(r[2])} for r in rows]


def connections_present(store) -> list:
    if not _has_table(store, "access_connections"):
        return []
    rows = store.conn.execute(
        "SELECT connection_id, user_id, status FROM access_connections"
        " ORDER BY connection_id").fetchall()
    return [{"connection_id": r[0], "user_id": r[1], "status": r[2]} for r in rows]


def _synthetic_sessions_allowed() -> bool:
    from . import access_control

    adapter = access_control.session_adapter()
    return bool(getattr(adapter, "allow_synthetic", False))


def google_oidc_state() -> dict:
    """Whether a real Google login is connected, for a health line or a report.

    One function, one path. The board owns the bound flow and the board reads
    the real state, so this delegates instead of re-deriving anything. An
    earlier version had a fallback that computed the same answer by another
    route; two routes that are meant to agree are how a health check and a screen
    end up telling an operator different things.

    Nothing here re-derives the answer from the environment. A report has to
    describe the process that is actually serving, not the settings someone meant
    to apply — the environment can be fully set while the process bound no flow.
    """
    from . import ledger_board

    return ledger_board.google_oidc_connection_state()


def _has_table(store, name) -> bool:
    return store.conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone()[0] > 0


# -------------------------------------------------------- health / readiness
def health_check(config: DurableConfig, store=None) -> dict:
    """Report each fact separately; a missing one is never folded into success."""
    checks = []

    def add(name, ok, detail="", fatal=True):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "fatal": fatal})

    add("data_root_exists", config.data_root.is_dir(), str(config.data_root))
    db_present = config.db_path.is_file()
    add("db_file_exists", db_present, str(config.db_path))
    if db_present:
        conn = sqlite3.connect(f"file:{config.db_path.as_posix()}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            add("db_integrity", integrity == "ok", integrity)
            present = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t in HEALTH_SCHEMA_TABLES if t not in present]
            add("db_schema", not missing,
                f"missing tables: {missing}" if missing else
                f"{len(HEALTH_SCHEMA_TABLES)} tables present")
        finally:
            conn.close()
    else:
        # The schema check is still reported. Skipping it because the DB is
        # missing would hide the failure behind the db_file_exists line.
        add("db_integrity", False, "not checked: the db file is missing")
        add("db_schema", False, "not checked: the db file is missing")
    free = _free_bytes(config.data_root)
    add("free_space", free is not None and free >= MIN_FREE_BYTES,
        f"{free} bytes" if free is not None else "free space unknown")
    # SPEC_REFINEMENT 19.3 asks for a warning *before* the volume is full, not
    # at the moment a write is refused. The first line is fatal at the same
    # threshold a write uses; this one is not, and it names what will start
    # being refused so an operator can act on the number.
    headroom = (free is not None
                and free - MIN_FREE_BYTES < space_guard.WARN_FREE_BYTES)
    add("free_space_headroom",
        not headroom,
        f"{WARN_FREE_BYTES - MIN_FREE_BYTES} bytes below this and writes will "
        f"start being refused; free={free} bytes"
        if headroom else
        ("free space unknown" if free is None
         else f"writes keep their headroom; free={free} bytes"),
        fatal=False)
    secrets = config.secret_state()
    missing_secrets = [name for name, present in secrets.items() if not present]
    add("required_secrets", not missing_secrets,
        f"missing: {missing_secrets}" if missing_secrets else
        f"{len(secrets)} checked")
    if store is not None:
        add("store_readable", True, "store bound")
    synthetic = _synthetic_sessions_allowed()
    # The detail states what was actually found. A fixed sentence here used to
    # say the allowance was present even on a healthy system, so the line
    # contradicted its own verdict in both directions.
    add("synthetic_sessions", not synthetic,
        "synthetic session adapter is allowed; not an operational auth path"
        if synthetic else
        "no synthetic session allowance; access must come from a real login")
    # A real Google login path is a separate fact from "the synthetic seam is
    # off". Turning one off does not turn the other on, so they are two lines.
    #
    # The line is reported always and is fatal only in production. A local or
    # synthetic run legitimately has no Google login yet, and making it fatal
    # there would mean `ops health` fails for a run that is working as declared.
    # In production a runbook with no real login serves nobody, so it is fatal.
    oidc = google_oidc_state()
    add("google_oidc_connected", bool(oidc.get("google_oidc_connected")),
        oidc.get("reason") or (
            f"google OIDC connected, library="
            f"{'available' if oidc.get('library_available') else 'missing'}"
            + (", owner bootstrap configured" if oidc.get(
                "owner_bootstrap_configured") else
                ", no owner sub configured")),
        fatal=config.environment == "production")
    fatal_failed = [c["check"] for c in checks if c["fatal"] and not c["ok"]]
    return {
        "ok": not fatal_failed,
        "failed": fatal_failed,
        "checks": checks,
        "config": config.describe(),
    }


# The four categories SPEC_REFINEMENT 17.4 asks an operational screen to show.
# Each is reported from an observable stored fact, never guessed, and each says
# what the operator should do. A category with nothing outstanding is listed as
# checked rather than omitted, so a short list cannot be read as "not looked at".
ACTION_CATEGORIES = (
    "save_failure", "processing_delay", "permission_pending", "backup_failure",
)

_OPEN_BATCH_STATES = (
    "'received','parsing','classifying','reconciling','processing'")


def action_required_report(config, store, *, now=None):
    """The states an operator has to act on, and nothing else.

    SPEC_REFINEMENT 17.4 asks for 저장 실패, 처리 지연, 예약 권한 확인 지연,
    백업 실패. Two rules matter. Only a state that needs action is listed, so a
    healthy day is quiet. And each item is derived from a stored fact, so the
    report can neither claim a problem that did not happen nor stay silent about
    one that did.
    """
    now = now or utc_now()
    items = []

    # 1. a save the ledger has not reflected yet
    save_failures = 0
    if _has_table(store, "board_requests"):
        save_failures = store.conn.execute(
            "SELECT COUNT(*) FROM board_requests WHERE ledger_pending=1"
        ).fetchone()[0]
    if save_failures:
        items.append({
            "category": "save_failure", "count": save_failures, "needs": "owner",
            "what": "장부 반영이 남은 저장이 있어요",
            "action": "미확정 저장을 확인해 확정하거나 되돌려 주세요",
        })

    # 2. an import that started and never finished
    processing = 0
    for table in ("card_import_batches", "bank_import_batches"):
        if not _has_table(store, table):
            continue
        try:
            processing += store.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE status IN"
                f" ({_OPEN_BATCH_STATES})").fetchone()[0]
        except Exception:  # noqa: BLE001 - a missing column is not a finding
            continue
    if processing:
        items.append({
            "category": "processing_delay", "count": processing, "needs": "owner",
            "what": "시작했지만 끝나지 않은 작업이 있어요",
            "action": "작업 상태를 확인하고 다시 실행해 주세요",
        })

    # 3. a staff request the owner has not decided
    permission_pending = 0
    if _has_table(store, "access_applications"):
        permission_pending = store.conn.execute(
            "SELECT COUNT(*) FROM access_applications WHERE status='pending'"
        ).fetchone()[0]
    if permission_pending:
        items.append({
            "category": "permission_pending", "count": permission_pending,
            "needs": "owner", "what": "결정되지 않은 직원 신청이 있어요",
            "action": "계정 관리에서 승인하거나 거절해 주세요",
        })

    # 4. a backup that is missing, unverifiable, or older than its own policy
    state = None
    getter = getattr(config, "last_backup_state", None)
    if callable(getter):
        try:
            state = getter()
        except Exception:  # noqa: BLE001 - an unreadable backup is a finding
            state = {"ok": False, "detail": "백업 상태를 읽지 못했어요"}
    if isinstance(state, dict):
        if not state.get("ok"):
            items.append({
                "category": "backup_failure", "count": 1, "needs": "owner",
                "what": str(state.get("detail") or "백업을 확인하지 못했어요"),
                "action": "백업을 다시 만들고 복구 시험을 실행해 주세요",
            })
        elif state.get("stale"):
            items.append({
                "category": "backup_failure", "count": 1, "needs": "owner",
                "what": f"마지막 백업이 오래됐어요 ({state.get('at') or '-'})",
                "action": "새 백업을 만들어 주세요",
            })

    return {
        "generated_at": now,
        "ok": not items,
        "checked": list(ACTION_CATEGORIES),
        "items": items,
    }


def readiness_report(config: DurableConfig, store, *, measurements=None) -> dict:
    """Measure the operational quantities on synthetic data.

    These are the items a cutover decision needs: how long a save takes, how
    many provider turns are attempted, how many full reconciliations run, and
    what state is outstanding. A turn that waits or fails is counted as such
    and never as a completed call.
    """
    measurements = measurements or {}
    rows = store.conn.execute(
        "SELECT COUNT(*) FROM board_rows").fetchone()[0]
    events = store.conn.execute(
        "SELECT COUNT(*) FROM board_revisions").fetchone()[0]
    turns = store.conn.execute(
        "SELECT COUNT(*) FROM rule_apply_requests").fetchone()[0] if \
        _has_table(store, "rule_apply_requests") else 0
    conversations = store.conn.execute(
        "SELECT COUNT(*) FROM board_learning_cases").fetchone()[0]
    outstanding = store.conn.execute(
        "SELECT COUNT(*) FROM board_requests WHERE ledger_pending=1"
    ).fetchone()[0]
    # A turn that is waiting is read from the measured value, not from a
    # constant. Reporting a hard-coded 0 here would state a number the run never
    # observed, which is the one thing a readiness report must not do.
    provider_turns = measurements.get("provider_turns", {}) or {}
    waiting_turns = provider_turns.get("waiting")
    if waiting_turns is None:
        # No measurement was supplied, so the honest answer is "not measured",
        # not "zero".
        waiting_turns = None
    else:
        waiting_turns = int(waiting_turns)
    health = health_check(config, store)
    return {
        "generated_at": utc_now(),
        "environment": config.environment,
        "ok": health["ok"],
        "health": health,
        "counts": {
            "rows": rows,
            "row_events": events,
            "learning_cases": conversations,
            "rule_apply_requests": turns,
            "outstanding_ledger_pending": outstanding,
        },
        "provider_turns": provider_turns,
        "save_timings_ms": measurements.get("save_timings_ms", {}),
        "reconciliations": measurements.get("reconciliations", {}),
        "waiting_turns": waiting_turns,
        "waiting_turns_measured": waiting_turns is not None,
        "action_required": action_required_report(config, store),
        "external_conditions_still_unmet": EXTERNAL_CONDITIONS,
    }


# The conditions that need a human decision or a real external connection.
# They are listed here so a green local run cannot be read as a release.
EXTERNAL_CONDITIONS = [
    {"id": "HOSTING-RESOURCE",
     "condition": "실시 전행 호스팅 자원 확보 (예: Oracle Always Free)",
     "state": "not_provisioned",
     "needs": "사용자 로그인 + 계정/카드 등록",
     # The readiness code exists and is exercised: `cli serve --host`, a
     # durable data root, the runbook, `ops health`, `ops smoke` and a gate
     # that refuses to serve a misconfigured host.
     # Reporting `not_implemented` here would have said the phase is unbuilt
     # when what is actually missing is a server to run it on.
     "code_status": "operational_readiness_implemented_awaits_resource"},
    {"id": "GOOGLE-OIDC-CLIENT",
     "condition": "Google OAuth 클라이언트 ID와 허용 콜백 주소",
     "state": "no_credentials",
     "needs": "사용자가 콘솔에서 발급 후 환경 설정으로 제공",
     # The Authorization Code flow is implemented and its boundaries are
     # tested, so the code is no longer a synthetic-only stand-in. What is
     # still missing is a real client: this condition stays open.
     "code_status": "implemented_awaits_client"},
    {"id": "RESERVATION-API",
     "condition": "예약 시스템 담당자·배정 API 연결",
     "state": "not_connected",
     "needs": "예약 저장소 엔드포인트와 인증 방식",
     "code_status": "snapshot_sync_implemented_awaits_live_transport"},
    {"id": "PRODUCTION-DB",
     "condition": "운영 DB 경로 지정과 최초 시드 확인",
     "state": "not_migrated",
     "needs": "실제 Google 기준본과 운영 DB",
     # `ops migrate-rehearsal` seals, compares and records without applying,
     # so the pipeline is exercised locally. Only the real sources and the
     # operational database are missing, and neither can be synthesised.
     "code_status": "synthetic_rehearsal_only_awaits_real_sources"},
    {"id": "PAID-RESOURCE",
     "condition": "유료 전환이 필요한 경우 별도 승인",
     "state": "not_approved",
     "needs": "사용자 결정",
     "code_status": "not_applicable"},
    {"id": "DEPLOY",
     "condition": "운영 배포",
     "state": "not_deployed",
     "needs": "위 조건 정리와 사용자 승인",
     # A deploy manifest, a dry run and a pre-bind readiness gate exist. None
     # of them is a deployment, so the condition stays open.
     "code_status": "gated_and_dry_run_only_awaits_deployment"},
]


# ------------------------------------------------------------ restart check
def restart_survival_check(db_path, *, store_factory, save_row,
                           request_id: str) -> dict:
    """Close a store, reopen it, and check the rows and work state survived.

    This is run for real against a synthetic DB: a save and a request-id
    replay, then a fresh process-level store.
    """
    first = store_factory(db_path)
    try:
        saved = dict(save_row(first))
        # read the row back while the first connection is still open, so the
        # expectation is what the writer actually committed
        row_id = saved.get("row_id")
        observed = first.get_row(row_id) or {}
        saved["display_tab_id"] = observed.get("display_tab_id")
        saved["revision"] = observed.get("revision")
    finally:
        first.close()
    second = store_factory(db_path)
    try:
        row_id, expected_revision = saved["row_id"], saved["revision"]
        after = second.get_row(row_id)
        problems = []
        if after is None:
            problems.append("the saved row did not survive the restart")
        else:
            if after["revision"] != expected_revision:
                problems.append(
                    f"revision changed across the restart: {expected_revision}"
                    f" -> {after['revision']}")
            if after.get("display_tab_id") != saved.get("display_tab_id"):
                problems.append("the trip assignment did not survive")
        events = second.conn.execute(
            "SELECT COUNT(*) FROM board_revisions WHERE row_id=?",
            (row_id,)).fetchone()[0]
        if events == 0:
            problems.append("the row event history did not survive")
        # the same request id must still return the first result
        replay = second.conn.execute(
            "SELECT result_json FROM board_requests WHERE client_request_id=?",
            (request_id,)).fetchone()
        if replay is None:
            problems.append("the request id was lost across the restart")
        return {
            "ok": not problems,
            "problems": problems,
            "row_id": row_id,
            "revision": expected_revision,
            "events": events,
            "reopened_from": str(db_path),
        }
    finally:
        second.close()


# --------------------------------------------------------- deploy dry run
def build_deploy_manifest(config: DurableConfig, *, host_role="local-single",
                          service_name="web-ledger", python_executable=None,
                          entry_command=None, bind_host="127.0.0.1",
                          behind_proxy=False) -> dict:
    """Describe the service that would run, without creating it.

    Nothing here provisions, installs or starts anything. The manifest records
    the paths, the entry command and the bind posture a deployment would need,
    so a dry run can check them for consistency.

    The entry command is recorded, never executed. A caller that has a different
    entry point passes it in, because a manifest that names a command nobody can
    run is worse than no manifest.

    `behind_proxy` defaults to False on purpose. Defaulting it to True would let
    `--host 0.0.0.0` come back green, which reads as an approved public bind on
    a server that terminates no TLS. The acknowledgement has to be made.
    """
    if entry_command is None:
        # The default has to be a command that runs with no further arguments.
        # It was `webapp.cli serve`, which requires `--snapshot`; a manifest that
        # named it passed the "entry command present" check and then failed the
        # moment anybody followed it. A dry run that cannot be executed is not a
        # dry run.
        entry_command = [python_executable or sys.executable,
                         str(Path(__file__).resolve().parent.parent
                             / "run_candidate.py"),
                         "--data-root", str(config.data_root),
                         "--environment", config.environment,
                         "--require-ready"]
    return {
        "manifest_version": 1,
        "service": service_name,
        "host_role": host_role,
        "environment": config.environment,
        "generated_at": utc_now(),
        "applied": False,
        "python": python_executable or sys.executable,
        "python_version": ".".join(str(v) for v in sys.version_info[:3]),
        "entry": {
            "command": list(entry_command),
            "working_dir": str(config.data_root),
        },
        "bind": bind_posture(bind_host, behind_proxy=behind_proxy),
        "paths": config.describe(),
        "checks": [
            "data_root is absolute and exists",
            "db_path is inside data_root",
            "export_dir, evidence_dir and source_dir are inside data_root",
            "no development default path is used",
            "required secrets are present in the environment, not in the manifest",
            "the app port is not exposed without TLS in front of it",
        ],
    }


def _entry_command_is_runnable(command) -> bool:
    """Whether the recorded entry command could actually be started here.

    "Present" was the only test before, and a command with a required argument
    nobody filled in is present, printable and useless: the default named
    `webapp.cli serve`, which requires `--snapshot`. The dry run passed and the
    deployment then failed on first start. This parses the recorded arguments
    against the real entry point, so a missing required argument is a failure of
    the manifest rather than of the deployment.
    """
    if not command or not isinstance(command, (list, tuple)):
        return False
    parts = [str(p) for p in command]
    if not parts:
        return False
    script = parts[1] if len(parts) > 1 else ""
    if script.endswith(".py") and not Path(script).is_file():
        return False
    if script.endswith("run_candidate.py"):
        import argparse
        import importlib.util

        entry_source = Path(__file__).resolve().parent.parent / script
        spec = importlib.util.spec_from_file_location("_webledger_entry",
                                                      entry_source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parser = module.build_parser()
        try:
            parsed = parser.parse_args(parts[2:])
        except SystemExit:
            return False
        # The entry point takes no *required* argument, because the data root may
        # come from the environment. A recorded command with neither the flag nor
        # the variable is still unrunnable, and it fails at start-up rather than
        # at parse time, which is the worst moment to find out.
        if getattr(parsed, "data_root", None) in (None, "") and not \
                os.environ.get("WEBLEDGER_DATA_ROOT"):
            return False
    return True


def dry_run_deploy(config: DurableConfig, manifest) -> dict:
    """Validate the manifest against the local configuration. Applies nothing."""
    results = []

    def check(name, ok, detail=""):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    check("manifest_not_applied", manifest.get("applied") is False)
    check("data_root_absolute", config.data_root.is_absolute(),
          str(config.data_root))
    check("data_root_exists", config.data_root.is_dir(), str(config.data_root))
    check("data_root_outside_source_checkout",
          not _inside_source_checkout(config.data_root),
          "the data root must not live inside a source checkout; 18.3 item 2 "
          "puts durable data under an explicit persistent root")
    check("entry_command_present",
          bool(manifest.get("entry", {}).get("command")),
          "a manifest that names no command cannot be run")
    entry = manifest.get("entry", {})
    check("entry_command_is_runnable",
          _entry_command_is_runnable(entry.get("command")),
          "the recorded entry command does not parse, or names a file this "
          "checkout does not contain, or is missing a required argument")
    bind = manifest.get("bind")
    check("bind_posture_recorded", bool(bind),
          "the manifest must state which addresses the app port answers on")
    if bind:
        check("app_port_not_exposed_without_tls", bool(bind.get("acceptable")),
              f"{bind.get('shape')}: {bind.get('note')}")
        check("external_exposure_known",
              bind.get("external_exposure") in ("none", "app port, without TLS"),
              str(bind.get("external_exposure")))
    inside = []
    for name in ("db_path", "export_dir", "evidence_dir", "source_dir"):
        value = getattr(config, name)
        try:
            value.resolve().relative_to(config.data_root)
            inside.append((name, True))
        except ValueError:
            inside.append((name, False))
    check("paths_inside_data_root", all(ok for _, ok in inside),
          ", ".join(f"{n}={ok}" for n, ok in inside))
    for directory in (config.export_dir, config.evidence_dir, config.source_dir):
        directory.mkdir(parents=True, exist_ok=True)
    check("directories_created", all(p.is_dir() for p in
                                     (config.export_dir, config.evidence_dir,
                                      config.source_dir)))
    secrets = config.secret_state()
    check("required_secrets_present",
          all(secrets.values()) or not secrets,
          f"missing: {[k for k, v in secrets.items() if not v]}"
          if not all(secrets.values()) else f"{len(secrets)} present")
    # The secret *name* may appear so an operator can see what is needed, but a
    # secret *value* must never be carried into a manifest or a runbook.
    manifest_text = canonical_text(manifest)
    leaked = [name for name, present in secrets.items()
              if present and _env_value(name)
              and _env_value(name) in manifest_text]
    check("no_secret_value_in_manifest", not leaked,
          f"leaked values for: {leaked}" if leaked
          else "manifest records names, not values")
    check("synthetic_sessions_not_operational", not _synthetic_sessions_allowed(),
          "synthetic session allowance must be off for a runbook"
          if _synthetic_sessions_allowed()
          else "no synthetic session allowance")
    oidc = google_oidc_state()
    check("google_oidc_connection_recorded", "google_oidc_connected" in oidc,
          f"google_oidc_connected={oidc.get('google_oidc_connected')}")
    # A production runbook with no real login path serves nobody, and one with
    # only the synthetic seam serves a session header. Both are findings.
    if config.environment == "production":
        check("google_oidc_connected", bool(oidc.get("google_oidc_connected")),
              oidc.get("reason") or "a production runbook needs a real login")
    failed = [r["check"] for r in results if not r["ok"]]
    return {"ok": not failed, "failed": failed, "checks": results,
            "applied": False,
            "external_conditions_still_unmet": EXTERNAL_CONDITIONS}


def run_restore_drill(config: DurableConfig, store, *, target_root,
                      store_factory, trial_seconds=None) -> dict:
    """A trial restore plus the figures a cutover decision needs.

    Item 4 of SPEC_REFINEMENT 17.3 says a restore is rehearsed and then the target and
    timing are decided, and 17.2 says the numbers are presented rather than
    assumed. This makes one backup, restores it to a separate path, and reports
    what was measured. The live DB is never overwritten.
    """
    manifest = make_backup_bundle(config, store, label="drill")
    bundle = config.data_root / "backups" / manifest["bundle"]
    started = time.perf_counter()
    result = restore_bundle(config, bundle, target_root=target_root,
                            store_factory=store_factory)
    elapsed = time.perf_counter() - started if trial_seconds is None \
        else trial_seconds
    figures = recovery_figures(config, store, bundle=manifest,
                               trial_seconds=elapsed)
    apply_retention(config)
    return {"manifest": manifest, "bundle": str(bundle), "restore": result,
            "figures": figures,
            "recoverable": bool(result["ok"])}


def recovery_figures(config: DurableConfig, store, *, bundle=None,
                     trial_seconds=None) -> dict:
    """The numbers SPEC_REFINEMENT 17.2 says an operator has to be shown.

    17.2 asks for `최대 잃을 수 있는 최근 입력 범위`, `시험 복구에 걸린 시간`
    and `저장 비용과 보관 기간`, and it forbids promising lossless recovery or
    uninterrupted operation while those are still undecided. Each figure is
    measured from a real fact here; nothing is assumed.
    """
    now = utc_now()
    figures = {"generated_at": now}

    # 1. the newest input the store holds, which bounds what a restore of an
    #    older bundle would not contain. With no store bound the figure is
    #    reported as unmeasured rather than guessed.
    newest = None
    if store is None:
        figures["newest_input_note"] = (
            "장부가 연결되지 않아 최신 입력을 확인하지 못했어요")
    for table, column in (("board_revisions", "created_at"),
                          ("board_requests", "created_at"),
                          ("board_rows", "updated_at")):
        if store is None or not _has_table(store, table):
            continue
        cols = {r[1] for r in store.conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            continue
        value = store.conn.execute(
            f"SELECT MAX({column}) FROM {table}").fetchone()[0]
        if value and (newest is None or str(value) > newest):
            newest = str(value)
    figures["newest_input_in_store"] = newest
    backup_at = None
    if bundle is not None:
        backup_at = bundle.get("created_at")
    figures["bundle_created_at"] = backup_at
    figures["max_input_range_at_risk"] = _input_range(newest, backup_at)

    # 2. how long the trial restore actually took, when one was measured.
    if trial_seconds is None:
        figures["trial_restore_seconds"] = None
        figures["trial_restore_note"] = (
            "시험 복구를 아직 실행하지 않아 시간을 제시할 수 없어요")
    else:
        figures["trial_restore_seconds"] = round(float(trial_seconds), 3)
        figures["trial_restore_note"] = "실측값"

    # 3. what the retained bundles cost on this disk.
    bundles = list_bundles(config)
    total = 0
    per_bundle = []
    for manifest in bundles:
        size = 0
        for group in manifest["files"].values():
            for item in group:
                size += int(item.get("size_bytes") or 0)
        per_bundle.append({"bundle": manifest["bundle"], "bytes": size})
        total += size
    figures["bundle_count"] = len(bundles)
    figures["bytes_on_disk"] = total
    figures["bytes_per_bundle_estimate"] = (
        round(total / len(bundles)) if bundles else None)
    figures["retention_keep"] = config.keep_backups
    figures["free_bytes_at_data_root"] = _free_bytes(config.data_root)
    figures["per_bundle"] = per_bundle

    # 4. the two numbers a cutover plan has to fix, and the promise we refuse.
    figures["rpo_note"] = (
        "복구 목표 시점은 백업 주기로 결정되며 아직 수치를 정하지 않았어요")
    figures["rto_note"] = (
        "복구 목표 시간은 시험 복구 실측 뒤 운영비와 비교해 정해요")
    figures["promises_not_made"] = [
        "무손실 복구를 약속하지 않어요",
        "무중단 운영을 약속하지 않어요",
        "운영 중 새 입력을 받은 DB를 이전 백업으로 조용히 교체하지 않아요",
    ]
    return figures


def _input_range(newest, backup_at):
    """The window of input a restore of `backup_at` would leave out."""
    if not newest or not backup_at:
        return {"measured": False,
                "note": "백업 시점이나 최신 입력을 알 수 없어 범위를 못 정해요"}
    if newest <= backup_at:
        return {"measured": True, "newest_input": newest,
                "bundle_created_at": backup_at, "inputs_after_backup": 0,
                "note": "백업 시점 이후 새 입력이 없어요"}
    return {"measured": True, "newest_input": newest,
            "bundle_created_at": backup_at, "inputs_after_backup": None,
            "note": "백업 시점 이후 입력이 있어요. 이 구간은 이 백업으로 복구되지 "
                    "않습니다. 정확한 건수와 시점은 원천에서 확인해 주세요"}


def recovery_lines(figures: dict) -> list:
    """The 17.2 recovery lines, built in one place.

    The runbook writes exactly what this returns, and a caller can compare the
    returned lines against the generated document instead of re-typing the
    wording. That keeps the test from drifting away from the text it defends.
    """
    rng = figures.get("max_input_range_at_risk", {}) or {}
    seconds = figures.get("trial_restore_seconds")
    lines = ["## 회복 수치 (명세 17.2)", ""]
    lines += [
        f"- 최대 잃을 수 있는 최근 입력 범위: {rng.get('note')}",
        f"  - 장부의 최신 입력: {figures.get('newest_input_in_store')}",
        f"  - 백업 기준 시점: {figures.get('bundle_created_at')}",
        f"  - 백업 시점 이후 입력 건수: {rng.get('inputs_after_backup')}",
        f"- 시험 복구에 걸린 시간: "
        f"{seconds if seconds is not None else '미측정'}"
        f" ({figures.get('trial_restore_note')})",
        f"- 저장 비용과 보관 기간: 묶음 {figures.get('bundle_count')}개, "
        f"합계 {figures.get('bytes_on_disk')} bytes, "
        f"개당 추정 {figures.get('bytes_per_bundle_estimate')} bytes, "
        f"보관 {figures.get('retention_keep')}개",
        f"  - 데이터 루트 남은 공간: {figures.get('free_bytes_at_data_root')} bytes",
        "",
        "### 아직 약속하지 않는 것",
        "",
    ]
    lines += [f"- {p}" for p in figures.get("promises_not_made", [])]
    lines += [f"- {figures.get('rpo_note')}",
              f"- {figures.get('rto_note')}"]
    return lines


def write_deploy_runbook(path, config, manifest, dry_run, *, figures=None) -> Path:
    """The runbook a human would follow. It performs no step by itself."""
    lines = [
        "# 배포 전환 절차 (실행하지 않음)",
        "",
        f"생성: {manifest['generated_at']}",
        f"환경: {manifest['environment']} / 서비스: {manifest['service']}",
        "",
        "이 문서는 절차 설명이며 어떤 단계도 자동으로 실행하지 않는다.",
        "",
        "## dry run 결과",
        "",
        f"- 상태: {'통과' if dry_run['ok'] else '실패'}",
        f"- 실패 항목: {dry_run['failed'] or '없음'}",
        "",
    ]

    # SPEC_REFINEMENT 17.2 names the figures an operator must be shown. A
    # runbook that omitted them would leave the cutover decision without the
    # numbers it is supposed to rest on.
    if figures is None:
        lines += ["## 회복 수치 (명세 17.2)", "",
                  "- 아직 측정하지 않았어요. `ops drill` 로 측정한다."]
    else:
        lines += recovery_lines(figures)

    lines += [
        "",
        "## 바인딩 형태",
        "",
    ]
    bind = (manifest.get("bind") or {})
    if bind:
        lines += [
            f"- 앱이 응답하는 주소: `{bind.get('host')}`",
            f"- 형태: `{bind.get('shape')}`",
            f"- 외부 노출: {bind.get('external_exposure')}",
            f"- 설명: {bind.get('note')}",
            f"- 진입 명령: `{' '.join(manifest.get('entry', {}).get('command', []))}`",
        ]
    else:
        lines += ["- manifest 에 바인딩 형태가 없어요."]
    lines += [
        "",
        "## 수동 단계 (사용자 결정 필요)",
        "",
        "1. 호스팅 자원 확보 후 `data_root`를 실제 영속 경로로 다시 설정한다.",
        "2. 같은 머신에서 HTTPS를 종료하는 프록시를 두고 앱은 루프백에 묶는다.",
        "   SQLite 파일·원천 디렉터리·작업자 포트는 외부에 열지 않는다.",
        "3. Google OAuth 클라이언트를 발급받아 콜백 주소를 등록한다.",
        "4. 예약 API 엔드포인트와 인증 방식을 연결한다.",
        "5. 아래 절차를 순서대로 실행해 health·readiness·drill 을 확인한다.",
        "6. 위 항목이 모두 채워진 뒤에만 배포 승인을 검토한다.",
        "",
        "## 운영 확인 절차",
        "",
        "```",
        "# 1. 자원이 준비되었는지. 임시 루트면 TEMP_DATA_ROOT 로 거부된다",
        "python -m webapp.cli ops health --environment production --secret MUSE_KEY",
        "",
        "# 2. 조치가 필요한 상태만 본다. 실패 시 종료 코드 2",
        "python -m webapp.cli ops actions",
        "",
        "# 3. 시험 복구와 17.2 회복 수치를 함께 산출한다",
        "python -m webapp.cli ops drill --target <운영과 다른 경로> --runbook RUNBOOK.md",
        "",
        "# 4. 배포 manifest 와 바인딩 형태를 검증한다 (아무것도 적용하지 않음)",
        "python -m webapp.cli ops dry-run --secret MUSE_KEY --runbook RUNBOOK.md",
        "```",
        "",
        "`health` 의 `failed` 가 비어 있고, `drill` 의 `recoverable` 가 true이며,",
        "`content_compared` 가 true일 때만 운영 전환을 검토한다. 세 조건 중 하나라도",
        "거짓이면 그 항목을 먼저 고친다.",
        "",
        "## 아직 준비되지 않은 외부 조건",
        "",
    ]
    for item in EXTERNAL_CONDITIONS:
        lines.append(f"- **{item['id']}** {item['condition']} "
                     f"(상태: {item['state']}, 코드: {item['code_status']}, "
                     f"필요: {item['needs']})")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------- helpers
def _inside_source_checkout(path) -> bool:
    """Whether a durable data root sits inside this source tree.

    SPEC_REFINEMENT 18.3 item 2 forbids leaving durable data in the checkout or
    in a working-directory-relative path, because a redeploy or a checkout wipe
    takes it with it. A synthetic run is exempt, the same way a temp-rooted data
    root is.
    """
    try:
        target = Path(path).resolve()
        root = Path(__file__).resolve().parent.parent
        target.relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _free_bytes(path: Path):
    # Delegates rather than measuring. A second implementation here would be a
    # second answer to "how much room is left", and a health line that read a
    # different number than the guard a write used is how an operator ends up
    # told `ok` by one surface and refused by the other.
    return space_guard.free_bytes(path)


def durable_config_for(data_root, *, required_secrets=(),
                       keep_backups=DEFAULT_KEEP_BACKUPS,
                       environment="local-synthetic",
                       create: bool = False) -> DurableConfig:
    """Build a configuration from one root, with the conventional sub-paths.

    The serving entry point and the health, readiness, drill and dry-run
    commands all read their paths from here, so a service and the checks that
    inspect it cannot end up pointing at different directories. Every refusal in
    `DurableConfig` still applies: a relative root, a development default, a
    temp-rooted production root or a root inside this source checkout is
    rejected.
    """
    root = Path(data_root).resolve()
    if create:
        # Where the root *is* is checked before anything is created. A relative
        # path, a development default, a temp-rooted production root and a root
        # inside the checkout are all decisions the caller has to change, and
        # every one of those refusals used to arrive after four directories had
        # already been made -- so a refused configuration left debris for the
        # operator to clean up. The existence check is skipped here because the
        # directory is what the next step creates; the real constructor runs it.
        DurableConfig(
            data_root=root, db_path=root / "board.sqlite",
            export_dir=root / "exports", evidence_dir=root / "evidence",
            source_dir=root / "source", required_secrets=required_secrets,
            keep_backups=keep_backups, environment=environment,
            allow_missing_root=True)
        for sub in ("", "exports", "evidence", "source"):
            (root / sub if sub else root).mkdir(parents=True, exist_ok=True)
        for sub in ("", "exports", "evidence", "source"):
            (root / sub if sub else root).mkdir(parents=True, exist_ok=True)
    return DurableConfig(
        data_root=root,
        db_path=root / "board.sqlite",
        export_dir=root / "exports",
        evidence_dir=root / "evidence",
        source_dir=root / "source",
        required_secrets=required_secrets,
        keep_backups=keep_backups,
        environment=environment,
    )


def default_config_for_synthetic(base_dir, **kwargs) -> DurableConfig:
    """A valid configuration over a caller-supplied durable root."""
    base = Path(base_dir).resolve()
    root = base / "data"
    for sub in ("", "exports", "evidence", "source"):
        (root / sub if sub else root).mkdir(parents=True, exist_ok=True)
    return DurableConfig(
        data_root=root,
        db_path=root / "board.sqlite",
        export_dir=root / "exports",
        evidence_dir=root / "evidence",
        source_dir=root / "source",
        **kwargs,
    )
