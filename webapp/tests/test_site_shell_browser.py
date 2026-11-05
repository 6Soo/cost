import os
from unittest.mock import patch

from webapp import access_control, google_ledger_page
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc
from webapp.tests.test_reserve_link import OWNER
from webapp.tests.test_reserve_link_browser import LinkBrowserFixture


class SiteShellBrowserTests(LinkBrowserFixture):
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
        self.assertEqual(page.evaluate("sessionStorage.getItem('cost-nav-trip')"), trips[0])
        page.goto(base + '/board')
        self.assertIn('첫 미마감 여행', page.locator('h1').inner_text())
        self.assertEqual(page.locator('#trips a.sel').count(), 1)
        self.assertIn('tab=' + trips[1], page.locator('#trips a.sel').get_attribute('href'))
        self.assertEqual(page.evaluate("sessionStorage.getItem('cost-nav-trip')"), trips[1])
        self.assertIn('tab=' + trips[1], page.evaluate("sessionStorage.getItem('cost-workflow-return')"))
        page.goto(base + '/board?tab=' + trips[2])
        self.assertIn('다음 여행', page.locator('h1').inner_text())
        self.assertIn('tab=' + trips[2], page.locator('#trips a.sel').get_attribute('href'))

    def test_theme_keyboard_motion_and_responsive_contract(self):
        page, base = self.prepare_pages(1440)
        for width in (320, 375, 390, 760, 1024, 1440):
            with self.subTest(width=width):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base + '/board')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                toggle = page.locator('#site-theme-toggle')
                self.assertEqual(toggle.count(), 1)
                before = page.locator('html').get_attribute('data-theme')
                toggle.focus()
                page.keyboard.press('Enter')
                after = page.locator('html').get_attribute('data-theme')
                self.assertNotEqual(before, after)
                self.assertEqual(toggle.get_attribute('aria-label'),
                                 '라이트모드로 전환' if after == 'dark' else '다크모드로 전환')
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
        page.locator('#site-theme-toggle').click()
        self.assertEqual(page.locator('html').get_attribute('data-theme'), 'light')
        page.reload()
        self.assertEqual(page.locator('html').get_attribute('data-theme'), 'light')

    def test_refund_empty_state_uses_shared_tokens_in_both_themes(self):
        page, base = self.prepare_pages(375)
        page.emulate_media(color_scheme='light')
        response = page.goto(base + '/board?tab=refunds')
        self.assertEqual(response.status, 200)
        empty = page.locator('#live-rows .ui-state')
        self.assertEqual(empty.count(), 1)
        self.assertEqual(empty.inner_text(), '환불 쌍이 없습니다.')
        light = empty.evaluate('''el => ({background:getComputedStyle(el).backgroundColor,
          token:getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()})''')
        self.assertEqual(light['background'], 'rgb(255, 255, 255)')
        page.evaluate("localStorage.removeItem('cost-theme')")
        page.emulate_media(color_scheme='dark')
        page.reload()
        dark = page.locator('#live-rows .ui-state').evaluate('''el => ({
          background:getComputedStyle(el).backgroundColor,
          token:getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()})''')
        self.assertEqual(dark['background'], 'rgb(30, 41, 59)')
        self.assertEqual(dark['token'], '#1E293B')

    def test_sidebar_appearance_stays_the_same_between_ledger_and_cards(self):
        for width in (390, 1440):
            with self.subTest(width=width):
                page, base = self.prepare_pages(width)
                appearances = []
                for path in ('/board', '/cards', '/import'):
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
        # The Google ledger route was deliberately removed; exercise live destinations only.
        for path in ('/', '/board', '/import', '/cards', '/receipts', '/reserve-links', '/trips', '/access/admin'):
            with self.subTest(path=path):
                response = page.goto(base + path)
                self.assertEqual(response.status, 200, f"{path} returned HTTP {response.status}")
                self.assertEqual(page.locator('#nav').count(), 1)
                links = page.locator('#nav a[href]').evaluate_all('(items)=>items.map(a=>a.getAttribute("href"))')
                if menu is None:
                    menu = links
                self.assertEqual(links, menu)
                self.assertEqual(page.locator('#nav').bounding_box()['x'], 0)
                main = page.locator('#site-content') if page.locator('#site-content').count() else page.locator('#main')
                self.assertGreaterEqual(main.bounding_box()['x'], 232)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 1440)

    def test_brand_link_navigates_home_and_no_standalone_home_link(self):
        page, base = self.prepare_pages(1440)
        page.goto(base + '/board')
        brand = page.locator('#nav a.brand[href="/"]')
        self.assertEqual(brand.count(), 1)
        self.assertIn('숲길여행 회계', brand.first.inner_text())
        self.assertEqual(page.locator('#nav .site-links a[href="/"]').count(), 0)
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
        mobile.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertIn('open', mobile.locator('#nav').get_attribute('class'))
        mobile_brand = mobile.locator('#nav a.brand[href="/"]')
        self.assertEqual(mobile_brand.count(), 1)
        self.assertTrue(mobile_brand.first.is_visible())
        self.assertGreaterEqual(mobile_brand.first.bounding_box()['height'], 44)
        self.assertEqual(mobile.locator('#nav .site-links a[href="/"]').count(), 0)
        mobile_brand.first.click()
        mobile.wait_for_url(mobile_base + '/')
        self.assertEqual(mobile.url, mobile_base + '/')

    def test_mobile_menu_navigation_and_input_are_usable(self):
        page, base = self.prepare_pages(390)
        page.goto(base + '/cards')
        page.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertIn('open', page.locator('#nav').get_attribute('class'))
        page.get_by_label('여행 검색').fill('Synthetic draft')
        page.keyboard.press('Escape')
        self.assertNotIn('open', page.locator('#nav').get_attribute('class'))
        page.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertEqual(page.get_by_label('여행 검색').input_value(), 'Synthetic draft')
        page.locator('#nav a[href="/import"]').first.click()
        self.assertEqual(page.url, base + '/import')
        self.assertEqual(page.locator('#nav').count(), 1)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.get_by_role('button', name='전체 메뉴 열기').click()
        page.locator('#nav a[href="/cards/all"]').click()
        self.assertEqual(page.url, base + '/cards/all')
        self.assertEqual(page.locator('#nav a[href="/cards/all"]').get_attribute('aria-current'), 'page')
        page.goto(base + '/board')
        page.get_by_role('button', name='전체 메뉴 열기').click()
        self.assertIn('open', page.locator('#nav').get_attribute('class'))
        page.keyboard.press('Escape')
        self.assertNotIn('open', page.locator('#nav').get_attribute('class'))
