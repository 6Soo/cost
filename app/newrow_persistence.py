"""Validated whole-file persistence for certain new rows only.

Scope: only rows that pass validation and are not already persisted
with matching content hash. Existing/manual/financial tables are never
modified by this module (tests use synthetic SQLite paths only).

Retry-safe: same input + same DB -> same result (skip or insert).
Explicit failure: validation, idempotency conflict, or audit failure
raises PersistenceError subclasses; never silent.
"""
import sqlite3, hashlib, json, os
from datetime import datetime, timezone

class PersistenceValidationError(ValueError): pass
class PersistenceConflictError(ValueError): pass
class PersistenceAuditError(ValueError): pass
class PersistenceError(Exception): pass

SCHEMA = """
CREATE TABLE IF NOT EXISTS persisted_rows (
  row_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  persisted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_persisted_rows_kind ON persisted_rows(kind);
CREATE TABLE IF NOT EXISTS audit_log (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  subject TEXT NOT NULL,
  action TEXT NOT NULL,
  row_ids TEXT NOT NULL,
  status TEXT NOT NULL
);
"""

def _sha256(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

def _now():
    return datetime.now(timezone.utc).isoformat()

class NewRowPersist:
    """Whole-file persistence of validated new rows to a dedicated SQLite DB."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure synthetic/test-only isolation: never default to production paths
        if db_path in ("", "/", "."):
            raise PersistenceValidationError("db_path must be explicit (synthetic/test isolation)")

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init(self, conn):
        for stmt in SCHEMA.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        conn.commit()

    def persist(self, rows, audit_subject="newrow-persist"):
        """Persist validated new rows; idempotent; audit; retry-safe."""
        if not isinstance(rows, list):
            raise PersistenceValidationError("rows must be list")
        # Validation: every row needs row_id, kind, and non-empty content
        for r in rows:
            if not isinstance(r, dict):
                raise PersistenceValidationError("each row must be dict")
            if not r.get("row_id") or not r.get("kind"):
                raise PersistenceValidationError("row missing row_id or kind")
            # Value/content must exist for hashing
            content = r.get("content") or r.get("value") or r.get("payload")
            if content is None:
                raise PersistenceValidationError("row missing content/value/payload")

        conn = self._conn()
        try:
            self._init(conn)
            inserted = []
            skipped = []
            conflicts = []
            for r in rows:
                rid = r["row_id"]
                kind = r["kind"]
                content = r.get("content") or r.get("value") or r.get("payload")
                content_sha = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
                # Idempotency check
                existing = conn.execute(
                    "SELECT content_sha256 FROM persisted_rows WHERE row_id=?", (rid,)
                ).fetchone()
                if existing:
                    if existing[0] == content_sha:
                        skipped.append(rid)
                        continue
                    else:
                        conflicts.append(rid)
                        raise PersistenceConflictError(
                            f"row {rid} exists with different content (idempotency conflict)")
                # Whole-file write (insert only new validated rows)
                conn.execute(
                    "INSERT INTO persisted_rows(row_id, kind, content_sha256, persisted_at) VALUES (?,?,?,?)",
                    (rid, kind, content_sha, _now()))
                inserted.append(rid)
            # Audit: append-only audit log for this operation
            row_ids_json = json.dumps({"inserted": inserted, "skipped": skipped, "conflicts": conflicts})
            status = "conflict" if conflicts else ("partial" if (inserted and skipped) else ("inserted" if inserted else "skipped"))
            conn.execute(
                "INSERT INTO audit_log(at, subject, action, row_ids, status) VALUES (?,?,?,?,?)",
                (_now(), audit_subject, "persist_newrows", row_ids_json, status))
            conn.commit()
            return {"inserted": inserted, "skipped": skipped, "status": status, "db_path": self.db_path}
        except (PersistenceConflictError, PersistenceValidationError):
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            raise PersistenceAuditError(f"audit/persist failure: {exc}") from exc
        finally:
            conn.close()
