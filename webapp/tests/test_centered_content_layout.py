"""Desktop content alignment and small-screen reflow with synthetic pages."""
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_design_assets, receipt_review, site_shell


def test_native_and_receipt_content_are_centered_in_workspace():
    native = ("<!doctype html><html><head><style>" + ledger_design_assets.STYLE +
              "</style></head><body><div class='app'><aside id='nav'></aside>"
              "<main class='main' id='main'><div class='page-hd'><div><h1>여행 관리</h1></div>"
              "<div class='act'><a href='/board'>장부</a></div></div>"
              "<div class='page-body'><div class='sect'>합성 내용</div></div></main></div></body></html>")
    with patch('webapp.ledger_design._nav_html', return_value="<aside id='nav'></aside>"):
        receipt = site_shell.wrap_document(receipt_review.render_html(
            {'candidates': [], 'holds': [], 'images': []}, csrf='synthetic', trips=[]), '/receipts')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1920, 'height': 900})
            for doc, parent, content in [(native, 'main', '.page-body'),
                                         (receipt, '#site-content', '#site-content > main')]:
                page.set_content(doc, wait_until='domcontentloaded')
                if parent == '#site-content':
                    assert page.evaluate("document.querySelector('.site-app').getBoundingClientRect().width") == 1920
                sizes = page.evaluate("""([p,c])=>{const a=document.querySelector(p).getBoundingClientRect(),
                    b=document.querySelector(c).getBoundingClientRect();
                    return {width:b.width, offset:Math.abs((a.left+a.right-b.left-b.right)/2)}}""", [parent, content])
                assert sizes['width'] <= 1180
                assert sizes['offset'] < 2
            page.set_viewport_size({'width': 390, 'height': 844})
            for doc in (native, receipt):
                page.set_content(doc, wait_until='domcontentloaded')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
