import json
from urllib.parse import urlsplit
from unittest import mock

import pytest

from app.ota_queue_paging import build_queue_index, list_queue_page
from webapp import access_control, ledger_board, ota_payment_review
from webapp.ota_snapshot import OtaSnapshotService


KEY = b"page-route-test-key-0123456789-abcdef"


def event_row(event_id, **extra):
    return {"ota_event_id": event_id, "provider": "agoda", "booking_ref": "BOOK-1",
            "event_type": "booking", "paid_on": "2026-09-10", "item": "Synthetic stay",
            "amount": 1000, "currency": "KRW", "status": "HOLD_AMBIGUOUS",
            "evidence_status": "conflict", "source_digest": "private-digest",
            **extra}


def route_rows(count=53):
    return [{"queue": "needs_action", "reason_codes": ["HOLD_AMBIGUOUS"],
             "event": {"ota_event_id": f"evt-{n:04}", "provider": "agoda",
                       "booking_ref": f"BOOK-{n}", "event_type": "booking",
                       "paid_on": "2026-09-10", "item": "Synthetic stay",
                       "amount": 1000, "currency": "KRW",
                       "status": "HOLD_AMBIGUOUS", "merchant": "Synthetic merchant",
                       "source_digest": "PRIVATE-DIGEST-DO-NOT-LEAK",
                       "raw_source": "PRIVATE-BODY-DO-NOT-LEAK"}}
            for n in range(count)]


class Handler:
    def __init__(self, path, user="synthetic-user"):
        self.path = path
        self.current_user_id = lambda: user
        self.headers = {}
        self.response = None

    def _send_json(self, body, status=200):
        self.response = (status, body)


class PageBackend:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def queue_page_context(self):
        self.calls.append("page_context")
        return self.context

    def _data(self):
        self.calls.append("data")
        raise AssertionError("request must not access backend data")

    def cards_for_event(self, *_args):
        self.calls.append("cards")
        raise AssertionError("request must not materialize cards")


def ready_context(rows=None, generation=7):
    index = build_queue_index(rows if rows is not None else route_rows(), generation=generation,
                              snapshot_nonce="opaque-generation-token", signing_key=KEY)
    return {"index": index, "status": "ready", "generation": generation,
            "generated_at": "2026-10-28T01:02:03+00:00", "fresh": True,
            "stale": False, "refreshing": False}


def dispatch(path, backend, user="synthetic-user"):
    handler = Handler(path, user)
    with mock.patch.object(ota_payment_review, "enabled", return_value=True):
        ota_payment_review.dispatch(handler, urlsplit(path), backend=backend)
    return handler.response


def test_canonical_rows_preserve_cardinality_and_summary_page_queue_counts_match():
    events = [event_row(f"evt-{n:02}") for n in range(50)]
    events += [event_row("duplicate"), event_row("duplicate"), event_row(None)]
    results = [{"ota_event_id": f"evt-{n:02}", "status": "HOLD_AMBIGUOUS",
                "reason": "private reason", "evidence_status": "conflict"}
               for n in range(50)]
    orphan = {"ota_event_id": "orphan", "status": "MATCHED_AUTO",
              "reason": "unique_exact_evidence", "evidence_status": "paid_verified"}
    events_before = json.dumps(events, sort_keys=True)
    results_before = json.dumps(results, sort_keys=True)
    joined = ota_payment_review._canonical_queue_rows(events, results, {})
    summary = ota_payment_review._canonical_queue_summary_rows(joined)
    page_rows = ota_payment_review._canonical_queue_page_rows(joined)
    index = build_queue_index(page_rows, generation=1, snapshot_nonce="joined",
                              signing_key=KEY)
    assert len(joined) == len(events)
    assert len(page_rows) == sum(bucket["event_count"]
                                 for bucket in summary["counts_by_queue"].values())
    page_counts = {queue: sum(row["queue"] == queue for row in page_rows)
                   for queue in summary["counts_by_queue"]}
    assert page_counts == {queue: bucket["event_count"]
                           for queue, bucket in summary["counts_by_queue"].items()}
    assert len(ota_payment_review._canonical_queue_rows([], [orphan], {})) == 1
    duplicate_rows = [row for row in page_rows
                      if row["event"]["ota_event_id"] == "duplicate"]
    assert len(duplicate_rows) == 2
    assert all(row["queue"] == "needs_action" for row in duplicate_rows)
    assert any("EVENT_ID_MISSING" in row["reason_codes"] for row in page_rows)
    first = list_queue_page(index, limit=20)
    second = list_queue_page(index, limit=20, cursor=first["next_cursor"])
    third = list_queue_page(index, limit=20, cursor=second["next_cursor"])
    assert [len(first["items"]), len(second["items"]), len(third["items"])] == [20, 20, 13]
    assert first["total_count"] == summary["counts_by_queue"]["needs_action"]["event_count"]
    assert json.dumps(events, sort_keys=True) == events_before
    assert json.dumps(results, sort_keys=True) == results_before


