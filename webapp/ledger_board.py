"""Phase 1 synthetic ledger board.

Read-only trial screen built from the synthetic C1~I3 fixture defined in
WEB_LEDGER_DETAILED_CONTRACT section 9. No source reading, no persistence,
no AI, no real reservation links. Every page states that data is synthetic.

Expected fixture totals (contract):
  trip A income 1000000, expense 180000, profit 820000
  customer U1 800000, U2 200000; unclassified 30000 (not in A expense)
"""

from __future__ import annotations

import html
import http.cookies
import datetime as dt
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlsplit

from .classification_rules import (SYNTHETIC_MODE_NOTE, dialog_state_label,
                                   question_view, reason_label)
from . import board_export_helpers, board_read_projection, board_render_helpers, read_scope, ui_icons

CSRF_TOKEN = secrets.token_hex(16)

# ------------------------------------------------------- the review feature
# Fixed refusal messages for the actual-source review. A code and a sentence a
# user can act on, and nothing else: no path, no digest, no value, no file
# content. The same code always means the same thing, so a log line built from
# it cannot carry source data either.
_REVIEW_MESSAGES = {
    "REVIEW_UNAVAILABLE": "실제 자료 검토가 설정되지 않았어요.",
    "REVIEW_CONFIG_INVALID": "실제 자료 설정이 올바르지 않아요.",
    "REVIEW_SOURCE_DRIFT": "실제 자료가 설정과 달라졌어요. 다시 확인해 주세요.",
    "REVIEW_REVISION_CONFLICT": "다른 기기에서 더 최근 결정을 저장했어요.",
    "REVIEW_SOURCE_BINDING_CONFLICT": "실제 자료가 바뀐 데이터에서 왔어요. 페이지를 다시 불러오고 실제 자료를 다시 확인해 주세요.",
    "REVIEW_DECISIONS_UNAVAILABLE": "결정 저장소를 열 수 없어요.",
    "REVIEW_INTERNAL_ERROR": "결정을 처리하지 못했어요.",
}

#: Codes that are the caller's fault rather than the deployment's, so they are
#: answered 400 instead of 503. The list is the core's own decision vocabulary.
_REVIEW_CLIENT_CODES = frozenset((
    "INVALID_ARGUMENT", "DECISION_SHAPE_INVALID", "DECISION_DUPLICATE_REF",
    "DECISION_UNKNOWN_REF", "DECISION_VALUE_INVALID", "INSUFFICIENT_EVIDENCE",
    "EXPORT_BINDING_MISMATCH",
))

#: The published origin, when there is one. Set, it is the only origin a review
#: write may come from, exactly and with no scheme fallback. Left unset, only this
#: server's own listening address is accepted, which is the local synthetic case.
_REVIEW_PUBLIC_BASE_URL_ENV = "WEBLEDGER_PUBLIC_BASE_URL"

_REVIEW_UNCONFIGURED_PAGE = (
    "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
    "<title>실제 자료 검토</title></head><body>"
    "<h1>실제 자료 검토를 쓸 수 없어요</h1>"
    "<p>실제 자료 검토는 서버 설정이 없거나 설정된 자료가 바뀌어서 지금은 열 수 "
    "없어요. 예제 자료로 대신 보여주지 않아요.</p>"
    "<p><a href='/board'>장부로 돌아가기</a></p></body></html>"
)
_STORE = None
_NO_REQUEST_STORE = object()
_REQUEST_STORE = ContextVar("ledger_request_store", default=_NO_REQUEST_STORE)


def _active_store():
    """Return the store for this request, or the process default outside one."""
    local = _REQUEST_STORE.get()
    return _STORE if local is _NO_REQUEST_STORE else local


def _get_card_db_path() -> str | None:
    """Get the card transactions database path from the active store's connection.
    Uses PRAGMA database_list to get the actual file path from the SQLite connection.
    Returns None if no store is bound or the connection has no file path.
    """
    store = _active_store()
    if store is None or store.conn is None:
        return None
    try:
        cursor = store.conn.execute('PRAGMA database_list')
        for row in cursor:
            # row = (seq, name, file_path)
            path = row[2]
            if path and path != '':
                return path
    except Exception:
        pass
    return None


def _store_request_locked(method):
    """Serialize database work after the HTTP request has been parsed."""
    def wrapped(self, *args, **kwargs):
        lock = getattr(self.server, "store_lock", None)
        # The liveness probe reads no store, so it must not queue behind a slow page.
        if lock is None or urlparse(self.path).path == "/healthz":
            return method(self, *args, **kwargs)
        with lock:
            if getattr(self.server, 'runtime_closing', False):
                self._send_json({'code': 'SERVER_STOPPING',
                                 'message': '서버가 종료 중입니다. 잠시 후 다시 시도해 주세요.'}, code=503)
                return
            return method(self, *args, **kwargs)

    wrapped.__name__ = getattr(method, "__name__", "wrapped")
    wrapped.__doc__ = getattr(method, "__doc__", None)
    return wrapped


_IMPORTER = None
_MUSE = None
_GEMINI = None
# Phase 6: the owner-only provider configuration service. Unbound by default.
_PROVIDER_CONFIG = None
_PROVIDER_AUTOWIRE = False
_PROVIDER_TRANSPORT = None
_ACCESS = None
# Phase 7b: the Google OIDC login flow. Unbound unless the deployment set the
# environment, so an unconfigured server keeps refusing every session.
_OIDC = None
# Phase 7: until an access store is bound the board keeps its pre-Phase-7
# single-operator behaviour, so owner functionality is unchanged. Binding a
# store turns on server-side role enforcement. The default session adapter
# establishes no session at all, so nothing is ever served as a viewer by
# accident, and a client-supplied header is not a credential.
ACCESS_ENFORCEMENT = False

# APP_SPEC 3 keeps `authority_status` its own responsibility, so a schedule's
# standing is shown as a value and never inferred from the tab's name. A tab made
# on screen reads as unconfirmed until its own source says otherwise.
AUTHORITY_LABELS = {
    "authoritative": "권위 있음",
    "needs_review": "검토 필요",
    "unconfirmed": "미확인",
    "conflicted": "충돌",
}

# The role a renderer should draw owner-only controls for. It is decided once per
# request on the server and kept per thread, so a screen can ask for it without
# the request object being threaded through every renderer, and one request's
# role can never reach another request's screen on the same server.
_ROLE_LOCAL = threading.local()


def resolve_role(headers, cookies=None) -> str:
    """Decide the role for this request, on the server, from the session only."""
    if not ACCESS_ENFORCEMENT:
        role = "owner"
        session = None
    else:
        session = current_session(headers, cookies)
        role = ("owner" if session is not None and is_owner_session(session)
                else "viewer")
    _ROLE_LOCAL.role = role
    _ROLE_LOCAL.session = session
    return role


def current_role() -> str:
    """The role decided for the request being served on this thread."""
    role = getattr(_ROLE_LOCAL, "role", None)
    if role is not None:
        return role
    return "viewer" if ACCESS_ENFORCEMENT else "owner"


def current_request_session():
    """The session decided for the request being served on this thread, or None.

    A renderer that has to narrow what it draws asks for this rather than
    re-reading the request, so the session it filters by is the same one the
    role was decided from. It is per thread, so one request's session can never
    reach another request's screen on the same server.
    """
    return getattr(_ROLE_LOCAL, "session", None)


def bind_store(store) -> None:
    global _STORE
    _STORE = store


def bind_access(access_store) -> None:
    """Attach the Phase 7 access store and turn on server-side enforcement."""
    global _ACCESS, ACCESS_ENFORCEMENT
    _ACCESS = access_store
    ACCESS_ENFORCEMENT = access_store is not None
    if access_store is not None:
        # An adapter that can read the account generation needs the store, so a
        # session is stamped with the generation that is in force now.
        adapter = access_control_session_adapter()
        binder = getattr(adapter, "bind_store", None)
        if callable(binder):
            binder(access_store)


def bind_oidc(flow) -> None:
    """Attach a connected Google login flow, or None to stay fail-closed.

    Binding a flow also binds its session adapter, so from this point every
    request is decided by a signed cookie. Passing None leaves the previous
    adapter alone, which is how a test detaches a flow without pretending the
    board forgot to ask.
    """
    global _OIDC
    _OIDC = flow
    return _OIDC


def oidc_flow():
    return _OIDC


def access_control_session_adapter():
    from . import access_control

    return access_control.session_adapter()


def access_store():
    return _ACCESS


def current_session(headers, cookies=None):
    """The session for this request, or None. Never trusts a request body."""
    from . import access_control

    if not ACCESS_ENFORCEMENT:
        return None
    return access_control.session_adapter().session_for(headers, cookies)


def require_session(headers, cookies=None):
    # Imported once at the top: an import inside a branch binds a local name
    # and the later use would raise UnboundLocalError.
    from . import access_control

    session = current_session(headers)
    if session is None:
        # 401 asks for a re-login and never says which path exists.
        raise access_control.AccessError(
            access_control.AUTH_REQUIRED, "다시 로그인해 주세요", status=401)
    if not _ACCESS.account_role(session.user_id):
        # An unknown or deactivated account is a re-login, not a 404: it says
        # nothing about whether any trip exists.
        raise access_control.AccessError(access_control.AUTH_REQUIRED,
                                         "계정을 먼저 연결해 주세요",
                                         status=401)
    # A session established before a permission change, a logout or an account
    # switch is stale. Refusing it is what stops a client from re-rendering
    # data it was allowed to see under the old generation (SPEC 15.3).
    current = _ACCESS.session_generation(session.user_id)
    if session.session_generation and session.session_generation < current:
        raise access_control.AccessError(
            "SESSION_STALE", "권한이 바뀌었어요. 다시 로그인해 주세요", status=401)
    return session


def _receipts_owner_request() -> bool:
    """Owner only, and only when the access store is enforcing. Enforcement off means no owner."""
    if not ACCESS_ENFORCEMENT:
        return False
    session = getattr(_ROLE_LOCAL, "session", None)
    return session is not None and is_owner_session(session)


def _participant_owner_request() -> bool:
    """참가 대조는 소유자만 본다. 인증을 강제하지 않는 서버에는 소유자가 없다.

    실명·참가 표시·원본 경로가 담기기 때문에, 인증 경계가 없는 서버에서는 열지 않는다.
    """
    if not ACCESS_ENFORCEMENT:
        return False
    session = getattr(_ROLE_LOCAL, "session", None)
    return session is not None and is_owner_session(session)
def _active_role(user_id) -> str | None:
    """The role the access store lists right now. A deactivated or removed account has none."""
    return _ACCESS.account_role(user_id) if _ACCESS else None


def is_owner_session(session) -> bool:
    if session is None or not _ACCESS:
        return False
    return _ACCESS.is_owner(session.user_id)


def viewer_visible_tabs(session) -> set:
    if session is None or not _ACCESS:
        return set()
    return _ACCESS.visible_tabs(session.user_id)


def deny_for_viewer(*, action: bool = False):
    """Refuse a request a viewer may not make.

    DETAILED_CONTRACT 4.3 separates the two cases. A read of a trip, row or
    evidence the caller may not see answers 404 `RESOURCE_NOT_FOUND` so its
    existence is not disclosed (SPEC 15.3). An action the role may never
    perform - a save, an export, a job lookup, a download - answers 403
    `ACTION_FORBIDDEN` instead, and that decision is taken before any resource
    is read, so the status does not depend on whether the resource exists.
    """
    from . import access_control

    if action:
        raise access_control.AccessError(access_control.ACTION_FORBIDDEN,
                                        "이 동작은 owner만 할 수 있어요",
                                        status=403)
    raise access_control.AccessError(access_control.RESOURCE_NOT_FOUND,
                                     "없는 경로예요")


def parts_value(path: str) -> str:
    return path.strip("/").split("/")[1] if path.strip("/").count("/") else ""


def google_oidc_connection_state() -> dict:
    """The real Google login connection state, from one place.

    This delegates to the same `google_oidc.connection_state` that
    `ops.google_oidc_state` uses, so the board, `/auth/state` and `ops health`
    cannot disagree about whether a login is connected. A second, separately
    written answer is what let `/access/me` report `false` on a host where the
    login worked. The access store is passed so the presence-only owner
    fields (`owner_exists`, `bootstrap_open`) describe this process without
    exposing any sub value.
    """
    from . import google_oidc

    return google_oidc.connection_state(oidc_flow(), _ACCESS)


def _bootstrap_guidance(*, role, oidc: dict) -> str:
    """Operator next step for owner bootstrap. Presence only, no sub values."""
    if role == "owner":
        return "owner already set; this session is owner"
    if not bool((oidc or {}).get("google_oidc_connected")):
        return "Google login is not connected; check deployment settings"
    if bool((oidc or {}).get("owner_exists")):
        return "owner already exists; no bootstrap; ask the owner for access"
    if not bool((oidc or {}).get("owner_bootstrap_configured")):
        return ("no owner yet and no owner sub configured; copy own_google_sub"
                " to WEBLEDGER_OWNER_GOOGLE_SUB, restart, then log in again")
    return ("owner sub is configured and no owner exists yet; the next login"
            " whose sub matches the configured value bootstraps")


# ------------------------------------------------- Phase 7 view rendering
def access_control_render_viewer_status(session, store) -> dict:
    """The viewer's own state, never another person's application list."""
    applications = store.applications_for(session.user_id)
    connection = store.active_connection(session.user_id)
    # The connection state is a fact about this deployment, read from the bound
    # flow rather than asserted. `identity_source` above says where *this*
    # session came from; this says whether a real Google login is available at
    # all, which is what an operator needs when the two disagree.
    oidc = google_oidc_connection_state()
    role = store.account_role(session.user_id)
    # Self-discovery only: an operator learns their own Google sub from their
    # own authenticated response so they can configure WEBLEDGER_OWNER_GOOGLE_SUB.
    # No other account identifier is included here, and the configured owner
    # value itself is never echoed.
    own_google_sub = (session.user_id if not session.is_synthetic
                      and session.provider == "google" else "")
    return {
        "user_id": session.user_id,
        "role": role,
        "email": session.email,
        "identity_source": "synthetic" if session.is_synthetic else "google_oidc",
        "google_oidc_connected": bool(oidc.get("google_oidc_connected")),
        "google_oidc": oidc,
        "own_google_sub": own_google_sub,
        "owner_exists": bool(oidc.get("owner_exists")),
        "bootstrap_guidance": _bootstrap_guidance(role=role, oidc=oidc),
        "session_generation": store.session_generation(session.user_id),
        "cache_namespace": session.cache_namespace(),
        "applications": applications,
        "connection": connection,
        "visible_tabs": sorted(store.visible_tabs(session.user_id)),
    }


def access_control_render_viewer_board(session, store, tab_id: str) -> str:
    """A viewer board with only its own trips, rows and totals.

    The response is built from the viewer allowlist. The internal memo, the
    change history and anything the AI conversation produced are not part of
    it, and no other trip name is rendered.
    """
    from . import access_control
    from . import ledger_design

    allowed = store.visible_tabs(session.user_id)
    trips = []
    # Trips and rows come from the ledger store; the access store only answers
    # which trips this caller may see.
    all_trips = _active_store().list_trips(include_archived=True) if _active_store() is not None else []
    for trip in all_trips:
        if trip["tab_id"] not in allowed:
            continue
        rows = _active_store().list_tab_rows(trip["tab_id"]) if _active_store() is not None else []
        income = sum(r["amount_krw"] for r in rows if r["row_kind"] == "income")
        expense = sum(r["amount_krw"] for r in rows if r["row_kind"] != "income")
        trips.append({"tab_id": trip["tab_id"],
                      "display_key": trip["display_key"],
                      "starts_on": trip["starts_on"],
                      "ends_on": trip["ends_on"],
                      "archived": trip["archived"],
                      "income_krw": income, "expense_krw": expense,
                      "balance_krw": income - expense,
                      "row_count": len(rows)})
    # The live refresh replaces this one block, and it is built by the same
    # renderer from the same allowlist, so a refreshed viewer board is
    # indistinguishable from a freshly loaded one and cannot widen the scope.
    body = f"<div id='live-viewer'>{ledger_design.viewer_trips_html(trips)}</div>"
    from . import live_sync

    config = live_sync.client_config(
        live_sync.viewer_token(_active_store(), allowed),
        tab_id or "", role="viewer")
    return ledger_design.render(ledger_design.shell(
        "담당 여행", tab_id=tab_id or "", heading="담당 여행", body=body),
        live_config=config)


def access_control_render_viewer_row(session, projected) -> str:
    from . import access_control
    from . import ledger_design

    access_control.assert_no_denied_fields(projected)
    pairs = "".join(f"<li>{esc(k)}: {esc(v)}</li>"
                    for k, v in projected.items() if v not in (None, ""))
    body = (f"<div class='sect'><h2>거래</h2><ul class='kv'>{pairs}</ul></div>")
    return ledger_design.render(ledger_design.shell(
        "거래", tab_id=projected.get("display_tab_id") or "",
        heading="거래", body=body))


def access_control_render_viewer_income(session, row) -> str:
    from . import ledger_design

    pairs = "".join(f"<li>{esc(k)}: {esc(v)}</li>"
                    for k, v in row.items()
                    if k in access_control_allowed() and v not in (None, ""))
    body = f"<div class='sect'><h2>수입</h2><ul class='kv'>{pairs}</ul></div>"
    return ledger_design.render(ledger_design.shell(
        "수입", tab_id=row.get("display_tab_id") or "", heading="수입", body=body))


def access_control_allowed():
    from . import access_control

    return set(access_control.VIEWER_ROW_FIELDS)


def access_control_render_owner_admin(session, store) -> str:
    """The owner's account-management entry point and the pending count.

    SPEC 16.2: the owner gets an entry point and a pending count. No mail is
    sent, and this screen does not create a reservation person or write an
    assignment into the reservation database.
    """
    from . import ledger_design

    pending = store.pending_applications()
    rows = "".join(
        f"<li>{esc(a['user_id'])} · {esc(a['requested_name'])}"
        f" · {esc(a['nickname'])} · revision {a['revision']}"
        f" · <a href='/access/admin?case={esc(a['application_id'])}'>열기</a></li>"
        for a in pending)
    people = "".join(
        f"<li>{esc(p['reservation_person_id'])} · {esc(p['display_name'])}"
        f" {esc('(' + p['disambiguator'] + ')') if p['disambiguator'] else ''}"
        f"{' · 비활성' if not p['is_active'] else ''}</li>"
        for p in store.list_reservation_persons())
    body = (
        "<div class='sect'><h2>계정 관리</h2>"
        f"<p>대기 신청 {len(pending)}건</p>"
        f"<ul>{rows}</ul>"
        "<h3>예약 담당자 후보</h3>"
        f"<ul>{people}</ul>"
        "<p class='muted'>같은 이름이 여럿이면 담당자 ID로 구분해요. "
        "이 화면은 예약 DB에 배정을 쓰지 않습니다.</p></div>")
    return ledger_design.render(ledger_design.shell(
        "계정 관리", tab_id="", heading="계정 관리", body=body))


def _operator_choice(case_id, form):
    """The target trip the owner has already chosen, read from the request.

    This is the server's value, not the model's. The event year comes from the
    row's own occurred_on rather than from anything a provider said, so a rule
    scope is anchored to stored data. With no trip chosen there is no candidate,
    which is the correct outcome rather than a guess at the current tab.
    """
    trip_id = str((form or {}).get("display_tab_id") or "").strip()
    if not trip_id or not trip_id.startswith("trip-"):
        return None
    if _active_store() is None:
        return None
    case = _active_store().conn.execute(
        "SELECT row_id FROM board_learning_cases WHERE case_id=?",
        (case_id,)).fetchone()
    if case is None:
        return None
    row = _active_store().get_row(case[0]) or {}
    occurred = str(row.get("occurred_on") or "")
    year = int(occurred[:4]) if occurred[:4].isdigit() else None
    if year is None:
        return None
    return {"trip_id": trip_id, "event_year": year}


def row_has_conflict(row: dict) -> bool:
    """Whether this row's newest ledger event is an unresolved conflict note.

    Read through the store rather than kept in a column, so the screen and the
    audit ledger cannot disagree (APP_SPEC 9: the state is told apart in the DB
    and in the row detail).
    """
    if _active_store() is None:
        return False
    try:
        return _active_store().row_conflict(row.get("row_id") or "") is not None
    except Exception:
        return False


def _note_row_conflict(row_id, expected_revision, payload, client_request_id) -> None:
    """Record a refused save as an unresolved conflict, in its own transaction.

    Called only where the store has already answered `EDIT_CONFLICT`. The row's
    values, revision and totals are not touched, and the refused request is not
    stored as a request result, so a failed save still changes nothing about the
    ledger's business state (REVIEW R01).
    """
    if _active_store() is None:
        return
    skip = {"csrf", "expected_revision", "client_request_id", "return_to"}
    attempted = {k: v for k, v in (payload or {}).items() if k not in skip}
    try:
        _active_store().record_conflict(
            row_id=row_id, expected_revision=expected_revision,
            attempted=attempted, client_request_id=client_request_id,
            actor="owner")
    except Exception:
        # A note that cannot be written must not turn a correct refusal into a
        # crash; the caller still gets EDIT_CONFLICT.
        pass


def row_needs_review(row: dict) -> bool:
    """Whether a row still waits for a person, per APP_SPEC 5 and section 9.

    Section 5 says a row that needs a reservation number, a usage period or a
    trip assignment is left as `검토필요` when it has no basis, and section 9
    lists `분류대기` as a row the existing rules could not place. Both are read
    off fields the ledger already keeps: a row with no trip, or with no recorded
    classification basis, is one a person still has to decide. Nothing here
    invents a new state or a new column.
    """
    if row.get("display_tab_id") is None:
        return True
    if str(row.get("classification_state") or "") == "unclassified":
        return True
    return not str(row.get("classification_basis") or "").strip()


def access_control_render_provider_config(session, status) -> str:
    """The owner's provider-key screen.

    PHASES 6.4 asks for the key to be entered on a secret input screen. That is
    what this is: a password-type field, posted to an owner-only endpoint, and
    never rendered back. The page shows whether a key exists and a short
    fingerprint so two keys can be told apart; the value itself is not on the
    page, not in the HTML, and not in the response.

    The form is a plain POST with no JavaScript, so it still works with script
    turned off. The secret is written with `autocomplete="off"` and is not
    echoed into the value attribute.
    """
    from . import ledger_design

    def line(name, label):
        entry = status.get(name) or {}
        # The contract asks for the connection state, whether a key is
        # registered, the selected model, and the fallback switch as separate
        # items, so they are reported separately. A key without a model is not
        # the same as no key, and saying "no key" would send the owner looking
        # in the wrong place.
        if entry.get("configured"):
            state = f"사용 준비됨 · 모델 {esc(entry.get('model') or '-')}"
        elif entry.get("has_key") and not entry.get("has_model"):
            state = ("키 등록됨 · 모델 미선택 (대화는 대기 상태)"
                     f" · 지문 {esc(entry.get('key_fingerprint') or '-')}")
        elif entry.get("has_key"):
            state = (f"키 등록됨 · 지문 {esc(entry.get('key_fingerprint') or '-')}"
                     f" · 모델 미설정 (대화는 대기 상태)")
        else:
            state = "키 없음 (대화는 대기 상태)"
        # The model is chosen from the list the server fetched, and only from
        # entries whose free support is confirmed. Nothing is hardcoded, so an
        # empty list is shown as "not fetched yet" rather than as "none exist".
        selectable = list(entry.get("selectable_models") or ())
        fetched_at = entry.get("models_fetched_at")
        if not entry.get("models"):
            options = ("<option value=''>조회 전 · 목록을 먼저 읽어 주세요"
                       "</option>")
        elif not selectable:
            options = ("<option value=''>무료 지원이 확인된 모델이 없어요"
                       "</option>")
        else:
            current = str(entry.get("model") or "")
            options = "".join(
                f"<option value='{esc(model)}'"
                f"{' selected' if model == current else ''}>{esc(model)}</option>"
                for model in selectable)
        fetched_note = (f" · 조회 시점 {esc(fetched_at)}" if fetched_at
                        else " · 아직 조회한 적 없음")
        return (
            f"<h3>{esc(label)}</h3><p class='muted'>{state}</p>"
            f"<form method='post' action='/access/providers' class='f'>"
            f"<input type='hidden' name='action' value='set'>"
            f"<input type='hidden' name='provider' value='{esc(name)}'>"
            f"<input type='hidden' name='csrf' value='{esc(CSRF_TOKEN)}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<div class='f'><label for='k-{esc(name)}'>키</label>"
            f"<input id='k-{esc(name)}' name='secret' type='password'"
            f" autocomplete='off' autocapitalize='off' spellcheck='false'"
            f" placeholder='붙여넣은 값은 저장 후 화면에 남지 않아요'></div>"
            f"<div class='f'><label for='m-{esc(name)}'>모델</label>"
            f"<select id='m-{esc(name)}' name='model'>{options}</select></div>"
            f"<button class='btn primary' type='submit'>{ui_icons.icon('save')}저장</button>"
            f"<button class='btn' type='submit' formaction='/access/providers'"
            f" name='action' value='refresh-models'"
            f" formnovalidate>{ui_icons.icon('refresh-cw')}모델 목록 다시 읽기</button>"
            f"<button class='btn' type='submit' formaction='/access/providers'"
            f" name='action' value='connection-test'"
            f" formnovalidate>{ui_icons.icon('link')}연결 테스트</button>"
            f"</form>"
            f"<p class='muted'>사용 가능한 모델은 서버가 조회한 목록{esc(fetched_note)}"
            " 중 무료 지원이 확인된 항목만 고를 수 있어요.</p>"
            f"<form method='post' action='/access/providers' class='f'>"
            f"<input type='hidden' name='action' value='clear'>"
            f"<input type='hidden' name='provider' value='{esc(name)}'>"
            f"<input type='hidden' name='csrf' value='{esc(CSRF_TOKEN)}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<button class='btn' type='submit'>{ui_icons.icon('x-circle')}키 지우기</button></form>")

    tier = status.get("tier") or {}
    tier_state = str(tier.get("state") or "unknown")
    tier_label = {"verified": "확인됨",
                  "setting-required": "설정 필요",
                  "unknown": "미확인"}.get(tier_state, tier_state)
    tier_note = {
        "verified": f"무료 등급을 {esc(tier.get('verified_at') or '-')}에 확인했어요.",
        "setting-required": "프로젝트 등급을 AI Studio에서 확인하고 기록해 주세요.",
        "unknown": "아직 프로젝트 등급을 확인하지 않았어요.",
    }[tier_state]
    fallback_on = bool(status.get("fallback_enabled"))
    toggle_state = "켜짐" if fallback_on else "꺼짐"
    toggle_action = "0" if fallback_on else "1"
    toggle_label = "fallback 끄기" if fallback_on else "fallback 켜기"
    body = (
        "<div class='sect'><h2>제공자 연결</h2>"
        "<p>대화는 owner만 키를 등록할 수 있어요. 키는 서버 설정에만 보관되고 "
        "화면·대화 기록·로그에 나타나지 않아요.</p>"
        f"{line('muse', 'Muse (내 PC)')}"
        f"{line('gemini', 'Gemini (서버 fallback)')}"
        "<form method='post' action='/access/providers' class='f'>"
        "<input type='hidden' name='action' value='fallback'>"
        "<input type='hidden' name='enabled' value='"
        f"{toggle_action}'>"
        f"<input type='hidden' name='csrf' value='{esc(CSRF_TOKEN)}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        "<h3>Gemini fallback</h3>"
        f"<p class='muted'>현재 {toggle_state}. 꺼 두면 Muse 연결이 실패해도 "
        "Gemini를 부르지 않고 대기를 유지해요.</p>"
        f"<button class='btn' type='submit'>{esc(toggle_label)}</button>"
        "</form>"
        "<h3>프로젝트 등급</h3>"
        f"<p class='muted'>현재 <strong>{esc(tier_label)}</strong> · "
        f"{esc(tier_note)} 앱은 무료 과금을 보장하지 않아요.</p>"
        "<form method='post' action='/access/providers' class='f'>"
        "<input type='hidden' name='action' value='record-tier'>"
        f"<input type='hidden' name='csrf' value='{esc(CSRF_TOKEN)}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        "<div class='f'><label for='tier-v'>등급</label>"
        "<select id='tier-v' name='tier'>"
        "<option value='free'>free</option>"
        "<option value='paid'>paid</option>"
        "<option value='unknown'>확인 못 함</option>"
        "</select></div>"
        "<div class='f'><label for='tier-at'>확인 시점</label>"
        "<input id='tier-at' name='verified_at' type='text' "
        "placeholder='2026-09-27T10:00'></div>"
        f"<button class='btn' type='submit'>{ui_icons.icon('pencil')}등급 기록</button>"
        "</form>"
        "<p class='muted'>이 화면은 실제 모델을 호출하지 않아요. 연결 테스트는 "
        "합성 문장 하나만 보내고 성공 여부와 실제 모델 ID만 알려 줘요. 키를 지우면 "
        "다음 대화는 대기 상태가 되고, 한도가 소진된 경우와 같은 방식으로 대기를 "
        "유지해요.</p></div>")
    return ledger_design.render(ledger_design.shell(
        "제공자 연결", tab_id="", heading="제공자 연결", body=body))


