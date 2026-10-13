"""HTTP-level proof for Muse read-only extraction and optional ticket grouping."""
from unittest.mock import patch
import time
import pytest

from webapp.tests.test_receipt_review import ReceiptReviewTests, PNG
from webapp import receipt_review


@pytest.fixture
def case():
    server = ReceiptReviewTests()
    server.setUp()
    try:
        yield server
    finally:
        server.tearDown()


def _same_ticket(box):
    return {"box": box, "merchant": "합성 승선권", "date": "2026-09-20",
            "currency": "JPY", "total": 820, "payment": "cash", "confidence": 1}


def test_vision_is_owner_scoped_read_only_and_muse_unavailable_defaults_closed(case):
    image = case.request("/api/receipts/image", raw=PNG, token=case.csrf())[1]["sha256"]
    status, denied = case.request("/api/receipts/vision", {"image": image}, token=case.csrf())
    assert status == 501 and denied["code"] == "VISION_DISABLED"
    response = {"receipts": [{"id": "example", "box": [.1,.1,.5,.5], "amount": 820,
                 "merchant": "합성 승선권", "date": "2026-09-20", "currency": "JPY",
                 "payment": None, "category_hint": "교통비", "note": None,
                 "requires_review": True}], "confirmed": False}
    from webapp import receipt_vision_jobs
    with receipt_vision_jobs._LOCK:
        receipt_vision_jobs._JOBS.clear()
        receipt_vision_jobs._BY_IMAGE.clear()
    with patch("webapp.receipt_review.opencode_receipt_vision.enabled", return_value=True), \
         patch("webapp.receipt_review.opencode_receipt_vision.recognize", return_value=response) as model:
        status, started = case.request("/api/receipts/vision", {"image": image}, token=case.csrf())
        assert status == 202 and started["job_id"]
        data = None
        for _ in range(300):
            status, state = case.request("/api/receipts/vision/" + started["job_id"], token=case.csrf())
            assert status == 200
            if state["status"] == "done":
                data = state["result"]
                break
            time.sleep(0.02)
        assert data is not None and data["confirmed"] is False
        assert len(data["receipts"]) == 1
        assert len(case.request("/api/receipts")[1]["candidates"]) == 0
        model.assert_called_once()


def test_same_page_identical_tickets_can_be_separate_then_user_grouped(case):
    sha = case.request("/api/receipts/image", raw=PNG, token=case.csrf())[1]["sha256"]
    body = {"image": sha, "trip_id": case.trip,
            "regions": [_same_ticket([.1,.1,.3,.3]), _same_ticket([.5,.1,.7,.3])]}
    status, result = case.request("/api/receipts/scan", body, token=case.csrf())
    assert status == 200 and result["added"] == 2
    candidates = case.request("/api/receipts")[1]["candidates"]
    assert len(candidates) == 2
    assert all(c["trip_id"] == case.trip for c in candidates)
    for candidate in candidates:
        status, _ = case.request("/api/receipts/confirm", {
            "identity": candidate["identity"],
            "expected_version": receipt_review.candidate_version(candidate),
            "payee": candidate["merchant"], "category": "교통비"}, token=case.csrf())
        assert status == 200
    candidates = case.request("/api/receipts")[1]["candidates"]
    assert case.request("/api/receipts/tsv?trip=" + case.trip)[1]["row_count"] == 2
    selection = {
        "trip_id": case.trip,
        "identities": [c["identity"] for c in candidates],
        "expected_versions": {c["identity"]: receipt_review.candidate_version(c) for c in candidates}
    }
    status, group = case.request("/api/receipts/group", selection, token=case.csrf())
    assert status == 200 and group["members"] == 2 and group["amount_krw"] == 16400
    stored = case.request("/api/receipts")[1]["candidates"]
    assert all(c["group_id"] == group["group_id"] for c in stored)
    assert case.request("/api/receipts/tsv?trip=" + case.trip)[1]["row_count"] == 1
    status, ungroup = case.request("/api/receipts/ungroup", {
        "group_id": group["group_id"]}, token=case.csrf())
    assert status == 200 and ungroup["ungrouped"] == 2
    assert case.request("/api/receipts/tsv?trip=" + case.trip)[1]["row_count"] == 2


def test_invalid_trip_cannot_be_auto_assigned(case):
    sha = case.request("/api/receipts/image", raw=PNG, token=case.csrf())[1]["sha256"]
    status, rejected = case.request("/api/receipts/scan", {
        "image": sha, "trip_id": "not-a-trip", "regions": [_same_ticket([.1,.1,.3,.3])]
    }, token=case.csrf())
    assert status == 400 and rejected["code"] == "TRIP_UNKNOWN"
    assert case.request("/api/receipts")[1]["candidates"] == []
