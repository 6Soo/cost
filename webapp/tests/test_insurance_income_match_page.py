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
    def _send(self, body): self.sent.append(("html", body, 200))


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


if __name__ == "__main__":
    unittest.main()
