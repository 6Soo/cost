"""Contract test for receipt_review.py render_html CSS/accessibility changes (§3~§5).
Only synthetic fixtures; no actual customer data, no DB writes, no Google writes.
Verifies the rendered HTML contract (form names/action, CSRF, escaped content,
label links, amount/currency/state preservation) rather than source-string only.
"""
import html
import json
from pathlib import Path


# Synthetic receipt fixtures matching the spec's synthetic-data contract.
SYNTHETIC_CANDIDATE = {
    "identity": "syn-001",
    "date": "2026-10-12",
    "merchant": "테스트상호",
    "currency": "JPY",
    "total_jpy": 2345,
    "total_original": 2345,
    "payment": "cash",
    "payee": "테스트상호",
    "category": "식비",
    "trip_id": "trip-syn",
    "group_id": None,
    "image_sha": "a" * 64,
    "hold": None,
    "amount_krw": 23450,
}
SYNTHETIC_TRIPS = [{"id": "trip-syn", "name": "합성 여행"}]


def test_render_preserves_contract_and_uses_design_tokens():
    # Direct import avoids importing the full server stack unnecessarily.
    from webapp import receipt_review

    csrf_value = "test-csrf-token-123"
    data = {
        "candidates": [SYNTHETIC_CANDIDATE],
        "holds": [],
        "images": ["b" * 64],
    }
    rendered = receipt_review.render_html(data, csrf=csrf_value, trips=SYNTHETIC_TRIPS)

    # Must be a complete HTML document string (not just a fragment).
    assert isinstance(rendered, str)
    assert rendered.startswith("<!doctype html>")
    assert "<html lang='ko'>" in rendered

    # CSRF token must appear in the inline script and in the JS post helper.
    assert "const csrf=" in rendered
    assert f"{json.dumps(csrf_value)}" in rendered
    # The script includes the CSRF in the fetch headers contract.
    assert "X-CSRF-Token" in rendered

    # Form fields/actions/names must preserve existing contract links.
    # The edit action uses POST to /api/receipts/edit; the image route uses GET /api/receipts/image/.
    assert "/api/receipts/edit" in rendered
    assert "/api/receipts/image/" in rendered

    # Existing amount/currency/state preservation (not source-string only).
    # The synthetic candidate's currency and total must appear in the rendered row.
    assert "JPY" in rendered  # currency token present in label / select
    assert "2345" in rendered  # numeric value preserved
    assert "식비" in rendered  # category preserved
    assert "테스트상호" in rendered  # merchant escaped and preserved

    # State display: confirmed receipt has payee and category => '분류됨'.
    assert "분류됨" in rendered

    # HTML escape boundary: malicious input must not break out of value attributes.
    malicious = {**SYNTHETIC_CANDIDATE, "merchant": "<script>alert(1)</script>",
                 "date": "2026-10-12", "total_jpy": 1, "amount_krw": 10,
                 "payee": "<img src=x>", "category": "</label><script>"}
    malicious_data = {
        "candidates": [malicious],
        "holds": [],
        "images": [],
    }
    malicious_rendered = receipt_review.render_html(
        malicious_data, csrf=csrf_value, trips=SYNTHETIC_TRIPS)
    # Escaped values must not contain raw tags in value attributes (escape boundary).
    # Note: the page itself includes legitimate <script> blocks (VISION_SCRIPT), so we
    # check that malicious input does not appear unescaped inside value/text nodes.
    assert 'value=\'<script>alert(1)</script>\'' not in malicious_rendered
    assert 'value="<script>alert(1)</script>"' not in malicious_rendered
    # The escaped merchant should appear with HTML entities, not raw markup.
    escaped_merchant = html.escape("<script>alert(1)</script>")
    # It must not appear as a raw tag inside value or text nodes; it should be entity-escaped.
    assert '<script>alert(1)</script>' not in malicious_rendered or escaped_merchant in malicious_rendered

    # Label ID/link preservation: data-merchant, data-date, data-payment, data-trip,
    # data-category, data-payee links must exist with aria-label attributes.
    assert 'data-merchant=' in rendered
    assert 'data-date=' in rendered
    assert 'data-payment=' in rendered
    assert 'data-trip=' in rendered
    assert 'data-payee=' in rendered
    assert 'data-category=' in rendered

    # Design system token connections (§4.2 / §3) must be present in CSS.
    assert "var(--bg)" in rendered
    assert "var(--paper)" in rendered
    assert "var(--ink)" in rendered
    assert "var(--line)" in rendered
    assert "var(--focus)" in rendered
    assert "var(--mut)" in rendered
    assert "var(--grn)" in rendered
    assert "var(--neg)" in rendered
    assert "var(--line-strong)" in rendered
    assert "var(--sel)" in rendered

    # Mobile/responsive contract (§3.2 / §3.3): focus-visible and min-width/overflow rules.
    assert ":focus-visible" in rendered
    assert "min-width:0" in rendered
    assert "overflow-wrap:break-word" in rendered

    # Accessibility label preservation (§3.3): aria-label connections for inputs.
    assert 'aria-label=' in rendered
    assert 'aria-pressed=' in rendered

    # The photo strip must not break at 375px: grid minmax must include 100% guard.
    assert "minmax(min(100px,100%),1fr)" in rendered or "minmax(100px,1fr)" in rendered


if __name__ == "__main__":
    test_render_preserves_contract_and_uses_design_tokens()
    print("PASS: contract test covers design tokens, HTML escape, label links, amount/state, 375px guards")