def test_events_get_pages_without_classification_sort_reconcile_or_candidate_calls():
    backend = PageBackend(ready_context())
    with (mock.patch.object(ota_payment_review, "classify_event", side_effect=AssertionError),
          mock.patch.object(ota_payment_review, "summarize_queue", side_effect=AssertionError),
          mock.patch.object(ota_payment_review, "build_queue_index", side_effect=AssertionError)):
        first_status, first = dispatch("/api/imports/ota/events?limit=20", backend)
        second_status, second = dispatch(
            "/api/imports/ota/events?limit=20&cursor=" + first["next_cursor"], backend)
        third_status, third = dispatch(
            "/api/imports/ota/events?limit=20&cursor=" + second["next_cursor"], backend)
    assert (first_status, second_status, third_status) == (200, 200, 200)
    assert [len(first["items"]), len(second["items"]), len(third["items"])] == [20, 20, 13]
    ids = [item["event"]["ota_event_id"] for page in (first, second, third)
           for item in page["items"]]
    assert len(ids) == len(set(ids)) == 53
    assert backend.calls == ["page_context"] * 3
    encoded = json.dumps((first, second, third))
    assert "PRIVATE-DIGEST" not in encoded
    assert "PRIVATE-BODY" not in encoded
    assert "source_digest" not in encoded
    assert set(first["items"][0]["event"]) == {
        "ota_event_id", "provider", "booking_ref", "event_type", "paid_on",
        "item", "currency", "amount", "status"}


@pytest.mark.parametrize("query", [
    "limit=+1", "limit=01x", "limit=0", "limit=101", "queue=unknown",
    "q=", "cursor=", "limit=20&limit=10", "queue=needs_action&queue=completed",
    "unknown=1", "limit=1;queue=completed",
])
def test_events_get_rejects_malformed_or_duplicate_query_parameters(query):
    status, body = dispatch("/api/imports/ota/events?" + query, PageBackend(ready_context()))
    assert status == 400
    assert body["code"] in ("INVALID_QUERY", "INVALID_INPUT")
    assert query not in json.dumps(body)


@pytest.mark.parametrize('query', ['limit=0', 'provider=bad%20provider', 'q=', 'q=' + 'x' * 121])
def test_invalid_queries_fail_before_reading_snapshot_context(query):
    backend = PageBackend({})
    status, body = dispatch('/api/imports/ota/events?' + query, backend)
    assert status == 400 and body['code'] == 'INVALID_QUERY'
    assert backend.calls == []


