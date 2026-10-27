import json

import pytest
from playwright.sync_api import sync_playwright

from webapp.ota_payment_review import render_import_section


def _snapshot(include_proposal=False):
    events = [
        {"ota_event_id": "partial-1", "provider": "trip", "booking_ref": "BOOK-PARTIAL",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "status": "HOLD_PARTIAL_GROUP", "reason": "partial_repeated_payment_group",
         "group_count": {"ota": 3, "cards": 2}, "matched_count": 2,
         "ota_group_ids": ["partial-1", "partial-2", "partial-3"],
         "card_group_ids": ["partial-card-1", "partial-card-2"]},
        {"ota_event_id": "ordered-1", "provider": "trip", "booking_ref": "BOOK-ORDERED",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "service_period": {"starts_on": "2026-10-01", "ends_on": "2026-10-03"},
         "status": "MATCHED_AUTO", "allocation_basis": "user_approved_stable_order",
         "individual_payment_evidence": False, "group_count": {"ota": 2, "cards": 2},
         "ota_group_ids": ["ordered-1", "ordered-2"],
         "card_group_ids": ["ordered-card-1", "ordered-card-2"]},
        {"ota_event_id": "ordered-2", "provider": "trip", "booking_ref": "BOOK-ORDERED-2",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "status": "MATCHED_AUTO", "allocation_basis": "user_approved_stable_order",
         "individual_payment_evidence": False, "group_count": {"ota": 2, "cards": 2},
         "ota_group_ids": ["ordered-1", "ordered-2"],
         "card_group_ids": ["ordered-card-1", "ordered-card-2"]},
        {"ota_event_id":"manual-group-a", "provider":"trip", "booking_ref":"BOOK-MANUAL-A",
         "event_type":"charge", "paid_on":"2026-09-04", "amount":"30000", "currency":"KRW",
         "amount_krw":30000, "status":"HOLD_GROUP_CONFIRMATION_REQUIRED",
         "allocation_basis":"user_confirmed_group_required", "matched_count":2,
         "group_count":{"ota":2,"cards":2}, "ota_group_ids":["manual-group-a","manual-group-b"],
         "card_group_ids":["manual-card-a","manual-card-b"],
         "proposed_mapping":{"manual-group-a":"manual-card-a","manual-group-b":"manual-card-b"}},
        {"ota_event_id":"manual-group-b", "provider":"trip", "booking_ref":"BOOK-MANUAL-B",
         "event_type":"charge", "paid_on":"2026-09-04", "amount":"30000", "currency":"KRW",
         "amount_krw":30000, "status":"HOLD_GROUP_CONFIRMATION_REQUIRED",
         "allocation_basis":"user_confirmed_group_required", "matched_count":2,
         "group_count":{"ota":2,"cards":2}, "ota_group_ids":["manual-group-a","manual-group-b"],
         "card_group_ids":["manual-card-a","manual-card-b"],
         "proposed_mapping":{"manual-group-a":"manual-card-a","manual-group-b":"manual-card-b"}},
        {"ota_event_id": "unknown-date", "provider": "trip", "booking_ref": "BOOK-UNKNOWN",
         "event_type": "charge", "paid_on": "미확인", "status": "HOLD_DATE_UNKNOWN",
         "reason": "payment_date_not_in_source"},
        {"ota_event_id": "changed-1", "provider": "trip", "booking_ref": "BOOK-CHANGED",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "status": "HOLD_GROUP_CHANGED", "review_warning": "confirm_group_reallocation",
         "group_count": {"ota": 2, "cards": 2}, "ota_group_ids": ["changed-1", "changed-2"],
         "card_group_ids": ["changed-card-1", "changed-card-2"],
         "proposed_mapping": {"changed-1": "changed-card-2", "changed-2": "changed-card-1"}},
        {"ota_event_id": "changed-2", "provider": "trip", "booking_ref": "BOOK-CHANGED-2",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "status": "HOLD_GROUP_CHANGED", "review_warning": "confirm_group_reallocation",
         "group_count": {"ota": 2, "cards": 2}, "ota_group_ids": ["changed-1", "changed-2"],
         "card_group_ids": ["changed-card-1", "changed-card-2"],
         "proposed_mapping": {"changed-1": "changed-card-2", "changed-2": "changed-card-1"}},
        {"ota_event_id": "overfull-1", "provider": "trip", "booking_ref": "BOOK-OVERFULL",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "30000", "currency": "KRW",
         "amount_krw": 30000, "status": "HOLD_GROUP_CHANGED", "review_warning": "confirm_group_reallocation",
         "group_count": {"ota": 2, "cards": 3}, "ota_group_ids": ["overfull-1", "overfull-2"],
         "card_group_ids": ["overfull-card-1", "overfull-card-2", "overfull-card-3"],
         "proposed_mapping": {"overfull-1": "overfull-card-1", "overfull-2": "overfull-card-2"}},
        {"ota_event_id": "candidate", "provider": "trip", "booking_ref": "BOOK-CANDIDATE",
         "event_type": "charge", "paid_on": "2026-09-04", "amount": "12500", "currency": "KRW",
         "amount_krw": 12500, "status": "HOLD_AMOUNT_MISMATCH", "reason": "amount_differs"},
    ]
    candidate_card = {"transaction_id": "select-card", "issuer": "Synthetic Bank", "merchant": "TRIP.COM",
                      "card_tail": "2042", "approval_date": "2026-09-04", "amount_krw": 12000,
                      "approval_number": "SYN-AUTH", "transaction_direction": "purchase"}
    return {"events": events, "cards_by_event": {
        "partial-1": [dict(candidate_card, transaction_id="partial-card-1", selection_disabled=True,
                           selection_disabled_reason="반복 묶음의 부분 대응이라 개별 연결을 보류합니다."),
                      dict(candidate_card, transaction_id="partial-card-2", selection_disabled=True)],
        "ordered-1": [dict(candidate_card, transaction_id="ordered-card-1", selection_disabled=True,
                           selection_disabled_reason="사용자 승인 순서 배정이며 개별 근거는 미확인입니다.")],
        "ordered-2": [dict(candidate_card, transaction_id="ordered-card-2", selection_disabled=True)],
        "manual-group-a": [dict(candidate_card, transaction_id="manual-card-a", selection_disabled=True)],
        "manual-group-b": [dict(candidate_card, transaction_id="manual-card-b", selection_disabled=True)],
        "changed-1": [], "changed-2": [], "overfull-1": [],
        "unknown-date": [], "candidate": [candidate_card]},
        "proposals": ([{"proposal_id": "proposal-1", "status": "pending",
                        "question": "검토한 조건을 다음 거래에 적용할까요?",
                        "conditions": {"date_lag_days": -2}}
                       ] if include_proposal else [])}


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_synthetic_browser_group_candidates_disabled_proposal_and_overflow(width, height):
    state = {"proposal": False, "answered": False, "group_confirmation": None}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_default_timeout(5000)
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        def respond(route):
            request = route.request
            if request.method == "GET":
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(_snapshot(state["proposal"]), ensure_ascii=False))
                return
            payload = request.post_data_json or {}
            if request.url.endswith("/preview"):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"preview_digest": "synthetic-digest", "difference_krw": -500,
                                               "event_amount_krw": 12500, "card_amount_krw": 12000}))
            elif request.url.endswith("/group/confirm"):
                state["group_confirmation"] = payload
                route.fulfill(status=200, content_type="application/json", body='{"status":"frozen"}')
            elif request.url.endswith("/confirm"):
                state["proposal"] = True
                route.fulfill(status=200, content_type="application/json", body='{"status":"MATCHED_USER"}')
            elif request.url.endswith("/proposal"):
                state["answered"] = payload.get("action") == "once"
                route.fulfill(status=200, content_type="application/json", body='{"status":"answered_once"}')
            else:
                route.fulfill(status=404, content_type="application/json", body='{}')

        page.route("http://localhost/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=render_import_section("synthetic-csrf")))
        page.route("http://localhost/api/imports/ota**", respond)
        page.goto("http://localhost/")
        page.locator("#ota-review > summary").click()
        try:
            page.get_by_text("BOOK-PARTIAL", exact=True).wait_for()
        except Exception as error:
            raise AssertionError(f"browser snapshot failed; status={page.locator('#ota-status').inner_text()}; errors={page_errors}") from error
        partial = page.locator('[data-event="partial-1"]')
        partial.get_by_text("거래 ID 보기").click()
        assert "3건 ↔ 2건" in partial.inner_text()
        assert "부분 묶음" in partial.inner_text()
        assert "partial-1, partial-2, partial-3" in partial.inner_text()
        assert "partial-card-1, partial-card-2" in partial.inner_text()
        assert partial.locator("input[type=radio]").count() == 2
        assert partial.locator("input[type=radio]:disabled").count() == 2

        ordered = page.locator('[data-event="ordered-1"]')
        assert "사용자 승인 순서 배정" in ordered.inner_text()
        assert "개별 결제 근거 미확인" in ordered.inner_text()
        assert "2026-10-01 ~ 2026-10-03" in ordered.inner_text()
        assert ordered.locator("input[type=radio]:disabled").count() == 1
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="현재 순서 배정을 확인하고 고정").first.click()
        assert state["group_confirmation"]["event_ids"] == ["ordered-1", "ordered-2"]
        manual_group = page.get_by_role("button", name="\ud604\uc7ac \uc21c\uc11c \ubc30\uc815\uc744 \ud655\uc778\ud558\uace0 \uace0\uc815")
        assert manual_group.count() == 2
        page.once("dialog", lambda dialog: dialog.accept())
        manual_group.nth(1).click()
        assert state["group_confirmation"]["event_ids"] == ["manual-group-a", "manual-group-b"]
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="새 순서 배정 검토 및 고정").first.click()
        assert state["group_confirmation"]["replace"] is True
        reallocation_buttons = page.get_by_role("button", name="새 순서 배정 검토 및 고정")
        assert reallocation_buttons.count() == 2
        assert reallocation_buttons.nth(1).is_disabled()

        unknown = page.locator('[data-event="unknown-date"]')
        assert unknown.locator(".ota-card-row").count() == 0
        candidate = page.locator('[data-event="candidate"]')
        assert candidate.locator("input[type=radio]:not(:disabled)").count() == 1
        candidate.locator("input[type=radio]").check()
        candidate.get_by_role("button", name="차이 미리 보기").click()
        try:
            candidate.locator(".ota-preview").wait_for()
        except Exception as error:
            raise AssertionError(f"browser preview failed; status={page.locator('#ota-status').inner_text()}; errors={page_errors}") from error
        assert "500" in candidate.locator(".ota-preview").inner_text()
        candidate.get_by_role("button", name="이 거래로 결제 연결 확정").click()
        proposal = page.locator('[data-proposal="proposal-1"]')
        proposal.wait_for()
        assert proposal.get_by_label("이번 건만").is_checked()
        assert proposal.locator('input[name="date_lag_days"]').get_attribute("min") == "-7"
        proposal.get_by_role("button", name="제안에 답하기").click()
        page.get_by_text("규칙 저장 없이 이번 건만 처리했습니다.", exact=True).wait_for()
        assert state["answered"]
        assert page.evaluate("document.documentElement.scrollWidth") == width
        browser.close()


