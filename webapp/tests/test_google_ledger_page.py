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
    assert trips["0404_에히메"]["net"] == 600 and trips["0404_에히메"]["verified"] is True
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
    assert "메인과 보관에 모두 있음" in body and "Google 합계와 행 합계가 다름" in body
    assert "SOURCE_UNREACHABLE" in body


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
    assert trip["chosen_source"] == "archive" and trip["net"] == 600


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
    assert handler.sent[0][:2] == ("json", 503)


def test_viewer_sees_only_granted_trip_without_copies_or_sources(snapshot_file):
    page.set_grants(snapshot_file, user_id="viewer-1", keys=["<script>0630"], granted=True, at="t")
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger"), is_owner=False, viewer_user_id="viewer-1")
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
    assert page.caller(True, _Session("boss"), lambda s: s.user_id == "boss") == (True, "boss")
    assert page.caller(True, _Session("v1"), lambda s: False) == (False, "v1")


def test_owner_row_detail_lists_rows_with_position_and_amount(snapshot_file):
    handler = FakeHandler()
    page.dispatch(handler, parsed("/api/google-ledger/rows"), is_owner=True,
                  query={"key": ["0404_에히메"], "source": ["main"]})
    _, code, body = handler.sent[0]
    assert code == 200
    assert body["expense"][0]["row"] == 12 and body["expense"][0]["amount"] == 400
    assert body["income"][0]["payee"] == "INCOME-NAME"


def test_row_detail_is_owner_only_and_missing_tab_is_404(snapshot_file):
    viewer = FakeHandler()
    page.dispatch(viewer, parsed("/api/google-ledger/rows"), is_owner=False, viewer_user_id="v1",
                  query={"key": ["0404_에히메"], "source": ["main"]})
    assert viewer.sent[0][:2] == ("json", 403)
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
