from __future__ import annotations

import functools
import json
import sqlite3
import threading
from pathlib import Path

PAYMENT_TABLE_CANDIDATES = (
    "card_payments",
    "payments",
    "normalized_payments",
)
DECISION_TABLE_CANDIDATES = ("classification_decisions",)
GATE_ORDER = tuple(f"GATE{i}" for i in range(1, 8))


class ReadOnlyViolation(RuntimeError):
    pass


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _pick_table(conn, candidates):
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for name in candidates:
        if name in names:
            return name
    return None


class ReadOnlyCandidate:
    def __init__(self, db_path, descriptor=None):
        self.db_path = Path(db_path)
        self.descriptor = descriptor
        self._sha_before = None
        self._sha_after = None
        uri = f"file:{self.db_path.as_posix()}?mode=ro&immutable=1"
        self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA query_only=ON")
        from .contracts import sha256_file

        self._sha_before = sha256_file(self.db_path)

    @_locked
    def close(self):
        try:
            self.conn.execute("PRAGMA query_only=OFF")
            self.conn.execute("SELECT 1")
        except sqlite3.Error:
            pass
        finally:
            self.conn.execute("PRAGMA query_only=ON")
            self.conn.close()
            from .contracts import sha256_file

            self._sha_after = sha256_file(self.db_path)

    @property
    def unchanged_on_disk(self) -> bool:
        return self._sha_before == self._sha_after

    @_locked
    def assert_write_blocked(self):
        try:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS __wprobe__(x INTEGER)"
            )
        except sqlite3.Error as exc:
            return exc
        raise ReadOnlyViolation("write to read-only candidate succeeded")

    @_locked
    def table_names(self):
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [row[0] for row in rows]

    @_locked
    def integrity_check(self) -> str:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "unknown"

    @_locked
    def payments_summary(self):
        table = _pick_table(self.conn, PAYMENT_TABLE_CANDIDATES)
        if not table:
            return {"table": None, "count": 0, "sum_krw": 0}
        columns = {
            row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")
        }
        amount_col = "amount_krw" if "amount_krw" in columns else None
        count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        total = 0
        if amount_col:
            row = self.conn.execute(
                f"SELECT COALESCE(SUM({amount_col}), 0) FROM {table}"
            ).fetchone()
            total = int(row[0])
        return {"table": table, "count": int(count), "sum_krw": total}

    @_locked
    def queue_rows(self, limit=200):
        table = _pick_table(self.conn, PAYMENT_TABLE_CANDIDATES)
        if not table:
            return []
        columns = {
            row[1]: row[1]
            for row in self.conn.execute(f"PRAGMA table_info({table})")
        }
        wanted = [
            name
            for name in ("event_key", "occurred_on", "card4", "merchant", "amount_krw")
            if name in columns
        ]
        if not wanted:
            return []
        key_col = "event_key" if "event_key" in columns else "rowid"
        select = ", ".join(wanted + ([key_col] if key_col == "rowid" else []))
        sql = f"SELECT {select} FROM {table} ORDER BY occurred_on LIMIT ?"
        cursor = self.conn.execute(sql, (limit,))
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    @_locked
    def active_decisions(self):
        table = _pick_table(self.conn, DECISION_TABLE_CANDIDATES)
        if not table:
            return []
        columns = {
            row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")
        }
        if "superseded_by_id" in columns:
            where = "superseded_by_id IS NULL"
        elif "status" in columns:
            where = "status='active'"
        else:
            where = "1=1"
        fields = ["id"]
        for name in ("event_key", "account", "cost_type", "allocation_target", "vat_tag"):
            if name in columns:
                fields.append(name)
        cursor = self.conn.execute(
            f"SELECT {', '.join(fields)} FROM {table} WHERE {where}"
        )
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def gates_from_report(self):
        source = None
        if self.descriptor:
            report_path = self.descriptor.get("gate_report")
            if report_path and isinstance(report_path, dict):
                base = Path(self.descriptor.get("base_dir", "."))
                path = base / report_path["path"]
                with open(path, "r", encoding="utf-8") as handle:
                    source = json.load(handle)
        if not source:
            return []
        raw_gates = source.get("gates") or []
        rows = []
        for entry in raw_gates:
            gate = entry.get("gate") or entry.get("name")
            rows.append(
                {
                    "gate": gate,
                    "status": entry.get("status"),
                    "detail": entry.get("detail") or entry.get("reason"),
                }
            )
        readiness = source.get("readiness") or {}
        rows.append({"gate": "TRIAGE_PASS", "status": readiness.get("triage_pass")})
        rows.append({"gate": "shadow_ready", "status": readiness.get("shadow_ready")})
        rows.append({"gate": "release_ready", "status": readiness.get("release_ready")})
        order = {name: index for index, name in enumerate(GATE_ORDER)}
        rows.sort(key=lambda row: order.get(row["gate"], 99))
        return rows
