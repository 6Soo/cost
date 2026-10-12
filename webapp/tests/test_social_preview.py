from urllib.request import urlopen
import threading

from webapp import ledger_board as board


def test_public_preview_and_image_without_ledger_access(tmp_path):
    server = board.serve(port=0, db_path=str(tmp_path / "board.sqlite"),
                         with_worker=False, seed_demo=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/share") as response:
            html = response.read().decode()
            assert response.status == 200
            assert 'rel="icon"' in html
            assert 'href="/assets/brand/wallet-favicon-v2.png"' in html
            assert 'property="og:image"' in html
            assert 'https://ledger.foresttour.kr/assets/og/cost-travel-v3.png' in html
            assert 'name="twitter:card" content="summary_large_image"' in html
            assert 'content="1200"' in html and 'content="630"' in html
        with urlopen(base + "/assets/og/cost-travel-v3.png") as response:
            data = response.read()
            assert response.headers['Content-Type'] == 'image/png'
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            assert int.from_bytes(data[16:20], 'big') == 1200
            assert int.from_bytes(data[20:24], 'big') == 630
        with urlopen(base + "/assets/brand/wallet-favicon-v2.png") as response:
            data = response.read()
            assert response.headers['Content-Type'] == 'image/png'
            assert int.from_bytes(data[16:20], 'big') == 32
            assert int.from_bytes(data[20:24], 'big') == 32
        with urlopen(base + "/favicon.ico") as response:
            assert response.headers['Content-Type'] == 'image/x-icon'
            assert response.read()[:4] == b"\x00\x00\x01\x00"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        server.card_store.close()


def test_metadata_leaves_fragments_and_existing_tags_unchanged():
    from webapp import social_preview
    assert social_preview.decorate('<div>fragment</div>') == '<div>fragment</div>'
    html = social_preview.decorate('<html><head></head><body>private</body></html>')
    assert html.count('property="og:image"') == 1
    assert social_preview.decorate(html) == html
    assert 'private' not in social_preview.META


def test_favicon_has_transparent_background_at_all_sizes():
    from PIL import Image
    from pathlib import Path
    brand = Path(__file__).parents[1] / "static" / "brand"
    with Image.open(brand / "wallet-favicon-v2.png") as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((16, 20))[3] >= 250
    with Image.open(brand / "wallet-favicon-v2.ico") as icon:
        for size in [(16, 16), (32, 32), (48, 48)]:
            frame = icon.ico.getimage(size).convert("RGBA")
            assert frame.getpixel((0, 0))[3] == 0
            assert frame.getpixel((size[0] // 2, size[1] * 2 // 3))[3] >= 250