def test_events_get_auth_cursor_filter_generation_and_snapshot_failures_are_finite():
    backend = PageBackend(ready_context())
    status, body = dispatch("/api/imports/ota/events", backend, user="")
    assert status == 403 and body["code"] == "ACCESS_REQUIRED"

    page_status, page = dispatch("/api/imports/ota/events?limit=1", backend)
    assert page_status == 200
    cursor = page["next_cursor"]
    assert dispatch("/api/imports/ota/events?limit=2&cursor=" + cursor, backend)[0] == 409
    filter_status, filter_error = dispatch(
        "/api/imports/ota/events?provider=expedia&limit=1&cursor=" + cursor, backend)
    assert filter_status == 409 and filter_error["code"] == "SNAPSHOT_CHANGED"
    changed_generation = PageBackend(ready_context(generation=8))
    generation_status, generation_error = dispatch(
        "/api/imports/ota/events?limit=1&cursor=" + cursor, changed_generation)
    assert generation_status == 409 and generation_error["code"] == "SNAPSHOT_CHANGED"
    tampered_status, tampered_error = dispatch(
        "/api/imports/ota/events?limit=1&cursor=" + cursor[:-2] + "AA", backend)
    assert tampered_status == 400 and tampered_error["code"] == "BAD_CURSOR"

    for context in (
        {**ready_context(), "status": "refreshing", "fresh": False, "stale": True},
        {**ready_context(), "index": None},
        {"index": None, "status": "loading", "generation": 0, "fresh": False,
         "stale": True, "refreshing": False},
    ):
        status, response = dispatch("/api/imports/ota/events", PageBackend(context))
        assert status == 409
        assert response["code"] == "SNAPSHOT_NOT_READY"
        assert "index" not in json.dumps(response)


def test_groups_route_is_authenticated_limited_and_keeps_member_details_private_until_lazy_get():
    rows = []
    for n in range(23):
        event = {"ota_event_id":f"group-{n:02}", "provider":"agoda",
                 "booking_ref":f"BOOK-{n}", "event_type":"charge", "paid_on":"2026-09-10",
                 "amount":1000, "currency":"KRW", "status":"HOLD_AMBIGUOUS",
                 "group_members":[{"ota_event_id":f"member-{n}-charge", "event_type":"charge",
                                    "amount":1000, "currency":"KRW", "status":"HOLD_AMBIGUOUS"},
                                   {"ota_event_id":f"member-{n}-refund", "event_type":"refund",
                                    "amount":200, "currency":"KRW", "status":"HOLD_EVIDENCE_CONFLICT"}],
                 "source_digest":"PRIVATE", "reservation_identity_attestation":{"identity":"PRIVATE"}}
        rows.append({"queue":"needs_action", "reason_codes":["HOLD_AMBIGUOUS"], "event":event})
    context = ready_context(rows)

    class GroupBackend(PageBackend):
        def queue_group_context(self):
            self.calls.append("group_context")
            return context

    backend = GroupBackend(context)
    assert dispatch("/api/imports/ota/groups?limit=21", backend)[0] == 400
    assert dispatch("/api/imports/ota/groups", backend, user="")[0] == 403
    status, first = dispatch("/api/imports/ota/groups?limit=20", backend)
    assert status == 200 and len(first["items"]) == 20
    assert first["next_cursor"]
    serialized = json.dumps(first)
    assert "PRIVATE" not in serialized and "reservation_identity_attestation" not in serialized
    assert len(first["items"][0]["event"]["group_members"]) == 2
    status, second = dispatch("/api/imports/ota/groups?limit=20&cursor=" + first["next_cursor"], backend)
    assert status == 200 and len(second["items"]) == 3
    ids = [item["event"]["ota_event_id"] for item in first["items"] + second["items"]]
    assert ids == [f"group-{n:02}" for n in range(23)]


