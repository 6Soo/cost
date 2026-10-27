from webapp import ledger_design, google_ledger_page


def test_net_income_label_explains_calculation_and_preserves_values():
    incomes = [{'amount_krw': 10000}]
    expenses = [{'amount_krw': 3000}]
    markup = ledger_design._summary_html(incomes, expenses)
    assert '총수입' in markup and '총수입 − 지출' in markup
    assert '10,000원' in markup and '3,000원' in markup and '7,000원' in markup
    assert '차액' not in markup and '수입, 총수입에서 지출을 뺀 금액' in markup
    filtered = ledger_design._summary_html(incomes, expenses, filtered=(2000, 500, 1, 1), whole=(10000, 3000, 2, 3))
    assert '전체 총수입' in filtered and '검색 결과 총수입' in filtered
    assert '검색 결과 수입' in filtered and '1,500원' in filtered
    unverified = ledger_design._summary_html([], expenses, recorded_income_count=0,
        google_income={'show_rows': False, 'verified': False})
    assert 'net-income' not in unverified and '확인 필요' in unverified


def test_expense_table_keeps_full_service_dates_in_a_dedicated_wrapping_column(monkeypatch):
    monkeypatch.setattr(ledger_design.board, 'current_role', lambda: 'owner')
    row = {'row_id': 'synthetic-expense', 'row_kind': 'expense', 'source_kind': 'manual',
           'amount_krw': 12345, 'item': '숙박비', 'description': '합성 숙소 ' * 30,
           'occurred_on': '2026-06-30', 'service_period': '2026-06-30~2026-07-01'}
    # Verify the actual table markup, including the source period text.
    markup = ledger_design._tables_html([], [row], selected='', unclassified=False)
    assert "width:280px" in markup and "width:28%" in markup
    assert "class='c-stay'" in markup
    assert '6월 30일(화) ~ 7월 1일(수)' in markup
    assert 'text-overflow:clip' in ledger_design.STYLE


def test_browser_expense_table_keeps_long_party_and_service_dates_reachable(monkeypatch):
    from playwright.sync_api import sync_playwright
    from webapp import site_shell

    monkeypatch.setattr(ledger_design.board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(ledger_design, '_nav_html', lambda *args, **kwargs: '')
    merchant = '합성 숙박 가맹점 ' * 18
    row = {'row_id': 'synthetic-long-expense', 'row_kind': 'expense', 'source_kind': 'manual',
           'amount_krw': 12345, 'item': '숙박비', 'description': merchant,
           'source_merchant': merchant, 'occurred_on': '2026-06-30',
           'service_period': '2026-06-30~2026-07-01'}
    markup = ledger_design.render(
        ledger_design._tables_html([], [row], selected='', unclassified=False)
        + ledger_design._mobile_html([], [row], selected='', unclassified=False))
    markup = site_shell.wrap_document(markup, '/board?tab=synthetic-trip')

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.set_content(markup)

            def choose_theme(theme):
                if page.locator('html').get_attribute('data-theme') != theme:
                    page.locator('#site-theme-toggle').click()
                assert page.locator('html').get_attribute('data-theme') == theme

            for width in (375, 1280):
                page.set_viewport_size({'width': width, 'height': 812})
                for theme in ('dark', 'light'):
                    choose_theme(theme)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    if width == 375:
                        date = page.locator('.li .d')
                        merchant_text = page.locator('.li .mobile-party .t')
                        assert date.is_visible() and date.inner_text() == '2026-06-30'
                        assert merchant_text.is_visible()
                        assert ' '.join(merchant.split()) in ' '.join(merchant_text.inner_text().split())
                        date_box, merchant_box = date.bounding_box(), merchant_text.bounding_box()
                        assert 0 <= date_box['x'] < width and date_box['x'] + date_box['width'] <= width
                        assert date_box['y'] + date_box['height'] <= merchant_box['y']
                        assert merchant_box['x'] >= 0 and merchant_box['x'] + merchant_box['width'] <= width
                        assert merchant_text.evaluate('(el) => getComputedStyle(el).whiteSpace') == 'normal'
                    else:
                        date_cell = page.locator('.c-date')
                        stay_cell = page.locator('.c-stay')
                        amount_cell = page.locator('.c-amt')
                        assert date_cell.is_visible() and date_cell.inner_text() == '2026-06-30'
                        assert stay_cell.is_visible() and '6월 30일(화)' in stay_cell.inner_text()
                        assert '7월 1일(수)' in stay_cell.inner_text()
                        date_box = date_cell.bounding_box()
                        stay_box, amount_box = stay_cell.bounding_box(), amount_cell.bounding_box()
                        assert date_box['width'] > 0 and date_box['height'] > 0
                        assert stay_box['x'] + stay_box['width'] <= amount_box['x'] + 1
                        text_rects = stay_cell.evaluate("""el => {
                          const range=document.createRange(); range.selectNodeContents(el);
                          return [...range.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}));
                        }""")
                        assert text_rects and all(r['right'] <= stay_box['x'] + stay_box['width'] + 1
                                                  and r['left'] >= stay_box['x'] - 1 for r in text_rects)
                        merchant_node = page.locator('.c-party .s-main')
                        assert ' '.join(merchant.split()) in ' '.join(merchant_node.inner_text().split())
            page.set_viewport_size({'width': 375, 'height': 812})
            page.evaluate('document.documentElement.style.zoom="200%"')
            for theme in ('dark', 'light'):
                choose_theme(theme)
                date = page.locator('.li .d')
                merchant_text = page.locator('.li .mobile-party .t')
                assert date.is_visible() and date.inner_text() == '2026-06-30'
                assert merchant_text.is_visible()
                assert ' '.join(merchant.split()) in ' '.join(merchant_text.inner_text().split())
                date_box, merchant_box = date.bounding_box(), merchant_text.bounding_box()
                assert date_box['y'] + date_box['height'] <= merchant_box['y']
                assert merchant_box['x'] + merchant_box['width'] <= page.evaluate('innerWidth')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