def bind_dialog_adapters(muse=None, gemini=None) -> None:
    """Server-side provider injection for dialog turns.

    A request body can never choose a provider and never carries a key. When
    nothing is bound, a turn only waits. The adapters report `is_real_call`
    themselves; a synthetic adapter must stay marked as not a real call.
    """
    global _MUSE, _GEMINI
    _MUSE, _GEMINI = muse, gemini


def bind_provider_config(service=None, *, autowire=False, transport=None) -> None:
    """Bind the owner-only provider configuration service.

    Unbound by default. With nothing bound the configuration surface refuses
    every request, so a deploy that forgets to configure it cannot fall back to
    a permissive default.

    `autowire` decides whether a configuration change rebuilds the adapters.
    It is off by default so that a test or a caller who injected adapters
    explicitly keeps them; a deploy that wants the configured key to take effect
    without a restart turns it on and passes the transport it wants. Turning it
    on with no transport produces adapters that report `not_configured` and
    park the turn, which is the safe direction.
    """
    global _PROVIDER_CONFIG, _PROVIDER_AUTOWIRE, _PROVIDER_TRANSPORT
    _PROVIDER_CONFIG = service
    _PROVIDER_AUTOWIRE = bool(autowire)
    _PROVIDER_TRANSPORT = transport
    if _PROVIDER_CONFIG is not None and _PROVIDER_AUTOWIRE:
        _rebuild_provider_adapters()


def _rebuild_provider_adapters() -> None:
    """Rebuild the adapter pair from server-side configuration.

    Reads the store, never a request. With autowire off this does nothing, so an
    injected adapter is never replaced behind a test's back.
    """
    global _MUSE, _GEMINI
    if _PROVIDER_CONFIG is None or not _PROVIDER_AUTOWIRE:
        return
    from .provider_transport import build_adapters

    _MUSE, _GEMINI = build_adapters(_PROVIDER_CONFIG.config,
                                    transport=_PROVIDER_TRANSPORT)


def _transport_for(provider):
    """The transport the deployment bound for one provider.

    It may be a per-provider dict or a single shared transport. When nothing is
    bound this returns None, and the model-list fetch reports
    `not_configured` rather than inventing a transport that would silently
    succeed.
    """
    transport = _PROVIDER_TRANSPORT
    if isinstance(transport, dict):
        return transport.get(provider)
    return transport


def provider_status():
    """A description of the provider wiring with no secret in it.

    Readable without a role because it holds only presence, a model id, and a
    fingerprint. The owner gate is on the configuration surface itself, not on
    this summary.
    """
    if _PROVIDER_CONFIG is None:
        return {"bound": False, "muse": {"configured": False},
                "gemini": {"configured": False}}
    from .provider_transport import adapter_report

    report = adapter_report(_MUSE, _GEMINI)
    report["bound"] = True
    report["autowire"] = bool(_PROVIDER_AUTOWIRE)
    report.update(_PROVIDER_CONFIG.public_status())
    return report


def bind_importer(importer) -> None:
    global _IMPORTER
    _IMPORTER = importer


def live_trips(include_archived: bool = False):
    if _active_store() is None:
        return [dict(t) for t in TRIPS]
    return _active_store().list_trips(include_archived=include_archived)


def valid_tab_ids() -> set:
    return {t["tab_id"] for t in live_trips(include_archived=True)}


def _all_tab_ids() -> list:
    return [t["tab_id"] for t in live_trips(include_archived=True)]


def default_board_tab() -> str:
    """Which tab `/board` opens on when the request names none.

    It used to default to `trip-demo-a`, one of this module's example trips. On a
    store that has never been seeded that trip does not exist, so `/board` opened
    on a trip the reader has never heard of, showing the head "여행을 선택해 주세요"
    and a rail with no selected tab. It is also a hard-coded example id in a code
    path a real deployment runs.

    So the default is a question about the data rather than a constant: the first
    real trip, and the 분류대기 bucket when there is no trip at all. An empty store
    opens on 분류대기, which is a screen that exists and says so, instead of on a
    trip that does not.
    """
    trips = live_trips()
    if trips:
        return trips[0]["tab_id"]
    return "unclassified"


def _with_display_amount(rows):
    return board_read_projection.with_display_amount(rows, store=_active_store())


def _shown_date(row) -> str:
    return board_read_projection.shown_date(row)


def _persisted_rows(kind: str):
    """Every row of one kind that the bound store actually holds.

    This is the only source of rows when a store is bound, and that is the point of
    it. The earlier version walked the module-level `EXPENSES`/`INCOMES` and, for
    each one, fell back to the static dict when the store had no such row. A store
    opened with `seed_demo=False` therefore showed the whole example board while
    its own `board_rows` table was empty, which is what an operator saw: the page
    said 합성 자료 and listed trips that had never been imported. The rows below
    come from `list_tab_rows`, which also returns the allocation projections and
    the split remainders, so a store that has only allocations still shows them.
    """
    return board_read_projection.persisted_rows(
        kind,
        remember_fn=read_scope.remember,
        loader_fn=lambda: _load_persisted_rows(kind),
    )


def _load_persisted_rows(kind: str):
    store = _active_store()
    return board_read_projection.load_persisted_rows(
        kind,
        store=store,
        tab_ids=_all_tab_ids(),
        fetch_tab_rows_fn=lambda tab: read_scope.remember(
            ('persisted_tab_rows', id(store), tab), lambda: store.list_tab_rows(tab)
        ),
    )


def _expense_rows():
    return board_read_projection.expense_rows(
        store=_active_store(),
        fallback_expenses=EXPENSES,
        persisted_rows_fn=_persisted_rows,
    )


def _income_rows():
    return board_read_projection.income_rows(
        store=_active_store(),
        fallback_incomes=INCOMES,
        persisted_rows_fn=_persisted_rows,
    )


def _trip_totals(tab_id: str):
    return board_read_projection.trip_totals(
        tab_id,
        store=_active_store(),
        fallback_totals_fn=lambda tid: {
            "income": trip_income_total(tid),
            "expense": trip_expense_total(tid),
            "profit": trip_profit(tid),
        },
    )


def _unclassified_rows():
    return board_read_projection.unclassified_rows(expense_rows=_expense_rows())


def _income_total(rows) -> int:
    return board_read_projection.income_total(
        rows,
        store=_active_store(),
        shown_amount_fn=_shown_amount,
    )

SYNTHETIC_MARK = "합성 자료"


def example_row_ids() -> set:
    """The ids this module's example data defines."""
    return {r["row_id"] for r in EXPENSES} | {r["row_id"] for r in INCOMES}


def _store_holds_only_the_examples() -> bool:
    """Is every row in the bound store one of this module's example rows?

    A store opened with `seed_demo=True` writes those rows into the database, so
    from here there is no way to tell a seeded store from an imported one by
    looking at the ids. That is the whole question the badge has to answer, and
    it can be answered: a store holding nothing but the example ids, on the
    example trips, is the example board whether or not it was written by the
    seeder. The moment a row of its own is there, it is not.
    """
    store = _active_store()
    if store is None:
        return False
    examples = example_row_ids()
    total = store.visible_row_count()
    if not total:
        return False
    example_tabs = {t["tab_id"] for t in TRIPS}
    # Count only example rows on existing example tabs. Splits, remainders,
    # imported rows and other tabs make the total larger than this count.
    placeholders = ','.join('?' for _ in examples)
    tab_placeholders = ','.join('?' for _ in example_tabs)
    matching = store.conn.execute(
        'SELECT COUNT(*) FROM board_rows b'
        ' WHERE b.row_kind IN (\'expense\',\'income\')'
        f' AND b.row_id IN ({placeholders})'
        f' AND (b.display_tab_id IS NULL OR b.display_tab_id IN ({tab_placeholders}))'
        ' AND (b.display_tab_id IS NULL OR EXISTS ('
        'SELECT 1 FROM trip_tabs t WHERE t.tab_id=b.display_tab_id AND t.deleted=0))'
        ' AND NOT EXISTS (SELECT 1 FROM income_allocations a'
        ' WHERE a.source_row_id=b.row_id AND a.active=1)',
        (*examples, *example_tabs),
    ).fetchone()[0]
    return total == matching


def data_status_mark() -> str:
    """여행·가져온 카드 자료·장부 기록을 구분해 실제 저장 상태를 표시한다."""
    if _active_store() is None or _store_holds_only_the_examples():
        return SYNTHETIC_MARK
    store = _active_store()
    parts = []
    trip_count = len(live_trips())
    if trip_count:
        parts.append(f"여행 {trip_count}개")
    with store._lock:
        if store.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone():
            cards = store.conn.execute("SELECT COUNT(*) FROM transactions WHERE classification_state!='preserved'").fetchone()[0]
            if cards:
                parts.append(f"카드 자료 {cards:,}건")
    count = store.visible_row_count()
    parts.append(f"장부 기록 {count:,}건")
    return " · ".join(parts)


def nav_data_note() -> str:
    """The sidebar's one line about where the rows came from.

    It said 합성 자료만 적용돼요, which is false on any store serving real rows and
    for the same reason as the badge. It reports the same number instead, or says
    the screen is showing the in-memory example board when that is what it is.
    """
    if _active_store() is None:
        return f"지금은 {SYNTHETIC_MARK}만 보여요."
    return "화면의 행은 이 서버에 저장된 값이에요."

TRIPS = (
    {"tab_id": "trip-demo-a", "display_key": "0408_예시여행A", "starts_on": "2026-04-08", "ends_on": "2026-04-14", "destination": "예시여행A"},
    {"tab_id": "trip-demo-b", "display_key": "0420_예시여행B", "starts_on": "2026-04-20", "ends_on": "2026-04-23", "destination": "예시여행B"},
)

EXPENSES = (
    {
        "row_id": "expense-demo-c1", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-09", "item": "숙박비", "description": "예시 숙소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 100000,
        "source_kind": "카드", "source_event_id": "SRC-C1",
        "source_merchant": "예시 숙소",
        "event_kind": "purchase",
        "card_kind": "K1",
        "classification_state": "auto_classified",
        "classification_basis": "정규화 가맹점·카드 종류·거래 방향 후보 A",
    },
    {
        "row_id": "expense-demo-c2", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-10", "item": "숙박비", "description": "예시 숙소 취소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": -20000,
        "source_kind": "카드", "source_event_id": "SRC-C2",
        "source_merchant": "예시 숙소 추소",
        "event_kind": "cancellation",
        "card_kind": "K1",
        "classification_state": "auto_classified",
        "classification_basis": "원천 확인 취소 사건, 부호 보존",
    },
    {
        "row_id": "expense-demo-c3", "display_tab_id": None,
        "occurred_on": "2026-04-11", "item": "교통비", "description": "예시 이동",
        "service_period": "", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 30000,
        "source_kind": "카드", "source_event_id": "SRC-C3",
        "source_merchant": "예시 이동",
        "event_kind": "purchase",
        "card_kind": "K2",
        "classification_state": "unclassified",
        "classification_basis": "목적지 없음, 분류대기",
    },
    {
        "row_id": "expense-demo-c4", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-09", "item": "숙박비", "description": "예시 숙소",
        "service_period": "2026-04-09~2026-04-10", "reservation_no": "",
        "evidence_type": "카드", "amount_krw": 100000,
        "source_kind": "카드", "source_event_id": "SRC-C4",
        "source_merchant": "예시 숙소",
        "event_kind": "purchase",
        "card_kind": "K1",
        "classification_state": "auto_classified",
        "classification_basis": "C1과 날짜·가맹점 동일, 원천 거래 ID 상이, 별도 사건",
    },
)

INCOMES = (
    {
        "row_id": "income-demo-i1", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-01", "customer_id": "U1",
        "customer_name": "김예시", "nickname": "예시별명",
        "income_kind": "deposit", "event_type": "receipt", "amount_krw": 500000,
        "source_kind": "직접 입력", "source_event_id": "INC-I1",
    },
    {
        "row_id": "income-demo-i2", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-05", "customer_id": "U1",
        "customer_name": "김예시", "nickname": "예시별명",
        "income_kind": "balance", "event_type": "receipt", "amount_krw": 300000,
        "source_kind": "직접 입력", "source_event_id": "INC-I2",
    },
    {
        "row_id": "income-demo-i3", "display_tab_id": "trip-demo-a",
        "occurred_on": "2026-04-06", "customer_id": "U2",
        "customer_name": "김예시", "nickname": "다른별명",
        "income_kind": "deposit", "event_type": "receipt", "amount_krw": 200000,
        "source_kind": "직접 입력", "source_event_id": "INC-I3",
    },
)

INCOME_KIND_LABEL = {"deposit": "예약금", "balance": "잔금", "additional": "추가금"}


