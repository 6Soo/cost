from playwright.sync_api import sync_playwright, expect

from webapp.card_flow import page


def test_card_upload_accepts_multiple_files_and_drop_target_is_keyboard_accessible():
    document = page("synthetic-csrf")
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page()
            screen.route("http://synthetic.test/import*", lambda r: r.fulfill(
                content_type="text/html", body=document))
            screen.route("http://synthetic.test/api/imports/rules", lambda r: r.fulfill(
                content_type="application/json", body='{"rules": []}'))
            screen.route("http://synthetic.test/api/imports", lambda r: r.fulfill(
                content_type="application/json", body='{"batches": []}'))
            screen.goto("http://synthetic.test/import#newupload")
            expect(screen.locator("#upload-drop")).to_be_visible()
            screen.locator("#file").set_input_files([
                {"name": "january.csv", "mimeType": "text/csv", "buffer": b"a,b\n"},
                {"name": "february.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": b"PK"},
            ])
            assert screen.locator("#file").get_attribute("multiple") is not None
            assert screen.locator("#file").evaluate("el => el.files.length") == 2
            expect(screen.locator("#upload-selection")).to_contain_text("2개 파일 선택됨")
            assert screen.locator("#upload-drop").get_attribute("tabindex") == "0"
            with screen.expect_file_chooser(timeout=3000):
                screen.locator("#upload-drop").press("Enter")
            screen.locator("#upload-drop").dispatch_event("dragover")
            assert "is-dragover" in (screen.locator("#upload-drop").get_attribute("class") or "")
            screen.evaluate("""() => {
                const transfer = new DataTransfer();
                transfer.items.add(new File(['a,b'], 'dropped.csv'));
                transfer.items.add(new File(['invalid'], 'unsupported.txt'));
                document.querySelector('#upload-drop').dispatchEvent(
                    new DragEvent('drop', {dataTransfer: transfer, bubbles: true}));
            }""")
            expect(screen.locator("#upload-selection")).to_contain_text("1개 파일 선택됨")
            expect(screen.locator("#upload-file-list")).to_have_text("dropped.csv")
            expect(screen.locator("#status")).to_contain_text("지원하지 않는 파일 형식은 제외")
        finally:
            browser.close()


def test_upload_queue_continues_after_failure_and_preserves_each_outcome():
    """Exercise real JS requests, including a partial classification and HTTP failure."""
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page(viewport={"width": 390, "height": 844})
            requests = []
            screen.route("http://synthetic.test/import*", lambda r: r.fulfill(
                content_type="text/html", body=page("synthetic-csrf")))

            def respond(route):
                request = route.request
                if request.method != "POST":
                    route.fulfill(json={"rules": [], "batches": []})
                    return
                requests.append(request.headers["x-filename"])
                assert request.headers["x-csrf-token"] == "synthetic-csrf"
                assert request.post_data_buffer == b"a,b\n"
                if len(requests) == 2:
                    route.fulfill(status=422, json={"message": "파일 형식 오류"})
                    return
                route.fulfill(json={"batch_id": str(len(requests)), "upload_summary": {
                    "status": "passed" if len(requests) == 1 else "incomplete"}})

            screen.route("http://synthetic.test/api/**", respond)
            screen.goto("http://synthetic.test/import")
            # Rendering the full ledger is covered by the existing server/browser test.
            screen.evaluate("render = () => {}")
            screen.locator("#file").set_input_files([
                {"name": name, "mimeType": "text/csv", "buffer": b"a,b\n"}
                for name in ("first.csv", "broken.csv", "last.csv")])
            screen.locator("#upload").click()
            expect(screen.locator("#status")).to_contain_text("2개 파일 처리 · 1개 파일 업로드 실패 · 1개 파일 분류 미완료")
            assert requests == ["first.csv", "broken.csv", "last.csv"]
            outcomes = screen.locator("#upload-results")
            expect(outcomes).to_contain_text("first.csv · 전수 분류 검증 통과")
            expect(outcomes).to_contain_text("broken.csv · 업로드 실패: 파일 형식 오류")
            expect(outcomes).to_contain_text("last.csv · 분류 미완료")
            assert outcomes.locator("a").evaluate_all("xs => xs.map(x => x.getAttribute('href'))") == [
                "/import?batch=1#summary", "/import?batch=3#summary"]
            expect(screen.locator("#file")).to_be_enabled()
            expect(screen.locator("#upload")).to_be_enabled()
            assert screen.evaluate("document.documentElement.scrollWidth <= innerWidth"), screen.evaluate("Array.from(document.querySelectorAll('*')).filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.tagName,e.id,e.className,e.getBoundingClientRect().width])")
        finally:
            browser.close()
