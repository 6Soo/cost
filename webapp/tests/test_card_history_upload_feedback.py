"""Regression checks for upload terminal errors, edited coverage and recovery state."""
import json

from playwright.sync_api import expect, sync_playwright

from webapp import cards_all, ledger_board, ledger_design, site_shell
from webapp.tests.test_cards_all import card_db_path


JOB_ID = "a" * 32
BATCH_ID = "batch-" + "b" * 24
JOB_KEY = "cost-card-upload-job"


def _document(db_path, query, monkeypatch):
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")
    monkeypatch.setattr(ledger_design, "nav_region", lambda *args, **kwargs: "")
    monkeypatch.setattr(cards_all, "_trip_context", lambda: ({}, set()))
    html = cards_all.cards_all_page(query, db_path=db_path, owner=True, csrf="synthetic-csrf")
    return site_shell.wrap_document(html, "/cards/all")


def _open_page(browser, document, *, query, jobs, routes):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_default_timeout(5000)
    page.route("http://cost.test/cards/all*", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=document))
    page.route("http://cost.test/api/cards/coverage/summary", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"available": True, "overview": {}, "cards": [], "files": []})))
    for pattern, handler in routes:
        page.route(pattern, handler)
    page.add_init_script(f"""localStorage.setItem('cost-card-upload-job', JSON.stringify({json.dumps(jobs)}));
      const native = window.setTimeout.bind(window);
      window.setTimeout = (callback, delay, ...args) => native(callback, delay >= 1000 ? 0 : delay, ...args);
    """)
    page.goto("http://cost.test/cards/all?" + query)
    return page


def _job(job_id=JOB_ID, batch_id=BATCH_ID, filename="synthetic.csv"):
    return {"status_url": "/api/imports/upload-status/" + job_id,
            "batch_id": batch_id, "filename": filename}


def test_terminal_server_error_is_shown_once_without_transient_retry(card_db_path, monkeypatch):
    calls = []

    def status(route):
        calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"status": "error", "message": "parser rejected synthetic input"}))

    document = _document(card_db_path, {"panel": ["upload"]}, monkeypatch)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = _open_page(browser, document, query="panel=upload", jobs=[_job()],
                              routes=[("**/api/imports/upload-status/**", status)])
            entry = page.locator(".card-upload-result").first
            expect(entry).to_have_attribute("data-outcome", "server-error")
            expect(entry.locator(".card-upload-result-state")).to_have_text("parser rejected synthetic input")
            expect(page.locator("#card-upload-resume-status")).to_contain_text("서버 오류 1개")
            assert len(calls) == 1
        finally:
            browser.close()


def test_unknown_resume_state_is_counted_and_can_be_checked_again(card_db_path, monkeypatch):
    calls = {"error": 0, "done": 0, "unknown": 0}

    def status(route):
        job_id = route.request.url.rsplit("/", 1)[-1]
        if job_id == "c" * 32:
            calls["done"] += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"status": "done", "result": {"batch_id": "batch-" + "c" * 24}}))
        elif job_id == "d" * 32:
            calls["error"] += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"status": "error", "message": "terminal synthetic error"}))
        else:
            calls["unknown"] += 1
            if calls["unknown"] <= 5:
                route.fulfill(status=503, content_type="application/json", body='{"code":"UNAVAILABLE"}')
            else:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"status": "done", "result": {"batch_id": "batch-" + "e" * 24}}))

    document = _document(card_db_path, {"panel": ["upload"]}, monkeypatch)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            jobs = [_job("c" * 32, "batch-" + "c" * 24, "done.csv"),
                    _job("d" * 32, "batch-" + "d" * 24, "error.csv"),
                    _job("e" * 32, "batch-" + "e" * 24, "unknown.csv")]
            page = _open_page(browser, document, query="panel=upload", jobs=jobs,
                              routes=[("**/api/imports/upload-status/**", status)])
            entry = page.locator('.card-upload-result[data-outcome="unknown"]')
            expect(entry).to_have_attribute("data-outcome", "unknown")
            expect(page.locator("#card-upload-resume-status")).to_contain_text(
                "완료 1개 · 서버 오류 1개 · 상태 미확인 1개")
            expect(page.get_by_role("button", name="미확인 상태 다시 조회")).to_be_visible()
            assert page.locator("#card-upload-results").evaluate(
                "e => [...e.children].every(child => child.tagName === 'LI')")
            assert page.locator("#card-upload-results #card-upload-resume-retry").count() == 0
            assert page.evaluate("JSON.parse(localStorage.getItem('cost-card-upload-job')).length") == 1

            page.get_by_role("button", name="미확인 상태 다시 조회").click()
            expect(page.locator(".card-upload-result").first).to_have_attribute("data-outcome", "saved")
            expect(page.locator("#card-upload-resume-status")).to_contain_text("완료 1개")
            expect(page.get_by_role("button", name="미확인 상태 다시 조회")).to_have_count(0)
            assert calls == {"error": 1, "done": 1, "unknown": 6}
        finally:
            browser.close()


def test_upload_with_legacy_gap_needs_no_period_confirmation(card_db_path, monkeypatch):
    calls = []
    evidence = {"card_id": "synthetic-card", "issuer": "SYNTH", "card_tail": "1234",
                "date_basis": "이용일", "start_date": "2026-04-01", "end_date": "2026-04-30"}

    def status(route):
        calls.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "status": "done", "result": {"batch_id": BATCH_ID, "coverage_available": True,
                "coverage_confirmed": False, "coverage_evidence": evidence}}))

    submitted = []

    def confirm(route):
        submitted.append(json.loads(route.request.post_data)["evidence"])
        route.fulfill(status=200, content_type="application/json", body='{"confirmed":true}')

    document = _document(card_db_path, {"panel": ["upload"]}, monkeypatch)
    query = ("panel=upload&gap_card=synthetic-card&gap_start=2026-04-01&gap_end=2026-04-30"
             "&gap_issuer=SYNTH&gap_tail=1234&gap_basis=%EC%9D%B4%EC%9A%A9%EC%9D%BC")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = _open_page(browser, document, query=query, jobs=[_job()], routes=[
                ("**/api/imports/upload-status/**", status),
                ("**/api/imports/*/coverage/confirm", confirm),
            ])
            expect(page.locator(".card-upload-coverage-form")).to_have_count(0)
            expect(page.locator("[data-gap-coverage-outcome]")).to_have_text(
                "업로드 후 거래일자 공백 현황을 다시 계산합니다.")
            expect(page.locator("#card-gap-context")).to_contain_text("파일 조회기간 사이")
            assert submitted == []
            assert len(calls) == 1
        finally:
            browser.close()
