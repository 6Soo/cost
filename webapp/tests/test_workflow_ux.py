from unittest.mock import patch
from html.parser import HTMLParser

from webapp import ledger_board as board
from webapp.ledger_store import LedgerStore


def elements(document, tag, **expected):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.found = []

        def handle_starttag(self, name, attrs):
            attrs = dict(attrs)
            if name == tag and all(key in attrs and (value is None or attrs[key] == value)
                                   for key, value in expected.items()):
                self.found.append(attrs)
    parser = Parser()
    parser.feed(document)
    return parser.found


def test_trip_and_export_views_preserve_data_and_explicit_selection(tmp_path):
    store = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    try:
        trips = [store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                                   destination='합성 UX ' + label, client_request_id='ux-'+label)
                 for label in ('A', 'B')]
        before = list(store.conn.iterdump())
        with patch.object(board, '_STORE', store), patch.object(board, 'current_role', return_value='owner'):
            page = board.export_page(trips[1]['tab_id'])
            assert [e['value'] for e in elements(page, 'input', name='tab_ids', checked=None)] == [trips[1]['tab_id']]
            assert len(elements(board.export_page(), 'input', name='tab_ids', checked=None)) == 2
            assert len(elements(board.export_page('not-a-trip'), 'input', name='tab_ids', checked=None)) == 2
            # Snapshot settings remain enabled for income reads after the old page's removal.
            with patch('webapp.google_ledger_page.enabled', return_value=True):
                management = board.trips_page(role='owner')
            # wave3 2fb8916a moved trip rows from <article class='card …'> to <tr>.
            assert len(elements(management, 'tr', **{'class':'trip-management-row'})) == 2
            assert not elements(management, 'details', **{'class':'trip-meta','open':None})
            assert elements(management, 'form', id='trip-management-filter')
            assert not elements(management, 'a', href='/google-ledger')
            manual = board.expense_new_page(trips[1]['tab_id'])
            assert elements(manual, 'option', selected=None)[0]['value'] == trips[1]['tab_id']
        assert list(store.conn.iterdump()) == before
    finally:
        store.close()