def test_synthetic_browser_submits_user_approved_alias_and_discount_selects():
    submitted = {}
    snapshot = {"events": [], "cards_by_event": {}, "proposals": [{
        "proposal_id": "alias-proposal-synthetic", "status": "pending",
        "question": "합성 별칭 규칙 확인", "conditions": {"provider": "trip", "item": "항공권"}}]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("http://localhost/", lambda route: route.fulfill(status=200,
            content_type="text/html; charset=utf-8", body=render_import_section("synthetic-csrf")))
        def respond(route):
            if route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(snapshot))
            else:
                submitted.update(route.request.post_data_json)
                route.fulfill(status=200, content_type="application/json", body='{"status":"approved"}')
        page.route("http://localhost/api/imports/ota**", respond)
        page.goto("http://localhost/")
        page.locator("#ota-review > summary").click()
        proposal = page.locator('[data-proposal="alias-proposal-synthetic"]')
        proposal.get_by_label("규칙 저장").check()
        fields = proposal.locator(".ota-proposal-fields")
        fields.get_by_label("규칙 종류").select_option("provider_alias")
        fields.locator('input[name="alias"]').fill("TRIP.COM SYNTHETIC")
        fields.get_by_label("승인 근거 출처").fill("synthetic-receipt")
        fields.get_by_label("할인율 (1/10000 단위)").fill("250")
        fields.get_by_label("할인 한도 (원)").fill("5000")
        fields.get_by_label("최소 결제 금액 (원)").fill("10000")
        fields.get_by_label("원 단위 처리").select_option("half_up")
        fields.get_by_label("결제 수단").fill("synthetic-card")
        fields.get_by_label("적용 시작일").fill("2026-09-01")
        fields.get_by_label("적용 종료일").fill("2026-09-30")
        with page.expect_response(lambda response: response.url.endswith("/proposal") and
                                  response.request.method == "POST") as response_info:
            proposal.get_by_role("button", name="제안에 답하기").click()
        submitted.update(response_info.value.request.post_data_json)
        assert submitted["action"] == "approve"
        assert submitted["conditions"]["rule_kind"] == "provider_alias"
        assert submitted["conditions"]["alias"] == "TRIP.COM SYNTHETIC"
        assert submitted["conditions"]["rounding_mode"] == "half_up"
        assert submitted["conditions"]["discount_rate_bps"] == 250
        browser.close()