def test_large_group_member_pages_are_bounded_complete_private_and_generation_bound():
    from webapp.ota_payment_review import _canonical_queue_projection
    source_rows = []
    count = 1003
    for number in range(count):
        source_rows.append({
            "ota_event_id":f"large-member-{number:04}", "provider":"agoda",
            "booking_ref":"SYNTH-LARGE", "event_type":"refund" if number % 3 == 0 else "charge",
            "paid_on":"2026-10-01", "amount":100 + number, "currency":"KRW",
            "status":"HOLD_EVIDENCE_CONFLICT" if number % 3 == 0 else "HOLD_DATE_UNKNOWN",
            "evidence_status":"conflict" if number % 3 == 0 else "paid_verified",
            "reservation_identity_attestation":{"provider":"agoda", "identity":"opaque-synthetic",
                "identity_status":"verified", "evidence_status":"verified", "source_status":"verified",
                "source_lineage_id":"synthetic-lineage", "evidence_link_ids":["link"]},
            "_portal_reservation_provenance":{"provider":"agoda", "identity":"opaque-synthetic",
                "source_digest":"PRIVATE-DIGEST", "source_lineage_id":"synthetic-lineage"},
        })
    page_rows, groups, summary, member_rows = _canonical_queue_projection(source_rows)
    assert len(groups) == 1 and groups[0]["event"]["group_total_count"] == count
    assert len(groups[0]["event"]["group_members"]) == 3
    assert summary["verified_group_count"] == 1 and summary["singleton_fallback_count"] == 0
    group_id = groups[0]["event"]["group_id"]
    member_index = build_queue_index(member_rows[group_id], generation=17,
                                     snapshot_nonce="large-group-members", signing_key=KEY)
    list_index = build_queue_index(groups, generation=17,
                                   snapshot_nonce="large-group-list", signing_key=KEY)

    class MembersBackend(PageBackend):
        def queue_group_context(self):
            return {"index":list_index, "status":"ready", "generation":17,
                    "generated_at":"2026-10-28T00:00:00+00:00", "fresh":True,
                    "stale":False, "refreshing":False}

        def queue_group_members_context(self, requested_id, generation):
            self.calls.append((requested_id, generation))
            return {"index":member_index, "status":"ready", "generation":17,
                    "generated_at":"2026-10-28T00:00:00+00:00", "fresh":True,
                    "stale":False, "refreshing":False}

    backend = MembersBackend({})
    status, listing = dispatch("/api/imports/ota/groups?limit=20", backend)
    assert status == 200 and len(listing["items"]) == 1
    card = listing["items"][0]["event"]
    assert len(card["group_members"]) <= 3 and card["group_total_count"] == count
    assert "PRIVATE-DIGEST" not in json.dumps(listing)
    assert not backend.calls

    seen = []
    cursor = None
    while True:
        query = f"generation=17&limit=20" + ("&cursor=" + cursor if cursor else "")
        status, body = dispatch(f"/api/imports/ota/groups/{group_id}/members?{query}", backend)
        assert status == 200
        items = body["items"]
        assert 0 < len(items) <= 20
        seen.extend(item["event"]["ota_event_id"] for item in items)
        assert "PRIVATE-DIGEST" not in json.dumps(body)
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == count and len(set(seen)) == count
    assert set(seen) == {f"large-member-{number:04}" for number in range(count)}
    assert dispatch(f"/api/imports/ota/groups/{group_id}/members?generation=18&limit=20", backend)[0] == 409
    assert dispatch(f"/api/imports/ota/groups/{group_id}/members?generation=17&limit=21", backend)[0] == 400


def test_snapshot_worker_builds_index_at_publication_and_hides_private_state(tmp_path):
    rows = route_rows(3)
    service = OtaSnapshotService(
        key_fn=lambda: "synthetic-input-key",
        reconcile_fn=lambda: {"public": {"events": []}, "results": [], "links": {},
                              "data": {"events": ["private"]}, "queue_summary": {"x": 1},
                              "queue_page_rows": rows, "queue_group_rows": rows},
        persist_path=tmp_path / "snapshot.json", start=False)
    service.check_now()
    view = service.view()
    assert view["status"] == "ready"
    assert "_queue_page_index" not in json.dumps(view)
    assert "queue_page_rows" not in json.dumps(view)
    context = service.queue_page_context()
    assert context["index"]._generation == view["generation"] == 1
    assert context["status"] == "ready"
    group_context = service.queue_group_context()
    assert group_context["index"]._generation == view["generation"]
    persisted = (tmp_path / "snapshot.json").read_text(encoding="utf-8")
    assert "_queue_page_index" not in persisted
    assert "queue_page_rows" not in persisted
    assert "queue_group_rows" not in persisted
    assert "_queue_group_index" not in persisted
    assert "signing_key" not in persisted

    restored = OtaSnapshotService(
        key_fn=lambda: "synthetic-input-key",
        reconcile_fn=lambda: {"public": {}, "results": [], "links": {}, "data": {},
                              "queue_page_rows": rows, "queue_group_rows": rows},
        persist_path=tmp_path / "snapshot.json", start=False)
    before_rebuild = restored.queue_page_context()
    assert before_rebuild["index"] is None
    assert restored.queue_group_context()["index"] is None
    assert before_rebuild["status"] == "refreshing"
    restored_status, restored_error = dispatch(
        "/api/imports/ota/events", PageBackend(before_rebuild))
    assert restored_status == 409
    assert restored_error["code"] == "SNAPSHOT_NOT_READY"
    restored.check_now()
    after_rebuild = restored.queue_page_context()
    assert after_rebuild["status"] == "ready"
    assert after_rebuild["index"]._generation == view["generation"] + 1
    assert restored.queue_group_context()["index"]._generation == view["generation"] + 1


