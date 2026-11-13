"""Rendered primary screens must not point at unregistered internal routes."""
import re
from html import unescape
from urllib.parse import urlsplit
from types import SimpleNamespace

from webapp import cards_all, receipt_review
from webapp.card_flow import home_page
from webapp import ledger_board


def test_primary_screen_internal_links_have_registered_paths(monkeypatch):
    class Lock:
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    class Result:
        def __iter__(self): return iter(())
        def fetchone(self): return (0, 0)
        def fetchall(self): return []

    board = SimpleNamespace(conn=SimpleNamespace(execute=lambda *_: Result()), _lock=Lock(),
                            list_trips=lambda: [], visible_row_count=lambda: 0)
    monkeypatch.setattr('app.reserve_trips.registrations', lambda _board: {})
    monkeypatch.setattr('app.reserve_trips.sync_status', lambda _board: {})
    monkeypatch.setattr('webapp.ledger_design.render', lambda value, **_kwargs: value)
    monkeypatch.setattr('webapp.ledger_design.shell', lambda *args, **kwargs: kwargs['body'])

    screens = [
        home_page(board),
        ledger_board.trips_page(),
        cards_all._transaction_header(),
        receipt_review.render_html({'candidates': [], 'holds': [], 'images': [],
                                    'pdfs': [], 'uploads': [], 'drafts': []}, 'synthetic'),
    ]
    registered = {'/', '/board', '/cards/all', '/receipts', '/export', '/trips',
                  '/participants', '/reserve-links', '/rules', '/ota'}
    for name in ('receipt_review', 'cards_all'):
        module = globals()[name]
        registered.update(getattr(module, 'ROUTES', ()))
    for screen in screens:
        for raw in re.findall(r"href=['\"]([^'\"]+)['\"]", screen):
            href = unescape(raw)
            parts = urlsplit(href)
            if not parts.scheme and not parts.netloc and parts.path:
                assert parts.path in registered, href
