"""Database schema definition and table column ensure helpers for LedgerStore.

Extracted under RF-101 (Store decomposition schema responsibility bundle).
Verbatim extraction preserving exact DDL, defaults, and column check semantics.
"""
from __future__ import annotations

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


# Kept apart from SCHEMA_SQL, which a test pins to its base commit.
INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_board_rows_display_tab ON board_rows(display_tab_id, row_id);
"""


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
