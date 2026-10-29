"""Synthetic regression for the ledger's internal scrollports and viewport."""

import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from webapp import ledger_board
from webapp.ledger_store import LedgerStore


def test_ledger_long_content_stays_in_document_viewport_and_scrolls_by_keyboard():
    from playwright.sync_api import sync_playwright

    temp_dir = tempfile.mkdtemp(prefix="cost-ledger-viewport-")
    with patch.dict(os.environ, {
        "WEBLEDGER_DB": str(Path(temp_dir) / "viewport.sqlite"),
        "WEBLEDGER_EXPORT_DIR": str(Path(temp_dir) / "exports"),
    }):
        store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        ledger_board.bind_store(store)
        server = ledger_board.serve(port=0, with_worker=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    for width in (375, 390, 759, 760, 1280):
                        page = browser.new_page(viewport={"width": width, "height": 600})
                        page.goto(f"http://127.0.0.1:{server.server_address[1]}/board?tab=trip-demo-a")
                        page.evaluate("""() => {
                            for (const selector of ['#main', '#nav']) {
                                const tail = document.createElement('div');
                                tail.style.height = '1800px';
                                tail.textContent = 'Synthetic scroll boundary';
                                document.querySelector(selector).append(tail);
                            }
                        }""")
                        if width < 760:
                            page.click("#btn-menu")
                            page.wait_for_timeout(300)

                        page.locator("#nav").evaluate("element=>element.scrollTop=element.scrollHeight")
                        assert page.locator("#nav").evaluate("element=>element.scrollTop>0")
                        assert page.locator("#main").evaluate("element=>element.scrollTop===0")
                        if width < 760:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(300)

                        page.locator("#main").focus()
                        page.keyboard.press("PageDown")
                        page.wait_for_timeout(100)
                        assert page.locator("#main").evaluate("element=>element.scrollTop>0")
                        page.locator("#main").evaluate("element=>element.scrollTop=element.scrollHeight")
                        assert page.locator("#main").evaluate(
                            "element=>Math.abs(element.scrollHeight-element.clientHeight-element.scrollTop)<=1"
                        )
                        assert page.evaluate("window.scrollY===0")
                        assert page.evaluate("document.documentElement.scrollHeight-innerHeight<=1")
                        assert page.evaluate("document.documentElement.scrollWidth-innerWidth===0")
                        page.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            ledger_board.bind_store(None)
            store.close()
