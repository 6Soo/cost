from __future__ import annotations

import datetime as _dt
import functools
import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from .contracts import (
    ACTIONS,
    AXES_SCHEMA_VERSION,
    CHAINING_ACTIONS,
    GENESIS_HASH,
    TERMINAL_ACTIONS,
    canonical_text,
    domain_event_hash,
    sha256_bytes,
    validate_axes,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decision_events (
    sequence_no INTEGER NOT NULL,
    stream_id TEXT NOT NULL,
    event_id TEXT PRIMARY KEY,
    supersedes_event_id TEXT,
    action TEXT NOT NULL,
    target_direct_event_key TEXT,
    expected_source_sha256 TEXT,
    base_candidate_semantic_sha256 TEXT,
    axes_json TEXT,
    axes_schema_version TEXT,
    evidence_refs_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    actor_local_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    client_request_id TEXT,
    prev_event_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    UNIQUE(stream_id, sequence_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_decision_client_request
    ON decision_events(client_request_id)
    WHERE client_request_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS ledger_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS decision_events_no_update
BEFORE UPDATE ON decision_events
BEGIN
    SELECT RAISE(ABORT, 'append_only_violation');
END;
CREATE TRIGGER IF NOT EXISTS decision_events_no_delete
BEFORE DELETE ON decision_events
BEGIN
    SELECT RAISE(ABORT, 'append_only_violation');
END;
"""


class LedgerError(RuntimeError):
    pass


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class ChainViolation(LedgerError):
    pass


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _atomic_write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def build_payload(fields: dict) -> dict:
    return {
        "stream": fields["stream_id"],
        "seq": fields["sequence_no"],
        "prev": fields["prev_event_hash"],
        "supersedes": fields["supersedes_event_id"],
        "action": fields["action"],
        "target": fields["target_direct_event_key"],
        "expected_source_sha256": fields["expected_source_sha256"],
        "base_semantic": fields["base_candidate_semantic_sha256"],
        "axes_schema": fields["axes_schema_version"],
        "axes": json.loads(fields["axes_json"]) if fields["axes_json"] else None,
        "evidence_refs": json.loads(fields["evidence_refs_json"]),
        "rationale": fields["rationale"],
        "actor": fields["actor_local_id"],
        "recorded_at": fields["recorded_at"],
    }


class OperatorLedger:
    def __init__(self, path, checkpoint_path=None, *, connection=None):
        self.path = Path(path)
        self.embedded = connection is not None
        self.checkpoint_path = None if self.embedded else Path(
            checkpoint_path or f"{self.path}.checkpoint.json"
        )
        self.conn = connection if connection is not None else sqlite3.connect(
            str(self.path),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def in_database(cls, connection, path, *, legacy_path=None):
        """같은 장부 트랜잭션에 감사 이력을 보존한다. 옛 DB는 읽기만 한다."""
        connection.executescript(SCHEMA_SQL)
        connection.executescript(TRIGGER_SQL)
        if legacy_path is not None and Path(legacy_path).is_file():
            with closing(sqlite3.connect(Path(legacy_path).resolve().as_uri() + '?mode=ro',
                                         uri=True)) as source:
                old = cls.__new__(cls)
                old.conn, old._lock = source, threading.RLock()
                if not old.verify_chain()['ok']:
                    raise ChainViolation('legacy audit chain is invalid')
                connection.execute('BEGIN IMMEDIATE')
                try:
                    for table, key in (('ledger_meta', 'key'), ('decision_events', 'event_id')):
                        columns = [r[1] for r in source.execute(f'PRAGMA table_info({table})')]
                        if not columns:
                            raise LedgerError('legacy audit schema is missing')
                        for row in source.execute(f'SELECT * FROM {table}'):
                            identity = row[columns.index(key)]
                            current = connection.execute(
                                f'SELECT {",".join(columns)} FROM {table} WHERE {key}=?',
                                (identity,)).fetchone()
                            if current is not None:
                                if tuple(current) != tuple(row):
                                    raise LedgerError('legacy audit content conflict')
                            else:
                                connection.execute(
                                    f'INSERT INTO {table} ({",".join(columns)}) VALUES '
                                    f'({",".join("?" for _ in columns)})', row)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        connection.execute("INSERT OR IGNORE INTO ledger_meta VALUES ('schema_version','1')")
        connection.execute("INSERT OR IGNORE INTO ledger_meta VALUES ('base_candidate_semantic_sha256','')")
        return cls(path, connection=connection)

    @classmethod
    def create(cls, path, base_candidate_semantic_sha256="", actor_local_id="local-operator"):
        path = Path(path)
        if path.exists():
            raise LedgerError(f"ledger already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQL)
            conn.executescript(TRIGGER_SQL)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO ledger_meta(key, value) VALUES ('schema_version', ?)",
                (str(1),),
            )
            conn.execute(
                "INSERT INTO ledger_meta(key, value) VALUES "
                "('base_candidate_semantic_sha256', ?)",
                (base_candidate_semantic_sha256,),
            )
            conn.execute(
                "INSERT INTO ledger_meta(key, value) VALUES ('created_at', ?)",
                (_utc_now(),),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
        ledger = cls(path)
        ledger._write_checkpoint()
        return ledger

    @_locked
    def meta(self, key):
        row = self.conn.execute(
            "SELECT value FROM ledger_meta WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    @_locked
    def close(self):
        self.conn.close()

    def _head(self, stream_id):
        row = self.conn.execute(
            "SELECT sequence_no, event_hash FROM decision_events "
            "WHERE stream_id=? ORDER BY sequence_no DESC LIMIT 1",
            (stream_id,),
        ).fetchone()
        return row if row else None

    @_locked
    def append(
        self,
        *,
        stream_id,
        action,
        target_direct_event_key=None,
        expected_source_sha256=None,
        base_candidate_semantic_sha256=None,
        axes=None,
        evidence_refs=None,
        rationale,
        actor_local_id="local-operator",
        client_request_id=None,
        supersedes_event_id=None,
        recorded_at=None,
    ):
        if action not in ACTIONS:
            raise LedgerError(f"illegal action: {action}")
        if not isinstance(rationale, str) or not rationale.strip():
            raise LedgerError("rationale is required")
        axes_json = None
        if axes is not None:
            validate_axes(axes)
            axes_json = canonical_text(axes)
        evidence_refs = list(evidence_refs or [])
        for ref in evidence_refs:
            if not isinstance(ref, dict) or not {"kind", "key", "sha256"} <= set(ref):
                raise LedgerError("evidence refs need kind/key/sha256")
        if client_request_id:
            existing = self.find_by_client_request(client_request_id)
            if existing:
                if self.embedded and any((
                    existing['stream_id'] != stream_id,
                    existing['action'] != action,
                    existing['target_direct_event_key'] != target_direct_event_key,
                    existing['axes_json'] != axes_json,
                    existing['evidence_refs_json'] != canonical_text(evidence_refs),
                    existing['rationale'] != rationale.strip(),
                    existing['actor_local_id'] != actor_local_id,
                )):
                    raise LedgerError('same audit request has different content')
                return existing, False
        base = base_candidate_semantic_sha256 or self.meta(
            "base_candidate_semantic_sha256"
        )
        head = self._head(stream_id)
        if head is None:
            seq = 1
            prev_hash = GENESIS_HASH
            if supersedes_event_id is not None:
                raise ChainViolation("first event of a stream cannot supersede")
            if action in CHAINING_ACTIONS:
                raise ChainViolation(
                    f"stream must start with 'propose', got {action}"
                )
        else:
            seq = head[0] + 1
            prev_hash = head[1]
            last_action = self.conn.execute(
                "SELECT action FROM decision_events WHERE stream_id=? AND "
                "sequence_no=?",
                (stream_id, head[0]),
            ).fetchone()[0]
            if last_action in TERMINAL_ACTIONS:
                raise ChainViolation("stream is terminal; start a new stream")
            if supersedes_event_id is None:
                supersedes_event_id = self.event_id_at(stream_id, head[0])
            else:
                prior = self.conn.execute(
                    "SELECT sequence_no FROM decision_events WHERE event_id=?",
                    (supersedes_event_id,),
                ).fetchone()
                if not prior or prior[0] != head[0]:
                    raise ChainViolation(
                        "supersedes_event_id must reference the current head"
                    )
        fields = {
            "sequence_no": seq,
            "stream_id": stream_id,
            "supersedes_event_id": supersedes_event_id,
            "action": action,
            "target_direct_event_key": target_direct_event_key,
            "expected_source_sha256": expected_source_sha256,
            "base_candidate_semantic_sha256": base,
            "axes_schema_version": AXES_SCHEMA_VERSION if axes_json else None,
            "axes_json": axes_json,
            "evidence_refs_json": canonical_text(evidence_refs),
            "rationale": rationale.strip(),
            "actor_local_id": actor_local_id,
            "recorded_at": recorded_at or _utc_now(),
            "client_request_id": client_request_id,
            "prev_event_hash": prev_hash,
        }
        payload = build_payload(fields)
        event_hash = domain_event_hash(payload)
        event_id = sha256_bytes((event_hash + ":" + prev_hash).encode("utf-8"))[:32]
        own_transaction = not self.conn.in_transaction
        try:
            if own_transaction:
                self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "INSERT INTO decision_events ("
                "sequence_no, stream_id, event_id, supersedes_event_id, action,"
                " target_direct_event_key, expected_source_sha256,"
                " base_candidate_semantic_sha256, axes_json,"
                " axes_schema_version, evidence_refs_json, rationale,"
                " actor_local_id, recorded_at, client_request_id,"
                " prev_event_hash, event_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    seq,
                    stream_id,
                    event_id,
                    supersedes_event_id,
                    action,
                    target_direct_event_key,
                    expected_source_sha256,
                    base,
                    axes_json,
                    fields["axes_schema_version"],
                    fields["evidence_refs_json"],
                    fields["rationale"],
                    actor_local_id,
                    fields["recorded_at"],
                    client_request_id,
                    prev_hash,
                    event_hash,
                ),
            )
            if own_transaction:
                self.conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if own_transaction:
                self.conn.execute("ROLLBACK")
            raise LedgerError(f"insert rejected: {exc}") from exc
        except sqlite3.Error:
            if own_transaction:
                self.conn.execute("ROLLBACK")
            raise
        event = self.get_event(event_id)
        self._write_checkpoint()
        return event, True

    @_locked
    def attach_evidence(self, *, stream_id, added_refs, rationale, **kwargs):
        head = self._head(stream_id)
        if head is None:
            raise ChainViolation("cannot attach to empty stream")
        head_row = self.get_event_by_seq(stream_id, head[0])
        merged = list(json.loads(head_row["evidence_refs_json"]))
        for ref in added_refs:
            if not {"kind", "key", "sha256"} <= set(ref):
                raise LedgerError("evidence refs need kind/key/sha256")
            if ref not in merged:
                merged.append(ref)
        return self.append(
            stream_id=stream_id,
            action="attach_evidence",
            target_direct_event_key=head_row["target_direct_event_key"],
            expected_source_sha256=head_row["expected_source_sha256"],
            axes=json.loads(head_row["axes_json"])
            if head_row["axes_json"]
            else None,
            evidence_refs=merged,
            rationale=rationale,
            supersedes_event_id=None,
            **kwargs,
        )

    @_locked
    def find_by_client_request(self, client_request_id):
        row = self.conn.execute(
            "SELECT * FROM decision_events WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    @_locked
    def event_id_at(self, stream_id, sequence_no):
        row = self.conn.execute(
            "SELECT event_id FROM decision_events WHERE stream_id=? AND "
            "sequence_no=?",
            (stream_id, sequence_no),
        ).fetchone()
        return row[0] if row else None

    @_locked
    def get_event(self, event_id):
        row = self.conn.execute(
            "SELECT * FROM decision_events WHERE event_id=?", (event_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    @_locked
    def get_event_by_seq(self, stream_id, sequence_no):
        row = self.conn.execute(
            "SELECT * FROM decision_events WHERE stream_id=? AND sequence_no=?",
            (stream_id, sequence_no),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    @_locked
    def all_events(self):
        rows = self.conn.execute(
            "SELECT * FROM decision_events ORDER BY stream_id, sequence_no"
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @_locked
    def streams(self):
        rows = self.conn.execute(
            "SELECT DISTINCT stream_id FROM decision_events ORDER BY stream_id"
        ).fetchall()
        return [row[0] for row in rows]

    def _row_to_dict(self, row):
        names = [d[0] for d in self.conn.execute(
            "SELECT * FROM decision_events LIMIT 0"
        ).description]
        return dict(zip(names, row))

    @_locked
    def verify_chain(self):
        problems = []
        events = self.all_events()
        by_stream = {}
        for event in events:
            by_stream.setdefault(event["stream_id"], []).append(event)
        for stream_id, stream_events in sorted(by_stream.items()):
            expected_seq = 1
            expected_prev = GENESIS_HASH
            for event in stream_events:
                if event["sequence_no"] != expected_seq:
                    problems.append(
                        f"{stream_id}: sequence gap at {event['sequence_no']}"
                    )
                    break
                if event["prev_event_hash"] != expected_prev:
                    problems.append(f"{stream_id}:{event['sequence_no']} broken prev link")
                payload = build_payload(event)
                recomputed = domain_event_hash(payload)
                if recomputed != event["event_hash"]:
                    problems.append(
                        f"{stream_id}:{event['sequence_no']} hash mismatch"
                    )
                expected_prev = event["event_hash"]
                expected_seq += 1
        heads = self._checkpoint_heads_from_db()
        return {"ok": not problems, "problems": problems, "heads": heads}

    def _checkpoint_heads_from_db(self):
        heads = {}
        for stream_id in self.streams():
            head = self._head(stream_id)
            if head:
                heads[stream_id] = {
                    "sequence_no": head[0],
                    "event_hash": head[1],
                }
        return heads

    @_locked
    def _write_checkpoint(self):
        if self.embedded:
            return
        doc = {
            "version": 1,
            "db_file": self.path.name,
            "updated_at_utc": _utc_now(),
            "heads": self._checkpoint_heads_from_db(),
        }
        _atomic_write_json(self.checkpoint_path, doc)
        return doc

    @_locked
    def verify_checkpoint(self):
        if self.embedded:
            return {"ok": self.verify_chain()["ok"], "status": "same_database"}
        db_heads = self._checkpoint_heads_from_db()
        if not self.checkpoint_path.is_file():
            return {
                "status": "missing_checkpoint",
                "ok": False,
                "db_heads": db_heads,
            }
        with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
            cp = json.load(handle)
        cp_heads = cp.get("heads", {})
        for stream_id, info in cp_heads.items():
            db_info = db_heads.get(stream_id)
            if db_info is None:
                return {
                    "status": "mismatch_stream_missing_in_db",
                    "ok": False,
                    "stream": stream_id,
                }
            if info["sequence_no"] > db_info["sequence_no"]:
                return {
                    "status": "mismatch",
                    "ok": False,
                    "stream": stream_id,
                    "reason": "checkpoint ahead of database",
                }
            if info["sequence_no"] < db_info["sequence_no"]:
                return {
                    "status": "checkpoint_stale",
                    "ok": True,
                    "repairable": True,
                    "stream": stream_id,
                }
            if info["event_hash"] != db_info["event_hash"]:
                return {
                    "status": "mismatch",
                    "ok": False,
                    "stream": stream_id,
                    "reason": "head hash differs at equal sequence",
                }
        for stream_id in db_heads:
            if stream_id not in cp_heads:
                return {
                    "status": "checkpoint_stale",
                    "ok": True,
                    "repairable": True,
                    "stream": stream_id,
                }
        return {"status": "ok", "ok": True, "heads": db_heads}

    @_locked
    def event_hash_at(self, stream_id, sequence_no):
        row = self.conn.execute(
            "SELECT event_hash FROM decision_events WHERE stream_id=? AND "
            "sequence_no=?",
            (stream_id, sequence_no),
        ).fetchone()
        return row[0] if row else None

    @_locked
    def repair_checkpoint(self):
        chain = self.verify_chain()
        if not chain["ok"]:
            raise ChainViolation(f"refusing repair with broken chain: {chain['problems']}")
        self._write_checkpoint()
        return self.verify_checkpoint()

    @_locked
    def backup(self, backup_path):
        backup_path = Path(backup_path)
        if backup_path.resolve() == self.path.resolve():
            raise LedgerError('backup must not replace the original database')
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if backup_path.exists():
            backup_path.unlink()
        target = sqlite3.connect(str(backup_path))
        try:
            self.conn.backup(target)
        finally:
            target.close()
        if self.embedded:
            return {"backup_db": str(backup_path), "backup_checkpoint": None}
        backup_cp = Path(f"{backup_path}.checkpoint.json")
        _atomic_write_json(backup_cp, self._load_checkpoint())
        return {"backup_db": str(backup_path), "backup_checkpoint": str(backup_cp)}

    def _load_checkpoint(self):
        with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @_locked
    def materialize(self):
        active = {}
        resolved_out = []
        for stream_id in self.streams():
            head = self._head(stream_id)
            event = self.get_event_by_seq(stream_id, head[0])
            if event["action"] in TERMINAL_ACTIONS:
                resolved_out.append({"stream_id": stream_id, "action": event["action"]})
                continue
            active[stream_id] = {
                "event_id": event["event_id"],
                "action": event["action"],
                "target": event["target_direct_event_key"],
                "axes": json.loads(event["axes_json"]) if event["axes_json"] else None,
                "evidence_refs": json.loads(event["evidence_refs_json"]),
                "recorded_at": event["recorded_at"],
            }
        return {"active": active, "resolved_out": resolved_out}
