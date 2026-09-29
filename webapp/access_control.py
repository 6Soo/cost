"""Phase 7 access control: roles, the staff link flow, trip assignment
snapshots and the evidence preview boundary.

Scope and boundary
------------------
This is the local synthetic implementation of SPEC_REFINEMENT 15 and 16 and
PHASES Phase 7. It is NOT connected to a real identity provider. Google OIDC
(16.1) is deliberately not implemented here: there is no client id, no
callback allowlist and no key material in this repository, and none of it may
be invented. `SyntheticSession` below is the test seam that stands in for a
verified session, and it is refused unless a caller explicitly binds it.

Decisions recorded from the specification:

* Logging in is not access. The first account is never auto-promoted to owner.
  Ownership comes from `ensure_owner`, which refuses to guess from a display
  name, an email string or a first-visit order (15.1).
* The account key is a stable provider subject id, never an email or a
  nickname, so a rename cannot mint a new account or a new permission (15.1).
* Both relations must hold to see a trip: the account link must be active AND
  a currently valid assignment snapshot must name the trip (15.1).
* An older assignment snapshot must never restore a permission that a newer
  snapshot revoked. Assignment application is monotonic in the source
  revision, so a revoked-at-5 stays revoked when an active-at-3 arrives
  (15.2). A missing trip in a partial page is not a revocation (15.2).
* Every read is decided on the server. A trip, row or evidence the caller may
  not see answers 404 rather than 403, so existence does not leak (15.3).
* Viewer responses are built from an allowlist rather than by stripping owner
  fields (15.3).
* Evidence access is checked row -> trip -> valid assignment -> what may be
  shown. Knowing an evidence id never yields the original file, and there is
  no viewer download path at all (15.4, 15.5).
* A permission cache records `last_verified_at` and `valid_until`. The window
  is a required argument and is never treated as unlimited (15.2).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# A permission cache window is required. The default is deliberately short so
# a revoked assignment stops being served quickly; the operational value has to
# be set with the measured lookup cost (SPEC 15.2).
DEFAULT_VALIDITY = timedelta(minutes=30)

# The maximum delay a revocation can be served for is bounded by the window.
# Longer windows trade revocation latency for fewer origin lookups.
MAX_REVOCATION_DELAY = timedelta(hours=24)

ROLE_OWNER = "owner"
ROLE_VIEWER = "viewer"

# The response vocabulary is named by DETAILED_CONTRACT 4.3 so the board and
# the access store speak one language. An internal caller may raise a
# different code, but these are the codes a client sees.
AUTH_REQUIRED = "AUTH_REQUIRED"
ACTION_FORBIDDEN = "ACTION_FORBIDDEN"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"

APPLICATION_PENDING = "pending"
APPLICATION_APPROVED = "approved"
APPLICATION_REJECTED = "rejected"
APPLICATION_WITHDRAWN = "withdrawn"

CONNECTION_ACTIVE = "active"
CONNECTION_REVOKED = "revoked"

ASSIGN_ACTIVE = "active"
ASSIGN_REVOKED = "revoked"

# Sync refusal codes. Every one is raised as AccessError with the status shown
# so the importer and the ops rehearsal can map them to stable exit codes.
# Stale (older revision) is NOT an error: it answers ignored_stale_or_equal.
SNAPSHOT_CONFLICT = "SNAPSHOT_CONFLICT"  # same revision, different digest: 409
SNAPSHOT_EMPTY_REQUIRES_OVERRIDE = "SNAPSHOT_EMPTY_REQUIRES_OVERRIDE"  # 409
SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE = "SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE"  # 409
UNKNOWN_TRIP = "UNKNOWN_TRIP"  # assignment names a trip that is not there: 422

# SQLite wait policy for the reservation sync path. Matches the board store
# (`ledger_store` sets the same value): wait up to 5s for a lock, then answer
# TEMPORARILY_UNAVAILABLE (503, retry with the same request) instead of
# crashing. The importer opens its connection with timeout=10.0 on top.
BUSY_TIMEOUT_MS = 5000
TRANSIENT_SQLITE_MARKERS = ("database is locked", "database table is locked",
                            "database is busy")

# Rows a viewer may receive. Everything else, including the internal memo, the
# change history and anything the AI conversation produced, is not here.
VIEWER_ROW_FIELDS = (
    "row_id",
    "row_kind",
    "display_tab_id",
    "occurred_on",
    "item",
    "description",
    "amount_krw",
    "currency",
    "income_kind",
    "customer_name",
    "reservation_no",
    "source_kind",
    "source_merchant",
    "evidence_type",
    "source_event_id",
    "is_cancellation",
)

# Never sent to a viewer, listed for the audit trail and the tests.
VIEWER_DENIED_FIELDS = (
    "operator_note",
    "memo_internal",
    "card_last4",
    "approval_no",
    "bank_account_ref",
    "rule_id",
    "learning_case_id",
)

# Routes only an owner may reach. A viewer gets 404 on each of them.
OWNER_ONLY_PATHS = (
    "/import",
    "/export",
    "/trips",
    "/rules",
    "/api/imports",
    "/api/bank-imports",
    "/api/exports",
    "/api/classification",
    "/api/trips",
    "/api/rows",
    "/api/income",
)

# The original evidence file is never served to anyone through the board, and
# never to a viewer by any route.
EVIDENCE_ORIGINAL_DENIED = "EVIDENCE_ORIGINAL_DENIED"
EVIDENCE_NOT_SEPARATED = "EVIDENCE_NOT_SEPARATED"
EVIDENCE_UNSUPPORTED = "EVIDENCE_UNSUPPORTED"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS access_accounts (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_synthetic INTEGER NOT NULL DEFAULT 1,
    session_generation INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_applications (
    application_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    requested_name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_connections (
    connection_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    reservation_person_id TEXT NOT NULL,
    reservation_person_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS access_application_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 1,
    client_request_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_requests (
    client_request_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_reservation_persons (
    reservation_person_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    disambiguator TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS access_trip_assignments (
    assignment_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tab_id TEXT NOT NULL,
    state TEXT NOT NULL,
    snapshot_revision INTEGER NOT NULL,
    source_version TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    valid_until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_trip_assignment_heads (
    user_id TEXT NOT NULL,
    tab_id TEXT NOT NULL,
    head_snapshot_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, tab_id)
);
CREATE TABLE IF NOT EXISTS access_reservation_directory_head (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
    snapshot_revision INTEGER NOT NULL,
    digest TEXT NOT NULL,
    source_version TEXT NOT NULL DEFAULT '',
    exported_at TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_reservation_sync_attempts (
    attempt_id TEXT PRIMARY KEY,
    snapshot_revision INTEGER NOT NULL,
    digest TEXT NOT NULL DEFAULT '',
    source_version TEXT NOT NULL DEFAULT '',
    persons_seen INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    error_code TEXT NOT NULL DEFAULT '',
    persons_deactivated INTEGER NOT NULL DEFAULT 0,
    connections_revoked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_evidence (
    evidence_id TEXT PRIMARY KEY,
    tab_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'image',
    separation_state TEXT NOT NULL DEFAULT 'original_only',
    separated_version TEXT NOT NULL DEFAULT '',
    separated_sha256 TEXT NOT NULL DEFAULT '',
    original_sha256 TEXT NOT NULL DEFAULT '',
    allowed_tabs_json TEXT NOT NULL DEFAULT '[]'
);
"""


class AccessError(Exception):
    """Refusal with a code, so a route can answer 404 without leaking why."""

    def __init__(self, code: str, message: str = "", *, status: int = 404):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status = status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_transient_sqlite(exc: BaseException) -> bool:
    """True when the database is locked/busy and the same request may retry."""
    text = str(exc).lower()
    return any(marker in text for marker in TRANSIENT_SQLITE_MARKERS)


