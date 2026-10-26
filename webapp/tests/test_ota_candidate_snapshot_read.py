"""Candidate GETs never reconcile original mail on the HTTP thread."""
from types import SimpleNamespace
from urllib.parse import urlsplit
import pytest
from webapp import ota_payment_review as review


def test_pending_card_candidates_use_snapshot_and_never_legacy_data():
    calls = []
    def pending():
        calls.append('snapshot')
        raise review.OtaSnapshotNotReady('refreshing')
    backend = SimpleNamespace(_action_data=pending, _data=lambda: pytest.fail('foreground mail parsing'))
    with pytest.raises(review.OtaSnapshotNotReady):
        review.CoreOtaPaymentBackend.cards_for_event(backend, 'synthetic')
    assert calls == ['snapshot']


@pytest.mark.parametrize('error', [review.OtaSnapshotNotReady('refreshing'), review.StalePreviewError()])
def test_pending_cards_route_returns_explicit_retry_without_source_details(error, monkeypatch):
    monkeypatch.setattr(review, 'enabled', lambda: True)
    replies = []
    handler = SimpleNamespace(current_user_id=lambda: 'synthetic-owner',
        _send_json=lambda payload, status=200: replies.append((status, payload)))
    def pending(_):
        raise error
    assert review.dispatch(handler, urlsplit('/api/imports/ota/cards/synthetic'),
        backend=SimpleNamespace(cards_for_event=pending), csrf='synthetic')
    status, payload = replies[0]
    assert status == 409 and payload['code'] == 'OTA_SNAPSHOT_NOT_READY'
    assert 'synthetic' not in str(payload)


def test_browser_pending_candidates_can_be_retried_without_financial_writes():
    from playwright.sync_api import sync_playwright, expect

    snapshot = {'events': [{'ota_event_id': 'synthetic', 'provider': 'Synthetic OTA',
        'booking_ref': 'SYNTHETIC', 'amount_krw': 12000, 'paid_on': '2026-10-02',
        'status': 'HOLD_AMBIGUOUS', 'card_candidate_count': 1}], 'proposals': []}
    calls = []
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.set_default_timeout(5000)
            def handle(route):
                calls.append((route.request.url, route.request.method))
                if '/cards/' not in route.request.url:
                    route.fulfill(json=snapshot)
                elif sum('/cards/' in url for url, _ in calls) == 1:
                    route.fulfill(status=409, json={'code': 'OTA_SNAPSHOT_NOT_READY',
                                                   'message': 'Synthetic pending'})
                else:
                    route.fulfill(json={'cards': [{'transaction_id': 'synthetic-card',
                        'merchant': 'Synthetic merchant', 'amount_krw': 12000}]})
            page.route('**/api/imports/ota**', handle)
            page.set_content('<base href="http://localhost/">' + review.render_import_section('synthetic'))
            toggle = page.locator('.ota-event h4[role=button]')
            toggle.press('Enter')
            expect(page.locator('.ota-cards')).to_contain_text('예약 근거 갱신 중입니다.')
            expect(page.locator('.ota-cards')).to_have_attribute('data-loading', 'false')
            expect(page.locator('[data-preview]')).to_be_disabled()
            toggle.press('Enter')
            expect(page.locator('.ota-cards input[type=radio]')).to_have_count(1)
            expect(toggle).to_have_attribute('aria-expanded', 'true')
            assert sum('/cards/' in url for url, _ in calls) == 2
            assert all(method == 'GET' for _, method in calls)
        finally:
            browser.close()
