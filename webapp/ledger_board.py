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
import json
import secrets
import sqlite3
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit

from .classification_rules import (SYNTHETIC_MODE_NOTE, dialog_state_label,
                                   question_view, reason_label)

CSRF_TOKEN = secrets.token_hex(16)
_STORE = None
_IMPORTER = None
_MUSE = None
_GEMINI = None
# Phase 6: the owner-only provider configuration service. Unbound by default.
_PROVIDER_CONFIG = None
_PROVIDER_AUTOWIRE = False
_PROVIDER_TRANSPORT = None
_ACCESS = None
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
    "unconfirmed": "미확정",
    "conflicted": "충돌",
}

# The role a renderer should draw owner-only controls for. It is decided once per
# request on the server and kept per thread, so a screen can ask for it without
# the request object being threaded through every renderer, and one request's
# role can never reach another request's screen on the same server.
_ROLE_LOCAL = threading.local()


def resolve_role(headers) -> str:
    """Decide the role for this request, on the server, from the session only."""
    if not ACCESS_ENFORCEMENT:
        role = "owner"
    else:
        session = current_session(headers)
        role = ("owner" if session is not None and is_owner_session(session)
                else "viewer")
    _ROLE_LOCAL.role = role
    return role


def current_role() -> str:
    """The role decided for the request being served on this thread."""
    role = getattr(_ROLE_LOCAL, "role", None)
    if role is not None:
        return role
    return "viewer" if ACCESS_ENFORCEMENT else "owner"


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


def access_control_session_adapter():
    from . import access_control

    return access_control.session_adapter()


def access_store():
    return _ACCESS


def current_session(headers):
    """The session for this request, or None. Never trusts a request body."""
    from . import access_control

    if not ACCESS_ENFORCEMENT:
        return None
    return access_control.session_adapter().session_for(headers)


def require_session(headers):
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


