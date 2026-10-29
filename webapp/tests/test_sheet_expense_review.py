"""Synthetic route, save-boundary, and browser acceptance for SDD-06."""
import json
import pathlib
from types import SimpleNamespace

import pytest

from webapp import sheet_expense_review as review


TRIP = "synthetic-trip-2026"
TX = "synthetic-cost-17"


def sample_preview(*, status="MATCHED_MANUAL", corrected=False):
    result = {
        "transaction_id": TX, "trip_id": TRIP, "sheet_id": "synthetic-sheet-4",
        "source": "main", "status": status, "sheet_row_key": "sha256:synthetic-row-key",
        "row_number": 14, "sheet_fingerprint": "sha256:synthetic-row-v1",
        "basis": ["same_trip", "same_amount_currency_sign", "unique_merchant"],
        "differences": {"category": {"manual": "현지경비", "cost": "식비"}},
        "reason": "synthetic difference", "user_corrected": corrected,
    }
    return {
        "trip_id": TRIP, "source_available": True,
        "source_info": {"trip_key": "private-google-key", "sheet_id": "synthetic-sheet-4",
                        "source": "main", "layout": "rev", "synced_at": "2026-10-29T00:00:00Z"},
        "source_digest": "sha256:synthetic-source-v1", "preview_digest": "sha256:synthetic-preview-v1",
        "revision": {"generation": "synthetic-generation", "source_digest": "sha256:synthetic-source-v1"},
        "links_path": "C:/private/synthetic-links.json", "results": [result],
        "counts": {status: 1},
        "cost_rows": [{"transaction_id": TX, "trip_id": TRIP, "date": "2026-10-20",
                        "merchant": "Synthetic Cafe", "item": "식비", "amount_krw": 12000,
                        "currency": "KRW", "card_tail": "4321", "description": "Synthetic memo"}],
    }


class FakeLinks:
    class LinkError(Exception):
        def __init__(self, code):
            self.code = code
            super().__init__(code)

    def __init__(self):
        self.data = {"revision": 0, "links": [], "history": []}
        self.saved = []

    def load_links(self, _path):
        return self.data

    def save_links(self, _path, results, *, expected_revision, request_id, source_digest):
        previous = next((event for event in self.data["history"]
                         if event.get("kind") == "request" and event.get("request_id") == request_id), None)
        if previous:
            return self.data
        if expected_revision != self.data["revision"]:
            raise ValueError("LINK_REVISION_CONFLICT")
        self.saved.append((results, expected_revision, request_id, source_digest))
        self.data["revision"] += 1
        for result in results:
            after = {**result, "stable_key": result.get("sheet_row_key"),
                     "provenance": {"request_id": request_id}}
            self.data["links"].append(after)
            self.data["history"].append({"kind": "link_saved", "after": after})
        self.data["history"].append({"kind": "request", "revision": self.data["revision"], "request_id": request_id,
                                     "source_digest": source_digest})
        return self.data


class FakeHandler:
    def __init__(self, method="GET"):
        self.command = method
        self.headers = {"X-CSRF-Token": "csrf-synthetic"}
        self.response = None
        self.html = None

    def _send_json(self, value, code=200, **_kwargs):
        self.response = (code, value)

    def _send(self, value, code=200):
        self.html = (code, value)


@pytest.fixture
def route_env(monkeypatch):
    links = FakeLinks()
    preview = sample_preview()
    monkeypatch.setattr(review, "_owner_request", lambda: True)
    monkeypatch.setattr(review, "_active_board", lambda: object())
    monkeypatch.setattr(review, "_preview_for_trip", lambda _board, _trip: preview)
    monkeypatch.setattr(review, "_link_store", lambda: links)
    return preview, links


def test_routes_are_exact_and_viewer_denied(monkeypatch):
    assert review.owns_route(review.PAGE_PATH)
    assert review.owns_route(review.API_PATH)
    assert not review.owns_route("/api/google-ledger/expense-reconciliation/extra")
    handler = FakeHandler()
    monkeypatch.setattr(review, "_owner_request", lambda: False)
    assert review.dispatch(handler, SimpleNamespace(path=review.API_PATH), query={"trip": [TRIP]})
    assert handler.response[0] == 403
    assert handler.response[1]["code"] == "OWNER_ONLY"


