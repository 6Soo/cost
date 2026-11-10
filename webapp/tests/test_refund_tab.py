import json

import pytest

from webapp import ledger_board as board, ledger_design as design, refund_tab, live_sync
from webapp.tests import test_refund_group_commit as fixtures


@pytest.fixture
def pair():
    case = fixtures.RefundGroupCommitTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def test_all_linked_members_keep_their_identity_and_multiple_refunds(pair):
    conn = pair.board.conn
    conn.execute("UPDATE transactions SET transaction_direction='cancellation', amount_krw=-100000, "
                 "original_approval_number='100' WHERE transaction_id=?", (pair.other,))
    conn.commit()
    before = conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    assert refund_tab.groups(pair.board) == []
    conn.execute('UPDATE transactions SET amount_krw=-300000 WHERE transaction_id=?', (pair.other,))
    conn.commit()
    before = conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    grouped = refund_tab.groups(pair.board)
    assert len(grouped) == 1
    assert {r['transaction_id'] for r in grouped[0]} == {pair.original, pair.refund, pair.other}
    assert sum(r['amount_krw'] for r in grouped[0]) == 0
    html = design.page('refunds')
    assert '전액 환불' in html and '-700,000원' in html and '-300,000원' in html
    assert '미기록' in html
    assert before == conn.execute('SELECT * FROM transactions ORDER BY transaction_id').fetchall()
    assert conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0] == 0
    assert '전액 환불' in design.rows_part('refunds')
    assert design.summary_part('refunds') == ''


def test_booked_pair_moves_only_in_owner_display_and_preserves_totals(pair, monkeypatch):
    conn = pair.board.conn
    for tid, amount in ((pair.original, 1000000), (pair.refund, -700000)):
        payload = dict(row_id='saved-' + tid, row_kind='expense', display_tab_id=None,
                       amount_krw=amount, occurred_on='2026-10-01', item='항공료',
                       description='합성항공', source_event_id=tid, revision=1)
        conn.execute('INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json) VALUES (?,?,?,?,?)',
                     (payload['row_id'], 'expense', None, 1, json.dumps(payload)))
    conn.commit()
    before = conn.execute('SELECT * FROM board_rows ORDER BY row_id').fetchall()
    monkeypatch.setattr(board, 'current_role', lambda: 'owner')
    assert len(design._selected_rows('unclassified')[1]) == 2
    assert refund_tab.groups(pair.board) == []
    conn.execute('UPDATE transactions SET amount_krw=-1000000 WHERE transaction_id=?', (pair.refund,))
    conn.commit()
    assert len(design._selected_rows('unclassified')[1]) == 2
    refund_row = pair.board.get_row('saved-' + pair.refund)
    refund_row['amount_krw'] = -1000000
    conn.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?', (json.dumps(refund_row), refund_row['row_id']))
    conn.commit()
    before = conn.execute('SELECT * FROM board_rows ORDER BY row_id').fetchall()
    assert design._selected_rows('unclassified')[1] == []
    assert len(design._selected_rows('unclassified')[3]) == 0
    assert '0원' in design.summary_part('unclassified')
    assert '장부 기록됨' in refund_tab.render(pair.board)
    assert '자료 검토' in design.page('refunds')
    # Refunds moved from the sidebar to the 거래 section tabs (UI/UX spec §5.3).
    assert 'tab=refunds' not in design.nav_part('unclassified')
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    assert len(design._selected_rows('unclassified')[1]) == 2
    assert before == conn.execute('SELECT * FROM board_rows ORDER BY row_id').fetchall()


def test_refund_changes_refresh_the_virtual_tab_and_conflicts_are_not_paired(pair):
    before = live_sync.owner_token(pair.board, 'refunds')
    pair.board.conn.execute("UPDATE transactions SET conflict_reason='synthetic conflict' WHERE transaction_id=?", (pair.refund,))
    pair.board.conn.commit()
    assert live_sync.owner_token(pair.board, 'refunds') != before
    assert refund_tab.groups(pair.board) == []
    assert '환불 쌍이 없습니다.' in refund_tab.render(pair.board)


def test_partial_refund_stays_with_its_trip_and_net_cost(pair):
    conn = pair.board.conn
    for tid, amount in ((pair.original, 1000000), (pair.refund, -700000)):
        row = dict(row_id='trip-' + tid, row_kind='expense', display_tab_id='trip-A',
                   amount_krw=amount, occurred_on='2026-10-01', item='항공료',
                   description='합성항공', source_event_id=tid, revision=1)
        conn.execute('INSERT INTO board_rows VALUES (?,?,?,?,?)',
                     (row['row_id'], 'expense', 'trip-A', 1, json.dumps(row)))
    conn.execute("INSERT INTO trip_tabs(tab_id,display_key) VALUES ('trip-A','합성 여행')")
    conn.commit()
    assert len(design._selected_rows('trip-A')[1]) == 2
    assert '300,000원' in design.summary_part('trip-A')
    assert refund_tab.groups(pair.board) == []


def test_cancellation_own_approval_without_original_reference_is_not_a_confirmed_group(pair):
    conn = pair.board.conn
    conn.execute("UPDATE transactions SET original_approval_number='',approval_number='100',amount_krw=-1000000 WHERE transaction_id=?", (pair.refund,))
    conn.commit()
    assert refund_tab.groups(pair.board) == []
    conn.execute("UPDATE transactions SET approval_number='100' WHERE transaction_id=?", (pair.other,))
    conn.commit()
    assert refund_tab.groups(pair.board) == []


def test_refund_page_mobile_and_live_fragments_keep_all_members(pair):
    from playwright.sync_api import sync_playwright
    pair.board.conn.execute('UPDATE transactions SET amount_krw=-1000000 WHERE transaction_id=?', (pair.refund,))
    pair.board.conn.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.set_content(design.render(design.page('refunds')))
            assert page.locator('.refund-card').count() == 1
            assert page.locator('.refund-line').count() == 2
            assert page.locator('#live-rows').count() == 1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert '환불' in page.locator('h1').inner_text()
        finally:
            browser.close()