# ------------------------------------------------- Phase 7 view rendering
def access_control_render_viewer_status(session, store) -> dict:
    """The viewer's own state, never another person's application list."""
    applications = store.applications_for(session.user_id)
    connection = store.active_connection(session.user_id)
    return {
        "user_id": session.user_id,
        "role": store.account_role(session.user_id),
        "email": session.email,
        "identity_source": "synthetic" if session.is_synthetic else "google_oidc",
        "google_oidc_connected": False,
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
    all_trips = _STORE.list_trips(include_archived=True) if _STORE is not None else []
    for trip in all_trips:
        if trip["tab_id"] not in allowed:
            continue
        rows = _STORE.list_tab_rows(trip["tab_id"]) if _STORE is not None else []
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
    items = "".join(
        f"<li><a href='/board?tab={esc(t['tab_id'])}'>{esc(t['display_key'])}</a>"
        f" — {esc(t['starts_on'])}~{esc(t['ends_on'])}"
        f" · 수입 {t['income_krw']:,}원 · 지출 {t['expense_krw']:,}원"
        f" · 차액 {t['balance_krw']:,}원</li>"
        for t in trips)
    if not trips:
        body = ("<div class='sect'><h2>담당 여행</h2>"
                "<p>현재 배정된 여행이 없습니다</p></div>")
    else:
        body = (f"<div class='sect'><h2>담당 여행</h2><ul>{items}</ul></div>")
    return ledger_design.render(ledger_design.shell(
        "담당 여행", tab_id=tab_id or "", heading="담당 여행", body=body))


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
    if _STORE is None:
        return None
    case = _STORE.conn.execute(
        "SELECT row_id FROM board_learning_cases WHERE case_id=?",
        (case_id,)).fetchone()
    if case is None:
        return None
    row = _STORE.get_row(case[0]) or {}
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
    if _STORE is None:
        return False
    try:
        return _STORE.row_conflict(row.get("row_id") or "") is not None
    except Exception:
        return False


def _note_row_conflict(row_id, expected_revision, payload, client_request_id) -> None:
    """Record a refused save as an unresolved conflict, in its own transaction.

    Called only where the store has already answered `EDIT_CONFLICT`. The row's
    values, revision and totals are not touched, and the refused request is not
    stored as a request result, so a failed save still changes nothing about the
    ledger's business state (REVIEW R01).
    """
    if _STORE is None:
        return
    skip = {"csrf", "expected_revision", "client_request_id", "return_to"}
    attempted = {k: v for k, v in (payload or {}).items() if k not in skip}
    try:
        _STORE.record_conflict(
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
            f"<button class='btn primary' type='submit'>저장</button>"
            f"<button class='btn' type='submit' formaction='/access/providers'"
            f" name='action' value='refresh-models'"
            f" formnovalidate>모델 목록 다시 읽기</button>"
            f"<button class='btn' type='submit' formaction='/access/providers'"
            f" name='action' value='connection-test'"
            f" formnovalidate>연결 테스트</button>"
            f"</form>"
            f"<p class='muted'>사용 가능한 모델은 서버가 조회한 목록{esc(fetched_note)}"
            " 중 무료 지원이 확인된 항목만 고를 수 있어요.</p>"
            f"<form method='post' action='/access/providers' class='f'>"
            f"<input type='hidden' name='action' value='clear'>"
            f"<input type='hidden' name='provider' value='{esc(name)}'>"
            f"<input type='hidden' name='csrf' value='{esc(CSRF_TOKEN)}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<button class='btn' type='submit'>키 지우기</button></form>")

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
        "<button class='btn' type='submit'>등급 기록</button>"
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
    if _STORE is None:
        return [dict(t) for t in TRIPS]
    return _STORE.list_trips(include_archived=include_archived)


def valid_tab_ids() -> set:
    return {t["tab_id"] for t in live_trips(include_archived=True)}


def _all_tab_ids() -> list:
    return [t["tab_id"] for t in live_trips(include_archived=True)]


def _with_display_amount(rows):
    if _STORE is None:
        return rows
    for r in rows:
        if "display_amount_krw" not in r:
            projected = _STORE.projected(r)
            r["display_amount_krw"] = projected["display_amount_krw"]
            r["display_occurred_on"] = projected["display_occurred_on"]
        elif "display_occurred_on" not in r:
            r["display_occurred_on"] = _STORE.display_occurred_on(r)
    return rows


def _shown_date(row) -> str:
    return row.get("display_occurred_on", row["occurred_on"])


def _expense_rows():
    if _STORE is None:
        return [dict(r) for r in EXPENSES]
    seen = {r["row_id"] for r in EXPENSES}
    out = []
    for r in EXPENSES:
        saved = _STORE.get_row(r["row_id"])
        out.append(saved if saved is not None else dict(r))
    for tab in _all_tab_ids() + [None]:
        for saved in _STORE.list_tab_rows(tab):
            if saved["row_kind"] == "expense" and saved["row_id"] not in seen:
                seen.add(saved["row_id"])
                out.append(saved)
    return _with_display_amount(out)


def _income_rows():
    if _STORE is None:
        return [dict(r) for r in INCOMES]
    out = []
    for r in INCOMES:
        saved = _STORE.get_row(r["row_id"])
        out.append(saved if saved is not None else dict(r))
    if _STORE is not None:
        seen = {r["row_id"] for r in INCOMES}
        for tab in _all_tab_ids() + [None]:
            for saved in _STORE.list_tab_rows(tab):
                if saved["row_kind"] == "income" and saved["row_id"] not in seen:
                    seen.add(saved["row_id"])
                    out.append(saved)
    return _with_display_amount(out)


def _trip_totals(tab_id: str):
    if _STORE is None:
        return {
            "income": trip_income_total(tab_id),
            "expense": trip_expense_total(tab_id),
            "profit": trip_profit(tab_id),
        }
    return _STORE.tab_totals(tab_id)


def _unclassified_rows():
    return [r for r in _expense_rows() if r["display_tab_id"] is None]


def _income_total(rows) -> int:
    linked = _STORE.linked_bank_row_ids() if _STORE is not None else set()
    return sum(
        _shown_amount(r) for r in rows if r["row_id"] not in linked
    )

SYNTHETIC_MARK = "합성 자료"

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


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def trip_income_total(tab_id: str) -> int:
    return sum(r["amount_krw"] for r in INCOMES if r["display_tab_id"] == tab_id)


def trip_expense_total(tab_id: str) -> int:
    return sum(r["amount_krw"] for r in EXPENSES if r["display_tab_id"] == tab_id)


def trip_profit(tab_id: str) -> int:
    return trip_income_total(tab_id) - trip_expense_total(tab_id)


def customer_total(customer_id: str, tab_id: str) -> int:
    return sum(
        r["amount_krw"]
        for r in INCOMES
        if r["customer_id"] == customer_id and r["display_tab_id"] == tab_id
    )


def unclassified_expenses():
    return [r for r in EXPENSES if r["display_tab_id"] is None]


def unclassified_total() -> int:
    return sum(r["amount_krw"] for r in unclassified_expenses())


def find_row(row_id: str):
    if _STORE is not None:
        allocation = _STORE.get_allocation_display(row_id)
        if allocation is not None:
            return ("income", allocation)
    for r in _expense_rows():
        if r["row_id"] == row_id:
            return ("expense", r)
    for r in _income_rows():
        if r["row_id"] == row_id:
            return ("income", r)
    if _STORE is not None:
        hidden = _STORE.get_row(row_id)
        if hidden is not None:
            hidden["display_amount_krw"] = _STORE.display_amount(hidden)
            hidden["display_occurred_on"] = _STORE.display_occurred_on(hidden)
            return (hidden["row_kind"], hidden)
    return (None, None)


def split_page(source_id: str) -> str:
    from . import ledger_design

    if _STORE is None:
        return ledger_design.render(ledger_design.shell(
            '배분 추정', tab_id='', heading='배분 추정',
            body="<div class='sect'><p>저장소가 연결되지 않았어요.</p></div>"))
    source = _STORE.get_row(source_id)
    if source is None or source["row_kind"] != "income":
        return ledger_design.render(ledger_design.shell(
            '배분 편집', tab_id='', heading='배분 편집',
            body="<div class='sect'><p>없는 수입 행이에요.</p></div>"))
    reflected = _STORE.display_amount(source)
    allocs = _STORE.active_allocations(source_id)
    remainder = reflected - sum(a["amount_krw"] for a in allocs)
    def tab_options(current):
        cur = current or "unclassified"
        out = (
            f"<option value='unclassified'{' selected' if cur == 'unclassified' else ''}>"
            "분류대기(미배정 배분)</option>"
        )
        for t in live_trips():
            selected = " selected" if cur == t["tab_id"] else ""
            out += f"<option value='{esc(t['tab_id'])}'{selected}>{esc(t['display_key'])}</option>"
        return out
    rows_html = ""
    for i, a in enumerate(list(allocs) + [{}, {}]):
        aid = a.get("allocation_id", "")
        rows_html += (
            f"<tr><td data-label='배분 ID'>"
            f"<input name='alc_{i}_id' value='{esc(aid)}' readonly></td>"
            f"<td data-label='고객'>"
            f"<input name='alc_{i}_customer' value='{esc(a.get('customer_name', ''))}'></td>"
            f"<td data-label='여행'>"
            f"<select name='alc_{i}_tab'>{tab_options(a.get('display_tab_id'))}</select></td>"
            f"<td data-label='종류'><select name='alc_{i}_kind'>"
            + "".join(
                f"<option value='{k}'{' selected' if a.get('income_kind') == k else ''}>"
                f"{esc(INCOME_KIND_LABEL[k])}</option>"
                for k in ("deposit", "balance", "additional")
            ) +
            "</td>"
            f"<td data-label='금액'>"
            f"<input name='alc_{i}_amount' value='{esc(a.get('amount_krw', ''))}'>"
            "</td></tr>"
        )
    principal_fields = ""
    if source.get("source_kind") == "직접 입력":
        principal_fields = (
            "<p><label>원금(선택, 배분안과 함께 저장)</label>"
            f"<input name='new_principal_amount' value='{source['amount_krw']}'></p>"
            "<p class='muted'>은행 원천은 정정 경로에서 배분안과 함께 조정해요.</p>"
        )
    body = (
        "<div class='sect'><h2>입금 나누기</h2>"
        f"<p>원천 입금액 {source['amount_krw']:,}원 · 현재 장부 반영액 {reflected:,}원 · "
        f"배분한 금액 {reflected - remainder:,}원 · 남은 금액 {remainder:,}원</p>"
        f"<form method='post' action='/api/income/{esc(source_id)}/allocations'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='expected_source_revision' value='{source['revision']}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<input type='hidden' name='row_count' value='{len(allocs) + 2}'>"
        f"{principal_fields}"
        "<table class='alloc'>"
        "<colgroup><col style='width:150px'><col><col style='width:230px'>"
        "<col style='width:120px'><col style='width:140px'></colgroup>"
        "<thead><tr><th scope='col'>배분 ID</th><th scope='col'>고객</th>"
        "<th scope='col'>여행</th><th scope='col'>종류</th><th scope='col'>금액</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
        "<p class='muted'>금액이 빈 행은 제외돼요. 합계가 반영액을 넘으면 저장하지 않아요. "
        "같은 입금의 배분 표시 날짜는 원천 날짜를 함께 써요.</p>"
        "<button type='submit'>배분안 저장</button></form>"
        f"<p><a href='/row?id={esc(source_id)}'>원천 상세로</a></p></div>"
    )
    return ledger_design.render(ledger_design.shell(
        '배분 추정', tab_id='', heading='배분 추정', body=body))


def history_html(row_id: str) -> str:
    if _STORE is None:
        return ""
    items = _STORE.list_history(row_id)
    if not items:
        return "<h3>변경 이력</h3><p class='muted'>직접 수정된 변경이 없어요</p>"
    lis = "".join(
        f"<li>rev {h['revision']} · {esc(h['change_mode'])} · {esc(h['actor'])} · "
        f"{esc(h['created_at'])} · 요청 {esc(h['event_id'] or '감사 기록 없음')}</li>"
        for h in items
    )
    # APP_SPEC 9 lists `충돌` among the states told apart in the row detail, and
    # DETAILED 3.2 says the row edit screen shows the conflict with a way to
    # re-edit from the latest revision. A conflict clears on the next save.
    conflict_html = ""
    try:
        conflict = _STORE.row_conflict(row_id)
    except Exception:
        conflict = None
    if conflict:
        conflict_html = (
            "<h3>충돌</h3><p class='muted'>revision "
            f"{esc(str(conflict.get('expected_revision')))}로 저장을 시도했지만 "
            f"이 행은 revision {esc(str(conflict.get('current_revision')))}까지 "
            "바뀌었습니다. 이 저장은 장부에 반영되지 않았습니다. "
            "최신 값을 확인한 뒤 다시 저장해 주세요.</p>")
    status = _STORE.revert_status(row_id)
    if status["revertible"]:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<form method='post' action='/api/rows/{esc(row_id)}/revert'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{items[-1]['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<button type='submit'>직전 수정 되돌리기</button></form>"
        )
    else:
        revert_html = (
            "<h3>직전 수정 되돌리기</h3>"
            f"<p class='muted'>{esc(status['reason'])}</p>"
        )
    return (f"<h3>변경 이력</h3><ul>{lis}</ul>{conflict_html}{revert_html}")


def allocation_revert_status(allocation):
    from .ledger_store import SaveError

    if allocation is None:
        return {"revertible": False, "reason": "없는 배분 행이에요"}
    stored = _STORE.get_allocation(allocation["row_id"])
    if stored is not None:
        allocation = {**allocation, **stored}
    if not allocation.get("active"):
        return {"revertible": False, "reason": "비활성 배분은 되돌릴 수 없어요"}
    source = _STORE.get_row(allocation["source_row_id"])
    if source is None:
        return {"revertible": False, "reason": "원천 입금 행이 없어요"}
    if source["revision"] != allocation["source_revision"]:
        return {"revertible": False, "reason": "원천 입금이 바뀌어서 최신 상태를 확인해 주세요"}
    try:
        changes, history = _STORE._allocation_revert_changes(allocation)
    except SaveError as exc:
        return {"revertible": False, "reason": str(exc)}
    return {
        "revertible": True,
        "reason": None,
        "changes": changes,
        "expected_source_revision": source["revision"],
        "history": history,
    }


def allocation_history_html(allocation) -> str:
    rows = _STORE.conn.execute(
        "SELECT created_at, client_request_id, reverts_event_id, event_id"
        " FROM income_allocation_history WHERE allocation_id=? ORDER BY id DESC",
        (allocation["row_id"],),
    ).fetchall()
    items = "".join(
        f"<li>{esc(created_at)} · 요청 {esc(request_id)} · "
        f"사건 {esc(event_id or '대기')} · 되돌림 대상 {esc(reverts_event_id or '-')}</li>"
        for created_at, request_id, reverts_event_id, event_id in rows
    )
    status = allocation_revert_status(allocation)
    if status["revertible"]:
        changes = " · ".join(
            f"{esc(field)}={esc(value)}"
            for field, value in sorted(status["changes"].items())
        )
        revert_html = (
            "<h3>이 배분 행 되돌리기</h3>"
            f"<p class='muted'>되돌릴 값: {changes}</p>"
            f"<form method='post' action='/api/rows/{esc(allocation['row_id'])}/revert'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{status['expected_source_revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<button type='submit'>이 배분 행 되돌리기</button></form>"
        )
    else:
        revert_html = (
            "<h3>이 배분 행 되돌리기</h3>"
            f"<p class='muted'>{esc(status['reason'])}</p>"
        )
    history = f"<ul>{items}</ul>" if items else "<p class='muted'>아직 이 배분 행의 변경 이력이 없어요.</p>"
    return f"<h3>배분 행 변경 이력</h3>{history}{revert_html}"


def allocation_detail_body(allocation, edit: bool) -> str:
    source = _STORE.get_row(allocation["source_row_id"])
    reflected = _STORE.display_amount(source) if source is not None else 0
    trips = list(live_trips(include_archived=True))
    current_tab = allocation.get("display_tab_id")
    if current_tab is not None and not any(t["tab_id"] == current_tab for t in trips):
        trips.append({"tab_id": current_tab, "display_key": "삭제된 여행"})
    tab_options = (
        "<option value='unclassified'"
        f"{' selected' if current_tab is None else ''}>분류대기(미배정 배분)</option>"
        + "".join(
            f"<option value='{esc(t['tab_id'])}'"
            f"{' selected' if current_tab == t['tab_id'] else ''}>{esc(t['display_key'])}</option>"
            for t in trips
        )
    )
    kind_options = "".join(
        f"<option value='{kind}'{' selected' if allocation.get('income_kind') == kind else ''}>"
        f"{esc(INCOME_KIND_LABEL[kind])}</option>"
        for kind in ("deposit", "balance", "additional")
    )
    if edit:
        form = (
            "<h3>배분 행 편집</h3>"
            f"<form method='post' action='/api/rows/{esc(allocation['row_id'])}/save'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{source['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<p><label>고객 ID</label><input name='customer_id' value='{esc(allocation.get('customer_id') or '')}'></p>"
            f"<p><label>고객 이름</label><input name='customer_name' value='{esc(allocation.get('customer_name', ''))}'></p>"
            f"<p><label>닉네임</label><input name='nickname' value='{esc(allocation.get('nickname', ''))}'></p>"
            f"<p><label>여행</label><select name='display_tab_id'>{tab_options}</select></p>"
            f"<p><label>입금 종류</label><select name='income_kind'>{kind_options}</select></p>"
            f"<p><label>거래일자</label><input value='{esc(allocation['occurred_on'])}' readonly></p>"
            f"<p><label>배분 금액</label><input value='{esc(allocation['amount_krw'])}' readonly></p>"
            "<p class='muted'>고객 정보·여행·입금 종류만 바꿀 수 있어요. 날짜와 금액은 전체 배분 편집에서 원천 규칙에 따라 조정해요.</p>"
            "<button type='submit'>배분 행 저장</button> "
            f"<a href='/row?id={esc(allocation['row_id'])}'>취소</a></form>"
        )
    else:
        form = f"<p><a href='/row?id={esc(allocation['row_id'])}&edit=1'>배분 행 편집</a></p>"
    links = (
        f"<p><a href='/income/{esc(allocation['source_row_id'])}/split'>전체 배분안 편집</a> · "
        f"<a href='/row?id={esc(allocation['source_row_id'])}'>원천 상세</a></p>"
    )
    return (
        f"<h2>입금 배분 {esc(allocation.get('customer_name', ''))} {_shown_amount(allocation):,}원</h2>"
        f"<ul><li>배분 ID: {esc(allocation['row_id'])}</li>"
        f"<li>원천 입금 {reflected:,}원 중 이 배분 {_shown_amount(allocation):,}원</li>"
        f"<li>입금 종류: {esc(INCOME_KIND_LABEL.get(allocation.get('income_kind'), ''))}</li></ul>"
        f"{form}{links}{allocation_history_html(allocation)}"
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
    for t in live_trips():
        if query and query not in (t["display_key"] + t["destination"]):
            continue
        cls = "tab sel" if t["tab_id"] == selected else "tab"
        totals = _trip_totals(t["tab_id"])
        items.append(
            f"<a class='{cls}' href='/board?tab={esc(t['tab_id'])}'>"
            f"<div>{esc(t['display_key'])}</div>"
            f"<div class='amt'>{totals['income']:,}원</div>"
            f"<small>지출 {totals['expense']:,}원</small></a>"
        )
    if _STORE is not None:
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
    if not query or query in "분류대기":
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
        head = "<h2>분류대기</h2><p class='muted'>분류를 기다리는 내역이에요. 전체 장부가 확정됐다는 뜻이 아니에요.</p>"
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
        linked = _STORE.linked_bank_row_ids() if _STORE is not None else set()
        billed = [r for r in incomes if r["row_id"] not in linked]
        customers = sorted({r["customer_id"] for r in billed})
        cust_lines = "".join(
            f"<div>{esc(next(r['customer_name'] for r in billed if r['customer_id'] == c))} "
            f"({esc(c)}): <b>{sum(_shown_amount(r) for r in billed if r['customer_id'] == c):,}원</b></div>"
            for c in customers
        )
        head = f"<h2>{esc(trip['display_key'])} <span class='muted'>{esc(trip['starts_on'])}~{esc(trip['ends_on'])}</span></h2>"
        meta_line = ""
        if _STORE is not None and trip.get("prepared_on"):
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
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
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
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
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


def expense_new_page() -> str:
    options = "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t['display_key'])}</option>" for t in live_trips()
    )
    top = (
        "<div class='top'><h1>웹 장부"
        f"<span class='synth'>{SYNTHETIC_MARK}</span></h1>"
        "<p><a href='/board'>장부</a> · <a href='/import'>카드 가져오기</a> · "
        "<a href='/export'>선택 탭 출력</a> · <a href='/trips'>여행 관리</a></p></div>"
    )
    body = (
        "<div class='body'><h2>수기 지출 추가 (현금·계좌이체)</h2>"
        f"<form method='post' action='/api/expenses/manual'>"
        f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<p><label>여행</label><select name='display_tab_id'>{options}</select></p>"
        "<p><label>거래일자</label><input name='occurred_on' placeholder='2026-04-01'></p>"
        "<p><label>지급 수단</label><select name='pay_method'>"
        "<option value='현금'>현금</option><option value='계좌이체'>계좌이체</option></select></p>"
        "<p><label>항목</label><input name='item'></p>"
        "<p><label>내용</label><input name='description'></p>"
        "<p><label>금액(원, 환불은 음수)</label><input name='amount_krw'></p>"
        "<p><label>메모</label><input name='operator_note'></p>"
        "<button type='submit'>저장</button></form></div>"
    )
    return layout("수기 지출 추가", f"{top}<div class='wrap'>{body}</div>")


RULE_MODE_LABEL = SYNTHETIC_MODE_NOTE


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

    if _STORE is None:
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body="<div class='sect'><p>저장소가로 연결되지 않아요.</p></div>"))
    state = _STORE.dialog_page_state(case_id)
    row = _STORE.get_row(state["row_id"]) if state.get("row_id") else None
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

    # 합성 턴
    turn_no = (conv.get("turn_count") or 0) + 1
    parts.append(
        "<form method='post' action='/api/classification/conversation/advance'>"
        + _rule_hidden(case_id, f"ui-turn-{case_id}-{turn_no:02d}")
        + "<button class='btn' type='submit'>규칙 초안 요청 (합성 턴)</button></form>")
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
            f" · {esc(rule['status'])}</p>")
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

    if not role:
        # Called without a request (local single-user mode, and the tests that
        # exercise this page directly). Under enforcement the route always
        # passes the role it decided on the server, so nothing is guessed here.
        role = "viewer" if ACCESS_ENFORCEMENT else "owner"
    if _STORE is None:
        body = "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>"
        return layout("여행 관리", f"{top}<div class='wrap'>{body}</div>")
    cards = []
    for t in live_trips(include_archived=True):
        if t.get("deleted"):
            continue
        try:
            kind = "보관됨" if t["archived"] else "활성"
            preview = _STORE.preview_tab_delete(t["tab_id"])
            counts = (f"수입 {preview['income_count']}건 {preview['income_total']:,}원 · "
                      f"지출 {preview['expense_count']}건 {preview['expense_total']:,}원")
        except Exception as exc:
            counts = f"조회 실패: {esc(str(exc))}"
        cards.append(
            "<div class='card'>"
            f"<h3>{esc(t['display_key'])} <span class='muted'>{kind}</span></h3>"
            f"<p class='muted rev-note'>여행 revision {t['revision']}</p>"
            f"<p class='muted'>{esc(t['starts_on'])}~{esc(t['ends_on'])} · {esc(t['destination'])}</p>"
            f"<p class='muted'>작성일 {esc(t['prepared_on'])} · 담당자 {esc(t['prepared_by_name'])}</p>"
            # APP_SPEC 3 keeps the schedule authority and the tab kind apart from
            # the display name, so the screen states them rather than implying
            # them through the name.
            f"<p class='muted'>연도 {esc(str(t.get('event_year') or ''))} · "
            f"종류 {esc(t.get('tab_kind') or 'trip')} · "
            f"권위 {esc(AUTHORITY_LABELS.get(t.get('authority_status'), '미확정'))}</p>"
            f"<p>{counts}</p>"
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            f"<p><label>표시 이름</label><input name='display_key' value='{esc(t['display_key'])}'></p>"
            f"<p><label>작성일</label><input name='prepared_on' value='{esc(t['prepared_on'])}'></p>"
            f"<p><label>담당자</label><input name='prepared_by_name' value='{esc(t['prepared_by_name'])}'></p>"
            "<button type='submit'>정보 저장</button></form>"
            f"<form method='post' action='/api/trips/{esc(t['tab_id'])}/meta'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='expected_revision' value='{t['revision']}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            f"<input type='hidden' name='archived' value='{'0' if t['archived'] else '1'}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            f"<button type='submit'>{'복원' if t['archived'] else '보관'}</button></form>"
            f"<p><a href='/trips?preview_tab={esc(t['tab_id'])}'>삭제 미리보기</a></p>"
            "</div>"
        )
    # APP_SPEC 3: the `새 탭 추가` screen takes 날짜 and 행선지 and makes a new
    # internal tab_id. It is an owner action, so the form is not rendered for a
    # viewer at all (SPEC 15.3 returns the fields a viewer needs rather than
    # hiding fields inside an owner response), and the endpoint refuses the
    # write itself.
    create_html = ""
    if role == "owner":
        create_html = (
            "<div class='card'><h3>새 탭 추가</h3>"
            "<form method='post' action='/api/tabs' id='new-trip-form'>"
            f"<input type='hidden' name='csrf' value='{CSRF_TOKEN}'>"
            f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
            "<input type='hidden' name='return_to' value='/trips'>"
            "<p><label>날짜</label>"
            "<input name='starts_on' placeholder='YYYY-MM-DD' required></p>"
            "<p><label>행선지</label>"
            "<input name='destination' required></p>"
            "<p><label>종료일</label>"
            "<input name='ends_on' placeholder='YYYY-MM-DD'></p>"
            # 4.2 lists 탭 종류 and 일정 근거 as part of this dialog.
            "<p><label>탭 종류</label><select name='tab_kind'>"
            "<option value='trip'>여행</option>"
            "<option value='overhead'>기타비용</option>"
            "<option value='closing'>종결</option>"
            "<option value='other'>그 외</option></select></p>"
            "<p><label>일정 근거 해시</label>"
            "<input name='source_sha256' placeholder='권위 일정 원천의 sha256 (64자, 없으면 비움)'></p>"
            "<p class='muted'>같은 날짜와 행선지의 여행이 이미 있으면 그 여행을 "
            "보여 줍니다. 두 여행을 합칠지는 자동으로 결정하지 않습니다. "
            "일정 근거가 없는 탭은 자동 확정하지 않고 검토 필요로 남기며, "
            "화면에서 탭을 만든다고 권위 일정이 권위가 있는 것으로 바뀌지 않습니다."
            "</p>"
            "<button type='submit'>여행 추가</button></form></div>"
        )
    preview_html = ""
    if preview_tab:
        try:
            preview = _STORE.preview_tab_delete(preview_tab)
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
                "<button type='submit'>내역 이동 후 삭제 확정</button></form>"
                "<p class='muted'>원천·이력·과거 출력은 지우지 않고 화면 탭만 없앱니다. "
                "확정 시점에 장부가 바뀌었으면 처음부터 다시 확인합니다.</p></div>"
            )
        except Exception as exc:
            preview_html = f"<div class='card'><p>미리보기 실패: {esc(str(exc))}</p></div>"
    body = (f"<div class='sect'><h2>여행 관리</h2>{create_html}{preview_html}"
            f"{''.join(cards)}</div>")
    return ledger_design.render(ledger_design.shell(
        "여행 관리", tab_id="", heading="여행 관리", body=body))


