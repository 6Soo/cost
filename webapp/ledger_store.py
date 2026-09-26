"""Phase 2 row save store (synthetic working DB only).

Single write path: one SQLite file holds row projections, revisions,
idempotency records, and manual overrides. Every save also appends an
audit event to the existing append-only operator ledger. The row
transaction commits first; if the ledger append then fails, the request
is marked ledger-pending and replayed on the next save or verify call.
No physical deletes: cancel only discards the client draft.

Allowed fields by source kind (contract):
  card expense: display_tab_id, item, description, operator_note
  direct income: display_tab_id, income kind fields, customer link, memo
  bank income: customer/trip link and permitted business fields only
Card occurred_on, amount_krw, sign, source keys, merchant text are
rejected at the API boundary when present in a save request.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from . import ledger_board as board
from .operator_ledger import LedgerError, OperatorLedger

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS board_rows (
    row_id TEXT PRIMARY KEY,
    row_kind TEXT NOT NULL,
    display_tab_id TEXT,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS board_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    prev_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    event_id TEXT,
    change_mode TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'save',
    reverts_event_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS board_requests (
    client_request_id TEXT PRIMARY KEY,
    row_id TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    ledger_pending INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS board_manual_overrides (
    row_id TEXT NOT NULL,
    field TEXT NOT NULL,
    event_id TEXT NOT NULL,
    PRIMARY KEY (row_id, field)
);
CREATE TABLE IF NOT EXISTS board_learning_cases (
    case_id TEXT PRIMARY KEY,
    row_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    dialog_state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS income_corrections (
    correction_id TEXT PRIMARY KEY,
    row_id TEXT NOT NULL,
    corrected_amount_krw INTEGER NOT NULL,
    corrected_occurred_on TEXT,
    row_revision INTEGER,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS income_source_links (
    row_id TEXT NOT NULL,
    bank_batch_id TEXT NOT NULL,
    bank_row_index INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (row_id, bank_batch_id, bank_row_index)
);
CREATE TABLE IF NOT EXISTS trip_tabs (
    tab_id TEXT PRIMARY KEY,
    display_key TEXT NOT NULL,
    destination TEXT NOT NULL DEFAULT '',
    starts_on TEXT NOT NULL DEFAULT '',
    ends_on TEXT NOT NULL DEFAULT '',
    prepared_on TEXT NOT NULL DEFAULT '',
    prepared_by_name TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS trip_tab_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tab_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    change_kind TEXT NOT NULL,
    prev_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trip_tab_requests (
    client_request_id TEXT PRIMARY KEY,
    tab_id TEXT NOT NULL,
    expected_revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    ledger_pending INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS income_allocations (
    allocation_id TEXT PRIMARY KEY,
    source_row_id TEXT NOT NULL,
    customer_id TEXT,
    customer_name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    display_tab_id TEXT,
    income_kind TEXT NOT NULL DEFAULT 'deposit',
    amount_krw INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    source_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS income_allocation_requests (
    client_request_id TEXT PRIMARY KEY,
    source_row_id TEXT NOT NULL,
    expected_source_revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    ledger_pending INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger_outbox (
    outbox_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_direct_event_key TEXT,
    rationale TEXT NOT NULL,
    actor_local_id TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    relayed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS income_allocation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    allocation_id TEXT NOT NULL,
    source_row_id TEXT NOT NULL,
    prev_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    reverts_event_id TEXT NOT NULL DEFAULT ''
);
"""

SYNTHETIC_OWNER_NAME = "테스트 소유자"


def _seoul_today() -> str:
    import datetime as _dt

    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=9)).date().isoformat()

CARD_EDITABLE = ("display_tab_id", "item", "description", "operator_note")
CARD_READONLY = (
    "occurred_on", "amount_krw", "source_event_id", "source_kind",
    "merchant", "reservation_no",
)
INCOME_EDITABLE = (
    "display_tab_id", "income_kind", "customer_id", "customer_name",
    "nickname", "occurred_on", "amount_krw", "operator_note",
)
ALLOCATION_ROW_EDITABLE = (
    "customer_id", "customer_name", "nickname", "display_tab_id", "income_kind",
)

ERRORS = (
    "EDIT_CONFLICT",
    "REQUEST_ID_REUSED",
    "REQUEST_ID_REUSE_UNVERIFIED",
    "FIELD_READ_ONLY",
    "INVALID_VALUE",
    "TARGET_NOT_ASSIGNABLE",
    "DELETE_PREVIEW_STALE",
)


