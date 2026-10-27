from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ota_catalog, site_shell


def test_ota_reason_panel_contrast_follows_manual_theme_and_system():
    data = dict(rows=[], all_count=3, unassigned_count=1, excluded_count=2,
                total=3, page=1, pages=1, months=[], providers=[], warnings=[],
                reasons=[dict(label='이용기간이 수집되지 않음', count=1)],
                trip_problems=[dict(name='합성 여행', reason='일정 원본 미확인')], trip_count=1)
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        document = site_shell.wrap_document(ota_catalog.render_html(data, {}), '/ota')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(color_scheme='dark', viewport=dict(width=390, height=900))
        context.route('http://ota.test/**', lambda route: route.fulfill(body=document, content_type='text/html'))
        page = context.new_page()
        page.goto('http://ota.test/')
        for theme in ('dark', 'light', 'dark'):
            assert page.locator('html').get_attribute('data-theme') == theme
            for selector in ('.trip-check h2', '.trip-check td', '.trip-check .small', '.trip-check li'):
                colors = page.locator(selector).first.evaluate('''el=>{
                    const rgb=c=>c.match(/[\\d.]+/g).slice(0,3).map(Number);
                    const lum=c=>rgb(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4})
                      .reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
                    let bg=el;while(getComputedStyle(bg).backgroundColor==='rgba(0, 0, 0, 0)')bg=bg.parentElement;
                    const a=lum(getComputedStyle(el).color),b=lum(getComputedStyle(bg).backgroundColor);
                    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                }''')
                assert colors >= 4.5, (theme, selector, colors)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('#site-theme-toggle').click()
        browser.close()