def test_get_api_projects_public_fields_only_and_counts_five_states(route_env):
    _preview, links = route_env
    handler = FakeHandler()
    assert review.dispatch(handler, SimpleNamespace(path=review.API_PATH), query={"trip": [TRIP]})
    code, payload = handler.response
    assert code == 200
    assert payload["counts"]["MATCHED_MANUAL"] == 1
    assert set(payload["counts"]) == set(review.STATUSES)
    row = payload["results"][0]
    assert row["card"] == "•••• 4321"
    assert row["row_number"] == 14
    assert row["differences"]["category"] == {"manual": "현지경비", "cost": "식비"}
    assert "links_path" not in payload and "cost_rows" not in payload
    assert "private-google-key" not in json.dumps(payload, ensure_ascii=False)
    assert "C:/private" not in json.dumps(payload, ensure_ascii=False)
    assert links.saved == []


def _post_body(payload, **updates):
    body = {
        "trip_id": TRIP, "transaction_ids": [TX], "csrf": "csrf-synthetic",
        "expected_revision": 0, "preview_digest": payload["preview_digest"],
        "request_id": "links:request-synthetic-1",
        # These fields are maliciously client supplied and must be ignored.
        "sheet_row_key": "client-controlled-row", "sheet_id": "client-controlled-sheet",
        "status": "MATCHED_MANUAL",
    }
    body.update(updates)
    return json.dumps(body).encode()


def test_post_recomputes_match_and_saves_only_server_metadata(route_env):
    preview, links = route_env
    handler = FakeHandler("POST")
    assert review.dispatch(handler, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    code, response = handler.response
    assert code == 200 and response["saved_count"] == 1
    saved, revision, request_id, source_digest = links.saved[0]
    assert revision == 0 and request_id == "links:request-synthetic-1"
    assert source_digest == "sha256:synthetic-source-v1"
    assert saved[0]["sheet_row_key"] == "sha256:synthetic-row-key"
    assert saved[0]["sheet_id"] == "synthetic-sheet-4"
    assert saved[0]["user_override"] is False
    assert saved[0]["link_method"] == "automatic_match"
    assert "client-controlled" not in json.dumps(saved)


def test_post_requires_csrf_and_rejects_stale_preview_or_revision(route_env):
    preview, links = route_env
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_post_body(preview), csrf="different-token")
    assert handler.response[0] == 403
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_post_body(preview, preview_digest="old-digest"), csrf="csrf-synthetic")
    assert handler.response[0] == 409 and handler.response[1]["code"] == "PREVIEW_STALE"
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_post_body(preview, expected_revision=9), csrf="csrf-synthetic")
    assert handler.response[0] == 409 and handler.response[1]["code"] == "LINK_REVISION_CONFLICT"
    assert links.saved == []


@pytest.mark.parametrize("status,corrected,expected", [
    ("NEW_EXPENSE", False, "MATCH_NOT_CONFIRMED"),
    ("REVIEW_CONFLICT", False, "MATCH_NOT_CONFIRMED"),
    ("MATCHED_MANUAL", True, "USER_CORRECTION_PROTECTED"),
])
def test_post_never_saves_new_conflicting_or_user_corrected_rows(route_env, monkeypatch, status, corrected, expected):
    preview, links = route_env
    preview["results"][0]["status"] = status
    preview["results"][0]["user_corrected"] = corrected
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    assert handler.response[0] == 409 and handler.response[1]["code"] == expected
    assert links.saved == []


def test_same_request_retry_is_idempotent_after_source_preview_changes(route_env):
    preview, links = route_env
    first = FakeHandler("POST")
    review.dispatch(first, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    assert first.response[0] == 200
    preview["preview_digest"] = "sha256:next-preview-after-link"
    preview["results"][0]["status"] = "MATCHED_EXISTING"
    retry = FakeHandler("POST")
    review.dispatch(retry, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    assert retry.response[0] == 200 and retry.response[1]["replayed"] is True
    assert len(links.saved) == 1


def _exported(preview):
    return {"source_available": True, "tsv": "2026-10-20\tSynthetic Cafe\t식비\t\t\t카드\t12000\n",
            "row_count": 1, "total_krw": 12000, "reconciliation": preview}


def _export_body(preview, **updates):
    body = {"trip_id": TRIP, "action": "export", "csrf": "csrf-synthetic",
            "expected_revision": 0, "preview_digest": preview["preview_digest"],
            "request_id": "export:request-synthetic-2"}
    body.update(updates)
    return json.dumps(body).encode()


def test_export_rechecks_live_preview_saves_matches_before_returning_tsv(route_env, monkeypatch):
    preview, links = route_env
    monkeypatch.setattr(review, "_export_for_trip", lambda _board, _trip, _rows=None: _exported(preview))
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview), csrf="csrf-synthetic")
    code, response = handler.response
    assert code == 200 and response["row_count"] == 1
    assert response["tsv"].startswith("2026-10-20\tSynthetic Cafe")
    assert len(links.saved) == 1
    assert links.saved[0][0][0]["user_override"] is False


