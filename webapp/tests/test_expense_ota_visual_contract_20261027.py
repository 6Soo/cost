"""Synthetic structural regression for expense/OTA visual consistency (no live data)."""
from webapp import ota_payment_review
from webapp import card_flow


def test_ota_owner_review_uses_semantic_tokens_and_collapsible_evidence():
    doc = ota_payment_review.render_import_section('synthetic-token')
    assert 'id="ota-review"' in doc
    assert 'class="ota-more"' in doc
    assert '예약·결제 근거 자세히 보기' in doc
    assert 'var(--shell-paper' in doc
    assert 'var(--shell-ink' in doc
    assert 'var(--shell-line' in doc
    assert 'var(--shell-accent' in doc
    assert '@media(width < 760px)' in doc
    assert '#ota-review .ota-event .ota-overview' in doc
    assert '#ota-review button:focus-visible' in doc
    assert '금융 상태 보기' in doc
    assert 'data-preview=' in doc  # Existing guarded actions stay wired.


def test_kakao_merchant_key_is_read_only_review_classification():
    assert card_flow._refund_merchant_key("카카오T가승인_유페이") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오T일반택시(법인)_0") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오모빌리티 택시요금") == "카카오택시"
    assert card_flow._refund_merchant_key("카카오T대리") != "카카오택시"
    assert card_flow._refund_merchant_key("카카오페이") != "카카오택시"


def test_expense_cleanup_styles_keep_collapsed_refund_drilldown():
    import inspect
    from webapp import card_cleanup_ui, card_evidence_ui, expense_workspace
    src = ''.join(inspect.getsource(module) for module in
                  (card_flow, card_cleanup_ui, card_evidence_ui, expense_workspace))
    assert "cleanup-merchant-compare" in src
    assert "cleanup-kakao-inventory" in src
    assert "cleanup-compare-row" in src
    assert "원결제·취소 근거 자세히 보기" in src
    assert "task_label = '정리할 지출' if page_title == '지출 정리' else '카드 거래'" in src
    assert "('cleanup', 'expense-overview', 'list', task_label)" in src


def test_browser_ota_theme_fold_keyboard_and_guarded_preview(monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    from webapp import site_shell
    monkeypatch.setattr('webapp.ledger_design._nav_html', lambda *_: '<aside id="nav"></aside>')
    snapshot = {'events': [{'ota_event_id': 'synthetic-event', 'provider': 'Synthetic OTA',
                 'booking_ref': 'SYNTHETIC-BOOKING', 'amount': 12000, 'amount_krw': 12000,
                 'currency': 'KRW', 'paid_on': '2026-10-02', 'status': 'HOLD_AMBIGUOUS',
                 'card_candidate_count': 1}], 'proposals': []}
    document = site_shell.wrap_document('<!doctype html><html><head><meta charset="utf-8"><title>Synthetic</title>'
        '<style>*{box-sizing:border-box}</style></head><body>' +
        ota_payment_review.render_import_section('synthetic-token') + '</body></html>', '/import')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            screen = browser.new_page(viewport={'width': 375, 'height': 812})
            screen.set_default_timeout(5000)
            calls = []
            def handle(route):
                url, method = route.request.url, route.request.method
                calls.append((url, method, route.request.headers))
                if '/cards/' in url:
                    route.fulfill(json={'cards': [{'transaction_id': 'synthetic-card', 'issuer': 'Synthetic',
                        'merchant': 'Synthetic merchant', 'amount_krw': 12000,
                        'approval_date': '2026-10-02'}]})
                elif url.endswith('/preview'):
                    route.fulfill(json={'difference_krw': 0, 'event_amount_krw': 12000,
                                        'card_amount_krw': 12000, 'preview_digest': 'synthetic'})
                else:
                    route.fulfill(json=snapshot)
            screen.route('http://localhost/import', lambda route: route.fulfill(body=document, content_type='text/html'))
            screen.route('**/api/imports/ota**', handle)
            screen.goto('http://localhost/import')
            event = screen.locator('.ota-event')
            expect(event).to_have_count(1)
            assert not event.locator('.ota-more').evaluate('(e)=>e.open')
            assert event.locator('[data-preview]').is_disabled()
            event.locator('.ota-more summary').click()
            expect(event.locator('.ota-facts')).to_be_visible()
            toggle = event.locator('h4[role=button]')
            toggle.focus()
            toggle.press('Enter')
            expect(event.locator('input[type=radio]')).to_have_count(1)
            expect(toggle).to_have_attribute('aria-expanded', 'true')
            event.locator('input[type=radio]').check()
            event.locator('[data-preview]').click()
            expect(event.locator('#ota-confirm')).to_be_visible()
            assert [m for u, m, h in calls if u.endswith('/preview')] == ['POST']
            assert next(h for u, m, h in calls if u.endswith('/preview'))['x-csrf-token'] == 'synthetic-token'
            assert not any(u.endswith('/confirm') for u, m, h in calls)
            event.locator('[data-none]').click()
            expect(event.locator('[data-preview]')).to_be_disabled()
            expect(event.locator('#ota-confirm')).to_have_count(0)
            for width in (375, 390, 759, 760, 1280):
                screen.set_viewport_size({'width': width, 'height': 812})
                assert screen.evaluate('document.documentElement.scrollWidth<=innerWidth')
            for scheme, expected in [('dark', 'rgb(30, 41, 59)'), ('light', 'rgb(255, 255, 255)')]:
                screen.emulate_media(color_scheme=scheme)
                expect(screen.locator('#ota-review')).to_have_css('background-color', expected)
                expect(screen.locator('#site-theme-toggle')).to_have_attribute('aria-label', '라이트모드로 전환' if scheme == 'dark' else '다크모드로 전환')
                screen.get_by_role('button', name='라이트모드로 전환' if scheme == 'dark' else '다크모드로 전환').click()
                expect(screen.locator('#ota-review')).to_have_css('background-color', 'rgb(255, 255, 255)' if scheme == 'dark' else 'rgb(30, 41, 59)')
                screen.get_by_role('button', name='다크모드로 전환' if scheme == 'dark' else '라이트모드로 전환').click()
                screen.evaluate("localStorage.removeItem('cost-theme')")
                screen.reload()
                expect(screen.locator('.ota-event')).to_have_count(1)
            screen.set_viewport_size({'width': 760, 'height': 812})
            screen.evaluate("document.documentElement.style.zoom='200%'")
            # CSS zoom stresses this component; it is not actual browser 200% acceptance.
            assert screen.locator('#ota-review').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        finally:
            browser.close()
