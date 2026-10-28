"""Synthetic forest mail through the read-only worker/card/detail boundary."""
import json
import pytest

from app import forest_mail, ota_payments
from app.ota_review import OtaReviewStore
from tests.card_pipeline.test_forest_mail import body_notice
from webapp import ota_catalog, ota_payment_review
from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_flow import CARD
from webapp.tests.test_ota_payment_review import primed


def test_worker_candidates_detail_and_trip_suggestion_preserve_manual_financial_state(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    review_path = tmp_path / 'review.sqlite'
    OtaReviewStore(review_path).close()
    maildir = tmp_path / 'mail'
    maildir.mkdir()
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료')
    (maildir / 'gmail-test.json').write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    flow = CardFlow(board)
    flow.pipeline.receive(CARD.replace('합성상점'.encode(), '합성자연휴양림'.encode()), 'synthetic.csv')
    board.conn.execute("UPDATE transactions SET approval_date='2026-10-01',"
                       "display_tab_id='manual-trip-B',trip_id='manual-trip-B',classification_source='manual'")
    board.conn.commit()
    monkeypatch.setattr(ota_catalog, '_trip_context', lambda *_: [
        {'tab_id': 'trip-A', 'name': '합성 여행 A', 'starts_on': '2026-10-04',
         'ends_on': '2026-10-08', 'valid': True},
        {'tab_id': 'invalid', 'name': '미검증 여행', 'starts_on': '2026-10-05',
         'ends_on': '2026-10-05', 'valid': False}])
    backend = ota_payment_review.CoreOtaPaymentBackend(board, str(review_path), read_only=True,
        payments=ota_payments, store_type=OtaReviewStore, sources={'mail_directories': [str(maildir)]})
    before = board.conn.total_changes
    try:
        data = backend._data()
        event, = data[0]
        result, = data[3]
        assert '합성 여행 A' in event['travel_suggestion']
        assert '퇴실일 미확인' in event['travel_suggestion']
        assert '미검증 여행' not in event['travel_suggestion']
        assert result['status'] == 'RESERVATION_ONLY' and result['transaction_id'] is None
        assert len(result['candidate_search']['candidates']) == 1
        snapshot = backend.snapshot_from(data)
        public, = snapshot['events']
        assert public['travel_suggestion'] == event['travel_suggestion']
        candidate, = snapshot['cards_by_event'][event['ota_event_id']]
        assert candidate['selection_disabled'] and not candidate['candidate_resolution_allowed']
        assert candidate['reservation_amount_status'] == 'UNKNOWN'
        assert public['service_period'] == {'starts_on': '2026-10-05', 'ends_on': None}
        assert 'source_ids' not in public and 'source_digest' not in public
        row = board.conn.execute('SELECT trip_id,classification_source FROM transactions').fetchone()
        assert tuple(row) == ('manual-trip-B', 'manual')
        assert board.conn.total_changes == before
        assert backend.store.links() == {}
        # No inferred booking number is needed to make the evidence useful.
        assert public['booking_ref'] is None
    finally:
        backend.close()
        board.close()


def test_trip_suggestions_do_not_use_cancelled_or_conflicting_evidence(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(ota_catalog, '_trip_context', lambda *_: [])
    events = [{'provider': 'forest', 'reservation_status': status,
               'service_period_conflict': conflict,
               'service_period': {'starts_on': '2026-10-05', 'ends_on': None}}
              for status, conflict in [('cancelled', False), ('observed', True)]]
    ota_payment_review._forest_trip_suggestions(SimpleNamespace(list_trips=lambda: []), events)
    assert all('travel_suggestion' not in e for e in events)


def test_forest_relationship_confirmation_is_separate_idempotent_and_preserves_manual_assignment(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_CARD_SCHEMA_POLICY', 'create')
    monkeypatch.setenv('WEBLEDGER_UNIFIED_DB', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    review_path = tmp_path / 'review.sqlite'
    OtaReviewStore(review_path).close()
    maildir = tmp_path / 'mail'
    maildir.mkdir()
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료')
    path = maildir / 'gmail-test.json'
    path.write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
    CardFlow(board).pipeline.receive(CARD.replace('합성상점'.encode(), '국립자연휴양림'.encode()), 'synthetic.csv')
    board.conn.execute("UPDATE transactions SET approval_date='2026-10-01',"
                       "trip_id='manual-trip-B',display_tab_id='manual-trip-B',classification_source='manual'")
    board.conn.commit()
    backend = ota_payment_review.CoreOtaPaymentBackend(board, str(review_path), read_only=False,
        payments=ota_payments, store_type=OtaReviewStore, sources={'mail_directories': [str(maildir)]})
    before = board.conn.total_changes
    try:
        primed(board, backend)
        data = backend._data()
        event, = data[0]
        result, = data[3]
        assert result['reservation_link']['status'] == 'NEEDS_REVIEW'
        candidate, = result['candidate_search']['candidates']
        tid = candidate['transaction_id']
        assert candidate['branch_status'] == 'UNKNOWN' and not candidate['resolution_allowed']
        preview = backend.reservation_preview(event['ota_event_id'], tid)
        assert preview['payment_verified'] is False and preview['amount_difference'] is None
        confirmed = backend.reservation_confirm(event['ota_event_id'], tid, preview['preview_digest'],
            expected_revision=0, request_id='synthetic-forest-confirm', user='synthetic-owner')
        replay = backend.reservation_confirm(event['ota_event_id'], tid, preview['preview_digest'],
            expected_revision=0, request_id='synthetic-forest-confirm', user='synthetic-owner')
        assert confirmed == replay and confirmed['status'] == 'USER_CONFIRMED'
        assert confirmed['payment_verified'] is False
        updated = backend._data()
        assert updated[3][0]['status'] == 'RESERVATION_ONLY'
        assert updated[3][0]['reservation_link']['status'] == 'USER_CONFIRMED'
        assert backend.store.links() == {}
        assert board.conn.total_changes == before
        assert tuple(board.conn.execute('SELECT trip_id,classification_source FROM transactions').fetchone()) == ('manual-trip-B', 'manual')
        # A new room in the same facility cannot inherit the old user relation.
        mail['payload']['body'] = {'content': '2026-10-05 합성자연휴양림 다른실 객실 예약완료'}
        path.write_text(json.dumps({'responses': [mail]}), encoding='utf-8')
        stale = backend._data()
        assert stale[0][0]['ota_event_id'] == event['ota_event_id']
        assert stale[3][0]['reservation_link']['status'] == 'STALE'
        assert backend.store.reservation_links()[event['ota_event_id']]['transaction_id'] == tid
        with pytest.raises((ota_payment_review.InvalidReviewInput, ota_payment_review.OtaSnapshotNotReady,
                            ota_payment_review.StalePreviewError)):
            backend.preview(event['ota_event_id'], tid)
    finally:
        backend.close()
        board.close()


def test_browser_displays_forest_service_day_auth_metadata_and_trip_candidate():
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    mail = body_notice('2026-10-05 합성자연휴양림 가상실 객실 예약완료')
    event, = forest_mail.collect({mail['id']: mail})
    event.update(status='RESERVATION_ONLY', travel_suggestion='합성 여행 · AUTO_INFERRED · 퇴실일 미확인')
    public, = ota_payment_review.public_snapshot({'events': [event]})['events']
    queue_event = dict(public, group_total_count=1,
                       group_members=[dict(public, detail_available=True)])
    def route(request):
        path = urlsplit(request.request.url).path
        if path.endswith('/summary'):
            body = {'status': 'ready', 'fresh': True, 'stale': False, 'refreshing': False,
                    'generation': 9, 'counts_authoritative': True,
                    'counts_by_queue': {'needs_action': {'event_count': 1, 'group_count': 1}}}
        elif path.endswith('/groups'):
            body = {'generation': 9, 'total_count': 1, 'next_cursor': None,
                    'items': [{'queue': 'needs_action', 'reason_codes': [], 'event': queue_event}]}
        elif '/events/' in path:
            body = {'generation': 9, 'event_id': public['ota_event_id'], 'event': public}
        else:
            request.fulfill(status=404, json={})
            return
        request.fulfill(json=body)
    with sync_playwright() as runner:
        browser = runner.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.set_default_timeout(4000)
            page.route('**/api/imports/ota/**', route)
            page.set_content("<base href='http://localhost/'>" + ota_payment_review.render_import_section('csrf'))
            page.locator('#ota-review > summary').click()
            item = page.locator('[data-queue-detail]').first
            item.locator('summary').click()
            item.locator('[data-load-detail]').click()
            detail = page.locator('[data-event]').first
            detail.wait_for()
            detail.locator('.ota-more > summary').click()
            text = detail.inner_text()
            assert '2026-10-05' in text
            assert '합성자연휴양림' in text and '가상실' in text
            assert '퇴실일 미확인' in text and '합성 여행' in text
            assert 'DKIM 통과 기록 없음' in text and '발신 미검증' not in text
            assert detail.locator('[data-load-reservation-candidates]').count() == 1
        finally:
            browser.close()
