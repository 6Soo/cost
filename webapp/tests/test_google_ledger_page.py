import json
from urllib.parse import urlparse

import pytest

from app import google_authority as ga
from webapp import google_ledger_page as page


def block(total, verified=True):
    return {"sheet_total": total, "row_sum": total, "total": total, "verified": verified}


def copy(sheet, income, expense, verified=True):
    return {"sheet": sheet, "layout": "rev", "flags": [], "income": block(income, verified),
            "expense": block(expense, verified)}


def snapshot_doc():
    dup = {"key": "0404_에히메", "closure": "closed", "closure_current": True, "canonical_source": "main",
           "income_total": 1000, "expense_total": 400, "net": 600, "verified": True,
           "reported": {"income_total": 1000, "expense_total": 400, "net": 600},
           "copies": {"main": copy("0404_에히메", 1000, 400), "archive": copy("0404_에히메", 900, 300)},
           "review": ["DUPLICATE_IN_BOTH"]}
    mismatch = {"key": "<script>0630", "closure": "open", "closure_current": True, "canonical_source": "main",
                "income_total": None, "expense_total": None, "net": None, "verified": False,
                "reported": {"income_total": 5, "expense_total": 2, "net": 3},
                "copies": {"main": copy("<script>0630", 5, 2, verified=False), "archive": None},
                "review": ["TOTAL_MISMATCH"]}
    return {"schema": "google-authority-readonly-v2", "synced_at": "2026-10-11T10:00:00+09:00",
            "sources": {"main": {"status": "ok", "error_code": None, "stale": False,
                                 "last_ok_at": "2026-10-11T10:00:00+09:00", "checked_at": "x"},
                        "archive": {"status": "error", "error_code": "SOURCE_UNREACHABLE", "stale": True,
                                    "last_ok_at": None, "checked_at": "x"}},
            "trips": [dup, mismatch], "rows_generation": "gen"}


class FakeHandler:
    def __init__(self, token=""):
        self.headers = {"X-CSRF-Token": token} if token else {}
        self.sent = []

    def _send_json(self, value, code=200, extra_headers=None):
        self.sent.append(("json", code, value))

    def _send(self, text, code=200):
        self.sent.append(("html", code, text))


def rows_doc():
    line = lambda row, payee, amount: {"row": row, "cells": {"B": "2027-08-02", "C": payee, "D": "식비",
                                                            "E": "", "F": "RESV-1", "G": "카드"}, "amount": amount}
    return {"schema": ga.ROWS_SCHEMA, "generation": "gen", "synced_at": "t",
            "sources": {"main": {"content_sha256": None, "trips": {
                "0404_에히메": {"income": [line(6, "INCOME-NAME", 1000)], "expense": [line(12, "PAYEE-<b>", 400)]}}}}}