# --------------------------------------------------------------- identity
@dataclass(frozen=True)
class Session:
    """A verified session. `provider` is the stable account key.

    `is_synthetic` marks the local stand-in. Nothing in the board treats a
    synthetic session as a real login; the field exists so a report can say
    which of the two was exercised.
    """

    user_id: str
    display_name: str = ""
    email: str = ""
    provider: str = "synthetic"
    is_synthetic: bool = True
    session_generation: int = 0

    def cache_namespace(self) -> str:
        """Account plus generation, so a revoked session cannot reuse a cache."""
        return f"{self.provider}:{self.user_id}:{self.session_generation}"


class SyntheticSessionAdapter:
    """Test seam for the identity provider. Refused unless explicitly bound.

    SPEC 16.1 forbids using a synthetic token or a development role switch as
    operational authentication, so the adapter only reads a request header and
    only when `bind_sessions` was called with `allow_synthetic=True`. The
    header is not a credential: it selects an account that must already exist
    in the accounts table with a role.

    The session is stamped with the account's current generation, so a request
    is always judged against the generation that is in force now. The
    `GENERATION_HEADER` exists so a test can present an older generation and
    observe that a stale session is refused (SPEC 15.3).
    """

    HEADER = "X-Synthetic-User"
    GENERATION_HEADER = "X-Synthetic-Generation"

    def __init__(self, allow_synthetic: bool = False, access_store=None):
        self.allow_synthetic = bool(allow_synthetic)
        self._access = access_store

    def bind_store(self, access_store) -> None:
        self._access = access_store

    def session_for(self, headers, cookies=None) -> Session | None:
        if not self.allow_synthetic:
            return None
        user_id = (headers.get(self.HEADER) or "").strip()
        if not user_id:
            return None
        generation = 0
        presented = (headers.get(self.GENERATION_HEADER) or "").strip()
        if presented:
            try:
                generation = int(presented)
            except ValueError:
                return None
        if not generation and self._access is not None:
            generation = self._access.session_generation(user_id)
        return Session(user_id=user_id, provider="synthetic", is_synthetic=True,
                       session_generation=generation)


class UnboundSessionAdapter:
    """The default: no session is ever established, so nothing is served."""

    def session_for(self, headers, cookies=None) -> Session | None:
        return None


_SESSION_ADAPTER = UnboundSessionAdapter()
_SESSION_LOCK = threading.Lock()


def bind_sessions(adapter) -> None:
    global _SESSION_ADAPTER
    with _SESSION_LOCK:
        _SESSION_ADAPTER = adapter or UnboundSessionAdapter()


def session_adapter():
    return _SESSION_ADAPTER


def bind_synthetic_sessions(allow: bool = True) -> None:
    bind_sessions(SyntheticSessionAdapter(allow_synthetic=allow))