def _flag(value) -> bool:
    """Accept only explicit switches for the rule scope."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def local_path(value) -> str:
    """Accept only a local path of this app as a return target.

    A scheme, a protocol relative address, a host, a backslash or a control
    character makes the value unusable, so a crafted return_to cannot send the
    owner to another origin or split a header.
    """
    if not isinstance(value, str) or not value:
        return ""
    if any(ch in value for ch in ("\r", "\n", "\t", "\\", "\x00")):
        return ""
    if not value.startswith("/") or value.startswith("//"):
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        return ""
    allowed = ("/board", "/row", "/rules", "/trips", "/export", "/import", "/income")
    if not any(parts.path == prefix or parts.path.startswith(prefix + "/")
               or parts.path.startswith(prefix + "?") for prefix in allowed):
        return ""
    return value


esc = board_render_helpers.esc


def trip_income_total(tab_id: str) -> int:
    return board_read_projection.trip_income_total(tab_id, rows=INCOMES)


def trip_expense_total(tab_id: str) -> int:
    return board_read_projection.trip_expense_total(tab_id, rows=EXPENSES)


def trip_profit(tab_id: str) -> int:
    return board_read_projection.trip_profit(trip_income_total(tab_id), trip_expense_total(tab_id))


def customer_total(customer_id: str, tab_id: str) -> int:
    return board_read_projection.customer_total(customer_id, tab_id, rows=INCOMES)


def unclassified_expenses():
    return board_read_projection.unclassified_rows(expense_rows=EXPENSES)


def unclassified_total() -> int:
    return sum(r["amount_krw"] for r in unclassified_expenses())


def find_row(row_id: str):
    if _active_store() is not None:
        allocation = _active_store().get_allocation_display(row_id)
        if allocation is not None:
            return ("income", allocation)
    for r in _expense_rows():
        if r["row_id"] == row_id:
            return ("expense", r)
    for r in _income_rows():
        if r["row_id"] == row_id:
            return ("income", r)
    if _active_store() is not None:
        hidden = _active_store().get_row(row_id)
        if hidden is not None:
            hidden["display_amount_krw"] = _active_store().display_amount(hidden)
            hidden["display_occurred_on"] = _active_store().display_occurred_on(hidden)
            return (hidden["row_kind"], hidden)
    return (None, None)


def split_page(source_id: str) -> str:
    return board_render_helpers.split_page(
        source_id,
        store=_active_store(),
        csrf_token=CSRF_TOKEN,
        trips_fn=live_trips,
    )


def history_html(row_id: str) -> str:
    return board_render_helpers.history_html(
        row_id,
        store=_active_store(),
        csrf_token=CSRF_TOKEN,
    )


def allocation_revert_status(allocation):
    return board_render_helpers.allocation_revert_status(
        allocation,
        store=_active_store(),
    )


def allocation_history_html(allocation) -> str:
    return board_render_helpers.allocation_history_html(
        allocation,
        store=_active_store(),
        csrf_token=CSRF_TOKEN,
    )


def allocation_detail_body(allocation, edit: bool) -> str:
    return board_render_helpers.allocation_detail_body(
        allocation,
        edit=edit,
        store=_active_store(),
        csrf_token=CSRF_TOKEN,
        trips_fn=lambda: live_trips(include_archived=True),
        shown_amount_fn=_shown_amount,
    )


STYLE = (
    "<style>body{font-family:'Malgun Gothic',sans-serif;margin:0;background:#f4f5f7;color:#222}"
    ".top{background:#fff;border-bottom:1px solid #ddd;padding:10px 16px;position:sticky;top:0;z-index:5}"
    ".top h1{font-size:18px;margin:0}.synth{display:inline-block;background:#fff4d6;border:1px solid #e0b800;"
    "font-size:12px;padding:1px 8px;border-radius:10px;margin-left:8px}"
    ".wrap{display:flex;min-height:calc(100vh - 57px)}"
    ".tabs{width:240px;flex:none;background:#fff;border-right:1px solid #ddd;overflow-y:auto;padding:8px}"
    ".tab{display:block;border:1px solid transparent;border-radius:8px;padding:10px;margin-bottom:6px;"
    "color:#222;text-decoration:none}.tab.sel{border-color:#3182f6;background:#eef4ff}"
    ".tab .amt{font-size:20px;font-weight:bold}.tab small{color:#666}"
    ".body{flex:1;min-width:0;padding:16px}.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:12px}"
    ".big{font-size:28px;font-weight:bold}.muted{color:#666;font-size:13px}"
    "table{border-collapse:collapse;width:100%}td,th{border:1px solid #e2e2e2;padding:8px;font-size:14px;text-align:left}"
    "th{background:#f7f8fa}.num{text-align:right;font-variant-numeric:tabular-nums}"
    ".scrollx{overflow-x:auto}.detail{width:420px;flex:none;background:#fff;border-left:1px solid #ddd;"
    "padding:16px;overflow-y:auto}input,select{font-size:14px;padding:6px;width:100%;box-sizing:border-box}"
    ".rowbtn{font-size:13px;padding:4px 10px}.btnprep{background:#eee;border:1px solid #ccc;border-radius:8px;"
    "padding:8px 14px;font-size:14px;color:#666}.search{font-size:14px;padding:8px;width:100%;box-sizing:border-box}"
    "@media (max-width:760px){.wrap{flex-direction:column}.tabs{width:auto;border-right:none;border-bottom:1px solid #ddd;"
    "max-height:220px}.detail{width:auto;border-left:none;border-top:1px solid #ddd}}"
    "</style>"
)


def layout(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title>{STYLE}</head><body>{body}</body></html>"
    )


def tabs_html(selected: str, query: str = "") -> str:
    expenses = _expense_rows()
    items = []
    for t in board_export_helpers.filter_trips(live_trips(), query=query):
        cls = "tab sel" if t["tab_id"] == selected else "tab"
        totals = _trip_totals(t["tab_id"])
        items.append(
            f"<a class='{cls}' href='/board?tab={esc(t['tab_id'])}'>"
            f"<div>{esc(t['display_key'])}</div>"
            f"<div class='amt'>{totals['expense']:,}원</div>"
            f"<small>지출 {totals['expense']:,}원</small></a>"
        )
    if _active_store() is not None:
        archived = [t for t in live_trips(include_archived=True) if t["archived"]]
        if archived and not query:
            links = "".join(
                f"<a class='tab' href='/board?tab={esc(t['tab_id'])}'>"
                f"<div>{esc(t['display_key'])} (보관)</div></a>"
                for t in archived
            )
            items.append(f"<div class='muted'>보관된 여행</div>{links}")
    unc = [r for r in expenses if r["display_tab_id"] is None]
    unc_total = sum(_shown_amount(r) for r in unc)
    if board_export_helpers.is_unclassified_matched(query):
        cls = "tab sel" if selected == "unclassified" else "tab"
        items.append(
            f"<a class='{cls}' href='/board?tab=unclassified'>"
            f"<div>분류대기</div><div class='amt'>{len(unc)}건</div>"
            f"<small>미배정 {unc_total:,}원</small></a>"
        )
    return "".join(items) if items else "<p class='muted'>여행 탭을 추가해 주세요</p>"


def board_page(tab_id: str, query: str = "") -> str:
    trip = next((t for t in live_trips(include_archived=True) if t["tab_id"] == tab_id), None)
    if tab_id == "unclassified":
        rows = _unclassified_rows()
        unc_total = sum(_shown_amount(r) for r in rows)
        inc_rows = [r for r in _income_rows() if r["display_tab_id"] is None]
        head = "<h2>분류대기</h2>"
        tables = income_table(inc_rows) + expense_table(rows)
        summary = f"<div class='card'><span class='muted'>미배정</span><div class='big'>{unc_total:,}원</div></div>"
    elif trip is None:
        head = "<h2>여행을 선택해 주세요</h2>"
        tables = ""
        summary = ""
    else:
        incomes = [r for r in _income_rows() if r["display_tab_id"] == tab_id]
        expenses = [r for r in _expense_rows() if r["display_tab_id"] == tab_id]
        totals = _trip_totals(tab_id)
        linked = _active_store().linked_bank_row_ids() if _active_store() is not None else set()
        billed = [r for r in incomes if r["row_id"] not in linked]
        customers = sorted({r["customer_id"] for r in billed})
        cust_lines = "".join(
            f"<div>{esc(next(r['customer_name'] for r in billed if r['customer_id'] == c))} "
            f"({esc(c)}): <b>{sum(_shown_amount(r) for r in billed if r['customer_id'] == c):,}원</b></div>"
            for c in customers
        )
        head = f"<h2>{esc(trip['display_key'])} <span class='muted'>{esc(trip['starts_on'])}~{esc(trip['ends_on'])}</span></h2>"
        meta_line = ""
        if _active_store() is not None and trip.get("prepared_on"):
            meta_line = (
                f"<p class='muted'>작성일 {esc(trip['prepared_on'])} · 담당자 "
                f"{esc(trip.get('prepared_by_name', ''))}"
                + (" · 보관됨" if trip.get("archived") else "")
                + " · <a href='/trips'>여행 관리</a></p>"
            )
        head += meta_line
        summary = (
            "<div class='card'><span class='muted'>수입 합계</span>"
            f"<div class='big'>{totals['income']:,}원</div>"
            "<span class='muted'>지출 합계</span>"
            f"<div class='big'>{totals['expense']:,}원</div>"
            "<span class='muted'>회사수익인식</span>"
            f"<div class='big'>{totals['profit']:,}원</div>"
            f"<p class='muted'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</p></div>"
            f"<div class='card'><h3>고객별 합계</h3>{cust_lines}</div>"
        )
        tables = income_table(incomes) + expense_table(expenses)
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{data_status_mark()}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    side = (
        "<div class='tabs'>"
        f"<form method='get' action='/board'><input class='search' name='q' placeholder='여행 검색' value='{esc(query)}'></form>"
        f"{tabs_html(tab_id, query)}</div>"
    )
    return layout("웹 장부", f"{top}<div class='wrap'>{side}<div class='body'>{head}{summary}{tables}</div></div>")


def income_new_page() -> str:
    options = "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>" for t in live_trips()
    )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{data_status_mark()}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<div class='body'><h2>수입 직접 입력</h2>"
        f"<form method='post' action='/api/income'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<p><label>여행</label><select name='display_tab_id'>{options}</select></p>"
        "<p><label>거래일자</label><input name='occurred_on' placeholder='2026-04-01'></p>"
        "<p><label>금액(원)</label><input name='amount_krw'></p>"
        "<p><label>입금 종류</label><select name='income_kind'>"
        "<option value='deposit'>예약금</option><option value='balance'>잔금</option>"
        "<option value='additional'>추가금</option></select></p>"
        "<p><label>이름</label><input name='customer_name'></p>"
        "<p><label>닉네임</label><input name='nickname'></p>"
        "<p><label>메모</label><input name='operator_note'></p>"
        "<button type='submit'>저장</button></form></div>"
    )
    return layout("수입 직접 입력", f"{top}<div class='wrap'>{body}</div>")


MANUAL_EXPENSE_STYLE = """<style>
.mx-card{max-width:680px;margin:24px auto 40px;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:26px 28px 22px;box-shadow:0 1px 2px rgba(16,24,40,.05)}
.mx-card h2{margin:0 0 20px;font-size:20px;font-weight:700;letter-spacing:-.01em;color:var(--ink)}
.mx-sub{font-size:14px;font-weight:500;color:var(--mut);margin-left:6px}
.mx-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px 18px}
.mx-field{display:flex;flex-direction:column;gap:6px;min-width:0}
.mx-field.wide{grid-column:1 / -1}
.mx-field label{font-size:13px;font-weight:600;color:var(--mut)}
.mx-field input,.mx-field select{height:42px;box-sizing:border-box;width:100%;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:var(--paper);font:inherit;font-size:14.5px;color:var(--ink)}
.mx-field input:focus,.mx-field select:focus{outline:2px solid #3B82F6;outline-offset:-1px}
.mx-amount input{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
.mx-actions{display:flex;justify-content:flex-end;margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}
.mx-submit{height:42px;padding:0 24px;border:0;border-radius:9px;background:#1D4ED8;color:#fff;font:inherit;font-size:14.5px;font-weight:600;cursor:pointer}
.mx-submit:hover{background:#1E40AF}
@media (max-width:640px){.mx-grid{grid-template-columns:1fr}.mx-card{margin:12px;padding:20px}}
</style>"""


def expense_new_page() -> str:
    options = "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>" for t in live_trips()
    )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{data_status_mark()}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<section class='mx-card'><h2>수기 지출 추가 <span class='mx-sub'>현금·계좌이체</span></h2>"
        f"<form method='post' action='/api/expenses/manual' class='mx-form'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        "<div class='mx-grid'>"
        f"<div class='mx-field wide'><label for='mx-tab'>여행</label><select id='mx-tab' name='display_tab_id'>{options}</select></div>"
        "<div class='mx-field'><label for='mx-date'>거래일자</label><input id='mx-date' type='date' name='occurred_on' required></div>"
        "<div class='mx-field'><label for='mx-pay'>지급 수단</label><select id='mx-pay' name='pay_method'>"
        "<option value='현금'>현금</option><option value='계좌이체'>계좌이체</option></select></div>"
        "<div class='mx-field'><label for='mx-item'>항목</label><input id='mx-item' name='item'></div>"
        "<div class='mx-field'><label for='mx-desc'>내용</label><input id='mx-desc' name='description'></div>"
        "<div class='mx-field wide mx-amount'><label for='mx-amount'>금액 (원, 환불은 음수)</label>"
        "<input id='mx-amount' name='amount_krw' inputmode='numeric' placeholder='0'></div>"
        "<div class='mx-field wide'><label for='mx-memo'>메모</label><input id='mx-memo' name='operator_note'></div>"
        "</div>"
        "<div class='mx-actions'><button class='mx-submit' type='submit'>저장</button></div>"
        "</form></section>"
    )
    return layout("수기 지출 추가", f"{top}<div class='wrap'>{MANUAL_EXPENSE_STYLE}{body}</div>")


RULE_MODE_LABEL = SYNTHETIC_MODE_NOTE


def _rule_scope_text(rule: dict) -> str:
    """The rule in one sentence, so the owner can see how wide it is before applying."""
    conditions = rule.get("conditions") or {}
    names = {"merchant_normalized": "가맹점", "card_kind": "카드 구분", "transaction_direction": "거래 방향"}
    parts = []
    for field, entry in conditions.items():
        value = entry.get("value")
        value = ", ".join(map(str, value)) if isinstance(value, list) else value
        parts.append(f"{names.get(field, field)} = {value}")
    optional = rule.get("optional_conditions") or {}
    if optional.get("amount_range"):
        parts.append(f"금액 범위 {optional['amount_range']}")
    if optional.get("date_or_service_period"):
        parts.append(f"기간 {optional['date_or_service_period']}")
    effect_names = {"item": "항목", "display_tab_id": "여행 탭", "description_template": "내용"}
    changes = ", ".join(f"{effect_names.get(k, k)} → {v}" for k, v in (rule.get("effects") or {}).items())
    text = " · ".join(parts) + (f" ⇒ {changes}" if changes else "")
    scope = rule.get("scope") or {}
    if scope.get("trip_id"):
        text += f" (여행 {scope['trip_id']}, {scope.get('event_year')}년)"
    if list(conditions) == ["merchant_normalized"]:
        text += (" — 모든 여행·모든 카드의 같은 가맹점 거래에 해당합니다."
                 " 같은 가맹점의 기존 카드 분류 규칙이 있으면 미래 입력부터 이 규칙이 그 항목을 대체합니다")
    return text


def _rule_hidden(case_id, request_id, extra=""):
    return (f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='case' value='{esc(case_id)}'>"
            f"<input type='hidden' name='client_request_id' value='{esc(request_id)}'>"
            f"{extra}")


def rule_dialog_page(case_id: str, query: dict) -> str:
    """Minimal rule dialog screen on top of the existing functional HTML.

    The screen only orchestrates existing endpoints. It never writes a row
    itself, and a provider answer is shown as a draft the owner must confirm.
    """
    from . import ledger_design

    if _active_store() is None:
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body="<div class='sect'><p>저장소가 연결되지 않았어요.</p></div>"))
    state = _active_store().dialog_page_state(case_id)
    row = _active_store().get_row(state["row_id"]) if state.get("row_id") else None
    if row is None:
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body="<div class='sect'><p>대화에 연결된 행이 없어요.</p></div>"))
    row_id = esc(row["row_id"])
    dialog = state["dialog_state"]
    conv = state["conversation"] or {}
    pending = state["pending_draft"]
    rule = state["rule"]
    provider = state["provider"] or {}
    real_call = bool(provider.get("is_real_call"))
    mode_label = "AI 연결됨" if real_call else RULE_MODE_LABEL
    notice = query.get("msg", [""])[0]
    parts = []

    parts.append(
        f"<h3>규칙 대화</h3>"
        f"<p class='muted'>{esc(row.get('item', ''))} · {esc(row.get('description', ''))}</p>"
        f"<p><span class='synth'>{esc(mode_label)}</span> "
        f"<span class='muted'>대화 상태: {esc(dialog_state_label(dialog))}"
        + (f" · 공급자: {esc(conv.get('active_provider') or '-')}"
           f" · model: {esc(conv.get('active_model_id') or '-')}"
           f" · 턴 {conv.get('turn_count', 0)}회" if conv else "")
        + "</span></p>")
    if notice:
        parts.append(f"<p class='muted'>{esc(notice)}</p>")
    if "PREVIEW_STALE" in notice:
        parts.append(
            "<p class='muted'>선택한 행이 바뀌었어요. 아래에서 새 미리보기를 다시 받아 주세요."
            " 일부 행만 적용되지는 않습니다.</p>")
    if dialog == "closed":
        parts.append(
            "<form method='post' action='/api/classification/dialog/resume'>"
            + _rule_hidden(case_id, f"ui-resume-{case_id}")
            + "<button class='btn' type='submit'>대화 재개</button></form>")
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body=(f"<div class='sect'>{''.join(parts)}"
                  "<p><a href='/board'>목록으로</a></p></div>")))

    if state["should_not_create_rule"]:
        parts.append(
            "<p class='muted'>이번 거래만 적용하기로 하셨습니다. 규칙 초안·영향 미리보기·"
            "적용은 진행하지 않고, 이미 저장한 행 수정은 그대로 유지합니다.</p>")

    # 근거 자유문: 그대로 저장한다
    parts.append(
        "<form method='post' action='/api/classification/dialog/note'>"
        + _rule_hidden(case_id, f"ui-note-{case_id}")
        + "<p><label>근거 설명 (자유문)</label>"
        + f"<input name='note' value='{esc(state['note'])}' size='60'></p>"
        + "<button class='btn' type='submit'>근거 저장</button></form>")

    # 질문
    for question in state["questions"]:
        answered = question["answer"] is not None
        view = question_view(question)
        if question["question_key"] == "trip_move_reason" and not answered and not question["options"]:
            parts.append(
                "<section class='qgroup'><p>" + esc(view["prompt"]) + "</p>"
                "<form method='post' action='/api/classification/conversation/reasons'>"
                + _rule_hidden(case_id, f"ui-reasons-{case_id}")
                + "<button class='btn' type='submit'>AI \uc608\uc0c1 \uc774\uc720 2\uac1c \uc81c\uc548</button></form>"
                "<form method='post' action='/api/classification/dialog/answer'>"
                + _rule_hidden(case_id, f"ui-direct-reason-{case_id}",
                               f"<input type='hidden' name='question_id' value='{esc(question['question_id'])}'>"
                               f"<input type='hidden' name='expected_row_revision' value='{row.get('revision', 1)}'>"
                               "<input type='hidden' name='answer' value='__direct__'>")
                + "<label>\uc9c1\uc811 \uc785\ub825<textarea name='direct_answer' required maxlength='500'></textarea></label>"
                + "<button class='btn' type='submit'>\uc774\uc720 \uc800\uc7a5</button></form></section>")
            continue
        options = "".join(
            f"<label class='opt'>"
            f"<input type='radio' name='answer' value='{esc(option['value'])}'"
            f"{' checked' if question['answer'] == option['value'] else ''}>"
            f"<span>{esc(option['label'])}</span></label>"
            for option in view["options"])
        if answered:
            parts.append(f"<p class='muted'>답변 완료: {esc(view['answer_label'])}</p>")
        else:
            parts.append(
                f"<form method='post' action='/api/classification/dialog/answer'>"
                + _rule_hidden(case_id, f"ui-answer-{case_id}-{question['question_key']}",
                               f"<input type='hidden' name='question_id' value='{esc(question['question_id'])}'>"
                               f"<input type='hidden' name='expected_row_revision' value='{row.get('revision', 1)}'>")
                + "<div class='qgroup'>"
                + f"<p>{esc(view['prompt'])}</p><p>{options}</p>"
                + ("<label>\uc9c1\uc811 \uc785\ub825<textarea name='direct_answer' maxlength='500'></textarea></label>"
                   if question["question_key"] == "trip_move_reason" else "")
                + "<button class='btn' type='submit'>답변 저장</button></div></form>")
    if not state["open_questions"]:
        parts.append("<p class='muted'>더 물을 질문이 없어요.</p>")

    if state["should_not_create_rule"]:
        parts.append(
            "<form method='post' action='/api/classification/dialog/close'>"
            + _rule_hidden(case_id, f"ui-close-{case_id}")
            + "<button class='btn' type='submit'>대화 닫기</button></form>")
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id=row.get('display_tab_id') or '',
            heading='규칙 대화',
            body=(f"<div class='sect'>{''.join(parts)}"
                  f"<p><a href='/row?id={esc(row_id)}'>내용으로 돌아가기</a> · "
                  "<a href='/board'>목록으로</a></p></div>")))

    # 규칙 초안 요청
    turn_no = (conv.get("turn_count") or 0) + 1
    parts.append(
        "<form method='post' action='/api/classification/conversation/advance'>"
        + _rule_hidden(case_id, f"ui-turn-{case_id}-{turn_no:02d}")
        + "<button class='btn' type='submit'>규칙 초안 요청</button></form>")
    if conv.get("turns"):
        last = conv["turns"][-1]
        review = last.get("owner_review")
        parts.append(
            f"<p class='muted'>최근 턴 {esc(last['turn_id'])}: "
            f"{esc(last.get('state_label') or last['state'])}"
            + (f" · 채택 {esc(last['adopted_provider'])}" if last["adopted_provider"] else "")
            + (f" · 사유 {esc(reason_label(last['reason_code']))}"
               if last["reason_code"] else "")
            + (f" · 전환 {last['switch_count']}회" if last["switch_count"] else "")
            + (f" · 소유권 확인 대기 ({esc(reason_label(review['reason']))})"
               if review else "")
            + "</p>")
    if pending.get("draft_error"):
        parts.append(f"<p class='muted'>초안 검증 실패: {esc(pending['draft_error']['message'])}</p>")

    if not rule and dialog != "closed":
        parts.append(
            "<p class='muted'>이 거래에서 저장한 수정(항목·여행)을 같은 가맹점 거래에 반복 적용하는 규칙 초안을 만듭니다."
            " 초안은 아직 아무 행도 바꾸지 않으며, 아래에서 영향 미리보기를 확인한 뒤 직접 적용합니다.</p>"
            "<form method='post' action='/api/classification/conversation/owner-draft'>"
            + _rule_hidden(case_id, f"ui-owner-draft-{case_id}")
            + "<button class='btn' type='submit'>내 수정 내용으로 규칙 초안 만들기</button></form>")

    if pending.get("rule") and not pending.get("confirmed"):
        parts.append(
            "<p class='muted'>검증을 통과한 초안이에요. 저장하면 규칙 초안이 되고, 적용은 "
            "아래에서 범위를 고른 뒤 따로 합니다.</p>"
            "<form method='post' action='/api/classification/conversation/confirm-draft'>"
            + _rule_hidden(case_id, f"ui-confirm-{case_id}-{pending.get('turn_id', '')}")
            + "<button class='btn' type='submit'>초안 저장</button></form>")

    if rule:
        parts.append(
            f"<p class='muted'>저장된 규칙 {esc(rule['rule_id'])} · version {rule['version']}"
            f" · {esc(rule['status'])}</p>"
            f"<p><b>적용 조건</b> {esc(_rule_scope_text(rule['rule']))}</p>")
        existing = state.get("last_preview") or {}
        preview = existing.get("plan") or {}
        if preview:
            counts = preview.get("counts", {})
            amounts = preview.get("amounts", {})
            rows_html = "".join(
                f"<tr><td>{esc(c['row_id'])}</td><td>{esc(c['from_tab_id'] or '분류대기')}"
                f"</td><td>{esc(c['to_tab_id'] or '분류대기')}</td>"
                f"<td style='text-align:right'>{esc(c['amount_krw'])}</td></tr>"
                for c in preview.get("candidates", []))
            excluded_html = "".join(
                f"<li>{esc(e['row_id'])}: {esc(e['reason'])}</li>"
                for e in preview.get("excluded", []))
            parts.append(
                f"<h4>영향 미리보기 (preview {esc(existing['preview_id'])[:12]}…)</h4>"
                f"<p class='muted'>포함 {counts.get('included_rows', 0)}건 · 제외 "
                f"{counts.get('excluded_rows', 0)}건 · 매칭 {counts.get('matched_rows', 0)}건</p>"
                f"<table class='rules-table'><tr><th>행</th><th>이동 전</th><th>이동 후</th>"
                f"<th style='text-align:right'>금액</th></tr>{rows_html}</table>"
                + (f"<ul class='muted'>{excluded_html}</ul>" if excluded_html else "")
                + "<p class='muted'>합계(전): " + ", ".join(
                    f"{esc(tab)} {esc(value.get('before'))} → {esc(value.get('after'))}"
                    for tab, value in amounts.items()) + "</p>")
        parts.append(
            "<form method='post' action='/api/classification/rules/preview'>"
            + _rule_hidden(case_id, f"ui-preview-{case_id}-{turn_no:02d}",
                           f"<input type='hidden' name='rule_id' value='{esc(rule['rule_id'])}'>")
            + "<label style='margin-right:12px'><input type='checkbox' name='apply_existing' value='1' checked>"
            " 기존 행 적용</label>"
            + "<label><input type='checkbox' name='apply_future' value='1'> 미래 입력 적용</label>"
            + "<button class='btn' type='submit'>영향 미리보기</button></form>")
        if preview and existing:
            selected = ",".join(c["row_id"] for c in preview.get("candidates", []))
            parts.append(
                "<form method='post' action='/api/classification/rules/apply'>"
                + _rule_hidden(case_id, f"ui-apply-{case_id}-{existing['preview_id'][:12]}",
                               f"<input type='hidden' name='preview_id' value='{esc(existing['preview_id'])}'>"
                               f"<input type='hidden' name='apply_existing' value='{existing['apply_existing'] and '1' or ''}'>"
                               f"<input type='hidden' name='apply_future' value='{existing['apply_future'] and '1' or ''}'>"
                               + (f"<input type='hidden' name='selected_row_ids' value='{esc(selected)}'>" if selected else ""))
                + "<button class='btn' type='submit'>이 범위로 적용</button></form>")
    if dialog != "not_started":
        # Closing a dialog that was never started is refused by the store, so the
        # control is not offered until there is something to close.
        parts.append(
            "<form method='post' action='/api/classification/dialog/close'>"
            + _rule_hidden(case_id, f"ui-close-{case_id}")
            + "<button class='btn' type='submit'>대화 닫기</button></form>")
    body = (f"<div class='sect'>{''.join(parts)}"
            f"<p class='meta'>행 {row_id} · revision {row.get('revision', 1)}</p>"
            f"<p><a href='/row?id={row_id}'>내용으로 돌아가기</a> · "
            "<a href='/board'>목록으로</a></p></div>")
    return ledger_design.render(ledger_design.shell(
        '규칙 대화', tab_id=row.get('display_tab_id') or '',
        heading='규칙 대화', body=body))


def trips_page(preview_tab: str = "", role: str = "") -> str:
    from . import ledger_design
    from .sheets_export import _assignee_confirmed

    if not role:
        # Called without a request (local single-user mode, and the tests that
        # exercise this page directly). Under enforcement the route always
        # passes the role it decided on the server, so nothing is guessed here.
        role = "viewer" if ACCESS_ENFORCEMENT else "owner"
    if _active_store() is None:
        body = "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>"
        return layout("여행 관리", f"{top}<div class='wrap'>{body}</div>")
    store = _active_store()
    profile = (store.owner_profile() if store is not None
               and hasattr(store, "owner_profile")
               else {"company_name": "", "assignee_name": "", "revision": 0})
    cards = []
    from app.reserve_trips import registrations
    reserve_trips = registrations(store)
    for t in live_trips(include_archived=True):
        if t.get("deleted"):
            continue
        try:
            kind = "보관됨" if t["archived"] else "활성"
            registration = reserve_trips.get(t['tab_id'])
            if registration and not t['archived']:
                from app.reserve_trips import today
                status = registration['departure_status']
                kind = ('출발일·댓글 확인 필요' if status != 'scheduled' else
                        '출발 예정' if t['starts_on'] >= today() else '출발한 여행')
            preview = _active_store().preview_tab_delete(t["tab_id"])
            counts = (f"수입 {preview['income_count']}건 {preview['income_total']:,}원 · "
                      f"지출 {preview['expense_count']}건 {preview['expense_total']:,}원")
        except Exception as exc:
            counts = f"조회 실패: {esc(str(exc))}"
        # A trip whose assignee has a value but no recorded origin. It is reported,
        # never rewritten: quietly replacing it would destroy a record whose true
        # author is unknown, and the owner confirms it on this same form.
        assignee_shown = str(t.get("prepared_by_name") or "")
        assignee_note = ""
        if assignee_shown and not _assignee_confirmed(
                getattr(store, "conn", None), t["tab_id"],
                t.get("assignee_source") or "", assignee_shown):
            assignee_note = (
                " <span class='muted warntext'>· 담당자 확인이 필요해요"
                " (출처가 기록되지 않은 값이에요)</span>")
        cards.append(
            "<div class='card'>"
            f"<h3>{esc(t['display_key'])} <span class='muted'>{kind}</span></h3>"
            f"<p class='muted rev-note'>여행 revision {t['revision']}</p>"
            f"<p class='muted'>{esc(t['starts_on'])}~{esc(t['ends_on'])} · {esc(t['destination'])}</p>"
            f"<p class='muted'>작성일 {esc(t['prepared_on'])} · 담당자 "
            f"{esc(assignee_shown) if assignee_shown else '미입력'}{assignee_note}</p>"
            # APP_SPEC 3 keeps the schedule authority and the tab kind apart from
            # the display name, so the screen states them rather than implying
            # them through the name.
            f"<p class='muted'>연도 {esc(str(t.get('event_year') or ''))} · "
            f"종류 {esc(t.get('tab_kind') or 'trip')} · "
            f"권위 {esc(AUTHORITY_LABELS.get(t.get('authority_status'), '미확인'))}</p>"
            f"<p>{counts}</p>"
            + (f"<p class='muted'>댓글 {str(registration['comment_count'])+'개' if registration['comment_count'] is not None else '확인 불가'} · "
               f"<a href='{esc(registration['source_url'])}' target='_blank' rel='noopener'>여행글 보기</a></p>"
               if registration else '')
            +
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            f"<p><label>표시 이름</label><input name='display_key' value='{esc(t['display_key'])}'></p>"
            f"<p><label>작성일</label><input name='prepared_on' value='{esc(t['prepared_on'])}'></p>"
            f"<p><label>담당자</label><input name='prepared_by_name' value='{esc(assignee_shown)}'>"
            # The marker is a hidden field that is always submitted, and the
            # confirmation is a separate tick. An unchecked checkbox sends
            # nothing at all, so making the flag itself the checkbox would leave
            # an un-ticked form indistinguishable from a plain JSON caller.
            + f"<input type='hidden' name='assignee_form' value='1'>"
            + (f"<label class='muted'><input type='checkbox' name='assignee_confirmed' value='1'>"
               "이 담당자가 맞다고 확인해요</label>" if assignee_note else "")
            + "</p>"
            f"<button type='submit'>{ui_icons.icon('save')}정보 저장</button></form>"
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<input type='hidden' name='archived' value='{'0' if t['archived'] else '1'}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            f"<button type='submit'>{ui_icons.icon('archive')}{'복원' if t['archived'] else '보관'}</button></form>"
            f"<p><a href='/trips?preview_tab={esc(t['tab_id'])}'>삭제 미리보기</a></p>"
            "</div>"
        )
    profile_html = ""
    if role == "owner":
        # The owner's own company name and default assignee. Owner-only, because
        # it is the source for what every new trip is stamped with, and an empty
        # field is a legitimate state rather than something to guess at.
        profile_html = (
            "<div class='card'><h3>회사·담당자 정보</h3>"
            "<form method='post' action='/api/owner-profile' id='owner-profile-form'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{profile['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            "<p><label>회사명</label>"
            f"<input name='company_name' value='{esc(profile['company_name'])}'></p>"
            "<p><label>기본 담당자명</label>"
            f"<input name='assignee_name' value='{esc(profile['assignee_name'])}'></p>"
            "<p class='muted'>새로 만드는 여행에만 복사되고, 이미 있는 여행은 바뀌지 않습니다.</p>"
            f"<button type='submit'>{ui_icons.icon('save')}출처 정보 저장</button></form></div>")
    preview_html = ""
    if preview_tab:
        try:
            preview = _active_store().preview_tab_delete(preview_tab)
            dest_options = "".join(
                f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>"
                for t in live_trips() if t["tab_id"] != preview_tab
            )
            snapshot_json = esc(json.dumps(preview["snapshot"], ensure_ascii=False,
                                           sort_keys=True, default=str))
            preview_html = (
                "<div class='card'><h3>삭제 미리보기</h3>"
                f"<p>{esc(preview['display_key'])}: 수입 {preview['income_count']}건 "
                f"{preview['income_total']:,}원 · 지출 {preview['expense_count']}건 "
                f"{preview['expense_total']:,}원 · 배분 {preview['allocation_count']}건 · "
                f"대기 규칙 {preview['waiting_rules']}건</p>"
                f"<form method='post' action='/api/trips/{esc(preview_tab)}/delete'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                f"<input type='hidden' name='snapshot' value='{snapshot_json}'>"
                "<input type='hidden' name='return_to' value="
                f"'{esc('/trips?preview_tab=' + preview_tab)}'>"
                "<p><label>처리 방법</label><select name='mode'>"
                "<option value='move-unclassified'>분류대기로 이동</option>"
                "<option value='move-trip'>다른 여행으로 이동</option></select></p>"
                f"<p><label>목적지</label><select name='destination'>{dest_options}</select></p>"
                f"<button type='submit'>{ui_icons.icon('alert-triangle')}내역 이동 후 삭제 확정</button></form>"
                "<p class='muted'>원천·이력·과거 출력은 지우지 않고 화면 탭만 없앱니다. "
                "확정 시점에 장부가 바뀌었으면 처음부터 다시 확인합니다.</p></div>"
            )
        except Exception as exc:
            preview_html = f"<div class='card'><p>미리보기 실패: {esc(str(exc))}</p></div>"
    body = (f"<div class='sect'><h2>여행 관리</h2>{profile_html}{preview_html}"
            f"{''.join(cards)}</div>")
    return ledger_design.render(ledger_design.shell(
        "여행 관리", tab_id="", heading="여행 관리", body=body))


def export_page() -> str:
    from .sheets_export import assignee_needs_confirmation

    store = _active_store()
    active_trips = live_trips()
    archived_trips = ([t for t in live_trips(include_archived=True) if t["archived"]]
                      if store is not None else [])
    # Only the trips this page actually offers are judged. A deleted trip is not
    # on the page at all, and counting it would put a number here that names
    # nothing the owner can see. One call to the one decision function, so the
    # screen and the export cannot drift apart.
    shown_ids = [t["tab_id"] for t in active_trips + archived_trips]
    unconfirmed = set(assignee_needs_confirmation(store, shown_ids)
                      if store is not None else [])

    def trip_option(trip, suffix="", checked=True):
        tab_id = trip["tab_id"]
        note = ""
        if tab_id in unconfirmed:
            # The trip keeps the selection the page already gave it. Silently
            # unticking one would decide the owner's selection for them, and the
            # export they did not expect would be missing a trip. The note is
            # what is added.
            note = (" <span class='muted warntext'>담당자 확인이 필요해요"
                    " (출처가 기록되지 않은 값이 있어요) · "
                    "<a href='/trips'>여행 관리에서 확인</a></span>")
        return (f"<label><input type='checkbox' name='tab_ids'"
                f" value='{esc(tab_id)}'"
                + (" checked>" if checked else ">")
                + f" {esc(trip['display_key'])}{esc(suffix)}{note}</label><br>")

    options = "".join(trip_option(t) for t in active_trips)
    archived = ""
    if archived_trips:
        archived = "<h3>보관된 여행</h3>" + "".join(
            trip_option(t, " (보관)", checked=False) for t in archived_trips
        )
    counts = ""
    progress_note = ""
    jobs_html = ""
    # `review_note` is built further down inside the store branch, but the body
    # below uses it either way. Leaving it undefined made `export_page()` raise
    # `UnboundLocalError` whenever no store was bound, so the page could not be
    # rendered at all in that state rather than showing its empty form.
    review_note = ""
    if _active_store() is not None:
        trip_counts = board_export_helpers.export_trip_counts(
            live_trips(include_archived=True),
            list_tab_rows_fn=_active_store().list_tab_rows,
        )
        lines = []
        for tc in trip_counts:
            if tc["tab_id"] is None:
                lines.append(f"<li>분류대기: 수입 {tc['income_count']}행 · 지출 {tc['expense_count']}행 (출력에 들어가지 않아요)</li>")
            else:
                lines.append(
                    f"<li>{esc(tc['display_key'])}: 수입 {tc['income_count']}행 · 지출 {tc['expense_count']}행"
                    + (" (보관)" if tc["archived"] else "") + "</li>"
                )
        counts = f"<ul>{''.join(lines)}</ul>"
        # APP_SPEC 8 asks the dialog to state the 검토필요 and 충돌 row counts.
        # Both are read off the ledger: a row needs a person when it has no trip
        # or no recorded classification basis, and it is in conflict when the
        # row's newest ledger event is a conflict note.
        rc_summary = board_export_helpers.export_review_conflict_counts(
            live_trips(include_archived=True),
            list_tab_rows_fn=_active_store().list_tab_rows,
            row_needs_review_fn=row_needs_review,
            row_has_conflict_fn=row_has_conflict,
        )
        review_note = (
            "<p class='muted'>검토필요 {review}행 · 충돌 {conflict}행"
            "이 포함됩니다. 출력해도 분류는 바뀌지 않습니다."
            "</p>").format(review=rc_summary["review_total"],
                           conflict=rc_summary["conflict_total"])
        if rc_summary["per_tab"]:
            per_tab_lis = "".join(
                f"<li>{esc(pt['display_key'])}: 검토필요 {pt['review_count']}행"
                + (f" · 충돌 {pt['conflict_count']}행" if pt['conflict_count'] else "")
                + "</li>"
                for pt in rc_summary["per_tab"]
            )
            review_note += f"<ul class='muted'>{per_tab_lis}</ul>"
        try:
            importing = _active_store().conn.execute(
                "SELECT 1 FROM card_import_batches "
                "WHERE status IN ('reconciling','parsing') LIMIT 1").fetchone()
            if importing:
                progress_note = ("<p class='muted'>내역을 가져오는 중입니다. "
                                 "현재 저장된 내용만 포함합니다.</p>")
        except sqlite3.OperationalError:
            pass
        from .sheets_export import list_jobs

        jobs = list_jobs(_active_store().conn)
        if jobs:
            items = "".join(
                f"<li>{esc(j['created_at'])} · {len(j['tab_ids'])}개 탭 · "
                f"<a href='/api/exports/{esc(j['job_id'])}/download'>다운로드</a></li>"
                for j in jobs
            )
            jobs_html = f"<h3>최근 출력</h3><ul>{items}</ul>"
    body = (
        "<div class='sect'><h2>선택 탭 출력</h2>"
        f"{review_note}"
        f"{counts}"
        f"<form method='post' action='/api/exports/xlsx'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"{options}{archived}"
        "<p class='muted'>분류대기 거래가 포함될 수 있습니다.</p>"
        f"{progress_note}"
        + (("<p class='muted warntext'>담당자 확인이 필요한 여행 "
            + str(len(unconfirmed))
            + "개가 있어요. 해당 여행을 선택하면 확인 전에는 출력할 수 없어요. "
            "<a href='/trips'>여행 관리에서 확인</a></p>")
           if unconfirmed else "")
        + "<button type='submit'>출력</button></form>"
        f"{jobs_html}"
        "</div>"
    )
    from . import ledger_design

    return ledger_design.render(ledger_design.shell(
        '선택 탭 출력', tab_id='', heading='선택 탭 출력', body=body))


def import_page() -> str:
    from . import ledger_design

    body = (
        "<div class='sect'><h2>카드 가져오기 (합성 프로필)</h2>"
        f"<input type='file' id='f' accept='.csv'>"
        f"<button id='up'>올리기</button><p id='msg' class='muted'></p>"
        "<div id='res'></div>"
        "<h2>은행 가져오기 (합성 프로필)</h2>"
        f"<input type='file' id='bf' accept='.csv'>"
        f"<button id='bup'>올리기</button><p id='bmsg' class='muted'></p>"
        "<div id='bres'></div>"
        "<p><a href='/income/new'>수입 직접 입력</a> · <a href='/expense/new'>수기 지출 추가</a></p>"
        "<script>"
        f"const csrf='{CSRF_TOKEN}';"
        "document.getElementById('up').onclick=async()=>{"
        "const f=document.getElementById('f').files[0];if(!f){return;}"
        "const m=document.getElementById('msg');m.textContent='읽는 중';"
        "const r=await fetch('/api/imports',{method:'POST',"
        "headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(f.name),'X-CSRF-Token':csrf},"
        "body:f});"
        "if(!r.ok){const e=await r.json().catch(()=>({}));"
        "m.textContent='실패: '+(e.message||r.status)+' — 다시 올리면 이어서 처리해요.';return;}"
        "const j=await r.json();"
        "m.textContent='접수됐어요. 가져오는 동안 장부와 여기서 진행을 볼 수 있어요.';"
        "let p={};"
        "for(let i=0;i<120;i++){"
        "const q=await fetch('/api/imports/'+j.batch_id);"
        "if(!q.ok){m.textContent='진행 조회 실패 — 새로고침 뒤 다시 확인해 주세요.';return;}"
        "p=(await q.json()).result||{};"
        "if(p.status&&p.status!=='reconciling'&&p.status!=='parsing'&&p.status!=='processing')break;"
        "m.textContent='분류 중(가져온 행부터 장부에 보여요)...';"
        "await new Promise(s=>setTimeout(s,500));}"
        "if(p.status==='reconciling'||p.status==='parsing'||p.status==='processing'){"
        "m.textContent='아직 처리 중이에요. 잠시 뒤 새로고침하면 이어져요.';return;}"
        "m.textContent='완료';"
        "document.getElementById('res').innerHTML="
        "'<p>원본 '+p.source_rows+'행 · 새 사건 '+p.new_events+'건 · 여행 배치 '+p.placed_trips"
        "+'건 · 분류대기 '+p.placed_unclassified+'건 · 오류 '+p.parse_errors+'건 · 충돌 '+p.conflicts+'건</p>'"
        "+'<p><a href=\"/board\">여행 탭에서 보기</a> · <a href=\"/board?tab=unclassified\">분류대기 열기</a></p>';};"
        "document.getElementById('bup').onclick=async()=>{"
        "const f=document.getElementById('bf').files[0];if(!f){return;}"
        "const m=document.getElementById('bmsg');m.textContent='읽는 중';"
        "const r=await fetch('/api/bank-imports',{method:'POST',"
        "headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(f.name),'X-CSRF-Token':csrf},"
        "body:f});"
        "if(!r.ok){const e=await r.json().catch(()=>({}));"
        "m.textContent='실패: '+(e.message||r.status)+' — 열 이름을 확인해 주세요.';return;}"
        "const j=await r.json();"
        "m.textContent='완료';"
        "document.getElementById('bres').innerHTML="
        "'<p>원본 '+j.result.source_rows+'행 · 새 입금 '+j.result.new_events+'건 · 제외 '+j.result.excluded_rows+'건</p>'"
        "+'<p><a href=\"/board?tab=unclassified\">분류대기 열기</a></p>';};"
        "</script></div>"
    )
    return ledger_design.render(ledger_design.shell(
        '카드 가져오기', tab_id='', heading='카드 가져오기', body=body))


def _shown_amount(row) -> int:
    return board_read_projection.shown_amount(row)


def income_table(rows) -> str:
    return board_render_helpers.income_table(
        rows,
        shown_date_fn=_shown_date,
        shown_amount_fn=_shown_amount,
    )


def expense_table(rows) -> str:
    return board_render_helpers.expense_table(
        rows,
        shown_date_fn=_shown_date,
        shown_amount_fn=_shown_amount,
    )


editable_fields = board_render_helpers.editable_fields


def learning_case_id(row_id: str) -> str:
    return board_render_helpers.learning_case_id(
        row_id,
        store=_active_store(),
    )


def rule_dialog_link(row_id: str) -> str:
    return board_render_helpers.rule_dialog_link(
        row_id,
        store=_active_store(),
    )


def detail_page(row_id: str, edit: bool = False) -> str:
    kind, row = find_row(row_id)
    from . import ledger_design

    if row is None:
        return layout("행 없음", "<div class='top'><h1>웹 장부</h1></div><div class='body'><p>행이 없어요.</p></div>")
    from . import ledger_design

    if row.get("is_allocation") and _active_store() is not None:
        body = allocation_detail_body(row, edit)
        return ledger_design.render(ledger_design.shell(
            "배분 행 상세", tab_id=row.get("display_tab_id") or "",
            heading=f"배분 {esc(row_id)}", body=(
                f"<div class='sect'>{body}"
                "<p><a href='/board'>목록으로</a></p></div>")))
    if kind == "expense":
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>분류 근거: {esc(row['classification_basis'])}</li>"
            f"<li>분류 상태: {esc(row['classification_state'])} (표시만 일반 행)</li>"
            f"<li>여행 revision {esc(str(row.get('revision', 1)))}</li>"
        )
        if edit:
            if _active_store() is None:
                form = (
                    "<h3>행 편집 (저장 준비 중)</h3>"
                    "<p class='muted'>저장소가 연결되지 않았어요.</p>"
                    "<button class='btnprep' disabled>저장 준비 중</button>"
                )
            else:
                options = (
                    "<option value='unclassified'"
                    f"{' selected' if row['display_tab_id'] is None else ''}>"
                    "분류대기</option>"
                    + "".join(
                        f"<option value='{esc(t['tab_id'])}'"
                        f"{' selected' if row['display_tab_id'] == t['tab_id'] else ''}>"
                        f"{esc(t['display_key'])}</option>"
                        for t in live_trips()
                    )
                )
                if row.get("source_kind") == "수기":
                    extra_fields = (
                        f"<p><label>거래일자</label><input name='occurred_on' value='{esc(row['occurred_on'])}'></p>"
                        f"<p><label>금액(원)</label><input name='amount_krw' value='{esc(row['amount_krw'])}'></p>"
                    )
                    fixed_note = "원천 식별자는 고정 필드라 바꿀 수 없어요."
                else:
                    extra_fields = ""
                    fixed_note = "거래일자·금액·원천 식별자·가맹점 원문은 고정 필드라 바꿀 수 없어요."
                form = (
                    "<h3>행 편집</h3>"
                    f"<form method='post' action='/api/rows/{esc(row_id)}/save'>"
                    f"<input type='hidden' name='return_to' value='{esc('/row?id=' + row_id + ('&edit=1' if edit else ''))}'>"
                    f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                    f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                    f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                    f"<p><label>여행 배정</label><select name='display_tab_id'>{options}</select></p>"
                    f"<p><label>항목</label><input name='item' value='{esc(row['item'])}'></p>"
                    f"<p><label>내용</label><input name='description' value='{esc(row['description'])}'></p>"
                    f"{extra_fields}"
                    f"<p><label>메모</label><input name='operator_note' value='{esc(row.get('operator_note', ''))}'></p>"
                    "<p><label>변경 이유</label><select name='change_mode'>"
                    "<option value='exception'>예외 사항</option>"
                    "<option value='rule_change'>규칙 변경</option></select></p>"
                    f"<p class='muted'>{fixed_note}</p>"
                    "<button type='submit'>저장</button> "
                    "<a href='/row?id=" + esc(row_id) + "'>취소</a></form>"
                )
        else:
            form = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
        body = (
            f"<h2>지출 {esc(row['description'])} {row['amount_krw']:,}원</h2>"
            f"<ul>{info}</ul>"
            f"<p>메모: {esc(row.get('operator_note') or '없음')}</p>"
            f"{form}{history_html(row_id)}"
        )
    else:
        info = (
            f"<li>원천: {esc(row['source_kind'])} {esc(row['source_event_id'])}</li>"
            f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(row['income_kind'], ''))}</li>"
            f"<li>사건 구분: {esc(row['event_type'])}</li>"
        )
        extra = ""
        if _active_store() is not None and row.get("source_kind") == "은행":
            corrections = _active_store().list_corrections(row_id)
            if corrections:
                lis = "".join(
                    f"<li>{esc(c['corrected_amount_krw'])}원"
                    + (f" · {esc(c['corrected_occurred_on'])}" if c.get("corrected_occurred_on") else "")
                    + f" · {esc(c['reason'])} · {esc(c['created_at'])}</li>"
                    for c in corrections
                )
                extra = f"<h3>정정 기록</h3><ul>{lis}</ul>"
            extra += (
                "<h3>장부 정정</h3>"
                f"<form method='post' action='/api/income/{esc(row_id)}/correct'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                "<p><label>장부 표시 금액</label><input name='corrected_amount_krw'></p>"
                "<p><label>장부 표시 날짜(선택)</label><input name='corrected_occurred_on' placeholder='2026-04-02'></p>"
                "<p><label>이유</label><input name='reason'></p>"
                "<button type='submit'>정정 기록</button></form>"
                "<p class='muted'>은행 원본은 그대로 두고 장부 표시만 바꿔요.</p>"
            )
        elif _active_store() is not None and row.get("source_kind") == "직접 입력":
            options = (
                "<option value='unclassified'"
                f"{' selected' if row['display_tab_id'] is None else ''}>"
                "분류대기</option>"
                + "".join(
                    f"<option value='{esc(t['tab_id'])}'"
                    f"{' selected' if row['display_tab_id'] == t['tab_id'] else ''}>"
                    f"{esc(t['display_key'])}</option>"
                    for t in live_trips()
                )
            )
            kind_options = "".join(
                f"<option value='{k}'{' selected' if row['income_kind'] == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            )
            links = _active_store().conn.execute(
                "SELECT bank_batch_id, bank_row_index FROM income_source_links WHERE row_id=?",
                (row_id,),
            ).fetchall()
            link_lines = "".join(
                f"<li>은행 원천 {esc(b)} #{i}</li>" for b, i in links
            )
            link_info = f"<h3>연결된 은행 원천</h3><ul>{link_lines}</ul>" if link_lines else ""
            candidates = _active_store().find_bank_candidates(row_id)
            cand_lines = "".join(
                f"<li>{esc(c['occurred_on'])} · {esc(c['customer_name'])} · "
                f"{c['amount_krw']:,}원 · {esc(c['row_id'])}</li>"
                for c in candidates
            )
            cand_info = (
                "<h3>중복 후보(판단 전, 합산 제외 아님)</h3><ul>{cand_lines}</ul>"
                if cand_lines else ""
            ).format(cand_lines=cand_lines)
            lock_note = (
                "<p class='muted'>은행 원천 연결 뒤에는 날짜·금액을 여기서 바꿀 수 없어요. 은행 정정 경로를 써 주세요.</p>"
                if links else ""
            )
            if edit:
                extra = (
                    "<h3>행 편집</h3>"
                    f"<form method='post' action='/api/rows/{esc(row_id)}/save'>"
                    f"<input type='hidden' name='return_to' value='{esc('/row?id=' + row_id + ('&edit=1' if edit else ''))}'>"
                    f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                    f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                    f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                    f"<p><label>여행 배정</label><select name='display_tab_id'>{options}</select></p>"
                    f"<p><label>거래일자</label><input name='occurred_on' value='{esc(row['occurred_on'])}'></p>"
                    f"<p><label>금액(원)</label><input name='amount_krw' value='{esc(row['amount_krw'])}'></p>"
                    f"<p><label>입금 종류</label><select name='income_kind'>{kind_options}</select></p>"
                    f"<p><label>이름</label><input name='customer_name' value='{esc(row['customer_name'])}'></p>"
                    f"<p><label>닉네임</label><input name='nickname' value='{esc(row.get('nickname', ''))}'></p>"
                    f"<p><label>메모</label><input name='operator_note' value='{esc(row.get('operator_note', ''))}'></p>"
                    "<p><label>변경 이유</label><select name='change_mode'>"
                    "<option value='exception'>예외 사항</option>"
                    "<option value='rule_change'>규칙 변경</option></select></p>"
                    f"{lock_note}"
                    "<button type='submit'>저장</button> "
                    "<a href='/row?id=" + esc(row_id) + "'>취소</a></form>"
                )
            else:
                extra = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
            extra += (
                f"{link_info}{cand_info}"
                "<h3>은행 원천 연결</h3>"
                f"<form method='post' action='/api/income/{esc(row_id)}/link-bank'>"
                f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
                "<p><label>은행 배치 ID</label><input name='bank_batch_id'></p>"
                "<p><label>은행 행 번호</label><input name='bank_row_index'></p>"
                "<button type='submit'>연결</button></form>"
            )
        elif edit:
            extra = "<p class='muted'>은행 원천 행은 정정 경로로만 바꿀 수 있어요.</p>"
        else:
            extra = f"<p><a href='/row?id={esc(row_id)}&edit=1'>편집</a></p>"
        if _active_store() is not None:
            if row.get("is_allocation"):
                source = _active_store().get_row(row["source_row_id"])
                reflected = _active_store().display_amount(source) if source else 0
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<p class='muted'>원천 입금 {reflected:,}원 중 이 배분 {_shown_amount(row):,}원. "
                    "배분액은 배분 편집에서만 바꿔요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a> · "
                    f"<a href='/row?id={esc(row['source_row_id'])}'>원천 상세</a></p>"
                )
            elif row.get("is_remainder"):
                source = _active_store().get_row(row["source_row_id"])
                reflected = _active_store().display_amount(source) if source else 0
                extra = (
                    "<h3>미배분 잔액</h3>"
                    f"<p class='muted'>원천 입금 반영액 {reflected:,}원 중 아직 나누지 않은 금액이에요. "
                    "독립 입금 사건이 아니에요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a></p>"
                )
            elif row["row_id"] in _active_store().split_source_ids():
                allocs = _active_store().active_allocations(row["row_id"])
                remainder = _active_store().split_remainder(row["row_id"])
                lines = "".join(
                    f"<li>{esc(a['customer_name'])} · "
                    f"{esc(next((t['display_key'] for t in live_trips(include_archived=True) if t['tab_id'] == a['display_tab_id']), '분류대기'))} · "
                    f"{esc(INCOME_KIND_LABEL.get(a['income_kind'], ''))} · {a['amount_krw']:,}원</li>"
                    for a in allocs
                )
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<ul>{lines}</ul>"
                    f"<p class='muted'>미배분 잔액 {remainder:,}원. 원금은 합계에 넣지 않아요.</p>"
                    f"<p><a href='/income/{esc(row_id)}/split'>배분 편집 열기</a></p>"
                )
            elif not edit:
                extra += f"<p><a href='/income/{esc(row_id)}/split'>입금 나누기</a></p>"
        body = f"<h2>수입 {esc(row['customer_name'])} {_shown_amount(row):,}원</h2><ul>{info}</ul>{extra}"

    return ledger_design.render(ledger_design.shell(
        "행 상세", tab_id=row.get("display_tab_id") or "",
        heading=f"거래 {esc(row_id)}",
        meta=(f"<span>구분 <b>{'수입' if kind == 'income' else '지출'}</b></span>"
              + ("<span><a href='/trips'>여행 관리</a></span>" if kind != "income" else "")),
        body=(f"<div class='sect'>{body}{rule_dialog_link(row_id)}"
              "<p><a href='/board'>목록으로</a></p></div>")))


STATUS_FOR_CODE = {
    # The first block is the vocabulary of DETAILED_CONTRACT 4.3.
    "AUTH_REQUIRED": 401,
    "ACTION_FORBIDDEN": 403,
    "RESOURCE_NOT_FOUND": 404,
    "TEMPORARILY_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
    # Phase 6 provider configuration.
    "PROVIDER_CONFIG_UNBOUND": 503,
    "EDIT_CONFLICT": 409,
    "REQUEST_ID_REUSED": 409,
    # An export naming an assignee whose origin was never recorded. Refused whole
    # rather than produced with a marker on the sheet.
    "ASSIGNEE_UNCONFIRMED": 409,
    "FIELD_READ_ONLY": 422,
    "INVALID_VALUE": 422,
    "TARGET_NOT_ASSIGNABLE": 422,
    "CSRF_REQUIRED": 403,
    "PREVIEW_STALE": 409,
    "REFUND_PAIR_PARTIALLY_BOOKED": 409,
    "REFUND_GROUP_INCOMPLETE": 409,
    "DELETE_PREVIEW_STALE": 409,
    "RULE_FIELD_NOT_ALLOWED": 422,
    "RULE_EFFECT_FORBIDDEN": 422,
    "RULE_SCOPE_INCOMPLETE": 422,
    "RULE_CONDITION_TYPE": 422,
    "RULE_OPERATOR_NOT_ALLOWED": 422,
    "RULE_TEMPLATE_FORBIDDEN": 422,
    "RULE_SUPERSEDED": 409,
    "RULE_ONE_OFF": 422,
    "DIALOG_STALE": 409,
    "DIALOG_CLOSED": 409,
}


def _login_entry_body(has_login: bool) -> str:
    """Pretty static first-screen login card, no query reflection."""
    style = (
        "<style>"
        "body{margin:0;background:#faf6ec;}"
        ".lg-wrap{box-sizing:border-box;display:flex;align-items:center;"
        "justify-content:center;min-height:100vh;margin:0;padding:28px 16px;"
        "background:#faf6ec;}"
        ".lg-card{box-sizing:border-box;width:100%;max-width:440px;"
        "background:#fffdf8;border:1px solid #e7ddc6;border-radius:18px;"
        "padding:32px 28px;text-align:center;"
        "box-shadow:0 12px 32px rgba(47,93,58,.12),"
        "0 2px 6px rgba(60,50,30,.06);"
        "font-family:system-ui,-apple-system,'Segoe UI',Roboto,"
        "'Noto Sans KR',sans-serif;color:#2b2a26;}"
        ".lg-logo{display:flex;justify-content:center;margin:0 0 12px;}"
        ".lg-badge{width:52px;height:52px;border-radius:16px;"
        "background:#eef3e8;border:1px solid #d8e2cc;display:flex;"
        "align-items:center;justify-content:center;}"
        ".lg-brand{margin:0 0 4px;font-size:13px;letter-spacing:.12em;"
        "color:#5f7a63;font-weight:700;}"
        ".lg-title{margin:0 0 10px;font-size:28px;line-height:1.25;"
        "color:#234a2d;}"
        ".lg-desc{margin:0 0 20px;font-size:15px;line-height:1.65;"
        "color:#5b5546;}"
        ".lg-btn{box-sizing:border-box;display:flex;align-items:center;"
        "justify-content:center;gap:10px;min-height:52px;width:100%;"
        "padding:12px 16px;border-radius:12px;background:#2f5d3a;color:#fff;"
        "font-size:17px;font-weight:700;line-height:1.4;text-decoration:none;"
        "border:1px solid #2f5d3a;}"
        ".lg-btn:hover{background:#26492f;border-color:#26492f;}"
        ".lg-btn:focus-visible{outline:3px solid #1b3a23;outline-offset:3px;}"
        ".lg-g{width:22px;height:22px;border-radius:50%;background:#fff;"
        "display:inline-flex;align-items:center;justify-content:center;"
        "flex:none;}"
        ".lg-note{margin:16px 0 0;font-size:13.5px;line-height:1.6;"
        "color:#6b6455;}"
        ".lg-setup{box-sizing:border-box;margin:0;border:1px dashed #b9c4ab;"
        "border-radius:12px;background:#f2f5ec;padding:14px;font-size:14px;"
        "line-height:1.65;color:#43563f;}"
        "@media (max-width:360px){.lg-card{padding:26px 20px;}"
        ".lg-title{font-size:24px;}}"
        "@media (prefers-contrast:more){.lg-card{border-color:#234a2d;}"
        ".lg-desc,.lg-note{color:#2b2a26;}"
        ".lg-btn{text-decoration:underline;}}"
        "@media (forced-colors:active){.lg-card{border:2px solid CanvasText;}"
        ".lg-btn{forced-color-adjust:auto;}}"
        "</style>"
    )
    logo = (
        "<span class=\"lg-badge\" aria-hidden=\"true\">"
        "<svg viewBox=\"0 0 32 32\" width=\"30\" height=\"30\">"
        "<path d=\"M16 3 L24 14 H20.5 L26 22 H6 L11.5 14 H8 Z\" "
        "fill=\"#2f5d3a\"/>"
        "<rect x=\"14.7\" y=\"22\" width=\"2.6\" height=\"6\" rx=\"1\" "
        "fill=\"#7a5a3a\"/>"
        "<path d=\"M9 27.5 H23\" stroke=\"#7a5a3a\" stroke-width=\"1.6\" "
        "stroke-linecap=\"round\"/>"
        "</svg></span>"
    )
    google_g = (
        "<svg viewBox=\"0 0 24 24\" width=\"20\" height=\"20\">"
        "<path d=\"M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47"
        "c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 "
        "3.56-8.82z\" fill=\"#4285F4\"/>"
        "<path d=\"M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3"
        "c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29"
        "v3.09C3.26 21.3 7.31 24 12 24z\" fill=\"#34A853\"/>"
        "<path d=\"M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29"
        "V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z\" "
        "fill=\"#FBBC05\"/>"
        "<path d=\"M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42"
        "C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09"
        "C6.22 6.86 8.87 4.75 12 4.75z\" fill=\"#EA4335\"/>"
        "</svg>"
    )
    if has_login:
        action = (
            "<a class=\"lg-btn\" href=\"/auth/login\">"
            "<span class=\"lg-g\" aria-hidden=\"true\">"
            + google_g +
            "</span><span>Google 계정으로 로그인</span></a>"
        )
    else:
        action = (
            "<p class=\"lg-setup\">Google 로그인이 연결되어 있지 않아요. "
            "배포 환경 설정을 먼저 확인해 주세요.</p>"
        )
    return (
        "<meta name=\"viewport\" "
        "content=\"width=device-width, initial-scale=1\">"
        + style +
        "<main class=\"lg-wrap\"><div class=\"lg-card\">"
        "<div class=\"lg-logo\">" + logo + "</div>"
        "<p class=\"lg-brand\">숲길따라</p>"
        "<h1 class=\"lg-title\">웹 장부</h1>"
        "<p class=\"lg-desc\">여행별 수입과 지출을 차분히 정리하는 "
        "장부입니다.</p>"
        + action +
        "<p class=\"lg-note\">로그인 후 소유자의 승인이 필요합니다.</p>"
        "</div></main>"
    )


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        # Authentication responses own their cookies, including logout clearing.
        path = self.path.split("?", 1)[0]
        if not path.startswith("/auth/") and path != "/access/logout":
            adapter = access_control_session_adapter()
            renew = getattr(adapter, "renewal_cookie_header", None)
            if renew is not None:
                header = renew(self.headers)
                if header:
                    self.send_header("Set-Cookie", header)
        super().end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass

    def handle_one_request(self):
        """Serve one request, from the store of the server that accepted it.

        The board's store is a module global, which is right for a process that
        runs one ledger and wrong the moment a second server exists -- which is
        every test fixture, and also a graceful restart. A connection kept open
        by a client can deliver its next request after a teardown has rebound or
        cleared the global, and the handler then runs against a store that
        belongs to somebody else or to nobody.

        A context-local binding from `self.server` means every helper called by
        this request answers with the ledger of the server that accepted the
        connection. Another server can handle a request at the same time
        without replacing this request's store.

        A client that stops reading is a normal ending and is not an error: the
        socket is marked for closing rather than raising a traceback from a
        worker thread.
        """
        token = _REQUEST_STORE.set(getattr(self.server, "card_store", None))
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True
        finally:
            _REQUEST_STORE.reset(token)

    def _send(self, text: str, code: int = 200) -> None:
        from . import site_shell
        from . import social_preview
        text = social_preview.decorate(text)
        if not ACCESS_ENFORCEMENT or current_request_session() is not None:
            text = site_shell.wrap_document(text, self.path, status=code)
        # `no-store` on every HTML answer. The board is a live ledger: a browser
        # or proxy that may reuse a page or a fragment would show a stale ledger
        # and call it current, and the cross-screen change check compares against
        # the same database, so a cached copy would make the two disagree.
        data = text.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    # ------------------------------------------------- the session cookie
    def _platform_probe(self, path: str) -> tuple[int, dict]:
        """Answer a platform probe: no auth, no data, a real answer either way.

        `/healthz` never fails while the process is running, which is what a
        restart policy needs. `/readyz` fails when the working database is
        missing or has no schema, so a platform stops sending traffic to a
        process that cannot answer a request -- and the reason is named in a
        fixed vocabulary rather than by its output.
        """
        body = {"ok": True, "probe": path.lstrip("/")}
        if path == "/healthz":
            return 200, body
        problems = []
        try:
            store = _active_store()
        except NameError:  # pragma: no cover - the board always binds one
            store = None
        db_path = os.environ.get("WEBLEDGER_DB", "")
        if store is None:
            problems.append("store_not_bound")
        else:
            db_path = str(getattr(store, "path", db_path))
            try:
                conn = store.conn
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            except Exception:  # noqa: BLE001 - an unusable store is not ready
                tables = set()
                problems.append("database_unreadable")
            for required in ("board_rows", "trip_tabs"):
                if required not in tables:
                    problems.append(f"missing_table:{required}")
        body["ok"] = not problems
        if problems:
            body["problems"] = sorted(problems)
        return (200 if body["ok"] else 503), body

    def _cookies(self):
        """The request's cookies, parsed once per request.

        `BaseHTTPRequestHandler.headers` is an `email.message.Message`, which
        keeps repeated headers, so a second `Cookie` line is appended rather
        than replacing the first. A client can send two, and reading only the
        first would let it hide a cookie from the check.
        """
        jar = http.cookies.SimpleCookie()
        try:
            for raw in self.headers.get_all("Cookie") or []:
                jar.load(raw)
        except (AttributeError, http.cookies.CookieError):
            return {}
        return jar

    def _oidc_flow(self):
        """The connected Google flow, or None when the deployment has none."""
        return _OIDC

    def _auth_redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        # A redirect that carries a session must never be cached.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _auth_page(self, title: str, body: str, code: int = 200,
                   refusal: str = "") -> None:
        # The refusal code is rendered as a data attribute so a support answer
        # can name it without reading the server log, and so a route can be
        # checked for the specific refusal it is meant to produce.
        marker = f'<p data-refusal="{refusal}"></p>' if refusal else ""
        from . import social_preview
        data = (f"<!doctype html><html lang='ko'><head><meta charset=utf-8><title>{title}</title>"
                f"{social_preview.META}</head><body>{marker}{body}</body></html>").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _auth_routes(self, query) -> bool:
        """`/auth/login`, `/auth/callback` and `/access/logout`.

        A deployment with no Google configuration answers 503 on the login
        routes rather than redirecting somewhere. Silently sending an operator
        to a page that cannot log in looks like a working login flow.
        """
        from . import google_oidc
        from .google_oidc import OIDCError

        path = urlparse(self.path).path
        flow = self._oidc_flow()

        if path == "/auth/login":
            if flow is None:
                self._auth_page(
                    "로그인 설정 없음",
                    "<p>Google 로그인이 연결되어 있지 않아요. "
                    "배포 환경 설정을 먼저 확인해 주세요.</p>", code=503,
                   refusal="OIDC_NOT_CONFIGURED")
                return True
            try:
                from . import card_flow
                default_return = "/" if card_flow.enabled() else "/board"
                started = flow.authorization_url(
                    return_to=(query.get("return_to", [default_return])[0] or default_return))
            except OIDCError as exc:
                self._auth_page("로그인 불가", f"<p>{exc.message}</p>",
                                code=exc.status, refusal=exc.code)
                return True
            self._auth_redirect(started["url"])
            return True

        if path == "/auth/callback":
            if flow is None:
                self._auth_page("로그인 설정 없음",
                                "<p>Google 로그인이 연결되어 있지 않아요.</p>",
                                code=503, refusal="OIDC_NOT_CONFIGURED")
                return True
            error = (query.get("error", [""])[0] or "")
            if error:
                # Google refused, or the user declined. The description may name
                # the reason; it never names an account.
                self._auth_page("로그인 취소",
                                f"<p>로그인이 완료되지 않았어요 ({error}).</p>",
                                code=400, refusal=error)
                return True
            try:
                completed = flow.complete(
                    code=(query.get("code", [""])[0] or ""),
                    state=(query.get("state", [""])[0] or ""))
            except OIDCError as exc:
                self._auth_page("로그인 실패", f"<p>{exc.message}</p>",
                                code=exc.status, refusal=exc.code)
                return True
            self._auth_redirect(completed["return_to"],
                                cookie=flow.set_cookie(completed["cookie_value"]))
            return True

        if path == "/access/logout" and self.command == "GET":
            # Ending a session must also remove the cookie, or the browser
            # keeps presenting it. The generation moves on the POST route; the
            # GET is here so a plain link can end a session too, and it clears
            # the cookie regardless of whether a store is bound.
            cookie = (flow.clear_cookie() if flow is not None
                      else google_oidc.clear_cookie_header())
            self._auth_redirect("/board?msg=" + urlencode({"msg": "로그아웃"}),
                                cookie=cookie)
            return True

        if path == "/auth/state":
            # Presence only: whether a login is connected and whether the
            # bootstrap window is open. No sub value is exposed here; an
            # operator learns their own sub from authenticated /access/me.
            state = google_oidc.connection_state(flow, _ACCESS)
            self._send_json(state)
            return True

        return False

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(body)

    def _refuse_amount(self, is_form: bool, payload: dict,
                         row_id: str = "") -> None:
        if is_form:
            self._send_form_error("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요",
                                  payload, str(payload.get("return_to") or ""),
                                  row_id)
            return
        self._send_json({"code": "INVALID_VALUE", "field": "amount_krw",
                         "message": "금액은 정수 원화로 입력해 주세요"}, code=422)

    def _send_form_error(self, code: str, message: str, payload: dict,
                         return_to: str, row_id: str = "") -> None:
        """Answer a refused plain form post with the screen, in HTML.

        The typed values are rendered back into the form, escaped, and the
        answer carries the refusal status. Nothing typed is put in a URL, a
        referrer or a log. The JSON contract is untouched: only a form post
        without the JSON content type reaches this method.
        """
        from . import ledger_design

        target = local_path(return_to) or "/board"
        parts = urlsplit(target)
        query = parse_qs(parts.query)
        row_id = row_id or ""
        tab = query.get("tab", [""])[0] or ""
        if row_id and not tab:
            _kind, found = find_row(row_id)
            if found is not None:
                tab = found.get("display_tab_id") or ""
        if tab not in ("unclassified", "refunds") and tab not in valid_tab_ids():
            # The row's own trip is gone, or the URL asked for one that never
            # existed. Fall back to a trip that does, and to 분류대기 when the
            # store has none, rather than to a hard-coded example id.
            tab = default_board_tab()
        draft = {}
        if row_id and payload:
            kind, current = find_row(row_id)
            if current is not None:
                allowed, _fixed = editable_fields(
                    kind, current.get("source_kind", ""),
                    bool(current.get("is_allocation")))
                for key, value in payload.items():
                    if key not in allowed:
                        continue
                    if value is None or isinstance(value, (str, int, float)):
                        draft[key] = "" if value is None else str(value)
        fragment = ledger_design.page(
            tab, query.get("q", [""])[0], query.get("kind", [""])[0],
            row_id, error=f"{code}: {message}",
            archived=query.get("arch", [""])[0], draft=draft, back=target)
        body = ledger_design.render(fragment).encode("utf-8")
        self.send_response(STATUS_FOR_CODE.get(code, 422))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, value: dict, code: int = 200,
                   extra_headers: dict | None = None) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # Default no-store, so a ledger answer cannot be served from a cache. A
        # caller may still override it, and the health probes do not need to
        # change: a liveness answer holds no ledger data either way.
        self.send_header("Cache-Control", "no-store")
        for header_name, header_value in (extra_headers or {}).items():
            self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------- Phase 7 access
    def _phase7_refuse(self, exc) -> None:
        """Answer a refusal without leaking what the caller may not see.

        A permission boundary is 404 so a caller cannot map what exists. A
        refusal about the caller's own application keeps its own status,
        because that says nothing about anyone else's trip or evidence.

        An unexpected exception is *not* dressed as a 404. A 404 here means "you
        may not see this", so reporting a programming fault that way hides the
        fault and tells the caller something untrue. It becomes a 500 with a
        fixed message and no detail, and the exception type goes to the log so
        the fault is findable.
        """
        from . import access_control

        if isinstance(exc, access_control.AccessError):
            if exc.status == 404:
                self._send("없음", code=404)
                return
            if (exc.code == access_control.AUTH_REQUIRED and exc.status == 401
                    and getattr(self, "command", "") == "GET"):
                try:
                    req_path = urlparse(self.path).path
                except Exception:  # noqa: BLE001 - a bad target stays JSON
                    req_path = ""
                if req_path in ("/", "/board", "/review", "/import"):
                    try:
                        accept = self.headers.get("Accept") or ""
                    except Exception:  # noqa: BLE001 - no header stays JSON
                        accept = ""
                    accept_lower = str(accept).lower()
                    wants_json = ("application/json" in accept_lower
                                  and "text/html" not in accept_lower)
                    if not wants_json:
                        if self._oidc_flow() is None:
                            login_body = _login_entry_body(False)
                        else:
                            login_body = _login_entry_body(True)
                        self._auth_page("웹 장부", login_body, code=401,
                                        refusal="AUTH_REQUIRED")
                        return
            self._send_json({"code": exc.code, "message": exc.message},
                            code=exc.status)
            return
        import sys
        import traceback

        print(f"UNEXPECTED {type(exc).__name__} in a board handler: {exc!r}",
              file=sys.stderr)
        traceback.print_exc()
        self._send_json(
            {"code": "INTERNAL_ERROR",
             "message": "요청을 처리하지 못했어요. 같은 요청으로 다시 확인해 주세요",
             "retry_same_client_request_id": True}, code=500)

    def _phase7_get(self, parsed, query) -> bool:
        """Server-side read decision for this request.

        SPEC 15.3: the session and the role are checked on the server for every
        read. A viewer gets its own trip list, and any trip it may not read
        answers 404 rather than 403.

        The return value says whether the request has been answered here.
        `True` means this function wrote the whole response; `False` means it
        deliberately wrote nothing so `do_GET` should go on to the owner's own
        rendering. There is no third case: every route below either answers or
        raises, and a raise is turned into a refusal by `_phase7_refuse`.

        Why it has to be returned rather than left to the caller: an answer written
        here used to fall through into the owner's rendering in `do_GET`, and a
        second response went out on the same connection. A viewer's `/board` then
        carried an owner `live-config`, with an owner token, as a second body. The
        first response is what a normal client reads, so the leak was invisible
        except over a raw socket.
        """
        from . import access_control

        session = require_session(self.headers, self._cookies())
        path = parsed.path

        # The access screens answer for both roles.
        if path == "/access/me":
            self._send_json(access_control_render_viewer_status(session, _ACCESS))
            return True
        if path == "/access/admin":
            if not is_owner_session(session):
                # the account management screen is an owner action
                deny_for_viewer(action=True)
            self._send(access_control_render_owner_admin(session, _ACCESS))
            return True
        if path == "/access/providers":
            if not is_owner_session(session):
                # configuring a provider key is an owner action
                deny_for_viewer(action=True)
            if _PROVIDER_CONFIG is None:
                self._send_json(
                    {"code": "PROVIDER_CONFIG_UNBOUND",
                     "message": "제공자 설정이 연결되지 않았어요"}, code=503)
                return True
            self._send(access_control_render_provider_config(
                session, _PROVIDER_CONFIG.public_status()))
            return True
        if path in ("/reserve-links", "/api/reserve-link/plan",
                    "/api/reserve-link/state"):
            # Owner-only, like the review screen it feeds. A viewer learns neither
            # the source roster nor the link set.
            if not is_owner_session(session):
                deny_for_viewer(action=True)
            self._reserve_link_response(path)
            return True
        if path == "/api/review/apply/plan":
            # A plan is a read, but it is a read of the owner's choices against
            # the real source, so it sits behind the same owner gate as the
            # comparison itself rather than being published to a viewer.
            if not is_owner_session(session):
                deny_for_viewer(action=True)
            self._send_json(self._review_apply_plan())
            return True
        if path in ("/review", "/api/review/model", "/api/review/guidance"):
            if not is_owner_session(session):
                # The comparison is over the actual source and every card
                # candidate. It is an owner action, so the refusal is about the
                # action and not about whether a particular row exists.
                deny_for_viewer(action=True)
            from . import card_flow
            if path=='/review' and card_flow.enabled():
                return False
            if self._handle_review_get(path, query):
                return True
            return False
        if path == "/api/live/state":
            # SPEC 15.3: the session and the role are decided on the server for
            # every poll, exactly as for a page load. A poll is a read, so a
            # trip the caller may not read answers 404 rather than 403, and the
            # token is computed only over the trips this caller may read.
            self._live_sync_state(session, query)
            return True
        if path == "/access/rows":
            tab = query.get("tab", [""])[0]
            if not tab:
                deny_for_viewer()
            # An owner keeps the full board; a viewer only its own trips.
            if not is_owner_session(session):
                _ACCESS.require_view_tab(session.user_id, tab)
            rows = (_active_store().list_tab_rows(tab) if _active_store() is not None else [])
            allowed = (viewer_visible_tabs(session) if not is_owner_session(session)
                       else {r["display_tab_id"] for r in rows})
            projected = access_control.project_rows_for_viewer(
                rows, allowed, tab)
            if not is_owner_session(session):
                for item in projected:
                    access_control.assert_no_denied_fields(item)
            income = sum(r["amount_krw"] for r in projected
                         if r["row_kind"] == "income")
            expense = sum(r["amount_krw"] for r in projected
                          if r["row_kind"] != "income")
            self._send_json({"tab": tab, "rows": projected,
                             "totals": {"income_krw": income,
                                        "expense_krw": expense,
                                        "balance_krw": income - expense},
                             "row_count": len(projected)})
            return True
        if path.startswith("/evidence/preview/"):
            evidence_id = path.rsplit("/", 1)[-1]
            try:
                preview = _ACCESS.evidence_preview(user_id=session.user_id,
                                                  evidence_id=evidence_id)
            except access_control.AccessError:
                deny_for_viewer()
            self._send_json(preview)
            return True
        if path.startswith("/evidence/original/"):
            # There is no original-evidence route for anyone on the board.
            deny_for_viewer()

        if is_owner_session(session):
            # An owner keeps every existing screen unchanged. `False` means this
            # path deliberately answered nothing, so `do_GET` carries on to the
            # owner's own rendering. Saying `True` here would be the bug in reverse:
            # the owner would get a blank 200 instead of the board.
            return False
        if any(path == p or path.startswith(p + "/")
               for p in access_control.OWNER_ONLY_PATHS):
            # /export, /import, /trips, /rules, xlsx job lookup and download are
            # owner actions, so the refusal is about the action, not about any
            # row or trip the caller may not see.
            deny_for_viewer(action=True)
        if path in ("/", "/board"):
            tab = query.get("tab", [""])[0]
            if tab:
                _ACCESS.require_view_tab(session.user_id, tab)
            self._send(access_control_render_viewer_board(session, _ACCESS, tab))
            return True
        if path == "/row":
            row_id = query.get("id", [""])[0]
            kind, row = find_row(row_id)
            if row is None:
                deny_for_viewer()
            _ACCESS.require_view_tab(session.user_id,
                                     row.get("display_tab_id") or "")
            projected = access_control.project_row_for_viewer(
                row, viewer_visible_tabs(session))
            if projected is None:
                deny_for_viewer()
            self._send(access_control_render_viewer_row(session, projected))
            return True
        if path.startswith("/income/"):
            source_id = parts_value(path)
            row = _active_store().get_row(source_id) if _active_store() is not None else None
            if row is None:
                deny_for_viewer()
            _ACCESS.require_view_tab(session.user_id,
                                     row.get("display_tab_id") or "")
            self._send(access_control_render_viewer_income(session, row))
            return True
        deny_for_viewer()

    def _live_sync_state(self, session, query) -> None:
        """The cross-screen change check, decided on the server every time.

        Two answers. A `?token=` poll gets JSON with the current token and
        whether it moved. An `X-Part: live-state` request gets the page
        fragments, and only the caller's own: the owner sees its own board, a
        viewer sees the trips its allowlist names and nothing else.

        Both are `no-store`. A cached poll would make a screen report a stale
        ledger as current, which is the one thing a change check must not do.
        """
        from . import live_sync

        tab = query.get("tab", [""])[0]
        q = query.get("q", [""])[0]
        kind = query.get("kind", [""])[0]
        arch = query.get("arch", [""])[0]
        row_id = query.get("row", [""])[0]
        presented = query.get("token", [""])[0]
        # No access store bound means the single-operator server, where this
        # request is already the owner's own read.
        owner = session is None or is_owner_session(session)
        if owner:
            token = live_sync.owner_token(_active_store(), tab)
        else:
            allowed = viewer_visible_tabs(session)
            if tab:
                # A trip the caller may not read is 404, the same answer the page
                # load gives, so polling cannot be used to map what exists.
                _ACCESS.require_view_tab(session.user_id, tab)
            token = live_sync.viewer_token(_active_store(), allowed)
        wants_fragments = (self.headers.get("X-Part") or "") == "live-state"
        if wants_fragments:
            if owner:
                body = live_sync.owner_fragments(
                    _active_store(), tab, q, kind, row_id, arch)
            else:
                body = live_sync.viewer_fragments(
                    session, _ACCESS, _active_store(), tab)
            self._send(body)
            return
        self._send_json(
            {"tab": tab, "token": token,
             "changed": live_sync.tokens_differ(presented, token),
             "role": "owner" if owner else "viewer",
             "poll_interval_ms": live_sync.POLL_INTERVAL_MS},
            extra_headers={"Cache-Control": "no-store"})

    def _phase7_write(self, parsed, content_type: str, raw: bytes) -> bool:
        """Server-side write decision, taken before the body is dispatched.

        Returns True when the request was fully handled here. The session and
        the role come from the server; the user id in a body is never trusted
        (SPEC 16.1, 16.4).
        """
        from . import access_control

        session = require_session(self.headers, self._cookies())
        path = parsed.path
        # These endpoints own raw file bytes, not JSON or form data. Check
        # capability before dispatch; their upload handlers still enforce CSRF.
        if path in ('/api/receipts/image', '/api/imports'):
            if not is_owner_session(session):
                deny_for_viewer(action=True)
            return False
        payload = self._phase7_payload(content_type, raw)
        store = _ACCESS

        if path == "/access/applications":
            action = str(payload.get("action") or "create")
            request_id = str(payload.get("client_request_id") or "")
            if action == "create":
                result = store.create_application(
                    user_id=session.user_id,
                    requested_name=str(payload.get("requested_name") or ""),
                    nickname=str(payload.get("nickname") or ""),
                    description=str(payload.get("description") or ""),
                    client_request_id=request_id)
            elif action in ("update", "withdraw"):
                if action == "withdraw":
                    result = store.withdraw_application(
                        application_id=str(payload.get("application_id") or ""),
                        user_id=session.user_id,
                        expected_revision=int(payload.get("expected_revision") or 0),
                        client_request_id=request_id)
                else:
                    result = store.update_application(
                        application_id=str(payload.get("application_id") or ""),
                        user_id=session.user_id,
                        expected_revision=int(payload.get("expected_revision") or 0),
                        requested_name=payload.get("requested_name"),
                        nickname=payload.get("nickname"),
                        description=payload.get("description"),
                        client_request_id=request_id)
            else:
                raise access_control.AccessError("INVALID_VALUE", "알 수 없는 동작이에요",
                                                 status=422)
            self._send_json({"result": result,
                             "role": store.account_role(session.user_id),
                             "visible_tabs": sorted(
                                 store.visible_tabs(session.user_id))})
            return True

        if path == "/access/logout":
            # Ending a session is the server side of the contract in SPEC 15.3:
            # the generation moves, so the client can drop its cached ledger
            # data and any session it still holds is refused.
            generation = _ACCESS.bump_session_generation(session.user_id)
            # The cookie is removed as well. A logout that only moved the
            # generation would leave the browser holding a cookie that is stale
            # but still present, so the next visit would present it and be
            # refused with SESSION_STALE rather than being asked to log in.
            from . import google_oidc

            flow = self._oidc_flow()
            clear = (flow.clear_cookie() if flow is not None
                     else google_oidc.clear_cookie_header())
            self._send_json({
                "logged_out": True,
                "user_id": session.user_id,
                "session_generation": generation,
                "cache_namespace": session.cache_namespace(),
                "cookie_cleared": True,
                "client_must_clear": ["selected_row", "cached_ledger_data",
                                      "cached_evidence"],
            }, extra_headers={"Set-Cookie": clear})
            return True

        if path == "/access/providers":
            if not is_owner_session(session):
                # registering or clearing a provider key is an owner action
                deny_for_viewer(action=True)
            if _PROVIDER_CONFIG is None:
                self._send_json(
                    {"code": "PROVIDER_CONFIG_UNBOUND",
                     "message": "제공자 설정이 연결되지 않았어요"}, code=503)
                return True
            from .provider_config import ConfigError

            action = str(payload.get("action") or "")
            request_id = str(payload.get("client_request_id") or "")
            # The role comes from the access store, never from the body and
            # never from an attribute the session happens to carry.
            role = "owner" if is_owner_session(session) else "viewer"
            # A provider name is checked against the allowlist by the service,
            # not taken from the body as a free string. The key value arrives
            # here and is handed straight to the store; it is never echoed,
            # never logged, and never stored in the ledger.
            try:
                if action == "clear":
                    status = _PROVIDER_CONFIG.clear_provider(
                        role=role, provider=str(payload.get("provider") or ""),
                        client_request_id=request_id)
                elif action == "fallback":
                    raw = payload.get("enabled")
                    if isinstance(raw, str):
                        raw = raw.strip().lower() in ("1", "true", "on", "yes")
                    status = _PROVIDER_CONFIG.set_fallback(
                        role=role, enabled=bool(raw),
                        client_request_id=request_id)
                elif action == "refresh-models":
                    provider_name = str(payload.get("provider") or "")
                    status = _PROVIDER_CONFIG.refresh_model_catalog(
                        role=role, provider=provider_name,
                        transport=_transport_for(provider_name),
                        fetched_at=str(payload.get("fetched_at") or ""))
                elif action == "connection-test":
                    result = _PROVIDER_CONFIG.run_connection_test(
                        role=role, provider=str(payload.get("provider") or ""),
                        muse=_MUSE, gemini=_GEMINI)
                    self._send_json(result)
                    return True
                elif action == "record-tier":
                    status = _PROVIDER_CONFIG.record_tier_verification(
                        role=role, tier=str(payload.get("tier") or ""),
                        verified_at=str(payload.get("verified_at") or ""),
                        client_request_id=request_id)
                else:
                    status = _PROVIDER_CONFIG.set_provider(
                        role=role,
                        provider=str(payload.get("provider") or ""),
                        secret=payload.get("secret"),
                        model=payload.get("model"),
                        timeout=payload.get("timeout"),
                        client_request_id=request_id)
            except ConfigError as exc:
                self._send_json({"code": exc.code, "message": str(exc)},
                                code=STATUS_FOR_CODE.get(exc.code, 422))
                return True
            # A new key has to reach the adapter before the next turn uses it,
            # so the wiring is rebuilt here rather than at the next restart.
            # With autowire off this is a no-op and an injected adapter stays.
            _rebuild_provider_adapters()
            self._send_json(status)
            return True

        if path == "/access/decision":
            if not is_owner_session(session):
                # approving or rejecting is an owner action
                deny_for_viewer(action=True)
            action = str(payload.get("action") or "")
            request_id = str(payload.get("client_request_id") or "")
            application_id = str(payload.get("application_id") or "")
            expected = int(payload.get("expected_revision") or 0)
            if action == "approve":
                result = store.approve_application(
                    application_id=application_id, owner_id=session.user_id,
                    expected_revision=expected,
                    reservation_person_id=str(
                        payload.get("reservation_person_id") or ""),
                    client_request_id=request_id)
            elif action == "reject":
                result = store.reject_application(
                    application_id=application_id, owner_id=session.user_id,
                    expected_revision=expected,
                    reason=str(payload.get("reason") or ""),
                    client_request_id=request_id)
            elif action == "revoke":
                result = store.revoke_connection(
                    connection_id=str(payload.get("connection_id") or ""),
                    owner_id=session.user_id, expected_revision=expected,
                    client_request_id=request_id)
            else:
                raise access_control.AccessError("INVALID_VALUE", "알 수 없는 동작이에요",
                                                 status=422)
            self._send_json({"result": result})
            return True

        if path == "/access/assignments":
            # The reservation snapshot is applied by the sync, not by a
            # browser request. Pushing one is an owner action.
            if not is_owner_session(session):
                deny_for_viewer(action=True)
            result = store.apply_assignment_snapshot(
                user_id=str(payload.get("user_id") or ""),
                items=list(payload.get("items") or []),
                source_version=str(payload.get("source_version") or ""),
                complete=bool(payload.get("complete", True)),
                snapshot_revision=payload.get("snapshot_revision"))
            self._send_json({"result": result})
            return True

        if path in ("/api/review/decisions", "/api/review/export",
                    "/api/review/apply", "/api/reserve-link/links",
                    "/api/reserve-link/apply", "/api/review/guidance/save",
                    "/api/review/guidance/rule-preview", "/api/review/guidance/rule-apply"):
            if not is_owner_session(session):
                # Saving a decision is an owner action. A viewer never reaches
                # the body, so the decision cannot be written on their behalf.
                # Applying them is further along still, and is on the same gate.
                deny_for_viewer(action=True)
            if "application/json" not in (content_type or ""):
                self._send_json({"code": "CONTENT_TYPE_MISMATCH",
                                 "message": "JSON으로만 보낼 수 있어요"},
                                code=415)
                return True
            if not self._review_write_guards(payload):
                return True
            if path == "/api/review/apply":
                self._handle_review_apply(payload)
                return True
            if path in ("/api/reserve-link/links", "/api/reserve-link/apply"):
                self._reserve_link_write(path, payload)
                return True
            if path.startswith("/api/review/guidance/"):
                return self._handle_review_guidance(path, payload)
            return self._handle_review_post(path, payload)

        if is_owner_session(session):
            return False
        # Every other write is an owner capability: row saves, moves, the rule
        # dialogue, xlsx creation, job lookup, trip meta and imports. The
        # refusal is decided before the body reaches a handler, so it never
        # depends on whether the named resource exists.
        deny_for_viewer(action=True)

    def _review_leads_here(self) -> bool:
        """Should a bare `/` or `/board` open the review instead of the board?

        Three things have to be true, and all three are about the data rather
        than about the request: a review has to be configured, the operational
        board has to be empty, and the configured source has to still be exactly
        what its manifest bound. The first is cheap to refuse, the second is the
        user's actual situation, and the third is what stops a changed source from
        sending someone to a page that will only refuse.
        """
        from . import real_review

        service = self._review_service()
        if service is None:
            return False
        try:
            if not service.is_available():
                return False
        except Exception:
            return False
        if live_trips():
            return False
        return not (_expense_rows() or _income_rows())

    # ------------------------------------------------- the review routes
    def _review_service(self):
        from . import real_review

        return real_review.active_service()

    def _review_config_error(self) -> str:
        from . import real_review

        return real_review.config_error()

    def _review_refuse(self, code: str, status: int = 409) -> None:
        from . import real_review

        self._send_json({"code": code, "message": _REVIEW_MESSAGES.get(
            code, "실제 자료 검토를 진행할 수 없어요")}, code=status)

    def _handle_review_get(self, path: str, query: dict) -> bool:
        """`/review` and `/api/review/model`, for an owner, answered here.

        The role has already been decided by `_phase7_get` before this is
        called. A refusal is answered with a fixed code and no path, no value and
        no file content, because this route reads real source data.
        """
        if path == "/api/review/guidance":
            return self._handle_review_guidance(path, {
                "ref": query.get("ref", [""])[0],
                "binding": query.get("binding", [""])[0],
            })
        from . import real_review
        from . import real_review_ui

        service = self._review_service()
        if service is None:
            # Not configured, or configured with something unusable. Either way the
            # feature is unavailable and it never falls back to anything that could
            # be mistaken for real data. A manifest that was set but refused is
            # named as such, because "not set" and "set and broken" are different
            # things for whoever is looking at it.
            if path == "/api/review/model":
                self._review_refuse(self._review_config_error()
                                    or real_review.CODE_UNAVAILABLE, 503)
            else:
                self._send(_REVIEW_UNCONFIGURED_PAGE, code=503)
            return True
        try:
            if path == "/api/review/model":
                # `?state_only=1` is the two-second poll: the binding, the revision
                # and the counts, with no source rows and no choices. The full
                # comparison is read on load and when that revision moves.
                wanted = (query.get("state_only", [""])[0] or "").strip()
                if wanted not in ("", "0"):
                    if wanted != "1":
                        self._review_refuse("INVALID_ARGUMENT", 400)
                        return True
                    self._send_json(service.state_only_payload())
                else:
                    self._send_json(service.model_payload())
            else:
                self._send(real_review_ui.render_real_review_ui(CSRF_TOKEN))
        except real_review.RealReviewError as exc:
            if path == "/api/review/model":
                self._review_refuse(exc.code, 503)
            else:
                self._send(_REVIEW_UNCONFIGURED_PAGE, code=503)
        except Exception:
            if path == "/api/review/model":
                self._review_refuse(real_review.CODE_INTERNAL, 500)
            else:
                self._send(_REVIEW_UNCONFIGURED_PAGE, code=503)
        return True

    def _review_allowed_origin(self) -> set:
        """The origins a review write may come from, and no others.

        A configured `WEBLEDGER_PUBLIC_BASE_URL` is the whole answer: the write
        must come from exactly that origin. The request's own `Host` is not used
        as an alternative, because a Host header is chosen by whoever is making the
        request, and accepting `http://` of it as well as `https://` would accept
        a downgrade the published app never offers.

        With nothing configured the origin is this server's own address, built
        from the socket it is listening on rather than from a header. That is what
        a local synthetic run uses, and it is the only case that can reach a
        review at all.
        """
        configured = os.environ.get(_REVIEW_PUBLIC_BASE_URL_ENV, "").strip()
        if configured:
            parts = urlsplit(configured if "//" in configured
                             else "https://" + configured)
            origin = f"{parts.scheme}://{parts.netloc}"
            return {origin.rstrip("/")}
        host, port = self.server.server_address[0], self.server.server_address[1]
        return {f"http://{host}:{port}"}

    def _review_write_guards(self, payload: dict) -> bool:
        """Origin and CSRF for a review write. False means already refused.

        The Origin has to be one this server will accept, and only that: a
        cross-site form or fetch sends the attacker's origin, so this is what stops
        a page elsewhere from saving a decision into someone's review.

        The CSRF token is the board's existing one and is compared with `!=`,
        exactly as every other write on this server does. Requiring both is not
        redundant: the Origin check is a header a browser controls, and the token
        is one a cross-site reader cannot read.
        """
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if not origin:
            self._review_refuse("ORIGIN_REQUIRED", 403)
            return False
        if origin not in self._review_allowed_origin():
            self._review_refuse("ORIGIN_MISMATCH", 403)
            return False
        token = payload.get("csrf") or self.headers.get("X-CSRF-Token") or ""
        if token != CSRF_TOKEN:
            self._review_refuse("CSRF_REQUIRED", 403)
            return False
        return True

    # -- explicit reservation-to-ledger links ---------------------------
    def _reserve_link_payload(self) -> dict:
        """Everything the owner screen shows, in one payload.

        Three states, and they are different states rather than one with empty
        fields: no configuration, a configured source, and a configured source the
        ledger has no events for yet. Pending input is never filled in with example
        data — an owner looking at placeholder rows cannot tell them from real
        ones.
        """
        from . import reserve_link

        config = reserve_link.load_source_config()
        if not config.get("configured"):
            return {"configured": False, "code": config.get("code", ""),
                    "choices": reserve_link.ledger_event_choices(self._reserve_store()),
                    "counts": {"choices": len(
                        reserve_link.ledger_event_choices(
                            self._reserve_store()))}}
        store = self._reserve_store()
        try:
            snapshot = reserve_link.read_source(config)
        except reserve_link.ReserveLinkError as exc:
            # The configuration exists but the file no longer answers to it. The
            # screen says so and shows nothing else, rather than a stale roster.
            return {"configured": True, "readable": False, "code": exc.code,
                    "choices": reserve_link.ledger_event_choices(store),
                    "counts": {"choices": len(
                        reserve_link.ledger_event_choices(store))}}
        plan = reserve_link.build_plan(store, snapshot)
        return {
            "configured": True,
            "readable": True,
            "binding": plan["binding"],
            "link_version": plan["link_version"],
            "link_revision": plan["link_revision"],
            "link_digest": plan["link_digest"],
            "apply_digest": plan["apply_digest"],
            "applicable": plan["applicable"],
            "refusal_code": plan.get("refusal_code", ""),
            "counts": plan["counts"],
            "per_identifier": plan["per_identifier"],
            "unlinked": plan["unlinked"],
            "persons": [{"reservation_person_id": item["reservation_person_id"],
                         "display_name": item["display_name"],
                         "is_active": item["is_active"],
                         "assignments": item["assignments"],
                         "connected": len(item["connected"])}
                        for item in plan["persons"]],
            "choices": reserve_link.ledger_event_choices(store),
        }

    def _reserve_store(self):
        """The access store these links live in.

        The links are access records, so they belong to `_ACCESS` — the store the
        server is enforcing with — and not to the ledger store, which does not know
        what a reservation identifier is.
        """
        return _ACCESS if _ACCESS is not None else None

    def _reserve_link_response(self, path: str) -> None:
        from . import reserve_link

        if path == "/reserve-links":
            from . import reserve_link_ui
            # Nothing is interpolated into the document: the screen fetches the
            # payload over the authenticated route, so a copy of this HTML carries
            # no source identifier and no person.
            self._send(reserve_link_ui.render_reserve_link_ui(CSRF_TOKEN))
            return
        payload = self._reserve_link_payload()
        if path == "/api/reserve-link/state":
            payload = {"configured": payload.get("configured", False),
                       "link_revision": payload.get("link_revision", 0),
                       "link_version": payload.get("link_version", 0),
                       "link_digest": payload.get("link_digest", ""),
                       "binding": payload.get("binding"),
                       "counts": payload.get("counts", {})}
        self._send_json(payload)

    def _reserve_owner_id(self) -> str:
        """The account id of the owner whose session just passed the gate.

        `current_session` is the same resolution the gate itself used, so this
        cannot disagree with it: if the gate let the request through, this is that
        owner, and it is read-only.
        """
        try:
            resolved = current_session(self.headers, self._cookies())
        except Exception:
            return ""
        return getattr(resolved, "user_id", "") or ""

    def _reserve_link_write(self, path: str, payload: dict) -> None:
        """Save links, or run the apply. Both owner-only, both CSRF-checked."""
        from . import access_control, ledger_apply, real_review, reserve_link

        store = self._reserve_store()
        if store is None:
            self._review_refuse("STORE_UNBOUND", 503)
            return
        config = reserve_link.load_source_config()
        if not config.get("configured"):
            self._review_refuse(reserve_link.CODE_CONFIG_REQUIRED, 409)
            return
        try:
            snapshot = reserve_link.read_source(config)
        except reserve_link.ReserveLinkError as exc:
            self._review_refuse(exc.code, 409)
            return
        # The owner is already proven by the gate the caller passed. This asks the
        # access store for the account id behind that same decision rather than
        # re-deciding it, so a link can never be attributed to somebody the server
        # has not just identified.
        owner_id = self._reserve_owner_id()
        if not owner_id:
            self._review_refuse(real_review.CODE_UNAVAILABLE, 403)
            return
        try:
            if path == "/api/reserve-link/links":
                result = reserve_link.save_links(store, snapshot, payload,
                                                 owner_id=owner_id)
            else:
                result = reserve_link.apply_plan(
                    store, snapshot,
                    request_id=payload.get("request_id"),
                    presented_binding=payload.get("source_binding"),
                    presented_link_revision=payload.get("link_revision"),
                    presented_apply_digest=payload.get("apply_digest"),
                    owner_id=owner_id)
        except reserve_link.ReserveLinkError as exc:
            # A malformed request is the caller's to fix (400); a stale one is a
            # conflict the caller resolves by re-reading (409). Both are refusals,
            # but they ask different things of the person holding the screen.
            if exc.code in (reserve_link.CODE_APPLY_TARGET_UNAVAILABLE,
                            reserve_link.CODE_APPLY_TARGET_DELETED,
                            reserve_link.CODE_APPLY_TARGET_MISSING,
                            reserve_link.CODE_FIELD_INVALID,
                            reserve_link.CODE_FIELD_MISSING,
                            reserve_link.CODE_IDENTIFIER_NOT_IN_SOURCE,
                            reserve_link.CODE_TARGET_NOT_FOUND,
                            reserve_link.CODE_TARGET_DELETED,
                            reserve_link.CODE_DUPLICATE_TARGET,
                            reserve_link.CODE_SOURCE_HASH_MISMATCH,
                            reserve_link.CODE_SOURCE_UNREADABLE):
                self._review_refuse(exc.code, 400)
                return
            self._review_refuse(exc.code, 409)
            return
        except (real_review.RealReviewError, access_control.AccessError) as exc:
            # Both carry a fixed code and a status. `save_links` reports a stale
            # source or a link set another device changed by raising `AccessError`,
            # and it was landing on the generic handler below — a 500, which told
            # the caller the product had broken, gave the screen no code to show,
            # and read as "try again" when the real answer is "re-read and decide".
            # The code and status are carried through unchanged, so nothing about
            # the refusal itself is restated here.
            self._review_refuse(exc.code, exc.status or 409)
            return
        except Exception as exc:
            from .ledger_store import SaveError

            if isinstance(exc, SaveError):
                self._review_refuse(exc.code, 409)
                return
            self._review_refuse("REVIEW_INTERNAL_ERROR", 500)
            return
        self._send_json(result)

    def _review_apply_plan(self) -> dict:
        """The owner's plan, or a refusal in a fixed code.

        Nothing is written here. Building the plan reads the stored bundle and the
        stored choices, so what the owner is shown is exactly what an apply would
        use — and an unsaved choice on the screen is not part of it.
        """
        from . import ledger_apply

        service = self._review_service()
        store = _active_store()
        if service is None:
            return {"code": self._review_config_error() or "REVIEW_UNAVAILABLE",
                    "counts": {}}
        try:
            plan = ledger_apply.build_apply_plan(service, store)
        except ledger_apply.ApplyPlanError as exc:
            self._review_refuse(exc.code, 400)
            return {}
        # The facts themselves are not echoed. The owner is told the counts, the
        # binding they were made against and the per-ref codes, which is what a
        # decision needs; the seventeen columns stay on disk where they came from.
        return {
            "binding": plan["binding"],
            "choices_revision": plan["choices_revision"],
            "snapshot_sha256": plan["snapshot_sha256"],
            "plan_digest": plan["plan_digest"],
            # The counts say which of two units each one is counting. The owner is
            # looking at review rows on screen and card transactions in the
            # ledger, and adding the two together would be a number about
            # nothing.
            "counts": plan["counts"],
            "units": plan["units"],
            "held_refs": plan["held_refs"],
            "conflicts": plan["conflicts"],
            "already_applied": plan["already_applied"],
            "transactions": [{"ref": item["ref"],
                              "source_event_key": item["chosen_candidate_key"],
                              "fact_digest": item["fact_digest"]}
                             for item in plan["transactions"]],
        }

    def _handle_review_apply(self, payload: dict) -> None:
        """Run the plan, once, after checking everything it depends on.

        Owner-only, CSRF-checked and exact-origin checked by the caller, the same
        as a decision save. There is no automatic path into here: this runs only
        when the owner asks for it by name.
        """
        from . import ledger_apply, real_review

        store = _active_store()
        if store is None:
            self._review_refuse("STORE_UNBOUND", 503)
            return
        # Every part of the request has to be here, and has to be the right shape.
        #
        # A missing field is not filled in with a default. `plan_digest` absent
        # would otherwise mean "trust whatever the server plans now", and
        # `transactions` absent would mean "apply everything currently approved" —
        # so a request that names only a request id would write real rows. Both are
        # refused before anything is read or written.
        required = {
            "request_id": str,
            "binding": str,
            "plan_digest": str,
            "choices_revision": int,
        }
        for field, kind in required.items():
            value = payload.get(field)
            if type(value) is not kind or value == "":
                self._review_refuse(ledger_apply.CODE_PLAN_INPUT_INVALID, 400)
                return
        # Present and a list. An *empty* list is not refused here: it is a plan with
        # nothing in it, and the core answers that with its own code so the owner
        # is told "nothing to apply" rather than "your request was malformed".
        if not isinstance(payload.get("transactions"), list):
            self._review_refuse(ledger_apply.CODE_PLAN_INPUT_INVALID, 400)
            return
        try:
            result = ledger_apply.apply_apply_plan(
                self._review_service(), store,
                request_id=payload["request_id"],
                presented_binding=payload["binding"],
                presented_revision=payload["choices_revision"],
                presented_plan_digest=payload["plan_digest"],
                presented_transactions=payload["transactions"])
        except ledger_apply.ApplyPlanError as exc:
            # Nothing here is worth retrying on its own: the bundle moved, the
            # choices moved, or there is nothing to write. The owner is told which
            # and the plan is read again.
            self._review_refuse(exc.code, 409)
            return
        except real_review.RealReviewError as exc:
            self._review_refuse(exc.code, 409)
            return
        except Exception as exc:
            from .ledger_store import SaveError

            if isinstance(exc, SaveError):
                self._review_refuse(exc.code, 409)
                return
            self._review_refuse("REVIEW_INTERNAL_ERROR", 500)
            return
        self._send_json({
            "counts": result["counts"],
            "request_id": result["request_id"],
            "binding": result["binding"],
            "choices_revision": result["choices_revision"],
            "conflicts": result["conflicts"],
        })

    def _handle_review_guidance(self, path: str, payload: dict) -> bool:
        """Owner-only source answers and classification previews, behind CSRF."""
        from . import real_review
        from .review_guidance import GuidanceService, GuidanceError

        review = self._review_service()
        if review is None:
            self._review_refuse(self._review_config_error()
                                or real_review.CODE_UNAVAILABLE, 503)
            return True
        try:
            guidance = GuidanceService(review, _active_store())
            if path == "/api/review/guidance":
                result = guidance.get(payload.get("ref"), payload.get("binding"))
            elif path == "/api/review/guidance/save":
                result = guidance.save(**{key: payload.get(key) for key in (
                    "ref", "binding", "note", "item", "description",
                    "expected_revision", "request_id")})
            elif path == "/api/review/guidance/rule-preview":
                result = guidance.rule_preview(**{key: payload.get(key) for key in (
                    "ref", "binding", "note", "item", "description",
                    "condition_candidate_key", "apply_existing", "apply_future", "request_id")})
            else:
                result = guidance.apply_rule(**{key: payload.get(key) for key in (
                    "ref", "binding", "preview_id", "apply_existing", "apply_future", "request_id")})
            self._send_json(result)
        except GuidanceError as exc:
            status = 409 if "CONFLICT" in exc.code or "STALE" in exc.code else 422
            self._send_json({"code": exc.code, "message": exc.message}, code=status)
        except real_review.RealReviewError as exc:
            self._review_refuse(exc.code, 409 if "CONFLICT" in exc.code else 503)
        except Exception:
            self._review_refuse(real_review.CODE_INTERNAL, 500)
        return True

    def _handle_review_post(self, path: str, payload: dict) -> bool:
        """`/api/review/decisions` and `/api/review/export`, for an owner."""
        from . import real_review

        service = self._review_service()
        if service is None:
            self._review_refuse(self._review_config_error()
                                or real_review.CODE_UNAVAILABLE, 503)
            return True
        try:
            if path == "/api/review/decisions":
                decisions = payload.get("decisions")
                expected = payload.get("expected_revision")
                if type(decisions) is not list or type(expected) is not int \
                        or isinstance(expected, bool):
                    self._review_refuse(
                        real_review.CODE_INTERNAL, 400)
                    return True
                saved = service.save_decisions(decisions, expected,
                                               payload.get("binding"))
                self._send_json({"revision": saved["revision"]})
            else:
                decisions = payload.get("decisions")
                if decisions is not None and type(decisions) is not list:
                    self._review_refuse(real_review.CODE_INTERNAL, 400)
                    return True
                self._send_json(service.export(decisions, payload.get("binding")))
        except real_review.RealReviewError as exc:
            if exc.code in (real_review.CODE_REVISION_CONFLICT,
                            real_review.CODE_BINDING_CONFLICT):
                self._review_refuse(exc.code, 409)
            elif exc.code in _REVIEW_CLIENT_CODES:
                self._review_refuse(exc.code, 400)
            else:
                self._review_refuse(exc.code, 503)
        except Exception:
            self._review_refuse(real_review.CODE_INTERNAL, 500)
        return True

    def _phase7_payload(self, content_type: str, raw: bytes) -> dict:
        if "application/json" in content_type:
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                from . import access_control

                raise access_control.AccessError("INVALID_VALUE",
                                                 "요청을 읽을 수 없어요",
                                                 status=422)
        try:
            form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            from . import access_control

            raise access_control.AccessError("INVALID_VALUE", "요청을 읽을 수 없어요",
                                             status=422)
        return {k: v[0] for k, v in form.items()}

    @_store_request_locked
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        from . import social_preview
        if social_preview.dispatch(self, parsed.path):
            return
        # The platform's own liveness and readiness probes are answered before
        # any role is resolved. A PaaS health check carries no login, and a
        # 401 from a load balancer's probe reads as an unhealthy application. The
        # two answers are deliberately different questions and deliberately say
        # nothing about the ledger: `/healthz` is "this process is up", `/readyz`
        # is "the database is there and has the schema". Neither reports a row
        # count, a customer name, an amount or a path.
        if parsed.path in ("/healthz", "/readyz"):
            code, body = self._platform_probe(parsed.path)
            # The one `_send_json` on this class, called with its own signature.
            # A second definition of the same name was defined here first and
            # silently shadowed the real one, so the probe answered with the
            # whole `[status, body]` pair as its payload.
            self._send_json(body, code)
            return
        # The login, callback, logout and state routes are answered before role
        # resolution, because a caller with no session is exactly who needs
        # them.
        from . import google_demo_page
        if google_demo_page.dispatch(self, parsed):
            return
        if self._auth_routes(query):
            return
        resolve_role(self.headers, self._cookies())
        from . import google_ledger_page as _gl
        if _gl.owns_route(parsed.path):
            # Decided here, for every access setting: with enforcement off the caller is nobody, so the
            # Google routes answer 403 rather than falling through to the owner's board.
            is_owner, viewer = _gl.caller(ACCESS_ENFORCEMENT, getattr(_ROLE_LOCAL, "session", None),
                                          is_owner_session, _active_role)
            tabs = _ACCESS.visible_tabs(viewer) if (viewer and _ACCESS and not is_owner) else set()
            if _gl.dispatch(self, parsed, is_owner=is_owner, viewer_user_id=viewer, csrf=CSRF_TOKEN,
                            query=query, viewer_tabs=tabs):
                return
            self._send_json({"code": "NOT_FOUND"}, 404)
            return
        if ACCESS_ENFORCEMENT:
            # `_phase7_get` reports whether it answered. When it did, the request
            # is finished: falling through would render the owner's board and write
            # a second response on this connection. Only an owner pass-through
            # (`False`) continues below.
            try:
                if self._phase7_get(parsed, query):
                    return
            except Exception as exc:
                self._phase7_refuse(exc)
                return
        from . import receipt_review
        if receipt_review.dispatch(self, parsed, csrf=CSRF_TOKEN, board=_active_store(),
                                   is_owner=_receipts_owner_request(), query=query):
            return
        from . import flight_passenger_page
        if flight_passenger_page.dispatch(self, parsed, csrf=CSRF_TOKEN, board=_active_store(),
                                          is_owner=_participant_owner_request(), query=query):
            return
        from . import participant_income_page as _participant_page
        if _participant_page.owns_route(parsed.path):
            # The owner gate was already decided above for an enforced server.
            # The page refuses anyone else on its own, so a direct address request
            # cannot read a name.
            if _participant_page.dispatch(self, parsed, is_owner=_participant_owner_request(),
                                          csrf=CSRF_TOKEN, query=query):
                return
        from . import ota_catalog
        if ota_catalog.dispatch(self, parsed, board=_active_store(),
                                is_owner=_receipts_owner_request(), query=query, csrf=CSRF_TOKEN):
            return
        from . import card_flow
        if card_flow.dispatch(self, parsed, query=query, csrf=CSRF_TOKEN):
            return
        if parsed.path.startswith("/api/tabs/") and parsed.path.endswith("/tsv"):
            tab_id = unquote(parsed.path[len("/api/tabs/"):-len("/tsv")])
            self._send_tab_tsv(tab_id, query)
            return
        if parsed.path == "/api/board/tsv":
            tab_id = query.get("tab", [""])[0]
            self._send_tab_tsv(tab_id, query)
            return
        if parsed.path == "/cards/all":
            from . import cards_all

            self._send(cards_all.cards_all_page(query, db_path=_get_card_db_path()))
            return
        if card_flow.enabled() and parsed.path == '/review':
            self.send_response(303)
            self.send_header('Location', '/import')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        if parsed.path in ("/", "/board"):
            from . import ledger_design

            # An owner whose operational board is empty is sent to the actual
            # source comparison, because that is the work waiting for them. Only
            # when the request named no tab at all: `/board?tab=unclassified` is
            # a deliberate request for the operational board and is answered as
            # one. Only when the configured source is still exactly what was
            # bound, so a broken or changed manifest cannot bounce anyone into a
            # page that cannot answer. Only here, which is the owner
            # pass-through: a viewer was answered inside `_phase7_get` above and
            # never reaches this line.
            if "tab" not in query and not card_flow.enabled() and self._review_leads_here():
                self.send_response(303)
                self.send_header("Location", "/review")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            tab = query.get("tab", [default_board_tab()])[0]
            q = query.get("q", [""])[0]
            kind = query.get("kind", [""])[0]
            row_id = query.get("row", [""])[0]
            base = f"/board?tab={tab}"
            if q:
                base += f"&q={q}"
            if kind:
                base += f"&kind={kind}"
            if query.get("arch", [""])[0]:
                base += f"&arch={query['arch'][0]}"
            part = (self.headers.get("X-Part")
                    or query.get("part", [""])[0])
            if part == "panel":
                self._send(ledger_design.panel_part(row_id, back=base))
                return
            if part == "summary":
                self._send(ledger_design.summary_part(tab, kind, q))
                return
            from . import live_sync

            fragment = ledger_design.page(
                tab, q, kind, row_id,
                message=query.get("msg", [""])[0],
                archived=query.get("arch", [""])[0])
            self._send(ledger_design.render(
                fragment, live_config=live_sync.client_config(
                    live_sync.owner_token(_active_store(), tab), tab, q, kind,
                    role="owner",
                    archived=query.get("arch", [""])[0], selected=row_id)))
            return
        if parsed.path == "/api/live/state":
            # Only reachable when no access store is bound: the enforcement branch
            # above answers this path itself and returns.
            #
            # This branch must never run for an authenticated caller. `_phase7_get`
            # has already written the session-checked answer by the time control
            # gets here, so writing a second one would put two documents on the
            # same connection — the second computed from `session=None`, which
            # means the owner scope, for a caller who may only read one trip. A
            # client that reads the first Content-Length sees the right answer and
            # a client that reads the whole stream sees both. The guard below makes
            # that unrepresentable rather than merely unlikely.
            if ACCESS_ENFORCEMENT:
                # A refusal or an answer was already written above. Writing
                # anything now is the second response this block exists to prevent.
                return
            # The single-operator server has no access store, so there is no
            # session to check. The token is still computed from the database, so
            # a restart cannot look like an edit here either.
            self._live_sync_state(None, query)
            return
        if parsed.path.startswith("/assets/ota/"):
            from . import ledger_design

            found = ledger_design.ota_asset(parsed.path[len("/assets/ota/"):])
            if found is None:
                self._send("없음", code=404)
                return
            body, content_type = found
            self._send_bytes(body, content_type)
            return
        if parsed.path.startswith("/assets/fonts/"):
            from . import ledger_design

            found = ledger_design.static_asset(parsed.path.rsplit("/", 1)[-1])
            if found is None:
                self._send("없음", code=404)
                return
            body, content_type = found
            self._send_bytes(body, content_type)
            return
        elif parsed.path == "/row":
            row_id = query.get("id", [""])[0]
            # A row id that names nothing is RESOURCE_NOT_FOUND for the owner
            # too, not an empty edit form. The same answer is given to a
            # viewer (DETAILED_CONTRACT 4.3), so the two roles cannot be told
            # apart by probing ids. find_row also resolves an allocation row
            # beside its source, so both kinds keep their detail page.
            if find_row(row_id)[1] is None:
                self._send_json(
                    {"code": "RESOURCE_NOT_FOUND",
                     "message": "없는 행이에요"}, code=404)
                return
            self._send(detail_page(row_id, edit=query.get("edit", [""])[0] == "1"))
        elif parsed.path == "/import":
            self._send(import_page())
        elif parsed.path == "/income/new":
            self._send(income_new_page())
        elif parsed.path == "/expense/new":
            self._send(expense_new_page())
        elif parsed.path == "/export":
            self._send(export_page())
        elif parsed.path.startswith("/api/exports/") and parsed.path.endswith("/download"):
            self._send_export_file(parsed.path.rsplit("/", 2)[-2])
            return
        elif parsed.path.startswith("/api/exports/"):
            from .sheets_export import get_job

            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            job = get_job(_active_store().conn, parsed.path.rsplit("/", 1)[-1])
            if job is None:
                self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 작업이에요"}, code=404)
                return
            self._send_json(job, code=200)
        elif parsed.path.startswith("/income/") and parsed.path.endswith("/split"):
            parts = parsed.path.strip("/").split("/")
            self._send(split_page(parts[1] if len(parts) == 3 else ""))
        elif parsed.path == "/rules":
            case_id = query.get("case", [""])[0]
            if not case_id:
                self._send(layout("규칙 대화", "<div class='body'><p>대화 사례가 필요해요.</p></div>"), code=404)
                return
            self._send(rule_dialog_page(case_id, query))
        elif parsed.path == "/api/tabs":
            # APP_SPEC 10: 권위 상태, 합계, 검토 건수.
            self._send_tabs_index()
            return
        elif parsed.path == "/api/audit/changes":
            # APP_SPEC 10: 기간·탭·행·actor 필터.
            self._send_audit_changes(query)
            return
        elif parsed.path.startswith("/api/tabs/") and parsed.path.endswith("/rows"):
            # APP_SPEC 10: 수입·지출 행과 상태, 현재 revision.
            self._send_tab_rows(parsed.path[len("/api/tabs/"):-len("/rows")])
            return
        elif parsed.path.startswith("/api/rows/") and parsed.path.endswith(
                "/lineage"):
            # APP_SPEC 10: 원천, 제안, 사용자 수정, 이력.
            self._send_row_lineage(
                parsed.path[len("/api/rows/"):-len("/lineage")])
            return
        elif parsed.path == "/trips":
            self._send(trips_page(query.get("preview_tab", [""])[0],
                                  role=resolve_role(self.headers, self._cookies())))
        elif parsed.path.startswith("/api/imports/"):
            if _IMPORTER is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            progress = _IMPORTER.progress(parsed.path.rsplit("/", 1)[-1])
            if progress is None:
                self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 작업이에요"}, code=404)
                return
            self._send_json(progress, code=200)
        elif parsed.path == "/api/classification/conversation":
            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            conversation_id = query.get("conversation_id", [""])[0]
            if not conversation_id:
                self._send_json({"code": "INVALID_VALUE", "message": "conversation_id required"}, code=422)
                return
            self._send_json(_active_store().conversation_state(conversation_id), code=200)
        elif parsed.path == "/api/classification/dialog":
            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            self._send_json(_active_store().rule_dialog_state(query.get("case_id", [""])[0]), code=200)
        elif parsed.path.endswith("/versions") and parsed.path.startswith(
                "/api/classification/rules/"):
            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            rule_id = parsed.path.split("/")[4]
            history = _active_store().rule_history(rule_id)
            if history["current"] is None and not history["versions"]:
                self._send_json({"code": "RESOURCE_NOT_FOUND",
                             "message": "없는 경로예요"}, code=404)
                return
            self._send_json(history, code=200)
        elif parsed.path == "/api/classification/rules":
            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
                return
            self._send_json({"rules": _active_store().list_rules()}, code=200)
        elif parsed.path.startswith("/api/classification/rules/"):
            if _active_store() is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
                return
            rule = _active_store().get_rule(parsed.path.rsplit("/", 1)[-1])
            if rule is None:
                self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 작업이어요"}, code=404)
                return
            self._send_json(rule, code=200)
        elif parsed.path.startswith("/api/cards/transactions"):
            from . import card_transactions as _ct
            if parsed.path == "/api/cards/transactions/day" and current_role() != 'owner':
                self._send_json({"code": "OWNER_REQUIRED"}, code=403)
                return
            try:
                q = parse_qs(parsed.query)
                # Validate year parameter
                year_str = q.get("year", ["2026"])[0]
                try:
                    year = int(year_str)
                except (TypeError, ValueError):
                    self._send_json({"code": "INVALID_VALUE", "message": "year must be an integer"}, code=400)
                    return
                if year < 2000 or year > 2100:
                    self._send_json({"code": "INVALID_VALUE", "message": "year out of range"}, code=400)
                    return

                # Validate month parameter if present
                month = None
                month_str = q.get("month", [None])[0]
                if month_str is not None:
                    try:
                        month = int(month_str)
                    except (TypeError, ValueError):
                        self._send_json({"code": "INVALID_VALUE", "message": "month must be an integer"}, code=400)
                        return
                    if month < 1 or month > 12:
                        self._send_json({"code": "INVALID_VALUE", "message": "month must be 1-12"}, code=400)
                        return

                # Validate cursor format if present
                cursor = q.get("cursor", [None])[0]
                if cursor is not None:
                    parts = cursor.split("|", 1)
                    if len(parts) != 2 or not parts[0] or not parts[1]:
                        self._send_json({"code": "INVALID_VALUE", "message": "invalid cursor format"}, code=400)
                        return
                    c_date, c_id = parts
                    if not (c_date and c_date[0:4].isdigit() and len(c_date) >= 10):
                        self._send_json({"code": "INVALID_VALUE", "message": "invalid cursor date"}, code=400)
                        return

                # Get the card DB path from the active store (request-bound)
                card_db_path = _get_card_db_path()

                # In the base router's unbound test/development mode, retain
                # the V21 API's configured card DB fallback. A request-bound
                # store always takes precedence over this environment path.
                if card_db_path is None and _REQUEST_STORE.get() is _NO_REQUEST_STORE:
                    card_db_path = os.environ.get("WEBLEDGER_DB")

                if parsed.path == "/api/cards/transactions/day":
                    try:
                        result = _ct.list_for_day(db_path=card_db_path, day=q.get('date', [None])[0],
                                                  cursor=cursor, revision=q.get('revision', [None])[0])
                    except _ct.DaySourceChanged:
                        self._send_json({"code": "SOURCE_CHANGED"}, code=409)
                        return
                    self._send_json(result, code=200)
                    return
                if parsed.path == "/api/cards/transactions/years":
                    res = _ct.available_years(db_path=card_db_path)
                    self._send_json(res, code=200)
                    return
                if parsed.path == "/api/cards/transactions/summary":
                    summary = _ct.year_summary(db_path=card_db_path, year=year)
                    self._send_json({"year": year, "months": summary.get("months"), "undated_count": summary.get("undated_count")}, code=200)
                    return
                if parsed.path.startswith("/api/cards/transactions/undated"):
                    res = _ct.undated_list(db_path=card_db_path, year=year, cursor=cursor, per_page=100)
                    self._send_json(res, code=200)
                    return
                if month is None:
                    self._send_json({"code": "INVALID_VALUE", "message": "month required"}, code=400)
                    return
                res = _ct.list_for_month(db_path=card_db_path, year=year, month=month, cursor=cursor, per_page=100)
                self._send_json(res, code=200)
            except ValueError as exc:
                # Validation errors from card_transactions module
                self._send_json({"code": "INVALID_VALUE", "message": str(exc)}, code=400)
            except RuntimeError as exc:
                # Configuration errors (e.g., missing DB path)
                self._send_json({"code": "CONFIG_ERROR", "message": str(exc)}, code=503)
            except Exception as exc:
                # Unexpected errors
                self._send_json({"code": "INTERNAL_ERROR", "message": "요청을 처리하지 못했어요"}, code=500)
        else:

            self._send(layout("없음", "<p>없는 주소예요.</p>"), code=404)

    @_store_request_locked
    def do_POST(self) -> None:
        from .card_import import ImportError as CardImportError
        from .income_ledger import BankImporter, BankImportError
        from .ledger_store import SaveError

        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 5 * 1024 * 1024:
            self._send_json({"code": "TOO_LARGE", "message": "요청이 너무 커요"}, code=413)
            return
        content_type = self.headers.get("Content-Type") or ""
        raw = self.rfile.read(length) if length else b""

        if ACCESS_ENFORCEMENT:
            # Every write is decided on the server, before the body is read
            # into any handler, so a viewer cannot reach a write path at all.
            try:
                if self._phase7_write(parsed, content_type, raw):
                    return
            except Exception as exc:
                self._phase7_refuse(exc)
                return

        def read_payload():
            if "application/json" in content_type:
                try:
                    return json.loads(raw.decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
            try:
                form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
            except UnicodeDecodeError:
                raise SaveError("INVALID_VALUE", "요청을 읽을 수 없어요")
            return {k: (v if len(v) > 1 else v[0]) for k, v in form.items()}

        def check_csrf(payload):
            token = payload.get("csrf") or self.headers.get("X-CSRF-Token") or ""
            if token != CSRF_TOKEN:
                raise SaveError("CSRF_REQUIRED", "확인 토큰이 없어요")

        # The write gates below read the session this request resolved, never a leftover from another one.
        resolve_role(self.headers, self._cookies())
        from . import rule_review
        from . import card_flow as _card_flow_switch
        if _card_flow_switch.enabled() and rule_review.owns_route(parsed.path):
            board = _active_store()
            if board is not None and rule_review.dispatch(self, parsed, raw=raw, csrf=CSRF_TOKEN, board=board):
                return
        from . import ota_catalog
        if ota_catalog.dispatch_post(self, parsed, raw=raw, csrf=CSRF_TOKEN, board=_active_store(),
                                     is_owner=_receipts_owner_request()):
            return
        from . import receipt_review
        if receipt_review.dispatch(self, parsed, raw=raw, csrf=CSRF_TOKEN, board=_active_store(),
                                   is_owner=_receipts_owner_request()):
            return
        from . import google_ledger_page
        if google_ledger_page.owns_route(parsed.path):
            is_owner, viewer = google_ledger_page.caller(
                ACCESS_ENFORCEMENT, getattr(_ROLE_LOCAL, "session", None), is_owner_session,
                _active_role)
            tabs = _ACCESS.visible_tabs(viewer) if (viewer and _ACCESS and not is_owner) else set()
            if google_ledger_page.dispatch(self, parsed, is_owner=is_owner, viewer_user_id=viewer,
                                           raw=raw, csrf=CSRF_TOKEN, viewer_tabs=tabs):
                return
        from . import google_demo_page
        if google_demo_page.dispatch(self, parsed, raw=raw):
            return
        from . import flight_passenger_page
        if flight_passenger_page.dispatch(self, parsed, raw=raw, csrf=CSRF_TOKEN,
                                          board=_active_store(),
                                          is_owner=_participant_owner_request()):
            return
        from . import participant_income_page as _participant_page
        if _participant_page.owns_route(parsed.path):
            # The viewer refusal was already decided above when the server enforces
            # access. The write itself is CSRF-checked inside the page.
            if _participant_page.dispatch(self, parsed, is_owner=_participant_owner_request(),
                                          raw=raw, csrf=CSRF_TOKEN, content_type=content_type):
                return
        from . import card_flow
        if card_flow.dispatch(self, parsed, raw=raw, csrf=CSRF_TOKEN):
            return
        if parsed.path == "/api/imports":
            if _IMPORTER is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            token = self.headers.get("X-CSRF-Token") or ""
            if token != CSRF_TOKEN:
                self._send_json({"code": "CSRF_REQUIRED", "message": "확인 토큰이 없어요"}, code=403)
                return
            from urllib.parse import unquote

            filename = unquote(self.headers.get("X-Filename") or "upload.csv")
            try:
                received = _IMPORTER.receive(raw, filename)
                progress = _IMPORTER.progress(received["batch_id"])
                result = (progress or {}).get("result") or received.get("result") or {}
                self._send_json({"batch_id": received["batch_id"],
                                 "reused": received["reused"],
                                 "status": (progress or {}).get("status", "reconciling"),
                                 "result": result}, code=200)
            except CardImportError as exc:
                self._send_json({"code": exc.code, "message": str(exc)}, code=422)
            return
        if parsed.path in ("/api/classification/dialog/note",
                           "/api/classification/dialog/answer",
                           "/api/classification/dialog/close",
                           "/api/classification/dialog/resume",
                           "/api/classification/conversation/advance",
                           "/api/classification/conversation/reasons",
                           "/api/classification/conversation/confirm-draft",
                           "/api/classification/conversation/owner-draft",
                           "/api/classification/rules/preview",
                           "/api/classification/rules/apply") \
                and "application/json" not in content_type:
            self._handle_rule_dialog_form(parsed.path, raw, content_type)
            return
        if parsed.path in ("/api/classification/rules/draft",
                           "/api/classification/rules/preview",
                           "/api/classification/rules/apply",
                           "/api/classification/rules/revise",
                           "/api/classification/rules/supersede",
                           "/api/classification/rules/scope",
                           "/api/classification/dialog/open",
                           "/api/classification/dialog/answer",
                           "/api/classification/dialog/close",
                           "/api/classification/dialog/resume",
                           "/api/classification/conversation/open",
                           "/api/classification/conversation/turn",
                           "/api/classification/conversation/late",
                           "/api/classification/dialog/note",
                           "/api/classification/conversation/advance",
                           "/api/classification/conversation/reasons",
                           "/api/classification/conversation/confirm-draft"):
            self._handle_classification_rules(parsed.path, read_payload, check_csrf)
            return
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "rows" or parts[3] != "save":
            if parsed.path == "/api/income":
                self._handle_income_create(read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/expenses/manual":
                self._handle_manual_expense(read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/bank-imports":
                from urllib.parse import unquote

                self._handle_bank_import(
                    raw, unquote(self.headers.get("X-Filename") or "bank.csv"))
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "correct":
                self._handle_bank_correct(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "link-bank":
                self._handle_bank_link(parts[2], read_payload, check_csrf)
                return
            if len(parts) == 2 and parts[0] == "api" and parts[1] == "owner-profile":
                # The owner boundary is not decided here: `_phase7_write` has
                # already refused a viewer on any write, exactly as it does for
                # the tab and trip paths.
                self._handle_owner_profile(read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "trips" and parts[3] == "meta":
                self._handle_trip_meta(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "trips" and parts[3] == "delete":
                self._handle_trip_delete(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "rows" and parts[3] == "revert":
                self._handle_revert(parts[2], read_payload, check_csrf, content_type)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "income" and parts[3] == "allocations":
                self._handle_allocations(parts[2], read_payload, check_csrf, content_type)
                return
            if parsed.path == "/api/exports/xlsx":
                self._handle_export(read_payload, check_csrf, content_type)
                return
            self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 주소예요"}, code=404)
            return
        is_form = "application/json" not in content_type
        if _active_store() is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        try:
            payload = read_payload()
            check_csrf(payload)
            expected_revision = int(payload.get("expected_revision", ""))
        except SaveError as exc:
            if is_form:
                self._send_form_error(exc.code, str(exc), {},
                                      str(payload.get("return_to") or ""),
                                      parts[2] if len(parts) > 2 else "")
                return
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        except (TypeError, ValueError):
            if is_form:
                self._send_form_error("INVALID_VALUE", "revision이 필요해요", {},
                                      str(payload.get("return_to") or ""))
                return
            self._send_json({"code": "INVALID_VALUE", "message": "revision이 필요해요"}, code=422)
            return
        kind, current_row = find_row(parts[2])
        if current_row is None:
            if is_form:
                self._send_form_error("INVALID_VALUE", "없는 행이에요", {},
                                      str(payload.get("return_to") or ""))
                return
            self._send_json({"code": "INVALID_VALUE", "message": "없는 행이에요"}, code=422)
            return
        if current_row.get("is_allocation"):
            allowed, _ = editable_fields(
                kind, current_row.get("source_kind", ""), True)
            meta = ("csrf", "expected_revision", "client_request_id", "return_to")
            blocked = [key for key in payload if key not in allowed and key not in meta]
            if blocked:
                if is_form:
                    self._send_form_error(
                        "FIELD_READ_ONLY", f"{blocked[0]}는 배분 행에서 수정할 수 없어요",
                        payload, str(payload.get("return_to") or ""))
                    return
                self._send_json(
                    {"code": "FIELD_READ_ONLY",
                     "message": f"{blocked[0]}는 배분 행에서 수정할 수 없어요"},
                    code=422,
                )
                return
            changes = {key: payload[key] for key in allowed if key in payload}
            try:
                result = _active_store().update_allocation(
                    allocation_id=parts[2],
                    expected_source_revision=expected_revision,
                    changes=changes,
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner",
                )
            except SaveError as exc:
                if exc.code == "EDIT_CONFLICT":
                    # an allocation is a row too, so the same conflict note
                    # applies (APP_SPEC 9).
                    _note_row_conflict(
                        parts[2], expected_revision, payload,
                        str(payload.get("client_request_id") or ""))
                if is_form:
                    self._send_form_error(exc.code, str(exc), payload,
                                          str(payload.get("return_to") or ""))
                    return
                self._send_json({"code": exc.code, "message": str(exc)},
                                code=STATUS_FOR_CODE.get(exc.code, 422))
                return
            if is_form:
                back = str(payload.get("return_to") or "") or f"/row?id={parts[2]}"
                self.send_response(303)
                self.send_header("Location", back)
                self.end_headers()
            else:
                self._send_json(result, code=200)
            return
        source = current_row.get("source_kind", "")
        allowed, fixed = editable_fields(
            kind, source, bool(current_row.get("is_allocation")))
        meta = ("csrf", "expected_revision", "client_request_id", "change_mode",
                "return_to")
        blocked = [k for k in payload if k in fixed]
        if blocked:
            if is_form:
                self._send_form_error(
                    "FIELD_READ_ONLY", f"{blocked[0]}는 고정 필드라 바꿀 수 없어요",
                    payload, str(payload.get("return_to") or ""), parts[2])
                return
            self._send_json(
                {"code": "FIELD_READ_ONLY", "field": blocked[0],
                 "message": f"{blocked[0]}는 고정 필드라 바꿀 수 없어요"}, code=422)
            return
        unknown = [k for k in payload if k not in allowed and k not in meta]
        if unknown:
            if is_form:
                self._send_form_error(
                    "INVALID_VALUE", f"허용하지 않은 필드예요: {unknown[0]}",
                    payload, str(payload.get("return_to") or ""), parts[2])
                return
            self._send_json(
                {"code": "INVALID_VALUE", "field": unknown[0],
                 "message": f"허용하지 않은 필드예요: {unknown[0]}"}, code=422)
            return
        changes = {k: payload[k] for k in allowed if k in payload}
        # 분류대기 행의 여행 선택칸은 빈 값을 보낸다. 빈 값은 "여행 미정"이지 잘못된 탭이 아니다.
        if changes.get("display_tab_id") in ("", "unclassified"):
            changes["display_tab_id"] = None
        if "amount_krw" in changes:
            raw_amount = changes["amount_krw"]
            if isinstance(raw_amount, bool):
                self._refuse_amount(is_form, payload, parts[2])
                return
            try:
                changes["amount_krw"] = int(str(raw_amount).replace(",", ""))
            except (TypeError, ValueError):
                self._refuse_amount(is_form, payload, parts[2])
                return
        try:
            result = _active_store().save(
                row_id=parts[2],
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                change_mode=str(payload.get("change_mode") or ""),
                changes=changes,
                actor="owner",
            )
        except SaveError as exc:
            if exc.code == "EDIT_CONFLICT":
                # APP_SPEC 9: `충돌` is told apart in the DB and in the row
                # detail, so a refused save leaves a note. The note is written
                # here, after the store rolled the save back, and touches no
                # business value.
                _note_row_conflict(
                    parts[2], expected_revision, payload,
                    str(payload.get("client_request_id") or ""))
            if is_form:
                self._send_form_error(exc.code, str(exc), payload,
                                      str(payload.get("return_to") or ""),
                                      parts[2])
                return
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        except sqlite3.OperationalError as exc:
            # A locked or busy database is retryable with the same request id,
            # so the client keeps its draft and is told to confirm, not that
            # the request was invalid.
            self._send_transient(exc)
            return
        if is_form:
            back = str(payload.get("return_to") or "") or f"/row?id={parts[2]}"
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()
        else:
            self._send_json(result, code=200)

    # A transient store failure is reported, not raised at the client.
    #
    # DETAILED_CONTRACT 4.3 gives 503 TEMPORARILY_UNAVAILABLE for exactly this:
    # keep the draft, and confirm or retry the *same* request id. A SQLite lock
    # or a busy database is the real case; it is a retryable condition, so it
    # must not be dressed as a validation error or a 500.
    TRANSIENT_SQLITE = ("database is locked", "database table is locked",
                        "database is busy")

    def _send_transient(self, exc) -> None:
        text = str(exc).lower()
        if any(marker in text for marker in self.TRANSIENT_SQLITE):
            self._send_json(
                {"code": "TEMPORARILY_UNAVAILABLE",
                 "message": "잠시 저장할 수 없어요. 같은 요청으로 다시 확인해 주세요",
                 "retry_same_client_request_id": True},
                code=503)
            return
        self._send_json(
            {"code": "TEMPORARILY_UNAVAILABLE",
             "message": "요청을 처리하지 못했어요. 같은 요청으로 다시 확인해 주세요",
             "retry_same_client_request_id": True},
            code=503)

    def _handle_income_create(self, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
            result = _active_store().create_direct_income(
                fields={
                    "display_tab_id": payload.get("display_tab_id") or None,
                    "occurred_on": str(payload.get("occurred_on") or ""),
                    "amount_krw": amount,
                    "income_kind": str(payload.get("income_kind") or ""),
                    "customer_id": payload.get("customer_id") or None,
                    "customer_name": str(payload.get("customer_name") or ""),
                    "nickname": str(payload.get("nickname") or ""),
                    "memo": str(payload.get("operator_note") or ""),
                },
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={result['row_id']}")
            self.end_headers()

    def _handle_manual_expense(self, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "금액은 정수 원화로 입력해 주세요")
            result = _active_store().create_manual_expense(
                fields={
                    "display_tab_id": payload.get("display_tab_id") or None,
                    "occurred_on": str(payload.get("occurred_on") or ""),
                    "pay_method": str(payload.get("pay_method") or ""),
                    "item": str(payload.get("item") or ""),
                    "description": str(payload.get("description") or ""),
                    "amount_krw": amount,
                    "memo": str(payload.get("operator_note") or ""),
                },
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={result['row_id']}")
            self.end_headers()

    def _handle_bank_import(self, raw: bytes, filename: str) -> None:
        from .income_ledger import BankImporter, BankImportError

        if _active_store() is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        token = self.headers.get("X-CSRF-Token") or ""
        if token != CSRF_TOKEN:
            self._send_json({"code": "CSRF_REQUIRED", "message": "확인 토큰이 없어요"}, code=403)
            return
        try:
            importer = BankImporter(_active_store().conn, _active_store())
            received = importer.receive(raw, filename)
            self._send_json({"batch_id": received["batch_id"],
                             "reused": received["reused"],
                             "result": received["result"]}, code=200)
        except BankImportError as exc:
            self._send_json({"code": exc.code, "message": str(exc)}, code=422)

    def _handle_rule_dialog_form(self, path, raw: bytes, content_type: str) -> None:
        """HTML form post for the rule dialog screen.

        It reuses the same endpoints the JSON path uses and then goes back to
        the screen, so a double click repeats the same client request id and the
        server answers idempotently.
        """
        from urllib.parse import parse_qs, urlencode

        from .ledger_store import SaveError

        form = {k: (v if len(v) > 1 else v[0])
                for k, v in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}
        if form.get("csrf") != CSRF_TOKEN:
            self._send(layout("규칙 대화", "<div class='body'><p>확인 토큰이 없어요.</p></div>"), code=403)
            return
        case_id = str(form.get("case") or "")
        request_id = str(form.get("client_request_id") or "")
        selected = form.get("selected_row_ids")
        payload = dict(form)
        if path.endswith("/dialog/answer"):
            payload["expected_row_revision"] = form.get("expected_row_revision")
        if path.endswith("/rules/preview"):
            payload["apply_existing"] = form.get("apply_existing") in ("1", "on", "true")
            payload["apply_future"] = form.get("apply_future") in ("1", "on", "true")
        if path.endswith("/rules/apply"):
            payload["apply_existing"] = str(form.get("apply_existing") or "") == "1"
            payload["apply_future"] = str(form.get("apply_future") or "") == "1"
            if selected is not None and str(selected).strip():
                payload["selected_row_ids"] = [v for v in str(selected).split(",") if v]
        message = "처리했습니다"
        try:
            if path.endswith("/dialog/note"):
                _active_store().update_rule_dialog_note(
                    learning_case_id=case_id, note=str(form.get("note") or ""),
                    client_request_id=request_id, actor="owner")
                message = "근거 설명을 저장했습니다"
            elif path.endswith("/dialog/answer"):
                answer = str(form.get("answer") or "")
                if answer == "__direct__":
                    answer = str(form.get("direct_answer") or "").strip()
                    if not answer:
                        raise SaveError("INVALID_VALUE", "direct answer is required")
                _active_store().answer_rule_question(
                    question_id=str(form.get("question_id") or ""),
                    answer=answer,
                    expected_row_revision=int(form.get("expected_row_revision") or 0),
                    client_request_id=request_id, actor="owner")
                message = "답변을 저장했습니다"
            elif path.endswith("/dialog/close"):
                _active_store().close_rule_dialog(learning_case_id=case_id,
                                         client_request_id=request_id, actor="owner")
                message = "대화를 닫았습니다. 다시 열면 답변이 유지됩니다"
            elif path.endswith("/dialog/resume"):
                _active_store().resume_rule_dialog(learning_case_id=case_id,
                                          client_request_id=request_id, actor="owner")
                message = "대화를 다시 열었습니다"
            elif path.endswith("/conversation/advance"):
                result = _active_store().advance_dialog_conversation(
                    learning_case_id=case_id, client_request_id=request_id,
                    muse=_MUSE, gemini=_GEMINI, actor="owner",
                    operator=_operator_choice(case_id, form))
                turn = result.get("turn") or {}
                if turn.get("state") == "answered":
                    message = (f"초안을 받았습니다 · 공급자 {turn.get('adopted_provider')}"
                               f" · 전환 {turn.get('switch_count')}회")
                else:
                    message = (f"AI 초안 대기 중입니다 · 사유 {turn.get('reason_code') or '-'}"
                               " · 행 저장과 규칙 실행은 계속됩니다")
            elif path.endswith("/conversation/reasons"):
                result = _active_store().suggest_trip_move_reasons(
                    learning_case_id=case_id, client_request_id=request_id, muse=_MUSE)
                message = ("\uc774\ub3d9 \uc774\uc720 \uc120\ud0dd\uc9c0\ub97c \uc900\ube44\ud588\uc2b5\ub2c8\ub2e4."
                           if result.get("status") == "suggested"
                           else "\ubb34\ub8cc AI \uc81c\uc548\uc774 \uc5c6\uc2b5\ub2c8\ub2e4. \uc9c1\uc811 \uc785\ub825\ud574\uc8fc\uc138\uc694.")
            elif path.endswith("/conversation/owner-draft"):
                _active_store().owner_correction_draft(learning_case_id=case_id,
                                                       client_request_id=request_id, actor="owner")
                message = "수정 내용으로 규칙 초안을 만들었습니다. 적용 범위를 고르고 영향을 미리 확인해 주세요"
            elif path.endswith("/conversation/confirm-draft"):
                _active_store().confirm_dialog_draft(learning_case_id=case_id,
                                            client_request_id=request_id, actor="owner")
                message = "규칙 초안을 저장했습니다. 적용 범위를 고르고 적용해 주세요"
            elif path.endswith("/rules/preview"):
                result = _active_store().preview_rule(
                    rule_id=str(form.get("rule_id") or ""),
                    apply_existing=payload["apply_existing"],
                    apply_future=payload["apply_future"])
                counts = result.get("counts", {})
                message = (f"영향 미리보기: 포함 {counts.get('included_rows', 0)}건"
                           f" · 제외 {counts.get('excluded_rows', 0)}건")
            else:
                result = _active_store().apply_rule(
                    preview_id=str(form.get("preview_id") or ""),
                    apply_existing=payload["apply_existing"],
                    apply_future=payload["apply_future"],
                    selected_row_ids=payload.get("selected_row_ids"),
                    client_request_id=request_id, actor="owner")
                message = (f"적용했습니다 · {result.get('applied_count', 0)}건"
                           + (" · 미래 적용" if result.get("apply_future") else ""))
                if not (payload["apply_existing"] or payload["apply_future"]):
                    message = ("적용 범위(기존 행·미래 입력)를 하나 이상 골라야 규칙이 켜집니다. "
                               "규칙은 초안 상태로 남아 있어요")
                if result.get("apply_future"):
                    try:
                        from . import card_flow
                        card_flow.reclassify_pending(_active_store())
                    except Exception:
                        message += " · 미기록 카드 거래의 재분류는 다음 분류 때 반영됩니다"
        except SaveError as exc:
            self._redirect_rule_dialog(case_id, f"{exc.code}: {exc}")
            return
        except ValueError:
            self._redirect_rule_dialog(case_id, "INVALID_VALUE: 값을 확인해 주세요")
            return
        self._redirect_rule_dialog(case_id, message)

    def _redirect_rule_dialog(self, case_id: str, message: str) -> None:
        from urllib.parse import urlencode

        self.send_response(303)
        self.send_header(
            "Location",
            f"/rules?{urlencode({'case': case_id, 'msg': message})}")
        self.end_headers()

    def _handle_classification_rules(self, path, read_payload, check_csrf) -> None:
        """Phase 6A rule draft, impact preview, and confirmed apply.

        JSON only. The design template pass adds screens later.
        """
        from .ledger_store import SaveError

        if _active_store() is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
            return
        try:
            payload = read_payload()
            check_csrf(payload)
            if path.endswith("/draft"):
                raw = payload.get("draft")
                result = _active_store().create_rule_draft(
                    draft=raw if isinstance(raw, dict) else {},
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/preview"):
                result = _active_store().preview_rule(
                    rule_id=str(payload.get("rule_id") or ""),
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")))
            elif path.endswith("/revise"):
                raw = payload.get("draft")
                result = _active_store().revise_rule(
                    rule_id=str(payload.get("rule_id") or ""),
                    draft=raw if isinstance(raw, dict) else {},
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/supersede"):
                result = _active_store().supersede_rule(
                    new_rule_id=str(payload.get("new_rule_id") or ""),
                    old_rule_id=str(payload.get("old_rule_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/scope"):
                result = _active_store().update_rule_scope(
                    rule_id=str(payload.get("rule_id") or ""),
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/open"):
                result = _active_store().open_conversation(
                    learning_case_id=str(payload.get("learning_case_id")
                                         or payload.get("case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/turn"):
                # The body may not pick a provider. Adapters come from the
                # server binding only, and no key is accepted or stored.
                result = _active_store().run_dialog_turn(
                    conversation_id=str(payload.get("conversation_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    muse=_MUSE, gemini=_GEMINI, actor="owner")
            elif path.endswith("/conversation/late"):
                result = _active_store().adopt_late_response(
                    conversation_id=str(payload.get("conversation_id") or ""),
                    turn_id=str(payload.get("turn_id") or ""),
                    attempt_id=str(payload.get("attempt_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/note"):
                result = _active_store().update_rule_dialog_note(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    note=str(payload.get("note") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/advance"):
                result = _active_store().advance_dialog_conversation(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    muse=_MUSE, gemini=_GEMINI, actor="owner",
                        operator=_operator_choice(
                            str(payload.get("case")
                                or payload.get("learning_case_id") or ""), payload))
            elif path.endswith("/conversation/reasons"):
                result = _active_store().suggest_trip_move_reasons(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    muse=_MUSE)
            elif path.endswith("/conversation/confirm-draft"):
                result = _active_store().confirm_dialog_draft(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/open"):
                raw = payload.get("draft")
                result = _active_store().open_rule_dialog(
                    learning_case_id=str(payload.get("learning_case_id") or ""),
                    draft=raw if isinstance(raw, dict) else {},
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/answer"):
                try:
                    expected_revision = int(payload.get("expected_row_revision", ""))
                except (TypeError, ValueError):
                    raise SaveError("INVALID_VALUE", "row revision is required")
                result = _active_store().answer_rule_question(
                    question_id=str(payload.get("question_id") or ""),
                    answer=str(payload.get("answer") or ""),
                    expected_row_revision=expected_revision,
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/close"):
                result = _active_store().close_rule_dialog(
                    learning_case_id=str(payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/resume"):
                result = _active_store().resume_rule_dialog(
                    learning_case_id=str(payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            else:
                selected = payload.get("selected_row_ids")
                if selected is not None and not isinstance(selected, list):
                    raise SaveError("INVALID_VALUE", "선택 한 목록이 다시어요")
                result = _active_store().apply_rule(
                    preview_id=str(payload.get("preview_id") or ""),
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")),
                    selected_row_ids=selected,
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        self._send_json(result, code=200)

    def _handle_revert(self, row_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            result = _active_store().revert_row(
                row_id=row_id,
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            if exc.code == "EDIT_CONFLICT":
                _note_row_conflict(
                    row_id, expected_revision, {},
                    str(payload.get("client_request_id") or ""))
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={row_id}")
            self.end_headers()

    def _handle_allocations(self, source_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_source_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            if isinstance(payload.get("allocations"), list):
                plan = payload["allocations"]
            else:
                try:
                    count = int(payload.get("row_count", 0))
                except (TypeError, ValueError):
                    raise SaveError("INVALID_VALUE", "배분안이 올바르지 않아요")
                plan = []
                for i in range(count):
                    raw_amount = str(payload.get(f"alc_{i}_amount") or "").strip()
                    if not raw_amount:
                        continue
                    try:
                        amount = int(raw_amount.replace(",", ""))
                    except ValueError:
                        raise SaveError("INVALID_VALUE", "배분액은 정수 원화로 입력해 주세요")
                    tab = payload.get(f"alc_{i}_tab") or None
                    if tab == "unclassified":
                        tab = None
                    plan.append({
                        "allocation_id": str(payload.get(f"alc_{i}_id") or ""),
                        "customer_name": str(payload.get(f"alc_{i}_customer") or ""),
                        "display_tab_id": tab,
                        "income_kind": str(payload.get(f"alc_{i}_kind") or ""),
                        "amount_krw": amount,
                    })
            new_principal = None
            if str(payload.get("new_principal_amount") or "").strip():
                try:
                    new_principal = {
                        "amount_krw": int(str(payload["new_principal_amount"]).replace(",", "")),
                    }
                except ValueError:
                    raise SaveError("INVALID_VALUE", "원금은 정수 원화로 입력해 주세요")
            result = _active_store().save_allocations(
                source_row_id=source_id,
                expected_source_revision=expected_revision,
                allocations=plan,
                client_request_id=str(payload.get("client_request_id") or ""),
                new_principal=new_principal,
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={source_id}")
            self.end_headers()

    def _send_export_file(self, job_id: str) -> None:
        from urllib.parse import quote

        from .sheets_export import file_sha256, get_job

        if _active_store() is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        job = get_job(_active_store().conn, job_id)
        if job is None or not job.get("output_path"):
            self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 작업이에요"}, code=404)
            return
        path = job["output_path"]
        try:
            if file_sha256(path) != (job.get("output_sha256") or ""):
                self._send_json({"code": "EXPORT_CHANGED",
                                 "message": "출력 파일이 바뀌었어요. 다시 출력해 주세요"}, code=410)
                return
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "출력 파일이 없어요"}, code=404)
            return
        name = job.get("output_path", "ledger.xlsx").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        self.send_response(200)
        self.send_header("Content-Type",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         f"attachment; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(data)

    def _handle_export(self, read_payload, check_csrf, content_type) -> None:
        import os
        from pathlib import Path

        from .ledger_store import SaveError
        from .sheets_export import (UnconfirmedAssigneeError, build_workbook,
                                    file_sha256, get_job, publish_workbook,
                                    record_job)

        try:
            payload = read_payload()
            check_csrf(payload)
            raw_tabs = payload.get("tab_ids")
            if isinstance(raw_tabs, str):
                raw_tabs = [raw_tabs]
            tab_ids = [t for t in (raw_tabs or []) if isinstance(t, str)]
            valid = {t["tab_id"] for t in live_trips(include_archived=True)}
            if not tab_ids or any(t not in valid for t in tab_ids):
                raise SaveError("INVALID_VALUE", "출력할 여행을 골라 주세요")
            seen = set()
            ordered = [t for t in tab_ids if not (t in seen or seen.add(t))]
            job_id = f"xlsx-{payload.get('client_request_id') or uuid.uuid4().hex}"
            existing = get_job(_active_store().conn, job_id)
            if existing:
                if existing["tab_ids"] != ordered:
                    raise SaveError("REQUEST_ID_REUSED", "같은 요청 ID로 다른 내용을 보냈어요")
                if "application/json" in content_type:
                    self._send_json(existing, code=200)
                else:
                    self.send_response(303)
                    self.send_header(
                        "Location", f"/api/exports/{job_id}/download")
                    self.end_headers()
                return
            wb, manifest = build_workbook(_active_store(), ordered)
            output_dir = (os.environ.get("WEBLEDGER_EXPORT_DIR", "webledger-exports") or "").strip()
            stem = f"ledger-{manifest['input_snapshot_sha256'][:12]}"
            try:
                target, manifest = publish_workbook(
                    wb, manifest, output_dir or "webledger-exports", stem)
            except FileExistsError:
                # The stem comes from the input snapshot hash, so a new request
                # over the same input needs its own file name. The suffix is per
                # attempt, nothing is overwritten, and a retried request never
                # reaches here because the stored job answers first.
                target, manifest = publish_workbook(
                    wb, manifest, output_dir or "webledger-exports",
                    f"{stem}-{uuid.uuid4().hex[:8]}")
            manifest["output_path"] = str(target)
            record_job(_active_store().conn, job_id=job_id, tab_ids=ordered,
                       manifest=manifest, status="ready")
            job = get_job(_active_store().conn, job_id)
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        except UnconfirmedAssigneeError as exc:
            # Refused whole, before any sheet exists. The trips are named so the
            # owner can go and confirm them through the explicit trip meta path;
            # no file is produced carrying a name nobody claimed.
            self._send_json(exc.as_payload(), code=exc.status)
            return
        if "application/json" in content_type:
            self._send_json(job, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/api/exports/{job_id}/download")
            self.end_headers()

    def _handle_owner_profile(self, read_payload, check_csrf, content_type) -> None:
        """`POST /api/owner-profile`: the owner names the company and default assignee.

        Owner-only, CSRF-checked and revision-checked, reusing the same
        `_phase7_write` boundary every other write in this handler sits behind, so
        a viewer is refused before the body is read and no new gate is introduced.

        An empty name is stored rather than refused: "not set yet" is a real state
        for a default, and a field that can be filled once but never cleared is
        worse than one that starts empty.
        """
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            kwargs = {}
            for key in ("company_name", "assignee_name"):
                if key in payload:
                    kwargs[key] = payload[key]
            store = _active_store()
            if store is None:
                raise SaveError("INVALID_VALUE", "저장소가 연결되지 않았어요")
            result = store.save_owner_profile(
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner", **kwargs,
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            back = str(payload.get("return_to") or "") or "/trips"
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()

    def _handle_trip_meta(self, tab_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            kwargs = {}
            for key in ("display_key", "prepared_on"):
                if key in payload:
                    kwargs[key] = payload[key]
            if "archived" in payload:
                value = payload["archived"]
                kwargs["archived"] = str(value).strip().lower() not in ("", "0", "false", "no")
            if "prepared_by_name" in payload:
                # A caller that sends the field on its own is stating the
                # assignee, which is the existing contract and is honoured here.
                #
                # The trip form is the one caller that must not: it carries every
                # field on the trip, so a rename alone would arrive carrying the
                # assignee too, and saving it would record that the owner
                # confirmed a name they never looked at. The form says so by
                # sending `assignee_confirmed`, and then the value is compared
                # against what the server holds — so a changed name is an
                # explicit edit and an unchanged one counts only when the owner
                # ticked the confirmation.
                explicit_form = "assignee_form" in payload
                submitted = str(payload.get("prepared_by_name") or "")
                if not explicit_form:
                    kwargs["prepared_by_name"] = payload["prepared_by_name"]
                else:
                    confirmed = str(payload.get("assignee_confirmed") or "")
                    ticked = confirmed.strip().lower() not in ("", "0", "false", "no")
                    current = _active_store().get_trip(tab_id)
                    held = str((current or {}).get("prepared_by_name") or "")
                    if submitted != held or ticked:
                        kwargs["prepared_by_name"] = submitted
                    # Otherwise the field is dropped here on the server. Hiding
                    # it in the page with script would leave the promotion
                    # reachable by anyone who posts the form by hand.
            result = _active_store().save_trip_meta(
                tab_id=tab_id, expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner", **kwargs,
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            back = str(payload.get("return_to") or "") or "/trips"
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()

    def _send_tab_rows(self, tab_id) -> None:
        """APP_SPEC 10: `GET /api/tabs/{tab_id}/rows`.

        The income and expense rows with their state and the current revision, so
        a caller does not have to read the board HTML to learn a row's revision.
        """
        if _active_store() is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        if tab_id != "unclassified" and _active_store().get_trip(tab_id) is None:
            self._send_json(
                {"code": "RESOURCE_NOT_FOUND", "message": "없는 여행이에요"},
                code=404)
            return
        rows = _active_store().list_tab_rows(None if tab_id == "unclassified" else tab_id)
        out = []
        for r in rows:
            out.append({
                "row_id": r.get("row_id"),
                "row_kind": r.get("row_kind"),
                "display_tab_id": r.get("display_tab_id"),
                "revision": r.get("revision"),
                "amount_krw": _shown_amount(r),
                "occurred_on": r.get("occurred_on") or "",
                "classification_state": r.get("classification_state") or "",
                "needs_review": row_needs_review(r),
                "conflict": row_has_conflict(r),
            })
        self._send_json({
            "tab_id": tab_id, "rows": out, "count": len(out),
            "income_rows": sum(1 for r in out if r["row_kind"] == "income"),
            "expense_rows": sum(1 for r in out if r["row_kind"] != "income"),
        }, code=200)

    def _send_tab_tsv(self, tab_id: str, query: dict = None) -> None:
        """GET /api/tabs/{tab_id}/tsv or /api/board/tsv?tab={tab_id}"""
        if not tab_id:
            self._send_json({"code": "TAB_REQUIRED", "message": "여행 탭을 지정해 주세요."}, code=400)
            return
        from . import ledger_design
        if not ledger_design._is_trip_tab(tab_id):
            self._send_json({"code": "INVALID_TRIP_TAB", "message": "여행 탭이 아닙니다."}, code=400)
            return
        q = (query or {}).get("q", [""])[0] if query else ""
        kind = (query or {}).get("kind", [""])[0] if query else ""
        result = ledger_design.tsv_for_trip_expenses(tab_id, query=q, kind=kind)
        self._send_json(result, code=200)

    def _send_row_lineage(self, row_id) -> None:
        """APP_SPEC 10: `GET /api/rows/{row_id}/lineage`.

        원천, 제안, 사용자 수정, 이력. The row's source identifiers, what the
        classifier proposed, what the user changed, and the append-only history
        are returned as separate parts, so a caller can tell an agent's proposal
        from a person's save instead of reading one merged blob.
        """
        if _active_store() is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        kind, row = find_row(row_id)
        if row is None:
            self._send_json(
                {"code": "RESOURCE_NOT_FOUND", "message": "없는 행이에요"}, code=404)
            return
        try:
            history = _active_store().list_history(row_id)
        except Exception:
            history = []
        source = {"kind": row.get("source_kind") or "",
                  "event_id": row.get("source_event_id") or "",
                  "original_description": row.get("original_description") or "",
                  "card_hash": row.get("source_hash") or ""}
        proposal = {"classification_state": row.get("classification_state"),
                    "classification_basis": row.get("classification_basis") or "",
                    "display_tab_id": row.get("display_tab_id")}
        edits = [h for h in history
                 if h.get("kind") in ("save", "revert")]
        self._send_json({
            "row_id": row_id, "row_kind": kind,
            "revision": row.get("revision"),
            "source": source, "proposal": proposal,
            "user_edits": edits, "history": history,
            "event_count": len(history),
        }, code=200)

    def _send_audit_changes(self, query) -> None:
        """APP_SPEC 10: `GET /api/audit/changes`, filtered by 기간·탭·행·actor.

        The filter is applied in the query, so a caller asking for one row or one
        actor is not handed the whole ledger to discard on their side.
        """
        if _active_store() is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        where = ["1=1"]
        args = []
        since = str(query.get("since", [""])[0] or "").strip()
        until = str(query.get("until", [""])[0] or "").strip()
        row_id = str(query.get("row_id", [""])[0] or "").strip()
        actor = str(query.get("actor", [""])[0] or "").strip()
        tab_id = str(query.get("tab_id", [""])[0] or "").strip()
        if since:
            where.append("created_at >= ?")
            args.append(since)
        if until:
            where.append("created_at <= ?")
            args.append(until)
        if row_id:
            where.append("row_id = ?")
            args.append(row_id)
        if actor:
            where.append("actor = ?")
            args.append(actor)
        rows = _active_store().conn.execute(
            "SELECT row_id, revision, kind, reverts_event_id, event_id, actor,"
            f" created_at, client_request_id FROM board_revisions WHERE {' AND '.join(where)}"
            " ORDER BY created_at, id", args).fetchall()
        changes = []
        for r in rows:
            if tab_id:
                current = _active_store().get_row(r[0]) or {}
                if (current.get("display_tab_id") or "") != tab_id:
                    continue
            changes.append({
                "row_id": r[0], "revision": r[1], "kind": r[2] or "save",
                "reverts_event_id": r[3] or "", "event_id": r[4] or "",
                "actor": r[5], "created_at": r[6], "client_request_id": r[7],
            })
        self._send_json({"changes": changes, "count": len(changes),
                         "filters": {"since": since, "until": until,
                                     "row_id": row_id, "actor": actor,
                                     "tab_id": tab_id}}, code=200)

    def _send_tabs_index(self) -> None:
        """APP_SPEC 10: `GET /api/tabs` with 권위 상태, 합계, 검토 건수.

        Each tab reports its own authority standing rather than implying it
        through the display name, its income and expense totals, and how many of
        its rows still need a person's decision.
        """
        if _active_store() is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        out = []
        for t in live_trips(include_archived=True):
            if t.get("deleted"):
                continue
            rows = _active_store().list_tab_rows(t["tab_id"])
            income = sum(_shown_amount(r) for r in rows if r.get("row_kind") == "income")
            expense = sum(_shown_amount(r) for r in rows if r.get("row_kind") != "income")
            needs_review = sum(1 for r in rows if row_needs_review(r))
            conflicts = sum(1 for r in rows if row_has_conflict(r))
            out.append({
                "tab_id": t["tab_id"], "display_key": t["display_key"],
                "destination": t["destination"], "starts_on": t["starts_on"],
                "ends_on": t["ends_on"], "event_year": t.get("event_year"),
                "tab_kind": t.get("tab_kind") or "trip",
                "authority_status": t.get("authority_status") or "needs_review",
                "authority_label": AUTHORITY_LABELS.get(
                    t.get("authority_status"), "검토 필요"),
                "tab_lifecycle": t.get("tab_lifecycle") or "active",
                "sort_order": t.get("sort_order") or 0,
                "income_krw": income, "expense_krw": expense,
                "profit_krw": income - expense,
                "income_rows": sum(1 for r in rows if r.get("row_kind") == "income"),
                "expense_rows": sum(1 for r in rows if r.get("row_kind") != "income"),
                "needs_review_rows": needs_review,
                "conflict_rows": conflicts,
            })
        unclassified = _active_store().list_tab_rows(None)
        unc_income = sum(_shown_amount(r) for r in unclassified
                         if r.get("row_kind") == "income")
        unc_expense = sum(_shown_amount(r) for r in unclassified
                          if r.get("row_kind") != "income")
        out.append({
            "tab_id": "unclassified", "display_key": "분류대기",
            "destination": "", "starts_on": "", "ends_on": "",
            "event_year": None, "tab_kind": "other",
            "authority_status": "needs_review",
            "authority_label": AUTHORITY_LABELS["needs_review"],
            "tab_lifecycle": "active", "sort_order": 0,
            "income_krw": unc_income,
            "expense_krw": unc_expense,
            "profit_krw": unc_income - unc_expense,
            "income_rows": sum(1 for r in unclassified
                               if r.get("row_kind") == "income"),
            "expense_rows": sum(1 for r in unclassified
                                if r.get("row_kind") != "income"),
            "needs_review_rows": len(unclassified),
            "conflict_rows": sum(1 for r in unclassified if row_has_conflict(r)),
        })
        self._send_json({"tabs": out, "count": len(out)}, code=200)

    def _handle_trip_delete(self, tab_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                snapshot = json.loads(payload.get("snapshot") or "{}")
                expected_revision = int(snapshot.get("tab_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("DELETE_PREVIEW_STALE", "미리보기부터 다시 확인해 주세요")
            mode = str(payload.get("mode") or "move-unclassified")
            destination = str(payload.get("destination") or "") or None
            if mode == "move-trip" and not destination:
                raise SaveError("TARGET_NOT_ASSIGNABLE", "옮길 여행을 골라 주세요")
            result = _active_store().apply_tab_delete(
                tab_id=tab_id, expected_revision=expected_revision,
                mode=mode, destination=destination,
                snapshot=snapshot,
                client_request_id=str(payload.get("client_request_id") or ""),
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            back = str(payload.get("return_to") or "") or "/trips"
            self.send_response(303)
            self.send_header("Location", back)
            self.end_headers()

    def _handle_bank_correct(self, row_id, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                amount = int(str(payload.get("corrected_amount_krw", "")).replace(",", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "정정 금액은 정수 원화로 입력해 주세요")
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            date_value = str(payload.get("corrected_occurred_on") or "").strip() or None
            result = _active_store().correct_bank_income(
                row_id=row_id,
                corrected_amount_krw=amount,
                corrected_occurred_on=date_value,
                reason=str(payload.get("reason") or ""),
                client_request_id=str(payload.get("client_request_id") or ""),
                expected_revision=expected_revision,
                actor="owner",
            )
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(result, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/row?id={row_id}")
            self.end_headers()

    def _handle_bank_link(self, row_id, read_payload, check_csrf) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            try:
                expected_revision = int(payload.get("expected_revision", ""))
            except (TypeError, ValueError):
                raise SaveError("INVALID_VALUE", "revision이 필요해요")
            result = _active_store().link_bank_source(
                row_id=row_id,
                bank_batch_id=str(payload.get("bank_batch_id") or ""),
                bank_row_index=int(payload.get("bank_row_index", -1)),
                expected_revision=expected_revision,
                client_request_id=str(payload.get("client_request_id") or ""),
            )
        except (SaveError, TypeError, ValueError) as exc:
            code = exc.code if isinstance(exc, SaveError) else "INVALID_VALUE"
            self._send_json({"code": code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(code, 422))
            return
        self._send_json(result, code=200)


def serve(port: int = 8751, db_path=None, with_worker: bool = True,
           host: str = "127.0.0.1",
           seed_demo: bool = True) -> ThreadingHTTPServer:
    import os

    from .card_import import CardImporter, CardWorker
    from .ledger_store import LedgerStore

    if db_path is None:
        db_path = os.environ.get("WEBLEDGER_DB", "webledger.work.sqlite")
    store = LedgerStore(db_path, seed_demo=seed_demo)
    from . import card_flow
    # Loopback stays the default. 19.2 wants only the HTTPS app path exposed,
    # so a different address is the caller's stated decision, not a default
    # this module makes on its own.
    #
    # A threading server, not a plain one. `HTTPServer` accepts one connection
    # and then blocks reading that socket, so a client that opens a connection
    # and sends nothing holds every other client out of the backlog. A browser
    # does exactly that speculatively before a navigation, which is how this
    # module served a `Page.goto: Navigation ... Timeout` roughly one run in
    # ten; measured directly, one silent connection delayed a real request past
    # an eight second timeout, and a threading server answered the same request
    # in 0.04s. It is the same defect for a real user whose connection stalls.
    server = None
    worker = None
    try:
        importer = None if card_flow.enabled() else CardImporter(store.conn, store)
        server = ThreadingHTTPServer((host, port), Handler)
        # A worker thread must not keep the process alive after the socket closes.
        server.daemon_threads = True
        server.store_lock = threading.RLock()
        if with_worker and not card_flow.enabled():
            worker = CardWorker(db_path)
            worker.start()
        server.card_worker = worker
        server.card_store = store
    except BaseException:
        if worker is not None:
            try:
                worker.stop(timeout=5)
            except Exception:
                pass
        try:
            if server is not None:
                server.server_close()
        finally:
            store.close()
        raise
    # Publish only a fully constructed server; a bind failure must not replace
    # another server's active store with a failed, closed connection.
    bind_store(store)
    bind_importer(importer)
    return server


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    httpd = serve(args.port, host=args.host)
    print(f"ledger board on http://{args.host}:{args.port}/board (synthetic)")
    httpd.serve_forever()