def test_real_portal_producer_solver_worker_keeps_private_attestation_only_in_memory(tmp_path):
    from app.ota_payments import build_ota_payment_events, match_ota_payment_events
    from tests.card_pipeline.test_ota_portal import portal_database
    source_path = portal_database(tmp_path / "producer-worker.sqlite")
    events = build_ota_payment_events({"portal_databases":[source_path]})
    results = match_ota_payment_events(events, [])
    private_fields = ("reservation_identity_attestation", "_portal_reservation_provenance")
    assert events and all(all(key in result for key in private_fields) for result in results)
    persisted_path = tmp_path / "producer-worker-snapshot.json"
    service = OtaSnapshotService(
        key_fn=lambda:"synthetic-real-producer-key",
        reconcile_fn=lambda:{"public":{"events":[], "proposals":[]}, "results":results,
                             "links":{}, "data":{"events":events}},
        persist_path=persisted_path, start=False)
    service.check_now()
    assert all(all(key in row for key in private_fields) for row in service._current["results"])
    public_results = service.view()["current"]["results"]
    assert all(not any(key in row for key in private_fields) for row in public_results)
    text = persisted_path.read_text(encoding="utf-8")
    assert all(key not in text for key in private_fields)
    document = json.loads(text)
    assert len(document["results"]) == len(results)
    assert all(row.get("source_digest") for row in document["results"])
    assert all(row.get("source_lineage_ids") for row in document["results"])


def test_failed_refresh_retains_prior_index_but_route_freshness_gate_blocks_it():
    calls = {"n": 0}

    def reconcile():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic refresh failure")
        return {"public": {}, "results": [], "links": {}, "data": {},
                "queue_page_rows": route_rows(2)}

    keys = iter(("key-a", "key-b"))
    service = OtaSnapshotService(key_fn=lambda: next(keys), reconcile_fn=reconcile,
                                 start=False)
    service.check_now()
    prior = service.queue_page_context()["index"]
    service.check_now()
    context = service.queue_page_context()
    assert context["index"] is prior
    assert context["status"] == "error"
    backend = PageBackend(context)
    status, response = dispatch("/api/imports/ota/events", backend)
    assert status == 409
    assert response["code"] == "SNAPSHOT_NOT_READY"


def test_host_auth_refusal_remains_401_for_missing_login():
    response = {}

    class HostHandler:
        command = "GET"
        path = "/api/imports/ota/events"
        headers = {"Accept": "application/json"}

        def _send_json(self, body, code=200):
            response.update(status=code, body=body)

        def _send(self, *_args, **_kwargs):
            raise AssertionError("JSON API denial should remain JSON")

    handler = HostHandler()
    ledger_board.Handler._phase7_refuse(
        handler, access_control.AccessError(access_control.AUTH_REQUIRED,
                                            "login required", status=401))
    assert response["status"] == 401
    assert response["body"]["code"] == access_control.AUTH_REQUIRED
