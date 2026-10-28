import json
from urllib.parse import urlsplit
from unittest import mock

import pytest

from webapp import ota_payment_review
from webapp.ota_snapshot import OtaSnapshotService, SnapshotReadError


@pytest.mark.parametrize("limit", ["0", "21"])
def test_proposal_limit_rejected_before_context_read(limit):
    with pytest.raises(ValueError):
        ota_payment_review._strict_generation_query(
            f"generation=1&limit={limit}", proposals=True)


def source(event_id, **extra):
    return {"ota_event_id": event_id, "provider": "agoda", "booking_ref": "SYN-BOOK",
            "event_type": "charge", "paid_on": "2026-10-01", "amount": 12500,
            "currency": "KRW", "item": "Synthetic stay", "source_digest": "PRIVATE-DIGEST",
            "raw_source": "PRIVATE-MAIL-BODY", **extra}


class Handler:
    def __init__(self, path, user="synthetic-owner"):
        self.current_user_id = lambda: user
        self.headers = {}
        self.response = None
        self.path = path

    def _send_json(self, body, status=200):
        self.response = status, body


class DetailBackend:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def queue_detail_context(self, event_id, generation):
        self.calls.append((event_id, generation))
        if self.error:
            raise self.error
        return self.result

    def _data(self):
        raise AssertionError("detail GET must not read backend data")

    def snapshot_from(self, *_args, **_kwargs):
        raise AssertionError("detail GET must not rebuild public snapshots")

    def cards_for_event(self, *_args):
        raise AssertionError("detail GET must not materialize candidates")


def dispatch(path, backend, user="synthetic-owner"):
    handler = Handler(path, user)
    with mock.patch.object(ota_payment_review, "enabled", return_value=True):
        ota_payment_review.dispatch(handler, urlsplit(path), backend=backend)
    return handler.response


def test_worker_detail_projection_prefers_enriched_public_rows_and_excludes_ambiguous_ids():
    events = [source("unique"), source("duplicate"), source("duplicate"), source(None)]
    results = [
        {"ota_event_id": "unique", "status": "HOLD_AMBIGUOUS", "reason": "private reason"},
        {"ota_event_id": "duplicate", "status": "HOLD_AMBIGUOUS"},
    ]
    joined = ota_payment_review._canonical_queue_rows(events, results, {})
    enriched = ota_payment_review.public_snapshot({"events": [{
        **source("unique"), "status": "HOLD_AMBIGUOUS", "reason": "private reason",
        "card_candidate_count": 3, "candidate_count": 2,
        "candidate_search": {"candidates": ["PRIVATE-CARD"]},
    }], "proposals": []})
    details, ambiguous = ota_payment_review._canonical_queue_detail_data(
        joined, events, results, enriched)
    assert set(details) == {"unique"}
    assert "duplicate" in ambiguous
    assert details["unique"]["card_candidate_count"] == 3
    encoded = json.dumps(details)
    assert "PRIVATE-DIGEST" not in encoded
    assert "PRIVATE-MAIL-BODY" not in encoded
    assert "PRIVATE-CARD" not in encoded
    assert "source_digest" not in encoded
    assert "candidate_search" not in encoded
    assert None not in details


def test_source_only_and_orphan_result_rows_remain_without_detail_lookup():
    events = [source("source-only")]
    results = [{"ota_event_id": "orphan-result", "status": "MATCHED_AUTO"}]
    queue_rows = ota_payment_review._canonical_queue_rows(events, results, {})
    details, ambiguous = ota_payment_review._canonical_queue_detail_data(
        queue_rows, events, results, {"events": [], "proposals": []})
    assert details == {}
    assert ambiguous == frozenset()


def test_worker_group_evidence_preserves_peers_without_candidate_materialization():
    events = [source("a", booking_ref="SYN-A"), source("b", booking_ref="SYN-B")]
    results = [{"ota_event_id": identity, "status": "MATCHED_AUTO",
                "transaction_id": "card-" + identity, "ota_group_ids": ["a", "b"],
                "card_group_ids": ["card-a", "card-b"]} for identity in ("a", "b")]
    cards = [{"transaction_id": "card-" + identity, "merchant": "Synthetic shop",
              "approval_date": "2026-10-02", "amount_krw": 12500,
              "raw_source": "PRIVATE-CARD-SOURCE"} for identity in ("a", "b")]
    rows = ota_payment_review._canonical_queue_rows(events, results, {})
    details, _ = ota_payment_review._canonical_queue_detail_data(
        rows, events, results, {"events": []}, cards)
    assert [pair["booking_ref"] for pair in details["a"]["group_pairs"]] == ["SYN-A", "SYN-B"]
    assert details["a"]["group_pairs"][1]["approval_date"] == "2026-10-02"
    assert "PRIVATE" not in json.dumps(details)