@pytest.fixture
def snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    path.write_text(json.dumps(snapshot_doc(), ensure_ascii=False), encoding="utf-8")
    ga._rows_file(rows_path, "gen").write_text(json.dumps(rows_doc(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(path))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(rows_path))
    return path


def parsed(path):
    return urlparse(path)


def test_disabled_without_snapshot_setting(monkeypatch):
    monkeypatch.delenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", raising=False)
    handler = FakeHandler()
    assert page.dispatch(handler, parsed("/api/google-ledger"), is_owner=True) is False
    assert handler.sent == []


def test_non_owner_gets_403_json_never_a_page(snapshot_file):
    for path in ("/google-ledger", "/api/google-ledger"):
        handler = FakeHandler()
        assert page.dispatch(handler, parsed(path), is_owner=False) is True
        assert handler.sent[0][:2] == ("json", 403)
        assert "0404" not in json.dumps(handler.sent[0][2], ensure_ascii=False)


def test_owner_api_hides_rows_and_shows_figures_by_verification(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=True)
    _, code, payload = handler.sent[0]
    assert code == 200
    trips = {t["key"]: t for t in payload["trips"]}
    # The archive source in this fixture failed; a retained snapshot is not current verification.
    assert trips["0404_에히메"]["net"] is None and trips["0404_에히메"]["verified"] is False
    assert 'SOURCE_STALE' in trips["0404_에히메"]['review']
    unverified = trips["<script>0630"]
    assert unverified["net"] is None and unverified["verified"] is False
    text = json.dumps(payload, ensure_ascii=False)
    assert "rows" not in text and "PAYEE" not in text


def test_owner_html_escapes_titles_and_labels_checks(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger"), is_owner=True)
    _, code, body = handler.sent[0]
    assert code == 200
    assert "<script>0630" not in body and "&lt;script&gt;0630" in body
    assert "메인과 보관에 모두 있음" in body and "장부 합계와 행 합계가 다름" in body
    assert "보관 장부 동기화를 확인해 주세요." in body
    assert "role='alert'" in body
    assert "SOURCE_UNREACHABLE" not in body


def test_choice_requires_csrf_and_records_history(snapshot_file):
    no_token = FakeHandler()
    page.dispatch(no_token, parsed("/api/google-ledger/choice"), is_owner=True, raw=b"{}", csrf="tok")
    assert no_token.sent[0][:2] == ("json", 403)

    body = json.dumps({"key": "0404_에히메", "source": "archive"}).encode()
    handler = FakeHandler(token="tok")
    page.dispatch(handler, parsed("/api/google-ledger/choice"), is_owner=True, raw=body, csrf="tok")
    assert handler.sent[0][:2] == ("json", 200)
    stored = page.load_choices(snapshot_file)
    assert stored["choices"] == {"0404_에히메": "archive"}
    assert stored["history"][0]["from"] is None and stored["history"][0]["to"] == "archive"


def test_chosen_archive_copy_drives_figures_only_when_verified(snapshot_file):
    page.record_choice(snapshot_file, key="0404_에히메", source="archive", at="t")
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=True)
    trip = next(t for t in handler.sent[0][2]["trips"] if t["key"] == "0404_에히메")
    # The fixture's archive sync is in error, so the choice selects a copy but cannot lift the block.
    assert trip["chosen_source"] == "archive" and trip["net"] is None
    assert "SOURCE_NOT_CURRENT" in trip["blocked_by"]


def test_non_owner_cannot_change_choice(snapshot_file):
    body = json.dumps({"key": "0404_에히메", "source": "archive"}).encode()
    handler = FakeHandler(token="tok")
    page.dispatch(handler, parsed("/api/google-ledger/choice"), is_owner=False, raw=body, csrf="tok")
    assert handler.sent[0][:2] == ("json", 403)
    assert page.load_choices(snapshot_file)["choices"] == {}


def test_unreadable_snapshot_is_503_not_empty_page(tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(path))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger"), is_owner=True)
    assert handler.sent[0][:2] == ("html", 503)
    assert "다시 확인" in handler.sent[0][2]
    assert str(path) not in handler.sent[0][2]
    api = FakeHandler()
    page.dispatch(api, parsed("/api/google-ledger"), is_owner=True)
    assert api.sent[0][:2] == ("json", 503)
    assert api.sent[0][2]['code'] == 'SNAPSHOT_UNREADABLE'


def test_viewer_sees_only_granted_trip_without_copies_or_sources(snapshot_file):
    page.set_grants(snapshot_file, user_id="viewer-1", keys=["<script>0630"], granted=True, at="t")
    page.set_mapping(snapshot_file, key="<script>0630", tab_id="tab-A", known_keys={"<script>0630"})
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=False, viewer_user_id="viewer-1",
                  viewer_tabs={"tab-A"})
    _, code, payload = handler.sent[0]
    assert code == 200
    assert [t["key"] for t in payload["trips"]] == ["<script>0630"]
    text = json.dumps(payload, ensure_ascii=False)
    assert "copies" not in text and "reported" not in text and "error_code" not in text
    assert "0404_에히메" not in text


