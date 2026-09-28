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
                "SELECT tab_id, valid_until FROM access_trip_assignments"
                " WHERE user_id=? AND state=?", (user_id, ASSIGN_ACTIVE)):
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
    def apply_assignment_snapshot(self, *, user_id: str, items: list,
                                  source_version: str,
                                  validity: timedelta = DEFAULT_VALIDITY,
                                  now: datetime | None = None,
                                  complete: bool = True) -> dict:
        """Apply one reservation snapshot.

        `items` is the full assignment list of that source version. Every
        entry carries its own `snapshot_revision` and state. Application is
        monotonic per (user, trip): an entry whose revision is not newer than
        the stored head is ignored, so a revoked-at-5 permission is not
        restored by an active-at-3 that arrives afterwards.

        `complete=False` means the page is partial. A trip missing from a
        partial page is left alone rather than treated as revoked, because a
        missing row is not evidence of a revocation (SPEC 15.2).
        """
        if validity <= timedelta(0):
            raise AccessError("INVALID_VALUE", "유효기간이 필요해요", status=422)
        if validity > MAX_REVOCATION_DELAY:
            raise AccessError(
                "INVALID_VALUE",
                "유효기간이 해제 지연 상한을 넘어요", status=422)
        now = now or utc_now()
        if not self.account(user_id):
            raise AccessError(RESOURCE_NOT_FOUND, "계정이 없어요")
        applied, ignored = [], []
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for item in items:
                    tab_id = str(item.get("tab_id") or "").strip()
                    if not tab_id:
                        continue
                    state = item.get("state") or ASSIGN_ACTIVE
                    if state not in (ASSIGN_ACTIVE, ASSIGN_REVOKED):
                        raise AccessError("INVALID_VALUE", "배정 상태가 올바르지 않아요",
                                          status=422)
                    try:
                        revision = int(item.get("snapshot_revision"))
                    except (TypeError, ValueError):
                        raise AccessError("INVALID_VALUE", "배정 revision이 필요해요",
                                          status=422)
                    if revision < 0:
                        raise AccessError("INVALID_VALUE", "배정 revision이 올바르지 않아요",
                                          status=422)
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
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
        return {"user_id": user_id, "source_version": source_version or "",
                "complete": bool(complete), "applied": applied,
                "ignored_older": ignored,
                "visible_tabs": sorted(self.visible_tabs(user_id, now=now))}

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
        """
        with self.lock:
            self.conn.execute(
                "INSERT INTO access_reservation_persons(reservation_person_id,"
                " display_name, nickname, is_active, disambiguator)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(reservation_person_id) DO UPDATE SET"
                " display_name=excluded.display_name, nickname=excluded.nickname,"
                " is_active=excluded.is_active,"
                " disambiguator=excluded.disambiguator",
                (reservation_person_id, display_name or "", nickname or "",
                 1 if is_active else 0, disambiguator or ""))
            self.conn.commit()
        return self.reservation_person(reservation_person_id)

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