def test_detail_get_is_authenticated_strict_generation_and_allowlisted():
    public_event = ota_payment_review.public_snapshot({"events": [{
        **source("evt/encoded"), "status": "HOLD_AMBIGUOUS", "reason": "amount_differs",
        "card_candidate_count": 2, "candidate_search": {"candidates": ["secret"]},
    }], "proposals": []})["events"][0]
    fingerprint = "a" * 64
    rule_fingerprint = "b" * 64
    backend = DetailBackend({"event": public_event, "generation": 12, "ambiguous": False,
        "summary": {"snapshot_status":"ready", "generation":12, "fresh":True,
                    "stale":False, "refreshing":False,
                    "input_fingerprint":fingerprint, "rule_fingerprint":rule_fingerprint},
        "telemetry": {"input_fingerprint":fingerprint, "rule_fingerprint":rule_fingerprint}})
    path = "/api/imports/ota/events/evt%2Fencoded?generation=12"
    status, body = dispatch(path, backend)
    assert status == 200
    assert body["event_id"] == "evt/encoded"
    assert body["generation"] == 12
    assert body["trace"]["trace_status"] == "complete"
    assert body["telemetry_sample"]["stage"] == "detail_read"
    assert body["event"]["card_candidate_count"] == 2
    assert "candidate_search" not in json.dumps(body)
    assert "PRIVATE-DIGEST" not in json.dumps(body)
    assert "PRIVATE-MAIL-BODY" not in json.dumps(body)
    assert dispatch(path, backend, user="")[0] == 403

    for query in ("", "generation=", "generation=-1", "generation=12&generation=12",
                  "generation=12&extra=x", "generation=12345678901234567"):
        result_status, result = dispatch(
            "/api/imports/ota/events/evt%2Fencoded?" + query, backend)
        assert result_status == 400 and result["code"] == "INVALID_QUERY"

    assert dispatch("/api/imports/ota/events/%ZZ?generation=12", backend)[0] == 400
    assert dispatch("/api/imports/ota/events/evt%2Fencoded?generation=13",
                    DetailBackend(error=SnapshotReadError("SNAPSHOT_CHANGED", 409)))[0] == 409
    assert dispatch("/api/imports/ota/events/missing?generation=12",
                    DetailBackend({"event": None, "generation": 12,
                                   "ambiguous": False}))[0] == 404
    ambiguous_status, ambiguous_body = dispatch(
        "/api/imports/ota/events/duplicate?generation=12",
        DetailBackend({"event": None, "generation": 12, "ambiguous": True}))
    assert ambiguous_status == 409 and ambiguous_body["code"] == "EVENT_ID_AMBIGUOUS"
    assert backend.calls == [("evt/encoded", 12)]


def test_detail_get_does_not_classify_build_index_scan_snapshot_or_load_cards():
    event = {"ota_event_id": "evt", "status": "HOLD_AMBIGUOUS"}
    fingerprint = "a" * 64
    rule_fingerprint = "b" * 64
    backend = DetailBackend({"event": event, "generation": 3, "ambiguous": False,
        "summary": {"snapshot_status":"ready", "generation":3, "fresh":True,
                    "stale":False, "refreshing":False,
                    "input_fingerprint":fingerprint, "rule_fingerprint":rule_fingerprint},
        "telemetry": {"input_fingerprint":fingerprint, "rule_fingerprint":rule_fingerprint}})
    with (mock.patch.object(ota_payment_review, "classify_event", side_effect=AssertionError),
          mock.patch.object(ota_payment_review, "summarize_queue", side_effect=AssertionError),
          mock.patch.object(ota_payment_review, "build_queue_index", side_effect=AssertionError)):
        status, body = dispatch("/api/imports/ota/events/evt?generation=3", backend)
    assert status == 200 and body["event"] == event
    assert backend.calls == [("evt", 3)]


def test_proposal_pages_are_bounded_signed_and_generation_bound():
    proposals = [{"proposal_id": f"proposal-{n:02}", "question": "Synthetic proposal",
                  "status": "pending", "conditions": {"provider": "agoda"}}
                 for n in range(43)]
    service = OtaSnapshotService(
        key_fn=lambda: "synthetic-proposal-key",
        reconcile_fn=lambda: {"public": {"events": [], "cards_by_event": {},
                                          "proposals": proposals},
                              "results": [], "links": {}, "data": {},
                              "queue_page_rows": []}, start=False)
    service.check_now()
    first = service.proposal_page_context(1, limit=20)
    second = service.proposal_page_context(1, limit=20, cursor=first["next_cursor"])
    third = service.proposal_page_context(1, limit=20, cursor=second["next_cursor"])
    assert [len(first["items"]), len(second["items"]), len(third["items"])] == [20, 20, 3]
    ids = [item["proposal_id"] for page in (first, second, third) for item in page["items"]]
    assert len(ids) == len(set(ids)) == 43
    assert "proposal-" not in first["next_cursor"]
    with pytest.raises(SnapshotReadError) as changed:
        service.proposal_page_context(2, limit=20, cursor=first["next_cursor"])
    assert (changed.value.code, changed.value.status_code) == ("SNAPSHOT_CHANGED", 409)
    with pytest.raises(SnapshotReadError) as bad:
        service.proposal_page_context(1, limit=20, cursor=first["next_cursor"][:-2] + "AA")
    assert (bad.value.code, bad.value.status_code) == ("BAD_CURSOR", 400)


def test_detail_map_is_private_and_restored_generation_waits_for_worker(tmp_path):
    persisted = tmp_path / "ota-snapshot.json"
    reconciled = {"public": {"events": [], "cards_by_event": {}, "proposals": []},
                  "results": [], "links": {}, "data": {}, "queue_page_rows": [],
                  "queue_detail_rows": {"synthetic": {"ota_event_id": "synthetic"}},
                  "queue_ambiguous_ids": []}
    service = OtaSnapshotService(key_fn=lambda: "synthetic", reconcile_fn=lambda: reconciled,
                                 persist_path=persisted, start=False)
    service.check_now()
    assert "_queue_detail_map" not in service.view()
    saved = persisted.read_text(encoding="utf-8")
    assert "_queue_detail_map" not in saved and "queue_detail_rows" not in saved
    restored = OtaSnapshotService(key_fn=lambda: "synthetic", reconcile_fn=lambda: reconciled,
                                 persist_path=persisted, start=False)
    with pytest.raises(SnapshotReadError) as not_ready:
        restored.queue_detail_context("synthetic", 1)
    assert (not_ready.value.code, not_ready.value.status_code) == ("SNAPSHOT_NOT_READY", 409)
