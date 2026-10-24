import json
import re
import subprocess

import pytest

from app import ota_core_projection, ota_payments
from app.ota_review import OtaReviewStore
from tests.card_pipeline.test_toyoko_mail import message
from webapp import card_catalog, ota_catalog, ota_payment_review
from webapp.card_flow import CardFlow, page
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD


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
        assert result['candidate_search']['candidates'][0]['transaction_id'] == tid
        snapshot = backend.snapshot_from(data)
        candidate = snapshot['cards_by_event'][event['ota_event_id']][0]
        assert candidate['selection_disabled'] is True
        canonical = {'events': data[0], 'transactions': data[1], 'links': data[2], 'results': data[3]}
        current = {'generation': 7, 'results': [{'ota_event_id': event['ota_event_id'], 'status': 'RESERVATION_ONLY'}],
                   'data': canonical}
        monkeypatch.setattr(CardFlow, '_held_ota_snapshot', lambda self: (current, True))
        notes = flow._ota_candidate_notes([{'transaction_id': tid}])
        assert '1234567' in notes[tid][0] and '미확정' in notes[tid][0]
        missing = flow._ota_candidate_notes([{'transaction_id': 'missing-native',
            'merchant': 'TOYOKO INN Tokyo JP', 'foreign_currency': '', 'foreign_amount': ''}])
        assert '현지 금액·통화 확인' in missing['missing-native'][0]
        states, generation, _ = flow._ota_card_statuses([{'transaction_id': tid}])
        assert states[tid] == 'CANDIDATE' and generation == 7
        listing = card_catalog.catalog(board, {})
        assert '1234567' in card_catalog.render_html(listing, {})
        assert ota_catalog._reservation_card_candidates(flow)[('toyoko', event['booking_ref'])] == [tid]
        warnings = []
        assert ('toyoko', event['booking_ref']) in ota_catalog._rows_from_sources(board, sources, warnings)
        # 예약 후보를 장부 예약번호나 확정 비용 근거로 승격하지 않는다.
        assert ota_core_projection.card_matches([], canonical) == []
        with pytest.raises(ota_payment_review.InvalidReviewInput):
            backend._selection(event['ota_event_id'], tid, canonical)
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
