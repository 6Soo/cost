"""Synthetic browser checks for bounded OTA queue paging and inline details."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from webapp import ota_payment_review, site_shell


class OtaQueueUiBrowserTests(unittest.TestCase):
    def test_group_card_keeps_charge_refund_members_and_fetches_each_detail_lazily(self):
        requested = []
        members = [
            {"ota_event_id":"charge-original", "provider":"agoda", "booking_ref":"BOOK-SYNTH",
             "event_type":"charge", "paid_on":None, "amount":"30000", "currency":"KRW",
             "status":"HOLD_DATE_UNKNOWN"},
            {"ota_event_id":"refund-partial", "provider":"agoda", "booking_ref":"BOOK-SYNTH",
             "event_type":"refund", "paid_on":"2026-10-03", "amount":"5000", "currency":"KRW",
             "status":"HOLD_EVIDENCE_CONFLICT"},
        ]

        def route(route):
            url = urlsplit(route.request.url)
            requested.append(url.path)
            if url.path.endswith("/summary"):
                body = {"status":"ready", "fresh":True, "stale":False, "refreshing":False,
                        "generation":4, "counts_authoritative":True,
                        "counts_by_queue":{"needs_action":{"event_count":2,"group_count":1}}}
            elif url.path.endswith("/groups"):
                body = {"generation":4, "items":[{"queue":"needs_action",
                    "reason_codes":["PAYMENT_EVIDENCE_CONFLICT"], "event":{
                        "ota_event_id":"charge-original", "provider":"agoda", "booking_ref":"BOOK-SYNTH",
                        "event_type":"charge", "status":"HOLD_DATE_UNKNOWN",
                        "group_id":"a"*64, "group_total_count":2,
                        "group_members":[{**member, "detail_available":True} for member in members]}}],
                    "next_cursor":None}
            elif "/groups/" in url.path and url.path.endswith("/members"):
                body = {"generation":4, "total_count":2, "next_cursor":None,
                        "items":[{"queue":"needs_action", "reason_codes":[],
                                  "event":{**member, "detail_available":True}} for member in members]}
            elif url.path.startswith("/api/imports/ota/groups/"):
                event_id = url.path.split("/")[-2]
                event = next(row["event"] for row in rows if row["event"]["ota_event_id"] == event_id)
                body = {"generation":7,"total_count":1,"items":[{"queue":"needs_action","reason_codes":[],"event":event}],"next_cursor":None}
            elif url.path.startswith("/api/imports/ota/events/"):
                event_id = url.path.rsplit("/", 1)[-1]
                body = {"generation":4, "event_id":event_id,
                        "event":{**next(item for item in members if item["ota_event_id"] == event_id),
                                 "evidence_missing":True}}
            elif url.path.startswith("/api/imports/ota/cards/"):
                body = {"cards":[]}
            else:
                route.fulfill(status=404, body='{}')
                return
            route.fulfill(json=body)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width":390,"height":844})
                page.route("**/api/imports/ota/**", route)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("synthetic-csrf"))
                page.locator("#ota-review > summary").click()
                card = page.locator("#ota-events > [data-queue-detail]").first
                card.wait_for()
                self.assertEqual(sum("/members" in path for path in requested), 0)
                card.locator("summary").click()
                page.locator('[data-load-detail="charge-original"]').wait_for()
                self.assertIn("30000", card.inner_text())
                self.assertIn("5000", card.inner_text())
                self.assertEqual(page.locator("[data-event]").count(), 0)
                self.assertEqual(sum("/members" in path for path in requested), 1)
                card.locator('[data-load-detail="charge-original"]').click()
                page.locator('[data-event="charge-original"]').wait_for()
                self.assertEqual(page.locator('[data-event="charge-original"] [data-cards-loaded="false"]').count(), 1)
                card.locator('[data-load-detail="refund-partial"]').click()
                page.locator('[data-event="refund-partial"]').wait_for()
                self.assertIn("HOLD_EVIDENCE_CONFLICT", [member["status"] for member in members])
                self.assertEqual(requested.count("/api/imports/ota/groups"), 1)
                self.assertEqual(sum(path.startswith("/api/imports/ota/events/") for path in requested), 2)
                self.assertTrue(all(path != "/api/imports/ota" for path in requested))
            finally:
                browser.close()

    def test_bounded_pages_filters_details_lazy_cards_and_no_full_snapshot(self):
        requested = []
        rows = []
        for n in range(45):
            event = {"ota_event_id": f"synthetic-{n:02}", "provider": "agoda",
                     "booking_ref": f"BOOK-{n:02}", "event_type": "charge",
                     "paid_on": "2026-10-01", "item": "Synthetic stay",
                     "amount": 12000, "currency": "KRW", "status": "HOLD_AMBIGUOUS"}
            event["group_members"] = [{**event, "detail_available":True}]
            event["group_total_count"] = 1
            rows.append({"queue": "needs_action", "reason_codes": [], "event": event})

        def route(route):
            url = urlsplit(route.request.url)
            requested.append(url.path)
            query = parse_qs(url.query)
            if url.path == "/api/imports/ota/summary":
                body = {"status": "ready", "fresh": True, "stale": False,
                        "refreshing": False, "generation": 7, "coverage": "canonical",
                        "counts_authoritative": True,
                        "counts_by_queue": {"needs_action": {"event_count": 45, "group_count": 45}},
                        "verified_group_count": 0, "singleton_fallback_count": 45}
            elif url.path == "/api/imports/ota/groups":
                cursor = query.get("cursor", [""])[0]
                start = 20 if cursor == "cursor-20" else 40 if cursor == "cursor-40" else 0
                body = {"generation": 7, "total_count": 45, "items": rows[start:start + 20],
                        "next_cursor": "cursor-20" if start == 0 else
                        "cursor-40" if start == 20 else None,
                        "singleton_fallback_count":45, "verified_group_count":0}
            elif url.path.startswith("/api/imports/ota/events/"):
                event_id = url.path.rsplit("/", 1)[-1]
                event = next(row["event"] for row in rows
                             if row["event"]["ota_event_id"] == event_id)
                body = {"generation": 7, "event_id": event_id,
                        "event": {**event, "reason": "amount_differs", "evidence_missing": False,
                                  "card_candidate_count": 1,
                                  "candidate_search": {"hidden": "secret"}}}
            elif url.path.startswith("/api/imports/ota/cards/"):
                body = {"cards": []}
            elif url.path.startswith("/api/imports/ota/diagnostics/"):
                body = {"snapshot": {"status": "ready"}}
            else:
                route.fulfill(status=404, content_type="application/json",
                              body='{"code":"NOT_FOUND"}')
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 812})
                page.set_default_timeout(3000)
                page.on("pageerror", lambda error: print("PAGEERROR", error))
                page.route("**/api/imports/ota/**", route)
                page.route("**/api/imports/ota", route)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("synthetic-csrf"))
                page.locator("#ota-review > summary").click()
                page.locator("[data-queue-detail]").first.wait_for()
                self.assertEqual(page.locator("#ota-events > [data-queue-detail]").count(), 20)
                self.assertIn("연결 검토 완료", page.locator("#ota-queue-summary").inner_text())
                page.locator("#ota-page-next").click()
                page.locator('[data-event-id="synthetic-20"]').wait_for()
                self.assertEqual(page.locator("#ota-events > [data-queue-detail]").count(), 20)
                page.locator("#ota-page-next").click()
                page.locator('[data-event-id="synthetic-40"]').wait_for()
                self.assertEqual(page.locator("#ota-events > [data-queue-detail]").count(), 5)
                page.locator("#ota-page-prev").click()
                page.locator('[data-event-id="synthetic-20"] > summary').click()
                page.locator('[data-event-id="synthetic-20"] [data-load-detail]').click()
                page.locator('[data-event="synthetic-20"]').wait_for()
                self.assertEqual(page.locator('[data-event="synthetic-20"] [data-cards-loaded="false"]').count(), 1)
                self.assertNotIn("secret", page.locator('[data-event="synthetic-20"]').inner_text())
                page.locator('[data-event="synthetic-20"] [data-diagnostic] summary').click()
                page.locator('[data-event="synthetic-20"] [data-diagnostic] pre').wait_for()
                self.assertTrue(all(path != "/api/imports/ota" for path in requested))
                self.assertTrue(any(path.startswith("/api/imports/ota/events/") for path in requested))
                page.locator("#ota-q-filter").fill("BOOK-20")
                page.wait_for_timeout(450)
                self.assertGreaterEqual(requested.count("/api/imports/ota/groups"), 4)
            finally:
                browser.close()

    def test_reflow_and_close_stops_polling(self):
        requested = []
        event = {"ota_event_id": "theme-event", "provider": "agoda", "booking_ref": "THEME-BOOKING",
                 "event_type": "charge", "paid_on": "2026-10-01", "item": "Synthetic stay",
                 "amount": 12000, "currency": "KRW", "status": "HOLD_AMBIGUOUS"}
        summary = {"status": "ready", "fresh": True, "stale": False, "refreshing": False,
                   "generation": 1, "counts_available": False, "counts_authoritative": False,
                   "coverage": "canonical", "counts_by_queue": None}

        def handler(route):
            path = urlsplit(route.request.url).path
            requested.append(path)
            if path.endswith("/summary"):
                body = summary
            elif path == "/api/imports/ota/groups":
                body = {"generation": 1, "items": [{"queue": "needs_action", "reason_codes": [],
                         "event": {**event, "group_members":[{**event, "detail_available":True}], "group_total_count":1}}], "next_cursor": None,
                        "singleton_fallback_count":1, "verified_group_count":0}
            elif "/members" in path:
                body = {"generation":1,"total_count":1,"items":[{"queue":"needs_action","reason_codes":[],"event":{**event,"detail_available":True}}],"next_cursor":None}
            elif path.endswith("/theme-event"):
                body = {"generation": 1, "event_id": "theme-event", "event": {
                    **event, "card_candidate_count": 1, "candidate_count": 1}}
            elif path.endswith("/cards/theme-event"):
                body = {"cards": []}
            else:
                body = {"generation": 1, "items": [], "next_cursor": None}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_default_timeout(4000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route("**/api/imports/ota/**", handler)
                document = ("<!doctype html><html><head><meta charset='utf-8'><base href='http://localhost/'></head><body>" +
                            ota_payment_review.render_import_section("csrf") + "</body></html>")
                page.set_content(site_shell.wrap_document(document, "/import"))
                for color in ("light", "dark"):
                    page.emulate_media(color_scheme=color)
                    page.locator("#site-theme-toggle").click()
                    effective = "dark" if color == "light" else "light"
                    self.assertEqual(page.locator("html").get_attribute("data-theme"), effective)
                    page.keyboard.press('Tab')
                    page.keyboard.press('Shift+Tab')
                    focus = page.evaluate("({id:document.activeElement.id,outline:getComputedStyle(document.activeElement).outlineStyle})")
                    self.assertEqual(focus["id"], "site-theme-toggle")
                    self.assertNotEqual(focus["outline"], "none")
                    for width in (375, 1280):
                        page.set_viewport_size({"width": width, "height": 800})
                        if not page.locator("#ota-review").evaluate("e => e.open"):
                            page.locator("#ota-review > summary").click()
                        page.evaluate("document.documentElement.style.zoom='200%'")
                        dimensions = page.evaluate(
                            "({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})")
                        self.assertLessEqual(dimensions["scroll"], dimensions["client"] + 2)
                        page.evaluate("document.documentElement.style.zoom='100%'")
                    try:
                        page.locator('#ota-queue-summary').filter(has_text='집계 미확인').wait_for()
                    except Exception:
                        self.fail(str({'errors': errors, 'requests': requested,
                                       'open': page.locator('#ota-review').evaluate('el => el.open'),
                                       'text': page.locator('#ota-review').inner_text()}))
                    self.assertNotIn("0건", page.locator("#ota-queue-summary").inner_text())
                    if not page.locator("[data-event='theme-event']").count():
                        page.locator("[data-queue-detail] > summary").click()
                        page.locator("[data-load-detail]").click()
                    page.locator("[data-event='theme-event']").wait_for()
                page.locator("#ota-review > summary").click()
                before = len(requested)
                page.wait_for_timeout(150)
                self.assertEqual(len(requested), before)
            finally:
                browser.close()

    def test_noncurrent_summary_does_not_show_cached_queue_rows(self):
        paths = []

        def handler(route):
            path = urlsplit(route.request.url).path
            paths.append(path)
            body = {"status": "refreshing", "fresh": False, "stale": True,
                    "refreshing": True, "generation": 3, "coverage": "canonical",
                    "counts_authoritative": False, "counts_by_queue": {}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 800})
                page.route("**/api/imports/ota/**", handler)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("csrf"))
                page.locator("#ota-review > summary").click()
                page.locator("#ota-freshness").filter(has_text="최신 자료").wait_for()
                self.assertNotIn("/api/imports/ota/groups", paths)
                self.assertIn("집계 미확인", page.locator("#ota-queue-summary").inner_text())
                self.assertNotIn("0건", page.locator("#ota-queue-summary").inner_text())
            finally:
                browser.close()

    def test_bad_cursor_resets_once_and_unsaved_choice_blocks_navigation(self):
        requests = []
        entries = [{"queue": "needs_action", "reason_codes": [], "event": {
            "ota_event_id": f"evt-{i}", "provider": "agoda", "booking_ref": f"B-{i}",
            "event_type": "charge", "paid_on": "2026-10-01", "item": "Stay",
            "amount": 10, "currency": "KRW", "status": "HOLD_AMBIGUOUS"}}
            for i in range(21)]
        for entry in entries:
            entry["event"]["group_members"] = [{**entry["event"], "detail_available":True}]
            entry["event"]["group_total_count"] = 1

        def handler(route):
            parsed = urlsplit(route.request.url)
            requests.append(parsed.path + ("?" + parsed.query if parsed.query else ""))
            query = parse_qs(parsed.query)
            if parsed.path.endswith("/summary"):
                body = {"status": "ready", "fresh": True, "stale": False,
                        "refreshing": False, "generation": 2, "coverage": "canonical",
                        "counts_authoritative": True, "counts_by_queue": {}}
            elif parsed.path == "/api/imports/ota/groups" and query.get("cursor"):
                route.fulfill(status=400, content_type="application/json",
                              body='{"code":"BAD_CURSOR"}')
                return
            elif parsed.path == "/api/imports/ota/groups":
                body = {"generation": 2, "total_count": 21, "items": entries[:20],
                        "next_cursor": "broken-cursor"}
            elif parsed.path.startswith("/api/imports/ota/groups/"):
                body = {"generation":2,"total_count":1,"items":[entries[0]],"next_cursor":None}
            elif parsed.path.endswith("/events/evt-0"):
                body = {"generation": 2, "event_id": "evt-0", "event": {
                    **entries[0]["event"], "card_candidate_count": 1}}
            elif parsed.path.endswith("/cards/evt-0"):
                body = {"cards": [{"transaction_id": "synthetic-card", "issuer": "Bank",
                                    "merchant": "Store", "amount_krw": 10,
                                    "selection_disabled": False}]}
            else:
                route.fulfill(status=404, content_type="application/json", body='{}')
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 800})
                page.set_default_timeout(3000)
                page.route("**/api/imports/ota/**", handler)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("csrf"))
                page.locator("#ota-review > summary").click()
                page.locator("[data-queue-detail]").first.wait_for()
                page.locator("#ota-page-next").click()
                page.locator('[data-event-id="evt-0"]').wait_for()
                page.wait_for_timeout(100)
                self.assertEqual(sum("/api/imports/ota/groups?" in value for value in requests), 3, requests)
                row = page.locator('[data-event-id="evt-0"]')
                row.locator(":scope > summary").click()
                row.locator("[data-load-detail]").click()
                row.locator(".ota-event").wait_for()
                row.locator(".ota-event h4[role=button]").click()
                choice = row.locator('.ota-card-row input[type="radio"]')
                choice.wait_for()
                choice.check()
                page.locator("#ota-page-next").click()
                self.assertEqual(page.locator('[data-event-id="evt-0"]').count(), 1)
                before = len(requests)
                page.locator('#ota-queue-filter').select_option('completed')
                self.assertEqual(page.locator('#ota-queue-filter').input_value(), 'needs_action')
                page.locator('#ota-q-filter').fill('discarded-filter')
                page.wait_for_timeout(400)
                self.assertEqual(page.locator('#ota-q-filter').input_value(), '')
                self.assertEqual(len(requests), before)
                self.assertTrue(choice.is_checked())
            finally:
                browser.close()

    def test_existing_preview_confirm_and_proposal_controls_use_bounded_detail_reads(self):
        requested = []
        event = {"ota_event_id": "evt-action", "provider": "agoda", "booking_ref": "BOOK-A",
                 "event_type": "charge", "paid_on": "2026-10-01", "item": "Stay",
                 "amount": 100, "currency": "KRW", "status": "HOLD_AMBIGUOUS"}

        def handler(route):
            parsed = urlsplit(route.request.url)
            requested.append((parsed.path, route.request.method))
            if parsed.path.endswith("/summary"):
                body = {"status": "ready", "fresh": True, "stale": False,
                        "refreshing": False, "generation": 4, "coverage": "canonical",
                        "counts_authoritative": True, "counts_by_queue": {}}
            elif parsed.path == "/api/imports/ota/groups":
                body = {"generation": 4, "total_count": 1, "items": [
                    {"queue": "needs_action", "reason_codes": [], "event": {**event,"group_members":[{**event, "detail_available":True}],"group_total_count":1}}],
                    "next_cursor": None}
            elif parsed.path.startswith("/api/imports/ota/groups/"):
                body = {"generation":4,"total_count":1,"items":[{"queue":"needs_action","reason_codes":[],"event":{**event,"detail_available":True}}],"next_cursor":None}
            elif parsed.path.endswith("/events/evt-action"):
                body = {"generation": 4, "event_id": "evt-action",
                        "event": {**event, "card_candidate_count": 1}}
            elif parsed.path.endswith("/cards/evt-action"):
                body = {"cards": [{"transaction_id": "card-a", "issuer": "Bank",
                                    "merchant": "Shop", "amount_krw": 100,
                                    "approval_date": "2026-10-01",
                                    "selection_disabled": False}]}
            elif parsed.path.endswith("/preview"):
                body = {"event_id": "evt-action", "transaction_id": "card-a",
                        "preview_digest": "digest-synthetic", "difference_krw": 0,
                        "event_amount_krw": 100, "card_amount_krw": 100}
            elif parsed.path.endswith("/confirm"):
                body = {"status": "MATCHED_USER", "transaction_id": "card-a"}
            elif parsed.path == "/api/imports/ota/proposals":
                body = {"generation": 4, "items": [{"proposal_id": "proposal-a",
                        "question": "Synthetic proposal", "status": "pending", "conditions": {}}],
                        "next_cursor": None, "total_count": 1}
            elif parsed.path.endswith("/proposal"):
                body = {"status": "answered_once"}
            else:
                route.fulfill(status=404, content_type="application/json", body='{"code":"NOT_FOUND"}')
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.set_default_timeout(3000)
                page.route("**/api/imports/ota/**", handler)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section("csrf"))
                page.evaluate("Object.defineProperty(crypto, 'randomUUID', {value: () => 'synthetic-request-id'})")
                page.locator("#ota-review > summary").click()
                row = page.locator("[data-queue-detail]").first
                row.wait_for()
                row.locator(":scope > summary").click()
                row.locator("[data-load-detail]").click()
                row.locator(".ota-event h4[role=button]").click()
                radio = row.locator('.ota-card-row input[type="radio"]')
                radio.check()
                row.locator("button[data-preview]").click()
                row.locator("#ota-confirm").wait_for()
                row.locator("#ota-confirm").click()
                page.locator("#ota-proposals-panel > summary").click()
                proposal = page.locator("#ota-proposals [data-proposal]").first
                proposal.wait_for()
                proposal.locator("button[data-answer]").click()
                self.assertIn(("/api/imports/ota/preview", "POST"), requested)
                self.assertIn(("/api/imports/ota/confirm", "POST"), requested)
                self.assertIn(("/api/imports/ota/proposal", "POST"), requested)
                self.assertNotIn(("/api/imports/ota", "GET"), requested)
            finally:
                browser.close()


    def test_late_poll_response_preserves_a_new_unsaved_card_selection(self):
        pending = []
        summary_reads = []
        summary = {"status": "ready", "fresh": True, "stale": False,
                   "refreshing": False, "generation": 1, "counts_by_queue": {}}
        event = {"ota_event_id": "race", "booking_ref": "SYN-RACE", "status": "HOLD_AMBIGUOUS"}

        def handle(route):
            path = urlsplit(route.request.url).path
            if path.endswith('/summary'):
                summary_reads.append(path)
                if len(summary_reads) > 1:
                    pending.append(route)
                    return
                body = summary
            elif path.endswith('/groups'):
                body = {"generation": 1, "items": [{"event": {**event, "group_members":[{**event, "detail_available":True}], "group_total_count":1}}], "next_cursor": None,
                        "singleton_fallback_count":1, "verified_group_count":0}
            elif '/events/' in path:
                body = {"generation": 1, "event": event}
            else:
                body = {"cards": [{"transaction_id": "synthetic-card", "amount_krw": 10}]}
            route.fulfill(json=body)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(3000)
                page.clock.install()
                page.route('**/api/imports/ota/**', handle)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section('csrf'))
                page.locator('#ota-review > summary').click()
                page.locator('[data-queue-detail] > summary').click()
                page.locator('[data-load-detail]').click()
                page.locator('h4[role=button]').click()
                radio = page.locator('.ota-card-row input')
                radio.wait_for()
                with page.expect_request('**/api/imports/ota/summary'):
                    page.clock.run_for(10000)
                page.wait_for_timeout(50)
                self.assertEqual(len(pending), 1)
                radio.check()
                pending[0].fulfill(json=summary)
                page.locator('#ota-freshness').filter(has_text='저장하지 않은 선택').wait_for()
                self.assertTrue(radio.is_checked())
            finally:
                browser.close()

    def test_generation_mismatch_discards_rows_and_proposal_edits_block_navigation(self):
        reads = []
        state = {"generation": 1}

        def handler(route):
            path = urlsplit(route.request.url).path
            reads.append(path)
            if path.endswith('/summary'):
                body = {"status": "ready", "fresh": True, "stale": False,
                        "refreshing": False, "generation": state['generation'],
                        "counts_by_queue": None, "counts_authoritative": False}
            elif path.endswith('/groups'):
                state['generation'] = 2
                body = {"generation": 2, "items": [{"event": {
                    "ota_event_id": "current", "booking_ref": "CURRENT"}}], "next_cursor": None}
            else:
                body = {"generation": 2, "items": [{"proposal_id": "p-1",
                        "question": "Synthetic question", "conditions": {}}], "next_cursor": "next"}
            route.fulfill(json=body)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 812})
                page.set_default_timeout(4000)
                page.route('**/api/imports/ota/**', handler)
                page.set_content("<base href='http://localhost/'>" +
                                 ota_payment_review.render_import_section('csrf'))
                page.locator('#ota-review > summary').click()
                page.locator('#ota-freshness').get_by_text('자료가 갱신되어 최신 목록을 다시 불러옵니다.').wait_for()
                self.assertEqual(page.locator('[data-queue-detail]').count(), 0)
                page.locator('[data-event-id="current"]').wait_for()
                self.assertGreaterEqual(reads.count('/api/imports/ota/summary'), 2)
                page.locator('#ota-proposals-panel > summary').click()
                proposal = page.locator('[data-proposal="p-1"]')
                proposal.wait_for()
                proposal.locator('input[value="edit"]').check()
                proposal.locator('input[name="item"]').fill('unsaved synthetic edit')
                before = len(reads)
                page.locator('#ota-proposals-next').click()
                self.assertEqual(len(reads), before)
                self.assertEqual(proposal.locator('input[name="item"]').input_value(), 'unsaved synthetic edit')
                page.locator('#ota-queue-filter').select_option('completed')
                self.assertEqual(page.locator('#ota-queue-filter').input_value(), 'needs_action')
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