# --------------------------------------------------------------- the store
class AccessStore:
    """Roles, the link application flow, and assignment snapshots.

    It keeps its own tables in the same SQLite file as the board so one file
    still holds the whole local state, but it never edits the board's tables
    and never writes a row revision or an income event. A connection change is
    an access record, not a ledger event (SPEC 16.4).
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock | None = None):
        self.conn = conn
        self.lock = lock or threading.RLock()
        self.ensure_schema()

    # ------------------------------------------------------------- schema
    def ensure_schema(self) -> None:
        with self.lock:
            self.conn.executescript(SCHEMA_SQL)
            self._migrate_columns()
            self.conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self.conn.commit()

    def _migrate_columns(self) -> None:
        """Add a column to a table created before it existed.

        A database made by an earlier version must gain the new column rather
        than be dropped and rebuilt: the access records inside it are the
        authority and must not be recreated from nothing.
        """
        present = {r[1] for r in self.conn.execute("PRAGMA table_info(access_accounts)")}
        if "session_generation" not in present:
            self.conn.execute(
                "ALTER TABLE access_accounts ADD COLUMN"
                " session_generation INTEGER NOT NULL DEFAULT 1")
        head_present = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(access_reservation_directory_head)")}
        if "persons_seen" not in head_present:
            # Older heads counted nobody. A legacy head reports 0, which
            # disables the large-drop ratio once (fail-open exactly once) and
            # every later head carries the real count.
            self.conn.execute(
                "ALTER TABLE access_reservation_directory_head ADD COLUMN"
                " persons_seen INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------- request reuse
    def _replay(self, scope: str, client_request_id: str, payload: dict):
        """Reuse a verified earlier result, refuse the same id with new content."""
        if not client_request_id or not isinstance(client_request_id, str):
            raise AccessError("INVALID_VALUE", "요청 ID가 필요해요", status=422)
        digest = sha256_text(canonical(payload))
        row = self.conn.execute(
            "SELECT payload_sha256, result_json FROM access_requests"
            " WHERE client_request_id=?", (client_request_id,)).fetchone()
        if row:
            if row[0] != digest:
                raise AccessError(
                    "REQUEST_ID_REUSED",
                    "같은 요청 ID로 다른 내용을 보냈어요", status=409)
            return json.loads(row[1])
        return None

    def _record(self, scope: str, client_request_id: str, payload: dict,
                result: dict) -> None:
        self.conn.execute(
            "INSERT INTO access_requests(client_request_id, scope,"
            " payload_sha256, result_json, created_at) VALUES (?,?,?,?,?)",
            (client_request_id, scope, sha256_text(canonical(payload)),
             canonical(result), iso(utc_now())))

    def _run(self, scope: str, client_request_id: str, payload: dict,
             work) -> dict:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                replayed = self._replay(scope, client_request_id, payload)
                if replayed is not None:
                    self.conn.execute("ROLLBACK")
                    return replayed
                result = work()
                self._record(scope, client_request_id, payload, result)
                self.conn.execute("COMMIT")
                return result
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------ accounts
    def create_account(self, *, user_id: str, role: str, display_name: str = "",
                       email: str = "", is_active: bool = True,
                       is_synthetic: bool = True) -> dict:
        """Create an account with an explicit role. Never auto-promotes."""
        user_id = (user_id or "").strip()
        if not user_id:
            raise AccessError("INVALID_VALUE", "사용자 ID가 필요해요", status=422)
        if role not in (ROLE_OWNER, ROLE_VIEWER):
            raise AccessError("INVALID_VALUE", "역할이 올바르지 않아요", status=422)
        now = iso(utc_now())
        with self.lock:
            self.conn.execute(
                "INSERT INTO access_accounts(user_id, display_name, email, role,"
                " is_active, is_synthetic, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " display_name=excluded.display_name, email=excluded.email,"
                " role=excluded.role, is_active=excluded.is_active,"
                " updated_at=excluded.updated_at",
                (user_id, display_name or "", email or "", role,
                 1 if is_active else 0, 1 if is_synthetic else 0, now, now))
            self.conn.commit()
        return self.account(user_id)

    def ensure_owner(self, user_id: str) -> dict:
        """The single owner bootstrap, and it only runs when none exists.

        SPEC 15.1: ownership is deployment configuration or this explicit
        call, never the first account to arrive. A second call is refused so
        the owner cannot be handed out by a race.
        """
        with self.lock:
            existing = self.conn.execute(
                "SELECT user_id FROM access_accounts WHERE role=?"
                " AND is_active=1", (ROLE_OWNER,)).fetchone()
            if existing:
                if existing[0] != user_id:
                    raise AccessError(
                        "OWNER_ALREADY_SET",
                        f"이미 소유자가 {existing[0]}로 정해져 있어요", status=409)
                return self.account(user_id)
        return self.create_account(user_id=user_id, role=ROLE_OWNER)

    def account(self, user_id: str):
        row = self.conn.execute(
            "SELECT user_id, display_name, email, role, is_active, is_synthetic,"
            " session_generation, created_at, updated_at"
            " FROM access_accounts WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return {
            "user_id": row[0], "display_name": row[1], "email": row[2],
            "role": row[3], "is_active": bool(row[4]),
            "is_synthetic": bool(row[5]), "session_generation": row[6],
            "created_at": row[7], "updated_at": row[8],
        }

    def account_role(self, user_id: str):
        row = self.conn.execute(
            "SELECT role, is_active FROM access_accounts WHERE user_id=?",
            (user_id,)).fetchone()
        if not row or not row[1]:
            return None
        return row[0]

    def set_account_active(self, *, user_id: str, is_active: bool) -> dict:
        with self.lock:
            if not self.account(user_id):
                raise AccessError(RESOURCE_NOT_FOUND, "계정이 없어요")
            self.conn.execute(
                "UPDATE access_accounts SET is_active=?, updated_at=?"
                " WHERE user_id=?", (1 if is_active else 0, iso(utc_now()),
                                     user_id))
            # Deactivating an account must also end the sessions that were
            # established while it was active (SPEC 15.3).
            if not is_active:
                self._bump_generation(user_id)
            self.conn.commit()
        return self.account(user_id)

    def session_generation(self, user_id: str) -> int:
        """The account's current generation.

        A session established under an older generation is stale and must not
        be served, so a revoke, a deactivation or an account switch cannot be
        answered from data the client already holds (SPEC 15.3).
        """
        row = self.conn.execute(
            "SELECT session_generation FROM access_accounts WHERE user_id=?",
            (user_id,)).fetchone()
        return int(row[0]) if row else 0

    def _bump_generation(self, user_id: str) -> int:
        self.conn.execute(
            "UPDATE access_accounts"
            " SET session_generation = session_generation + 1, updated_at=?"
            " WHERE user_id=?", (iso(utc_now()), user_id))
        row = self.conn.execute(
            "SELECT session_generation FROM access_accounts WHERE user_id=?",
            (user_id,)).fetchone()
        return int(row[0]) if row else 0

    def bump_session_generation(self, user_id: str) -> int:
        """End every session of one account, for a logout or an account switch."""
        with self.lock:
            if not self.account(user_id):
                raise AccessError(RESOURCE_NOT_FOUND, "계정이 없어요")
            value = self._bump_generation(user_id)
            self.conn.commit()
        return value

    def list_accounts(self, role: str | None = None) -> list:
        if role:
            rows = self.conn.execute(
                "SELECT user_id FROM access_accounts WHERE role=? ORDER BY user_id",
                (role,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT user_id FROM access_accounts ORDER BY user_id").fetchall()
        return [self.account(r[0]) for r in rows]

    # --------------------------------------------------------- permissions
    def is_owner(self, user_id: str) -> bool:
        return self.account_role(user_id) == ROLE_OWNER

    def require_owner(self, user_id: str) -> None:
        if not self.is_owner(user_id):
            # 404 so a viewer cannot map the owner's routes by status code.
            raise AccessError(RESOURCE_NOT_FOUND, "없는 경로예요")

    def visible_tabs(self, user_id: str, *, now: datetime | None = None) -> set:
        """The trips a viewer may read right now.

        Requires an active account, an active connection and an assignment that
        is both locally not revoked and inside its own validity window.
        """
        if self.account_role(user_id) == ROLE_OWNER:
            return {t["tab_id"] for t in self._live_tabs()}
        now = now or utc_now()
        if not self.account_role(user_id):
            return set()
        if not self._active_connection(user_id):
            return set()
        allowed = set()
        # The cache window is applied per request (SPEC 15.2).
        for row in self.conn.execute(
                "SELECT a.tab_id, a.valid_until"
                " FROM access_trip_assignments a"
                " JOIN access_trip_assignment_heads h"
                "   ON h.user_id=a.user_id AND h.tab_id=a.tab_id"
                "  AND h.head_snapshot_revision=a.snapshot_revision"
                "  AND h.state=a.state"
                " WHERE a.user_id=? AND a.state=?", (user_id, ASSIGN_ACTIVE)):
            until = parse_iso(row[1])
            if until is not None and until <= now:
                continue
            allowed.add(row[0])
        return allowed

    def _live_tabs(self) -> list:
        rows = self.conn.execute(
            "SELECT tab_id FROM trip_tabs WHERE deleted=0 AND archived=0"
            " ORDER BY starts_on, tab_id").fetchall()
        return [{"tab_id": r[0]} for r in rows]

    def can_view_tab(self, user_id: str, tab_id: str, *,
                     now: datetime | None = None) -> bool:
        if not tab_id:
            return False
        return tab_id in self.visible_tabs(user_id, now=now)

    def require_view_tab(self, user_id: str, tab_id: str, *,
                         now: datetime | None = None) -> None:
        if not self.can_view_tab(user_id, tab_id, now=now):
            # 404 rather than 403: the caller must not learn it exists.
            raise AccessError(RESOURCE_NOT_FOUND, "없는 경로예요")

    # ---------------------------------------------------- assignment sync
    def _prepare_assignment_snapshot(self, *, items: list, complete: bool,
                                     snapshot_revision: int | None):
        normalized = []
        item_revisions = set()
        for item in items:
            tab_id = str(item.get("tab_id") or "").strip()
            if not tab_id:
                continue
            state = item.get("state") or ASSIGN_ACTIVE
            if state not in (ASSIGN_ACTIVE, ASSIGN_REVOKED):
                raise AccessError("INVALID_VALUE", "invalid assignment state",
                                  status=422)
            try:
                revision = int(item.get("snapshot_revision"))
            except (TypeError, ValueError):
                raise AccessError("INVALID_VALUE", "assignment revision required",
                                  status=422)
            if revision < 0:
                raise AccessError("INVALID_VALUE", "invalid assignment revision",
                                  status=422)
            item_revisions.add(revision)
            normalized.append((item, tab_id, state, revision))

        complete_revision = None
        if snapshot_revision is not None:
            try:
                complete_revision = int(snapshot_revision)
            except (TypeError, ValueError):
                raise AccessError("INVALID_VALUE", "snapshot revision required",
                                  status=422)
            if complete_revision < 0:
                raise AccessError("INVALID_VALUE", "invalid snapshot revision",
                                  status=422)
        elif complete and len(item_revisions) == 1:
            complete_revision = next(iter(item_revisions))
        elif complete and len(item_revisions) > 1:
            raise AccessError(
                "INVALID_VALUE",
                "complete snapshot requires an explicit snapshot revision",
                status=422)
        return normalized, complete_revision

    def _apply_assignment_snapshot_tx(self, *, user_id: str, normalized: list,
                                      source_version: str, validity: timedelta,
                                      now: datetime, complete: bool,
                                      complete_revision: int | None) -> dict:
        applied, ignored = [], []
        mentioned_tabs = set()
        for item, tab_id, state, revision in normalized:
            mentioned_tabs.add(tab_id)
            head = self.conn.execute(
                "SELECT head_snapshot_revision, state"
                " FROM access_trip_assignment_heads WHERE user_id=? AND tab_id=?",
                (user_id, tab_id)).fetchone()
            if head is not None and revision <= head[0]:
                ignored.append({"tab_id": tab_id, "snapshot_revision": revision,
                                "head": head[0], "head_state": head[1]})
                continue
            assignment_id = item.get("assignment_id") or uuid.uuid4().hex
            valid_until = iso(now + validity)
            self.conn.execute(
                "INSERT INTO access_trip_assignments("
                " assignment_id, user_id, tab_id, state, snapshot_revision,"
                " source_version, observed_at, last_verified_at, valid_until)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(assignment_id) DO UPDATE SET"
                " state=excluded.state,"
                " snapshot_revision=excluded.snapshot_revision,"
                " source_version=excluded.source_version,"
                " observed_at=excluded.observed_at,"
                " last_verified_at=excluded.last_verified_at,"
                " valid_until=excluded.valid_until",
                (assignment_id, user_id, tab_id, state, revision,
                 source_version or "", iso(now), iso(now), valid_until))
            self.conn.execute(
                "INSERT INTO access_trip_assignment_heads("
                " user_id, tab_id, head_snapshot_revision, state, updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(user_id, tab_id) DO UPDATE SET"
                " head_snapshot_revision=excluded.head_snapshot_revision,"
                " state=excluded.state, updated_at=excluded.updated_at",
                (user_id, tab_id, revision, state, iso(now)))
            applied.append({"tab_id": tab_id, "state": state,
                            "snapshot_revision": revision})

        if complete:
            active_heads = self.conn.execute(
                "SELECT tab_id, head_snapshot_revision"
                " FROM access_trip_assignment_heads"
                " WHERE user_id=? AND state=?",
                (user_id, ASSIGN_ACTIVE)).fetchall()
            omitted = [(tab_id, head_revision)
                       for tab_id, head_revision in active_heads
                       if tab_id not in mentioned_tabs]
            if omitted and complete_revision is None:
                raise AccessError(
                    "INVALID_VALUE",
                    "empty complete snapshot requires snapshot revision",
                    status=422)
            for tab_id, head_revision in omitted:
                if complete_revision <= head_revision:
                    ignored.append({
                        "tab_id": tab_id,
                        "snapshot_revision": complete_revision,
                        "head": head_revision,
                        "head_state": ASSIGN_ACTIVE,
                        "omitted_from_complete_snapshot": True,
                    })
                    continue
                assignment_id = uuid.uuid4().hex
                valid_until = iso(now + validity)
                self.conn.execute(
                    "INSERT INTO access_trip_assignments("
                    " assignment_id, user_id, tab_id, state, snapshot_revision,"
                    " source_version, observed_at, last_verified_at, valid_until)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (assignment_id, user_id, tab_id, ASSIGN_REVOKED,
                     complete_revision, source_version or "", iso(now),
                     iso(now), valid_until))
                self.conn.execute(
                    "UPDATE access_trip_assignment_heads"
                    " SET head_snapshot_revision=?, state=?, updated_at=?"
                    " WHERE user_id=? AND tab_id=?",
                    (complete_revision, ASSIGN_REVOKED, iso(now),
                     user_id, tab_id))
                applied.append({
                    "tab_id": tab_id,
                    "state": ASSIGN_REVOKED,
                    "snapshot_revision": complete_revision,
                    "omitted_from_complete_snapshot": True,
                })
        return {"applied": applied, "ignored_older": ignored}

    def apply_assignment_snapshot(self, *, user_id: str, items: list,
                                  source_version: str,
                                  validity: timedelta = DEFAULT_VALIDITY,
                                  now: datetime | None = None,
                                  complete: bool = True,
                                  snapshot_revision: int | None = None) -> dict:
        """Apply one reservation snapshot.

        Each item carries its own snapshot_revision and state. Application is
        monotonic per (user, trip): an entry whose revision is not newer than
        the stored head is ignored, so an older active row cannot restore a
        permission revoked by a newer row.

        complete=False means the page is partial. A trip missing from a partial
        page is left alone rather than treated as revoked (SPEC 15.2).

        A complete snapshot revokes active assignments omitted from the
        snapshot. The snapshot-level revision is used for those revoke rows.
        It may be inferred when every supplied item has the same revision;
        otherwise snapshot_revision must be provided explicitly.
        """
        if validity <= timedelta(0):
            raise AccessError("INVALID_VALUE", "validity must be positive", status=422)
        if validity > MAX_REVOCATION_DELAY:
            raise AccessError(
                "INVALID_VALUE",
                "validity exceeds the maximum revocation delay", status=422)
        now = now or utc_now()
        if not self.account(user_id):
            raise AccessError(RESOURCE_NOT_FOUND, "account not found")

        normalized, complete_revision = self._prepare_assignment_snapshot(
            items=items, complete=complete, snapshot_revision=snapshot_revision)
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if _is_transient_sqlite(exc):
                    raise AccessError(
                        TEMPORARILY_UNAVAILABLE,
                        "잠시 저장할 수 없어요. 같은 요청으로 다시 확인해 주세요",
                        status=503)
                raise
            try:
                result = self._apply_assignment_snapshot_tx(
                    user_id=user_id, normalized=normalized,
                    source_version=source_version, validity=validity, now=now,
                    complete=complete, complete_revision=complete_revision)
                self.conn.execute("COMMIT")
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        return {"user_id": user_id, "source_version": source_version or "",
                "complete": bool(complete), "applied": result["applied"],
                "ignored_older": result["ignored_older"],
                "visible_tabs": sorted(self.visible_tabs(user_id, now=now))}

    def reservation_directory_head(self):
        row = self.conn.execute(
            "SELECT snapshot_revision, digest, source_version, exported_at, imported_at,"
            " persons_seen"
            " FROM access_reservation_directory_head WHERE singleton_id=1").fetchone()
        if not row:
            return None
        return {"snapshot_revision": row[0], "digest": row[1],
                "source_version": row[2], "exported_at": row[3],
                "imported_at": row[4], "persons_seen": row[5]}

    # ------------------------------------------------- sync attempt audit
    def _log_sync_attempt(self, *, revision: int, digest: str,
                          source_version: str, persons_seen: int,
                          outcome: str, error_code: str = "",
                          persons_deactivated: int = 0,
                          connections_revoked: int = 0) -> None:
        """Record one sync attempt, including refusals.

        The log lives beside the directory head so an operator can answer
        "what tried to change access and what was the answer" without
        replaying snapshots. It is written in its own commit AFTER the main
        transaction rolled back or committed, so a refusal is recorded even
        though it changed nothing else. Best effort: logging must never turn
        a successful sync into a failure.
        """
        try:
            with self.lock:
                self.conn.execute(
                    "INSERT INTO access_reservation_sync_attempts("
                    " attempt_id, snapshot_revision, digest, source_version,"
                    " persons_seen, outcome, error_code, persons_deactivated,"
                    " connections_revoked, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, revision, digest or "",
                     source_version or "", persons_seen, outcome,
                     error_code or "", persons_deactivated,
                     connections_revoked, iso(utc_now())))
                self.conn.commit()
        except Exception:
            pass

    def list_sync_attempts(self, *, limit: int = 50) -> list:
        """Newest sync attempts first, for the audit trail and the tests."""
        rows = self.conn.execute(
            "SELECT snapshot_revision, digest, source_version, persons_seen,"
            " outcome, error_code, persons_deactivated, connections_revoked,"
            " created_at FROM access_reservation_sync_attempts"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, int(limit)),)).fetchall()
        return [{"snapshot_revision": r[0], "digest": r[1],
                 "source_version": r[2], "persons_seen": r[3],
                 "outcome": r[4], "error_code": r[5],
                 "persons_deactivated": r[6], "connections_revoked": r[7],
                 "created_at": r[8]} for r in rows]

    def _known_trip_ids(self) -> set | None:
        """Live trip directory, or None when there is no trip table at all."""
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='trip_tabs'").fetchone()
        if not row:
            return None
        return {r[0] for r in self.conn.execute("SELECT tab_id FROM trip_tabs")}

    def sync_reservation_access_snapshot(self, *, snapshot: dict,
                                          validity: timedelta = DEFAULT_VALIDITY,
                                          now: datetime | None = None,
                                          allow_empty: bool = False,
                                          allow_large_drop: bool = False) -> dict:
        """Atomically synchronize the complete Reservation access directory.

        Fail-closed guards, in order:

        * older revision: ignored as stale, never applied;
        * same revision with a different digest: refused as SNAPSHOT_CONFLICT
          (409) instead of silently ignored, so a forked export cannot hide
          behind an equal revision;
        * empty person list: refused as SNAPSHOT_EMPTY_REQUIRES_OVERRIDE (409)
          unless ``allow_empty`` is set, so an empty export is never read as
          "everyone left";
        * every assigned trip code must exist in ``trip_tabs`` (UNKNOWN_TRIP,
          422), so a typo cannot mint an invisible permission;
        * a directory that shrank to less than half its previous size is
          refused as SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE (409) unless
          ``allow_large_drop`` is set, so a truncated export cannot revoke
          everyone at once.

        Every attempt -- applied, ignored, or refused -- is recorded in
        ``access_reservation_sync_attempts``. A locked database answers
        TEMPORARILY_UNAVAILABLE (503) instead of raising.
        """
        if validity <= timedelta(0) or validity > MAX_REVOCATION_DELAY:
            raise AccessError("INVALID_VALUE", "invalid assignment validity", status=422)
        try:
            revision = int(snapshot["snapshot_revision"])
            persons = list(snapshot["persons"])
            digest = str(snapshot["digest"])
            source_version = str(snapshot["schema_version"])
            exported_at = str(snapshot["exported_at"])
        except (KeyError, TypeError, ValueError):
            raise AccessError("INVALID_VALUE", "invalid reservation access snapshot",
                              status=422)
        if revision < 0 or not digest:
            raise AccessError("INVALID_VALUE", "invalid reservation access snapshot",
                              status=422)
        now = now or utc_now()

        def refused(outcome: str, code: str, message: str, status: int):
            self._log_sync_attempt(
                revision=revision, digest=digest,
                source_version=source_version, persons_seen=len(persons),
                outcome=outcome, error_code=code)
            raise AccessError(code, message, status=status)

        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if _is_transient_sqlite(exc):
                    self._log_sync_attempt(
                        revision=revision, digest=digest,
                        source_version=source_version,
                        persons_seen=len(persons),
                        outcome="transient_unavailable",
                        error_code=TEMPORARILY_UNAVAILABLE)
                    raise AccessError(
                        TEMPORARILY_UNAVAILABLE,
                        "잠시 저장할 수 없어요. 같은 요청으로 다시 확인해 주세요",
                        status=503)
                raise
            try:
                head = self.reservation_directory_head()
                if head is not None and revision < head["snapshot_revision"]:
                    self.conn.execute("ROLLBACK")
                    self._log_sync_attempt(
                        revision=revision, digest=digest,
                        source_version=source_version,
                        persons_seen=len(persons), outcome="ignored_stale")
                    return {
                        "snapshot_revision": revision,
                        "digest": digest,
                        "ignored_stale_or_equal": True,
                        "persons_seen": len(persons),
                        "persons_deactivated": 0,
                        "connections_revoked": 0,
                        "sessions_bumped": 0,
                        "connected_persons_synced": 0,
                        "assignments_applied": 0,
                        "assignments_ignored_older": 0,
                    }
                if head is not None and revision == head["snapshot_revision"]:
                    if digest == head["digest"]:
                        self.conn.execute("ROLLBACK")
                        self._log_sync_attempt(
                            revision=revision, digest=digest,
                            source_version=source_version,
                            persons_seen=len(persons),
                            outcome="ignored_idempotent")
                        return {
                            "snapshot_revision": revision,
                            "digest": digest,
                            "ignored_stale_or_equal": True,
                            "persons_seen": len(persons),
                            "persons_deactivated": 0,
                            "connections_revoked": 0,
                            "sessions_bumped": 0,
                            "connected_persons_synced": 0,
                            "assignments_applied": 0,
                            "assignments_ignored_older": 0,
                        }
                    self.conn.execute("ROLLBACK")
                    refused("conflict", SNAPSHOT_CONFLICT,
                            "같은 revision인데 내용이 달라요. 내보내기를 확인해 주세요",
                            409)

                if not persons and not allow_empty:
                    self.conn.execute("ROLLBACK")
                    refused("empty_requires_override",
                            SNAPSHOT_EMPTY_REQUIRES_OVERRIDE,
                            "빈 명단은 적용하지 않아요. 전체 해지가 맞다면 명시적으로 확인해 주세요",
                            409)

                prior_seen = head["persons_seen"] if head is not None else 0
                # An explicitly confirmed empty list already says "everyone
                # left", so it does not need the large-drop flag as well.
                if (persons and head is not None and prior_seen > 0
                        and len(persons) * 2 < prior_seen
                        and not allow_large_drop):
                    self.conn.execute("ROLLBACK")
                    refused("large_drop_requires_override",
                            SNAPSHOT_LARGE_DROP_REQUIRES_OVERRIDE,
                            "명단이 절반 이하로 줄었어요. 잘린 내보내기가 아닌지 확인해 주세요",
                            409)

                wanted_trips = set()
                for person in persons:
                    if person.get("is_active"):
                        for trip_code in person.get("assignments") or []:
                            wanted_trips.add(str(trip_code))
                if wanted_trips:
                    known = self._known_trip_ids()
                    if known is None:
                        self.conn.execute("ROLLBACK")
                        refused("unknown_trip", UNKNOWN_TRIP,
                                "여행 목록을 확인할 수 없어요. 장부 DB에 적용해 주세요",
                                422)
                    unknown = sorted(wanted_trips - known)[:20]
                    if unknown:
                        self.conn.execute("ROLLBACK")
                        refused("unknown_trip", UNKNOWN_TRIP,
                                "없는 여행 코드가 있어요: " + ", ".join(unknown),
                                422)

                source_ids = set()
                active_people = {}
                for person in persons:
                    person_id = str(person["reservation_person_id"])
                    source_ids.add(person_id)
                    is_active = bool(person["is_active"])
                    self.conn.execute(
                        "INSERT INTO access_reservation_persons("
                        " reservation_person_id, display_name, nickname, is_active, disambiguator)"
                        " VALUES (?,?,?,?,?)"
                        " ON CONFLICT(reservation_person_id) DO UPDATE SET"
                        " display_name=excluded.display_name,"
                        " nickname=excluded.nickname,"
                        " is_active=excluded.is_active",
                        (person_id, str(person.get("display_name") or ""),
                         str(person.get("nickname") or ""), 1 if is_active else 0, ""))
                    if is_active:
                        active_people[person_id] = person

                known_ids = {row[0] for row in self.conn.execute(
                    "SELECT reservation_person_id FROM access_reservation_persons")}
                omitted_ids = known_ids - source_ids
                if omitted_ids:
                    placeholders = ",".join("?" for _ in omitted_ids)
                    self.conn.execute(
                        f"UPDATE access_reservation_persons SET is_active=0"
                        f" WHERE reservation_person_id IN ({placeholders})",
                        tuple(sorted(omitted_ids)))

                inactive_ids = source_ids - set(active_people)
                revoke_ids = omitted_ids | inactive_ids
                revoked_users = []
                if revoke_ids:
                    placeholders = ",".join("?" for _ in revoke_ids)
                    rows = self.conn.execute(
                        f"SELECT connection_id, user_id FROM access_connections"
                        f" WHERE status=? AND reservation_person_id IN ({placeholders})",
                        (CONNECTION_ACTIVE, *tuple(sorted(revoke_ids)))).fetchall()
                    for connection_id, user_id in rows:
                        stamp = iso(now)
                        self.conn.execute(
                            "UPDATE access_connections SET status=?, revision=revision+1,"
                            " updated_at=?, revoked_at=? WHERE connection_id=?",
                            (CONNECTION_REVOKED, stamp, stamp, connection_id))
                        self._bump_generation(user_id)
                        revoked_users.append(user_id)

                synced = 0
                assignment_applied = 0
                assignment_ignored = 0
                for person_id, person in active_people.items():
                    rows = self.conn.execute(
                        "SELECT user_id FROM access_connections"
                        " WHERE reservation_person_id=? AND status=?",
                        (person_id, CONNECTION_ACTIVE)).fetchall()
                    for (user_id,) in rows:
                        items = [{"tab_id": trip_code, "state": ASSIGN_ACTIVE,
                                  "snapshot_revision": revision}
                                 for trip_code in person["assignments"]]
                        normalized, complete_revision = self._prepare_assignment_snapshot(
                            items=items, complete=True, snapshot_revision=revision)
                        result = self._apply_assignment_snapshot_tx(
                            user_id=user_id, normalized=normalized,
                            source_version=source_version, validity=validity, now=now,
                            complete=True, complete_revision=complete_revision)
                        synced += 1
                        assignment_applied += len(result["applied"])
                        assignment_ignored += len(result["ignored_older"])

                imported_at = iso(now)
                self.conn.execute(
                    "INSERT INTO access_reservation_directory_head("
                    " singleton_id, snapshot_revision, digest, source_version,"
                    " exported_at, imported_at, persons_seen) VALUES (1,?,?,?,?,?,?)"
                    " ON CONFLICT(singleton_id) DO UPDATE SET"
                    " snapshot_revision=excluded.snapshot_revision,"
                    " digest=excluded.digest,"
                    " source_version=excluded.source_version,"
                    " exported_at=excluded.exported_at,"
                    " imported_at=excluded.imported_at,"
                    " persons_seen=excluded.persons_seen",
                    (revision, digest, source_version, exported_at, imported_at,
                     len(persons)))
                self.conn.execute("COMMIT")
            except AccessError:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            except sqlite3.OperationalError as exc:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if _is_transient_sqlite(exc):
                    self._log_sync_attempt(
                        revision=revision, digest=digest,
                        source_version=source_version,
                        persons_seen=len(persons),
                        outcome="transient_unavailable",
                        error_code=TEMPORARILY_UNAVAILABLE)
                    raise AccessError(
                        TEMPORARILY_UNAVAILABLE,
                        "잠시 저장할 수 없어요. 같은 요청으로 다시 확인해 주세요",
                        status=503)
                self._log_sync_attempt(
                    revision=revision, digest=digest,
                    source_version=source_version,
                    persons_seen=len(persons), outcome="db_error",
                    error_code="DB_UNAVAILABLE")
                raise
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                self._log_sync_attempt(
                    revision=revision, digest=digest,
                    source_version=source_version,
                    persons_seen=len(persons), outcome="error",
                    error_code="SYNC_FAILED")
                raise

        self._log_sync_attempt(
            revision=revision, digest=digest, source_version=source_version,
            persons_seen=len(persons), outcome="applied",
            persons_deactivated=len(omitted_ids) + len(inactive_ids),
            connections_revoked=len(revoked_users))
        return {
            "snapshot_revision": revision,
            "digest": digest,
            "ignored_stale_or_equal": False,
            "persons_seen": len(persons),
            "persons_deactivated": len(omitted_ids) + len(inactive_ids),
            "connections_revoked": len(revoked_users),
            "sessions_bumped": len(revoked_users),
            "connected_persons_synced": synced,
            "assignments_applied": assignment_applied,
            "assignments_ignored_older": assignment_ignored,
        }

    def assignment_head(self, user_id: str, tab_id: str):
        row = self.conn.execute(
            "SELECT head_snapshot_revision, state FROM access_trip_assignment_heads"
            " WHERE user_id=? AND tab_id=?", (user_id, tab_id)).fetchone()
        if not row:
            return None
        return {"snapshot_revision": row[0], "state": row[1]}

    # ------------------------------------------------ application workflow
    def _event(self, application_id, from_status, to_status, actor, reason,
               revision, client_request_id):
        self.conn.execute(
            "INSERT INTO access_application_events(application_id, from_status,"
            " to_status, actor, reason, revision, client_request_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (application_id, from_status or "", to_status or "", actor or "",
             reason or "", revision, client_request_id or "", iso(utc_now())))

    def application(self, application_id: str):
        row = self.conn.execute(
            "SELECT application_id, user_id, requested_name, nickname, description,"
            " status, revision, decided_by, decision_reason, created_at, updated_at"
            " FROM access_applications WHERE application_id=?",
            (application_id,)).fetchone()
        if not row:
            return None
        return {
            "application_id": row[0], "user_id": row[1],
            "requested_name": row[2], "nickname": row[3],
            "description": row[4], "status": row[5], "revision": row[6],
            "decided_by": row[7], "decision_reason": row[8],
            "created_at": row[9], "updated_at": row[10],
        }

    def applications_for(self, user_id: str) -> list:
        rows = self.conn.execute(
            "SELECT application_id FROM access_applications WHERE user_id=?"
            " ORDER BY created_at, application_id", (user_id,)).fetchall()
        return [self.application(r[0]) for r in rows]

    def pending_applications(self) -> list:
        rows = self.conn.execute(
            "SELECT application_id FROM access_applications WHERE status=?"
            " ORDER BY created_at, application_id",
            (APPLICATION_PENDING,)).fetchall()
        return [self.application(r[0]) for r in rows]

    def create_application(self, *, user_id: str, requested_name: str,
                           nickname: str = "", description: str = "",
                           client_request_id: str) -> dict:
        """Open an application. The user id comes from the session, not the body.

        A second open application for the same account is refused instead of
        stacking, and an existing one is returned (SPEC 16.2/16.4).
        """
        payload = {"user_id": user_id, "requested_name": requested_name,
                   "nickname": nickname, "description": description}

        def work():
            if self.account_role(user_id) is None:
                raise AccessError(RESOURCE_NOT_FOUND, "계정이 없어요")
            open_row = self.conn.execute(
                "SELECT application_id FROM access_applications"
                " WHERE user_id=? AND status IN (?,?)",
                (user_id, APPLICATION_PENDING, APPLICATION_APPROVED)).fetchone()
            if open_row:
                return self.application(open_row[0])
            application_id = f"app-{uuid.uuid4().hex[:16]}"
            now = iso(utc_now())
            self.conn.execute(
                "INSERT INTO access_applications(application_id, user_id,"
                " requested_name, nickname, description, status, revision,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (application_id, user_id, requested_name or "", nickname or "",
                 description or "", APPLICATION_PENDING, 1, now, now))
            self._event(application_id, "", APPLICATION_PENDING, user_id, "", 1,
                        client_request_id)
            return self.application(application_id)

        return self._run("application.create", client_request_id, payload, work)

    def update_application(self, *, application_id: str, user_id: str,
                           expected_revision: int, requested_name=None,
                           nickname=None, description=None,
                           client_request_id: str) -> dict:
        payload = {"application_id": application_id, "user_id": user_id,
                   "expected_revision": expected_revision,
                   "requested_name": requested_name, "nickname": nickname,
                   "description": description}

        def work():
            current = self.application(application_id)
            if current is None or current["user_id"] != user_id:
                raise AccessError(RESOURCE_NOT_FOUND, "없는 신청이에요")
            if current["status"] != APPLICATION_PENDING:
                raise AccessError("APPLICATION_NOT_PENDING",
                                  "대기 중인 신청만 고칠 수 있어요", status=409)
            if current["revision"] != expected_revision:
                raise AccessError("EDIT_CONFLICT",
                                  "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요",
                                  status=409)
            changes = {}
            if requested_name is not None:
                changes["requested_name"] = str(requested_name)
            if nickname is not None:
                changes["nickname"] = str(nickname)
            if description is not None:
                changes["description"] = str(description)
            revision = current["revision"] + 1
            sets = ", ".join(f"{k}=?" for k in changes)
            self.conn.execute(
                f"UPDATE access_applications SET {sets}, revision=?, updated_at=?"
                " WHERE application_id=?",
                (*changes.values(), revision, iso(utc_now()), application_id))
            self._event(application_id, current["status"], current["status"],
                        user_id, "update", revision, client_request_id)
            return self.application(application_id)

        return self._run("application.update", client_request_id, payload, work)

    def withdraw_application(self, *, application_id: str, user_id: str,
                             expected_revision: int,
                             client_request_id: str) -> dict:
        payload = {"application_id": application_id, "user_id": user_id,
                   "expected_revision": expected_revision, "action": "withdraw"}

        def work():
            current = self.application(application_id)
            if current is None or current["user_id"] != user_id:
                raise AccessError(RESOURCE_NOT_FOUND, "없는 신청이에요")
            if current["status"] != APPLICATION_PENDING:
                raise AccessError("APPLICATION_NOT_PENDING",
                                  "대기 중인 신청만 철회할 수 있어요", status=409)
            if current["revision"] != expected_revision:
                raise AccessError("EDIT_CONFLICT",
                                  "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요",
                                  status=409)
            revision = current["revision"] + 1
            self.conn.execute(
                "UPDATE access_applications SET status=?, revision=?, updated_at=?"
                " WHERE application_id=?",
                (APPLICATION_WITHDRAWN, revision, iso(utc_now()),
                 application_id))
            self._event(application_id, current["status"], APPLICATION_WITHDRAWN,
                        user_id, "", revision, client_request_id)
            return self.application(application_id)

        return self._run("application.withdraw", client_request_id, payload, work)

    # ------------------------------------------------- owner decisions
    def register_reservation_person(self, *, reservation_person_id: str,
                                     display_name: str, nickname: str = "",
                                     disambiguator: str = "",
                                     is_active: bool = True) -> dict:
        """Synthetic stand-in for the reservation system's person directory.

        The owner picks one id from this list. A shared name is not an
        identity, so `disambiguator` exists to tell duplicates apart and the
        approval path refuses to guess.

        Labels follow the snapshot parser policy (length cap, no control
        characters). An empty `disambiguator` never clears a stored one: it
        means "no change", so re-registering a person without the field keeps
        the value that told duplicates apart.
        """
        from ledger.domain.reservation_access_snapshot import (
            DISPLAY_NAME_MAX_LEN, check_label_text)
        try:
            person_id = check_label_text(reservation_person_id,
                                         "reservation_person_id")
            display_name = check_label_text(display_name, "display_name",
                                            allow_empty=True,
                                            max_len=DISPLAY_NAME_MAX_LEN)
            nickname = check_label_text(nickname, "nickname", allow_empty=True)
            disambiguator = check_label_text(disambiguator, "disambiguator",
                                             allow_empty=True)
        except ValueError as exc:
            raise AccessError("INVALID_VALUE", f"담당자 이름이 올바르지 않아요: {exc}",
                              status=422)
        with self.lock:
            if not disambiguator:
                existing = self.reservation_person(person_id)
                if existing and existing.get("disambiguator"):
                    disambiguator = existing["disambiguator"]
            self.conn.execute(
                "INSERT INTO access_reservation_persons(reservation_person_id,"
                " display_name, nickname, is_active, disambiguator)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(reservation_person_id) DO UPDATE SET"
                " display_name=excluded.display_name, nickname=excluded.nickname,"
                " is_active=excluded.is_active,"
                " disambiguator=excluded.disambiguator",
                (person_id, display_name or "", nickname or "",
                 1 if is_active else 0, disambiguator or ""))
            self.conn.commit()
        return self.reservation_person(person_id)

    def reservation_person(self, reservation_person_id: str):
        row = self.conn.execute(
            "SELECT reservation_person_id, display_name, nickname, is_active,"
            " disambiguator FROM access_reservation_persons"
            " WHERE reservation_person_id=?", (reservation_person_id,)).fetchone()
        if not row:
            return None
        return {"reservation_person_id": row[0], "display_name": row[1],
                "nickname": row[2], "is_active": bool(row[3]),
                "disambiguator": row[4]}

    def list_reservation_persons(self, *, only_active: bool = False) -> list:
        sql = "SELECT reservation_person_id FROM access_reservation_persons"
        if only_active:
            sql += " WHERE is_active=1"
        rows = self.conn.execute(sql + " ORDER BY display_name").fetchall()
        return [self.reservation_person(r[0]) for r in rows]

    def find_reservation_persons_by_name(self, name: str) -> list:
        rows = self.conn.execute(
            "SELECT reservation_person_id FROM access_reservation_persons"
            " WHERE display_name=? ORDER BY reservation_person_id",
            (name or "",)).fetchall()
        return [self.reservation_person(r[0]) for r in rows]

    def approve_application(self, *, application_id: str, owner_id: str,
                            expected_revision: int,
                            reservation_person_id: str,
                            client_request_id: str) -> dict:
        """Approve and link in one transaction.

        The person must exist and be active, and the same person or the same
        account must not already be connected. Re-approving the identical pair
        is a verified reuse, not a second connection (SPEC 16.3).
        """
        payload = {"application_id": application_id, "owner_id": owner_id,
                   "expected_revision": expected_revision,
                   "reservation_person_id": reservation_person_id}

        def work():
            self.require_owner(owner_id)
            current = self.application(application_id)
            if current is None:
                raise AccessError(RESOURCE_NOT_FOUND, "없는 신청이에요")
            existing_person = self.conn.execute(
                "SELECT connection_id, user_id, status FROM access_connections"
                " WHERE reservation_person_id=? AND status=?",
                (reservation_person_id, CONNECTION_ACTIVE)).fetchone()
            existing_user = self.conn.execute(
                "SELECT connection_id, reservation_person_id FROM access_connections"
                " WHERE user_id=? AND status=?",
                (current["user_id"], CONNECTION_ACTIVE)).fetchone()
            # Re-approving the identical account/person pair is a verified
            # reuse, not a second connection and not a conflict (SPEC 16.3).
            if (current["status"] == APPLICATION_APPROVED and existing_user
                    and existing_user[1] == reservation_person_id):
                return {"application": current,
                        "connection": self.connection(existing_user[0])}
            # The application's own state is reported before anything about the
            # person or the account, so a withdrawn or rejected application is
            # not disguised as a person conflict (SPEC 16.5: the reasons are not
            # merged into one message).
            if current["status"] != APPLICATION_PENDING:
                raise AccessError("APPLICATION_NOT_PENDING",
                                  "대기 중인 신청만 승인할 수 있어요", status=409)
            person = self.reservation_person(reservation_person_id)
            if person is None:
                raise AccessError("PERSON_NOT_FOUND",
                                  "예약 담당자를 먼저 선택해 주세요", status=422)
            if not person["is_active"]:
                raise AccessError("PERSON_INACTIVE",
                                  "비활성 담당자는 연결할 수 없어요", status=422)
            if existing_person and existing_person[1] != current["user_id"]:
                raise AccessError(
                    "PERSON_ALREADY_LINKED",
                    "다른 계정이 이미 이 담당자를 쓰고 있어요", status=409)
            if existing_user:
                raise AccessError(
                    "ACCOUNT_ALREADY_LINKED",
                    "이 계정은 이미 다른 담당자와 연결돼 있어요", status=409)
            if current["revision"] != expected_revision:
                raise AccessError("EDIT_CONFLICT",
                                  "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요",
                                  status=409)
            now = iso(utc_now())
            revision = current["revision"] + 1
            connection_id = f"conn-{uuid.uuid4().hex[:16]}"
            self.conn.execute(
                "INSERT INTO access_connections(connection_id, user_id,"
                " reservation_person_id, reservation_person_label, status,"
                " revision, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (connection_id, current["user_id"], reservation_person_id,
                 person["display_name"], CONNECTION_ACTIVE, 1, now, now))
            self.conn.execute(
                "UPDATE access_applications SET status=?, revision=?,"
                " decided_by=?, updated_at=? WHERE application_id=?",
                (APPLICATION_APPROVED, revision, owner_id, now, application_id))
            self._event(application_id, current["status"], APPLICATION_APPROVED,
                        owner_id, "", revision, client_request_id)
            return {"application": self.application(application_id),
                    "connection": self.connection(connection_id)}

        return self._run("application.approve", client_request_id, payload, work)

    def reject_application(self, *, application_id: str, owner_id: str,
                           expected_revision: int, reason: str,
                           client_request_id: str) -> dict:
        payload = {"application_id": application_id, "owner_id": owner_id,
                   "expected_revision": expected_revision, "reason": reason}

        def work():
            self.require_owner(owner_id)
            current = self.application(application_id)
            if current is None:
                raise AccessError(RESOURCE_NOT_FOUND, "없는 신청이에요")
            if current["status"] == APPLICATION_REJECTED:
                return current
            if current["status"] != APPLICATION_PENDING:
                raise AccessError("APPLICATION_NOT_PENDING",
                                  "대기 중인 신청만 거절할 수 있어요", status=409)
            if current["revision"] != expected_revision:
                raise AccessError("EDIT_CONFLICT",
                                  "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요",
                                  status=409)
            revision = current["revision"] + 1
            now = iso(utc_now())
            self.conn.execute(
                "UPDATE access_applications SET status=?, revision=?,"
                " decided_by=?, decision_reason=?, updated_at=?"
                " WHERE application_id=?",
                (APPLICATION_REJECTED, revision, owner_id, reason or "", now,
                 application_id))
            self._event(application_id, current["status"], APPLICATION_REJECTED,
                        owner_id, reason, revision, client_request_id)
            return self.application(application_id)

        return self._run("application.reject", client_request_id, payload, work)

    def connection(self, connection_id: str):
        row = self.conn.execute(
            "SELECT connection_id, user_id, reservation_person_id,"
            " reservation_person_label, status, revision, created_at,"
            " updated_at, revoked_at FROM access_connections WHERE connection_id=?",
            (connection_id,)).fetchone()
        if not row:
            return None
        return {"connection_id": row[0], "user_id": row[1],
                "reservation_person_id": row[2],
                "reservation_person_label": row[3], "status": row[4],
                "revision": row[5], "created_at": row[6], "updated_at": row[7],
                "revoked_at": row[8]}

    def active_connection(self, user_id: str):
        row = self.conn.execute(
            "SELECT connection_id FROM access_connections"
            " WHERE user_id=? AND status=?", (user_id, CONNECTION_ACTIVE)).fetchone()
        return self.connection(row[0]) if row else None

    def _active_connection(self, user_id: str):
        row = self.conn.execute(
            "SELECT connection_id FROM access_connections"
            " WHERE user_id=? AND status=?", (user_id, CONNECTION_ACTIVE)).fetchone()
        return self.connection(row[0]) if row else None

    def revoke_connection(self, *, connection_id: str, owner_id: str,
                          expected_revision: int,
                          client_request_id: str) -> dict:
        payload = {"connection_id": connection_id, "owner_id": owner_id,
                   "expected_revision": expected_revision}

        def work():
            self.require_owner(owner_id)
            current = self.connection(connection_id)
            if current is None:
                raise AccessError(RESOURCE_NOT_FOUND, "없는 연결이에요")
            if current["status"] == CONNECTION_REVOKED:
                return current
            if current["revision"] != expected_revision:
                raise AccessError("EDIT_CONFLICT",
                                  "다른 저장이 먼저 됐어요. 최신 값을 보고 다시 저장해 주세요",
                                  status=409)
            revision = current["revision"] + 1
            now = iso(utc_now())
            self.conn.execute(
                "UPDATE access_connections SET status=?, revision=?,"
                " updated_at=?, revoked_at=? WHERE connection_id=?",
                (CONNECTION_REVOKED, revision, now, now, connection_id))
            # Revoking a link ends the account's sessions, so a client that
            # still holds the old generation cannot be answered with data
            # that was allowed under the revoked link (SPEC 15.3).
            self._bump_generation(current["user_id"])
            return self.connection(connection_id)

        return self._run("connection.revoke", client_request_id, payload, work)

    # ------------------------------------------------------------ evidence
    def register_evidence(self, *, evidence_id: str, tab_id: str = "",
                          kind: str = "image", separation_state: str = "original_only",
                          separated_version: str = "", separated_sha256: str = "",
                          original_sha256: str = "", allowed_tabs: list | None = None) -> dict:
        with self.lock:
            self.conn.execute(
                "INSERT INTO access_evidence(evidence_id, tab_id, kind,"
                " separation_state, separated_version, separated_sha256,"
                " original_sha256, allowed_tabs_json) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(evidence_id) DO UPDATE SET tab_id=excluded.tab_id,"
                " kind=excluded.kind,"
                " separation_state=excluded.separation_state,"
                " separated_version=excluded.separated_version,"
                " separated_sha256=excluded.separated_sha256,"
                " original_sha256=excluded.original_sha256,"
                " allowed_tabs_json=excluded.allowed_tabs_json",
                (evidence_id, tab_id or "", kind, separation_state,
                 separated_version, separated_sha256, original_sha256,
                 canonical(sorted(allowed_tabs or []))))
            self.conn.commit()
        return self.evidence(evidence_id)

    def evidence(self, evidence_id: str):
        row = self.conn.execute(
            "SELECT evidence_id, tab_id, kind, separation_state,"
            " separated_version, separated_sha256, original_sha256,"
            " allowed_tabs_json FROM access_evidence WHERE evidence_id=?",
            (evidence_id,)).fetchone()
        if not row:
            return None
        return {"evidence_id": row[0], "tab_id": row[1], "kind": row[2],
                "separation_state": row[3], "separated_version": row[4],
                "separated_sha256": row[5], "original_sha256": row[6],
                "allowed_tabs": json.loads(row[7] or "[]")}

    def evidence_preview(self, *, user_id: str, evidence_id: str,
                         now: datetime | None = None) -> dict:
        """Row -> trip -> valid assignment -> what may be shown, in that order.

        The original file is never returned and there is no download shape.
        A mixed original with no separated material reports the preparation
        gap instead of leaking the original (SPEC 15.4).
        """
        record = self.evidence(evidence_id)
        if record is None:
            raise AccessError(RESOURCE_NOT_FOUND, "없는 증빙이에요")
        if not self.can_view_tab(user_id, record["tab_id"], now=now):
            raise AccessError(RESOURCE_NOT_FOUND, "없는 증빙이에요")
        if record["kind"] not in ("image", "pdf"):
            raise AccessError(EVIDENCE_UNSUPPORTED,
                              "이 형식은 미리보기를 지원하지 않아요")
        if record["separation_state"] != "separated":
            return {"evidence_id": evidence_id, "state": "preparation_needed",
                    "allowed_tabs": record["allowed_tabs"],
                    "message": "여행 전용으로 나눈 자료가 아직 준비되지 않았어요",
                    "original_available": False}
        return {"evidence_id": evidence_id, "state": "ready", "kind": record["kind"],
                "separated_version": record["separated_version"],
                "separated_sha256": record["separated_sha256"],
                "allowed_tabs": record["allowed_tabs"],
                "preview_path": f"/evidence/preview/{evidence_id}",
                "original_available": False}

    def owner_evidence_preview(self, evidence_id: str) -> dict:
        record = self.evidence(evidence_id)
        if record is None:
            raise AccessError(RESOURCE_NOT_FOUND, "없는 증빙이에요")
        return dict(record, state="owner_original_reference",
                    original_available=True)


def attach_to_ledger_store(ledger_store) -> "AccessStore":
    """Build an AccessStore on the same SQLite file and reuse its lock.

    The access tables live beside the board tables so one file still holds the
    whole local state, but nothing here writes a row revision, an income event
    or a history row: a connection or permission change is an access record,
    not a ledger event (SPEC 16.4).
    """
    conn = getattr(ledger_store, "conn", None)
    if conn is None:
        raise AccessError(RESOURCE_NOT_FOUND, "저장소가 연결되지 않았어요")
    lock = getattr(ledger_store, "_lock", None)
    return AccessStore(conn, lock=lock)


# ------------------------------------------------------------ projections
def project_rows_for_viewer(rows: list, allowed_tabs: set,
                            tab_id: str | None = None) -> list:
    """Allowlisted rows for the trips the caller may read, in a stable order."""
    out = []
    for row in rows:
        projected = project_row_for_viewer(row, allowed_tabs, tab_id)
        if projected is not None:
            out.append(projected)
    return out


def project_row_for_viewer(row: dict, allowed_tabs: set, tab_id: str | None = None):
    """Build a viewer row from the allowlist, or None when it is not visible."""
    row_tab = row.get("display_tab_id")
    if row_tab not in allowed_tabs:
        return None
    if tab_id is not None and row_tab != tab_id:
        return None
    return {key: row.get(key) for key in VIEWER_ROW_FIELDS}


def assert_no_denied_fields(payload: dict) -> None:
    """Guard for the tests: a viewer payload must not carry a denied field."""
    for field_name in VIEWER_DENIED_FIELDS:
        if field_name in payload:
            raise AccessError("LEAK", f"viewer payload leaked {field_name}",
                              status=500)