def test_viewer_without_grant_gets_an_empty_list_not_other_trips(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger"), is_owner=False, viewer_user_id="viewer-2")
    _, code, body = handler.sent[0]
    assert code == 200 and "0404_에히메" not in body and "<script>0630" not in body


def test_anonymous_is_refused_and_viewer_cannot_grant(snapshot_file):
    anon = FakeHandler()
    page.dispatch(anon, parsed("/google-ledger"), is_owner=False, viewer_user_id=None)
    assert anon.sent[0][:2] == ("json", 403)

    body = json.dumps({"user_id": "viewer-1", "keys": ["0404_에히메"], "granted": True}).encode()
    viewer = FakeHandler(token="tok")
    page.dispatch(viewer, parsed("/api/google-ledger/grants"), is_owner=False, viewer_user_id="viewer-1",
                  raw=body, csrf="tok")
    assert viewer.sent[0][:2] == ("json", 403)
    assert page.load_grants(snapshot_file)["grants"] == {}


def test_owner_grant_and_revoke_are_recorded_and_default_deny_holds(snapshot_file):
    body = json.dumps({"user_id": "viewer-1", "keys": ["0404_에히메"], "granted": True}).encode()
    owner = FakeHandler(token="tok")
    page.dispatch(owner, parsed("/api/google-ledger/grants"), is_owner=True, raw=body, csrf="tok")
    assert owner.sent[0][:2] == ("json", 200)
    assert page.load_grants(snapshot_file)["grants"] == {"viewer-1": ["0404_에히메"]}

    revoke = json.dumps({"user_id": "viewer-1", "keys": ["0404_에히메"], "granted": False}).encode()
    page.dispatch(FakeHandler(token="tok"), parsed("/api/google-ledger/grants"), is_owner=True, raw=revoke, csrf="tok")
    stored = page.load_grants(snapshot_file)
    assert stored["grants"]["viewer-1"] == [] and len(stored["history"]) == 2
    empty = FakeHandler()
    page.dispatch(empty, parsed("/api/google-ledger"), is_owner=False, viewer_user_id="viewer-1")
    assert empty.sent[0][2]["trips"] == []


def test_invalid_grant_body_is_400_not_500(snapshot_file):
    handler = FakeHandler(token="tok")
    page.dispatch(handler, parsed("/api/google-ledger/grants"), is_owner=True, raw=b"not json", csrf="tok")
    assert handler.sent[0][:2] == ("json", 400)
    bad = FakeHandler(token="tok")
    page.dispatch(bad, parsed("/api/google-ledger/grants"), is_owner=True,
                  raw=json.dumps({"user_id": "", "keys": "x", "granted": True}).encode(), csrf="tok")
    assert bad.sent[0][:2] == ("json", 400)


class _Session:
    def __init__(self, user_id):
        self.user_id = user_id


def test_enforcement_off_never_grants_owner_even_with_a_session():
    assert page.caller(False, _Session("boss"), lambda s: True) == (False, None)


def test_anonymous_request_is_not_owner_when_enforced(snapshot_file):
    assert page.caller(True, None, lambda s: True) == (False, None)
    handler = FakeHandler()
    is_owner, viewer = page.caller(True, None, lambda s: True)
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=is_owner, viewer_user_id=viewer)
    assert handler.sent[0][:2] == ("json", 403)


def test_confirmed_owner_session_is_owner_and_viewer_session_is_viewer():
    assert page.caller(True, _Session("boss"), lambda s: s.user_id == "boss", lambda u: "owner") == (True, "boss")
    assert page.caller(True, _Session("v1"), lambda s: False, lambda u: "viewer") == (False, "v1")
    assert page.caller(True, _Session("v1"), lambda s: False, lambda u: None) == (False, None)


def test_owner_row_detail_lists_rows_with_position_and_amount(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger/rows"), is_owner=True,
                  query={"key": ["0404_에히메"], "source": ["main"]})
    _, code, body = handler.sent[0]
    assert code == 200
    assert body["expense"][0]["row"] == 12 and body["expense"][0]["amount"] == 400
    assert body["income"][0]["name"] == "INCOME-NAME" and body["income"][0]["deposit"] == ""
    assert body["expense"][0]["payee"] == "PAYEE-<b>" and body["expense"][0]["category"] == "식비"


def test_row_detail_for_an_ungranted_viewer_is_404_and_missing_tab_is_404(snapshot_file):
    viewer = FakeHandler()
    page.dispatch(viewer, parsed("/api/google-ledger/rows"), is_owner=False, viewer_user_id="v1",
                  query={"key": ["0404_에히메"], "source": ["main"]}, viewer_tabs={"tab-A"})
    # Not granted, so the same answer as a missing trip: nothing about the trip is revealed.
    assert viewer.sent[0][:2] == ("json", 404)
    missing = FakeHandler()
    page.dispatch(missing, parsed("/api/google-ledger/rows"), is_owner=True,
                  query={"key": ["nope"], "source": ["main"]})
    assert missing.sent[0][:2] == ("json", 404)


def test_row_detail_html_escapes_cell_text(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger/rows"), is_owner=True,
                  query={"key": ["0404_에히메"], "source": ["main"]})
    body = handler.sent[0][2]
    assert "PAYEE-&lt;b&gt;" in body and "<b>" not in body


def test_mismatched_rows_fail_the_whole_page_closed(snapshot_file):
    rows_file = ga._rows_file(snapshot_file.parent / "rows-private.json", "gen")
    doc = rows_doc()
    doc["sources"]["main"]["content_sha256"] = "x"
    rows_file.write_text(json.dumps(doc), encoding="utf-8")
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=True)
    assert handler.sent[0][:2] == ("json", 503)
    assert handler.sent[0][2]["code"] == "GENERATION_MISMATCH"


