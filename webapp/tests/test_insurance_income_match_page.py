import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

from webapp import insurance_income_match_page as page


def state(rows=None):
    rows = rows or [{"review_row_id": "review-1", "masked_name": "김*람",
                     "match_state": "ambiguous", "candidate_count": 2,
                     "matches": [{"ref": "private-ref-1", "fingerprint": "fp", "name": "가람<합성>",
                                  "nickname": "별명", "date": "2026-10-01", "amount": 1234,
                                  "trip_id": "trip-secret", "trip_name": "합성 여행"},
                                 {"ref": "private-ref-2", "name": "가람2", "date": "2026-10-02",
                                  "amount": None, "trip_id": "trip-secret", "trip_name": "합성 여행"}]}]
    contract = {"contract_key": "contract-syn", "travel_start": "2026-10-01",
                "travel_end": "2026-10-05", "insurance_status": "completed_or_expired",
                "trip_options": [{"trip_id": "trip-secret", "trip_name": "합성 여행"}], "rows": rows}
    return {"available": True, "code": "OK", "message": "정상", "fingerprint": "fp",
            "counts": {"contracts": 1, "rows": len(rows), "matched": 0, "ambiguous": 1,
                       "unmatched": 0, "no_visible_letters": 0}, "contracts": [contract]}


class Handler:
    command = "GET"
    def __init__(self): self.sent = []
    def _send_json(self, body, status=200): self.sent.append(("json", body, status))
    def _send(self, body, status=200): self.sent.append(("html", body, status))


class InsuranceIncomeMatchPageTests(unittest.TestCase):
    def test_routes_and_masked_candidate_display(self):
        self.assertTrue(page.owns_route(page.PAGE_PATH))
        document = page.render_page(state())
        self.assertIn("보험 명단 · 수입 글자 대조", document)
        self.assertIn("김*람", document)
        self.assertIn("후보 여러 건", document)
        self.assertIn("가람&lt;합성&gt;", document)
        self.assertIn("글자 대조는 보험 가입 완료", document)
        self.assertIn("candidate-choice", document)
        self.assertIn("50", document)
        self.assertIn("가입 완료 또는 기간 종료(조회 자료)", document)
        self.assertNotIn("completed_or_expired", document)
        self.assertNotIn(">contract-syn<", document)
        self.assertIn("value='contract-syn'", document)

    def test_amount_keeps_fraction_and_negative_sign(self):
        self.assertEqual(page._amount("1234.50"), "1,234.50원")
        self.assertEqual(page._amount("-1234.5"), "-1,234.5원")
        self.assertEqual(page._amount(None), "금액 미기재")
        self.assertEqual(page._amount("0"), "0원")

    def test_contract_scope_and_unavailable_freshness_are_shown_safely(self):
        payload = state()
        payload["contracts"][0]["scope_label"] = "연결된 여행 기간 자료"
        doc = page.render_page(payload)
        self.assertIn("연결된 여행 기간 자료", doc)
        payload.update(available=False, code="STALE", message="다시 동기화 필요",
                       inputs_freshness="오래된 자료 <확인>")
        doc = page.render_page(payload)
        self.assertIn("자료 최신성: 오래된 자료 &lt;확인&gt;", doc)

    def test_all_rows_are_accounted_for_by_bounded_pagination(self):
        rows = [{"review_row_id": f"r{i}", "masked_name": f"이*{i}",
                 "match_state": "unmatched", "candidate_count": 0, "matches": []}
                for i in range(159)]
        doc = page.render_page(state(rows))
        self.assertIn("전체 159건", doc)
        self.assertIn("1 / 4", doc)
        self.assertIn("data-page-size='50'", doc)

    def test_non_owner_is_refused_before_loader(self):
        handler, called = Handler(), []
        handled = page.dispatch(handler, urlsplit(page.PAGE_PATH), is_owner=False,
                                state_loader=lambda **kw: called.append(True))
        self.assertTrue(handled)
        self.assertEqual(called, [])
        self.assertEqual(handler.sent[0][2], 403)

    def test_get_only_and_raw_payload_rejected(self):
        for command, raw in (("POST", None), ("GET", b"")):
            handler = Handler(); handler.command = command
            page.dispatch(handler, urlsplit(page.PAGE_PATH), is_owner=True, raw=raw,
                          state_loader=lambda **kw: self.fail("loader must not run"))
            self.assertEqual(handler.sent[0][2], 405)

    def test_owner_loader_receives_filters_and_api_has_no_source_paths(self):
        handler, received = Handler(), []
        query = {"contract_key": ["contract-syn"], "trip": ["trip-secret"]}
        page.dispatch(handler, urlsplit(page.ROUTES[1]), is_owner=True, query=query,
                      state_loader=lambda **kw: received.append(kw) or state())
        self.assertEqual(received, [{"query": query}])
        self.assertEqual(handler.sent[0][0], "json")
        self.assertNotIn("/private/", repr(handler.sent[0][1]))

    def test_loader_exception_does_not_leak_exception_path(self):
        handler = Handler()
        page.dispatch(handler, urlsplit(page.ROUTES[1]), is_owner=True,
                      state_loader=lambda **kw: (_ for _ in ()).throw(OSError("C:/private/source.pdf")))
        self.assertNotIn("source.pdf", repr(handler.sent[0][1]))
        self.assertEqual(handler.sent[0][1]["code"], "SOURCE_UNAVAILABLE")

    def test_html_error_status_matches_api_status(self):
        for code, expected in (("INVALID_FILTER", 400), ("SOURCE_UNAVAILABLE", 503)):
            handler = Handler()
            page.dispatch(handler, urlsplit(page.PAGE_PATH), is_owner=True,
                          state_loader=lambda **kw: {"available": False, "code": code})
            self.assertEqual(handler.sent[0][2], expected)


if __name__ == "__main__":
    unittest.main()