class SaveError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _valid_date(value) -> bool:
    import datetime as _dt
    import re

    if not isinstance(value, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _normalize_create_input(fields: dict) -> dict:
    return json.loads(_canonical({
        k: (None if v is None else v) for k, v in (fields or {}).items()
    }))


def _ensure_correction_columns(conn) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(income_corrections)").fetchall()}
    if "corrected_occurred_on" not in cols:
        conn.execute("ALTER TABLE income_corrections ADD COLUMN corrected_occurred_on TEXT")
    if "row_revision" not in cols:
        conn.execute("ALTER TABLE income_corrections ADD COLUMN row_revision INTEGER")
    rev_cols = {row[1] for row in conn.execute("PRAGMA table_info(board_revisions)").fetchall()}
    if "kind" not in rev_cols:
        conn.execute("ALTER TABLE board_revisions ADD COLUMN kind TEXT NOT NULL DEFAULT 'save'")
    if "reverts_event_id" not in rev_cols:
        conn.execute("ALTER TABLE board_revisions ADD COLUMN reverts_event_id TEXT NOT NULL DEFAULT ''")


def _row_to_record(kind: str, row: dict) -> dict:
    record = {
        "row_id": row["row_id"],
        "row_kind": kind,
        "display_tab_id": row["display_tab_id"],
        "revision": 1,
    }
    if kind == "expense":
        record.update(
            occurred_on=row["occurred_on"],
            item=row["item"],
            description=row["description"],
            service_period=row.get("service_period", ""),
            reservation_no=row.get("reservation_no", ""),
            evidence_type=row.get("evidence_type", ""),
            amount_krw=row["amount_krw"],
            source_kind=row["source_kind"],
            source_event_id=row["source_event_id"],
            classification_state=row.get("classification_state", ""),
            classification_basis=row.get("classification_basis", ""),
            operator_note="",
        )
    else:
        record.update(
            occurred_on=row["occurred_on"],
            customer_id=row["customer_id"],
            customer_name=row["customer_name"],
            nickname=row.get("nickname", ""),
            income_kind=row["income_kind"],
            event_type=row.get("event_type", "receipt"),
            amount_krw=row["amount_krw"],
            source_kind=row["source_kind"],
            source_event_id=row["source_event_id"],
            operator_note="",
        )
    return record


class LedgerStore:
    """Synthetic working-DB save path with operator-ledger audit trail."""

    def __init__(self, path, ledger: OperatorLedger | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        first_create = not self.path.exists()
        self.conn = sqlite3.connect(
            str(self.path), timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA_SQL)
        _ensure_correction_columns(self.conn)
        if first_create:
            self._seed()
        self._ensure_trips()
        operator_path = self.path.with_suffix(".operator.sqlite")
        if not operator_path.exists():
            OperatorLedger.create(str(operator_path))
        self.ledger = ledger or OperatorLedger(operator_path)

    def _ensure_trips(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM trip_tabs").fetchone()[0]
        if count:
            return
        today = _seoul_today()
        for trip in board.TRIPS:
            self.conn.execute(
                "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
                " ends_on, prepared_on, prepared_by_name, archived, deleted, revision)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (trip["tab_id"], trip["display_key"], trip.get("destination", ""),
                 trip.get("starts_on", ""), trip.get("ends_on", ""),
                 today, SYNTHETIC_OWNER_NAME, 0, 0, 1),
            )
        self.conn.commit()

    def _seed(self) -> None:
        for row in board.EXPENSES:
            record = _row_to_record("expense", dict(row))
            self.conn.execute(
                "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                " VALUES (?,?,?,?,?)",
                (record["row_id"], "expense", record["display_tab_id"], 1, _canonical(record)),
            )
        for row in board.INCOMES:
            record = _row_to_record("income", dict(row))
            self.conn.execute(
                "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                " VALUES (?,?,?,?,?)",
                (record["row_id"], "income", record["display_tab_id"], 1, _canonical(record)),
            )

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def get_row(self, row_id: str):
        row = self.conn.execute(
            "SELECT row_kind, display_tab_id, revision, payload_json FROM board_rows WHERE row_id=?",
            (row_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[3])
        payload["row_id"] = row_id
        payload["row_kind"] = row[0]
        payload["display_tab_id"] = row[1]
        payload["revision"] = row[2]
        return payload

    def list_tab_rows(self, tab_id: str | None):
        split = self.split_source_ids()
        if tab_id is None:
            rows = self.conn.execute(
                "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
                " WHERE display_tab_id IS NULL ORDER BY row_id"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT row_id, row_kind, display_tab_id, revision, payload_json FROM board_rows"
                " WHERE display_tab_id=? ORDER BY row_id",
                (tab_id,),
            ).fetchall()
        out = []
        for row_id, kind, display, revision, payload_json in rows:
            if row_id in split:
                continue
            payload = json.loads(payload_json)
            payload["row_id"] = row_id
            payload["row_kind"] = kind
            payload["display_tab_id"] = display
            payload["revision"] = revision
            out.append(payload)
        try:
            alloc_rows = self.conn.execute(
                "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
                " display_tab_id, income_kind, amount_krw, active, source_revision"
                " FROM income_allocations WHERE active=1"
                " AND ((? IS NULL AND display_tab_id IS NULL) OR display_tab_id=?)"
                " ORDER BY allocation_id",
                (tab_id, tab_id),
            ).fetchall()
        except Exception:
            alloc_rows = []
        for raw in alloc_rows:
            alloc = self._allocation_dict(raw)
            source = self.get_row(alloc["source_row_id"])
            if source is None:
                continue
            out.append(self._allocation_display_row(alloc, source))
        if tab_id is None:
            for source_id in sorted(split):
                source = self.get_row(source_id)
                if source is None:
                    continue
                if self.split_remainder(source_id) != 0:
                    out.append(self._remainder_display_row(source))
        return out

    def list_history(self, row_id: str):
        try:
            rows = self.conn.execute(
                "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
                " client_request_id, kind, reverts_event_id FROM board_revisions"
                " WHERE row_id=? ORDER BY revision",
                (row_id,),
            ).fetchall()
            return [
                {
                    "revision": r[0], "prev": json.loads(r[1]), "new": json.loads(r[2]),
                    "event_id": r[3], "change_mode": r[4], "actor": r[5],
                    "created_at": r[6], "client_request_id": r[7],
                    "kind": r[8] or "save", "reverts_event_id": r[9] or "",
                }
                for r in rows
            ]
        except Exception:
            rows = self.conn.execute(
                "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
                " client_request_id FROM board_revisions WHERE row_id=? ORDER BY revision",
                (row_id,),
            ).fetchall()
            return [
                {
                    "revision": r[0], "prev": json.loads(r[1]), "new": json.loads(r[2]),
                    "event_id": r[3], "change_mode": r[4], "actor": r[5],
                    "created_at": r[6], "client_request_id": r[7],
                    "kind": "save", "reverts_event_id": "",
                }
                for r in rows
            ]

    def _latest_entry(self, row_id: str):
        history = self.list_history(row_id)
        return history[-1] if history else None

    def _correction_for_revision(self, row_id: str, revision: int):
        for corr in self.list_corrections(row_id):
            if corr.get("row_revision") == revision:
                return corr
        return None

    def _plan_snapshots(self, entry: dict):
        cid = entry.get("client_request_id") or ""
        for table in ("income_allocation_requests", "board_requests"):
            try:
                row = self.conn.execute(
                    f"SELECT result_json FROM {table} WHERE client_request_id=?",
                    (cid,),
                ).fetchone()
            except Exception:
                continue
            if not row:
                continue
            stored = json.loads(row[0])
            res = stored.get("result") or {}
            if "alloc_before" in res or "alloc_after" in res:
                return res.get("alloc_before") or [], res.get("alloc_after") or []
        return None, None

    def _restore_allocation_set(self, *, source_row_id: str, new_revision: int,
                                before: list) -> None:
        keep = {a["allocation_id"] for a in before}
        for item in before:
            exists = self.conn.execute(
                "SELECT allocation_id FROM income_allocations WHERE allocation_id=?",
                (item["allocation_id"],),
            ).fetchone()
            if exists:
                self.conn.execute(
                    "UPDATE income_allocations SET customer_id=?, customer_name=?, nickname=?,"
                    " display_tab_id=?, income_kind=?, amount_krw=?, active=1,"
                    " source_revision=? WHERE allocation_id=?",
                    (item.get("customer_id"), item.get("customer_name", ""),
                     item.get("nickname", ""), item.get("display_tab_id"),
                     item.get("income_kind", "deposit"), item["amount_krw"],
                     new_revision, item["allocation_id"]),
                )
            else:
                self.conn.execute(
                    "INSERT INTO income_allocations(allocation_id, source_row_id, customer_id,"
                    " customer_name, nickname, display_tab_id, income_kind, amount_krw,"
                    " active, source_revision, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (item["allocation_id"], source_row_id, item.get("customer_id"),
                     item.get("customer_name", ""), item.get("nickname", ""),
                     item.get("display_tab_id"), item.get("income_kind", "deposit"),
                     item["amount_krw"], 1, new_revision, _utc_now(), ""),
                )
        for (aid,) in self.conn.execute(
            "SELECT allocation_id FROM income_allocations"
            " WHERE source_row_id=? AND active=1",
            (source_row_id,),
        ).fetchall():
            if aid not in keep:
                self.conn.execute(
                    "UPDATE income_allocations SET active=0, source_revision=?"
                    " WHERE allocation_id=?",
                    (new_revision, aid),
                )

    def revert_status(self, row_id: str) -> dict:
        current = self.get_row(row_id)
        if current is None:
            return {"revertible": False, "reason": "없는 행이에요"}
        target = self._latest_entry(row_id)
        if target is None or target["prev"] == {}:
            return {"revertible": False, "reason": "최신 내역을 다시 확인해 주세요"}
        kind = target.get("kind") or "save"
        if kind == "revert":
            return {"revertible": False, "reason": "이미 되돌린 수정입니다"}
        if kind in ("alloc", "alloc-revert", "allocation-edit", "allocation-revert"):
            return {"revertible": False, "reason": "직전 변경은 배분 수정이라 행 되돌릴 수 없어요"}
        if kind in ("link", "move", "create"):
            return {"revertible": False, "reason": "최신 내역을 다시 확인해 주세요"}
        if kind == "correct-bank" or self._correction_for_revision(row_id, target["revision"]):
            corrs = self.list_corrections(row_id)
            idx = next((i for i, c in enumerate(corrs)
                        if c.get("row_revision") == target["revision"]), None)
            if idx is None:
                return {"revertible": False, "reason": "최신 내역을 다시 확인해 주세요"}
            prev_corr = corrs[idx - 1] if idx > 0 else None
            after = {
                "corrected_amount_krw": (prev_corr["corrected_amount_krw"]
                                         if prev_corr else current["amount_krw"]),
                "corrected_occurred_on": (prev_corr.get("corrected_occurred_on")
                                          if prev_corr else None),
            }
            return {"revertible": True, "reason": None,
                    "target_revision": target["revision"], "after": after,
                    "before": {"corrected_amount_krw": self.display_amount(current),
                               "corrected_occurred_on": self.display_occurred_on(current)}}
        prev_vals = target["prev"]
        after = {f: prev_vals.get(f) for f in prev_vals if f in current and current.get(f) != prev_vals.get(f)}
        dest = prev_vals.get("display_tab_id")
        if dest is not None:
            trip = self.get_trip(dest)
            if trip is None or trip["deleted"]:
                return {"revertible": False, "reason": "이전 여행이 삭제됐습니다",
                        "target_revision": target["revision"]}
        return {"revertible": True, "reason": None,
                "target_revision": target["revision"], "after": after,
                "before": {f: current.get(f) for f in after}}

    def revert_row(self, *, row_id: str, expected_revision: int,
                   client_request_id: str, actor: str = "owner") -> dict:
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            # Check if this is an allocation ID (starts with "alc-")
            if row_id.startswith("alc-"):
                return self._revert_allocation(
                    allocation_id=row_id, expected_source_revision=expected_revision,
                    client_request_id=client_request_id, actor=actor)
            current = self.get_row(row_id)
            if current is None:
                raise SaveError("INVALID_VALUE", "없는 행이에요")
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if stored["row_id"] != row_id:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if stored.get("expected_revision") == expected_revision:
                    return stored["result"]
                status = self.revert_status(row_id)
                want_changes = ({"revert": status["target_revision"]}
                                if status["revertible"] else None)
                if stored.get("changes") != want_changes:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return stored["result"]
            if current["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            status = self.revert_status(row_id)
            if not status["revertible"]:
                raise SaveError("INVALID_VALUE", status["reason"])
            target_revision = status["target_revision"]
            target = next(h for h in self.list_history(row_id)
                          if h["revision"] == target_revision)
            want_changes = {"revert": target_revision}
            new_revision = current["revision"] + 1
            created_at = _utc_now()
            kind = target.get("kind") or "save"
            is_bank_correction = (
                kind == "correct-bank"
                or self._correction_for_revision(row_id, target_revision) is not None
            )
            correction_id = None
            restored_correction = None
            restore_plan_before = None
            if is_bank_correction:
                after = status["after"]
                restored_correction = {
                    "corrected_amount_krw": after["corrected_amount_krw"],
                    "corrected_occurred_on": after["corrected_occurred_on"],
                }
                correction_id = f"corr-revert-{client_request_id}"
                before, applied = self._plan_snapshots(target)
                if (before is not None and applied is not None
                        and (before or applied)):
                    restore_plan_before = before
                restored = dict(current)
            else:
                source = current.get("source_kind", "")
                if current["row_kind"] == "expense" and source in ("카드", ""):
                    editable = CARD_EDITABLE
                elif current["row_kind"] == "expense":
                    editable = CARD_EDITABLE + ("occurred_on", "amount_krw")
                elif source == "은행":
                    editable = ("customer_id", "customer_name", "nickname",
                                "display_tab_id", "operator_note", "income_kind")
                else:
                    editable = INCOME_EDITABLE
                restored = dict(current)
                for field in editable:
                    if field in target["prev"] and restored.get(field) != target["prev"].get(field):
                        restored[field] = target["prev"][field]
                self._validate(current, {f: restored[f] for f in editable
                                         if f in target["prev"]
                                         and restored.get(f) != current.get(f)})
            restored["revision"] = new_revision
            target_event = target.get("event_id") or ""
            outbox_id = f"ledger-{client_request_id}"
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 행이에요")
                if fresh[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                if is_bank_correction:
                    self.conn.execute(
                        "INSERT INTO income_corrections(correction_id, row_id,"
                        " corrected_amount_krw, corrected_occurred_on, row_revision,"
                        " reason, actor, created_at, client_request_id)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (correction_id, row_id, restored_correction["corrected_amount_krw"],
                         restored_correction["corrected_occurred_on"], new_revision,
                         "직전 수정 되돌리기", actor, created_at,
                         f"{client_request_id}:bank"),
                    )
                if restore_plan_before is not None:
                    self._restore_allocation_set(
                        source_row_id=row_id, new_revision=new_revision,
                        before=restore_plan_before)
                cursor = self.conn.execute(
                    "UPDATE board_rows SET display_tab_id=?, revision=?, payload_json=?"
                    " WHERE row_id=? AND revision=?",
                    (restored["display_tab_id"], new_revision,
                     _canonical(restored), row_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
                    " event_id, change_mode, actor, created_at, client_request_id,"
                    " kind, reverts_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (row_id, new_revision, _canonical(current), _canonical(restored),
                     "", "exception", actor, created_at, client_request_id,
                     "revert", target_event),
                )
                for field in restored:
                    if field in ("row_id", "row_kind", "revision") or field not in current:
                        continue
                    if restored.get(field) != current.get(field):
                        self.conn.execute(
                            "INSERT OR REPLACE INTO board_manual_overrides(row_id, field, event_id)"
                            " VALUES (?,?,?)",
                            (row_id, field, ""),
                        )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="correct", target=current.get("source_event_id"),
                    rationale=f"직전 수정 되돌리기 {row_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, expected_revision,
                     _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                 "changes": want_changes, "change_mode": "exception",
                                 "source_event_id": current.get("source_event_id"),
                                 "actor": actor, "new_revision": new_revision,
                                 "result": {"outcome": "reverted", "row_id": row_id,
                                            "revision": new_revision, "event_id": None,
                                            "reverted_revision": target_revision,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM board_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        retry_stored = json.loads(found[0])
                        if retry_stored.get("changes") == want_changes:
                            return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if retry_stored.get("changes") == want_changes:
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            stored = json.loads(
                self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()[0]
            )
            return stored["result"]

    def _revert_allocation(self, *, allocation_id: str, expected_source_revision: int,
                           client_request_id: str, actor: str = "owner") -> dict:
        return self._apply_allocation_row_change(
            api="allocation-revert", allocation_id=allocation_id,
            expected_source_revision=expected_source_revision,
            client_request_id=client_request_id, changes=None, actor=actor,
        )

    def linked_bank_row_ids(self) -> set:
        """Bank income rows attached as evidence to a direct income.

        R06: 연결된 은행 행은 두 번째 확정 수입으로 합산하지 않는다.
        """
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT r.stable_key FROM income_source_links l"
                " JOIN bank_import_rows r ON r.batch_id=l.bank_batch_id"
                " AND r.row_index=l.bank_row_index"
            ).fetchall()
        except Exception:
            return set()
        return {f"bnk-{key[:16]}" for (key,) in rows}

    def tab_totals(self, tab_id: str) -> dict:
        income = 0
        expense = 0
        linked = self.linked_bank_row_ids()
        split = self.split_source_ids()
        for (row_id, kind, display, payload) in self.conn.execute(
            "SELECT row_id, row_kind, display_tab_id, payload_json FROM board_rows"
        ).fetchall():
            if display != tab_id:
                continue
            if row_id in linked or row_id in split:
                continue
            record = json.loads(payload)
            record["row_id"] = row_id
            amount = self.display_amount(record)
            if kind == "income":
                income += amount
            else:
                expense += amount
        try:
            alloc_rows = self.conn.execute(
                "SELECT amount_krw FROM income_allocations"
                " WHERE active=1 AND display_tab_id=?",
                (tab_id,),
            ).fetchall()
        except Exception:
            alloc_rows = []
        income += sum(r[0] for r in alloc_rows)
        return {"income": income, "expense": expense, "profit": income - expense}

    def find_bank_candidates(self, row_id: str) -> list:
        """R06: 직접 수입과 날짜·금액·입금자가 같은 미연결 은행 행을 후보로."""
        current = self.get_row(row_id)
        if current is None or current["row_kind"] != "income":
            return []
        if current.get("source_kind") == "은행":
            return []
        linked = self.linked_bank_row_ids()
        out = []
        for (bid, kind, display, payload) in self.conn.execute(
            "SELECT row_id, row_kind, display_tab_id, payload_json FROM board_rows"
            " WHERE row_kind='income'"
        ).fetchall():
            if bid == row_id or bid in linked:
                continue
            record = json.loads(payload)
            if record.get("source_kind") != "은행":
                continue
            if (str(record.get("occurred_on", "")) != str(current.get("occurred_on", ""))
                    or record.get("amount_krw") != current.get("amount_krw")):
                continue
            want = str(current.get("customer_name") or "")
            if want and str(record.get("customer_name") or "") != want:
                continue
            record["row_id"] = bid
            record["row_kind"] = kind
            record["display_tab_id"] = display
            out.append(record)
        return out

    def _validate(self, current: dict, changes: dict) -> None:
        kind = current["row_kind"]
        source = current.get("source_kind", "")
        if kind == "expense" and source in ("카드", ""):
            for field in changes:
                if field in CARD_READONLY:
                    raise SaveError("FIELD_READ_ONLY", f"{field}는 고정 필드라 바꿀 수 없어요")
                if field not in CARD_EDITABLE:
                    raise SaveError("INVALID_VALUE", f"허용하지 않은 필드예요: {field}")
        elif kind == "expense":
            for field in changes:
                if field not in CARD_EDITABLE + ("occurred_on", "amount_krw"):
                    raise SaveError("INVALID_VALUE", f"허용하지 않은 필드예요: {field}")
        else:
            if source == "은행":
                for field in changes:
                    if field not in ("customer_id", "customer_name", "nickname",
                                     "display_tab_id", "operator_note", "income_kind"):
                        raise SaveError("FIELD_READ_ONLY", f"{field}는 바꿀 수 없어요")
            else:
                for field in changes:
                    if field not in INCOME_EDITABLE:
                        raise SaveError("FIELD_READ_ONLY", f"{field}는 바꿀 수 없어요")
                if "amount_krw" in changes or "occurred_on" in changes:
                    try:
                        linked_direct = {
                            r[0] for r in self.conn.execute(
                                "SELECT DISTINCT row_id FROM income_source_links"
                            ).fetchall()
                        }
                    except Exception:
                        linked_direct = set()
                    if current.get("row_id") in linked_direct:
                        raise SaveError(
                            "FIELD_READ_ONLY",
                            "은행 원천 연결 뒤에는 은행 정정 경로를 써 주세요")
        if "display_tab_id" in changes:
            from . import ledger_board as board

            target = changes["display_tab_id"]
            valid = board.valid_tab_ids() | {None}
            if target not in valid:
                raise SaveError("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
        if "amount_krw" in changes:
            value = changes["amount_krw"]
            if isinstance(value, bool) or not isinstance(value, int):
                raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
        if "occurred_on" in changes:
            if not _valid_date(changes["occurred_on"]):
                raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
        if "income_kind" in changes:
            if changes["income_kind"] not in ("deposit", "balance", "additional"):
                raise SaveError("INVALID_VALUE", "입금 종류를 골라 주세요")

    def save(
        self,
        *,
        row_id: str,
        expected_revision: int,
        client_request_id: str,
        change_mode: str,
        changes: dict,
        actor: str = "owner",
    ) -> dict:
        if change_mode not in ("exception", "rule_change"):
            raise SaveError("INVALID_VALUE", "변경 이유를 예외 사항과 규칙 변경 중에서 골라 주세요")
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            changes = dict(changes)
            if changes.get("display_tab_id") == "unclassified":
                changes["display_tab_id"] = None
            existing = self.conn.execute(
                "SELECT result_json, row_id, expected_revision FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if stored["row_id"] != row_id or stored["expected_revision"] != expected_revision or stored["changes"] != changes or stored["change_mode"] != change_mode:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return stored["result"]
            current = self.get_row(row_id)
            if current is None:
                raise SaveError("INVALID_VALUE", "없는 행이에요")
            if current["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            if (current["row_kind"] == "income" and row_id in self.split_source_ids()
                    and any(f != "occurred_on" for f in changes)):
                raise SaveError("FIELD_READ_ONLY", "배분된 입금은 배분 편집에서 원금과 함께 조정해 주세요")
            self._validate(current, changes)
            prev = dict(current)
            new = dict(current)
            for field, value in changes.items():
                new[field] = value
            if all(new.get(k) == prev.get(k) for k in changes):
                result = {
                    "outcome": "unchanged", "row_id": row_id,
                    "revision": current["revision"], "event_id": None,
                    "affected_tab_ids": sorted({t for t in (prev["display_tab_id"], new["display_tab_id"]) if t}),
                    "learning_case_id": None, "request_id": client_request_id,
                }
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute(
                        "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                        " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                        (client_request_id, row_id, expected_revision,
                         _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                     "changes": changes, "change_mode": change_mode, "result": result}),
                         0, _utc_now()),
                    )
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
                return result
            new["revision"] = current["revision"] + 1
            created_at = _utc_now()
            source_event_id = current.get("source_event_id")
            business_changed = any(
                field != "operator_note" and new.get(field) != prev.get(field)
                for field in changes
            )
            learning_case_id = (
                f"case-{client_request_id}"
                if change_mode == "rule_change" and business_changed
                else None
            )
            # R01: revision 확인은 쓰기 트랜잭션 안에서 다시 수행한다.
            # 행·revision·수동 고정·학습 사례·요청 결과·정본 사건(outbox)을
            # 같은 트랜잭션에 넣고, 별도 DB 복제는 COMMIT 뒤 내구성 기록에서 한다.
            outbox_id = f"ledger-{client_request_id}"
            ledger_action = "propose" if current["revision"] == 1 else "correct"
            ledger_rationale = f"행 저장 {row_id} revision {new['revision']} ({change_mode})"
            outer_txn = self.conn.in_transaction
            if not outer_txn:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 행이에요")
                if fresh[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                cursor = self.conn.execute(
                    "UPDATE board_rows SET display_tab_id=?, revision=?, payload_json=?"
                    " WHERE row_id=? AND revision=?",
                    (new["display_tab_id"], new["revision"], _canonical(new),
                     row_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row_id, new["revision"], _canonical(prev), _canonical(new), "",
                     change_mode, actor, created_at, client_request_id),
                )
                for field in changes:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO board_manual_overrides(row_id, field, event_id)"
                        " VALUES (?,?,?)",
                        (row_id, field, ""),
                    )
                if learning_case_id:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO board_learning_cases(case_id, row_id, event_id,"
                        " dialog_state, created_at) VALUES (?,?,?,?,?)",
                        (learning_case_id, row_id, "", "waiting", created_at),
                    )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action=ledger_action, target=source_event_id,
                    rationale=ledger_rationale, actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, expected_revision,
                     _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                 "changes": changes, "change_mode": change_mode,
                                 "source_event_id": source_event_id,
                                 "actor": actor,
                                 "new_revision": new["revision"],
                                 "result": {"outcome": "saved", "row_id": row_id,
                                            "revision": new["revision"], "event_id": None,
                                            "affected_tab_ids": sorted(
                                                {t for t in (prev["display_tab_id"],
                                                             new["display_tab_id"]) if t}),
                                            "learning_case_id": learning_case_id,
                                            "request_id": client_request_id,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                if not outer_txn:
                    self.conn.execute("COMMIT")
            except SaveError as exc:
                if not outer_txn:
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM board_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        retry_stored = json.loads(found[0])
                        if (retry_stored["row_id"] == row_id
                                and retry_stored["expected_revision"] == expected_revision
                                and retry_stored["changes"] == changes
                                and retry_stored["change_mode"] == change_mode):
                            return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                if not outer_txn:
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if (retry_stored["row_id"] == row_id
                            and retry_stored["expected_revision"] == expected_revision
                            and retry_stored["changes"] == changes
                            and retry_stored["change_mode"] == change_mode):
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                if not outer_txn:
                    self.conn.execute("ROLLBACK")
                raise
            if outer_txn:
                return {"outcome": "saved", "row_id": row_id, "revision": new["revision"],
                        "event_id": None,
                        "affected_tab_ids": sorted(
                            {t for t in (prev["display_tab_id"], new["display_tab_id"]) if t}),
                        "learning_case_id": learning_case_id, "request_id": client_request_id,
                        "ledger_pending": True}
            self._relay_outbox([outbox_id])
            # Link event_id to revision / overrides / learning case, and
            # finalize the request record.
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {
                "outcome": "saved", "row_id": row_id, "revision": new["revision"],
                "event_id": None, "affected_tab_ids": sorted(
                    {t for t in (prev["display_tab_id"], new["display_tab_id"]) if t}),
                "learning_case_id": learning_case_id, "request_id": client_request_id,
                "ledger_pending": True,
            }

    def import_row(self, *, row_id: str, fields: dict, batch_id: str,
                   client_request_id: str, actor: str = "owner") -> dict:
        """Insert one imported event as a new board row (revision 1).

        Reuses the single write path: row insert, revision record,
        operator-ledger audit event, and idempotency record.
        """
        record = {
            "row_id": row_id,
            "row_kind": "expense",
            "display_tab_id": fields["display_tab_id"],
            "revision": 1,
            "occurred_on": fields["occurred_on"],
            "item": "숙박비" if "AGODA" in str(fields.get("merchant", "")).upper() else "기타",
            "description": str(fields.get("merchant", "")),
            "service_period": "",
            "reservation_no": "",
            "evidence_type": "카드",
            "amount_krw": fields["amount_krw"],
            "source_kind": "카드",
            "source_event_id": fields.get("approval_no") or row_id,
            "classification_state": fields.get("classification_state", ""),
            "classification_basis": f"가져오기 {batch_id} {fields.get('event_kind', '')}",
            "operator_note": "",
        }
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                return json.loads(existing[0])["result"]
            if self.get_row(row_id) is not None:
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            want = {"import": batch_id}
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                if self.conn.execute(
                    "SELECT row_id FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone():
                    raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
                self.conn.execute(
                    "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                    " VALUES (?,?,?,?,?)",
                    (row_id, "expense", record["display_tab_id"], 1, _canonical(record)),
                )
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row_id, 1, _canonical({}), _canonical(record), "",
                     "exception", actor, created_at, client_request_id),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="propose", target=record["source_event_id"],
                    rationale=f"가져오기 {batch_id} 행 {row_id}", actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, 1,
                     _canonical({"row_id": row_id, "expected_revision": 1,
                                 "changes": want, "change_mode": "exception",
                                 "source_event_id": record["source_event_id"],
                                 "actor": actor, "new_revision": 1,
                                 "result": {"outcome": "saved", "row_id": row_id,
                                            "revision": 1, "event_id": None,
                                            "affected_tab_ids": sorted(
                                                {t for t in (record["display_tab_id"],) if t}),
                                            "learning_case_id": None,
                                            "request_id": client_request_id,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM board_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        retry_stored = json.loads(found[0])
                        if retry_stored.get("changes") == want:
                            return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if retry_stored.get("changes") == want:
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {
                "outcome": "saved", "row_id": row_id, "revision": 1,
                "event_id": None, "affected_tab_ids": sorted(
                    {t for t in (record["display_tab_id"],) if t}),
                "learning_case_id": None, "request_id": client_request_id,
                "ledger_pending": True,
            }

    def _latest_correction(self, row_id: str):
        try:
            return self.conn.execute(
                "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
                " row_revision, reason, actor, created_at, client_request_id"
                " FROM income_corrections WHERE row_id=? ORDER BY rowid DESC LIMIT 1",
                (row_id,),
            ).fetchone()
        except Exception:
            return None

    def display_amount(self, row: dict) -> int:
        """Current display amount: latest bank correction wins, else stored amount."""
        if row.get("source_kind") != "은행":
            return row["amount_krw"]
        correction = self._latest_correction(row["row_id"])
        return correction[1] if correction else row["amount_krw"]

    def display_occurred_on(self, row: dict) -> str:
        """Current display date: latest bank date correction wins, else stored date."""
        if row.get("source_kind") != "은행":
            return row["occurred_on"]
        correction = self._latest_correction(row["row_id"])
        if correction and correction[2]:
            return correction[2]
        return row["occurred_on"]

    def projected(self, row: dict) -> dict:
        """R05: 화면·합계·출력이 함께 쓰는 현재 장부 투영."""
        out = dict(row)
        out["display_amount_krw"] = self.display_amount(row)
        out["display_occurred_on"] = self.display_occurred_on(row)
        return out

    def list_corrections(self, row_id: str):
        try:
            rows = self.conn.execute(
                "SELECT correction_id, corrected_amount_krw, corrected_occurred_on,"
                " row_revision, reason, actor, created_at"
                " FROM income_corrections WHERE row_id=? ORDER BY rowid",
                (row_id,),
            ).fetchall()
        except Exception:
            rows = self.conn.execute(
                "SELECT correction_id, corrected_amount_krw, reason, actor, created_at"
                " FROM income_corrections WHERE row_id=? ORDER BY rowid",
                (row_id,),
            ).fetchall()
            return [
                {"correction_id": r[0], "corrected_amount_krw": r[1],
                 "corrected_occurred_on": None, "row_revision": None,
                 "reason": r[2], "actor": r[3], "created_at": r[4]}
                for r in rows
            ]
        return [
            {"correction_id": r[0], "corrected_amount_krw": r[1],
             "corrected_occurred_on": r[2], "row_revision": r[3],
             "reason": r[4], "actor": r[5], "created_at": r[6]}
            for r in rows
        ]

    @staticmethod
    def _normalize_plan_for_compare(plan) -> list:
        return sorted(
            (str(p.get("allocation_id") or ""),
             str(p.get("customer_id") or ""), str(p.get("customer_name") or ""),
             str(p.get("nickname") or ""), str(p.get("display_tab_id") or ""),
             str(p.get("income_kind") or ""), p.get("amount_krw"))
            for p in (plan or [])
        )

    def correct_bank_income(self, *, row_id: str, corrected_amount_krw: int,
                            corrected_occurred_on=None, reason: str,
                            client_request_id: str, expected_revision: int,
                            allocation_plan=None, actor: str = "owner") -> dict:
        if isinstance(corrected_amount_krw, bool) or not isinstance(corrected_amount_krw, int):
            raise SaveError("INVALID_VALUE", "정정 금액은 정수 원화로 입력해 주세요")
        if corrected_occurred_on is not None and not _valid_date(corrected_occurred_on):
            raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
        if not reason or not reason.strip():
            raise SaveError("INVALID_VALUE", "정정 이유가 필요해요")
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            current = self.get_row(row_id)
            if current is None or current["row_kind"] != "income":
                raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
            if current.get("source_kind") != "은행":
                raise SaveError("INVALID_VALUE", "은행 원천 행만 정정 기록을 써요")
            has_allocs = bool(self.active_allocations(row_id))
            reflected = self.display_amount(current)
            want_plan = list(allocation_plan) if allocation_plan is not None else None
            if has_allocs and (corrected_amount_krw != reflected or want_plan is not None):
                if want_plan is None:
                    raise SaveError("INVALID_VALUE", "배분된 입금은 배분안을 함께 제출해 주세요")
                want_plan = self._validate_allocation_plan(
                    current, corrected_amount_krw, want_plan)
                if sum(p["amount_krw"] for p in want_plan) != corrected_amount_krw:
                    raise SaveError("INVALID_VALUE", "배분 합계와 정정액이 달라요")
            elif want_plan is not None:
                want_plan = self._validate_allocation_plan(
                    current, corrected_amount_krw, want_plan)
                if sum(p["amount_krw"] for p in want_plan) != corrected_amount_krw:
                    raise SaveError("INVALID_VALUE", "배분 합계와 정정액이 달라요")
            existing = self.conn.execute(
                "SELECT corrected_amount_krw, corrected_occurred_on, row_revision"
                " FROM income_corrections WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                if (existing[0] != corrected_amount_krw
                        or (existing[1] or None) != (corrected_occurred_on or None)):
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                stored = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if stored:
                    prev_result = json.loads(stored[0])["result"]
                    if want_plan is not None and self._normalize_plan_for_compare(
                            prev_result.get("applied_plan")) != self._normalize_plan_for_compare(want_plan):
                        raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                    return prev_result
                return {"row_id": row_id, "revision": existing[2],
                        "corrected_amount_krw": existing[0],
                        "corrected_occurred_on": existing[1], "reused": True}
            if current["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            new_revision = current["revision"] + 1
            date_value = corrected_occurred_on or None
            correction_id = f"corr-{client_request_id}"
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            alloc_before = self.active_allocations(row_id)
            alloc_after = []
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
                if fresh[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT correction_id FROM income_corrections WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                self.conn.execute(
                    "INSERT INTO income_corrections(correction_id, row_id, corrected_amount_krw,"
                    " corrected_occurred_on, row_revision, reason, actor, created_at,"
                    " client_request_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (correction_id, row_id, corrected_amount_krw, date_value,
                     new_revision, reason.strip(), actor, created_at, client_request_id),
                )
                if want_plan is not None:
                    _, alloc_after = self._apply_allocation_plan(
                        source_row_id=row_id, new_revision=new_revision,
                        plan=want_plan, client_request_id=client_request_id,
                        created_at=created_at, actor=actor)
                cursor = self.conn.execute(
                    "UPDATE board_rows SET revision=? WHERE row_id=? AND revision=?",
                    (new_revision, row_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id,"
                    " kind, reverts_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'')",
                    (row_id, new_revision, _canonical(current), _canonical(current),
                     "", "exception", actor, created_at, client_request_id, "correct-bank"),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="correct", target=current.get("source_event_id"),
                    rationale=f"은행 정정 {row_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, expected_revision,
                     _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                 "changes": {"correct-bank": {
                                     "amount": corrected_amount_krw,
                                     "occurred_on": date_value}},
                                 "change_mode": "exception",
                                 "source_event_id": current.get("source_event_id"),
                                 "actor": actor, "new_revision": new_revision,
                                 "result": {"correction_id": correction_id, "row_id": row_id,
                                            "revision": new_revision, "event_id": None,
                                            "corrected_amount_krw": corrected_amount_krw,
                                            "corrected_occurred_on": date_value,
                                            "applied_plan": alloc_after,
                                            "alloc_before": alloc_before,
                                            "reused": False,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    return self._replay_correction_request(
                        client_request_id, corrected_amount_krw, date_value, want_plan)
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                return self._replay_correction_request(
                    client_request_id, corrected_amount_krw, date_value, want_plan)
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return {**final, "correction_id": correction_id, "reused": False}
            stored = json.loads(
                self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()[0]
            )
            return stored["result"]

    def _replay_correction_request(self, client_request_id: str, corrected_amount_krw: int,
                                   date_value, want_plan) -> dict:
        row = self.conn.execute(
            "SELECT corrected_amount_krw, corrected_occurred_on FROM income_corrections"
            " WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if row is None:
            raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
        if row[0] != corrected_amount_krw or (row[1] or None) != (date_value or None):
            raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
        stored = self.conn.execute(
            "SELECT result_json FROM board_requests WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if stored:
            prev_result = json.loads(stored[0])["result"]
            if want_plan is not None and self._normalize_plan_for_compare(
                    prev_result.get("applied_plan")) != self._normalize_plan_for_compare(want_plan):
                raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
            return prev_result
        raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")

    def link_bank_source(self, *, row_id: str, bank_batch_id: str, bank_row_index: int,
                           expected_revision: int, client_request_id: str,
                           actor: str = "owner") -> dict:
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            existing_request = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing_request:
                stored = json.loads(existing_request[0])
                want = {"link-bank": {"bank_batch_id": bank_batch_id,
                                      "bank_row_index": bank_row_index}}
                if (stored["row_id"] != row_id
                        or stored["expected_revision"] != expected_revision
                        or stored["changes"] != want):
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return stored["result"]
            current = self.get_row(row_id)
            if current is None or current["row_kind"] != "income":
                raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
            if current.get("source_kind") != "직접 입력":
                raise SaveError("INVALID_VALUE", "직접 입력 행에만 은행 원천을 연결해요")
            if current["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            batch = self.conn.execute(
                "SELECT batch_id FROM bank_import_batches WHERE batch_id=?",
                (bank_batch_id,),
            ).fetchone()
            bank_row = self.conn.execute(
                "SELECT stable_key, raw_json, status FROM bank_import_rows"
                " WHERE batch_id=? AND row_index=?",
                (bank_batch_id, bank_row_index),
            ).fetchone()
            if batch is None or bank_row is None:
                raise SaveError("INVALID_VALUE", "없는 은행 원천이에요")
            other = self.conn.execute(
                "SELECT row_id FROM income_source_links WHERE bank_batch_id=?"
                " AND bank_row_index=? AND row_id!=?",
                (bank_batch_id, bank_row_index, row_id),
            ).fetchone()
            if other is not None:
                raise SaveError("INVALID_VALUE", "이미 다른 입금에 연결된 원천이에요")
            already = self.conn.execute(
                "SELECT row_id FROM income_source_links WHERE row_id=?"
                " AND bank_batch_id=? AND bank_row_index=?",
                (row_id, bank_batch_id, bank_row_index),
            ).fetchone()
            if already is not None:
                return {"row_id": row_id, "bank_batch_id": bank_batch_id,
                        "bank_row_index": bank_row_index, "reused": True,
                        "revision": current["revision"]}
            raw_fields = json.loads(bank_row[1])
            from .income_ledger import classify_bank_row as _classify_bank
            ok, payload = _classify_bank(raw_fields)
            if not ok:
                raise SaveError("INVALID_VALUE", "연결할 수 없는 은행 행이에요")
            if (str(payload["occurred_on"]) != str(current.get("occurred_on", ""))
                    or payload["amount_krw"] != current.get("amount_krw")
                    or str(payload["payer_name"]) != str(current.get("customer_name") or "")):
                raise SaveError("INVALID_VALUE", "다른 입금의 원천은 연결할 수 없어요")
            new_revision = current["revision"] + 1
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
                if fresh[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    want_dup = {"link-bank": {"bank_batch_id": bank_batch_id,
                                              "bank_row_index": bank_row_index}}
                    if (dup_stored["row_id"] == row_id
                            and dup_stored["expected_revision"] == expected_revision
                            and dup_stored["changes"] == want_dup):
                        return dup_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                self.conn.execute(
                    "INSERT INTO income_source_links(row_id, bank_batch_id,"
                    " bank_row_index, created_at) VALUES (?,?,?,?)",
                    (row_id, bank_batch_id, bank_row_index, created_at),
                )
                cursor = self.conn.execute(
                    "UPDATE board_rows SET revision=? WHERE row_id=? AND revision=?",
                    (new_revision, row_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id,"
                    " kind, reverts_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'')",
                    (row_id, new_revision, _canonical(current), _canonical(current),
                     "", "exception", actor, created_at, client_request_id, "link"),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="correct", target=current.get("source_event_id"),
                    rationale=f"은행 원천 연결 {row_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, expected_revision,
                     _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                 "changes": {"link-bank": {
                                     "bank_batch_id": bank_batch_id,
                                     "bank_row_index": bank_row_index}},
                                 "change_mode": "exception",
                                 "source_event_id": current.get("source_event_id"),
                                 "actor": actor, "new_revision": new_revision,
                                 "result": {"row_id": row_id, "revision": new_revision,
                                            "bank_batch_id": bank_batch_id,
                                            "bank_row_index": bank_row_index,
                                            "event_id": None, "reused": False,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    want_retry = {"link-bank": {"bank_batch_id": bank_batch_id,
                                                "bank_row_index": bank_row_index}}
                    if (retry_stored["row_id"] == row_id
                            and retry_stored["expected_revision"] == expected_revision
                            and retry_stored["changes"] == want_retry):
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {"row_id": row_id, "revision": new_revision,
                    "bank_batch_id": bank_batch_id, "bank_row_index": bank_row_index,
                    "event_id": None, "reused": False, "ledger_pending": True}

    @staticmethod
    def _trip_dict(row) -> dict:
        return {
            "tab_id": row[0], "display_key": row[1], "destination": row[2],
            "starts_on": row[3], "ends_on": row[4], "prepared_on": row[5],
            "prepared_by_name": row[6], "archived": bool(row[7]),
            "deleted": bool(row[8]), "revision": row[9],
        }

    def list_trips(self, include_archived: bool = False) -> list:
        rows = self.conn.execute(
            "SELECT tab_id, display_key, destination, starts_on, ends_on,"
            " prepared_on, prepared_by_name, archived, deleted, revision"
            " FROM trip_tabs WHERE deleted=0 ORDER BY starts_on, tab_id"
        ).fetchall()
        trips = [self._trip_dict(r) for r in rows]
        if not include_archived:
            trips = [t for t in trips if not t["archived"]]
        return trips

    def get_trip(self, tab_id: str):
        row = self.conn.execute(
            "SELECT tab_id, display_key, destination, starts_on, ends_on,"
            " prepared_on, prepared_by_name, archived, deleted, revision"
            " FROM trip_tabs WHERE tab_id=?",
            (tab_id,),
        ).fetchone()
        return self._trip_dict(row) if row else None

    def save_trip_meta(self, *, tab_id: str, expected_revision: int,
                       client_request_id: str, display_key=None,
                       prepared_on=None, prepared_by_name=None,
                       archived=None, actor: str = "owner") -> dict:
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                return json.loads(existing[0])["result"]
            current = self.get_trip(tab_id)
            if current is None or current["deleted"]:
                raise SaveError("INVALID_VALUE", "없는 여행이에요")
            if current["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            changes = {}
            if display_key is not None:
                if not str(display_key).strip():
                    raise SaveError("INVALID_VALUE", "이름이 비었어요")
                changes["display_key"] = str(display_key)
            if prepared_on is not None:
                if not _valid_date(str(prepared_on)):
                    raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
                changes["prepared_on"] = str(prepared_on)
            if prepared_by_name is not None:
                if not str(prepared_by_name).strip():
                    raise SaveError("INVALID_VALUE", "담당자 이름이 비었어요")
                changes["prepared_by_name"] = str(prepared_by_name)
            if archived is not None:
                changes["archived"] = bool(archived)
            new = dict(current)
            for field, value in changes.items():
                new[field] = value
            if all(new.get(k) == current.get(k) for k in changes):
                result = {"outcome": "unchanged", "tab_id": tab_id,
                          "revision": current["revision"], "event_id": None,
                          "ledger_pending": False}
                self.conn.execute(
                    "INSERT INTO trip_tab_requests(client_request_id, tab_id,"
                    " expected_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, tab_id, expected_revision,
                     _canonical({"tab_id": tab_id, "expected_revision": expected_revision,
                                 "changes": changes, "result": result}),
                     0, _utc_now()),
                )
                self.conn.commit()
                return result
            new_revision = current["revision"] + 1
            created_at = _utc_now()
            outbox_id = f"ledger-trip-{client_request_id}"
            ledger_action = ("propose" if current["revision"] == 1
                             and not changes.get("archived", False) else "correct")
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM trip_tabs WHERE tab_id=?", (tab_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 여행이에요")
                if fresh[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                cursor = self.conn.execute(
                    "UPDATE trip_tabs SET display_key=?, prepared_on=?,"
                    " prepared_by_name=?, archived=?, revision=? WHERE tab_id=? AND revision=?",
                    (new["display_key"], new["prepared_on"], new["prepared_by_name"],
                     1 if new["archived"] else 0, new_revision, tab_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO trip_tab_history(tab_id, revision, change_kind, prev_json,"
                    " new_json, event_id, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (tab_id, new_revision, "meta", _canonical(current),
                     _canonical(new), "", actor, created_at, client_request_id),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"trip-{tab_id}",
                    action=ledger_action, target=None,
                    rationale=f"여행 정보 저장 {tab_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO trip_tab_requests(client_request_id, tab_id,"
                    " expected_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, tab_id, expected_revision,
                     _canonical({"tab_id": tab_id, "expected_revision": expected_revision,
                                 "changes": changes,
                                 "source": "trip-meta",
                                 "actor": actor, "new_revision": new_revision,
                                 "result": {"outcome": "saved", "tab_id": tab_id,
                                            "revision": new_revision, "event_id": None,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        return json.loads(found[0])["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    return json.loads(found[0])["result"]
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_trip_request(client_request_id)
            if final is not None:
                return final
            stored = json.loads(
                self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()[0]
            )
            return stored["result"]

    def preview_tab_delete(self, tab_id: str) -> dict:
        trip = self.get_trip(tab_id)
        if trip is None or trip["deleted"]:
            raise SaveError("INVALID_VALUE", "없는 여행이에요")
        rows = [r for r in self.list_tab_rows(tab_id)]
        income_rows = [r for r in rows if r["row_kind"] == "income"]
        expense_rows = [r for r in rows if r["row_kind"] == "expense"]
        allocs = self.conn.execute(
            "SELECT allocation_id, source_row_id, amount_krw FROM income_allocations"
            " WHERE display_tab_id=? AND active=1",
            (tab_id,),
        ).fetchall()
        sources = {}
        for aid, src, _ in allocs:
            if src not in sources:
                srow = self.get_row(src)
                sources[src] = srow["revision"] if srow else None
        waiting = self.conn.execute(
            "SELECT COUNT(*) FROM board_learning_cases WHERE dialog_state='waiting'"
            " AND row_id IN (SELECT row_id FROM board_rows WHERE display_tab_id=?)",
            (tab_id,),
        ).fetchone()[0]
        snapshot = {
            "tab_revision": trip["revision"],
            "row_revisions": {r["row_id"]: r["revision"] for r in rows},
            "source_revisions": sources,
        }
        return {
            "tab_id": tab_id, "display_key": trip["display_key"],
            "income_count": len(income_rows),
            "income_total": sum(self.display_amount(r) for r in income_rows),
            "expense_count": len(expense_rows),
            "expense_total": sum(r["amount_krw"] for r in expense_rows),
            "allocation_count": len(allocs),
            "waiting_rules": waiting,
            "snapshot": snapshot,
        }

    def _trip_delete_replay(self, result_json: str, request: dict) -> dict:
        try:
            stored = json.loads(result_json)
        except (TypeError, json.JSONDecodeError):
            raise SaveError(
                "REQUEST_ID_REUSE_UNVERIFIED",
                "이전 삭제 결과를 읽을 수 없어 같은 요청인지 확인할 수 없어요",
            )
        if not isinstance(stored, dict) or stored.get("source") != "trip-delete":
            raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
        stored_request = stored.get("request")
        required = {"tab_id", "expected_revision", "mode", "destination", "snapshot"}
        if not isinstance(stored_request, dict) or set(stored_request) != required:
            raise SaveError(
                "REQUEST_ID_REUSE_UNVERIFIED",
                "이전 삭제 결과에 요청 정보가 없어 같은 요청인지 확인할 수 없어요",
            )
        if _canonical(stored_request) != _canonical(request):
            raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
        result = stored.get("result")
        if (not isinstance(result, dict)
                or result.get("outcome") != "deleted"
                or result.get("tab_id") != request["tab_id"]):
            raise SaveError(
                "REQUEST_ID_REUSE_UNVERIFIED",
                "이전 삭제 결과가 완료되지 않아 같은 요청인지 확인할 수 없어요",
            )
        return result

    def _finalized_trip_delete_replay(self, client_request_id: str,
                                      request: dict) -> dict:
        self._replay_pending()
        found = self.conn.execute(
            "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if not found:
            raise SaveError(
                "REQUEST_ID_REUSE_UNVERIFIED",
                "삭제 재시도 결과를 확인할 수 없어요",
            )
        return self._trip_delete_replay(found[0], request)

    def apply_tab_delete(self, *, tab_id: str, expected_revision: int,
                         mode: str, destination: str | None,
                         snapshot: dict, client_request_id: str,
                         actor: str = "owner") -> dict:
        if mode not in ("move-trip", "move-unclassified"):
            raise SaveError("INVALID_VALUE", "내역 처리 방법을 골라 주세요")
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        try:
            normalized_snapshot = json.loads(_canonical(snapshot))
        except (TypeError, json.JSONDecodeError):
            raise SaveError("INVALID_VALUE", "삭제 미리보기 형식이 달라요")
        if not isinstance(normalized_snapshot, dict):
            raise SaveError("INVALID_VALUE", "삭제 미리보기 형식이 달라요")
        normalized_destination = None
        if mode == "move-trip" and destination:
            if isinstance(destination, str) and not destination.strip():
                normalized_destination = None
            else:
                normalized_destination = destination
        request = {
            "tab_id": tab_id,
            "expected_revision": expected_revision,
            "mode": mode,
            "destination": normalized_destination,
            "snapshot": normalized_snapshot,
        }
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                return self._trip_delete_replay(existing[0], request)
            trip = self.get_trip(tab_id)
            if trip is None or trip["deleted"]:
                raise SaveError("INVALID_VALUE", "없는 여행이에요")
            if trip["revision"] != expected_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            target = None
            if mode == "move-trip":
                if normalized_destination is None or normalized_destination == tab_id:
                    raise SaveError("TARGET_NOT_ASSIGNABLE", "옮길 여행을 골라 주세요")
                target = self.get_trip(normalized_destination)
                if target is None or target["deleted"]:
                    raise SaveError("TARGET_NOT_ASSIGNABLE", "옮길 수 없는 여행이에요")
            rows = self.list_tab_rows(tab_id)
            current_snapshot = {
                "tab_revision": trip["revision"],
                "row_revisions": {r["row_id"]: r["revision"] for r in rows},
                "source_revisions": normalized_snapshot.get("source_revisions", {}),
            }
            for src, rev in normalized_snapshot.get("source_revisions", {}).items():
                srow = self.get_row(src)
                if (srow is None) or (srow["revision"] != rev):
                    raise SaveError("DELETE_PREVIEW_STALE", "미리보기 뒤 장부가 바뀌었어요. 다시 확인해 주세요")
            if (current_snapshot["tab_revision"] != normalized_snapshot.get("tab_revision")
                    or current_snapshot["row_revisions"] != normalized_snapshot.get("row_revisions", {})):
                raise SaveError("DELETE_PREVIEW_STALE", "미리보기 뒤 장부가 바뀌었어요. 다시 확인해 주세요")
            new_tab_revision = trip["revision"] + 1
            created_at = _utc_now()
            moved_rows = []
            moved_allocs = []
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                fresh_tab = self.conn.execute(
                    "SELECT revision FROM trip_tabs WHERE tab_id=?", (tab_id,)
                ).fetchone()
                if fresh_tab is None or fresh_tab[0] != expected_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                live_rows = self.conn.execute(
                    "SELECT row_id, revision FROM board_rows WHERE display_tab_id=?",
                    (tab_id,),
                ).fetchall()
                if ({r: v for r, v in live_rows} != normalized_snapshot.get("row_revisions", {})
                        or fresh_tab[0] != normalized_snapshot.get("tab_revision")):
                    raise SaveError("DELETE_PREVIEW_STALE", "미리보기 뒤 장부가 바뀌었어요. 다시 확인해 주세요")
                for src, rev in normalized_snapshot.get("source_revisions", {}).items():
                    live_src = self.conn.execute(
                        "SELECT revision FROM board_rows WHERE row_id=?", (src,)
                    ).fetchone()
                    if live_src is None or live_src[0] != rev:
                        raise SaveError("DELETE_PREVIEW_STALE", "미리보기 뒤 장부가 바뀌었어요. 다시 확인해 주세요")
                for row in rows:
                    new_rev = row["revision"] + 1
                    new_display = target["tab_id"] if target else None
                    updated = dict(row, display_tab_id=new_display, revision=new_rev)
                    cursor = self.conn.execute(
                        "UPDATE board_rows SET display_tab_id=?, revision=?, payload_json=?"
                        " WHERE row_id=? AND revision=?",
                        (new_display, new_rev, _canonical(updated),
                         row["row_id"], row["revision"]),
                    )
                    if cursor.rowcount == 0:
                        raise SaveError("DELETE_PREVIEW_STALE", "미리보기 뒤 장부가 바뀌었어요. 다시 확인해 주세요")
                    self.conn.execute(
                        "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
                        " event_id, change_mode, actor, created_at, client_request_id,"
                        " kind, reverts_event_id)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,'')",
                        (row["row_id"], new_rev, _canonical(row), _canonical(updated),
                         "", "exception", actor, created_at, f"{client_request_id}:move",
                         "move"),
                    )
                    moved_rows.append((row["row_id"], new_rev,
                                       row.get("source_event_id"), row["revision"]))
                alloc_rows = self.conn.execute(
                    "SELECT allocation_id FROM income_allocations"
                    " WHERE display_tab_id=? AND active=1",
                    (tab_id,),
                ).fetchall()
                for (aid,) in alloc_rows:
                    self.conn.execute(
                        "UPDATE income_allocations SET display_tab_id=? WHERE allocation_id=?",
                        (target["tab_id"] if target else None, aid),
                    )
                    moved_allocs.append(aid)
                cursor = self.conn.execute(
                    "UPDATE trip_tabs SET deleted=1, revision=? WHERE tab_id=? AND revision=?",
                    (new_tab_revision, tab_id, expected_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO trip_tab_history(tab_id, revision, change_kind, prev_json,"
                    " new_json, event_id, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (tab_id, new_tab_revision, "delete", _canonical(trip),
                     _canonical({**trip, "deleted": True, "revision": new_tab_revision}),
                     "", actor, created_at, client_request_id),
                )
                for row_id, new_rev, source_event_id, _prev_rev in moved_rows:
                    self._enqueue_ledger(
                        outbox_id=f"ledger-{client_request_id}:{row_id}",
                        stream_id=f"row-{row_id}",
                        action=self._stream_action(f"row-{row_id}"),
                        target=source_event_id,
                        rationale=f"여행 삭제 이동 {row_id} revision {new_rev}",
                        actor=actor,
                    )
                self._enqueue_ledger(
                    outbox_id=f"ledger-trip-{client_request_id}",
                    stream_id=f"trip-{tab_id}",
                    action=self._stream_action(f"trip-{tab_id}"),
                    rationale=f"여행 삭제 {tab_id} revision {new_tab_revision}",
                    actor=actor, target=None,
                )
                self.conn.execute(
                    "INSERT INTO trip_tab_requests(client_request_id, tab_id,"
                    " expected_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, tab_id, expected_revision,
                     _canonical({"tab_id": tab_id, "expected_revision": expected_revision,
                                 "request": request,
                                 "changes": {"delete": {"mode": mode,
                                                        "destination": target["tab_id"] if target else None}},
                                 "source": "trip-delete",
                                 "actor": actor, "new_revision": new_tab_revision,
                                 "moved_rows": moved_rows, "moved_allocs": moved_allocs,
                                 "result": {"outcome": "deleted", "tab_id": tab_id,
                                            "revision": new_tab_revision,
                                            "moved_rows": [r[0] for r in moved_rows],
                                            "moved_allocs": moved_allocs,
                                            "event_id": None, "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        return self._finalized_trip_delete_replay(
                            client_request_id, request
                        )
                    raise SaveError("REQUEST_ID_REUSE_UNVERIFIED", "삭제 재시도 결과를 확인할 수 없어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    return self._finalized_trip_delete_replay(
                        client_request_id, request
                    )
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox(
                [f"ledger-{client_request_id}:{row_id}" for row_id, _, _, _ in moved_rows]
                + [f"ledger-trip-{client_request_id}"]
            )
            final = self._finalize_trip_request(client_request_id)
            if final is not None:
                return final
            stored = json.loads(
                self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()[0]
            )
            return stored["result"]

    def _allocation_dict(self, row) -> dict:
        return {
            "allocation_id": row[0], "source_row_id": row[1],
            "customer_id": row[2], "customer_name": row[3] or "",
            "nickname": row[4] or "", "display_tab_id": row[5],
            "income_kind": row[6], "amount_krw": row[7],
            "active": bool(row[8]), "source_revision": row[9],
        }

    def active_allocations(self, source_row_id: str) -> list:
        rows = self.conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE source_row_id=? AND active=1"
            " ORDER BY allocation_id",
            (source_row_id,),
        ).fetchall()
        return [self._allocation_dict(r) for r in rows]

    def split_source_ids(self) -> set:
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT source_row_id FROM income_allocations WHERE active=1"
            ).fetchall()
        except Exception:
            return set()
        return {r[0] for r in rows}

    def split_remainder(self, source_row_id: str) -> int:
        source = self.get_row(source_row_id)
        if source is None:
            return 0
        reflected = self.display_amount(source)
        return reflected - sum(a["amount_krw"] for a in self.active_allocations(source_row_id))

    def _allocation_display_row(self, alloc: dict, source: dict) -> dict:
        shown_date = self.display_occurred_on(source)
        return {
            "row_id": alloc["allocation_id"], "row_kind": "income",
            "is_allocation": True, "source_row_id": alloc["source_row_id"],
            "display_tab_id": alloc["display_tab_id"],
            "revision": source["revision"],
            "occurred_on": shown_date, "display_occurred_on": shown_date,
            "customer_id": alloc["customer_id"], "customer_name": alloc["customer_name"],
            "nickname": alloc["nickname"], "income_kind": alloc["income_kind"],
            "event_type": "receipt", "amount_krw": alloc["amount_krw"],
            "display_amount_krw": alloc["amount_krw"],
            "source_kind": source.get("source_kind", ""),
            "source_event_id": source.get("source_event_id", ""),
            "operator_note": "",
        }

    def _remainder_display_row(self, source: dict) -> dict:
        remainder = self.split_remainder(source["row_id"])
        shown_date = self.display_occurred_on(source)
        return {
            "row_id": f"rem-{source['row_id']}", "row_kind": "income",
            "is_remainder": True, "source_row_id": source["row_id"],
            "display_tab_id": None, "revision": source["revision"],
            "occurred_on": shown_date, "display_occurred_on": shown_date,
            "customer_id": None, "customer_name": "", "nickname": "",
            "income_kind": "", "event_type": "receipt",
            "amount_krw": remainder, "display_amount_krw": remainder,
            "source_kind": source.get("source_kind", ""),
            "source_event_id": source.get("source_event_id", ""),
            "operator_note": "",
        }

    def get_allocation(self, allocation_id: str):
        """Get a single allocation by ID."""
        row = self.conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        return self._allocation_dict(row) if row else None

    def _normalize_allocation_row_changes(self, changes):
        if not isinstance(changes, dict) or not changes:
            raise SaveError("INVALID_VALUE", "수정할 수 있는 필드가 없어요")
        unknown = [field for field in changes if field not in ALLOCATION_ROW_EDITABLE]
        if unknown:
            raise SaveError("FIELD_READ_ONLY", f"{unknown[0]}는 배분 행에서 수정할 수 없어요")
        normalized = {}
        for field in ALLOCATION_ROW_EDITABLE:
            if field not in changes:
                continue
            value = changes[field]
            if field == "display_tab_id":
                value = None if value is None or str(value).strip() in ("", "unclassified") else str(value)
            elif field == "customer_id":
                value = None if value is None or str(value).strip() == "" else str(value)
            elif field in ("customer_name", "nickname"):
                value = "" if value is None else str(value)
            elif field == "income_kind":
                value = str(value or "")
                if value not in ("deposit", "balance", "additional"):
                    raise SaveError("INVALID_VALUE", "입금 종류를 골라 주세요")
            normalized[field] = value
        if not normalized:
            raise SaveError("INVALID_VALUE", "수정할 수 있는 필드가 없어요")
        destination = normalized.get("display_tab_id")
        if destination is not None:
            trip = self.get_trip(destination)
            if trip is None or trip["deleted"]:
                raise SaveError("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
        return normalized

    @staticmethod
    def _allocation_history_projection(allocation):
        return {
            **{field: allocation.get(field) for field in ALLOCATION_ROW_EDITABLE},
            "amount_krw": allocation.get("amount_krw"),
            "active": bool(allocation.get("active")),
            "source_revision": allocation.get("source_revision"),
        }

    def _latest_allocation_history(self, allocation_id):
        row = self.conn.execute(
            "SELECT id, prev_json, new_json, event_id, client_request_id, reverts_event_id"
            " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC LIMIT 1",
            (allocation_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "prev": json.loads(row[1]), "new": json.loads(row[2]),
            "event_id": row[3], "client_request_id": row[4],
            "reverts_event_id": row[5],
        }

    def _allocation_revert_changes(self, allocation):
        history = self._latest_allocation_history(allocation["allocation_id"])
        if history is None:
            raise SaveError("INVALID_VALUE", "되돌릴 배분 행 편집이 없어요")
        if history["reverts_event_id"]:
            raise SaveError("INVALID_VALUE", "이미 되돌린 수정이에요")
        origin = self.conn.execute(
            "SELECT result_json FROM board_requests WHERE client_request_id=?",
            (history["client_request_id"],),
        ).fetchone()
        origin_data = json.loads(origin[0]) if origin else {}
        if origin_data.get("api") != "allocation-edit":
            raise SaveError("INVALID_VALUE", "직전 변경은 배분 전체 수정이라 행 되돌릴 수 없어요")
        latest_source = self._latest_entry(allocation["source_row_id"])
        if latest_source is None or latest_source["client_request_id"] != history["client_request_id"]:
            raise SaveError("INVALID_VALUE", "최신 배분 변경이 아니어서 되돌릴 수 없어요")
        current = self._allocation_history_projection(allocation)
        for field in ALLOCATION_ROW_EDITABLE:
            if field in history["new"] and history["new"].get(field) != current.get(field):
                raise SaveError("INVALID_VALUE", "최신 배분 내용을 확인해 주세요")
        previous = history["prev"]
        changes = self._normalize_allocation_row_changes({
            field: previous.get(field, allocation.get(field))
            for field in ALLOCATION_ROW_EDITABLE if field in previous
        })
        return changes, history

    @staticmethod
    def _allocation_request_matches(stored, api, allocation_id,
                                    expected_source_revision, changes):
        if stored.get("api") != api:
            return False
        if stored.get("allocation_id") != allocation_id:
            return False
        if stored.get("expected_source_revision") != expected_source_revision:
            return False
        return changes is None or stored.get("changes") == changes

    def _apply_allocation_row_change(self, *, api, allocation_id,
                                     expected_source_revision, client_request_id,
                                     changes, actor, reverts_event_id="",
                                     reverted_request_id=""):
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        if isinstance(expected_source_revision, bool) or not isinstance(expected_source_revision, int):
            raise SaveError("INVALID_VALUE", "원천 버전이 필요해요")
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if self._allocation_request_matches(
                        stored, api, allocation_id, expected_source_revision, changes):
                    return stored["result"]
                raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
            allocation = self.get_allocation(allocation_id)
            if allocation is None:
                raise SaveError("INVALID_VALUE", "없는 배분 행이에요")
            if not allocation.get("active"):
                raise SaveError("INVALID_VALUE", "비활성 배분은 수정할 수 없어요")
            source = self.get_row(allocation["source_row_id"])
            if source is None or source["row_kind"] != "income":
                raise SaveError("INVALID_VALUE", "원천 수입 행이 없어요")
            if (source["revision"] != expected_source_revision
                    or allocation["source_revision"] != expected_source_revision):
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            target_history = None
            if changes is None:
                changes, target_history = self._allocation_revert_changes(allocation)
                reverts_event_id = (
                    target_history["event_id"] or target_history["client_request_id"]
                )
                reverted_request_id = target_history["client_request_id"]
            updated = dict(allocation)
            for field, value in changes.items():
                updated[field] = value
            changed_fields = [
                field for field in ALLOCATION_ROW_EDITABLE
                if allocation.get(field) != updated.get(field)
            ]
            created_at = _utc_now()
            source_row_id = allocation["source_row_id"]
            if not changed_fields:
                result = {
                    "outcome": "unchanged", "allocation_id": allocation_id,
                    "source_row_id": source_row_id, "revision": expected_source_revision,
                    "changed_fields": [], "event_id": None, "ledger_pending": False,
                }
                request_data = {
                    "row_id": allocation_id, "api": api,
                    "allocation_id": allocation_id, "source_row_id": source_row_id,
                    "expected_source_revision": expected_source_revision,
                    "changes": changes, "actor": actor,
                    "reverted_request_id": reverted_request_id,
                    "reverts_event_id": reverts_event_id,
                    "source_event_id": source.get("source_event_id"),
                    "new_revision": expected_source_revision, "result": result,
                }
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    fresh = self.conn.execute(
                        "SELECT revision FROM board_rows WHERE row_id=?", (source_row_id,)
                    ).fetchone()
                    if fresh is None or fresh[0] != expected_source_revision:
                        raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                    duplicate = self.conn.execute(
                        "SELECT result_json FROM board_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if duplicate:
                        raise SaveError("__REPLAY__", "retry")
                    self.conn.execute(
                        "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                        " result_json, ledger_pending, created_at) VALUES (?,?,?,?,0,?)",
                        (client_request_id, allocation_id, expected_source_revision,
                         _canonical(request_data), created_at),
                    )
                    self.conn.execute("COMMIT")
                except SaveError as exc:
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    if exc.code == "__REPLAY__":
                        found = self.conn.execute(
                            "SELECT result_json FROM board_requests WHERE client_request_id=?",
                            (client_request_id,),
                        ).fetchone()
                        if found and self._allocation_request_matches(
                                json.loads(found[0]), api, allocation_id,
                                expected_source_revision, changes):
                            return json.loads(found[0])["result"]
                    raise
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
                return result
            new_revision = expected_source_revision + 1
            updated["source_revision"] = new_revision
            before = self._allocation_history_projection(allocation)
            after = self._allocation_history_projection(updated)
            affected_tab_ids = sorted({
                value for value in (
                    allocation.get("display_tab_id"), updated.get("display_tab_id")
                ) if value is not None
            })
            result = {
                "outcome": "reverted" if api == "allocation-revert" else "saved",
                "allocation_id": allocation_id, "source_row_id": source_row_id,
                "revision": new_revision, "changed_fields": changed_fields,
                "affected_tab_ids": affected_tab_ids, "before": before, "after": after,
                "reverted_request_id": reverted_request_id or None,
                "event_id": None, "ledger_pending": True,
            }
            updated_source = dict(source)
            updated_source["revision"] = new_revision
            outbox_id = f"ledger-{client_request_id}"
            request_data = {
                "row_id": allocation_id, "api": api,
                "allocation_id": allocation_id, "source_row_id": source_row_id,
                "expected_source_revision": expected_source_revision,
                "changes": changes, "actor": actor,
                "reverted_request_id": reverted_request_id,
                "reverts_event_id": reverts_event_id,
                "source_event_id": source.get("source_event_id"),
                "new_revision": new_revision, "result": result,
            }
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh_source = self.conn.execute(
                    "SELECT revision, payload_json FROM board_rows WHERE row_id=?",
                    (source_row_id,),
                ).fetchone()
                fresh_allocation = self.get_allocation(allocation_id)
                if (fresh_source is None or fresh_source[0] != expected_source_revision
                        or fresh_allocation is None
                        or not fresh_allocation.get("active")
                        or fresh_allocation["source_revision"] != expected_source_revision):
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                duplicate = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if duplicate:
                    raise SaveError("__REPLAY__", "retry")
                cursor = self.conn.execute(
                    "UPDATE income_allocations SET customer_id=?, customer_name=?, nickname=?,"
                    " display_tab_id=?, income_kind=?, source_revision=?"
                    " WHERE allocation_id=? AND source_row_id=? AND active=1",
                    (updated["customer_id"], updated["customer_name"], updated["nickname"],
                     updated["display_tab_id"], updated["income_kind"], new_revision,
                     allocation_id, source_row_id),
                )
                if cursor.rowcount != 1:
                    raise SaveError("EDIT_CONFLICT", "배분 행이 바뀌었어요. 다시 확인해 주세요")
                self.conn.execute(
                    "UPDATE income_allocations SET source_revision=?"
                    " WHERE source_row_id=? AND active=1",
                    (new_revision, source_row_id),
                )
                cursor = self.conn.execute(
                    "UPDATE board_rows SET revision=?, payload_json=?"
                    " WHERE row_id=? AND revision=?",
                    (new_revision, _canonical(updated_source), source_row_id,
                     expected_source_revision),
                )
                if cursor.rowcount != 1:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id, kind, reverts_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (source_row_id, new_revision, _canonical(source),
                     _canonical(updated_source), "", "exception", actor, created_at,
                     client_request_id, api, reverts_event_id),
                )
                self._record_allocation_history(
                    allocation_id=allocation_id, source_row_id=source_row_id,
                    prev=before, new=after, actor=actor, created_at=created_at,
                    client_request_id=client_request_id,
                    reverts_event_id=reverts_event_id,
                )
                for field in changed_fields:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO board_manual_overrides(row_id, field, event_id)"
                        " VALUES (?,?,?)",
                        (allocation_id, field, ""),
                    )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{source_row_id}",
                    action="correct", target=source.get("source_event_id"),
                    rationale=f"배분 행 {api} {allocation_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,1,?)",
                    (client_request_id, allocation_id, expected_source_revision,
                     _canonical(request_data), created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM board_requests WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found and self._allocation_request_matches(
                            json.loads(found[0]), api, allocation_id,
                            expected_source_revision, changes):
                        return json.loads(found[0])["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            return final if final is not None else result

    def update_allocation(self, *, allocation_id: str, expected_source_revision: int,
                          client_request_id: str, actor: str = "owner",
                          changes: dict) -> dict:
        normalized = self._normalize_allocation_row_changes(changes)
        return self._apply_allocation_row_change(
            api="allocation-edit", allocation_id=allocation_id,
            expected_source_revision=expected_source_revision,
            client_request_id=client_request_id, changes=normalized, actor=actor,
        )

    def get_allocation_display(self, allocation_id: str):
        row = self.conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        if row is None:
            return None
        alloc = self._allocation_dict(row)
        if not alloc["active"]:
            return None
        source = self.get_row(alloc["source_row_id"])
        if source is None:
            return None
        return self._allocation_display_row(alloc, source)

    def _validate_allocation_plan(self, source: dict, reflected: int, plan: list) -> list:
        cleaned = []
        for index, item in enumerate(plan):
            if not isinstance(item, dict):
                raise SaveError("INVALID_VALUE", "배분안이 올바르지 않아요")
            amount = item.get("amount_krw")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
                raise SaveError("INVALID_VALUE", "배분액은 0이 아닌 정수 원화로 입력해 주세요")
            if reflected > 0 and amount < 0:
                raise SaveError("INVALID_VALUE", "양수 입금은 양수 배분만 할 수 있어요")
            if reflected < 0 and amount > 0:
                raise SaveError("INVALID_VALUE", "음수 환불은 음수 배분만 할 수 있어요")
            kind = item.get("income_kind")
            if kind not in ("deposit", "balance", "additional"):
                raise SaveError("INVALID_VALUE", "입금 종류를 골라 주세요")
            if not str(item.get("customer_name") or "").strip():
                raise SaveError("INVALID_VALUE", "배분 고객 이름이 필요해요")
            tab = item.get("display_tab_id")
            if tab is not None:
                trip = self.get_trip(tab)
                if trip is None or trip["deleted"]:
                    raise SaveError("TARGET_NOT_ASSIGNABLE", "배정할 수 없는 여행이에요")
            cleaned.append({
                "allocation_id": str(item.get("allocation_id") or ""),
                "customer_id": item.get("customer_id"),
                "customer_name": str(item.get("customer_name") or ""),
                "nickname": str(item.get("nickname") or ""),
                "display_tab_id": tab, "income_kind": kind, "amount_krw": amount,
            })
        total = sum(c["amount_krw"] for c in cleaned)
        if reflected == 0:
            if cleaned:
                raise SaveError("INVALID_VALUE", "나눌 금액이 없어요")
        elif abs(total) > abs(reflected):
            raise SaveError("INVALID_VALUE", "배분 합계가 입금액을 넘었어요")
        return cleaned

    def _allocation_snapshot(self, allocation_id: str):
        row = self.conn.execute(
            "SELECT allocation_id, source_row_id, customer_id, customer_name, nickname,"
            " display_tab_id, income_kind, amount_krw, active, source_revision"
            " FROM income_allocations WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        return self._allocation_dict(row) if row else None

    def _record_allocation_history(self, *, allocation_id: str, source_row_id: str,
                                   prev, new, actor: str, created_at: str,
                                   client_request_id: str, reverts_event_id: str = "") -> None:
        self.conn.execute(
            "INSERT INTO income_allocation_history(allocation_id, source_row_id, prev_json,"
            " new_json, event_id, actor, created_at, client_request_id, reverts_event_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (allocation_id, source_row_id, _canonical(prev or {}), _canonical(new or {}),
             "", actor, created_at, client_request_id, reverts_event_id),
        )

    def _apply_allocation_plan(self, *, source_row_id: str, new_revision: int,
                               plan: list, client_request_id: str,
                               created_at: str, actor: str = "owner") -> tuple:
        before = self.active_allocations(source_row_id)
        before_ids = {a["allocation_id"] for a in before}
        seen_ids = set()
        after_ids = []
        for index, item in enumerate(plan):
            aid = item["allocation_id"] or f"alc-{client_request_id[:12]}-{index}"
            if aid in seen_ids:
                raise SaveError("INVALID_VALUE", "배분 ID가 중복됐어요")
            seen_ids.add(aid)
            after_ids.append(aid)
            prev_snap = self._allocation_snapshot(aid)
            if prev_snap is not None and prev_snap["source_row_id"] != source_row_id:
                raise SaveError("INVALID_VALUE", "다른 입금의 배분이에요")
            if prev_snap is None:
                self.conn.execute(
                    "INSERT INTO income_allocations(allocation_id, source_row_id, customer_id,"
                    " customer_name, nickname, display_tab_id, income_kind, amount_krw,"
                    " active, source_revision, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, source_row_id, item["customer_id"], item["customer_name"],
                     item["nickname"], item["display_tab_id"], item["income_kind"],
                     item["amount_krw"], 1, new_revision, created_at, client_request_id),
                )
                self._record_allocation_history(
                    allocation_id=aid, source_row_id=source_row_id,
                    prev={}, new={**item, "allocation_id": aid, "active": True},
                    actor=actor, created_at=created_at, client_request_id=client_request_id)
            else:
                self.conn.execute(
                    "UPDATE income_allocations SET customer_id=?, customer_name=?, nickname=?,"
                    " display_tab_id=?, income_kind=?, amount_krw=?, active=1,"
                    " source_revision=? WHERE allocation_id=?",
                    (item["customer_id"], item["customer_name"], item["nickname"],
                     item["display_tab_id"], item["income_kind"], item["amount_krw"],
                     new_revision, aid),
                )
                updated = self._allocation_snapshot(aid)
                if _canonical({k: prev_snap.get(k) for k in
                               ("customer_id", "customer_name", "nickname", "display_tab_id",
                                "income_kind", "amount_krw", "active")}) != _canonical(
                        {k: updated.get(k) for k in
                         ("customer_id", "customer_name", "nickname", "display_tab_id",
                          "income_kind", "amount_krw", "active")}):
                    self._record_allocation_history(
                        allocation_id=aid, source_row_id=source_row_id,
                        prev=prev_snap, new=updated,
                        actor=actor, created_at=created_at, client_request_id=client_request_id)
        for aid in before_ids - seen_ids:
            prev_snap = self._allocation_snapshot(aid)
            self.conn.execute(
                "UPDATE income_allocations SET active=0, source_revision=? WHERE allocation_id=?",
                (new_revision, aid),
            )
            self._record_allocation_history(
                allocation_id=aid, source_row_id=source_row_id,
                prev=prev_snap, new={**(prev_snap or {}), "active": False},
                actor=actor, created_at=created_at, client_request_id=client_request_id)
        after = self.active_allocations(source_row_id)
        return before, after

    def save_allocations(self, *, source_row_id: str, expected_source_revision: int,
                         allocations: list, client_request_id: str,
                         new_principal=None, actor: str = "owner") -> dict:
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM income_allocation_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if (self._normalize_plan_for_compare(stored.get("plan"))
                        != self._normalize_plan_for_compare(list(allocations or []))
                        or stored.get("new_principal") != (new_principal or None)):
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return stored["result"]
            source = self.get_row(source_row_id)
            if source is None or source["row_kind"] != "income":
                raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
            if source["revision"] != expected_source_revision:
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            updated_source = dict(source)
            if new_principal is not None:
                if source.get("source_kind") != "직접 입력":
                    raise SaveError("INVALID_VALUE", "원금 변경은 직접 입력에만 함께 저장해요")
                if "amount_krw" in new_principal:
                    amount = new_principal["amount_krw"]
                    if isinstance(amount, bool) or not isinstance(amount, int):
                        raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
                    updated_source["amount_krw"] = amount
                if "occurred_on" in new_principal:
                    if not _valid_date(str(new_principal["occurred_on"])):
                        raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
                    updated_source["occurred_on"] = str(new_principal["occurred_on"])
            reflected = updated_source["amount_krw"]
            plan = self._validate_allocation_plan(source, reflected, list(allocations or []))
            total = sum(p["amount_krw"] for p in plan)
            new_revision = source["revision"] + 1
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.conn.execute(
                    "SELECT revision FROM board_rows WHERE row_id=?", (source_row_id,)
                ).fetchone()
                if fresh is None:
                    raise SaveError("INVALID_VALUE", "없는 수입 행이에요")
                if fresh[0] != expected_source_revision:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                dup = self.conn.execute(
                    "SELECT result_json FROM income_allocation_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                before, after = self._apply_allocation_plan(
                    source_row_id=source_row_id, new_revision=new_revision,
                    plan=plan, client_request_id=client_request_id,
                    created_at=created_at, actor=actor)
                updated_source["revision"] = new_revision
                cursor = self.conn.execute(
                    "UPDATE board_rows SET display_tab_id=?, revision=?, payload_json=?"
                    " WHERE row_id=? AND revision=?",
                    (updated_source["display_tab_id"], new_revision,
                     _canonical(updated_source), source_row_id, expected_source_revision),
                )
                if cursor.rowcount == 0:
                    raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
                    " event_id, change_mode, actor, created_at, client_request_id,"
                    " kind, reverts_event_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'')",
                    (source_row_id, new_revision, _canonical(source),
                     _canonical(updated_source),
                     "", "exception", actor, created_at, client_request_id, "alloc"),
                )
                result = {"outcome": "saved", "source_row_id": source_row_id,
                          "revision": new_revision, "event_id": None,
                          "allocations": [a["allocation_id"] for a in after],
                          "remainder": reflected - total,
                          "alloc_before": before, "alloc_after": after,
                          "ledger_pending": True}
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{source_row_id}",
                    action="correct", target=source.get("source_event_id"),
                    rationale=f"입금 배분 저장 {source_row_id} revision {new_revision}",
                    actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO income_allocation_requests(client_request_id, source_row_id,"
                    " expected_source_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, source_row_id, expected_source_revision,
                     _canonical({"source_row_id": source_row_id,
                                 "expected_source_revision": expected_source_revision,
                                 "plan": plan, "new_principal": new_principal or None,
                                 "actor": actor,
                                 "source_event_id": source.get("source_event_id"),
                                 "new_revision": new_revision, "result": result}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM income_allocation_requests"
                        " WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        retry_stored = json.loads(found[0])
                        if (self._normalize_plan_for_compare(retry_stored.get("plan"))
                                == self._normalize_plan_for_compare(plan)
                                and retry_stored.get("new_principal") == (new_principal or None)):
                            return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM income_allocation_requests"
                    " WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if (self._normalize_plan_for_compare(retry_stored.get("plan"))
                            == self._normalize_plan_for_compare(plan)
                            and retry_stored.get("new_principal") == (new_principal or None)):
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_alloc_request(client_request_id)
            if final is not None:
                return final
            stored = json.loads(
                self.conn.execute(
                    "SELECT result_json FROM income_allocation_requests"
                    " WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()[0]
            )
            return stored["result"]

    def create_direct_income(self, *, fields: dict, client_request_id: str,
                             actor: str = "owner") -> dict:
        for key in ("display_tab_id", "occurred_on", "amount_krw", "income_kind"):
            if key not in fields:
                raise SaveError("INVALID_VALUE", f"{key}가 필요해요")
        if fields["income_kind"] not in ("deposit", "balance", "additional"):
            raise SaveError("INVALID_VALUE", "입금 종류를 골라 주세요")
        if isinstance(fields["amount_krw"], bool) or not isinstance(fields["amount_krw"], int):
            raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
        if not _valid_date(str(fields["occurred_on"])):
            raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        row_id = f"inc-{client_request_id[:16]}"
        want_input = _normalize_create_input(fields)
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if stored.get("create_input") == want_input:
                    return stored["result"]
                raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
            if self.get_row(row_id) is not None:
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            record = {
                "row_id": row_id, "row_kind": "income",
                "display_tab_id": fields["display_tab_id"],
                "revision": 1,
                "occurred_on": str(fields["occurred_on"]),
                "customer_id": fields.get("customer_id"),
                "customer_name": str(fields.get("customer_name") or ""),
                "nickname": str(fields.get("nickname") or ""),
                "income_kind": fields["income_kind"],
                "event_type": "receipt",
                "amount_krw": fields["amount_krw"],
                "source_kind": "직접 입력",
                "source_event_id": row_id,
                "operator_note": str(fields.get("memo") or ""),
                "created_by_request": client_request_id,
            }
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    if dup_stored.get("create_input") == want_input:
                        return dup_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if self.conn.execute(
                    "SELECT row_id FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone():
                    raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
                self.conn.execute(
                    "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                    " VALUES (?,?,?,?,?)",
                    (row_id, "income", record["display_tab_id"], 1, _canonical(record)),
                )
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row_id, 1, _canonical({}), _canonical(record), "",
                     "exception", actor, created_at, client_request_id),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="propose", target=row_id,
                    rationale=f"직접 수입 {row_id}", actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, 1,
                     _canonical({"row_id": row_id, "expected_revision": 1,
                                 "changes": {"create": "direct-income"},
                                 "change_mode": "exception",
                                 "source_event_id": row_id, "actor": actor,
                                 "new_revision": 1, "create_input": want_input,
                                 "result": {"outcome": "saved", "row_id": row_id,
                                            "revision": 1, "event_id": None,
                                            "request_id": client_request_id,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if retry_stored.get("create_input") == want_input:
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {"outcome": "saved", "row_id": row_id, "revision": 1,
                    "event_id": None, "request_id": client_request_id,
                    "ledger_pending": True}

    def create_manual_expense(self, *, fields: dict, client_request_id: str,
                              actor: str = "owner") -> dict:
        for key in ("display_tab_id", "occurred_on", "amount_krw", "item"):
            if key not in fields:
                raise SaveError("INVALID_VALUE", f"{key}가 필요해요")
        if fields.get("pay_method") not in ("현금", "계좌이체"):
            raise SaveError("INVALID_VALUE", "지급 수단을 현금·계좌이체 중에서 골라 주세요")
        if isinstance(fields["amount_krw"], bool) or not isinstance(fields["amount_krw"], int):
            raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
        if not _valid_date(str(fields["occurred_on"])):
            raise SaveError("INVALID_VALUE", "날짜 형식이 달라요")
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        row_id = f"man-{client_request_id[:16]}"
        want_input = _normalize_create_input(fields)
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if stored.get("create_input") == want_input:
                    return stored["result"]
                raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
            if self.get_row(row_id) is not None:
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            record = {
                "row_id": row_id, "row_kind": "expense",
                "display_tab_id": fields["display_tab_id"],
                "revision": 1,
                "occurred_on": str(fields["occurred_on"]),
                "item": str(fields["item"]),
                "description": str(fields.get("description") or ""),
                "service_period": "",
                "reservation_no": "",
                "evidence_type": "현금" if fields["pay_method"] == "현금" else "계좌이체",
                "amount_krw": fields["amount_krw"],
                "source_kind": "수기",
                "source_event_id": row_id,
                "classification_state": "",
                "classification_basis": "직접 입력",
                "operator_note": str(fields.get("memo") or ""),
                "created_by_request": client_request_id,
            }
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    if dup_stored.get("create_input") == want_input:
                        return dup_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if self.conn.execute(
                    "SELECT row_id FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone():
                    raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
                self.conn.execute(
                    "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                    " VALUES (?,?,?,?,?)",
                    (row_id, "expense", record["display_tab_id"], 1, _canonical(record)),
                )
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row_id, 1, _canonical({}), _canonical(record), "",
                     "exception", actor, created_at, client_request_id),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="propose", target=row_id,
                    rationale=f"수기 지출 {row_id}", actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, 1,
                     _canonical({"row_id": row_id, "expected_revision": 1,
                                 "changes": {"create": "manual-expense"},
                                 "change_mode": "exception",
                                 "source_event_id": row_id, "actor": actor,
                                 "new_revision": 1, "create_input": want_input,
                                 "result": {"outcome": "saved", "row_id": row_id,
                                            "revision": 1, "event_id": None,
                                            "request_id": client_request_id,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                self.conn.execute("COMMIT")
            except SaveError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if retry_stored.get("create_input") == want_input:
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {"outcome": "saved", "row_id": row_id, "revision": 1,
                    "event_id": None, "request_id": client_request_id,
                    "ledger_pending": True}

    def import_income_row(self, *, row_id: str, fields: dict, batch_id: str,
                          client_request_id: str, actor: str = "owner") -> dict:
        record = {
            "row_id": row_id, "row_kind": "income",
            "display_tab_id": fields["display_tab_id"],
            "revision": 1,
            "occurred_on": fields["occurred_on"],
            "customer_id": fields.get("customer_id"),
            "customer_name": fields.get("customer_name", ""),
            "nickname": fields.get("nickname", ""),
            "income_kind": fields.get("income_kind", "deposit"),
            "event_type": "receipt",
            "amount_krw": fields["amount_krw"],
            "source_kind": "은행",
            "source_event_id": fields.get("source_event_id", row_id),
            "operator_note": "",
        }
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM board_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                return json.loads(existing[0])["result"]
            if self.get_row(row_id) is not None:
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            created_at = _utc_now()
            outbox_id = f"ledger-{client_request_id}"
            want = {"import": batch_id}
            outer_txn = self.conn.in_transaction
            if not outer_txn:
                self.conn.execute("BEGIN IMMEDIATE")
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    if not outer_txn:
                        try:
                            self.conn.execute("ROLLBACK")
                        except Exception:
                            pass
                    if dup_stored.get("changes") == want:
                        return dup_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if self.conn.execute(
                    "SELECT row_id FROM board_rows WHERE row_id=?", (row_id,)
                ).fetchone():
                    raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
                self.conn.execute(
                    "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
                    " VALUES (?,?,?,?,?)",
                    (row_id, "income", record["display_tab_id"], 1, _canonical(record)),
                )
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json, event_id,"
                    " change_mode, actor, created_at, client_request_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row_id, 1, _canonical({}), _canonical(record), "",
                     "exception", actor, created_at, client_request_id),
                )
                self._enqueue_ledger(
                    outbox_id=outbox_id, stream_id=f"row-{row_id}",
                    action="propose", target=record["source_event_id"],
                    rationale=f"은행 가져오기 {batch_id} 행 {row_id}", actor=actor,
                )
                self.conn.execute(
                    "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                    " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                    (client_request_id, row_id, 1,
                     _canonical({"row_id": row_id, "expected_revision": 1,
                                 "changes": want,
                                 "change_mode": "exception",
                                 "source_event_id": record["source_event_id"],
                                 "actor": actor, "new_revision": 1,
                                 "result": {"outcome": "saved", "row_id": row_id,
                                            "revision": 1, "event_id": None,
                                            "request_id": client_request_id,
                                            "ledger_pending": True}}),
                     1, created_at),
                )
                if not outer_txn:
                    self.conn.execute("COMMIT")
            except SaveError:
                if not outer_txn:
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
            except sqlite3.IntegrityError:
                if not outer_txn:
                    try:
                        self.conn.execute("ROLLBACK")
                    except Exception:
                        pass
                found = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if found:
                    retry_stored = json.loads(found[0])
                    if retry_stored.get("changes") == want:
                        return retry_stored["result"]
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                raise SaveError("REQUEST_ID_REUSED", "이미 있는 행이에요")
            except Exception:
                if not outer_txn:
                    self.conn.execute("ROLLBACK")
                raise
            if outer_txn:
                return {"outcome": "saved", "row_id": row_id, "revision": 1,
                        "event_id": None, "request_id": client_request_id,
                        "ledger_pending": True}
            self._relay_outbox([outbox_id])
            final = self._finalize_board_request(client_request_id)
            if final is not None:
                return final
            return {"outcome": "saved", "row_id": row_id, "revision": 1,
                    "event_id": None, "request_id": client_request_id,
                    "ledger_pending": True}

    def _stream_action(self, stream_id: str, default: str = "correct") -> str:
        try:
            return "correct" if stream_id in self.ledger.streams() else "propose"
        except Exception:
            return default

    def _outbox_commit(self) -> None:
        try:
            if not self.conn.in_transaction:
                self.conn.commit()
        except Exception:
            pass

    def _enqueue_ledger(self, *, outbox_id: str, stream_id: str, action: str,
                        target, rationale: str, actor: str) -> None:
        """같은 쓰기 트랜잭션 안에 정본 사건 payload를 남긴다. 호출자는 트랜잭션 소유."""
        self.conn.execute(
            "INSERT OR IGNORE INTO ledger_outbox(outbox_id, stream_id, action,"
            " target_direct_event_key, rationale, actor_local_id,"
            " event_id, relayed, created_at)"
            " VALUES (?,?,?,?,?,?,'',0,?)",
            (outbox_id, stream_id, action, target, rationale, actor, _utc_now()),
        )

    def _relay_outbox(self, outbox_ids=None) -> dict:
        """COMMIT 뒤 내구성 기록에서 별도 DB로 동일 payload를 복제한다."""
        if outbox_ids is None:
            rows = self.conn.execute(
                "SELECT outbox_id, stream_id, action, target_direct_event_key,"
                " rationale, actor_local_id FROM ledger_outbox WHERE relayed=0"
            ).fetchall()
        else:
            rows = []
            for oid in dict.fromkeys(outbox_ids):
                row = self.conn.execute(
                    "SELECT outbox_id, stream_id, action, target_direct_event_key,"
                    " rationale, actor_local_id FROM ledger_outbox"
                    " WHERE outbox_id=? AND relayed=0",
                    (oid,),
                ).fetchone()
                if row:
                    rows.append(row)
        results = {}
        for oid, stream_id, action, target, rationale, actor in rows:
            try:
                event, _ = self.ledger.append(
                    stream_id=stream_id, action=action,
                    target_direct_event_key=target, rationale=rationale,
                    actor_local_id=actor, client_request_id=oid,
                )
                event_id = event["event_id"]
            except Exception:
                results[oid] = None
                continue
            try:
                self.conn.execute(
                    "UPDATE ledger_outbox SET event_id=?, relayed=1 WHERE outbox_id=?",
                    (event_id, oid),
                )
            except Exception:
                results[oid] = None
                continue
            self._outbox_commit()
            results[oid] = event_id
        self._outbox_commit()
        return results

    def _outbox_event(self, outbox_id: str):
        row = self.conn.execute(
            "SELECT event_id FROM ledger_outbox WHERE outbox_id=? AND relayed=1",
            (outbox_id,),
        ).fetchone()
        if row and row[0]:
            return row[0]
        found = None
        try:
            found = self.ledger.find_by_client_request(outbox_id)
        except Exception:
            found = None
        return found["event_id"] if found else None

    def _finalize_board_request(self, client_request_id: str):
        row = self.conn.execute(
            "SELECT result_json, ledger_pending FROM board_requests WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if row is None:
            return None
        stored = json.loads(row[0])
        if not row[1]:
            return stored.get("result")
        event_id = self._outbox_event(f"ledger-{client_request_id}")
        if not event_id:
            return None
        new_revision = stored.get("new_revision")
        if new_revision is None:
            expected = stored.get("expected_revision", 1)
            changes = stored.get("changes", {})
            new_revision = 1 if changes.get("create") or changes.get("import") else expected + 1
        row_id = stored["row_id"]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "UPDATE board_revisions SET event_id=? WHERE row_id=? AND revision=?",
                (event_id, row_id, new_revision),
            )
            self.conn.execute(
                "UPDATE income_allocation_history SET event_id=?"
                " WHERE client_request_id=? AND event_id=''",
                (event_id, client_request_id),
            )
            self.conn.execute(
                "UPDATE board_manual_overrides SET event_id=? WHERE row_id=? AND event_id=''",
                (event_id, row_id),
            )
            learning_case_id = stored.get("result", {}).get("learning_case_id")
            if learning_case_id:
                self.conn.execute(
                    "UPDATE board_learning_cases SET event_id=? WHERE case_id=?",
                    (event_id, learning_case_id),
                )
            stored["result"]["event_id"] = event_id
            stored["result"]["ledger_pending"] = False
            self.conn.execute(
                "UPDATE board_requests SET result_json=?, ledger_pending=0"
                " WHERE client_request_id=?",
                (_canonical(stored), client_request_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return stored["result"]

    def _finalize_trip_request(self, client_request_id: str):
        row = self.conn.execute(
            "SELECT result_json, ledger_pending FROM trip_tab_requests WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if row is None:
            return None
        stored = json.loads(row[0])
        if not row[1]:
            return stored.get("result")
        tab_id = stored["tab_id"]
        new_revision = stored.get("new_revision", stored.get("expected_revision", 1) + 1)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if stored.get("source") == "trip-delete":
                for row_id, new_rev, _source_event_id, _prev_rev in stored.get("moved_rows", []):
                    event_id = self._outbox_event(f"ledger-{client_request_id}:{row_id}")
                    if event_id:
                        self.conn.execute(
                            "UPDATE board_revisions SET event_id=? WHERE row_id=? AND revision=?",
                            (event_id, row_id, new_rev),
                        )
            event_id = self._outbox_event(f"ledger-trip-{client_request_id}")
            if not event_id:
                self.conn.execute("ROLLBACK")
                return None
            self.conn.execute(
                "UPDATE trip_tab_history SET event_id=? WHERE tab_id=? AND revision=?",
                (event_id, tab_id, new_revision),
            )
            stored["result"]["event_id"] = event_id
            stored["result"]["ledger_pending"] = False
            self.conn.execute(
                "UPDATE trip_tab_requests SET result_json=?, ledger_pending=0"
                " WHERE client_request_id=?",
                (_canonical(stored), client_request_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return stored["result"]

    def _finalize_alloc_request(self, client_request_id: str):
        row = self.conn.execute(
            "SELECT result_json, ledger_pending FROM income_allocation_requests"
            " WHERE client_request_id=?",
            (client_request_id,),
        ).fetchone()
        if row is None:
            return None
        stored = json.loads(row[0])
        if not row[1]:
            return stored.get("result")
        event_id = self._outbox_event(f"ledger-{client_request_id}")
        if not event_id:
            return None
        source_row_id = stored["source_row_id"]
        new_revision = stored.get("new_revision",
                                  stored.get("expected_source_revision", 1) + 1)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "UPDATE board_revisions SET event_id=? WHERE row_id=? AND revision=?",
                (event_id, source_row_id, new_revision),
            )
            stored["result"]["event_id"] = event_id
            stored["result"]["ledger_pending"] = False
            self.conn.execute(
                "UPDATE income_allocation_requests SET result_json=?, ledger_pending=0"
                " WHERE client_request_id=?",
                (_canonical(stored), client_request_id),
            )
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return stored["result"]

    def _replay_trip_pending(self) -> None:
        try:
            pending = self.conn.execute(
                "SELECT client_request_id FROM trip_tab_requests"
                " WHERE ledger_pending=1"
            ).fetchall()
        except Exception:
            return
        self._relay_outbox()
        for (client_request_id,) in pending:
            try:
                self._finalize_trip_request(client_request_id)
            except Exception:
                continue

    def _replay_allocation_pending(self) -> None:
        try:
            pending = self.conn.execute(
                "SELECT client_request_id FROM income_allocation_requests"
                " WHERE ledger_pending=1"
            ).fetchall()
        except Exception:
            return
        self._relay_outbox()
        for (client_request_id,) in pending:
            try:
                self._finalize_alloc_request(client_request_id)
            except Exception:
                continue

    def _replay_pending(self) -> None:
        self._replay_trip_pending()
        self._replay_allocation_pending()
        self._relay_outbox()
        try:
            rows = self.conn.execute(
                "SELECT client_request_id FROM board_requests WHERE ledger_pending=1"
            ).fetchall()
        except Exception:
            return
        for (client_request_id,) in rows:
            try:
                self._finalize_board_request(client_request_id)
            except Exception:
                continue
