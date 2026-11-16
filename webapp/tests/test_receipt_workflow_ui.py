"""Synthetic contracts for the Paseo receipt UI and its backend route handoff."""

from __future__ import annotations

import sys
import types
from urllib.parse import urlsplit

from webapp import receipt_review
from webapp import receipt_workflow_ui


IMAGE_SHA = "a" * 64


def _receipt_data():
    return {
        "images": [IMAGE_SHA],
        "pdfs": [],
        "uploads": [{"kind": "image", "sha256": IMAGE_SHA, "name": "synthetic receipt.png"}],
        "candidates": [],
        "holds": [],
        "drafts": [],
    }


def test_default_workflow_shows_saved_photo_unchecked_and_keeps_manual_entry_path():
    page = receipt_review.render_html(
        _receipt_data(), "synthetic-csrf", [{"id": "trip-1", "name": "Synthetic trip"}]
    )
    panel = receipt_workflow_ui.render_panel(
        _receipt_data(), "synthetic-csrf", [{"id": "trip-1", "name": "Synthetic trip"}]
    )

    assert "synthetic receipt.png" in page
    assert f"data-rw-image value='{IMAGE_SHA}' aria-label='synthetic receipt.png 분석 대상으로 선택'" in page
    assert "checked" not in page.split("data-rw-image", 1)[1].split("</label>", 1)[0]
    assert "window.RECEIPT_WORKFLOW_CSRF=\"synthetic-csrf\"" in page
    assert 'window.RECEIPT_WORKFLOW_TRIPS=[{"id": "trip-1", "name": "Synthetic trip"}]' in page
    assert "/receipts?mode=classic" in page
    assert "저장된 분석 결과를 불러오는 중입니다." in page
    assert "분석 지시는 관리되는 기본 설정" in page
    assert "feedback" not in panel.lower()
    assert "id='classic-receipt-tools'" in page
    assert "id='receipt-table'" in page
    assert "id='other-methods'" in page
    assert "data-category" in page


def test_legacy_screen_keeps_upload_manual_input_and_draft_controls():
    page = receipt_review.render_html(_receipt_data(), "synthetic-csrf", image_sha=IMAGE_SHA,
                                      include_workflow=False)

    assert f"id='image-sha' value='{IMAGE_SHA}'" in page
    assert 'id="img-file"' in page
    assert "id='other-methods'" in page
    assert "id='r-merchant'" in page
    assert "/api/receipts/drafts" in page
    assert "receipt-workflow-panel" not in page


def test_inline_trip_data_escapes_script_terminators():
    malicious_name = "</script><script>alert(1)</script>&marker"
    panel = receipt_workflow_ui.render_panel(
        _receipt_data(), "synthetic-csrf", [{"id": "trip-1", "name": malicious_name}]
    )

    assert "window.RECEIPT_WORKFLOW_TRIPS=[{\"id\": \"trip-1\", \"name\": " in panel
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e\\u0026marker" in panel
    assert "</script><script>alert(1)</script>" not in panel
    assert "&marker" not in panel


def test_review_drafts_pin_revision_and_retry_only_after_explicit_failure_handling():
    script = receipt_workflow_ui.WORKFLOW_SCRIPT

    assert "baseRevision: candidate.revision" in script
    assert "expected_revision: draft.baseRevision" in script
    assert "draft.baseRevision = updated.revision" in script
    assert "if (allowConflict && draft.conflict)" in script
    assert "draft.baseRevision = candidate.revision" in script
    assert "let saved = false" in script
    assert "if (saved && drafts.get(candidateId) === draft" in script
    assert "else if (draft?.error)" in script
    assert "if (Object.is(currentValue, nextValue)) return;" in script


def test_job_retry_is_explicit_terminal_and_uses_retry_endpoint_with_stable_id():
    script = receipt_workflow_ui.WORKFLOW_SCRIPT

    assert "job.status === 'done' || job.status === 'failed'" in script
    assert 'data-retry-job="${escapeHtml(job.job_id)}"' in script
    assert "function retryRequestId(jobId)" in script
    assert "receipt-workflow-retry:${jobId}" in script
    assert "post('/api/receipts/workflow/retry'" in script
    assert "job_id: jobId" in script
    assert "request_id: request.request_id" in script
    assert "if (error.httpStatus === 409)" in script


def test_backend_error_codes_show_korean_guidance_and_keep_raw_code_diagnostic_only():
    script = receipt_workflow_ui.WORKFLOW_SCRIPT

    assert "function messageForCode(code, httpStatus = 0)" in script
    assert "분석 지시가 바뀌었습니다. 새 분석을 시작해 주세요." in script
    assert "이전 실행 상태를 확인하고 있어요. 중복 실행을 막기 위해 잠시 기다려 주세요." in script
    assert "Paseo 로그인이 필요합니다." in script
    assert "모델 사용 한도에 도달했습니다." in script
    assert "이 사진 형식은 선택한 모델에서 처리할 수 없습니다." in script
    assert "다른 화면에서 이 교정 내용을 바꿨습니다." in script
    assert "장부 보호 조건 때문에 반영을 중단했습니다." in script
    assert "messageForCode(code) || (serverMessage !== code ? serverMessage : '')" in script
    assert "messageForCode(normalizedCode)" in script
    assert 'title="진단 코드: ${escapeHtml(job.code)}"' in script
    assert '분석 실패${job.code}' not in script
    assert '실패 사유: ${escapeHtml(job.code)}' not in script


def test_receipt_dispatch_hands_workflow_routes_to_backend_contract(monkeypatch):
    calls = []
    backend = types.ModuleType("webapp.receipt_workflow")
    backend.owns_route = lambda path: path == "/api/receipts/workflow/review"

    def dispatch(handler, parsed, **kwargs):
        calls.append((handler, parsed.path, kwargs))
        return True

    backend.dispatch = dispatch
    monkeypatch.setitem(sys.modules, "webapp.receipt_workflow", backend)
    monkeypatch.setattr(sys.modules["webapp"], "receipt_workflow", backend, raising=False)

    class Handler:
        pass

    handler = Handler()
    raw = b'{"candidate_id":"synthetic"}'
    parsed = urlsplit("/api/receipts/workflow/review")
    assert receipt_review.dispatch(
        handler, parsed, raw=raw, csrf="csrf", board="synthetic-board", is_owner=True,
        query={"source": ["synthetic"]},
    ) is True

    assert calls == [(handler, "/api/receipts/workflow/review", {
        "raw": raw,
        "csrf": "csrf",
        "board": "synthetic-board",
        "is_owner": True,
        "query": {"source": ["synthetic"]},
    })]
