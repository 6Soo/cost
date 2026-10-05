"""Compact review and source answers through the real synthetic HTTP server."""
import json

from webapp.tests.test_real_review_browser import ReviewBrowserFixture, SETTLE_MS


class GuidanceBrowserTests(ReviewBrowserFixture):
    def wait_message(self, card, needle):
        card.locator(".guidance-message").filter(has_text=needle).wait_for(timeout=SETTLE_MS)

    def test_compact_mobile_card_hides_addresses_and_keeps_a_valid_two_column_table(self):
        page = self.open_review(viewport={"width": 375, "height": 844})
        card = self.card(page)
        visible = card.inner_text()
        self.assertNotIn(self.ref_of(0), visible)
        self.assertNotIn("APPROVAL-0001", visible)
        self.assertIn("검토 메모·요청 내용", visible)
        self.assertEqual(
            card.locator("label").filter(has_text="검토 메모·요청 내용").get_attribute("for"),
            card.locator("textarea").get_attribute("id"))
        # The current memo explanation is part of the collapsed card. Keep the
        # usable mobile contract: the card and its input/actions fit in one
        # viewport after scrolling to it, rather than a legacy pixel budget.
        page.evaluate("document.fonts.ready")
        self.assertLessEqual(card.bounding_box()["height"], page.viewport_size["height"])
        card.scroll_into_view_if_needed()
        for control in (card.locator("textarea"),
                        card.get_by_role("button", name="답변 저장", exact=True),
                        card.get_by_role("button", name="저장된 답변 보기", exact=True)):
            bounds = control.bounding_box()
            self.assertGreaterEqual(bounds["y"], 0)
            self.assertLessEqual(bounds["y"] + bounds["height"], page.viewport_size["height"])
        self.assertEqual(card.locator(".review-evidence[open]").count(), 0)
        self.assertEqual(card.locator(".guidance-rule[open]").count(), 0)
        card.locator(".review-evidence > summary").click()
        table = card.locator("table.fields")
        self.assertEqual(table.locator("thead th").all_text_contents(), ["항목", "값"])
        self.assertTrue(table.evaluate("t => [...t.rows].every(r => r.cells.length === 2)"))
        self.assertNotIn("칸", table.inner_text())
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 375)

    def test_answer_survives_reopen_and_conflicts_do_not_overwrite_another_device(self):
        first, second = self.open_review(), self.open_review()
        one, two = self.card(first), self.card(second)
        with second.expect_response("**/api/review/guidance?*"):
            two.locator("textarea").focus()
        note = "합성 답변 <script>window.guideInjected=1</script>"
        one.locator("textarea").fill(note)
        one.get_by_role("button", name="답변 저장", exact=True).click()
        self.wait_message(one, "저장했습니다")
        two.locator("textarea").fill("다른 기기의 입력")
        two.get_by_role("button", name="답변 저장", exact=True).click()
        self.wait_message(two, "다른 기기")
        self.assertEqual(two.locator("textarea").input_value(), "다른 기기의 입력")
        second.reload()
        second.wait_for_selector("#rows .card")
        two = self.card(second)
        two.get_by_role("button", name="저장된 답변 보기").click()
        self.wait_message(two, "불러왔습니다")
        self.assertEqual(two.locator("textarea").input_value(), note)
        self.assertIsNone(second.evaluate("window.guideInjected"))
        self.assertEqual(self.chosen(first), "")
        self.assertEqual(self.server_state()[1]["revision"], 0)
        self.assertEqual(len(self.store.list_tab_rows(None)), 0)

    def test_rule_preview_and_apply_have_independent_scope_and_no_card_approval(self):
        page = self.open_review()
        card = self.card(page)
        card.locator(".guidance-rule > summary").click()
        card.get_by_label("바꿀 항목", exact=True).fill("합성 숙박비")
        card.get_by_label("앞으로 가져오는 카드 내역에 적용").check()
        with page.expect_response("**/api/review/guidance/rule-preview") as preview_response:
            card.get_by_role("button", name="영향 미리보기", exact=True).click()
        response = preview_response.value
        self.assertEqual(response.status, 200, response.text())
        self.assertIn("기존 장부 0건", card.locator(".rule-preview").inner_text())
        card.get_by_role("button", name="확인한 규칙 적용", exact=True).click()
        self.wait_message(card, "규칙을 저장했습니다")
        self.assertEqual(self.chosen(page), "")
        self.assertEqual(self.server_state()[1]["revision"], 0)
        self.assertEqual(len(self.store.list_tab_rows(None)), 0)
        self.assertEqual(len(self.store.active_future_rules()), 1)

    def test_owner_csrf_and_origin_guards_cover_the_new_write_routes(self):
        from webapp import access_control
        self.access.create_account(user_id="synthetic-viewer", role="viewer")
        page = self.open_review()
        base = f"http://127.0.0.1:{self.port}"
        for action in ("save", "rule-preview", "rule-apply"):
            route = f"{base}/api/review/guidance/{action}"
            response = page.request.post(route, data=json.dumps({}), headers={
                "Content-Type": "application/json", "Origin": base})
            self.assertEqual(response.status, 403)
            response = page.request.post(route, data=json.dumps({}), headers={
                "Content-Type": "application/json", "Origin": "https://different.invalid"})
            self.assertEqual(response.status, 403)
            response = page.request.post(route, data=json.dumps({}), headers={
                "Content-Type": "application/json", "Origin": base,
                access_control.SyntheticSessionAdapter.HEADER: "synthetic-viewer"})
            self.assertEqual(response.status, 403)
