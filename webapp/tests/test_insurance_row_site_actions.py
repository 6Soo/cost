"""The shared action decorator must preserve compact insurance disclosures."""
from unittest.mock import patch
import re
from playwright.sync_api import sync_playwright
from webapp import participant_trip_panel as panel, ledger_design_assets, site_shell
from webapp.tests.test_participant_trip_panel import sample_state


def regression_document():
    state=sample_state(1)
    state['participants']=[{'participant_id':'person-0','display_name':'합*성',
        'links':[{'income_ref':state['income_rows'][0]['ref'],'method':'manual'}]}]
    markup=panel.render(state)
    linked=re.search(r"<template class='participant-income-status'[^>]*>(.*?)</template>",markup,re.S)[1]
    row=lambda key,cell: f"<tr id='{key}'><td>합성</td><td class='income-total'>1,000원</td><td class='participant-insurance-cell'>{cell}</td></tr>"
    body=("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>"+ledger_design_assets.STYLE+
        "</style></head><body><main id='main'><section id='google-trip-income'><table id='income-tbl'><tbody>"+
        row('linked',linked)+row('unlinked','미연결')+row('refunded','환불완료')+row('candidate',"<div class='participant-cell-content'><button class='insurance-review-status insurance-candidate-button'>보험 명단 후보 1건</button></div>")+row('async','미연결')+
        "</tbody></table></section><template id='linked-template'>"+linked+"</template></main></body></html>")
    with patch('webapp.ledger_design._nav_html',return_value='<aside id="nav"></aside>'):
        return site_shell.wrap_document(body,'/board')


def test_closed_and_async_insurance_rows_keep_same_height_and_keyboard_disclosure():
    with sync_playwright() as api:
        browser=api.chromium.launch()
        try:
            page=browser.new_page()
            page.set_content(regression_document())
            page.evaluate("document.querySelector('#async .participant-insurance-cell').replaceChildren(document.querySelector('#linked-template').content.cloneNode(true))")
            for width in (320,390,1440):
                page.set_viewport_size({'width':width,'height':900})
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    page.wait_for_function("[...document.querySelectorAll('.participant-link-details > summary')].every(s=>!s.classList.contains('site-action'))")
                    heights=page.locator('#income-tbl tbody tr').evaluate_all('(rows)=>rows.map(r=>r.getBoundingClientRect().height)')
                    assert max(heights)-min(heights)<1,heights
                    assert heights[0]==(93 if width<760 else 45),heights
                    candidate=page.locator('#candidate button')
                    assert 'site-action' not in (candidate.get_attribute('class') or '')
                    assert candidate.evaluate("el=>getComputedStyle(el).borderTopWidth") == '0px'
            summary=page.locator('#linked summary')
            summary.focus();page.keyboard.press('Enter')
            assert page.locator('#linked details').get_attribute('open') is not None
            assert page.locator('#linked button').is_visible()
            page.keyboard.press('Enter')
            assert page.locator('#linked details').get_attribute('open') is None
        finally:
            browser.close()