def export_page() -> str:
    options = "".join(
        f"<label><input type='checkbox' name='tab_ids' value='{esc(t['tab_id'])}' checked> "
        f"{esc(t['display_key'])}</label><br>" for t in live_trips()
    )
    archived = ""
    if _STORE is not None:
        arch = [t for t in live_trips(include_archived=True) if t["archived"]]
        if arch:
            archived = "<h3>보관된 여행</h3>" + "".join(
                f"<label><input type='checkbox' name='tab_ids' value='{esc(t['tab_id'])}'> "
                f"{esc(t['display_key'])} (보관)</label><br>" for t in arch
            )
    counts = ""
    progress_note = ""
    jobs_html = ""
    if _STORE is not None:
        from .card_import import CardImporter

        lines = []
        for t in live_trips(include_archived=True):
            rows = _STORE.list_tab_rows(t["tab_id"])
            inc = sum(1 for r in rows if r["row_kind"] == "income")
            exp = sum(1 for r in rows if r["row_kind"] == "expense")
            lines.append(
                f"<li>{esc(t['display_key'])}: 수입 {inc}행 · 지출 {exp}행"
                + (" (보관)" if t["archived"] else "") + "</li>")
        unc = _STORE.list_tab_rows(None)
        unc_inc = sum(1 for r in unc if r["row_kind"] == "income")
        unc_exp = sum(1 for r in unc if r["row_kind"] != "income")
        lines.append(f"<li>분류대기: 수입 {unc_inc}행 · 지출 {unc_exp}행 (출력에 들어가지 않아요)</li>")
        counts = f"<ul>{''.join(lines)}</ul>"
        # APP_SPEC 8 asks the dialog to state the 검토필요 and 충돌 row counts.
        # Both are read off the ledger: a row needs a person when it has no trip
        # or no recorded classification basis, and it is in conflict when the
        # row's newest ledger event is a conflict note.
        review_total = 0
        conflict_total = 0
        per_tab = []
        for t in live_trips(include_archived=True):
            trows = _STORE.list_tab_rows(t["tab_id"])
            n_review = sum(1 for r in trows if row_needs_review(r))
            n_conflict = sum(1 for r in trows if row_has_conflict(r))
            review_total += n_review
            conflict_total += n_conflict
            if n_review or n_conflict:
                per_tab.append(
                    f"<li>{esc(t['display_key'])}: 검토필요 {n_review}행"
                    + (f" · 충돌 {n_conflict}행" if n_conflict else "")
                    + "</li>")
        n_unc_review = sum(1 for r in unc if row_needs_review(r))
        n_unc_conflict = sum(1 for r in unc if row_has_conflict(r))
        review_note = (
            "<p class='muted'>검토필요 {review}행 · 충돌 {conflict}행"
            "은(는) 화면의 현재 내용 그대로 출력합니다. "
            "미확정인 행을 출력한다고 원래 회계 상태나 확정 여부가 바뀌지 않습니다."
            "</p>").format(review=review_total + n_unc_review,
                           conflict=conflict_total + n_unc_conflict)
        if per_tab:
            review_note += f"<ul class='muted'>{''.join(per_tab)}</ul>"
        try:
            importer = CardImporter(_STORE.conn, _STORE)
            states = set()
            for (batch_id,) in _STORE.conn.execute(
                    "SELECT batch_id FROM card_import_batches").fetchall():
                progress = importer.progress(batch_id)
                if progress:
                    states.add(progress["status"])
            if "reconciling" in states or "parsing" in states:
                progress_note = ("<p class='muted'>내역을 가져오는 중입니다. "
                                 "현재 저장된 내용만 포함합니다.</p>")
        except Exception:
            pass
        from .sheets_export import list_jobs

        jobs = list_jobs(_STORE.conn)
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
        "<p class='muted'>저장된 장부 버전으로 출력해요. 미저장 초안은 서버에 없어서 섞이지 않아요. "
        "미확정 행도 화면대로 들어가고 파일에는 상태 표시를 넣지 않아요.</p>"
        f"{progress_note}"
        "<button type='submit'>출력</button></form>"
        f"<h3>범위 안내</h3>{counts}"
        f"{jobs_html}"
        f"<p class='muted'>양식 {esc('매출자료 양식_rev')} 구조를 복제해요. 회사·제목·작성 정보는 합성 예시예요.</p></div>"
    )
    from . import ledger_design

    return ledger_design.render(ledger_design.shell(
        '선택 탭 출력', tab_id='', heading='선택 탭 출력', body=body))