def test_enabled_needs_both_snapshot_and_rows_setting(monkeypatch):
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", "x")
    monkeypatch.delenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", raising=False)
    assert page.enabled() is False


def _access(tmp_path):
    import sqlite3
    from webapp import access_control
    store = access_control.AccessStore(sqlite3.connect(tmp_path / "access.sqlite"))
    store.ensure_schema()
    store.create_account(user_id="boss", role="owner", is_synthetic=True)
    store.create_account(user_id="v1", role="viewer", is_synthetic=True)
    return store


def test_viewer_access_follows_the_access_store_active_state(tmp_path, snapshot_file):
    store = _access(tmp_path)
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=True, at="t")
    session = _Session("v1")
    assert page.caller(True, session, lambda x: store.is_owner(x.user_id), store.account_role) == (False, "v1")
    store.set_account_active(user_id="v1", is_active=False)
    assert page.caller(True, session, lambda x: store.is_owner(x.user_id), store.account_role) == (False, None)
    store.set_account_active(user_id="v1", is_active=True)
    assert page.caller(True, session, lambda x: store.is_owner(x.user_id), store.account_role) == (False, "v1")


def test_removed_account_gets_nothing_even_with_a_grant(tmp_path, snapshot_file):
    store = _access(tmp_path)
    page.set_grants(snapshot_file, user_id="ghost", keys=["0404_에히메"], granted=True, at="t")
    assert page.caller(True, _Session("ghost"), lambda x: store.is_owner(x.user_id), store.account_role) == (False, None)


def test_grant_revocation_empties_the_viewer_page_and_regranting_restores_it(tmp_path, snapshot_file):
    store = _access(tmp_path)
    page.set_mapping(snapshot_file, key="0404_에히메", tab_id="tab-A", known_keys={"0404_에히메"})
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=True, at="t")
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=False, at="t2")
    handler = FakeHandler()
    is_owner, viewer = page.caller(True, _Session("v1"), lambda x: store.is_owner(x.user_id), store.account_role)
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=is_owner, viewer_user_id=viewer)
    assert handler.sent[0][2]["trips"] == []
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=True, at="t3")
    page.set_mapping(snapshot_file, key="0404_에히메", tab_id="tab-A", known_keys={"0404_에히메"})
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=is_owner, viewer_user_id=viewer,
                  viewer_tabs={"tab-A"})
    assert [t["key"] for t in handler.sent[0][2]["trips"]] == ["0404_에히메"]


