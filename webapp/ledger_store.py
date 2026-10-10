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

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import ledger_board as board
from .operator_ledger import LedgerError, OperatorLedger
from .space_guard import SpaceRefused, reserve

# Bytes one row save is assumed to need. A row is small; the number exists so
# the refusal says how much it wanted, not because the estimate is precise.
SAVE_BYTES_PER_ROW = 8 * 1024

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
-- A rule learned from a reviewed source row, rather than from a board row.
--
-- `board_learning_cases` is keyed to a real ledger row, because a rule learned
-- from that row must be able to point back at it. A reviewed source row has no
-- board row to point at, and inventing one would put a row id in the record that
-- names nothing. So the proof lives here instead: which review binding and which
-- source ref were verified when the case was registered.
--
-- `context_json` holds derived facts only — a hash of the ref, a normalised
-- merchant, a card kind. Never a person, a reservation number or a note.
CREATE TABLE IF NOT EXISTS classification_source_cases (
    case_id TEXT PRIMARY KEY,
    binding TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classification_rules (
    rule_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    base_rule_version INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    apply_existing INTEGER NOT NULL DEFAULT 0,
    apply_future INTEGER NOT NULL DEFAULT 0,
    rule_hash TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    learning_case_id TEXT NOT NULL DEFAULT '',
    future_boundary_rowid INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_previews (
    preview_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    rule_hash TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    apply_existing INTEGER NOT NULL DEFAULT 0,
    apply_future INTEGER NOT NULL DEFAULT 0,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_apply_requests (
    client_request_id TEXT PRIMARY KEY,
    preview_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classification_rule_versions (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    base_rule_version INTEGER NOT NULL,
    previous_version INTEGER,
    previous_rule_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    rule_hash TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    confirmation_json TEXT NOT NULL DEFAULT '{}',
    actor TEXT NOT NULL DEFAULT 'owner',
    change_kind TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS classification_rule_versions_rule
    ON classification_rule_versions(rule_id, entry_id);
CREATE TABLE IF NOT EXISTS rule_lifecycle_requests (
    client_request_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_supersessions (
    supersession_id TEXT PRIMARY KEY,
    new_rule_id TEXT NOT NULL,
    old_rule_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_dialogs (
    case_id TEXT PRIMARY KEY,
    row_id TEXT NOT NULL,
    row_revision INTEGER NOT NULL,
    draft_json TEXT NOT NULL,
    apply_existing INTEGER NOT NULL DEFAULT 0,
    apply_future INTEGER NOT NULL DEFAULT 0,
    dialog_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_questions (
    question_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    question_key TEXT NOT NULL,
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_answer_requests (
    client_request_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_conversations (
    conversation_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    rule_id TEXT,
    rule_version INTEGER,
    handoff_summary TEXT NOT NULL DEFAULT '',
    active_provider TEXT,
    active_model_id TEXT,
    state TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_turns (
    turn_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    state TEXT NOT NULL,
    process_run_id TEXT NOT NULL DEFAULT '',
    abandoned_reason TEXT NOT NULL DEFAULT '',
    adopted_attempt_id TEXT,
    adopted_provider TEXT,
    reason_code TEXT,
    is_real_call INTEGER NOT NULL DEFAULT 0,
    switch_count INTEGER NOT NULL DEFAULT 0,
    draft_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_turn_attempts (
    attempt_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    reason_code TEXT,
    send_error TEXT,
    adopted INTEGER NOT NULL DEFAULT 0,
    is_real_call INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_process_leases (
    run_id TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_orphan_reviews (
    turn_id TEXT PRIMARY KEY,
    process_run_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_turn_requests (
    client_request_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rule_late_responses (
    late_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
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
    -- Where `prepared_by_name` came from: 'owner_profile', 'manual', 'seed', or
    -- '' for a row written before this column existed. It is provenance, not a
    -- flag, so a person who genuinely typed the same string as the old demo
    -- placeholder is not treated as a placeholder by comparing text.
    assignee_source TEXT NOT NULL DEFAULT '',
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
-- One row: the owner-entered company name and default assignee. These are the
-- source for NEW trips only. A trip keeps the values it was created with, so
-- changing this row never rewrites a trip that already exists — which is what
-- stops a name change from silently overwriting a record whose true author is
-- unknown.
CREATE TABLE IF NOT EXISTS owner_profile (
    profile_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL DEFAULT '',
    assignee_name TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    client_request_id TEXT NOT NULL DEFAULT ''
);
-- The audit for that row, in the same shape as `trip_tab_history`: what it was,
-- what it became, who changed it and under which request. Written in the same
-- transaction as the change, so a profile and its history cannot disagree.
CREATE TABLE IF NOT EXISTS owner_profile_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision INTEGER NOT NULL,
    change_kind TEXT NOT NULL,
    prev_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    client_request_id TEXT NOT NULL
);
-- The request ledger for that row, matching `trip_tab_requests`: the same
-- request id replays its stored result, and the same request id with different
-- input is a conflict rather than a second write.
CREATE TABLE IF NOT EXISTS owner_profile_requests (
    client_request_id TEXT PRIMARY KEY,
    input_digest TEXT NOT NULL,
    result_json TEXT NOT NULL,
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
-- The reviewed source facts, kept verbatim.
--
-- `facts_json` is the card master's seventeen original columns exactly as the
-- source stated them, and `fact_digest` is over those columns alone. Both dates
-- are kept, the sign is kept, the currency is kept, and the cancellation flag is
-- kept, because a summary of a card fact is a different fact.
CREATE TABLE IF NOT EXISTS source_fact_rows (
    source_event_key TEXT PRIMARY KEY,
    row_id TEXT NOT NULL UNIQUE,
    fact_digest TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    workbook_ref TEXT NOT NULL,
    review_ref TEXT NOT NULL,
    review_snapshot_sha256 TEXT NOT NULL,
    applied_request_id TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
-- One apply request, and the digest of the inputs it was made from. A repeated
-- request id with a different digest is a conflict rather than a second run.
CREATE TABLE IF NOT EXISTS source_fact_applies (
    request_id TEXT PRIMARY KEY,
    input_digest TEXT NOT NULL,
    binding TEXT NOT NULL,
    choices_revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
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

#: The assignee written into a trip before the owner ever named one. It is kept
#: only so trips that already carry it can be *reported* as unconfirmed, never so
#: a new trip can be stamped with it: a placeholder that reaches a saved record
#: becomes a claim the ledger then makes about who wrote something.
LEGACY_SYNTHETIC_OWNER_NAME = "테스트 소유자"


def owner_assignee_default(conn) -> str:
    """The owner-entered default assignee, or "" when there is not one yet.

    There is no fallback name here on purpose. Before the owner has set one, a
    new trip's assignee is empty and the screen asks for it, because inventing a
    value would turn "nobody has confirmed this" into a fact on the record.
    """
    try:
        row = conn.execute(
            "SELECT assignee_name FROM owner_profile WHERE profile_id='owner'"
        ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    return str(row[0] or "").strip()


def company_name_default(conn) -> str:
    """The owner-entered company name, or "" when there is not one yet."""
    try:
        row = conn.execute(
            "SELECT company_name FROM owner_profile WHERE profile_id='owner'"
        ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    return str(row[0] or "").strip()


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


def space_refused_as_save_error(exc: SpaceRefused) -> SaveError:
    """Carry a space refusal in the shape the save callers already handle.

    Every state-changing path in this store now reserves space inside
    `_begin_write`, so the refusal arrives from many places rather than one. The
    caller of `save` already handles `SaveError`; letting a second exception
    class escape would make every caller learn a second way to be told that a
    write did not happen. The code is preserved so a caller can still tell a
    space refusal from an edit conflict.
    """
    return SaveError(exc.code, exc.message)


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


# One process-wide run id. Every LedgerStore in this process shares it, so a
# second connection in the same process never looks like a restart. A restarted
# process gets a new uuid, so a recycled pid cannot impersonate the old owner.
_PROCESS_RUN_ID = uuid.uuid4().hex
_PROCESS_PID = os.getpid()

# A lease is fresh while its heartbeat is inside this window. Overridable only so
# a test can shorten it; the default is minutes, not seconds.
LEASE_TTL_SECONDS = float(os.environ.get("WEBLEDGER_RULE_LEASE_TTL", "300"))


def _process_alive(pid):
    """True, False, or None when this process cannot tell.

    Never sends a signal. A pid that cannot be inspected is None, not False, so
    a turn is never recovered on a guess: the caller keeps it and records the
    reason for review.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_INVALID_PARAMETER = 87
        # use_last_error is what makes ctypes.get_last_error() meaningful here.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Only "no such process" proves the owner is gone. Every other
            # reason for a refused handle stays unknown.
            return False if ctypes.get_last_error() == ERROR_INVALID_PARAMETER else None
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return None
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists, this one just may not signal it.
        return True
    except OSError:
        return None
    return True


def _lease_age_seconds(heartbeat_at: str) -> float:
    import datetime as _dt

    try:
        moment = _dt.datetime.fromisoformat(heartbeat_at)
    except (TypeError, ValueError):
        return float("inf")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return (_dt.datetime.now(_dt.timezone.utc) - moment).total_seconds()


def _ensure_rule_turn_columns(conn) -> None:
    """Add the process ownership columns to a database created earlier."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(rule_turns)").fetchall()}
    if "process_run_id" not in cols:
        conn.execute("ALTER TABLE rule_turns ADD COLUMN process_run_id TEXT NOT NULL DEFAULT ''")
    if "abandoned_reason" not in cols:
        conn.execute("ALTER TABLE rule_turns ADD COLUMN abandoned_reason TEXT NOT NULL DEFAULT ''")


def _ensure_trip_tab_columns(conn) -> None:
    """Add the APP_SPEC 3 tab-model columns to a database created earlier.

    Section 3 lists `event_year`, `tab_kind`, `authority_status`,
    `source_sha256` and `sort_order` as logical responsibilities and says not to
    add a new table when the existing schema can carry them. They are added here
    as columns with defaults, so a database written before this change keeps
    every row and reads the new fields at their neutral values.

    `tab_lifecycle` is deliberately not a column: `archived` and `deleted`
    already hold it, and a third copy would be free to disagree with them. It is
    derived on read instead.
    """
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(trip_tabs)").fetchall()}
    if "event_year" not in cols:
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN event_year INTEGER NOT NULL DEFAULT 0")
    if "tab_kind" not in cols:
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN tab_kind TEXT NOT NULL DEFAULT 'trip'")
    if "authority_status" not in cols:
        # Never 'authoritative' by default: section 3 says making a screen tab
        # is not what makes a schedule authoritative, and 4.2 says a tab with no
        # authority basis is needs_review.
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN authority_status TEXT NOT NULL"
            " DEFAULT 'needs_review'")
    if "source_sha256" not in cols:
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN source_sha256 TEXT NOT NULL DEFAULT ''")
    if "sort_order" not in cols:
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    if "assignee_source" not in cols:
        # Added empty on purpose. Filling it for existing rows would be a
        # migration: it would assert where a historical value came from, and for
        # these rows nobody knows. An empty source reads as "unconfirmed", which
        # is the true state, and the owner resolves it by editing the trip.
        conn.execute(
            "ALTER TABLE trip_tabs ADD COLUMN assignee_source TEXT NOT NULL DEFAULT ''")


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
            source_merchant=row.get("source_merchant", ""),
            event_kind=row.get("event_kind", ""),
            card_kind=row.get("card_kind", ""),
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

    def __init__(self, path, ledger: OperatorLedger | None = None,
                 seed_demo: bool = True):
        """Open the working database.

        `seed_demo` defaults to True so every existing caller keeps the demo
        board a developer expects. SPEC_REFINEMENT 18.3 5항 forbids synthetic
        seed rows at an *operational* start, so a process that is about to
        serve a real ledger passes False: an empty data root then stays empty
        and the operator sees no fabricated trips.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        first_create = not self.path.exists()
        self.conn = sqlite3.connect(
            str(self.path), timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        self._lock = threading.RLock()
        self._space_hold = None
        # A pending turn belongs to the process that sent it. Every store in
        # this process shares one run id, so a second connection is not a
        # restart.
        self._process_run_id = _PROCESS_RUN_ID
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA_SQL)
        _ensure_correction_columns(self.conn)
        _ensure_rule_turn_columns(self.conn)
        _ensure_trip_tab_columns(self.conn)
        self._register_process_lease()
        if seed_demo:
            if first_create:
                self._seed()
            self._ensure_trips()
        already_unified = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_events'").fetchone()
        self._embedded_audit = ledger is None and (
            os.environ.get('WEBLEDGER_UNIFIED_DB') == '1' or bool(already_unified))
        operator_path = self.path.with_suffix(".operator.sqlite")
        if self._embedded_audit:
            self.ledger = OperatorLedger.in_database(
                self.conn, self.path, legacy_path=operator_path)
        else:
            if not operator_path.exists():
                OperatorLedger.create(str(operator_path))
            self.ledger = ledger or OperatorLedger(operator_path)

    def _ensure_trips(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM trip_tabs").fetchone()[0]
        if count:
            return
        today = _seoul_today()
        assignee = owner_assignee_default(self.conn)
        # The demo seed says where its assignee came from, so a fixture that
        # prints on an exported sheet is distinguishable from a row whose author
        # nobody recorded.
        source = "owner_profile" if assignee else "seed"
        for trip in board.TRIPS:
            self.conn.execute(
                "INSERT INTO trip_tabs(tab_id, display_key, destination, starts_on,"
                " ends_on, prepared_on, prepared_by_name, assignee_source,"
                " archived, deleted, revision)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (trip["tab_id"], trip["display_key"], trip.get("destination", ""),
                 trip.get("starts_on", ""), trip.get("ends_on", ""),
                 today, assignee, source, 0, 0, 1),
            )
        self.conn.commit()

    def _begin_write(self, *, needed_bytes: int = None, code: str = "WRITE_NO_SPACE",
                     what: str = "데이터를 쓰는 데") -> None:
        """Open a write transaction, after reserving space for it.

        Every state-changing path in this store funnels through here, which is
        the point: a new write method cannot join the ones that are protected
        without adding itself to this one line. The previous version guarded
        only `save`, and 47 other entry points wrote to the same database
        without the policy 19.3 describes.

        The reservation is taken before the transaction opens, so a refusal
        leaves no open transaction and nothing half-applied.
        """
        from . import space_guard

        hold = space_guard.reserve_write(
            self.path,
            space_guard.WRITE_BYTES if needed_bytes is None else needed_bytes,
            code=code, what=what)
        self._space_hold = hold
        self._space_hold.__enter__()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._release_write_space()
            raise

    def _commit_write(self) -> None:
        """End a guarded write transaction and hand the reserved space back.

        Idempotent on purpose: a path that rolls back and then commits, or
        rolls back twice, must not double-release or fail. Releasing a
        reservation that is not held is a no-op.
        """
        try:
            if self.conn.in_transaction:
                self.conn.execute("COMMIT")
            else:
                self.conn.commit()
        finally:
            self._release_write_space()

    def _rollback_write(self) -> None:
        """Abandon a guarded write transaction and give the space back.

        A rollback is how a refused or failed write returns, so holding the
        reservation through it would shrink the volume's apparent headroom
        with every failed attempt until good writes were refused too.
        """
        try:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
        finally:
            self._release_write_space()

    def _release_write_space(self) -> None:
        hold = getattr(self, "_space_hold", None)
        if hold is not None:
            self._space_hold = None
            hold.__exit__(None, None, None)

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
            audit_connection = getattr(self.ledger, 'conn', None)
            if audit_connection is not None and audit_connection is not self.conn:
                audit_connection.close()
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

    def record_conflict(self, *, row_id: str, expected_revision: int,
                        attempted: dict, client_request_id: str = "",
                        actor: str = "owner") -> dict:
        """Note that a save was refused because the row had moved on.

        APP_SPEC 9 lists `충돌` among the states that are told apart "in the DB
        and in the row detail", and section 8 asks the export dialog for the
        number of rows in conflict. Section 6 says to reuse the existing
        append-only change ledger rather than add a table, so this writes one
        `board_revisions` row with `kind='conflict'`.

        It is a note, not a save: the row's revision, values and totals are not
        touched, and the refused request is not recorded as a request result. It
        is written in its own transaction after the save was rolled back, so the
        one-transaction guarantee of a save (REVIEW R01) is unchanged.
        """
        current = self.get_row(row_id)
        if current is None:
            return {}
        note = {
            "row_id": row_id, "expected_revision": expected_revision,
            "current_revision": current.get("revision"),
            "attempted": attempted,
            "at": _utc_now(),
        }
        with self._lock:
            # This note is written in its own transaction, so it never reaches
            # `_begin_write`. It still appends a revision row to the same
            # database, so it takes the same space reservation; a conflict note
            # that could not be stored would leave the UI showing a state the
            # database does not have.
            self._begin_write(code="CONFLICT_NOTE_NO_SPACE",
                              what="충돌 기록을 남기는 데")
            try:
                self.conn.execute(
                    "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
                    " event_id, change_mode, actor, created_at, client_request_id,"
                    " kind, reverts_event_id) VALUES (?,?,?,?,?,?,?,?,?,?,'')",
                    (row_id, int(current.get("revision") or 0),
                     _canonical(current), _canonical(note), "", "conflict", actor,
                     _utc_now(), str(client_request_id or ""), "conflict"),
                )
                self._commit_write()
            except SpaceRefused:
                self._rollback_write()
                raise
            except Exception:
                self._rollback_write()
                raise
        return note

    def row_conflict(self, row_id: str):
        """The unresolved conflict on this row, or None.

        Resolved means: the row's newest ledger event is not a conflict note. A
        later successful save therefore clears it, which is the only way it
        should clear.
        """
        row = self.conn.execute(
            "SELECT kind FROM board_revisions WHERE row_id=?"
            " ORDER BY revision DESC, id DESC LIMIT 1", (row_id,)).fetchone()
        if row is None or (row[0] or "save") != "conflict":
            return None
        last = self.conn.execute(
            "SELECT revision, new_json, actor, created_at, client_request_id"
            " FROM board_revisions WHERE row_id=? AND kind='conflict'"
            " ORDER BY revision DESC, id DESC LIMIT 1", (row_id,)).fetchone()
        if last is None:
            return None
        try:
            note = json.loads(last[1])
        except ValueError:
            note = {}
        return {"row_id": row_id, "revision": last[0], "actor": last[2],
                "created_at": last[3], "client_request_id": last[4],
                "expected_revision": note.get("expected_revision"),
                "current_revision": note.get("current_revision"),
                "attempted": note.get("attempted") or {}}

    def conflicting_row_ids(self) -> set:
        """Every row whose newest ledger event is a conflict note."""
        rows = self.conn.execute(
            "SELECT row_id, kind FROM board_revisions"
            " ORDER BY row_id, revision, id").fetchall()
        newest = {}
        for row_id, kind in rows:
            newest[row_id] = kind or "save"
        return {row_id for row_id, kind in newest.items() if kind == "conflict"}

    def list_history(self, row_id: str):
        try:
            rows = self.conn.execute(
                "SELECT revision, prev_json, new_json, event_id, change_mode, actor, created_at,"
                " client_request_id, kind, reverts_event_id FROM board_revisions"
                # a conflict note carries the row's current revision, so `id`
                # breaks the tie and keeps it after the save it refused
                " WHERE row_id=? ORDER BY revision, id",
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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
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
                self._rollback_write()
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

    # --- Phase 6A classification rules ---------------------------------
    # Draft -> impact preview -> confirm/apply. The draft reuses the learning
    # case that save(change_mode="rule_change") already created. Apply does
    # not call save(), because save() records every changed field as a manual
    # override and a rule must not look like a manual lock.

    FUTURE_PATH_CONNECTED = ("card_import.import_row",)
    FUTURE_PATH_NOT_CONNECTED = (
        "bank_income", "direct_income", "manual_expense",
    )

    # Per-source rule condition contract. Only the card source is connected.
    # Bank income, direct income, and manual expense rows have no card source
    # keys, so a rule that needs merchant, direction, or card kind does not
    # match them. Nothing is filled in from the amount sign or from the
    # editable description.
    SOURCE_CONDITION_CONTRACT = {
        "card": {
            "connected": True,
            "entry_path": "card_import.import_row",
            "source_keys": ("source_merchant", "event_kind", "card_kind"),
            "lineage": "card_import_rows.raw_json -> classify_parsed",
        },
        "bank_income": {"connected": False, "reason": "no card source keys"},
        "direct_income": {"connected": False, "reason": "no card source keys"},
        "manual_expense": {"connected": False, "reason": "no card source keys"},
    }

    def card_source_keys(self, row: dict) -> dict:
        """Read direction, card kind, and source merchant from the card lineage.

        A row imported by this code carries the keys in its payload. A row that
        predates it is resolved from the stored card source row through the
        same `classify_parsed` contract, so an existing row and a new upload
        produce identical keys. No card lineage means no keys, and the caller
        keeps the condition unmatched instead of guessing.
        """
        import json as _json

        from .card_import import classify_parsed

        row_id = str(row.get("row_id") or "")
        if row.get("source_merchant") or row.get("event_kind") or row.get("card_kind"):
            return {
                "source_merchant": str(row.get("source_merchant") or ""),
                "event_kind": str(row.get("event_kind") or ""),
                "card_kind": str(row.get("card_kind") or ""),
            }
        raw = None
        if row_id.startswith("imp-") and len(row_id) > 4:
            found = self.conn.execute(
                "SELECT raw_json FROM card_import_rows WHERE stable_key LIKE ?"
                " ORDER BY batch_id, row_index LIMIT 1", (row_id[4:] + "%",)).fetchone()
            if found:
                raw = found[0]
        if raw is None and row.get("source_event_id"):
            target = str(row["source_event_id"])
            for (candidate,) in self.conn.execute(
                    "SELECT raw_json FROM card_import_rows ORDER BY batch_id, row_index"):
                try:
                    fields = _json.loads(candidate)
                except ValueError:
                    continue
                if str(fields.get("approval_no") or "").strip() == target:
                    raw = candidate
                    break
        if raw is None:
            return {}
        try:
            fields = _json.loads(raw)
        except ValueError:
            return {}
        ok, event = classify_parsed(fields)
        if not ok or not isinstance(event, dict):
            return {}
        return {
            "source_merchant": str(event.get("merchant") or ""),
            "event_kind": str(event.get("event_kind") or ""),
            "card_kind": str(event.get("card_kind") or ""),
        }

    def manual_locked_fields(self, row_id: str) -> set:
        return {r[0] for r in self.conn.execute(
            "SELECT field FROM board_manual_overrides WHERE row_id=?",
            (row_id,)).fetchall()}

    def _draft_confirmation(self, rule: dict, case_id: str) -> dict:
        """User confirmation basis captured with a version record."""
        dialog = self._dialog_row(case_id) if case_id else None
        return {
            "learning_case_id": case_id,
            "answers": self._dialog_answers(case_id) if case_id else {},
            "apply_existing": None if dialog is None else bool(dialog[4]),
            "apply_future": None if dialog is None else bool(dialog[5]),
            "preview_id": None,
            "applied_rows": 0,
        }

    def _lifecycle_replay(self, client_request_id: str, operation: str, request: dict):
        row = self.conn.execute(
            "SELECT operation, request_json, result_json FROM rule_lifecycle_requests"
            " WHERE client_request_id=?", (client_request_id,)).fetchone()
        if row is None:
            return None
        if row[0] != operation or json.loads(row[1]) != request:
            raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
        return json.loads(row[2])

    def _store_lifecycle_request(self, client_request_id: str, operation: str,
                                 request: dict, result: dict, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO rule_lifecycle_requests(client_request_id, operation,"
            " request_json, result_json, created_at) VALUES (?,?,?,?,?)",
            (client_request_id, operation, _canonical(request), _canonical(result),
             created_at))

    def _rule_row(self, rule_id: str):
        return self.conn.execute(
            "SELECT rule_id, version, base_rule_version, status, apply_existing,"
            " apply_future, rule_hash, rule_json, learning_case_id,"
            " future_boundary_rowid, created_at, updated_at"
            " FROM classification_rules WHERE rule_id=?", (rule_id,)).fetchone()

    @staticmethod
    def _rule_dict(row) -> dict:
        rule = json.loads(row[7])
        return {
            "rule_id": row[0], "version": row[1], "base_rule_version": row[2],
            "status": row[3], "apply_existing": bool(row[4]),
            "apply_future": bool(row[5]), "rule_hash": row[6], "rule": rule,
            "learning_case_id": row[8], "future_boundary_rowid": row[9],
            "created_at": row[10], "updated_at": row[11],
        }

    def get_rule(self, rule_id: str):
        row = self._rule_row(rule_id)
        return None if row is None else self._rule_dict(row)

    def list_rules(self) -> list:
        return [self._rule_dict(r) for r in self.conn.execute(
            "SELECT rule_id, version, base_rule_version, status, apply_existing,"
            " apply_future, rule_hash, rule_json, learning_case_id,"
            " future_boundary_rowid, created_at, updated_at"
            " FROM classification_rules ORDER BY created_at, rule_id").fetchall()]

    def create_rule_draft(self, *, draft: dict, client_request_id: str,
                          actor: str = "owner") -> dict:
        """Validate one structured draft and store it as a draft rule."""
        from .classification_rules import RuleError, normalize_draft, rule_hash

        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        rule_id = f"rule-{client_request_id}"
        case_id = str((draft or {}).get("learning_case_id") or "").strip()
        with self._lock:
            self._replay_pending()
            try:
                rule = normalize_draft(draft, learning_case_id=case_id, rule_id=rule_id)
            except RuleError as exc:
                raise SaveError(exc.code, str(exc))
            digest = rule_hash(rule)
            existing = self._rule_row(rule_id)
            if existing is not None:
                if existing[6] != digest:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 초안을 보냈어요")
                return self._rule_dict(existing)
            if not case_id:
                raise SaveError("INVALID_VALUE", "규칙 대화 사례가 필요해요")
            case = self.conn.execute(
                "SELECT case_id, row_id, dialog_state FROM board_learning_cases WHERE case_id=?",
                (case_id,)).fetchone()
            if case is None and self.conn.execute(
                    "SELECT case_id FROM classification_source_cases"
                    " WHERE case_id=?", (case_id,)).fetchone() is None:
                raise SaveError("INVALID_VALUE", "없는 규칙 대화 사례예요")
            if self.case_is_one_off(case_id):
                raise SaveError(
                    "RULE_ONE_OFF",
                    "이번 거래만 적용하기로 한 답변이 있어 규칙을 만들지 않아요")
            created_at = _utc_now()
            self._begin_write()
            try:
                if self._rule_row(rule_id) is not None:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 초안을 보냈어요")
                self.conn.execute(
                    "INSERT INTO classification_rules(rule_id, version, base_rule_version,"
                    " status, apply_existing, apply_future, rule_hash, rule_json,"
                    " learning_case_id, future_boundary_rowid, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rule_id, rule["version"], rule["base_rule_version"], "draft", 0, 0,
                     digest, _canonical(rule), case_id, None, created_at, created_at),
                )
                self._record_rule_version(
                    rule_id, rule["version"], rule["base_rule_version"], "draft",
                    digest, rule, "created", client_request_id, created_at,
                    previous_version=None, previous_rule_hash="",
                    confirmation=self._draft_confirmation(rule, case_id),
                    actor=actor)
                self.conn.execute(
                    "UPDATE board_learning_cases SET dialog_state='drafted' WHERE case_id=?",
                    (case_id,))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return self._rule_dict(self._rule_row(rule_id))

    def _rule_candidate_rows(self, rule: dict) -> list:
        rows = []
        for row in self.conn.execute(
                "SELECT row_id, row_kind, display_tab_id, revision, payload_json"
                " FROM board_rows WHERE row_kind!='income' ORDER BY rowid").fetchall():
            payload = json.loads(row[4])
            payload["row_id"] = row[0]
            payload["revision"] = row[3]
            payload.update(self.card_source_keys(payload))
            rows.append(payload)
        return rows

    def build_rule_preview(self, rule_id: str, *, apply_existing: bool,
                           apply_future: bool) -> dict:
        """Server-side impact preview. Never trusts a client-side count."""
        from .classification_rules import (condition_source_report, find_conflicts,
                                           find_same_effect_rules, plan_effect,
                                           rule_matches)
        from .contracts import sha256_text

        stored = self.get_rule(rule_id)
        if stored is None:
            raise SaveError("INVALID_VALUE", "없는 규칙이에요")
        if stored["learning_case_id"] and self.case_is_one_off(stored["learning_case_id"]):
            raise SaveError(
                "RULE_ONE_OFF",
                "이번 거래만 적용하기로 한 답변이 있어 미리보기를 만들지 않아요")
        rule = stored["rule"]
        candidates = []
        excluded = []
        matched_rows = 0
        if apply_existing:
            active = [r for r in self.list_rules() if r["status"] == "active"]
            for row in self._rule_candidate_rows(rule):
                verdict = rule_matches(rule, row)
                if not verdict["matched"]:
                    continue
                matched_rows += 1
                conflicts = find_conflicts(rule, row, active)
                if conflicts:
                    excluded.append({
                        "row_id": row["row_id"], "revision": row["revision"],
                        "reason": "RULE_CONFLICT", "conflicts": conflicts,
                        "auto_resolved": False,
                        "resolution": "explicit_supersede_or_narrow_draft"})
                    continue
                same_effect = find_same_effect_rules(rule, row, active)
                locked = sorted(self.manual_locked_fields(row["row_id"]))
                changes = plan_effect(rule, row, locked)
                if locked:
                    excluded.append({
                        "row_id": row["row_id"], "revision": row["revision"],
                        "reason": "MANUAL_LOCK", "locked_fields": locked})
                if not changes:
                    excluded.append({
                        "row_id": row["row_id"], "revision": row["revision"],
                        "reason": "NO_CHANGE"})
                    continue
                candidates.append({
                    "row_id": row["row_id"], "revision": row["revision"],
                    "amount_krw": row.get("amount_krw"),
                    "from_tab_id": row.get("display_tab_id"),
                    "to_tab_id": changes.get("display_tab_id", row.get("display_tab_id")),
                    "changes": changes,
                    "locked_fields": locked,
                    "same_effect_rules": same_effect,
                })
        source_report = (condition_source_report(rule, self._rule_candidate_rows(rule))
                         if apply_existing else {})
        unavailable_conditions = sorted(
            field for field, info in source_report.items() if info["missing_source"])
        plan = {
            "rule_id": rule_id,
            "rule_hash": stored["rule_hash"],
            "rule_version": stored["version"],
            "base_rule_version": stored["base_rule_version"],
            "apply_existing": bool(apply_existing),
            "apply_future": bool(apply_future),
            "candidates": candidates,
            "excluded": excluded,
            "counts": {
                "matched_rows": matched_rows,
                "included_rows": len(candidates),
                "excluded_rows": len(excluded),
            },
            "amounts": self._rule_preview_amounts(candidates, rule) if apply_existing else {},
            "unavailable_conditions": unavailable_conditions,
            "condition_source_report": source_report,
            "conflict_policy": {
                "latest_rule_wins": False,
                "auto_resolve": False,
                "requires": "explicit_supersede_or_narrow_draft",
                "report": "conditions_and_example_row",
            },
            "source_condition_contract": {
                key: value for key, value in self.SOURCE_CONDITION_CONTRACT.items()},
            "future": {
                "path_connected": list(self.FUTURE_PATH_CONNECTED),
                "path_not_connected": list(self.FUTURE_PATH_NOT_CONNECTED),
                "note": "미래 거래 목록과 금액은 제시하지 않아요",
            } if apply_future else {
                "path_connected": [], "path_not_connected": [],
                "note": "미래 적용이 꺼져 있어요",
            },
        }
        plan["preview_id"] = sha256_text(_canonical({
            "rule_hash": plan["rule_hash"],
            "rule_version": plan["rule_version"],
            "base_rule_version": plan["base_rule_version"],
            "apply_existing": plan["apply_existing"],
            "apply_future": plan["apply_future"],
            "rows": [[c["row_id"], c["revision"]] for c in candidates],
        }))
        return plan

    def _rule_preview_amounts(self, candidates, rule=None) -> dict:
        """Per-tab expense totals before the change and after the projection.

        `before` is the sum of every current expense row in the tab, not only
        the matched rows, so the preview shows the real tab total.
        """
        current = {}
        for row in self._rule_candidate_rows(rule or {}):
            tab = str(row.get("display_tab_id") or "unclassified")
            current[tab] = current.get(tab, 0) + int(row.get("amount_krw") or 0)
        moving_out = {}
        moving_in = {}
        for item in candidates:
            amount = int(item.get("amount_krw") or 0)
            source = str(item.get("from_tab_id") or "unclassified")
            target = str(item.get("to_tab_id") or "unclassified")
            if source == target:
                continue
            moving_out[source] = moving_out.get(source, 0) + amount
            moving_in[target] = moving_in.get(target, 0) + amount
        tabs = sorted(set(current) | set(moving_out) | set(moving_in))
        return {
            tab: {
                "before": current.get(tab, 0),
                "moving_out": moving_out.get(tab, 0),
                "moving_in": moving_in.get(tab, 0),
                "after": (current.get(tab, 0) - moving_out.get(tab, 0)
                          + moving_in.get(tab, 0)),
            }
            for tab in tabs
        }

    def preview_rule(self, *, rule_id: str, apply_existing: bool,
                     apply_future: bool) -> dict:
        with self._lock:
            self._replay_pending()
            plan = self.build_rule_preview(
                rule_id, apply_existing=apply_existing, apply_future=apply_future)
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO rule_previews(preview_id, rule_id, rule_hash,"
                    " rule_version, apply_existing, apply_future, plan_json, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (plan["preview_id"], rule_id, plan["rule_hash"], plan["rule_version"],
                     int(apply_existing), int(apply_future), _canonical(plan), _utc_now()))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return plan

    def get_preview(self, preview_id: str):
        row = self.conn.execute(
            "SELECT preview_id, rule_id, rule_hash, rule_version, apply_existing,"
            " apply_future, plan_json FROM rule_previews WHERE preview_id=?",
            (preview_id,)).fetchone()
        if row is None:
            return None
        return {"preview_id": row[0], "rule_id": row[1], "rule_hash": row[2],
                "rule_version": row[3], "apply_existing": bool(row[4]),
                "apply_future": bool(row[5]), "plan": json.loads(row[6])}

    def active_future_rules(self) -> list:
        return [self._rule_dict(r) for r in self.conn.execute(
            "SELECT rule_id, version, base_rule_version, status, apply_existing,"
            " apply_future, rule_hash, rule_json, learning_case_id,"
            " future_boundary_rowid, created_at, updated_at"
            " FROM classification_rules WHERE status='active' AND apply_future=1"
            " ORDER BY created_at, rule_id").fetchall()]

    def apply_rule(self, *, preview_id: str, apply_existing: bool,
                   apply_future: bool, client_request_id: str,
                   selected_row_ids=None, actor: str = "owner") -> dict:
        """Apply one confirmed preview atomically, or reject the whole request."""
        from .classification_rules import plan_effect

        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {
            "preview_id": preview_id,
            "apply_existing": bool(apply_existing),
            "apply_future": bool(apply_future),
            "selected_row_ids": sorted(selected_row_ids) if selected_row_ids is not None else None,
        }
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT request_json, result_json FROM rule_apply_requests"
                " WHERE client_request_id=?", (client_request_id,)).fetchone()
            if existing:
                if json.loads(existing[0]) != request:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return json.loads(existing[1])
            preview = self.get_preview(preview_id)
            if preview is None:
                raise SaveError("INVALID_VALUE", "없는 미리보기예요")
            if bool(preview["apply_existing"]) != bool(apply_existing) or \
                    bool(preview["apply_future"]) != bool(apply_future):
                raise SaveError("PREVIEW_STALE", "확인한 적용 범위와 달라요. 새 미리보기를 받아 주세요")
            stored = self.get_rule(preview["rule_id"])
            if stored is None:
                raise SaveError("INVALID_VALUE", "없는 규칙이에요")
            if stored["status"] == "superseded":
                raise SaveError("RULE_SUPERSEDED", "이미 대체된 규칙이에요")
            if stored["learning_case_id"] and self.case_is_one_off(stored["learning_case_id"]):
                raise SaveError(
                    "RULE_ONE_OFF",
                    "이번 거래만 적용하기로 한 답변이 있어 적용하지 않아요")
            if stored["rule_hash"] != preview["rule_hash"] or stored["version"] != preview["rule_version"]:
                raise SaveError("PREVIEW_STALE", "규칙이 바뀌었어요. 새 미리보기를 받아 주세요")
            plan = preview["plan"]
            candidates = {c["row_id"]: c for c in plan["candidates"]}
            chosen = sorted(candidates) if request["selected_row_ids"] is None \
                else request["selected_row_ids"]
            unknown = [row_id for row_id in chosen if row_id not in candidates]
            if unknown:
                raise SaveError("PREVIEW_STALE", "선택한 행이 미리보기 범위와 달라요. 새 미리보기를 받아 주세요")
            resolved = []
            for row_id in chosen:
                item = candidates[row_id]
                current = self.get_row(row_id)
                if current is None:
                    raise SaveError("PREVIEW_STALE", f"선택한 행이 사라졌어요: {row_id}")
                if current["revision"] != item["revision"]:
                    raise SaveError("PREVIEW_STALE", f"선택한 행이 바뀌었어요: {row_id}")
                locked = self.manual_locked_fields(row_id)
                subject = dict(current)
                subject.update(self.card_source_keys(current))
                changes = plan_effect(stored["rule"], subject, locked)
                if not changes:
                    raise SaveError("PREVIEW_STALE", f"선택한 행의 변경이 사라졌어요: {row_id}")
                resolved.append((row_id, current, changes))
            created_at = _utc_now()
            applied = []
            self._begin_write()
            try:
                boundary = None
                if apply_future:
                    boundary = self.conn.execute(
                        "SELECT MAX(rowid) FROM board_rows").fetchone()[0]
                for row_id, current, changes in resolved:
                    fresh = self.conn.execute(
                        "SELECT revision FROM board_rows WHERE row_id=?", (row_id,)).fetchone()
                    if fresh is None or fresh[0] != current["revision"]:
                        raise SaveError("PREVIEW_STALE", f"선택한 행이 바뀌었어요: {row_id}")
                    new = dict(current)
                    for field, value in changes.items():
                        new[field] = value
                    new["revision"] = current["revision"] + 1
                    cursor = self.conn.execute(
                        "UPDATE board_rows SET display_tab_id=?, revision=?, payload_json=?"
                        " WHERE row_id=? AND revision=?",
                        (new.get("display_tab_id"), new["revision"], _canonical(new),
                         row_id, current["revision"]))
                    if cursor.rowcount == 0:
                        raise SaveError("PREVIEW_STALE", f"선택한 행이 바뀌었어요: {row_id}")
                    self.conn.execute(
                        "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
                        " event_id, change_mode, actor, created_at, client_request_id)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (row_id, new["revision"], _canonical(current), _canonical(new), "",
                         "rule_apply", actor, created_at, f"{client_request_id}-{row_id}"))
                    self._enqueue_ledger(
                        outbox_id=f"ledger-{client_request_id}-{row_id}",
                        stream_id=f"row-{row_id}",
                        action="correct" if current["revision"] > 1 else "propose",
                        target=current.get("source_event_id"),
                        rationale=f"규칙 적용 {preview['rule_id']} revision {new['revision']}",
                        actor=actor)
                    applied.append({"row_id": row_id, "revision": new["revision"],
                                    "changes": changes})
                status = "active" if (apply_existing or apply_future) else "draft"
                self.conn.execute(
                    "UPDATE classification_rules SET status=?, apply_existing=?,"
                    " apply_future=?, future_boundary_rowid=?, updated_at=?"
                    " WHERE rule_id=?",
                    (status, int(apply_existing), int(apply_future), boundary, created_at,
                     preview["rule_id"]))
                if stored["learning_case_id"]:
                    self.conn.execute(
                        "UPDATE board_learning_cases SET dialog_state='applied' WHERE case_id=?",
                        (stored["learning_case_id"],))
                result = {
                    "outcome": "applied" if applied else "noop",
                    "rule_id": preview["rule_id"],
                    "rule_hash": preview["rule_hash"],
                    "preview_id": preview_id,
                    "status": status,
                    "apply_existing": bool(apply_existing),
                    "apply_future": bool(apply_future),
                    "applied_rows": applied,
                    "applied_count": len(applied),
                    "future_boundary_rowid": boundary,
                    "request_id": client_request_id,
                }
                # Append-only: a confirmed apply writes its own history entry in
                # the same transaction, so an already committed entry keeps every
                # field it was written with.
                self._record_rule_version(
                    preview["rule_id"], stored["version"], stored["base_rule_version"],
                    status, stored["rule_hash"], stored["rule"], "apply",
                    client_request_id, created_at,
                    previous_version=stored["version"],
                    previous_rule_hash=stored["rule_hash"],
                    confirmation={
                        "learning_case_id": stored["learning_case_id"],
                        "answers": (self._dialog_answers(stored["learning_case_id"])
                                    if stored["learning_case_id"] else {}),
                        "apply_existing": bool(apply_existing),
                        "apply_future": bool(apply_future),
                        "preview_id": preview_id,
                        "preview_rule_hash": preview["rule_hash"],
                        "applied_rows": len(applied),
                        "applied_row_ids": [item["row_id"] for item in applied],
                        "rows_changed": len(applied),
                        "actor": actor,
                        "confirmed_at": created_at,
                    },
                    actor=actor)
                self._store_lifecycle_request(
                    client_request_id, "apply", request, result, created_at)
                self.conn.execute(
                    "INSERT INTO rule_apply_requests(client_request_id, preview_id,"
                    " request_json, result_json, created_at) VALUES (?,?,?,?,?)",
                    (client_request_id, preview_id, _canonical(request),
                     _canonical(result), created_at))
                self._commit_write()
            except SaveError:
                self._rollback_write()
                raise
            except sqlite3.IntegrityError:
                self._rollback_write()
                found = self.conn.execute(
                    "SELECT request_json, result_json FROM rule_apply_requests"
                    " WHERE client_request_id=?", (client_request_id,)).fetchone()
                if found and json.loads(found[0]) == request:
                    return json.loads(found[1])
                raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
            except Exception:
                self._rollback_write()
                raise
            for row_id, _current, _changes in resolved:
                self._relay_outbox([f"ledger-{client_request_id}-{row_id}"])
            return result

    def apply_active_rules_to_import(self, record: dict, event: dict) -> list:
        """Connect active future rules to the real card upload path.

        Only the card import path is connected. Bank income, direct income, and
        manual expense inserts are not connected and are reported as such.
        """
        from .classification_rules import RuleError, plan_effect, rule_matches

        applied = []
        if not event.get("merchant"):
            return applied
        for stored in self.active_future_rules():
            rule = stored["rule"]
            subject = dict(record)
            subject["source_merchant"] = event.get("merchant")
            subject["event_kind"] = event.get("event_kind")
            subject["card_kind"] = event.get("card_kind")
            try:
                verdict = rule_matches(rule, subject)
            except RuleError:
                continue
            if not verdict["matched"]:
                continue
            changes = plan_effect(rule, subject, ())
            if not changes:
                continue
            for field, value in changes.items():
                record[field] = value
            applied.append({"rule_id": stored["rule_id"], "changes": changes})
        return applied

    # --- Phase 6A-2 rule lifecycle and dialog state ---------------------
    # Nothing here calls a model or a network. The question set is derived
    # from the case row, the draft, and the answers already stored.

    def _record_rule_version(self, rule_id: str, version: int, base: int, status: str,
                             digest: str, rule: dict, change_kind: str,
                             client_request_id: str, created_at: str, *,
                             previous_version=None, previous_rule_hash: str = "",
                             confirmation: dict | None = None, actor: str = "owner") -> None:
        """Persist one full version record.

        The stored `rule_json` is the whole normalized draft, so conditions,
        effects, scope, exceptions, and the note survive. `previous_version` and
        `previous_rule_hash` keep the link to the version it was written from,
        and `confirmation_json` keeps the user confirmation basis: the dialog
        case, the answers, the chosen scope, and the confirmed preview.
        """
        self.conn.execute(
            "INSERT INTO classification_rule_versions(rule_id, version,"
            " base_rule_version, previous_version, previous_rule_hash, status,"
            " rule_hash, rule_json, confirmation_json, actor, change_kind,"
            " client_request_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rule_id, version, base, previous_version, previous_rule_hash or "", status,
             digest, _canonical(rule), _canonical(confirmation or {}), actor,
             change_kind, client_request_id, created_at))

    def list_rule_versions(self, rule_id: str) -> list:
        """Return the full stored history of one rule, oldest version first."""
        history = []
        for row in self.conn.execute(
                "SELECT entry_id, version, base_rule_version, previous_version,"
                " previous_rule_hash, status, rule_hash, rule_json, confirmation_json,"
                " actor, change_kind, client_request_id, created_at"
                " FROM classification_rule_versions WHERE rule_id=? ORDER BY entry_id",
                (rule_id,)).fetchall():
            rule = json.loads(row[7])
            history.append({
                "entry_id": row[0],
                "version": row[1],
                "base_rule_version": row[2],
                "previous_version": row[3],
                "previous_rule_hash": row[4],
                "status": row[5],
                "rule_hash": row[6],
                "rule": rule,
                "conditions": rule.get("conditions", {}),
                "optional_conditions": rule.get("optional_conditions", {}),
                "effects": rule.get("effects", {}),
                "scope": rule.get("scope", {}),
                "exceptions": rule.get("exceptions", []),
                "note": rule.get("note", ""),
                "evidence_case_ids": rule.get("evidence_case_ids", []),
                "confirmation": json.loads(row[8]),
                "actor": row[9],
                "change_kind": row[10],
                "client_request_id": row[11],
                "created_at": row[12],
            })
        return history

    def rule_history(self, rule_id: str) -> dict:
        """Version history plus the supersession links of one rule."""
        stored = self.get_rule(rule_id)
        history = self.list_rule_versions(rule_id)
        superseded_by = [
            {"superseded_by": row[0], "client_request_id": row[1], "created_at": row[2]}
            for row in self.conn.execute(
                "SELECT new_rule_id, client_request_id, created_at FROM rule_supersessions"
                " WHERE old_rule_id=? ORDER BY created_at", (rule_id,)).fetchall()
        ]
        supersedes = [
            {"supersedes": row[0], "client_request_id": row[1], "created_at": row[2]}
            for row in self.conn.execute(
                "SELECT old_rule_id, client_request_id, created_at FROM rule_supersessions"
                " WHERE new_rule_id=? ORDER BY created_at", (rule_id,)).fetchall()
        ]
        return {
            "rule_id": rule_id,
            "current": None if stored is None else {
                "version": stored["version"], "status": stored["status"],
                "base_rule_version": stored["base_rule_version"],
                "rule_hash": stored["rule_hash"],
                "apply_existing": stored["apply_existing"],
                "apply_future": stored["apply_future"],
                "future_boundary_rowid": stored["future_boundary_rowid"],
            },
            "versions": history,
            "version_count": len(history),
            "version_numbers": sorted({item["version"] for item in history}),
            "latest_version": history[-1]["version"] if history else None,
            "superseded_by": superseded_by,
            "supersedes": supersedes,
        }

    def revise_rule(self, *, rule_id: str, draft: dict, client_request_id: str,
                    actor: str = "owner") -> dict:
        """Create the next version of a rule and reset the confirmation.

        `base_rule_version` records the version this revision was written
        against, so a preview made for the previous version is refused.
        """
        from .classification_rules import RuleError, normalize_draft, rule_hash

        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        operation = "revise"
        request = {"rule_id": rule_id, "draft": draft or {}}
        with self._lock:
            self._replay_pending()
            replayed = self._lifecycle_replay(client_request_id, operation, request)
            if replayed is not None:
                return replayed
            stored = self.get_rule(rule_id)
            if stored is None:
                raise SaveError("INVALID_VALUE", "없는 규칙이에요")
            if stored["status"] == "superseded":
                raise SaveError("RULE_SUPERSEDED", "이미 대체된 규칙이에요")
            payload = dict(draft or {})
            payload["rule_id"] = rule_id
            payload["version"] = stored["version"] + 1
            payload["base_rule_version"] = stored["version"]
            try:
                rule = normalize_draft(
                    payload, learning_case_id=stored["learning_case_id"], rule_id=rule_id,
                    version=stored["version"] + 1, base_rule_version=stored["version"])
            except RuleError as exc:
                raise SaveError(exc.code, str(exc))
            digest = rule_hash(rule)
            created_at = _utc_now()
            self._begin_write()
            try:
                fresh = self.get_rule(rule_id)
                if fresh is None or fresh["version"] != stored["version"]:
                    raise SaveError("EDIT_CONFLICT", "규칙이 먼저 바뀌었어요. 최신 내용을 확인해 주세요")
                self.conn.execute(
                    "UPDATE classification_rules SET version=?, base_rule_version=?,"
                    " status='draft', apply_existing=0, apply_future=0, rule_hash=?,"
                    " rule_json=?, updated_at=? WHERE rule_id=?",
                    (rule["version"], rule["base_rule_version"], digest,
                     _canonical(rule), created_at, rule_id))
                self._record_rule_version(
                    rule_id, rule["version"], rule["base_rule_version"], "draft",
                    digest, rule, "revise", client_request_id, created_at,
                    previous_version=stored["version"],
                    previous_rule_hash=stored["rule_hash"],
                    confirmation=self._draft_confirmation(rule, stored["learning_case_id"]),
                    actor=actor)
                result = self.get_rule(rule_id)
                self._store_lifecycle_request(client_request_id, operation, request,
                                              result, created_at)
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def supersede_rule(self, *, new_rule_id: str, old_rule_id: str,
                       client_request_id: str, actor: str = "owner") -> dict:
        """Explicitly replace an older rule. Never automatic, never by age.

        Rows already changed by the old rule keep their values and their
        history. Only the future flag of the old rule stops.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        if new_rule_id == old_rule_id:
            raise SaveError("INVALID_VALUE", "대체할 규칙을 다른 규칙으로 골라 주세요")
        request = {"new_rule_id": new_rule_id, "old_rule_id": old_rule_id}
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT new_rule_id, old_rule_id, result_json FROM rule_supersessions"
                " WHERE client_request_id=?", (client_request_id,)).fetchone()
            if existing:
                if [existing[0], existing[1]] != [new_rule_id, old_rule_id]:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return json.loads(existing[2])
            new_rule = self.get_rule(new_rule_id)
            old_rule = self.get_rule(old_rule_id)
            if new_rule is None or old_rule is None:
                raise SaveError("INVALID_VALUE", "없는 규칙이에요")
            if old_rule["status"] == "superseded":
                raise SaveError("RULE_SUPERSEDED", "이미 대체된 규칙이에요")
            created_at = _utc_now()
            self._begin_write()
            try:
                if self.get_rule(old_rule_id)["status"] != old_rule["status"]:
                    raise SaveError("EDIT_CONFLICT", "규칙 상태가 먼저 바뀌었어요")
                self.conn.execute(
                    "UPDATE classification_rules SET status='superseded', apply_future=0,"
                    " updated_at=? WHERE rule_id=?", (created_at, old_rule_id))
                self._record_rule_version(
                    old_rule_id, old_rule["version"], old_rule["base_rule_version"],
                    "superseded", old_rule["rule_hash"], old_rule["rule"],
                    "superseded", client_request_id, created_at,
                    previous_version=old_rule["version"],
                    previous_rule_hash=old_rule["rule_hash"],
                    confirmation={
                        "superseded_by": new_rule_id,
                        "applied_existing": old_rule["apply_existing"],
                        "applied_future": old_rule["apply_future"],
                        "rows_changed": 0,
                        "history_kept": True,
                    },
                    actor=actor)
                result = {
                    "outcome": "superseded", "old_rule_id": old_rule_id,
                    "new_rule_id": new_rule_id, "old_status": "superseded",
                    "rows_changed": 0, "history_kept": True,
                    "request_id": client_request_id,
                }
                self.conn.execute(
                    "INSERT INTO rule_supersessions(supersession_id, new_rule_id,"
                    " old_rule_id, client_request_id, result_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (f"sup-{client_request_id}", new_rule_id, old_rule_id,
                     client_request_id, _canonical(result), created_at))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def update_rule_scope(self, *, rule_id: str, apply_existing: bool,
                          apply_future: bool, client_request_id: str,
                          actor: str = "owner") -> dict:
        """Change the scope switches of a rule without touching stored rows.

        Turning the future switch off does not revert a row that the rule
        already changed, and the applied history stays.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        operation = "scope"
        request = {"rule_id": rule_id, "apply_existing": bool(apply_existing),
                   "apply_future": bool(apply_future)}
        with self._lock:
            self._replay_pending()
            replayed = self._lifecycle_replay(client_request_id, operation, request)
            if replayed is not None:
                return replayed
            stored = self.get_rule(rule_id)
            if stored is None:
                raise SaveError("INVALID_VALUE", "없는 규칙이에요")
            if stored["status"] == "superseded":
                raise SaveError("RULE_SUPERSEDED", "이미 대체된 규칙이에요")
            status = "active" if (apply_existing or apply_future) else stored["status"]
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE classification_rules SET status=?, apply_existing=?,"
                    " apply_future=?, updated_at=? WHERE rule_id=?",
                    (status, int(apply_existing), int(apply_future), created_at, rule_id))
                self._record_rule_version(
                    rule_id, stored["version"], stored["base_rule_version"], status,
                    stored["rule_hash"], stored["rule"], "scope",
                    client_request_id, created_at,
                    previous_version=stored["version"],
                    previous_rule_hash=stored["rule_hash"],
                    confirmation={
                        "apply_existing": bool(apply_existing),
                        "apply_future": bool(apply_future),
                        "rows_changed": 0,
                        "history_kept": True,
                    },
                    actor=actor)
                result = {
                    "outcome": "scope_updated", "rule_id": rule_id, "status": status,
                    "apply_existing": bool(apply_existing),
                    "apply_future": bool(apply_future), "rows_changed": 0,
                    "history_kept": True, "request_id": client_request_id,
                }
                self._store_lifecycle_request(client_request_id, operation, request,
                                              result, created_at)
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    # ---------------------------------------------------------- dialog state
    def _dialog_row(self, case_id: str):
        return self.conn.execute(
            "SELECT case_id, row_id, row_revision, draft_json, apply_existing,"
            " apply_future, dialog_state, created_at, updated_at FROM rule_dialogs"
            " WHERE case_id=?", (case_id,)).fetchone()

    # Question order follows the contract: this-row-only first, then the basis,
    # then the scope. It is not alphabetical.
    QUESTION_ORDER = ("rule_kind", "evidence_basis", "trip_scope", "event_year", "period")

    def _question_rows(self, case_id: str):
        rows = self.conn.execute(
            "SELECT question_id, question_key, prompt, options_json, answer"
            " FROM rule_questions WHERE case_id=? ORDER BY created_at, question_id",
            (case_id,)).fetchall()
        order = {key: index for index, key in enumerate(self.QUESTION_ORDER)}

        def sort_key(row):
            return (order.get(row[1], len(order)), row[0])

        return sorted(rows, key=sort_key)

    def conversation_qa(self, case_id: str) -> list:
        """Structured question rows for provider context and inspection."""
        return [{"question_key": q[1], "options": json.loads(q[3]), "answer": q[4]}
                for q in self._question_rows(case_id)]

    def register_review_rule_case(self, *, case_id: str, binding: str,
                                  source_ref: str, candidate_key: str,
                                  context: dict) -> dict:
        """원천 검토에서 배운 규칙의 근거를 등록합니다.

        같은 근거로 다시 등록하면 이미 있는 것을 그대로 돌려줍니다. 반면 같은
        사례 ID에 다른 근거를 붙이지는 못하게 했습니다. 근거 두 개를 가리킬 수
        있는 사례 ID는 검증할 수 없는 ID이기 때문입니다.

        `context`에는 파생된 사실만 둡니다. 이름, 예약번호, 메모는 넣지 않고
        원천 참조와 그 해시를 함께 남깁니다.
        """
        from .contracts import sha256_text

        for label, value in (("사례 ID", case_id), ("바인딩", binding),
                             ("원천 참조", source_ref), ("후보 키", candidate_key)):
            if not value or not isinstance(value, str):
                raise SaveError("INVALID_VALUE", f"{label}가 필요해요")
        payload = _canonical(dict(context or {}))
        with self._lock:
            self._replay_pending()
            found = self.conn.execute(
                "SELECT binding, source_ref, candidate_key, context_json"
                " FROM classification_source_cases WHERE case_id=?",
                (case_id,)).fetchone()
            if found is not None:
                if (found[0] != binding or found[1] != source_ref
                        or found[2] != candidate_key or found[3] != payload):
                    raise SaveError("REQUEST_ID_REUSED",
                                    "같은 사례 번호에 다른 근거가 있어요")
                return {"case_id": case_id, "binding": binding,
                        "source_ref": source_ref, "candidate_key": candidate_key,
                        "source_ref_sha256": sha256_text(source_ref),
                        "created": False}
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT INTO classification_source_cases(case_id, binding,"
                    " source_ref, candidate_key, context_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (case_id, binding, source_ref, candidate_key, payload, created_at))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return {"case_id": case_id, "binding": binding,
                    "source_ref": source_ref, "candidate_key": candidate_key,
                    "source_ref_sha256": sha256_text(source_ref), "created": True}

    def review_rule_case(self, case_id: str):
        """등록된 원천 사례 근거를 읽습니다. 없으면 None. 읽기 전용."""
        import json as _json

        try:
            found = self.conn.execute(
                "SELECT case_id, binding, source_ref, candidate_key, context_json"
                " FROM classification_source_cases WHERE case_id=?",
                (case_id,)).fetchone()
        except Exception:
            return None
        if found is None:
            return None
        try:
            context = _json.loads(found[4])
        except Exception:
            context = {}
        return {"case_id": found[0], "binding": found[1], "source_ref": found[2],
                "candidate_key": found[3], "context": context}

    def case_is_one_off(self, case_id: str) -> bool:
        """True when a stored answer means "this transaction only".

        The flag is read back from the saved answers, so it survives a restart
        and a close/resume cycle without any extra state.
        """
        from .classification_rules import dialog_blocks_rule

        if not case_id:
            return False
        return dialog_blocks_rule(self._dialog_answers(case_id))

    def _dialog_answers(self, case_id: str) -> dict:
        return {row[1]: row[4] for row in self._question_rows(case_id)
                if row[4] is not None}

    def rule_dialog_state(self, case_id: str) -> dict:
        from .classification_rules import PROVIDER_INFO, dialog_blocks_rule

        row = self._dialog_row(case_id)
        questions = [
            {"question_id": q[0], "question_key": q[1], "prompt": q[2],
             "options": json.loads(q[3]), "answer": q[4], "answered": q[4] is not None}
            for q in self._question_rows(case_id)
        ]
        if row is None:
            return {"case_id": case_id, "dialog_state": "not_started",
                    "questions": [], "answers": {}, "provider": PROVIDER_INFO}
        answers = self._dialog_answers(case_id)
        one_off = dialog_blocks_rule(answers)
        # A one-off answer is terminal, so the reported state says so instead of
        # leaving the screen to infer it from the answers.
        dialog_state = "one_off" if one_off and row[6] != "closed" else row[6]
        return {
            "case_id": case_id, "row_id": row[1], "row_revision": row[2],
            "draft": json.loads(row[3]),
            "apply_existing": bool(row[4]), "apply_future": bool(row[5]),
            "dialog_state": dialog_state, "created_at": row[7], "updated_at": row[8],
            "questions": questions, "answers": answers,
            "open_questions": [] if one_off else [q for q in questions if not q["answered"]],
            "rule_should_not_be_created": one_off,
            "provider": PROVIDER_INFO,
        }

    def open_rule_dialog(self, *, learning_case_id: str, draft: dict,
                         client_request_id: str, apply_existing: bool = False,
                         apply_future: bool = False, actor: str = "owner") -> dict:
        """Persist the dialog and ask only the questions that are still needed."""
        from .classification_rules import (PROVIDER_INFO, MAX_QUESTIONS,
                                           dialog_blocks_rule, needed_questions)

        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            case = self.conn.execute(
                "SELECT case_id, row_id FROM board_learning_cases WHERE case_id=?",
                (learning_case_id,)).fetchone()
            if case is None:
                raise SaveError("INVALID_VALUE", "없는 규칙 대화 사례예요")
            row = self.get_row(case[1])
            if row is None:
                raise SaveError("INVALID_VALUE", "사례에 연결된 행이 없어요")
            existing = self._dialog_row(learning_case_id)
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO rule_dialogs(case_id, row_id, row_revision,"
                    " draft_json, apply_existing, apply_future, dialog_state,"
                    " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (learning_case_id, case[1], row["revision"], _canonical(draft or {}),
                     int(apply_existing), int(apply_future), "open",
                     created_at, created_at))
                answers = self._dialog_answers(learning_case_id)
                for spec in needed_questions(draft or {}, answers)[:MAX_QUESTIONS]:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO rule_questions(question_id, case_id,"
                        " question_key, prompt, options_json, answer, answered_at,"
                        " created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (f"q-{learning_case_id}-{spec['question_key']}", learning_case_id,
                         spec["question_key"], spec["prompt"],
                         _canonical(spec["options"]), None, "", created_at))
                self.conn.execute(
                    "UPDATE board_learning_cases SET dialog_state='open' WHERE case_id=?",
                    (learning_case_id,))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            state = self.rule_dialog_state(learning_case_id)
            state["requested_scope"] = {"apply_existing": bool(apply_existing),
                                        "apply_future": bool(apply_future)}
            state["provider"] = PROVIDER_INFO
            return state

    def answer_rule_question(self, *, question_id: str, answer: str,
                             expected_row_revision: int, client_request_id: str,
                             actor: str = "owner") -> dict:
        """Store one answer. Duplicate request returns the stored result."""
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {"question_id": question_id, "answer": answer,
                   "expected_row_revision": int(expected_row_revision)}
        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT request_json, result_json FROM rule_answer_requests"
                " WHERE client_request_id=?", (client_request_id,)).fetchone()
            if existing:
                if json.loads(existing[0]) != request:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                return json.loads(existing[1])
            found = self.conn.execute(
                "SELECT case_id, question_key, answer FROM rule_questions WHERE question_id=?",
                (question_id,)).fetchone()
            if found is None:
                raise SaveError("INVALID_VALUE", "없는 질문이에요")
            dialog = self._dialog_row(found[0])
            if dialog is None:
                raise SaveError("INVALID_VALUE", "아직 시작하지 않은 대화예요")
            if dialog[6] == "closed":
                raise SaveError("DIALOG_CLOSED", "닫은 대화는 다시 연 뒤 답해 주세요")
            current = self.get_row(dialog[1])
            if (dialog[2] != int(expected_row_revision)
                    or current is None or current["revision"] != dialog[2]):
                raise SaveError(
                    "DIALOG_STALE",
                    "대화 중이던 행이 바뀌었어요. 최신 행을 보고 다시 여세요")
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_questions SET answer=?, answered_at=? WHERE question_id=?",
                    (str(answer), created_at, question_id))
                self.conn.execute(
                    "UPDATE rule_dialogs SET updated_at=? WHERE case_id=?",
                    (created_at, found[0]))
                result = self.rule_dialog_state(found[0])
                result["answered_question"] = found[1]
                self.conn.execute(
                    "INSERT INTO rule_answer_requests(client_request_id, question_id,"
                    " request_json, result_json, created_at) VALUES (?,?,?,?,?)",
                    (client_request_id, question_id, _canonical(request),
                     _canonical(result), created_at))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def close_rule_dialog(self, *, learning_case_id: str, client_request_id: str,
                          actor: str = "owner") -> dict:
        """Close the dialog and keep every stored answer and the draft."""
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            dialog = self._dialog_row(learning_case_id)
            if dialog is None:
                raise SaveError("INVALID_VALUE", "아직 시작하지 않은 대화예요")
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_dialogs SET dialog_state='closed', updated_at=?"
                    " WHERE case_id=?", (created_at, learning_case_id))
                self.conn.execute(
                    "UPDATE board_learning_cases SET dialog_state='closed' WHERE case_id=?",
                    (learning_case_id,))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            state = self.rule_dialog_state(learning_case_id)
            state["closed"] = True
            state["request_id"] = client_request_id
            return state

    def resume_rule_dialog(self, *, learning_case_id: str, client_request_id: str,
                           actor: str = "owner") -> dict:
        """Reopen a closed dialog without asking answered questions again."""
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            dialog = self._dialog_row(learning_case_id)
            if dialog is None:
                raise SaveError("INVALID_VALUE", "아직 시작하지 않은 대화예요")
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_dialogs SET dialog_state='open', row_revision=?,"
                    " updated_at=? WHERE case_id=?",
                    (self.get_row(dialog[1])["revision"], created_at, learning_case_id))
                self.conn.execute(
                    "UPDATE board_learning_cases SET dialog_state='open' WHERE case_id=?",
                    (learning_case_id,))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            state = self.rule_dialog_state(learning_case_id)
            state["resumed"] = True
            state["request_id"] = client_request_id
            return state

    # --- Phase 6B provider-neutral dialog turns ------------------------
    # The conversation belongs to the app. Providers are injected by the
    # server, are never named by a request, and never receive a key.

    def _conversation_row(self, conversation_id: str):
        return self.conn.execute(
            "SELECT conversation_id, case_id, rule_id, rule_version, handoff_summary,"
            " active_provider, active_model_id, state, turn_count, created_at,"
            " updated_at FROM rule_conversations WHERE conversation_id=?",
            (conversation_id,)).fetchone()

    def open_conversation(self, *, learning_case_id: str, client_request_id: str,
                          actor: str = "owner") -> dict:
        """Create the app-owned conversation for a learning case.

        The conversation keeps the case link, the current rule version, the
        stored answers, and the handoff summary, so a provider can be replaced
        without losing the thread.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {"learning_case_id": learning_case_id}
        with self._lock:
            self._replay_pending()
            replayed = self._lifecycle_replay(client_request_id, "conversation_open", request)
            if replayed is not None:
                return replayed
            case = self.conn.execute(
                "SELECT case_id, row_id FROM board_learning_cases WHERE case_id=?",
                (learning_case_id,)).fetchone()
            if case is None:
                raise SaveError("INVALID_VALUE", "없는 규칙 대화 사례예요")
            existing = self.conn.execute(
                "SELECT conversation_id FROM rule_conversations WHERE case_id=?",
                (learning_case_id,)).fetchone()
            if existing is not None:
                result = self.conversation_state(existing[0])
                return result
            created_at = _utc_now()
            conversation_id = f"conv-{learning_case_id}"
            dialog = self._dialog_row(learning_case_id)
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT INTO rule_conversations(conversation_id, case_id, rule_id,"
                    " rule_version, handoff_summary, active_provider, active_model_id,"
                    " state, turn_count, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (conversation_id, learning_case_id, None, None, "",
                     None, None, "open", 0, created_at, created_at))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            result = self.conversation_state(conversation_id)
            self._store_lifecycle_request(client_request_id, "conversation_open",
                                          request, result, created_at)
            return result

    def conversation_state(self, conversation_id: str) -> dict:
        """Rebuild the whole context from storage. Used after a restart too."""
        from .dialog_turn import (ALLOWED_CONTEXT_FIELDS, EXCLUDED_CONTEXT_FIELDS,
                                   STATE_LABELS)

        row = self._conversation_row(conversation_id)
        if row is None:
            return {"conversation_id": conversation_id, "state": "not_found",
                    "turns": [], "answers": {}, "context_fields": list(ALLOWED_CONTEXT_FIELDS),
                    "excluded_context_fields": list(EXCLUDED_CONTEXT_FIELDS)}
        case = self.conn.execute(
            "SELECT row_id FROM board_learning_cases WHERE case_id=?", (row[1],)).fetchone()
        board_row = self.get_row(case[0]) if case else None
        if board_row is not None:
            board_row = dict(board_row)
            board_row.update(self.card_source_keys(board_row))
        rule = self.get_rule(row[2]) if row[2] else None
        dialog = self._dialog_row(row[1])
        # A turn whose owner could not be confirmed stays pending, and the
        # reason travels with it so nothing silently disappears.
        reviews = {
            r[0]: {"reason": r[1], "process_run_id": r[2]}
            for r in self.conn.execute(
                "SELECT turn_id, reason, process_run_id FROM rule_orphan_reviews"
            ).fetchall()}
        turns = [
            {
                "turn_id": t[0], "state": t[1],
                "state_label": STATE_LABELS.get(t[1], t[1]),
                "abandoned_reason": t[10],
                "owner_review": reviews.get(t[0]),
                "adopted_attempt_id": t[2],
                "adopted_provider": t[3], "reason_code": t[4],
                "is_real_call": bool(t[5]), "switch_count": t[6],
                "draft": json.loads(t[7]), "summary": json.loads(t[8]),
                "created_at": t[9],
                "attempts": [
                    {"attempt_id": a[0], "seq": a[1], "slot": a[2], "status": a[3],
                     "provider": a[4], "model_id": a[5], "reason_code": a[6],
                     "send_error": a[7] or None, "adopted": bool(a[8]),
                     "is_real_call": bool(a[9])}
                    for a in self.conn.execute(
                        "SELECT attempt_id, seq, slot, status, provider, model_id,"
                        " reason_code, send_error, adopted, is_real_call"
                        " FROM rule_turn_attempts WHERE turn_id=? ORDER BY seq",
                        (t[0],)).fetchall()
                ],
            }
            for t in self.conn.execute(
                "SELECT turn_id, state, adopted_attempt_id, adopted_provider,"
                " reason_code, is_real_call, switch_count, draft_json, summary_json,"
                " created_at, abandoned_reason FROM rule_turns"
                " WHERE conversation_id=?"
                " ORDER BY created_at, turn_id", (conversation_id,)).fetchall()
        ]
        late = [
            {"attempt_id": l[0], "turn_id": l[1], "status": l[2], "reason": l[3]}
            for l in self.conn.execute(
                "SELECT attempt_id, turn_id, status, reason FROM rule_late_responses"
                " WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,)).fetchall()
        ]
        return {
            "conversation_id": row[0],
            "case_id": row[1],
            "rule_id": row[2],
            "rule_version": row[3],
            "handoff_summary": row[4],
            "active_provider": row[5],
            "active_model_id": row[6],
            "state": row[7],
            "turn_count": row[8],
            "created_at": row[9],
            "updated_at": row[10],
            "row_id": board_row.get("row_id") if board_row else None,
            "row_revision": board_row.get("revision") if board_row else None,
            "answers": self._dialog_answers(row[1]) if dialog else {},
            "qa": self.conversation_qa(row[1]),
            "open_questions": [
                q["question_key"] for q in (self.rule_dialog_state(row[1])["questions"]
                                            if dialog else [])
                if not q["answered"]
            ],
            "turns": turns,
            "late_responses": late,
            "context_fields": list(ALLOWED_CONTEXT_FIELDS),
            "excluded_context_fields": list(EXCLUDED_CONTEXT_FIELDS),
        }

    def run_dialog_turn(self, *, conversation_id: str, client_request_id: str,
                        muse=None, gemini=None, actor: str = "owner",
                        operator: dict = None) -> dict:
        """Run one provider-neutral turn and persist every attempt.

        The draft a provider returns is only stored after the existing draft
        validator accepts it. Nothing here writes to the ledger: a model answer
        never changes a row, a trip, or an amount.

        `operator` carries the values the owner has already chosen, so a
        provider's prose can become a *candidate* rule without the model
        inventing a trip or a year. It is supplied by the server, never taken
        from provider text, and its absence simply means no candidate is built.
        """
        from .classification_rules import RuleError, normalize_draft, rule_hash
        from .dialog_turn import build_context, run_turn

        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {"conversation_id": conversation_id}
        with self._lock:
            self._replay_pending()
            replayed = self._turn_replay(client_request_id, request)
            if replayed is not None:
                return replayed
            conv = self._conversation_row(conversation_id)
            if conv is None:
                raise SaveError("INVALID_VALUE", "없는 대화예요")
            if self.case_is_one_off(conv[1]):
                raise SaveError(
                    "RULE_ONE_OFF",
                    "이번 거래만 적용하기로 한 답변이 있어 대화를 더 진행하지 않아요")
            case = self.conn.execute(
                "SELECT row_id FROM board_learning_cases WHERE case_id=?", (conv[1],)).fetchone()
            if case is None:
                raise SaveError("INVALID_VALUE", "대화에 연결된 사례가 없어요")
            board_row = self.get_row(case[0])
            if board_row is None:
                raise SaveError("INVALID_VALUE", "대화에 연결된 행이 없어요")
            board_row = dict(board_row)
            board_row.update(self.card_source_keys(board_row))
            rule = self.get_rule(conv[2]) if conv[2] else None
            turn_id = f"turn-{conversation_id}-{conv[8] + 1:03d}"
            context = build_context(
                conversation_id=conversation_id, turn_id=turn_id, row=board_row,
                rule=rule, answers=self._dialog_answers(conv[1]),
                handoff_summary=conv[4],
                qa=[{"question_key": q[1], "options": json.loads(q[3]), "answer": q[4]}
                    for q in self._question_rows(conv[1])])
            # The turn is stored as pending, with its owner, before any provider
            # is called. If this process stops while the request is in flight,
            # the turn is already on record and can be recovered. No attempt row
            # is written yet, so an answer to a send that never finished cannot
            # be adopted without a validation pass.
            sending_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO rule_turns(turn_id, conversation_id, state,"
                    " process_run_id, abandoned_reason, adopted_attempt_id,"
                    " adopted_provider, reason_code, is_real_call, switch_count,"
                    " draft_json, summary_json, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (turn_id, conversation_id, "pending", self._process_run_id, "",
                     None, None, None, 0, 0, "{}", _canonical({"phase": "sending"}),
                     sending_at))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise

            outcome = run_turn(turn_id=turn_id, context=context, muse=muse, gemini=gemini)

            draft = outcome.draft
            draft_error = None
            candidate_report = None
            stored_draft = {}
            if outcome.adopted and isinstance(draft, dict):
                payload = dict(draft)
                payload["rule_id"] = conv[2] or f"{conversation_id}-draft"
                try:
                    stored_draft = normalize_draft(
                        payload, learning_case_id=conv[1], rule_id=payload["rule_id"],
                        version=(rule["version"] + 1) if rule else 1,
                        base_rule_version=rule["version"] if rule else 0)
                except RuleError as exc:
                    draft_error = {"code": exc.code, "message": str(exc)}
                    stored_draft = {}
            elif outcome.adopted and outcome.summary:
                # The provider answered in prose. That is turned into a
                # candidate here, and only into a candidate: it is validated by
                # the same rule validator, it is stored as a draft, and the
                # owner still has to confirm it and preview the impact before
                # anything is applied. A model answer never applies itself.
                from . import rule_text

                try:
                    candidate = rule_text.rule_candidate(
                        text=outcome.summary, row=board_row,
                        learning_case_id=conv[1],
                        rule_id=conv[2] or f"{conversation_id}-draft",
                        version=(rule["version"] + 1) if rule else 1,
                        base_rule_version=rule["version"] if rule else 0,
                        operator=operator)
                    stored_draft = candidate["rule"]
                    candidate_report = rule_text.candidate_report(candidate)
                except (rule_text.TextRuleError, RuleError) as exc:
                    draft_error = {"code": getattr(exc, "code", "INVALID_VALUE"),
                                   "message": str(exc)}
                    stored_draft = {}
            created_at = _utc_now()
            self._begin_write()
            try:
                for item in outcome.attempts:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO rule_turn_attempts(attempt_id, turn_id,"
                        " seq, slot, status, provider, model_id, reason_code, send_error,"
                        " adopted, is_real_call, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item["attempt_id"], turn_id, item["seq"], item["slot"],
                         item["status"], item["provider"], item["model_id"],
                         item.get("reason_code"), item.get("send_error") or "",
                         int(bool(item.get("adopted"))),
                         int(bool(item.get("is_real_call"))), created_at))
                self.conn.execute(
                    "UPDATE rule_turns SET state=?, process_run_id=?,"
                    " abandoned_reason='', adopted_attempt_id=?, adopted_provider=?,"
                    " reason_code=?, is_real_call=?, switch_count=?, draft_json=?,"
                    " summary_json=? WHERE turn_id=?",
                    (outcome.state, self._process_run_id,
                     outcome.adopted_attempt_id, outcome.provider, outcome.reason_code,
                     int(bool(outcome.is_real_call)), outcome.switch_count,
                     _canonical({"rule": stored_draft, "draft_error": draft_error,
                                 "rule_hash": rule_hash(stored_draft) if stored_draft else ""}),
                     _canonical({"summary": outcome.summary or "", "conv_state": conv[7]}),
                     turn_id))
                self.conn.execute(
                    "UPDATE rule_conversations SET state=?, turn_count=turn_count+1,"
                    " rule_id=COALESCE(?, rule_id),"
                    " rule_version=COALESCE(?, rule_version),"
                    " handoff_summary=COALESCE(?, handoff_summary),"
                    " active_provider=?, active_model_id=?, updated_at=?"
                    " WHERE conversation_id=?",
                    (outcome.state, conv[2],
                     (rule["version"] + 1) if (rule and stored_draft) else conv[3],
                     (outcome.summary or "") if outcome.summary else None,
                     outcome.provider, outcome.model_id, created_at, conversation_id))
                result = self.conversation_state(conversation_id)
                result["turn"] = next(t for t in result["turns"] if t["turn_id"] == turn_id)
                result["draft"] = stored_draft
                result["draft_error"] = draft_error
                # A candidate is never applied. This flag is the record that the
                # preview and the owner confirm are still outstanding.
                result["candidate"] = candidate_report
                result["requires_owner_confirm"] = bool(candidate_report)
                result["notice"] = (
                    None if not outcome.switch_count
                    else "Muse 연결 실패로 Gemini fallback 사용 중"
                )
                result["is_real_call"] = bool(outcome.is_real_call)
                result["request_id"] = client_request_id
                self._store_turn_request(client_request_id, request, result, created_at)
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def adopt_late_response(self, *, conversation_id: str, turn_id: str,
                            attempt_id: str, client_request_id: str,
                            actor: str = "owner") -> dict:
        """Accept or refuse a late answer for a turn that already ran.

        Only the adopted attempt of that turn may still be adopted. Anything
        else is recorded as refused so it can never overwrite the result.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {"conversation_id": conversation_id, "turn_id": turn_id,
                   "attempt_id": attempt_id}
        with self._lock:
            self._replay_pending()
            replayed = self._turn_replay(client_request_id, request)
            if replayed is not None:
                return replayed
            if self._conversation_row(conversation_id) is None:
                raise SaveError("INVALID_VALUE", "없는 대화예요")
            turn = self.conn.execute(
                "SELECT turn_id, adopted_attempt_id, state, abandoned_reason"
                " FROM rule_turns WHERE turn_id=? AND conversation_id=?",
                (turn_id, conversation_id)).fetchone()
            known = self.conn.execute(
                "SELECT turn_id, adopted FROM rule_turn_attempts WHERE attempt_id=?",
                (attempt_id,)).fetchone()
            created_at = _utc_now()
            if turn is None:
                # The process stopped before the turn was stored. The answer can
                # never become the result, and the refusal is recorded so it
                # stays auditable instead of looking like a missing row.
                status, reason = "refused", "unknown_turn"
            elif known is None or known[0] != turn_id:
                status, reason = "refused", "unknown_attempt"
            elif turn[1] == attempt_id:
                status, reason = "refused", "already_adopted"
            elif turn[1] is not None:
                status, reason = "refused", "stale_attempt"
            elif turn[2] == "pending" and known is None:
                # The owner stopped before its send finished. The answer was never
                # validated here, so it is recorded and refused.
                status, reason = "refused", "send_never_finished"
            elif turn[2] == "pending" and not known[1]:
                # The request is still outstanding, so this answer is the one the
                # turn has been waiting for.
                self.conn.execute(
                    "UPDATE rule_turn_attempts SET adopted=1 WHERE attempt_id=?",
                    (attempt_id,))
                self.conn.execute(
                    "UPDATE rule_turns SET adopted_attempt_id=?, state='answered'"
                    " WHERE turn_id=?", (attempt_id, turn_id))
                status, reason = "adopted", "accepted"
            elif turn[2] == "abandoned":
                status, reason = "refused", turn[3] or "abandoned_turn"
            else:
                # A waiting turn already concluded: every provider answered.
                status, reason = "refused", "turn_already_concluded"
            self._begin_write()
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO rule_late_responses(late_id, conversation_id,"
                    " turn_id, attempt_id, status, reason, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (f"late-{client_request_id}", conversation_id, turn_id, attempt_id,
                     status, reason, created_at))
                result = self.conversation_state(conversation_id)
                result["late"] = {"attempt_id": attempt_id, "status": status,
                                  "reason": reason, "request_id": client_request_id}
                self._store_turn_request(client_request_id, request, result, created_at)
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def _turn_replay(self, client_request_id: str, request: dict):
        row = self.conn.execute(
            "SELECT request_json, result_json FROM rule_turn_requests"
            " WHERE client_request_id=?", (client_request_id,)).fetchone()
        if row is None:
            return None
        if json.loads(row[0]) != request:
            raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
        return json.loads(row[1])

    def _store_turn_request(self, client_request_id: str, request: dict,
                            result: dict, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO rule_turn_requests(client_request_id, conversation_id,"
            " request_json, result_json, created_at) VALUES (?,?,?,?,?)",
            (client_request_id, request["conversation_id"], _canonical(request),
             _canonical(result), created_at))

    # --- Phase 6C minimal dialog service for the functional UI ---------
    # The UI only orchestrates these calls. A provider never writes a row, and
    # the free text the user types stays in the app.

    def update_rule_dialog_note(self, *, learning_case_id: str, note: str,
                                client_request_id: str, actor: str = "owner") -> dict:
        """Store the user's own explanation. Free text is kept as written."""
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        request = {"learning_case_id": learning_case_id, "note": note}
        with self._lock:
            self._replay_pending()
            replayed = self._lifecycle_replay(client_request_id, "dialog_note", request)
            if replayed is not None:
                return replayed
            dialog = self._dialog_row(learning_case_id)
            if dialog is None:
                # The note is the first thing an owner can type, so it opens the
                # dialog row instead of refusing the input.
                case = self.conn.execute(
                    "SELECT row_id FROM board_learning_cases WHERE case_id=?",
                    (learning_case_id,)).fetchone()
                if case is None:
                    raise SaveError("INVALID_VALUE", "없는 규칙 대화 사례예요")
                row = self.get_row(case[0])
                if row is None:
                    raise SaveError("INVALID_VALUE", "사례에 연결된 행이 없어요")
                created_at = _utc_now()
                self._begin_write()
                try:
                    self.conn.execute(
                        "INSERT INTO rule_dialogs(case_id, row_id, row_revision,"
                        " draft_json, apply_existing, apply_future, dialog_state,"
                        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (learning_case_id, case[0], row["revision"], _canonical({}),
                         0, 0, "open", created_at, created_at))
                    self.conn.execute(
                        "UPDATE board_learning_cases SET dialog_state='open'"
                        " WHERE case_id=?", (learning_case_id,))
                    self._commit_write()
                except Exception:
                    self._rollback_write()
                    raise
                dialog = self._dialog_row(learning_case_id)
            draft = json.loads(dialog[3])
            draft["note"] = str(note or "")
            created_at = _utc_now()
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_dialogs SET draft_json=?, updated_at=? WHERE case_id=?",
                    (_canonical(draft), created_at, learning_case_id))
                result = self.rule_dialog_state(learning_case_id)
                result["note_saved"] = True
                result["request_id"] = client_request_id
                self._store_lifecycle_request(client_request_id, "dialog_note", request,
                                              result, created_at)
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
            return result

    def advance_dialog_conversation(self, *, learning_case_id: str,
                                    client_request_id: str, muse=None, gemini=None,
                                    actor: str = "owner",
                                    operator: dict = None) -> dict:
        """Open the conversation if needed, then run one provider turn.

        `operator` is the owner's already-chosen target trip, passed through to
        the turn so a prose answer can become a candidate without the model
        choosing a trip or a year. It is optional; without it the turn still
        runs and simply produces no candidate from prose.
        """
        if self.case_is_one_off(learning_case_id):
            raise SaveError(
                "RULE_ONE_OFF",
                "이번 거래만 적용하기로 한 답변이 있어 초안을 만들지 않아요")
        state = self.conversation_for_case(learning_case_id)
        if state is None:
            self.open_conversation(learning_case_id=learning_case_id,
                                   client_request_id=f"{client_request_id}-open")
        result = self.run_dialog_turn(
            conversation_id=f"conv-{learning_case_id}",
            client_request_id=client_request_id, muse=muse, gemini=gemini,
            actor=actor, operator=operator)
        result["dialog"] = self.rule_dialog_state(learning_case_id)
        return result

    def conversation_for_case(self, case_id: str):
        row = self.conn.execute(
            "SELECT conversation_id FROM rule_conversations WHERE case_id=?",
            (case_id,)).fetchone()
        return None if row is None else self.conversation_state(row[0])

    def pending_draft_for_case(self, case_id: str) -> dict:
        """The validated draft a turn produced and the UI may still confirm."""
        conv = self.conversation_for_case(case_id)
        if conv is None:
            return {"rule_id": None, "rule": None, "turn_id": None, "confirmed": False}
        answered = [t for t in conv["turns"] if t["state"] == "answered"]
        if not answered:
            return {"rule_id": None, "rule": None, "turn_id": None, "confirmed": False}
        last = answered[-1]
        rule = last["draft"].get("rule") or {}
        return {
            "rule_id": last["draft"].get("rule_hash") and rule.get("rule_id"),
            "rule": rule,
            "rule_hash": last["draft"].get("rule_hash"),
            "turn_id": last["turn_id"],
            "provider": last["adopted_provider"],
            "draft_error": last["draft"].get("draft_error"),
            "confirmed": conv["rule_id"] == rule.get("rule_id") and conv["rule_id"] is not None,
        }

    def owner_correction_draft(self, *, learning_case_id: str, client_request_id: str,
                               actor: str = "owner") -> dict:
        """Build a rule draft from the owner's own saved correction. No model call.

        Conditions come from the card source merchant only: the card ledger rows
        carry no direction or card kind that a rule could match, and an unmatched
        condition would make the rule silently do nothing. Effects are exactly the
        fields the owner changed from the row's first revision.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        case = self.conn.execute(
            "SELECT row_id FROM board_learning_cases WHERE case_id=?",
            (learning_case_id,)).fetchone()
        if case is None:
            raise SaveError("INVALID_VALUE", "없는 규칙 대화 사례예요")
        row = self.get_row(case[0])
        if row is None:
            raise SaveError("INVALID_VALUE", "대화에 연결된 행이 없어요")
        keys = self.card_source_keys(dict(row, row_id=case[0]))
        merchant = str(keys.get("source_merchant") or "").strip()
        if not merchant:
            raise SaveError("RULE_SOURCE_MISSING",
                            "카드 원천 가맹점을 읽을 수 없어 규칙 초안을 만들 수 없어요")
        first = self.conn.execute(
            "SELECT revision, prev_json, new_json FROM board_revisions WHERE row_id=?"
            " ORDER BY revision ASC LIMIT 1", (case[0],)).fetchone()
        # Revision 1 is the creation record (its new_json is the original). A row created without one
        # starts at its first saved edit, whose prev_json is the original.
        source = None
        if first:
            source = first[2] if first[0] == 1 else first[1]
        original = json.loads(source) if source else {}
        effects = {}
        item = str(row.get("item") or "").strip()
        if item and item != str(original.get("item") or "").strip():
            effects["item"] = item
        tab = str(row.get("display_tab_id") or "").strip()
        if tab and tab != str(original.get("display_tab_id") or "").strip():
            effects["display_tab_id"] = tab
        if not effects:
            raise SaveError("RULE_NO_CORRECTION",
                            "저장된 수정 내용이 없어 규칙 초안을 만들 수 없어요. 먼저 항목이나 여행을 수정해 저장해 주세요")
        draft = {"learning_case_id": learning_case_id,
                 "conditions": {"merchant_normalized": merchant},
                 "effects": effects, "note": "소유자 수정 내용에서 만든 초안"}
        if "display_tab_id" in effects:
            year = str(row.get("occurred_on") or "")[:4]
            draft["scope"] = {"trip_id": tab, "event_year": int(year) if year.isdigit() else None,
                              "applicability": "existing_and_future"}
        self.open_conversation(learning_case_id=learning_case_id,
                               client_request_id=client_request_id + "-open", actor=actor)
        result = self.create_rule_draft(draft=draft, client_request_id=client_request_id, actor=actor)
        with self._lock:
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_conversations SET rule_id=?, rule_version=?, updated_at=?"
                    " WHERE case_id=?", (result["rule_id"], result["version"], _utc_now(),
                                         learning_case_id))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
        return result

    def confirm_dialog_draft(self, *, learning_case_id: str, client_request_id: str,
                              actor: str = "owner") -> dict:
        """Store the turn's validated draft as a rule. Nothing is applied here."""
        pending = self.pending_draft_for_case(learning_case_id)
        if not pending["rule"]:
            raise SaveError("INVALID_VALUE", "아직 저장할 초안이 없어요")
        # The turn stored a normalized rule, so only the documented input keys
        # go back into the validator. Output-only keys are dropped here instead
        # of widening what the validator accepts.
        allowed = ("conditions", "optional_conditions", "effects", "scope",
                   "exceptions", "note", "learning_case_id")
        draft = {key: value for key, value in pending["rule"].items()
                 if key in allowed}
        draft["learning_case_id"] = learning_case_id
        result = self.create_rule_draft(
            draft=draft,
            client_request_id=client_request_id, actor=actor)
        with self._lock:
            self._begin_write()
            try:
                self.conn.execute(
                    "UPDATE rule_conversations SET rule_id=?, rule_version=?, updated_at=?"
                    " WHERE case_id=?", (result["rule_id"], result["version"],
                                         _utc_now(), learning_case_id))
                self._commit_write()
            except Exception:
                self._rollback_write()
                raise
        payload = self.rule_dialog_state(learning_case_id)
        payload["rule"] = result
        payload["confirmed"] = True
        payload["request_id"] = client_request_id
        return payload

    def dialog_page_state(self, case_id: str) -> dict:
        """Everything the minimal rule dialog screen needs, in one read."""
        dialog = self.rule_dialog_state(case_id)
        conv = self.conversation_for_case(case_id)
        dialog_row = self._dialog_row(case_id)
        case_row = self.conn.execute(
            "SELECT row_id FROM board_learning_cases WHERE case_id=?",
            (case_id,)).fetchone()
        last_preview = None
        if conv and conv.get("rule_id"):
            found = self.conn.execute(
                "SELECT preview_id, rule_id, apply_existing, apply_future, plan_json"
                " FROM rule_previews WHERE rule_id=? ORDER BY created_at DESC LIMIT 1",
                (conv["rule_id"],)).fetchone()
            if found is not None:
                last_preview = {
                    "preview_id": found[0], "rule_id": found[1],
                    "apply_existing": bool(found[2]), "apply_future": bool(found[3]),
                    "plan": json.loads(found[4]),
                }
        return {
            "case_id": case_id,
            "row_id": (dialog_row[1] if dialog_row
                       else (case_row[0] if case_row else None)),
            "row_revision": dialog_row[2] if dialog_row else None,
            "last_preview": last_preview,
            "dialog_state": dialog.get("dialog_state", "not_started"),
            "questions": dialog.get("questions", []),
            "answers": dialog.get("answers", {}),
            "open_questions": dialog.get("open_questions", []),
            "note": (dialog.get("draft") or {}).get("note", ""),
            "should_not_create_rule": dialog.get("rule_should_not_be_created", False),
            "one_off": self.case_is_one_off(case_id),
            "provider": (dialog.get("provider") or {}),
            "conversation": conv,
            "pending_draft": self.pending_draft_for_case(case_id),
            "rule": (conv or {}).get("rule_id") and self.get_rule(conv["rule_id"]),
        }

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
            # SPEC_REFINEMENT 19.3 puts row saving last, and only when even the
            # minimum headroom is gone: a save is never reported as a success it
            # did not achieve. The reservation happens inside `_begin_write`
            # below, which every write in this store now goes through. It is
            # reached *after* the stored-result replay on purpose: a request
            # that already completed performs no write, so refusing it for
            # space it does not need would report a finished request as a new
            # failure.
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
                self._begin_write(code="SAVE_NO_SPACE",
                                  what="행을 저장하는 데")
                try:
                    self.conn.execute(
                        "INSERT INTO board_requests(client_request_id, row_id, expected_revision,"
                        " result_json, ledger_pending, created_at) VALUES (?,?,?,?,?,?)",
                        (client_request_id, row_id, expected_revision,
                         _canonical({"row_id": row_id, "expected_revision": expected_revision,
                                     "changes": changes, "change_mode": change_mode, "result": result}),
                         0, _utc_now()),
                    )
                    self._commit_write()
                except SpaceRefused as refused:
                    self._rollback_write()
                    raise space_refused_as_save_error(refused) from refused
                except Exception:
                    self._rollback_write()
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
                try:
                    self._begin_write(code="SAVE_NO_SPACE",
                                      what="행을 저장하는 데")
                except SpaceRefused as refused:
                    # The reservation is taken before the transaction opens, so
                    # there is nothing to roll back and nothing was written.
                    raise space_refused_as_save_error(refused) from refused
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
                    self._commit_write()
            except SaveError as exc:
                if not outer_txn:
                    try:
                        self._rollback_write()
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
                        self._rollback_write()
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
                    self._rollback_write()
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
            "source_merchant": str(fields.get("merchant", "")),
            "event_kind": str(fields.get("event_kind", "")),
            "card_kind": str(fields.get("card_kind", "")),
            "classification_basis": f"가져오기 {batch_id} {fields.get('event_kind', '')}",
            "operator_note": "",
        }
        # Phase 6A: active future rules are evaluated on the real card
        # upload path only. A rule never writes amount, date, or source
        # fields, and the upload dedupe contract still owns re-upload of an
        # already existing event, so a re-upload cannot apply a rule twice.
        rule_applied = self.apply_active_rules_to_import(record, fields)
        if rule_applied:
            record["classification_basis"] = (
                record["classification_basis"] + " "
                + "영칙적용 "
                + ",".join(item["rule_id"] for item in rule_applied))
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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
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
                self._rollback_write()
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


    # ------------------------------------------- reviewed source facts
    def apply_reviewed_source_facts(self, *, request_id: str, input_digest: str,
                                    expected_binding: str,
                                    expected_choices_revision: int,
                                    items: list, verify=None,
                                    actor: str = "owner") -> dict:
        """Write reviewed card facts into the ledger, once, from the source itself.

        This is not `import_row`, and it must not be replaced by it. `import_row`
        takes an approval number or a generated row number as the event's
        identity, decides the cost item from the merchant's name, applies the
        active classification rules, and drops the memo. Every one of those is
        wrong for a fact a person looked at in the review and approved: the
        identity has to be the transaction's own key so the same transaction
        cannot become two expenses, and nothing may be decided from a merchant's
        name or from a rule that was written before the transaction existed.

        So the write here keeps the seventeen original columns exactly, decides
        nothing, and makes the second write of the same key a no-op rather than a
        second expense.

        `items` is a list of dicts with `source_event_key`, `facts` (the
        seventeen columns as a mapping), `workbook_ref`, `review_ref` and
        `review_snapshot_sha256`.

        Everything below happens in one transaction: the idempotency record, each
        fact, each board row, each revision, the request result and the audit
        event left waiting for its retry path. An exception part-way rolls the
        whole thing back, so a retry of the same request reproduces the same
        result rather than half of it.
        """
        created_at = _utc_now()
        with self._lock:
            # The existing retry path. An audit event left waiting by an earlier
            # write goes out through here rather than through a second queue this
            # method would have to keep in step with.
            self._replay_pending()
            # Answered before any transaction is opened, so a repeat of a
            # completed request is a read rather than a rollback.
            if type(request_id) is not str or request_id == "":
                raise SaveError("APPLY_REQUEST_INVALID", "요청 식별자가 필요해요")
            done = self.conn.execute(
                "SELECT input_digest, result_json FROM source_fact_applies"
                " WHERE request_id=?", (request_id,)).fetchone()
            if done is not None:
                if done[0] != input_digest:
                    raise SaveError(
                        "APPLY_REQUEST_INPUT_CONFLICT",
                        "같은 요청 식별자로 다른 입력이에요")
                self._relay_request_outbox(request_id)
                return json.loads(done[1])

            self._begin_write()
            try:
                # Re-checked inside the transaction. Two applies of the same
                # request that start together are serialised by BEGIN IMMEDIATE,
                # and the loser has to see the winner's record, not start over.
                again = self.conn.execute(
                    "SELECT input_digest, result_json FROM source_fact_applies"
                    " WHERE request_id=?", (request_id,)).fetchone()
                if again is not None:
                    if again[0] != input_digest:
                        raise SaveError(
                            "APPLY_REQUEST_INPUT_CONFLICT",
                            "같은 요청 식별자로 다른 입력이에요")
                    self._rollback_write()
                    self._relay_request_outbox(request_id)
                    return json.loads(again[1])

                # The caller's own check runs *inside* this transaction, with
                # the writes already begun. That is what binds the active bundle
                # and the saved choice version to the write itself: a bundle that
                # moved, or a choice saved by another device, between the plan and
                # this line raises here and everything below — the facts, the
                # rows, the revisions, the request record and the audit events —
                # is rolled back together. Nothing is half applied.
                applied, unchanged, conflicts = [], [], []
                for index, item in enumerate(items):
                    # Checked before *every* write, not once at the start.
                    #
                    # A single check at the top of the transaction leaves the rest
                    # of the loop unguarded: another writer that saves a decision,
                    # or replaces the source, while this loop is running lands
                    # between the check and the commit and its change is committed
                    # against. Re-checking here, and once more after the loop,
                    # means the last thing that happens before the commit is a
                    # check of the inputs the commit is based on.
                    if verify is not None:
                        verify()
                    outcome = self._apply_one_source_fact(
                        item, request_id=request_id, index=index,
                        actor=actor, created_at=created_at,
                        applied=applied, unchanged=unchanged,
                        conflicts=conflicts)
                    assert outcome in ("applied", "unchanged", "conflict")
                if verify is not None:
                    verify()

                result = {
                    "outcome": "applied",
                    "request_id": request_id,
                    "binding": expected_binding,
                    "choices_revision": expected_choices_revision,
                    "input_digest": input_digest,
                    "applied": applied,
                    "unchanged": unchanged,
                    "conflicts": conflicts,
                    "counts": {"applied": len(applied),
                               "unchanged": len(unchanged),
                               "conflicts": len(conflicts)},
                }
                self.conn.execute(
                    "INSERT INTO source_fact_applies(request_id, input_digest,"
                    " binding, choices_revision, result_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (request_id, input_digest, expected_binding,
                     expected_choices_revision,
                     json.dumps(result, ensure_ascii=False, sort_keys=True),
                     created_at))
                self._commit_write()
            except SaveError:
                self._rollback_write()
                raise
            except Exception:
                self._rollback_write()
                raise

            # After the commit, on the existing relay path. A failure here leaves
            # the row waiting with relayed=0 and is retried by the next write. It
            # is never a reason to make another row.
            self._relay_outbox()
            return result

    def resume_audit_relay(self, request_id: str) -> None:
        """Send this request's waiting audit events. See `_relay_request_outbox`."""
        self._relay_request_outbox(request_id)

    @staticmethod
    def _owns_outbox_id(outbox_id, prefix: str) -> bool:
        """Is this outbox row one of the request's own events?

        Two things had to be established before this was right, and both were
        wrong at first.

        A `LIKE` pattern built from the request id is not a literal: `_` matches
        any one character and `%` matches any run of them, so `request_a` claimed
        `requestXa`'s events. Escaping the pattern would have fixed that pair and
        left the next one.

        A prefix match alone is not enough either. `request` and `request-child`
        share a prefix, so `ledger-request-` also matches
        `ledger-request-child-0`, and relaying another request's backlog under
        this one is exactly the mistake the scoping exists to prevent.

        So ownership is proved rather than assumed: the row must begin with this
        request's literal prefix, and the remainder must be the decimal index this
        store appends. `child-0` is not a decimal index, so a longer request id is
        not mistaken for this one, and no character of either id is ever a pattern.
        """
        if type(outbox_id) is not str or not outbox_id.startswith(prefix):
            return False
        tail = outbox_id[len(prefix):]
        # `isdigit` alone would accept other scripts' digits, so `isascii` is
        # checked first: the index this store writes is ASCII.
        return bool(tail) and tail.isascii() and tail.isdigit()

    def _relay_request_outbox(self, request_id: str) -> None:
        """Resume this request's own audit events, through the existing path.

        A request that committed while the audit ledger was refusing still left
        events waiting with `relayed=0`. The retry of that request is when they go
        out — which is what `_replay_pending` does for any other write, so a client
        that retries gets the audit trail completed rather than a cached answer
        whose audit event quietly never arrives.

        Only this request's events, and proved as above: an unrelated request's
        backlog is not this request's to flush, and flushing it would put one
        request's audit events under another's identity.
        """
        prefix = "ledger-" + request_id + "-"
        with self._lock:
            rows = self.conn.execute(
                "SELECT outbox_id FROM ledger_outbox WHERE relayed=0").fetchall()
        pending = [row[0] for row in rows
                   if self._owns_outbox_id(row[0], prefix)]
        if pending:
            self._relay_outbox(pending)

    def source_fact_apply(self, request_id: str):
        """What one request id already did: its input digest and its result.

        Read before any of the checks that would refuse a retry, because a retry
        after a lost response presents the *original* plan, and that plan is no
        longer what a fresh plan says once the transactions are applied.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT input_digest, result_json FROM source_fact_applies"
                " WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return None
        return {"input_digest": row[0], "result": json.loads(row[1])}

    def applied_source_fact(self, source_event_key: str):
        """What this ledger holds for one transaction key, or None.

        Read by the plan so the owner is shown what is already there before being
        asked to write anything.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT row_id, fact_digest FROM source_fact_rows"
                " WHERE source_event_key=?", (source_event_key,)).fetchone()
        if row is None:
            return None
        return {"row_id": row[0], "fact_digest": row[1]}

    def _apply_one_source_fact(self, item, *, request_id, index, actor,
                               created_at, applied, unchanged, conflicts):
        """One transaction key's worth of work. See the caller for the why."""
        key = item["source_event_key"]
        facts = item["facts"]
        digest = _source_fact_digest(facts)
        existing = self.conn.execute(
            "SELECT row_id, fact_digest FROM source_fact_rows"
            " WHERE source_event_key=?", (key,)).fetchone()
        if existing is not None:
            if existing[1] != digest:
                # The key is the same and the source says something different.
                # Overwriting would rewrite an approved fact, and minting a new
                # key would make one transaction into two. It stays a conflict for
                # a person to look at.
                conflicts.append({"source_event_key": key,
                                  "row_id": existing[0],
                                  "code": "APPLY_SOURCE_FACT_CONFLICT"})
                return "conflict"
            # The same key and the same facts. Nothing is written, so nothing the
            # user has since edited on that row is reset, and no second expense or
            # second voucher appears.
            unchanged.append({"source_event_key": key, "row_id": existing[0]})
            return "unchanged"

        row_id = f"src-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"
        approval_date = str(facts.get("승인일", "") or "")
        posting_date = str(facts.get("매입일", "") or "")
        record = {
            "row_id": row_id,
            "row_kind": "expense",
            # Nothing decides the tab for a reviewed card fact. A trip assignment
            # comes from the owner's schedule, not from a merchant's name.
            "display_tab_id": None,
            "revision": 1,
            # Both dates are kept in their own fields below. This one column has
            # to hold one date, so it takes whichever the source stated; a
            # transaction with only one of the two is not inventing the other.
            "occurred_on": approval_date or posting_date,
            "source_approval_date": approval_date,
            "source_posting_date": posting_date,
            # The cost item is left empty. Naming an expense category by matching
            # a merchant's name is a guess, and a guess recorded as a fact is
            # worse than an empty field the owner fills in.
            "item": "",
            "description": str(facts.get("가맹점", "") or ""),
            "service_period": "",
            "reservation_no": "",
            "evidence_type": "카드",
            "amount_krw": _source_amount(facts.get("원화금액")),
            "source_local_amount": str(facts.get("현지금액", "") or ""),
            "source_currency": str(facts.get("통화", "") or ""),
            "source_kind": "카드",
            # The transaction's own key. This is what makes a second write of the
            # same transaction the same event rather than a new one.
            "source_event_id": key,
            "source_issuer": str(facts.get("카드사", "") or ""),
            "source_card_last4": str(facts.get("카드4", "") or ""),
            "source_approval_number": str(facts.get("승인번호", "") or ""),
            "source_cancelled": str(facts.get("취소여부", "") or ""),
            "source_origin": str(facts.get("출처", "") or ""),
            "source_fact_digest": digest,
            "classification_state": "unclassified",
            "source_merchant": str(facts.get("가맹점", "") or ""),
            "event_kind": str(facts.get("구분", "") or ""),
            "card_kind": str(facts.get("카드사", "") or ""),
            "classification_basis": f"검토 반영 {item['review_ref']}",
            # The review note is the person's own words about the transaction, so
            # it is carried. A later edit to it is not reset by a repeated apply,
            # because a repeated apply writes nothing.
            "operator_note": str(item.get("review_note", "") or ""),
        }
        self.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision,"
            " payload_json) VALUES (?,?,?,?,?)",
            (row_id, "expense", None, 1, _canonical(record)))
        self.conn.execute(
            "INSERT INTO board_revisions(row_id, revision, prev_json, new_json,"
            " event_id, change_mode, actor, created_at, client_request_id, kind,"
            " reverts_event_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (row_id, 1, _canonical({}), _canonical(record), "", "exception",
             actor, created_at, f"{request_id}-{index}", "save", ""))
        self.conn.execute(
            "INSERT INTO source_fact_rows(source_event_key, row_id, fact_digest,"
            " facts_json, workbook_ref, review_ref, review_snapshot_sha256,"
            " applied_request_id, applied_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, row_id, digest,
             # Column order as the master stated it, not sorted: the stored fact
             # is read back by a person comparing it with the source file.
             json.dumps(facts, ensure_ascii=False),
             str(item.get("workbook_ref", "") or ""),
             str(item.get("review_ref", "") or ""),
             str(item.get("review_snapshot_sha256", "") or ""),
             request_id, created_at))
        self._enqueue_ledger(
            outbox_id=f"ledger-{request_id}-{index}",
            stream_id=f"row-{row_id}", action="propose",
            target=key,
            rationale=f"검토 반영 {item['review_ref']} {key}", actor=actor)
        applied.append({"source_event_key": key, "row_id": row_id})
        return "applied"


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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    return self._replay_correction_request(
                        client_request_id, corrected_amount_krw, date_value, want_plan)
                raise
            except sqlite3.IntegrityError:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                return self._replay_correction_request(
                    client_request_id, corrected_amount_krw, date_value, want_plan)
            except Exception:
                self._rollback_write()
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
            self._begin_write()
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
                        self._rollback_write()
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
                self._commit_write()
            except SaveError:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self._rollback_write()
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
                self._rollback_write()
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
        archived = bool(row[7])
        deleted = bool(row[8])
        return {
            "tab_id": row[0], "display_key": row[1], "destination": row[2],
            "starts_on": row[3], "ends_on": row[4], "prepared_on": row[5],
            "prepared_by_name": row[6], "archived": archived,
            "deleted": deleted, "revision": row[9],
            # APP_SPEC 3: these five are separate responsibilities and are
            # never folded into the display name or the archive flag.
            "event_year": row[10], "tab_kind": row[11],
            "authority_status": row[12], "source_sha256": row[13],
            "sort_order": row[14],
            # Provenance of `prepared_by_name`. Empty means this row was written
            # before the column existed, so nobody recorded where the name came
            # from — not that the name is wrong.
            "assignee_source": row[15] if len(row) > 15 else "",
            # derived, so it cannot disagree with the two stored flags
            "tab_lifecycle": "deleted" if deleted else (
                "archived" if archived else "active"),
        }

    _TRIP_COLUMNS = ("tab_id, display_key, destination, starts_on, ends_on,"
                     " prepared_on, prepared_by_name, archived, deleted, revision,"
                     " event_year, tab_kind, authority_status, source_sha256,"
                     " sort_order, assignee_source")

    def list_trips(self, include_archived: bool = False) -> list:
        rows = self.conn.execute(
            f"SELECT {self._TRIP_COLUMNS}"
            " FROM trip_tabs WHERE deleted=0 ORDER BY starts_on, tab_id"
        ).fetchall()
        trips = [self._trip_dict(r) for r in rows]
        if not include_archived:
            trips = [t for t in trips if not t["archived"]]
        return trips

    def get_trip(self, tab_id: str):
        row = self.conn.execute(
            f"SELECT {self._TRIP_COLUMNS} FROM trip_tabs WHERE tab_id=?",
            (tab_id,),
        ).fetchone()
        return self._trip_dict(row) if row else None

    def find_trip_by_schedule(self, starts_on: str, destination: str):
        """The live trip already standing for this date and destination.

        APP_SPEC 3: a new tab on a date and destination that already exists must
        not add a second row, and whether the two should be merged is not
        decided here. The caller shows the existing tab instead.
        """
        row = self.conn.execute(
            f"SELECT {self._TRIP_COLUMNS} FROM trip_tabs"
            " WHERE deleted=0 AND starts_on=? AND destination=?"
            " ORDER BY tab_id LIMIT 1",
            (starts_on, destination),
        ).fetchone()
        return self._trip_dict(row) if row else None

    def create_trip(self, *, starts_on: str, destination: str,
                    ends_on: str = "", display_key=None, tab_kind: str = "trip",
                    source_sha256: str = "",
                    client_request_id: str, actor: str = "owner") -> dict:
        """Create one trip tab. APP_SPEC 3, the `새 탭 추가` contract.

        `starts_on` and `destination` are required. The internal `tab_id` is
        made here, and a date and destination that already has a live tab returns
        that tab without adding a row and without deciding a merge.

        `authority_status` starts at `needs_review` and this call never sets it to
        `authoritative`: section 3 says creating a screen tab is not what makes a
        schedule authoritative, and section 4.2 says a tab with no authority
        basis is made `needs_review` rather than confirmed on its own. The
        authoritative value still has to come from its own source with its own
        digest.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        import re as _re

        starts_on = str(starts_on or "").strip()
        destination = str(destination or "").strip()
        ends_on = str(ends_on or "").strip()
        source_sha256 = str(source_sha256 or "").strip()
        if not starts_on:
            raise SaveError("INVALID_VALUE", "여행 시작 날짜를 입력해 주세요")
        if not _valid_date(starts_on):
            raise SaveError("INVALID_VALUE", "여행 시작 날짜 형식이 달라요")
        if not destination:
            raise SaveError("INVALID_VALUE", "행선지를 입력해 주세요")
        if ends_on:
            if not _valid_date(ends_on):
                raise SaveError("INVALID_VALUE", "여행 종료 날짜 형식이 달라요")
            if ends_on < starts_on:
                raise SaveError("INVALID_VALUE",
                                "종료일이 시작일보다 앞이에요")
        if tab_kind not in ("trip", "overhead", "closing", "other"):
            raise SaveError("INVALID_VALUE", "탭 종류가 알아볼 수 없어요")
        if display_key is not None and not str(display_key).strip():
            raise SaveError("INVALID_VALUE", "표시 이름이 비었어요")
        if source_sha256 and not _re.fullmatch(r"[0-9a-f]{64}", source_sha256):
            raise SaveError("INVALID_VALUE", "일정 근거 해시 형식이 달라요")

        # The request identity binds to the payload, so a retry of the same id
        # with different content is refused instead of silently accepted.
        identity = _canonical({
            "op": "create-trip", "starts_on": starts_on,
            "destination": destination, "ends_on": ends_on,
            "display_key": None if display_key is None else str(display_key),
            "tab_kind": tab_kind, "source_sha256": source_sha256,
        })

        with self._lock:
            self._replay_pending()
            existing = self.conn.execute(
                "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if stored.get("identity") != identity:
                    raise SaveError("REQUEST_ID_REUSED",
                                    "같은 요청 ID로 다른 내용을 보냈어요")
                return stored["result"]

            # Section 3: the same date and destination shows the tab that is
            # already there. No second row, and no merge decision either way.
            already = self.find_trip_by_schedule(starts_on, destination)
            if already is not None:
                result = {"outcome": "existing", "created": False,
                          "tab_id": already["tab_id"],
                          "revision": already["revision"],
                          "merge_decided": False, "trip": already,
                          "ledger_pending": False}
                self.conn.execute(
                    "INSERT INTO trip_tab_requests(client_request_id, tab_id,"
                    " expected_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, already["tab_id"], already["revision"],
                     _canonical({"identity": identity, "result": result}),
                     0, _utc_now()),
                )
                self.conn.commit()
                return result

            event_year = int(starts_on[:4])
            name = (str(display_key).strip() if display_key is not None
                    else f"{starts_on[5:7]}{starts_on[8:10]}_{destination}")
            tab_id = f"trip-{uuid.uuid4().hex[:12]}"
            created_at = _utc_now()
            next_order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM trip_tabs"
            ).fetchone()[0]
            record = {"tab_id": tab_id, "display_key": name,
                      "destination": destination, "starts_on": starts_on,
                      "ends_on": ends_on, "event_year": event_year,
                      "tab_kind": tab_kind,
                      # 4.2: a tab with no authority basis is needs_review and is
                      # never confirmed just because the screen made it.
                      "authority_status": "needs_review",
                      "source_sha256": source_sha256, "sort_order": next_order,
                      "archived": False, "deleted": False, "revision": 1,
                      "tab_lifecycle": "active"}
            result = {"outcome": "created", "created": True, "tab_id": tab_id,
                      "revision": 1, "merge_decided": False,
                      "trip": record, "ledger_pending": True}

            self._begin_write()
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM trip_tab_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    raise SaveError("__REPLAY__", "retry")
                new_assignee = owner_assignee_default(self.conn)
                self.conn.execute(
                    "INSERT INTO trip_tabs(tab_id, display_key, destination,"
                    " starts_on, ends_on, event_year, tab_kind, authority_status,"
                    " source_sha256, sort_order, prepared_on, prepared_by_name,"
                    " assignee_source, archived, deleted, revision)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tab_id, name, destination, starts_on, ends_on, event_year,
                     tab_kind, "needs_review", source_sha256, next_order,
                     _seoul_today(),
                     new_assignee, "owner_profile" if new_assignee else "",
                     0, 0, 1),
                )
                self.conn.execute(
                    "INSERT INTO trip_tab_history(tab_id, revision, change_kind,"
                    " prev_json, new_json, event_id, actor, created_at,"
                    " client_request_id) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tab_id, 1, "create", _canonical({}), _canonical(record),
                     "", actor, created_at, client_request_id),
                )
                self.conn.execute(
                    "INSERT INTO trip_tab_requests(client_request_id, tab_id,"
                    " expected_revision, result_json, ledger_pending, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (client_request_id, tab_id, 0,
                     _canonical({"identity": identity, "result": result}),
                     1, created_at),
                )
                self._enqueue_ledger(
                    outbox_id=f"ledger-trip-{client_request_id}",
                    stream_id=f"trip-{tab_id}",
                    action="propose",
                    target=None,
                    rationale=f"여행 탭 생성 {tab_id} {starts_on} {destination}",
                    actor=actor,
                )
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                if exc.code == "__REPLAY__":
                    found = self.conn.execute(
                        "SELECT result_json FROM trip_tab_requests"
                        " WHERE client_request_id=?",
                        (client_request_id,),
                    ).fetchone()
                    if found:
                        return json.loads(found[0])["result"]
                    raise SaveError("REQUEST_ID_REUSED",
                                    "같은 요청 ID로 다른 내용을 보냈어요")
                raise
            except sqlite3.IntegrityError:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                raise SaveError("EDIT_CONFLICT",
                                "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            return result

    def owner_profile(self) -> dict:
        """The owner-entered company name and default assignee.

        Reads as an empty profile rather than None when nothing has been saved,
        so every caller gets the same shape and no caller has to invent a
        fallback name.
        """
        try:
            row = self.conn.execute(
                "SELECT company_name, assignee_name, revision, updated_at"
                " FROM owner_profile WHERE profile_id='owner'").fetchone()
        except Exception:
            return {"company_name": "", "assignee_name": "", "revision": 0,
                    "updated_at": "", "configured": False}
        if not row:
            return {"company_name": "", "assignee_name": "", "revision": 0,
                    "updated_at": "", "configured": False}
        return {"company_name": row[0] or "", "assignee_name": row[1] or "",
                "revision": row[2], "updated_at": row[3] or "",
                "configured": True}

    def save_owner_profile(self, *, expected_revision: int, client_request_id: str,
                           company_name=None, assignee_name=None,
                           actor: str = "owner") -> dict:
        """Save the owner profile under the same CAS, replay and audit rules as a trip.

        Everything that decides the outcome is read *inside* the write
        transaction, after `BEGIN IMMEDIATE`. Reading the current revision before
        opening one leaves a gap: two connections can both read revision 0, both
        decide they are first, and the second write silently overwrites the
        first. Here the second transaction waits, then re-reads and refuses.

        The same applies to the replay check. A retry that arrives while the
        original is still in flight must find the finished request and return its
        result, not miss it and write again.

        The update is conditional on the revision the caller presented, so even a
        path that got here without re-reading cannot write over a newer value.

        A saved, an unchanged and a replayed request all return the same shape,
        so a retry cannot be told apart from its first answer by shape alone.
        An empty name is stored, not refused: "not set yet" is a legitimate state
        for a default, and refusing it would leave a field that can be filled once
        and never cleared.
        """
        if not client_request_id or not isinstance(client_request_id, str):
            raise SaveError("INVALID_VALUE", "요청 ID가 필요해요")
        with self._lock:
            self._replay_pending()
            self._begin_write()
            try:
                existing = self.conn.execute(
                    "SELECT input_digest, result_json FROM owner_profile_requests"
                    " WHERE client_request_id=?", (client_request_id,)).fetchone()
                row = self.conn.execute(
                    "SELECT company_name, assignee_name, revision FROM owner_profile"
                    " WHERE profile_id='owner'").fetchone()
                current = {
                    "company_name": (row[0] or "") if row else "",
                    "assignee_name": (row[1] or "") if row else "",
                    "revision": row[2] if row else 0,
                }
                company = (current["company_name"] if company_name is None
                           else str(company_name).strip())
                assignee = (current["assignee_name"] if assignee_name is None
                            else str(assignee_name).strip())
                # The identity is the *explicit input*, not the values it resolves
                # to. Filling an omitted field from the current profile here would
                # make the same request carry a different meaning after the
                # profile changed: a retry of the original save would be refused as
                # a different request, and the owner would see a conflict for a
                # request they had not changed. An omitted field is recorded as
                # omitted, so "not mentioned" stays distinguishable from
                # "explicitly set to nothing".
                identity_input = {
                    "expected_revision": expected_revision,
                    "actor": actor,
                    "company_name": ({"given": False} if company_name is None
                                     else {"given": True, "value": company}),
                    "assignee_name": ({"given": False} if assignee_name is None
                                      else {"given": True, "value": assignee}),
                }
                digest = hashlib.sha256(
                    _canonical(identity_input).encode("utf-8")).hexdigest()
                if existing is not None:
                    if existing[0] != digest:
                        raise SaveError(
                            "EDIT_CONFLICT",
                            "같은 요청 번호에 다른 내용이 왔어요. 새로 저장해 주세요")
                    # The stored row is the result itself, so the first answer and
                    # this one are the same value and not merely the same fields.
                    self.conn.commit()
                    return json.loads(existing[1])
                if current["revision"] != expected_revision:
                    raise SaveError(
                        "EDIT_CONFLICT",
                        "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                now = _utc_now()
                if company == current["company_name"] and assignee == current["assignee_name"]:
                    result = {"outcome": "unchanged", "revision": current["revision"],
                              "company_name": company, "assignee_name": assignee,
                              "updated_at": now}
                    # The no-op still records its request, so a retry of it replays
                    # rather than re-deciding against a later revision.
                    self._record_owner_profile_request(
                        client_request_id, digest, result, now, actor,
                        current, current, "noop")
                    self.conn.commit()
                    return result
                revision = current["revision"] + 1
                if row is None:
                    self.conn.execute(
                        "INSERT INTO owner_profile(profile_id, company_name,"
                        " assignee_name, revision, updated_at, actor,"
                        " client_request_id) VALUES ('owner',?,?,?,?,?,?)",
                        (company, assignee, revision, now, actor, client_request_id))
                else:
                    updated = self.conn.execute(
                        "UPDATE owner_profile SET company_name=?, assignee_name=?,"
                        " revision=?, updated_at=?, actor=?, client_request_id=?"
                        " WHERE profile_id='owner' AND revision=?",
                        (company, assignee, revision, now, actor,
                         client_request_id, expected_revision))
                    if updated.rowcount != 1:
                        # The conditional write refused. Nothing is recorded, so the
                        # caller can retry with the revision it now sees.
                        raise SaveError(
                            "EDIT_CONFLICT",
                            "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
                result = {"outcome": "saved", "revision": revision,
                          "company_name": company, "assignee_name": assignee,
                          "updated_at": now}
                self._record_owner_profile_request(
                    client_request_id, digest, result, now, actor,
                    current, {"company_name": company, "assignee_name": assignee,
                              "revision": revision}, "save")
                self.conn.commit()
                return result
            except Exception:
                self.conn.rollback()
                raise

    def _record_owner_profile_request(self, client_request_id, digest, result,
                                      created_at, actor, prev, new,
                                      change_kind) -> None:
        """The request row and the audit row, written together.

        Both go in the caller's transaction on purpose. An audit trail that can
        disagree with the change it describes is worse than none, because it is
        read as if it were reliable.
        """
        self.conn.execute(
            "INSERT INTO owner_profile_requests(client_request_id, input_digest,"
            " result_json, created_at) VALUES (?,?,?,?)",
            (client_request_id, digest, _canonical(result), created_at))
        self.conn.execute(
            "INSERT INTO owner_profile_history(revision, change_kind, prev_json,"
            " new_json, actor, created_at, client_request_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (result["revision"], change_kind, _canonical(prev),
             _canonical(new), actor, created_at, client_request_id))

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
                # An owner typing the assignee is the owner confirming it, so the
                # provenance becomes `manual` whatever the text happens to be.
                # This is what resolves a row whose source was never recorded.
                changes["assignee_source"] = "manual"
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
            self._begin_write()
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
                    " prepared_by_name=?, assignee_source=?, archived=?,"
                    " revision=? WHERE tab_id=? AND revision=?",
                    (new["display_key"], new["prepared_on"], new["prepared_by_name"],
                     new.get("assignee_source", current.get("assignee_source", "") or ""),
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
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
                self._rollback_write()
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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
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
                self._rollback_write()
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
                self._begin_write()
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
                    self._commit_write()
                except SaveError as exc:
                    try:
                        self._rollback_write()
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
                    self._rollback_write()
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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
                except Exception:
                    pass
                raise SaveError("EDIT_CONFLICT", "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요")
            except Exception:
                self._rollback_write()
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
            self._begin_write()
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
                self._commit_write()
            except SaveError as exc:
                try:
                    self._rollback_write()
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
                    self._rollback_write()
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
                self._rollback_write()
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
            self._begin_write()
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    try:
                        self._rollback_write()
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
                self._commit_write()
            except SaveError:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self._rollback_write()
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
                self._rollback_write()
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
            self._begin_write()
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    try:
                        self._rollback_write()
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
                self._commit_write()
            except SaveError:
                try:
                    self._rollback_write()
                except Exception:
                    pass
                raise
            except sqlite3.IntegrityError:
                try:
                    self._rollback_write()
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
                self._rollback_write()
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
                self._begin_write()
            try:
                dup = self.conn.execute(
                    "SELECT result_json FROM board_requests WHERE client_request_id=?",
                    (client_request_id,),
                ).fetchone()
                if dup:
                    dup_stored = json.loads(dup[0])
                    if not outer_txn:
                        try:
                            self._rollback_write()
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
                    self._commit_write()
            except SaveError:
                if not outer_txn:
                    try:
                        self._rollback_write()
                    except Exception:
                        pass
                raise
            except sqlite3.IntegrityError:
                if not outer_txn:
                    try:
                        self._rollback_write()
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
                    self._rollback_write()
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

    def _commit_write(self) -> None:
        """Commit and hand the reserved space back."""
        try:
            self.conn.commit()
        finally:
            self._release_write_space()

    def _outbox_commit(self) -> None:
        try:
            if not self.conn.in_transaction:
                self.conn.commit()
        except Exception:
            pass

    def _enqueue_ledger(self, *, outbox_id: str, stream_id: str, action: str,
                        target, rationale: str, actor: str) -> None:
        """같은 쓰기 트랜잭션 안에 정본 사건 payload를 남긴다. 호출자는 트랜잭션 소유."""
        if self._embedded_audit:
            if not self.conn.in_transaction:
                raise LedgerError('audit requires the board transaction')
            event, _ = self.ledger.append(
                stream_id=stream_id, action=action,
                target_direct_event_key=target, rationale=rationale,
                actor_local_id=actor, client_request_id=outbox_id)
            # 기존 화면의 event_id 조회용 호환 기록이다. 전달 작업은 만들지 않는다.
            self.conn.execute(
                'INSERT OR IGNORE INTO ledger_outbox(outbox_id,stream_id,action,'
                'target_direct_event_key,rationale,actor_local_id,event_id,relayed,created_at)'
                ' VALUES (?,?,?,?,?,?,?,1,?)',
                (outbox_id,stream_id,action,target,rationale,actor,event['event_id'],_utc_now()))
            return
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
        self._begin_write()
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
            self._commit_write()
        except Exception:
            self._rollback_write()
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
        self._begin_write()
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
                self._rollback_write()
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
            self._commit_write()
        except Exception:
            self._rollback_write()
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
        self._begin_write()
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
            self._commit_write()
        except Exception:
            self._rollback_write()
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

    def _register_process_lease(self) -> None:
        """Claim or refresh this process's lease. Called on every store use."""
        now = _utc_now()
        self.conn.execute(
            "INSERT INTO rule_process_leases(run_id, pid, started_at, heartbeat_at)"
            " VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET"
            " heartbeat_at=excluded.heartbeat_at",
            (_PROCESS_RUN_ID, _PROCESS_PID, now, now))

    def _turn_owner_state(self, process_run_id: str, alive_probe=None) -> tuple:
        """Classify the owner of a pending turn.

        Returns (decision, reason). Only a confirmed dead owner may be
        abandoned. A live owner and an owner this process cannot confirm are both
        preserved, and the unknown case is recorded for review.
        """
        if not process_run_id:
            return ("preserve", "unknown_owner")
        lease = self.conn.execute(
            "SELECT pid, heartbeat_at FROM rule_process_leases WHERE run_id=?",
            (process_run_id,)).fetchone()
        if lease is None:
            # No lease was ever written, so nothing proves the owner is gone.
            return ("preserve", "unknown_owner")
        probe = alive_probe or _process_alive
        alive = probe(lease[0])
        fresh = _lease_age_seconds(lease[1]) <= LEASE_TTL_SECONDS
        if alive is None:
            # The owner cannot be inspected, so it is not confirmed dead.
            return ("preserve", "owner_state_unknown")
        if alive and fresh:
            return ("preserve", "owner_alive")
        if alive:
            # The pid is running but the heartbeat is old. A recycled pid looks
            # exactly like this, so the turn is kept.
            return ("preserve", "owner_pid_reused")
        if fresh:
            # The pid is gone but the lease is still inside its window. The
            # owner may be shutting down, so the turn is kept.
            return ("preserve", "owner_still_leased")
        return ("abandon", "process_restart")

    def _abandon_orphan_turns(self) -> list:
        """Recover only the turns whose owner is confirmed dead.

        A turn of a live process and a turn of unknown ownership stay pending.
        Unknown ownership is written to the review table instead of being
        resolved on a guess.
        """
        rows = self.conn.execute(
            "SELECT turn_id, process_run_id FROM rule_turns WHERE state='pending'"
            " AND process_run_id<>?", (self._process_run_id,)).fetchall()
        if not rows:
            return []
        now = _utc_now()
        self._begin_write()
        try:
            recovered = []
            for turn_id, owner in rows:
                decision, reason = self._turn_owner_state(owner)
                if decision == "abandon":
                    self.conn.execute(
                        "UPDATE rule_turns SET state='abandoned', abandoned_reason=?"
                        " WHERE turn_id=?", (reason, turn_id))
                    self.conn.execute(
                        "DELETE FROM rule_orphan_reviews WHERE turn_id=?", (turn_id,))
                    recovered.append(turn_id)
                elif reason not in ("owner_alive",):
                    self.conn.execute(
                        "INSERT OR REPLACE INTO rule_orphan_reviews(turn_id,"
                        " process_run_id, reason, created_at) VALUES (?,?,?,?)",
                        (turn_id, owner or "", reason, now))
            self._commit_write()
        except Exception:
            self._rollback_write()
            raise
        return recovered

    def _replay_pending(self) -> None:
        self._register_process_lease()
        self._abandon_orphan_turns()
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


def _source_fact_digest(facts: dict) -> str:
    """A digest of the source facts alone, with no column dropped.

    Deliberately not the ledger's row digest: this covers the seventeen columns
    as they arrived, so an edit a user made on the board afterwards does not make
    the next apply look like a changed source, and a changed source is not hidden
    by an edit.
    """
    canonical = json.dumps(facts, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_amount(value) -> int:
    """원화금액 as an integer, sign and zero kept.

    A zero and a negative are facts. Rounding them away, or treating an absolute
    value as the amount, would turn a cancellation into a purchase.
    """
    if value is None:
        return 0
    text = str(value).strip().replace(",", "")
    if text == "":
        return 0
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError, ArithmeticError):
        raise SaveError("APPLY_SOURCE_AMOUNT_INVALID",
                        "원천 금액을 읽지 못했어요") from None