def import_page() -> str:
    from . import ledger_design

    body = (
        "<div class='sect'><h2>카드 가져오기 (합성 프로필)</h2>"
        "<p class='muted'>합성 CSV만 받아요. 실제 카드 파일 형식은 프로필 확인 뒤에 연결해요.</p>"
        f"<input type='file' id='f' accept='.csv'>"
        f"<button id='up'>올리기</button><p id='msg' class='muted'></p>"
        "<div id='res'></div>"
        "<h2>은행 가져오기 (합성 프로필)</h2>"
        "<p class='muted'>합성 은행 CSV만 받아요. 실제 은행 양식은 확인 뒤에 연결해요. 출금은 수입으로 올리지 않아요.</p>"
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
    return row.get("display_amount_krw", row["amount_krw"])


def income_table(rows) -> str:
    trs = "".join(
        f"<tr><td>{esc(_shown_date(r))}</td><td>{esc(r['customer_name'])}</td>"
        f"<td>{esc(r['nickname'])}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'deposit' else ''}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'balance' else ''}</td>"
        f"<td class='num'>{_shown_amount(r) if r['income_kind'] == 'additional' else ''}</td>"
        f"<td class='num'>{_shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>수입 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>이름</th><th>닉네임</th><th>예약금</th><th>잔금</th>"
        f"<th>추가금</th><th>금액</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 입력한 입금이 없어요</td></tr>")


def expense_table(rows) -> str:
    trs = "".join(
        f"<tr><td>{esc(_shown_date(r))}</td><td>{esc(r['item'])}</td>"
        f"<td>{esc(r['description'])}</td><td>{esc(r['service_period'])}</td>"
        f"<td style='font-family:monospace'>{esc(r['reservation_no'])}</td>"
        f"<td>{esc(r['evidence_type'])}</td><td class='num'>{_shown_amount(r):,}</td>"
        f"<td><a href='/row?id={esc(r['row_id'])}'>상세</a> "
        f"<a href='/row?id={esc(r['row_id'])}&edit=1'>편집</a></td></tr>"
        for r in rows
    )
    return (
        "<div class='card'><h3>지출 내용</h3><div class='scrollx'><table>"
        "<tr><th>거래일자</th><th>항목</th><th>내용</th><th>기간</th><th>예약번호</th>"
        f"<th>증빙유형</th><th>금액(원)</th><th></th></tr>{trs}</table></div></div>"
    ).format(trs=trs if trs else "<tr><td colspan='8' class='muted'>아직 연결된 지출이 없어요</td></tr>")


def editable_fields(kind: str, source: str, is_allocation: bool = False):
    """The (changeable, fixed) field names for a row.

    The save endpoint and the edit form both read this, so the form can never
    offer a field the endpoint would refuse.
    """
    if is_allocation:
        # An allocation row refuses anything outside its own list, so it has no
        # separate fixed list to publish.
        return (("customer_id", "customer_name", "nickname",
                 "display_tab_id", "income_kind"), ())
    if kind == "expense" and source in ("카드", ""):
        return (("display_tab_id", "item", "description", "operator_note"),
                ("amount_krw", "occurred_on", "source_event_id", "source_kind",
                 "merchant", "reservation_no"))
    if kind == "expense":
        return (("display_tab_id", "item", "description", "operator_note",
                 "occurred_on", "amount_krw"),
                ("source_event_id", "source_kind", "merchant", "reservation_no"))
    if source == "은행":
        return (("customer_id", "customer_name", "nickname",
                 "display_tab_id", "operator_note", "income_kind"),
                ("amount_krw", "occurred_on", "source_event_id", "source_kind"))
    return (("display_tab_id", "income_kind", "customer_id", "customer_name",
             "nickname", "occurred_on", "amount_krw", "operator_note"),
            ("source_event_id", "source_kind"))


def learning_case_id(row_id: str) -> str:
    """The newest learning case of a row, or an empty string."""
    if _STORE is None:
        return ""
    try:
        found = _STORE.conn.execute(
            "SELECT case_id FROM board_learning_cases WHERE row_id=?"
            " ORDER BY created_at DESC LIMIT 1", (row_id,)).fetchone()
    except Exception:
        return ""
    return "" if found is None else found[0]


def rule_dialog_link(row_id: str) -> str:
    """Small link to the rule dialog when the row has a learning case."""
    case_id = learning_case_id(row_id)
    if not case_id:
        return ""
    return f"<p><a href='/rules?case={esc(case_id)}'>규칙 대화 열기</a></p>"


def detail_page(row_id: str, edit: bool = False) -> str:
    kind, row = find_row(row_id)
    from . import ledger_design

    if row is None:
        return layout("행 없음", "<div class='top'><h1>웹 장부</h1></div><div class='body'><p>행이 없어요. 목록으로 돌아가 주세요.</p></div>")
    from . import ledger_design

    if row.get("is_allocation") and _STORE is not None:
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
            if _STORE is None:
                form = (
                    "<h3>행 편집 (저장 준비 중)</h3>"
                    "<p class='muted'>저장소가 연결되지 않았어요. 서버를 작업 DB와 함께 실행해 주세요.</p>"
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
        if _STORE is not None and row.get("source_kind") == "은행":
            corrections = _STORE.list_corrections(row_id)
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
        elif _STORE is not None and row.get("source_kind") == "직접 입력":
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
            links = _STORE.conn.execute(
                "SELECT bank_batch_id, bank_row_index FROM income_source_links WHERE row_id=?",
                (row_id,),
            ).fetchall()
            link_lines = "".join(
                f"<li>은행 원천 {esc(b)} #{i}</li>" for b, i in links
            )
            link_info = f"<h3>연결된 은행 원천</h3><ul>{link_lines}</ul>" if link_lines else ""
            candidates = _STORE.find_bank_candidates(row_id)
            cand_lines = "".join(
                f"<li>{esc(c['occurred_on'])} · {esc(c['customer_name'])} · "
                f"{c['amount_krw']:,}원 · {esc(c['row_id'])}</li>"
                for c in candidates
            )
            cand_info = (
                "<h3>중복 후보(미확정, 합산 제외 아님)</h3><ul>{cand_lines}</ul>"
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
        if _STORE is not None:
            if row.get("is_allocation"):
                source = _STORE.get_row(row["source_row_id"])
                reflected = _STORE.display_amount(source) if source else 0
                extra = (
                    "<h3>한 입금에서 배분된 내역</h3>"
                    f"<p class='muted'>원천 입금 {reflected:,}원 중 이 배분 {_shown_amount(row):,}원. "
                    "배분액은 배분 편집에서만 바꿔요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a> · "
                    f"<a href='/row?id={esc(row['source_row_id'])}'>원천 상세</a></p>"
                )
            elif row.get("is_remainder"):
                source = _STORE.get_row(row["source_row_id"])
                reflected = _STORE.display_amount(source) if source else 0
                extra = (
                    "<h3>미배분 잔액</h3>"
                    f"<p class='muted'>원천 입금 반영액 {reflected:,}원 중 아직 나누지 않은 금액이에요. "
                    "독립 입금 사건이 아니에요.</p>"
                    f"<p><a href='/income/{esc(row['source_row_id'])}/split'>배분 편집 열기</a></p>"
                )
            elif row["row_id"] in _STORE.split_source_ids():
                allocs = _STORE.active_allocations(row["row_id"])
                remainder = _STORE.split_remainder(row["row_id"])
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
    "FIELD_READ_ONLY": 422,
    "INVALID_VALUE": 422,
    "TARGET_NOT_ASSIGNABLE": 422,
    "CSRF_REQUIRED": 403,
    "PREVIEW_STALE": 409,
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, text: str, code: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
        if tab != "unclassified" and tab not in valid_tab_ids():
            tab = "trip-demo-a" if "trip-demo-a" in valid_tab_ids() else ""
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

    def _send_json(self, value: dict, code: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
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

    def _phase7_get(self, parsed, query) -> None:
        """Server-side read decision for this request.

        SPEC 15.3: the session and the role are checked on the server for every
        read. A viewer gets its own trip list, and any trip it may not read
        answers 404 rather than 403.
        """
        from . import access_control

        session = require_session(self.headers)
        path = parsed.path

        # The access screens answer for both roles.
        if path == "/access/me":
            self._send_json(access_control_render_viewer_status(session, _ACCESS))
            return
        if path == "/access/admin":
            if not is_owner_session(session):
                # the account management screen is an owner action
                deny_for_viewer(action=True)
            self._send(access_control_render_owner_admin(session, _ACCESS))
            return
        if path == "/access/providers":
            if not is_owner_session(session):
                # configuring a provider key is an owner action
                deny_for_viewer(action=True)
            if _PROVIDER_CONFIG is None:
                self._send_json(
                    {"code": "PROVIDER_CONFIG_UNBOUND",
                     "message": "제공자 설정이 연결되지 않았어요"}, code=503)
                return
            self._send(access_control_render_provider_config(
                session, _PROVIDER_CONFIG.public_status()))
            return
        if path == "/access/rows":
            tab = query.get("tab", [""])[0]
            if not tab:
                deny_for_viewer()
            # An owner keeps the full board; a viewer only its own trips.
            if not is_owner_session(session):
                _ACCESS.require_view_tab(session.user_id, tab)
            rows = (_STORE.list_tab_rows(tab) if _STORE is not None else [])
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
            return
        if path.startswith("/evidence/preview/"):
            evidence_id = path.rsplit("/", 1)[-1]
            try:
                preview = _ACCESS.evidence_preview(user_id=session.user_id,
                                                  evidence_id=evidence_id)
            except access_control.AccessError:
                deny_for_viewer()
            self._send_json(preview)
            return
        if path.startswith("/evidence/original/"):
            # There is no original-evidence route for anyone on the board.
            deny_for_viewer()

        if is_owner_session(session):
            # An owner keeps every existing screen unchanged.
            return
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
            return
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
            return
        if path.startswith("/income/"):
            source_id = parts_value(path)
            row = _STORE.get_row(source_id) if _STORE is not None else None
            if row is None:
                deny_for_viewer()
            _ACCESS.require_view_tab(session.user_id,
                                     row.get("display_tab_id") or "")
            self._send(access_control_render_viewer_income(session, row))
            return
        deny_for_viewer()

    def _phase7_write(self, parsed, content_type: str, raw: bytes) -> bool:
        """Server-side write decision, taken before the body is dispatched.

        Returns True when the request was fully handled here. The session and
        the role come from the server; the user id in a body is never trusted
        (SPEC 16.1, 16.4).
        """
        from . import access_control

        session = require_session(self.headers)
        path = parsed.path
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
            self._send_json({
                "logged_out": True,
                "user_id": session.user_id,
                "session_generation": generation,
                "cache_namespace": session.cache_namespace(),
                "client_must_clear": ["selected_row", "cached_ledger_data",
                                      "cached_evidence"],
            })
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
                complete=bool(payload.get("complete", True)))
            self._send_json({"result": result})
            return True

        if is_owner_session(session):
            return False
        # Every other write is an owner capability: row saves, moves, the rule
        # dialogue, xlsx creation, job lookup, trip meta and imports. The
        # refusal is decided before the body reaches a handler, so it never
        # depends on whether the named resource exists.
        deny_for_viewer(action=True)

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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        resolve_role(self.headers)
        if ACCESS_ENFORCEMENT:
            try:
                self._phase7_get(parsed, query)
            except Exception as exc:
                self._phase7_refuse(exc)
                return
        if parsed.path in ("/", "/board"):
            from . import ledger_design

            tab = query.get("tab", ["trip-demo-a"])[0]
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
            fragment = ledger_design.page(
                tab, q, kind, row_id,
                message=query.get("msg", [""])[0],
                archived=query.get("arch", [""])[0])
            self._send(ledger_design.render(fragment))
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

            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
                return
            job = get_job(_STORE.conn, parsed.path.rsplit("/", 1)[-1])
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
                                  role=resolve_role(self.headers)))
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
            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            conversation_id = query.get("conversation_id", [""])[0]
            if not conversation_id:
                self._send_json({"code": "INVALID_VALUE", "message": "conversation_id required"}, code=422)
                return
            self._send_json(_STORE.conversation_state(conversation_id), code=200)
        elif parsed.path == "/api/classification/dialog":
            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            self._send_json(_STORE.rule_dialog_state(query.get("case_id", [""])[0]), code=200)
        elif parsed.path.endswith("/versions") and parsed.path.startswith(
                "/api/classification/rules/"):
            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "STORE_UNBOUND"}, code=503)
                return
            rule_id = parsed.path.split("/")[4]
            history = _STORE.rule_history(rule_id)
            if history["current"] is None and not history["versions"]:
                self._send_json({"code": "RESOURCE_NOT_FOUND",
                             "message": "없는 경로예요"}, code=404)
                return
            self._send_json(history, code=200)
        elif parsed.path == "/api/classification/rules":
            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
                return
            self._send_json({"rules": _STORE.list_rules()}, code=200)
        elif parsed.path.startswith("/api/classification/rules/"):
            if _STORE is None:
                self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
                return
            rule = _STORE.get_rule(parsed.path.rsplit("/", 1)[-1])
            if rule is None:
                self._send_json({"code": "RESOURCE_NOT_FOUND", "message": "없는 작업이어요"}, code=404)
                return
            self._send_json(rule, code=200)
        else:
            self._send(layout("없음", "<p>없는 주소예요.</p>"), code=404)

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
                           "/api/classification/conversation/confirm-draft",
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
            if len(parts) == 2 and parts[0] == "api" and parts[1] == "tabs":
                # APP_SPEC 10 names `POST /api/tabs` for tab creation, so that
                # is the one and only create path. `/api/trips/...` stays the
                # trip meta and delete family and does not create anything, so
                # no action answers at two URLs.
                # The owner boundary is not decided here. `_phase7_write` already
                # refuses a viewer on any write and asks a session-less caller to
                # log in again before this body is read, so this path answers
                # under the same rule as the tab paths that exist.
                self._handle_trip_create(read_payload, check_csrf, content_type)
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
        if _STORE is None:
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
                result = _STORE.update_allocation(
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
            result = _STORE.save(
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
            result = _STORE.create_direct_income(
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
            result = _STORE.create_manual_expense(
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

        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        token = self.headers.get("X-CSRF-Token") or ""
        if token != CSRF_TOKEN:
            self._send_json({"code": "CSRF_REQUIRED", "message": "확인 토큰이 없어요"}, code=403)
            return
        try:
            importer = BankImporter(_STORE.conn, _STORE)
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
                _STORE.update_rule_dialog_note(
                    learning_case_id=case_id, note=str(form.get("note") or ""),
                    client_request_id=request_id, actor="owner")
                message = "근거 설명을 저장했습니다"
            elif path.endswith("/dialog/answer"):
                _STORE.answer_rule_question(
                    question_id=str(form.get("question_id") or ""),
                    answer=str(form.get("answer") or ""),
                    expected_row_revision=int(form.get("expected_row_revision") or 0),
                    client_request_id=request_id, actor="owner")
                message = "답변을 저장했습니다"
            elif path.endswith("/dialog/close"):
                _STORE.close_rule_dialog(learning_case_id=case_id,
                                         client_request_id=request_id, actor="owner")
                message = "대화를 닫았습니다. 다시 열면 답변이 유지됩니다"
            elif path.endswith("/dialog/resume"):
                _STORE.resume_rule_dialog(learning_case_id=case_id,
                                          client_request_id=request_id, actor="owner")
                message = "대화를 다시 열었습니다"
            elif path.endswith("/conversation/advance"):
                result = _STORE.advance_dialog_conversation(
                    learning_case_id=case_id, client_request_id=request_id,
                    muse=_MUSE, gemini=_GEMINI, actor="owner",
                    operator=_operator_choice(case_id, form))
                turn = result.get("turn") or {}
                if turn.get("state") == "answered":
                    message = (f"초안을 받았습니다 · 공급자 {turn.get('adopted_provider')}"
                               f" · 전환 {turn.get('switch_count')}회")
                else:
                    message = (f"AI 초안 대기 중입니다 · 사유 {turn.get('reason_code') or '-'}"
                               " · 행 저장과 확정 규칙 실행은 계속됩니다")
            elif path.endswith("/conversation/confirm-draft"):
                _STORE.confirm_dialog_draft(learning_case_id=case_id,
                                            client_request_id=request_id, actor="owner")
                message = "규칙 초안을 저장했습니다. 적용 범위를 고르고 적용해 주세요"
            elif path.endswith("/rules/preview"):
                result = _STORE.preview_rule(
                    rule_id=str(form.get("rule_id") or ""),
                    apply_existing=payload["apply_existing"],
                    apply_future=payload["apply_future"])
                counts = result.get("counts", {})
                message = (f"영향 미리보기: 포함 {counts.get('included_rows', 0)}건"
                           f" · 제외 {counts.get('excluded_rows', 0)}건")
            else:
                result = _STORE.apply_rule(
                    preview_id=str(form.get("preview_id") or ""),
                    apply_existing=payload["apply_existing"],
                    apply_future=payload["apply_future"],
                    selected_row_ids=payload.get("selected_row_ids"),
                    client_request_id=request_id, actor="owner")
                message = (f"적용했습니다 · {result.get('applied_count', 0)}건"
                           + (" · 미래 적용" if result.get("apply_future") else ""))
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

        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장이 연결되지 않어요"}, code=503)
            return
        try:
            payload = read_payload()
            check_csrf(payload)
            if path.endswith("/draft"):
                raw = payload.get("draft")
                result = _STORE.create_rule_draft(
                    draft=raw if isinstance(raw, dict) else {},
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/preview"):
                result = _STORE.preview_rule(
                    rule_id=str(payload.get("rule_id") or ""),
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")))
            elif path.endswith("/revise"):
                raw = payload.get("draft")
                result = _STORE.revise_rule(
                    rule_id=str(payload.get("rule_id") or ""),
                    draft=raw if isinstance(raw, dict) else {},
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/supersede"):
                result = _STORE.supersede_rule(
                    new_rule_id=str(payload.get("new_rule_id") or ""),
                    old_rule_id=str(payload.get("old_rule_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/scope"):
                result = _STORE.update_rule_scope(
                    rule_id=str(payload.get("rule_id") or ""),
                    apply_existing=_flag(payload.get("apply_existing")),
                    apply_future=_flag(payload.get("apply_future")),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/open"):
                result = _STORE.open_conversation(
                    learning_case_id=str(payload.get("learning_case_id")
                                         or payload.get("case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/turn"):
                # The body may not pick a provider. Adapters come from the
                # server binding only, and no key is accepted or stored.
                result = _STORE.run_dialog_turn(
                    conversation_id=str(payload.get("conversation_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    muse=_MUSE, gemini=_GEMINI, actor="owner")
            elif path.endswith("/conversation/late"):
                result = _STORE.adopt_late_response(
                    conversation_id=str(payload.get("conversation_id") or ""),
                    turn_id=str(payload.get("turn_id") or ""),
                    attempt_id=str(payload.get("attempt_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/note"):
                result = _STORE.update_rule_dialog_note(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    note=str(payload.get("note") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/conversation/advance"):
                result = _STORE.advance_dialog_conversation(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    muse=_MUSE, gemini=_GEMINI, actor="owner",
                    operator=_operator_choice(
                        str(payload.get("case")
                            or payload.get("learning_case_id") or ""), payload))
            elif path.endswith("/conversation/confirm-draft"):
                result = _STORE.confirm_dialog_draft(
                    learning_case_id=str(payload.get("case")
                                         or payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/open"):
                raw = payload.get("draft")
                result = _STORE.open_rule_dialog(
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
                result = _STORE.answer_rule_question(
                    question_id=str(payload.get("question_id") or ""),
                    answer=str(payload.get("answer") or ""),
                    expected_row_revision=expected_revision,
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/close"):
                result = _STORE.close_rule_dialog(
                    learning_case_id=str(payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            elif path.endswith("/dialog/resume"):
                result = _STORE.resume_rule_dialog(
                    learning_case_id=str(payload.get("learning_case_id") or ""),
                    client_request_id=str(payload.get("client_request_id") or ""),
                    actor="owner")
            else:
                selected = payload.get("selected_row_ids")
                if selected is not None and not isinstance(selected, list):
                    raise SaveError("INVALID_VALUE", "선택 한 목록이 다시어요")
                result = _STORE.apply_rule(
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
            result = _STORE.revert_row(
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
            result = _STORE.save_allocations(
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

        if _STORE is None:
            self._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, code=503)
            return
        job = get_job(_STORE.conn, job_id)
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
        from .sheets_export import (build_workbook, file_sha256, get_job,
                                    publish_workbook, record_job)

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
            existing = get_job(_STORE.conn, job_id)
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
            wb, manifest = build_workbook(_STORE, ordered)
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
            record_job(_STORE.conn, job_id=job_id, tab_ids=ordered,
                       manifest=manifest, status="ready")
            job = get_job(_STORE.conn, job_id)
        except SaveError as exc:
            self._send_json({"code": exc.code, "message": str(exc)},
                            code=STATUS_FOR_CODE.get(exc.code, 422))
            return
        if "application/json" in content_type:
            self._send_json(job, code=200)
        else:
            self.send_response(303)
            self.send_header("Location", f"/api/exports/{job_id}/download")
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
            for key in ("display_key", "prepared_on", "prepared_by_name"):
                if key in payload:
                    kwargs[key] = payload[key]
            if "archived" in payload:
                value = payload["archived"]
                kwargs["archived"] = str(value).strip().lower() not in ("", "0", "false", "no")
            result = _STORE.save_trip_meta(
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
        if _STORE is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        if tab_id != "unclassified" and _STORE.get_trip(tab_id) is None:
            self._send_json(
                {"code": "RESOURCE_NOT_FOUND", "message": "없는 여행이에요"},
                code=404)
            return
        rows = _STORE.list_tab_rows(None if tab_id == "unclassified" else tab_id)
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

    def _send_row_lineage(self, row_id) -> None:
        """APP_SPEC 10: `GET /api/rows/{row_id}/lineage`.

        원천, 제안, 사용자 수정, 이력. The row's source identifiers, what the
        classifier proposed, what the user changed, and the append-only history
        are returned as separate parts, so a caller can tell an agent's proposal
        from a person's save instead of reading one merged blob.
        """
        if _STORE is None:
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
            history = _STORE.list_history(row_id)
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
        if _STORE is None:
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
        rows = _STORE.conn.execute(
            "SELECT row_id, revision, kind, reverts_event_id, event_id, actor,"
            f" created_at, client_request_id FROM board_revisions WHERE {' AND '.join(where)}"
            " ORDER BY created_at, id", args).fetchall()
        changes = []
        for r in rows:
            if tab_id:
                current = _STORE.get_row(r[0]) or {}
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
        if _STORE is None:
            self._send_json(
                {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                code=503)
            return
        out = []
        for t in live_trips(include_archived=True):
            if t.get("deleted"):
                continue
            rows = _STORE.list_tab_rows(t["tab_id"])
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
        unclassified = _STORE.list_tab_rows(None)
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

    def _handle_trip_create(self, read_payload, check_csrf, content_type) -> None:
        from .ledger_store import SaveError

        try:
            payload = read_payload()
            check_csrf(payload)
            if _STORE is None:
                self._send_json(
                    {"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"},
                    code=503)
                return
            result = _STORE.create_trip(
                starts_on=str(payload.get("starts_on") or ""),
                destination=str(payload.get("destination") or ""),
                ends_on=str(payload.get("ends_on") or ""),
                display_key=(payload.get("display_key")
                             if "display_key" in payload else None),
                tab_kind=str(payload.get("tab_kind") or "trip"),
                source_sha256=str(payload.get("source_sha256") or ""),
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
            result = _STORE.apply_tab_delete(
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
            result = _STORE.correct_bank_income(
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
            result = _STORE.link_bank_source(
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
           host: str = "127.0.0.1") -> HTTPServer:
    import os

    from .card_import import CardImporter, CardWorker
    from .ledger_store import LedgerStore

    if db_path is None:
        db_path = os.environ.get("WEBLEDGER_DB", "webledger.work.sqlite")
    store = LedgerStore(db_path)
    bind_store(store)
    bind_importer(CardImporter(store.conn, store))
    # Loopback stays the default. 19.2 wants only the HTTPS app path exposed,
    # so a different address is the caller's stated decision, not a default
    # this module makes on its own.
    server = HTTPServer((host, port), Handler)
    worker = None
    if with_worker:
        worker = CardWorker(db_path)
        worker.start()
    server.card_worker = worker
    server.card_store = store
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
