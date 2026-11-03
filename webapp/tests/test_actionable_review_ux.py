"""Synthetic action destinations and recovery after transient read failures."""
import json
import threading
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import sync_playwright

from webapp import cards_all, card_transactions, ledger_board, ota_payment_review
from webapp.tests.test_card_transactions import card_db_path
from webapp.tests.test_card_automatic_ux import flow
from webapp.trip_flight_ui import render_trip_flights


@pytest.fixture(autouse=True)
def synthetic_schema(monkeypatch):
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')


def test_all_card_projections_link_the_exact_batch_without_writes(card_db_path):
    import sqlite3
    with closing(sqlite3.connect(card_db_path)) as conn:
        before = list(conn.iterdump())
    groups = [card_transactions.list_for_month(card_db_path, 2026, 3),
              card_transactions.search_for_year(card_db_path, 2026, search=''),
              card_transactions.undated_list(card_db_path, 2026)]
    for group in groups:
        assert group['items']
        for row in group['items']:
            action = cards_all._review_action(row)
            assert row['batch_id'] and 'transaction=' in action and 'batch=' in action
            assert cards_all._review_action(card_transactions.transaction_detail(row['transaction_id'], card_db_path))
    with closing(sqlite3.connect(card_db_path)) as conn:
        assert list(conn.iterdump()) == before


def test_history_distinguishes_absent_current_and_stale_holds(card_db_path):
    import sqlite3
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute('CREATE TABLE transaction_review_holds (transaction_id TEXT, source_hash TEXT, kind TEXT, reason TEXT)')
        conn.execute("UPDATE transactions SET item='항공료', display_tab_id='T-A', classification_state='classified' WHERE transaction_id='TX-A-01'")
    row = card_transactions.transaction_detail('TX-A-01', card_db_path)
    assert 'review_hold' not in row
    assert row['next_action']['reason_category'] == ''
    assert '근거 충돌' not in cards_all.card_detail_html(row)
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("INSERT INTO transaction_review_holds VALUES ('TX-A-01','h1','manual_hold','확인할 합성 사유')")
    row = card_transactions.transaction_detail('TX-A-01', card_db_path)
    detail = cards_all.card_detail_html(row)
    assert '사용자 보류' in detail and '확인할 합성 사유' in detail
    assert 'transaction=TX-A-01' in detail and '사유 확인' in detail
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transaction_review_holds SET source_hash='old'")
    row = card_transactions.transaction_detail('TX-A-01', card_db_path)
    assert row['next_action']['reason_category'] == 'evidence'
    assert '보류한 원본이 달라' in cards_all.card_detail_html(row)


def test_history_review_button_opens_exact_editable_transaction(flow, monkeypatch):
    f, batch, _ = flow
    monkeypatch.setenv('WEBLEDGER_DB', str(f.board.path))
    previous = ledger_board._STORE
    ledger_board.bind_access(None)
    server = ledger_board.serve(port=0, with_worker=False, db_path=f.board.path, seed_demo=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        row = next(r for r in f.pipeline.get_batch(batch)['rows'] if r['amount_krw'] == 89891)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                page.goto(f'http://127.0.0.1:{server.server_address[1]}/cards/all?year=2026&month=4')
                target = page.locator(f'tr[data-tx-id="{row["transaction_id"]}"]')
                link = target.locator('.card-review-action')
                box = link.bounding_box()
                assert box['width'] >= 44 and box['height'] >= 44
                query = parse_qs(urlsplit(link.get_attribute('href')).query)
                assert query == {'batch': [batch], 'transaction': [row['transaction_id']]}
                link.click()
                page.locator('#questions article form').first.wait_for()
                assert '합성 AGODA A' in page.locator('#questions article').first.inner_text()
                assert page.locator('#questions article select[name=display_tab_id]').is_enabled()
                assert page.locator('#questions article input[name=item]').is_enabled()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); server.card_store.close(); thread.join(timeout=3)
        ledger_board.bind_store(previous)


def test_ota_group_failure_keeps_a_working_retry_button():
    attempts = []
    def respond(route):
        path = urlsplit(route.request.url).path
        if path.endswith('/summary'):
            body = dict(status='ready', fresh=True, stale=False, refreshing=False,
                        generation=4, counts_authoritative=True,
                        counts_by_queue={'needs_action': {'event_count': 1, 'group_count': 1}})
        elif path.endswith('/groups'):
            body = dict(generation=4, next_cursor=None, items=[dict(reason_codes=[], event=dict(
                provider='agoda', booking_ref='SYNTH', group_id='a'*64, group_total_count=1,
                group_members=[]))])
        elif path.endswith('/members'):
            attempts.append(path)
            if len(attempts) == 1:
                route.fulfill(status=503, json={'code': 'TEMPORARILY_UNAVAILABLE'})
                return
            body = dict(generation=4, total_count=1, next_cursor=None, items=[dict(event=dict(
                ota_event_id='synthetic', detail_available=True, event_type='charge'))])
        else:
            body = {}
        route.fulfill(json=body)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('**/api/imports/ota/**', respond)
            page.set_content("<base href='http://localhost/'>" + ota_payment_review.render_import_section('csrf'))
            page.locator('#ota-review > summary').click()
            page.locator('#ota-events > details > summary').click()
            page.get_by_role('button', name='구성원 다시 불러오기').click()
            page.locator('[data-load-detail=synthetic]').wait_for()
            assert len(attempts) == 2
            assert page.locator('[data-group-error]').count() == 0
        finally:
            browser.close()


def test_flight_list_and_detail_can_retry_without_collapsing():
    attempts = {'list': 0, 'detail': 0}
    def respond(route):
        detail = 'booking_key=' in route.request.url
        kind = 'detail' if detail else 'list'
        attempts[kind] += 1
        if attempts[kind] == 1:
            route.fulfill(status=503, json={'code': 'UNAVAILABLE'})
        elif detail:
            route.fulfill(json={'item': {'booking_ref': 'SYNTH', 'passengers': ['Synthetic'], 'legs': []}})
        else:
            route.fulfill(json=dict(items=[dict(booking_key='SYNTH', booking_ref='SYNTH', passenger_count=1)],
                                    source_generation='g', total_bookings=1, next_cursor=None))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://test.local/', lambda route: route.fulfill(body=render_trip_flights('trip-A'), content_type='text/html; charset=utf-8'))
            page.route('http://test.local/api/**', respond)
            page.goto('http://test.local/')
            page.locator('summary').click()
            page.get_by_role('button', name='다시 불러오기', exact=True).click()
            page.get_by_role('button', name='출발일 미확인 · SYNTH').click()
            page.get_by_role('button', name='다시 불러오기', exact=True).click()
            page.locator('.trip-flight-detail').wait_for()
            assert attempts == {'list': 2, 'detail': 2}
        finally:
            browser.close()


def test_missing_participant_sources_offer_concrete_destinations(monkeypatch):
    from webapp import participant_income_page
    monkeypatch.setattr(participant_income_page, '_trip_options', lambda _: [])
    document = participant_income_page.render_page(dict(
        trip_id='synthetic trip&1', configured=False, google={'available': False},
        participants=[], unlinked_income=[], completion={'blocked_by': ['ROSTER_MISSING']}))
    assert "href='/reserve-links'" in document
    assert "href='/google-ledger'" in document
    assert "href='/board?tab=synthetic+trip%261'" in document