def test_synthetic_browser_submits_signed_lag_range_without_legacy_scalar():
    submitted = {}
    snapshot = {"events": [], "cards_by_event": {}, "proposals": [{
        "proposal_id":"lag-range-synthetic", "status":"pending",
        "conditions":{"provider":"trip", "item":"flight", "currency":"KRW",
                      "event_type":"charge", "date_lag_days":0}}]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width":390, "height":844})
        page.route("http://localhost/", lambda route: route.fulfill(status=200,
            content_type="text/html; charset=utf-8", body=render_import_section("synthetic-csrf")))
        def respond(route):
            if route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(snapshot))
            else:
                submitted.update(route.request.post_data_json)
                route.fulfill(status=200, content_type="application/json", body='{"status":"approved"}')
        page.route("http://localhost/api/imports/ota**", respond)
        page.goto("http://localhost/")
        page.locator("#ota-review > summary").click()
        proposal = page.locator('[data-proposal="lag-range-synthetic"]')
        proposal.get_by_label("\uaddc\uce59 \uc800\uc7a5").check()
        fields = proposal.locator(".ota-proposal-fields")
        fields.locator('input[name="date_lag_min_days"]').fill("-1")
        fields.locator('input[name="date_lag_max_days"]').fill("2")
        with page.expect_response(lambda response: response.url.endswith("/proposal") and
                                  response.request.method == "POST") as response_info:
            proposal.get_by_role("button", name="\uc81c\uc548\uc5d0 \ub2f5\ud558\uae30").click()
        submitted.update(response_info.value.request.post_data_json)
        assert submitted["conditions"]["date_lag_min_days"] == -1
        assert submitted["conditions"]["date_lag_max_days"] == 2
        assert "date_lag_days" not in submitted["conditions"]
        assert submitted["conditions"]["currency"] == "KRW"
        assert submitted["conditions"]["event_type"] == "charge"
        assert page.evaluate("document.documentElement.scrollWidth") == 390
        browser.close()
