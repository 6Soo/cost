import json
import re
import subprocess
import time

import pytest

from app import ota_core_projection, ota_payments
from app.ota_review import OtaReviewStore
from tests.card_pipeline.test_toyoko_mail import message
from webapp import card_catalog, ota_catalog, ota_payment_review
from webapp.card_flow import CardFlow, page
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD
from webapp.tests.test_ota_payment_review import primed


def test_mail_core_card_ota_views_share_reservation_candidates_and_preserve_decision(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    monkeypatch.setenv('WEBLEDGER_REVIEW_FROM', '')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'isolated')
    review_path = tmp_path / 'review.sqlite'
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(review_path))
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    maildir = tmp_path / 'ota-mail'
    maildir.mkdir()
    mail = message()
    (maildir / 'gmail-synthetic.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    sources = {'mail_directories': [str(maildir)], 'portal_databases': [], 'missing': []}
    flow = CardFlow(board)
    flow.pipeline.receive(CARD.replace('합성상점'.encode(), '토요코인 울산삼산동'.encode()), 'synthetic.csv')
    row = board.conn.execute('SELECT transaction_id FROM transactions').fetchone()
    tid = row[0]
    board.conn.execute("UPDATE transactions SET decided_at='2026-10-01T11:00:00',"
                       "display_tab_id='owner-trip-B',trip_id='owner-trip-B',classification_source='manual'")
    board.conn.commit()
    store = OtaReviewStore(review_path)
    store.close()
    backend = ota_payment_review.CoreOtaPaymentBackend(board, str(review_path), read_only=True,
        payments=ota_payments, store_type=OtaReviewStore, sources=sources)
    before = board.conn.total_changes
    try:
        data = backend._data()
        event = data[0][0]
        result = data[3][0]
        assert result['status'] == 'RESERVATION_ONLY'
        assert result['reservation_link']['status'] == 'INFERRED'
        assert result['reservation_link']['payment_verified'] is False
        assert result['candidate_search']['candidates'][0]['transaction_id'] == tid
        snapshot = backend.snapshot_from(data)
        candidate = snapshot['cards_by_event'][event['ota_event_id']][0]
        assert candidate['selection_disabled'] is True
        assert snapshot['events'][0]['reservation_link']['status'] == 'INFERRED'
        canonical = {'events': data[0], 'transactions': data[1], 'links': data[2], 'results': data[3]}
        current = {'generation': 7, 'results': [{'ota_event_id': event['ota_event_id'], 'status': 'RESERVATION_ONLY',
            'reservation_link': result['reservation_link'], 'candidate_search': result['candidate_search']}],
                   'data': canonical}
        monkeypatch.setattr(CardFlow, '_held_ota_snapshot', lambda self: (current, True))
        notes = flow._ota_candidate_notes([{'transaction_id': tid}])
        assert any('1234567' in note and '미확정' in note for note in notes[tid])
        missing = flow._ota_candidate_notes([{'transaction_id': 'missing-native',
            'merchant': 'TOYOKO INN Tokyo JP', 'foreign_currency': '', 'foreign_amount': ''}])
        assert '현지 금액·통화 확인' in missing['missing-native'][0]
        states, generation, _ = flow._ota_card_statuses([{'transaction_id': tid}])
        assert states[tid] == 'RESERVATION_INFERRED' and generation == 7
        assert any('예약 추론' in note and '숙박 2026-10-01~2026-10-03' in note for note in notes[tid])
        listing = card_catalog.catalog(board, {})
        assert '1234567' in card_catalog.render_html(listing, {})
        page_html = ota_payment_review.render_import_section('synthetic-csrf')
        assert 'reservation/preview' in page_html and '예약 관계만 확인' in page_html
        assert '이 거래로 결제 연결 확정' in page_html
        assert 'reservation/confirm' in page_html
        assert ota_catalog._reservation_card_candidates(flow)[('toyoko', event['booking_ref'])] == [tid]
        assert ota_catalog._reservation_link_states(flow)[('toyoko', event['booking_ref'])][0]['status'] == 'INFERRED'
        warnings = []
        assert ('toyoko', event['booking_ref']) in ota_catalog._rows_from_sources(board, sources, warnings)
        ota_listing = ota_catalog.catalog(board, {}, sources=sources)
        ota_entry = next(item for item in ota_listing['rows'] if item['booking_ref'] == event['booking_ref'])
        assert ota_entry['card_candidates'] == [tid]
        assert ota_entry['reservation_links'][0]['status'] == 'INFERRED'
        ota_html = ota_catalog.render_html(ota_listing, {})
        assert '예약 추론 연결 · 결제 미검증' in ota_html
        assert tid not in ota_html
        # 예약 후보를 장부 예약번호나 확정 비용 근거로 승격하지 않는다.
        assert ota_core_projection.card_matches([], canonical) == []
        with pytest.raises(ota_payment_review.InvalidReviewInput):
            backend._selection(event['ota_event_id'], tid, canonical)
        assert board.conn.total_changes == before
        saved = board.conn.execute('SELECT trip_id,classification_source FROM transactions').fetchone()
        assert tuple(saved) == ('owner-trip-B', 'manual')
        backend.close()
        writer = ota_payment_review.CoreOtaPaymentBackend(board, str(review_path), read_only=False,
            payments=ota_payments, store_type=OtaReviewStore, sources=sources)
        backend = writer
        # Keep the synthetic authority input stable across snapshot priming; no authority fetch is used.
        board._reservation_authority = {'authority': None, 'error': 'synthetic_unavailable',
            'fresh': False, 'degraded': False, 'checked_at': time.monotonic(), 'last_success_at': None,
            'digest': 'synthetic-authority-unavailable'}
        key_before = ota_payment_review.input_key_for(writer)
        primed(board, writer)
        assert ota_payment_review.input_key_for(writer) == key_before
        preview = writer.reservation_preview(event['ota_event_id'], tid)
        confirmed = writer.reservation_confirm(event['ota_event_id'], tid, preview['preview_digest'],
            expected_revision=preview['expected_revision'], request_id='synthetic-reservation-confirm',
            user='synthetic-owner')
        assert confirmed['status'] == 'USER_CONFIRMED' and confirmed['payment_verified'] is False
        assert ota_payment_review.input_key_for(writer) != key_before
        updated = writer._data()
        assert updated[3][0]['status'] == 'RESERVATION_ONLY'
        assert updated[3][0]['reservation_link']['status'] == 'USER_CONFIRMED'
        assert writer.snapshot_from(updated)['events'][0]['reservation_link']['status'] == 'USER_CONFIRMED'
        (maildir / 'gmail-synthetic.json').write_text(json.dumps({'responses': []}), encoding='utf-8')
        missing_mail = writer._data()
        missing_result = next(row for row in missing_mail[3] if row['ota_event_id'] == event['ota_event_id'])
        missing_event = next(row for row in missing_mail[0] if row['ota_event_id'] == event['ota_event_id'])
        assert missing_event['evidence_missing'] is True
        assert missing_result['status'] == 'RESERVATION_ONLY'
        assert missing_result['reservation_link']['status'] == 'STALE'
        assert missing_result['candidate_search']['candidates'] == []
        writer._transactions = lambda: []
        missing_card = writer._data()
        missing_relation = next(row['reservation_link'] for row in missing_card[3]
                                if row['ota_event_id'] == event['ota_event_id'])
        assert missing_relation['status'] == 'STALE'
        assert writer.snapshot_from(missing_card)['events'][0]['reservation_link']['status'] == 'STALE'
        with pytest.raises((ota_payment_review.InvalidReviewInput, ota_payment_review.StalePreviewError)):
            writer.preview(event['ota_event_id'], tid)
        assert board.conn.total_changes == before
        saved = board.conn.execute('SELECT trip_id,classification_source FROM transactions').fetchone()
        assert tuple(saved) == ('owner-trip-B', 'manual')
    finally:
        backend.close()
        board.close()


def test_card_refresh_detects_new_reservation_candidates_without_financial_changes():
    stamp = re.search(r'^const stateStamp=.*$', page('synthetic-csrf'), re.MULTILINE).group(0)
    script = stamp + """
const before={batch_id:'synthetic',preview:{digest:'same'},rows:[{transaction_id:'one',revision:1}],trips:[]};
const after=JSON.parse(JSON.stringify(before));
after.rows[0].ota_link_status='CANDIDATE';
after.rows[0].ota_snapshot_generation=2;
after.rows[0].ota_candidate_notes=['synthetic reservation candidate'];
if(stateStamp(before)===stateStamp(after)) throw Error('new candidate did not refresh card view');
"""
    subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)


def test_public_snapshot_validates_reservation_link_without_exposing_private_fields():
    value = ota_payment_review.public_snapshot({'events': [
        {'ota_event_id': 'evt', 'provider': 'toyoko', 'reservation_link': {
            'status': 'USER_CONFIRMED', 'transaction_id': 'card-syn', 'basis': 'USER_CONFIRMED',
            'amount_status': 'UNKNOWN', 'payment_verified': True, 'event': {'secret': 'hidden'}}},
        {'ota_event_id': 'bad', 'reservation_link': {'status': 'MATCHED_USER', 'transaction_id': 'secret'}}]})
    assert value['events'][0]['reservation_link'] == {
        'status': 'USER_CONFIRMED', 'transaction_id': 'card-syn', 'basis': 'USER_CONFIRMED',
        'amount_status': 'UNKNOWN', 'payment_verified': False}
    assert 'reservation_link' not in value['events'][1]
    assert 'secret' not in json.dumps(value)


def test_reservation_review_script_parses_with_node():
    html = ota_payment_review.render_import_section('synthetic-csrf')
    scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
    assert scripts
    subprocess.run(['node', '--check'], input=scripts[-1], check=True, capture_output=True, text=True)
