import os
from unittest.mock import patch

from webapp import access_control, google_ledger_page
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class SiteShellBrowserTests(LinkBrowserFixture):
    def test_account_navigation_is_direct_on_native_and_wrapped_pages(self):
        # Use the actual menu renderer: a reduced fake missed the singleton
        # management disclosure after its other two destinations moved away.
        page, base = self.prepare_pages(1440)
        with patch.dict(os.environ, {'WEBLEDGER_FLIGHT_PASSENGER_MATCHING': '1'}):
            for width in (320, 390, 1440):
                for path in ('/board', '/access/admin', '/flight-passengers'):
                    with self.subTest(width=width, path=path):
                        page.set_viewport_size({'width': width, 'height': 900})
                        response = page.goto(base + path)
                        self.assertEqual(response.status, 200)
                        if width < 1024:
                            page.locator('.site-more-bottom').click()
                            account = page.locator('#site-more-dialog a[href="/access/admin"]')
                        else:
                            account = page.locator('#nav a[href="/access/admin"]')
                        self.assertEqual(account.count(), 1)
                        self.assertTrue(account.is_visible())
                        if width >= 1024:
                            self.assertEqual(account.locator('xpath=ancestor::details').count(), 0)
                            self.assertEqual(page.locator('#nav .nav-management').count(), 0)
                            self.assertEqual(page.locator('#nav a[href="/access/admin"]').count(), 1)
                        else:
                            self.assertTrue(page.locator('#site-more-dialog').get_attribute('open') is not None)
                        account.evaluate("e=>e.focus({focusVisible:true})")
                        self.assertTrue(account.evaluate('e=>e===document.activeElement'))
                        self.assertNotEqual(account.evaluate('e=>getComputedStyle(e).outlineStyle'), 'none')
                        if path == '/access/admin':
                            self.assertEqual(account.get_attribute('aria-current'), 'page')
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)

    def test_default_open_trip_overrides_remembered_closed_trip(self):
        store = self.server.card_store
        trips = [store.create_trip(
            display_key=name, destination='합성 여행', starts_on=start, ends_on=end,
            client_request_id='default-' + name)['tab_id']
            for name, start, end in [('마감 여행', '2026-07-01', '2026-07-03'),
                                     ('첫 미마감 여행', '2026-07-04', '2026-07-06'),
                                     ('다음 여행', '2026-07-07', '2026-07-09')]]
        store.save_trip_visual_close(tab_id=trips[0], expected_closed=False,
                                     closed=True, client_request_id='close-first')
        page, base = self.prepare_pages(1440)
        page.goto(base + '/board?tab=' + trips[0])
        self.assertIsNone(page.evaluate("sessionStorage.getItem('cost-nav-trip')"))
        page.goto(base + '/board')
        self.assertIn('첫 미마감 여행', page.locator('h1').inner_text())
        self.assertEqual(page.locator('#nav a[href="/trips"][aria-current=page]').count(), 1)
        self.assertIsNone(page.evaluate("sessionStorage.getItem('cost-nav-trip')"))
        self.assertIsNone(page.evaluate("sessionStorage.getItem('cost-workflow-return')"))
        page.goto(base + '/board?tab=' + trips[2])
        self.assertIn('다음 여행', page.locator('h1').inner_text())
        self.assertEqual(page.locator('#nav a[href="/trips"][aria-current=page]').count(), 1)

    def test_theme_keyboard_motion_and_responsive_contract(self):
        page, base = self.prepare_pages(1440)
        for width in (320, 375, 390, 760, 1024, 1440):
            with self.subTest(width=width):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base + '/board')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                if width < 1024:
                    page.locator('.site-more-bottom').click()
                toggle = page.locator('#site-theme-toggle')
                self.assertEqual(toggle.count(), 1)
                before = page.locator('html').get_attribute('data-theme')
                toggle.focus()
                page.keyboard.press('Enter')
                after = page.locator('html').get_attribute('data-theme')
                self.assertNotEqual(before, after)
                self.assertEqual(toggle.get_attribute('aria-label'),
                                 '밝은 화면으로 전환' if after == 'dark' else '어두운 화면으로 전환')
                self.assertEqual(page.evaluate('''() => {
                  const t=document.querySelector('#site-theme-toggle').getBoundingClientRect();
                  return t.width >= 44 && t.height >= 44;
                }'''), True)
                if width == 375:
                    page.evaluate("""() => {
                      const p=document.createElement('p');p.id='ui-loading-probe';
                      p.className='ui-state ui-state--loading';p.setAttribute('aria-busy','true');
                      p.textContent='합성 로딩';document.body.append(p);
                    }""")
                    self.assertEqual(page.locator('#ui-loading-probe').evaluate(
                        "el => getComputedStyle(el,'::before').animationDuration"), '0.8s')
                    page.evaluate("document.documentElement.style.zoom='200%'")
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)
                    page.evaluate("document.documentElement.style.zoom='100%'")

    def test_theme_override_and_reduced_motion(self):
        page, base = self.prepare_pages(390)
        page.emulate_media(color_scheme='dark', reduced_motion='reduce')
        page.goto(base + '/board')
        self.assertEqual(page.locator('html').get_attribute('data-theme'), 'dark')
        self.assertEqual(page.evaluate('''() => {
          const p=document.createElement('p');p.className='ui-state ui-state--loading';
          p.setAttribute('aria-busy','true');document.body.append(p);
          return getComputedStyle(p,'::before').animationDuration;
        }'''), '0s')
        page.locator('.site-more-bottom').click()
        page.locator('#site-theme-toggle').click()
        self.assertEqual(page.locator('html').get_attribute('data-theme'), 'light')
        page.reload()
        self.assertEqual(page.locator('html').get_attribute('data-theme'), 'light')

    def test_refund_empty_state_uses_shared_tokens_in_both_themes(self):
        page, base = self.prepare_pages(375)
        page.emulate_media(color_scheme='light')
        response = page.goto(base + '/board?tab=refunds')
        self.assertEqual(response.status, 200)
        empty = page.locator('.empty-state')
        self.assertEqual(empty.count(), 1)
        self.assertIn('환불·취소 거래가 없습니다.', empty.inner_text())
        light = empty.evaluate('''el => ({background:getComputedStyle(el).backgroundColor,
          token:getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()})''')
        self.assertEqual(light['background'], 'rgb(255, 255, 255)')
        page.evaluate("localStorage.removeItem('cost-theme')")
        page.emulate_media(color_scheme='dark')
        page.reload()
        dark = page.locator('.empty-state').evaluate('''el => ({
          background:getComputedStyle(el).backgroundColor,
          token:getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()})''')
        self.assertEqual(dark['background'], 'rgb(30, 41, 59)')
        self.assertEqual(dark['token'], '#1E293B')

    def test_sidebar_appearance_stays_the_same_between_ledger_and_cards(self):
        for width in (390, 1440):
            with self.subTest(width=width):
                page, base = self.prepare_pages(width)
                appearances = []
                for path in ('/board', '/cards/all'):
                    page.goto(base + path)
                    appearances.append(page.evaluate('''() => {
                      const selectors=['#nav','#nav .brand','#nav .brand small','#nav .nav-q input',
                        '#nav .work-menu','#nav .work-action[href="/receipts"]','#nav .work-action small',
                        '#nav .site-links a:not([aria-current=page])','#nav .nav-sec','#nav .nv','#nav .nav-ft'];
                      const props=['fontFamily','fontSize','lineHeight','width','padding','marginTop','marginBottom',
                        'backgroundColor','borderRadius','borderTopWidth','display','minHeight'];
                      return selectors.map(selector=>{const el=document.querySelector(selector);
                        if(!el)return null;const css=getComputedStyle(el);
                        return Object.fromEntries(props.map(p=>[p,css[p]]));});
                    }'''))
                for actual in appearances[1:]:
                    differences = [(i, {key: (expected[key], got[key]) for key in expected if expected[key] != got[key]})
                                   for i, (expected, got) in enumerate(zip(appearances[0], actual)) if expected != got]
                    self.assertEqual(differences, [])

    def prepare_pages(self, width):
        env = patch.dict(os.environ, {
            'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_RECEIPTS_STORE': str(self.tmp / 'receipts.json'),
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.tmp / 'google.json'),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(self.tmp / 'rows.json'),
        })
        env.start()
        self.addCleanup(env.stop)
        fake = patch.object(google_ledger_page.google_authority, 'load_consistent',
                            return_value=(healthy_snapshot(), rows_doc()['sources']))
        fake.start()
        self.addCleanup(fake.stop)
        context = self.browser.new_context(viewport={'width': width, 'height': 900})
        self.addCleanup(context.close)
        context.set_extra_http_headers({access_control.SyntheticSessionAdapter.HEADER: OWNER})
        return context.new_page(), f'http://127.0.0.1:{self.port}'

    def test_same_sidebar_on_all_work_screens_at_desktop(self):
        page, base = self.prepare_pages(1440)
        menu = None
        # The transient upload shell shares primary navigation but omits the
        # live trip rail while the card writer is busy.
        for path in ('/', '/board', '/import', '/cards', '/cards/all?panel=upload', '/receipts', '/reserve-links', '/trips', '/access/admin'):
            with self.subTest(path=path):
                response = page.goto(base + path)
                self.assertEqual(response.status, 200, f"{path} returned HTTP {response.status}")
                self.assertEqual(page.locator('#nav').count(), 1)
                links = page.locator('#nav .site-links a[href]').evaluate_all(
                    '(items)=>items.map(a=>a.getAttribute("href"))')
                if menu is None:
                    menu = links
                self.assertEqual(links, menu)
                self.assertEqual(page.locator('#nav a[href="/cards/all"]').count(), 1)
                self.assertEqual(page.locator('#nav a[href="/import"]').count(), 0)
                if path == '/cards/all?panel=upload':
                    self.assertEqual(page.evaluate("sessionStorage.getItem('cost-view:/cards/all')"), None)
                    self.assertIn('진행 중 여행', page.locator('#live-nav').inner_text())
                self.assertEqual(page.locator('#nav').bounding_box()['x'], 0)
                main = page.locator('#site-content') if page.locator('#site-content').count() else page.locator('#main')
                self.assertGreaterEqual(main.bounding_box()['x'], 232)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 1440)

    def test_brand_link_navigates_home_and_home_navigation_remains_available(self):
        page, base = self.prepare_pages(1440)
        page.goto(base + '/board')
        brand = page.locator('#nav a.brand[href="/"]')
        self.assertEqual(brand.count(), 1)
        self.assertIn('숲길여행 회계', brand.first.inner_text())
        self.assertEqual(page.locator('#nav .site-links a[href="/"]').count(), 1)
        brand.first.click()
        page.wait_for_url(base + '/')
        self.assertEqual(page.url, base + '/')
        page.goto(base + '/board')
        brand = page.locator('#nav a.brand[href="/"]')
        brand.first.focus()
        self.assertEqual(page.evaluate('document.activeElement.textContent'), '숲길여행 회계')
        page.keyboard.press('Enter')
        page.wait_for_url(base + '/')
        self.assertEqual(page.url, base + '/')
        mobile, mobile_base = self.prepare_pages(390)
        mobile.goto(mobile_base + '/cards')
        mobile_brand = mobile.locator('.site-topbar a.site-brand-mobile[href="/"]')
        self.assertEqual(mobile_brand.count(), 1)
        self.assertTrue(mobile_brand.first.is_visible())
        self.assertGreaterEqual(mobile_brand.first.bounding_box()['height'], 44)
        mobile_brand.first.click()
        mobile.wait_for_url(mobile_base + '/')
        self.assertEqual(mobile.url, mobile_base + '/')

    def test_mobile_menu_navigation_and_input_are_usable(self):
        page, base = self.prepare_pages(390)
        page.goto(base + '/cards')
        page.locator('.site-more-bottom').click()
        self.assertTrue(page.locator('#site-more-dialog').get_attribute('open') is not None)
        page.locator('#site-more-dialog a[href="/access/admin"]').focus()
        page.keyboard.press('Escape')
        self.assertIsNone(page.locator('#site-more-dialog').get_attribute('open'))
        page.locator('.site-bottom-nav a[href="/cards/all"]').click()
        self.assertEqual(page.url, base + '/cards/all')
        self.assertEqual(page.locator('#nav').count(), 1)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        self.assertEqual(page.locator('.site-bottom-nav a[href="/cards/all"]').get_attribute('aria-current'), 'page')
        page.goto(base + '/board')
        page.locator('.site-more-bottom').click()
        self.assertTrue(page.locator('#site-more-dialog').get_attribute('open') is not None)
        page.keyboard.press('Escape')
        self.assertIsNone(page.locator('#site-more-dialog').get_attribute('open'))