def test_export_applies_bounded_ledger_filters_to_tsv_scope(route_env, monkeypatch):
    preview, _links = route_env
    selected_rows = [{"transaction_id": "synthetic-filtered-cost"}]
    selected = []
    exported_rows = []
    monkeypatch.setattr(review, "_selected_expense_rows",
                        lambda trip, query, kind: selected.append((trip, query, kind)) or selected_rows)
    monkeypatch.setattr(review, "_export_for_trip",
                        lambda _board, _trip, rows=None: exported_rows.append(rows) or _exported(preview))
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview, query="Synthetic", kind="ex"), csrf="csrf-synthetic")
    assert handler.response[0] == 200
    assert selected == [(TRIP, "Synthetic", "ex")]
    assert exported_rows == [selected_rows]


@pytest.mark.parametrize("updates", [
    {"query": "x" * 161}, {"query": "bad\nquery"}, {"kind": "both"},
])
def test_export_rejects_invalid_filter_values(route_env, updates):
    preview, _links = route_env
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview, **updates), csrf="csrf-synthetic")
    assert handler.response[0] == 400 and handler.response[1]["code"] == "INVALID_FILTER"


def test_export_source_change_or_link_save_failure_returns_no_tsv(route_env, monkeypatch):
    preview, links = route_env
    changed = sample_preview()
    changed["preview_digest"] = "sha256:source-changed-after-get"
    monkeypatch.setattr(review, "_export_for_trip", lambda _board, _trip, _rows=None: _exported(changed))
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview), csrf="csrf-synthetic")
    assert handler.response[0] == 409 and handler.response[1]["code"] == "PREVIEW_STALE"
    assert "tsv" not in handler.response[1] and links.saved == []

    class BrokenLinks(FakeLinks):
        def save_links(self, *_args, **_kwargs):
            raise RuntimeError("synthetic save failure")

    broken = BrokenLinks()
    monkeypatch.setattr(review, "_link_store", lambda: broken)
    monkeypatch.setattr(review, "_export_for_trip", lambda _board, _trip, _rows=None: _exported(preview))
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview), csrf="csrf-synthetic")
    assert handler.response[0] == 503
    assert "tsv" not in handler.response[1]


def test_export_same_request_retry_returns_fresh_tsv_without_second_save(route_env, monkeypatch):
    preview, links = route_env
    original_digest = preview["preview_digest"]
    monkeypatch.setattr(review, "_export_for_trip", lambda _board, _trip, _rows=None: _exported(preview))
    first = FakeHandler("POST")
    review.dispatch(first, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview), csrf="csrf-synthetic")
    assert first.response[0] == 200
    preview["results"][0]["status"] = "MATCHED_EXISTING"
    preview["preview_digest"] = "sha256:preview-with-saved-link"
    second = FakeHandler("POST")
    review.dispatch(second, SimpleNamespace(path=review.API_PATH),
                    raw=_export_body(preview, preview_digest=original_digest),
                    csrf="csrf-synthetic")
    assert second.response[0] == 200 and second.response[1]["replayed"] is True
    assert second.response[1]["tsv"] and len(links.saved) == 1


def test_existing_link_is_acknowledged_without_rewriting_or_changing_provenance(route_env):
    preview, links = route_env
    preview["results"][0]["status"] = "MATCHED_EXISTING"
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    assert handler.response[0] == 200 and handler.response[1]["saved_count"] == 0
    assert links.saved == []


def test_unavailable_link_store_fails_closed_in_get_payload(route_env, monkeypatch):
    _preview, _links = route_env

    class BrokenLinks:
        @staticmethod
        def load_links(_path):
            raise OSError("synthetic storage unavailable")

    monkeypatch.setattr(review, "_link_store", lambda: BrokenLinks())
    handler = FakeHandler()
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH), query={"trip": [TRIP]})
    code, payload = handler.response
    assert code == 503
    assert payload["source_available"] is False
    assert payload["counts"]["SOURCE_UNAVAILABLE"] == 1
    assert payload["results"][0]["status"] == "SOURCE_UNAVAILABLE"