def test_owner_summary_links_each_copy_to_its_detail_and_viewer_gets_no_links(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger"), is_owner=True)
    body = handler.sent[0][2]
    # The fixture trip 0404 has both copies, so both detail links are offered.
    assert "source=main" in body and "source=archive" in body
    viewer = FakeHandler()
    page.dispatch(viewer, parsed("/google-ledger"), is_owner=False, viewer_user_id="v1")
    assert "/google-ledger/rows" not in viewer.sent[0][2]


def test_income_detail_and_expense_detail_show_their_own_columns(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/google-ledger/rows"), is_owner=True,
                  query={"key": ["0404_에히메"], "source": ["main"]})
    body = handler.sent[0][2]
    assert "<th>이름</th><th>닉네임</th><th>예약금</th>" in body
    assert "<th>지급처</th><th>분류</th><th>기간</th><th>예약번호</th><th>증빙</th>" in body


def _clean_trip(**over):
    base = {"key": "0404_에히메", "closure": "closed", "closure_current": True, "canonical_source": "main",
            "income_total": 1000, "expense_total": 400, "net": 600, "verified": True, "review": ["DUPLICATE_IN_BOTH"],
            "copies": {"main": copy("0404_에히메", 1000, 400), "archive": copy("0404_에히메", 900, 300)}}
    base.update(over)
    return base


def _clean_sources(**over):
    ok = {"status": "ok", "stale": False, "last_ok_at": "t", "checked_at": "t"}
    sources = {"main": dict(ok), "archive": dict(ok)}
    sources.update(over)
    return sources


def _chosen(trip, sources, choice="archive"):
    snapshot = {"synced_at": "t", "sources": sources, "trips": [trip]}
    return page.owner_payload(snapshot, {"choices": {trip["key"]: choice}, "history": []})["trips"][0]


def test_clean_archive_choice_counts_the_archive_figures():
    trip = _chosen(_clean_trip(), _clean_sources())
    assert trip["verified"] is True and trip["net"] == 600 and trip["blocked_by"] == []


def test_a_stale_source_keeps_the_block_even_when_the_archive_copy_is_chosen():
    stale_main = _clean_sources(main={"status": "error", "stale": True, "last_ok_at": "t", "checked_at": "t"})
    trip = _chosen(_clean_trip(review=["DUPLICATE_IN_BOTH", "SOURCE_STALE"]), stale_main)
    assert trip["verified"] is False and trip["net"] is None
    assert "SOURCE_NOT_CURRENT" in trip["blocked_by"]


def test_a_stale_archive_sync_blocks_the_archive_choice():
    stale_archive = _clean_sources(archive={"status": "error", "stale": True, "last_ok_at": "t", "checked_at": "t"})
    trip = _chosen(_clean_trip(), stale_archive)
    assert trip["verified"] is False and "SOURCE_NOT_CURRENT" in trip["blocked_by"]


def test_identity_uncertainty_is_not_lifted_by_a_manual_choice():
    for flag in ("POSSIBLE_DUPLICATE", "COPY_NAME", "DUPLICATE_IN_SOURCE"):
        trip = _chosen(_clean_trip(review=["DUPLICATE_IN_BOTH", flag]), _clean_sources())
        assert trip["verified"] is False, flag
        assert flag in trip["blocked_by"], flag


def test_closure_that_is_not_current_or_an_unverified_copy_blocks_the_choice():
    assert "CLOSURE_NOT_CURRENT" in _chosen(_clean_trip(closure_current=False), _clean_sources())["blocked_by"]
    unverified = _clean_trip(copies={"main": copy("0404_에히메", 1000, 400),
                                     "archive": copy("0404_에히메", 900, 300, verified=False)})
    assert "COPY_NOT_VERIFIED" in _chosen(unverified, _clean_sources())["blocked_by"]


def test_a_grant_without_a_cost_tab_link_shows_nothing(snapshot_file):
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=True, at="t")
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=False, viewer_user_id="v1", viewer_tabs={"tab-A"})
    assert handler.sent[0][2]["trips"] == []


def test_a_linked_tab_the_account_cannot_see_shows_nothing(snapshot_file):
    page.set_mapping(snapshot_file, key="0404_에히메", tab_id="tab-A", known_keys={"0404_에히메"})
    page.set_grants(snapshot_file, user_id="v1", keys=["0404_에히메"], granted=True, at="t")
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=False, viewer_user_id="v1", viewer_tabs={"tab-B"})
    assert handler.sent[0][2]["trips"] == []


def test_owner_sets_and_clears_the_link_and_unknown_trips_are_refused(snapshot_file):
    known = {"0404_에히메", "<script>0630"}
    page.set_mapping(snapshot_file, key="0404_에히메", tab_id="tab-A", known_keys=known)
    assert page.load_mapping(snapshot_file) == {"0404_에히메": "tab-A"}
    page.set_mapping(snapshot_file, key="0404_에히메", tab_id=None, known_keys=known)
    assert page.load_mapping(snapshot_file) == {}
    with pytest.raises(ValueError, match="GOOGLE_TRIP_UNKNOWN"):
        page.set_mapping(snapshot_file, key="not-a-trip", tab_id="tab-A", known_keys=known)


def test_mapping_route_is_owner_only_and_csrf_protected(snapshot_file, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('webapp.ledger_board._active_store',
                        lambda: SimpleNamespace(list_trips=lambda: [{'tab_id': 'tab-A'}]))
    body = json.dumps({"key": "0404_에히메", "tab_id": "tab-A"}).encode()
    viewer = FakeHandler(token="tok")
    page.dispatch(viewer, parsed("/api/google-ledger/mapping"), is_owner=False, viewer_user_id="v1",
                  raw=body, csrf="tok")
    assert viewer.sent[0][:2] == ("json", 403)
    no_token = FakeHandler()
    page.dispatch(no_token, parsed("/api/google-ledger/mapping"), is_owner=True, raw=body, csrf="tok")
    assert no_token.sent[0][:2] == ("json", 403)
    owner = FakeHandler(token="tok")
    page.dispatch(owner, parsed("/api/google-ledger/mapping"), is_owner=True, raw=body, csrf="tok")
    assert owner.sent[0][:2] == ("json", 200)
    assert page.load_mapping(snapshot_file) == {"0404_에히메": "tab-A"}