def test_unavailable_google_source_blocks_post_and_new_expense_never_saves(route_env):
    preview, links = route_env
    preview["source_available"] = False
    preview["results"][0]["status"] = "SOURCE_UNAVAILABLE"
    preview["preview_digest"] = "sha256:unavailable-preview"
    handler = FakeHandler("POST")
    review.dispatch(handler, SimpleNamespace(path=review.API_PATH), raw=_post_body(preview), csrf="csrf-synthetic")
    assert handler.response[0] == 503
    assert handler.response[1]["code"] == "SOURCE_UNAVAILABLE"
    assert links.saved == []


def test_page_escapes_untrusted_source_values(route_env):
    preview, _links = route_env
    preview["cost_rows"][0]["merchant"] = "<img src=x onerror=alert(1)>"
    preview["results"][0]["differences"]["description"] = {
        "manual": "<script>bad()</script>", "cost": "& unsafe"}
    handler = FakeHandler()
    review.dispatch(handler, SimpleNamespace(path=review.PAGE_PATH, query="trip=" + TRIP),
                    query={"trip": [TRIP]}, csrf="csrf-synthetic")
    document = handler.html[1]
    assert "<img src=x" not in document
    assert "<script>bad()" not in document
    assert "&lt;img" in document and "&lt;script&gt;bad()" in document


def test_get_page_is_accessible_responsive_and_uses_shared_shell_tokens(route_env):
    preview, _links = route_env
    preview["results"] = [sample_preview()["results"][0] for _ in range(51)]
    preview["counts"] = {"MATCHED_MANUAL": 51}
    handler = FakeHandler()
    review.dispatch(handler, SimpleNamespace(path=review.PAGE_PATH, query="trip=" + TRIP),
                    query={"trip": [TRIP]}, csrf="csrf-synthetic")
    code, document = handler.html
    assert code == 200
    assert "이미 수기로 기록됨 · 새 행 추가 안함" in document
    assert "연결 완료 · 수기 원본 유지 · 차이 있음" in document
    assert "Google 시트는 변경하지 않습니다" in document
    assert "aria-live='polite'" in document and "다음 페이지" in document
    assert "--shell-ink" in document and "--shell-paper" in document
    assert "•••• 4321" in document
    assert "C:/private" not in document


def test_browser_shell_theme_and_narrow_viewport(route_env):
    playwright = pytest.importorskip("playwright.sync_api")
    from webapp import site_shell

    preview, _links = route_env
    preview["results"] = [sample_preview()["results"][0] | {"transaction_id": f"synthetic-cost-{n}"}
                          for n in range(51)]
    preview["counts"] = {"MATCHED_MANUAL": 51}
    handler = FakeHandler()
    review.dispatch(handler, SimpleNamespace(path=review.PAGE_PATH, query="trip=" + TRIP),
                    query={"trip": [TRIP]}, csrf="csrf-synthetic")
    wrapped = site_shell.wrap_document(handler.html[1], review.PAGE_PATH)
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 320, "height": 780}, color_scheme="light")
                page.set_content(wrapped)
                page.wait_for_timeout(50)
                for theme in ("light", "dark"):
                    if page.locator("#site-theme-toggle").count():
                        current = page.locator("html").get_attribute("data-theme")
                        if current != theme:
                            page.locator("#site-theme-toggle").click()
                    page.locator(".ser-row").first.wait_for()
                    assert page.locator("html").evaluate("e=>e.dataset.theme") == theme
                    ink = page.locator(".ser-page").evaluate("e=>getComputedStyle(e).color")
                    assert ink and ink != "rgba(0, 0, 0, 0)"
                    contrast = page.locator(".ser-count strong").first.evaluate("""e=>{
                      const rgb=s=>s.match(/[\\d.]+/g).slice(0,3).map(Number);
                      const lum=s=>rgb(s).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                        .reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
                      const a=lum(getComputedStyle(e).color),b=lum(getComputedStyle(e.parentElement).backgroundColor);
                      return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                    }""")
                    assert contrast >= 4.5
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert page.locator(".ser-save button[value=links]").evaluate("e=>e.getBoundingClientRect().height >= 44")
                    assert page.get_by_role("button", name="신규 지출 복사").count() == 1
                    assert page.get_by_role("link", name="다음 페이지").count() == 1
                checkbox = page.locator("input[name=transaction_ids]").first
                checkbox.focus()
                page.keyboard.press("Space")
                assert checkbox.is_checked()
                page.keyboard.press("Tab")
                assert page.evaluate("document.activeElement.tagName") == "A"
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("document.activeElement.name") == "transaction_ids"
            finally:
                browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "browserType.launch" in str(exc):
            pytest.skip("synthetic browser runtime is unavailable")
        raise
