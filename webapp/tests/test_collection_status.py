"""수집 상태 판이 기존 기록만 읽는지 확인한다.

합성 자료로 원천별 표시, 기준 초과 경고, 없는 기록 처리, 로그인 실패 기록,
P2 실행 기록, 판정 없는 정상 거래 수, 그리고 비로그인 접근 차지를 검사한다.
운영 자료나 고객 원문은 쓰지 않는다.
"""
import datetime as dt
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app import google_authority
from app.ota_store import OtaStore
from app.reserve_trips import KST
from webapp import collection_status
from webapp.card_flow import CardFlow, home_page
from webapp.collection_status import THRESHOLDS_DAYS, evaluate, gather, render_html
from webapp.ledger_store import LedgerStore
from webapp.tests.test_uiux_copy import CASUAL_ENDINGS, FORBIDDEN

NOW = dt.datetime(2026, 11, 13, 12, 0, tzinfo=KST)

CARD = ('Issuer,Card No,Card Type,Type,Merchant,Amount,Foreign Amount,Currency,Amount KRW,'
        'Date,Post Date,Authorization Code,Cancel,Status\n'
        '국민,1234,domestic,purchase,합성상점,37000,,,37000,2026-10-01,2026-10-02,A123,,매입\n').encode()


def _record(days_ago, threshold, login=False):
    last = NOW - dt.timedelta(days=days_ago) if days_ago is not None else None
    return {'label': '합성 원천', 'last_at': last, 'threshold': threshold, 'login_required': login}


def _assert_clean(markup):
    assert not any(word in markup for word in FORBIDDEN), markup
    assert not CASUAL_ENDINGS.search(markup), markup


def _collection_block(html):
    """전체 화면에서 수집 상태 판만 잘라 낸다. 바깥 껍데기 문구는 검사하지 않는다."""
    start = html.index("<div class='home-collection'")
    end = html.index('</div>', start) + len('</div>')
    return html[start:end]


class EvaluateTests(unittest.TestCase):
    def test_thresholds_are_constants_in_one_table(self):
        self.assertEqual(THRESHOLDS_DAYS, {'card': 7, 'mail': 1, 'ota': 30, 'google': 1})

    def test_within_and_over_threshold(self):
        self.assertEqual(evaluate(_record(7, 7), NOW)['status'], '정상')
        self.assertEqual(evaluate(_record(8, 7), NOW)['status'], '경고')
        self.assertEqual(evaluate(_record(1, 1), NOW)['status'], '정상')
        self.assertEqual(evaluate(_record(2, 1), NOW)['status'], '경고')
        self.assertEqual(evaluate(_record(30, 30), NOW)['status'], '정상')
        self.assertEqual(evaluate(_record(31, 30), NOW)['status'], '경고')

    def test_days_ago_and_today(self):
        self.assertEqual(evaluate(_record(0, 7), NOW)['days_ago'], 0)
        self.assertEqual(evaluate(_record(13, 7), NOW)['days_ago'], 13)
        self.assertIn('오늘', render_html({'now': NOW, 'sources': [_record(0, 7)],
                                          'p2': None, 'normal_undecided': 0}))

    def test_no_record_is_not_invented(self):
        state = evaluate(_record(None, 7), NOW)
        self.assertEqual(state['status'], '기록 없음')
        self.assertIsNone(state['days_ago'])

    def test_login_failure_record_wins_over_freshness(self):
        self.assertEqual(evaluate(_record(0, 1, login=True), NOW)['status'], '로그인 필요')
        self.assertEqual(evaluate(_record(40, 1, login=True), NOW)['status'], '로그인 필요')

    def test_render_lists_every_source_and_threshold(self):
        data = gather(SimpleNamespace(conn=SimpleNamespace(
            execute=lambda *_a: SimpleNamespace(fetchone=lambda: (0, 0), fetchall=lambda: []))), now=NOW)
        markup = render_html(data)
        for label in ('국민카드', '하나카드', '기업카드', 'Gmail 메일', 'Agoda', 'Trip.com',
                      'Booking.com', '숲나들e', '산림치유원', 'Google 수입'):
            self.assertIn(label, markup)
        for days in THRESHOLDS_DAYS.values():
            self.assertIn(f'{days}일', markup)
        self.assertIn('기록 없음', markup)
        self.assertIn('판정 없는 정상 거래', markup)
        _assert_clean(markup)


class GatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.board = LedgerStore(self.data / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)
        self.env = patch.dict(os.environ, {
            'WEBLEDGER_UNIFIED_DB': '1',
            'WEBLEDGER_OTA_SOURCES': '',
            'WEBLEDGER_AGODA_PORTAL_DB': '',
            'WEBLEDGER_OTA_MAIL_DIR': str(self.data / 'ota-mail'),
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.root / 'google-snapshot.json'),
        })
        self.env.start()
        (self.data / 'ota-mail').mkdir()
        self._write_google({})
        store = OtaStore(self.data / 'ota-evidence.sqlite')
        store.close()
        (self.data / 'ota-sources.json').write_text(json.dumps({
            'schema_version': 'ota-sources-v1',
            'unified_database': str(self.data / 'ota-evidence.sqlite')}), encoding='utf-8')

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def _write_mail(self, last_run):
        (self.data / 'ota-mail' / 'collection.json').write_text(
            json.dumps({'last_run': last_run}), encoding='utf-8')

    def _write_google(self, sources):
        (self.root / 'google-snapshot.json').write_text(json.dumps({
            'schema': google_authority.SCHEMA, 'sources': sources, 'trips': []}), encoding='utf-8')

    def _import_ota(self, provider, booking_number):
        store = OtaStore(self.data / 'ota-evidence.sqlite')
        try:
            store.import_direct(provider=provider, account_key='합성계정', source_key='합성출처',
                                snapshot={'text': '합성 예약'},
                                facts=[{'provider': provider, 'booking_number': booking_number}])
        finally:
            store.close()

    def _age_ota(self, observed_at):
        import sqlite3
        with sqlite3.connect(self.data / 'ota-evidence.sqlite') as conn:
            conn.execute('UPDATE ota_source_revisions SET observed_at=?', (observed_at,))

    def _write_p2(self, summary):
        archive = self.root / 'archive'
        run = archive / 'p2-batch-synthetic'
        run.mkdir(parents=True)
        (run / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        config = self.root / 'config'
        config.mkdir()
        (config / 'card-flow.json').write_text(
            json.dumps({'p2_batch_archive': str(archive)}), encoding='utf-8-sig')

    def _labels(self, data):
        return {record['label']: record for record in data['sources']}

    def test_empty_environment_reports_no_record_everywhere(self):
        data = gather(self.board, now=NOW)
        for record in data['sources']:
            self.assertIsNone(record['last_at'], record['label'])
            self.assertFalse(record['login_required'])
        self.assertIsNone(data['p2'])
        self.assertEqual(data['normal_undecided'], 0)
        _assert_clean(render_html(data))

    def test_fixed_data_root_p2_summary_precedes_legacy_archive(self):
        root = self.data
        latest = root / 'p2-runs' / 'latest.json'
        latest.parent.mkdir(parents=True)
        latest.write_text(json.dumps({'schema': 1, 'finished_at': '2026-11-13T02:30:00+00:00',
            'target_groups': 4, 'successful_calls': 2, 'failed_calls': 1}), encoding='utf-8')
        self._write_p2({'merchants': 99, 'successful_calls': 88, 'failed_attempts': 77})
        status = collection_status._p2_status(root, self.root / 'config' / 'card-flow.json')
        self.assertEqual(status['merchants'], 4)
        self.assertEqual(status['success'], 2)
        self.assertEqual(status['failed'], 1)

    def test_card_last_collection_per_issuer_and_warning(self):
        self.flow.pipeline.receive(CARD, '합성.csv')
        data = gather(self.board, now=NOW)
        self.assertIsNotNone(self._labels(data)['국민카드']['last_at'])
        self.assertIsNone(self._labels(data)['하나카드']['last_at'])
        self.assertEqual(evaluate(self._labels(data)['국민카드'], NOW)['status'], '정상')
        with self.board._lock:
            self.board.conn.execute("UPDATE import_batches SET received_at='2026-10-01T00:00:00+00:00'")
            self.board.conn.commit()
        aged = self._labels(gather(self.board, now=NOW))['국민카드']
        self.assertEqual(evaluate(aged, NOW)['status'], '경고')

    def test_mail_last_run_and_daily_warning(self):
        self._write_mail('2026-11-13T01:14:42')
        data = gather(self.board, now=NOW)
        self.assertEqual(evaluate(self._labels(data)['Gmail 메일'], NOW)['status'], '정상')
        self._write_mail('2026-11-10T01:14:42')
        data = gather(self.board, now=NOW)
        self.assertEqual(evaluate(self._labels(data)['Gmail 메일'], NOW)['status'], '경고')

    def test_ota_providers_including_forest_split(self):
        self._import_ota('agoda', 'AG-1')
        self._import_ota('trip', 'TR-1')
        self._import_ota('forest', 'foresttrip:FT-1')
        self._import_ota('forest', 'sooperang:SP-1')
        labels = self._labels(gather(self.board, now=NOW))
        for name in ('Agoda', 'Trip.com', '숲나들e', '산림치유원'):
            self.assertIsNotNone(labels[name]['last_at'], name)
            self.assertEqual(evaluate(labels[name], NOW)['status'], '정상')
        self.assertIsNone(labels['Booking.com']['last_at'])
        self.assertEqual(evaluate(labels['Booking.com'], NOW)['status'], '기록 없음')

    def test_ota_old_import_warns_after_thirty_days(self):
        self._import_ota('agoda', 'AG-1')
        self._age_ota('2026-09-01T00:00:00+00:00')
        labels = self._labels(gather(self.board, now=NOW))
        self.assertEqual(evaluate(labels['Agoda'], NOW)['status'], '경고')

    def test_google_login_failure_record_shows_login_needed(self):
        self._write_google({'main': {'status': 'error', 'error_code': 'GOOGLE_AUTH_UNAVAILABLE',
                                     'last_ok_at': '2026-11-12T01:14:50+09:00', 'stale': True}})
        record = self._labels(gather(self.board, now=NOW))['Google 수입']
        self.assertTrue(record['login_required'])
        self.assertEqual(evaluate(record, NOW)['status'], '로그인 필요')

    def test_google_ok_uses_oldest_success_and_no_login_flag(self):
        self._write_google({
            'main': {'status': 'ok', 'error_code': None, 'last_ok_at': '2026-11-13T01:14:50+09:00'},
            'archive': {'status': 'ok', 'error_code': None, 'last_ok_at': '2026-11-11T01:14:50+09:00'}})
        record = self._labels(gather(self.board, now=NOW))['Google 수입']
        self.assertFalse(record['login_required'])
        self.assertEqual(record['last_at'].date().isoformat(), '2026-11-11')
        self.assertEqual(evaluate(record, NOW)['status'], '경고')

    def test_p2_summary_counts_and_missing_record(self):
        self.assertIsNone(gather(self.board, now=NOW)['p2'])
        self._write_p2({'merchants': 585, 'successful_calls': 13, 'failed_attempts': 2})
        p2 = gather(self.board, now=NOW)['p2']
        self.assertEqual((p2['merchants'], p2['success'], p2['failed']), (585, 13, 2))
        markup = render_html(gather(self.board, now=NOW))
        self.assertIn('대상 585곳', markup)
        self.assertIn('성공 13', markup)
        self.assertIn('실패 2', markup)
        _assert_clean(markup)

    def test_normal_undecided_counts_only_undecided_normal_purchases(self):
        self.flow.pipeline.receive(CARD, '합성.csv')
        self.assertEqual(gather(self.board, now=NOW)['normal_undecided'], 1)
        row = self.board.conn.execute('SELECT transaction_id FROM transactions').fetchone()
        with self.board._lock:
            self.board.conn.execute(
                "UPDATE transactions SET classification_state='classified', item='숙박비', "
                "trip_id='trip-x', display_tab_id='trip-x' WHERE transaction_id=?", (row[0],))
            self.board.conn.commit()
        self.assertEqual(gather(self.board, now=NOW)['normal_undecided'], 0)

    def test_gather_uses_sixty_second_cache(self):
        collection_status._cache_clear()
        calls = []
        real_card_last = collection_status._card_last

        def counting_card_last(board):
            calls.append(1)
            return real_card_last(board)

        clock = [1000.0]
        with patch.object(collection_status, '_card_last', side_effect=counting_card_last), \
                patch.object(collection_status.time, 'monotonic', side_effect=lambda: clock[0]):
            first = gather(self.board)
            self.assertEqual(len(calls), 1)
            second = gather(self.board)
            self.assertIs(second, first)
            self.assertEqual(len(calls), 1)
            clock[0] += collection_status._CACHE_TTL_SECONDS + 1.0
            third = gather(self.board)
            self.assertIsNot(third, first)
            self.assertEqual(len(calls), 2)
        collection_status._cache_clear()


class HomeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.board = LedgerStore(self.data / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)
        self.env = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_OTA_SOURCES': '',
                                           'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': ''})
        self.env.start()

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_home_renders_collection_block_inside_status_area(self):
        from webapp import ledger_board
        previous = ledger_board._STORE
        try:
            ledger_board.bind_store(self.board)
            html = home_page(self.board)
        finally:
            ledger_board.bind_store(previous)
        self.assertIn("aria-label='자료 상태'", html)
        self.assertIn("aria-label='수집 상태'", html)
        self.assertIn('국민카드', html)
        self.assertIn('판정 없는 정상 거래', html)
        self.assertIn('기록 없음', html)
        _assert_clean(_collection_block(html))


class GracefulDegradationTests(unittest.TestCase):
    def test_fake_board_without_path_renders_no_record(self):
        board = SimpleNamespace(
            conn=SimpleNamespace(execute=lambda *_a: SimpleNamespace(
                fetchone=lambda: (0, 0), fetchall=lambda: [])),
            _lock=type('Lock', (), {'__enter__': lambda self: self,
                                    '__exit__': lambda self, *_a: False})(),
            list_trips=lambda: [], visible_row_count=lambda: 0,
            trip_management_summaries=lambda: {})
        with patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': ''}):
            data = gather(board, now=NOW)
        for record in data['sources']:
            self.assertIsNone(record['last_at'])
        self.assertIsNone(data['p2'])
        markup = render_html(data)
        self.assertIn('기록 없음', markup)
        _assert_clean(markup)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AuthHttpTests(unittest.TestCase):
    SECRET = 'k7Qm2Zx9Tb4Nq8Vr3Ls6Wy1Pd5Gj0Hf7Ce2Ui4Ok8Mn1'
    CLIENT_ID = 'synthetic-client.apps.googleusercontent.com'
    OWNER = 'synthetic-owner-sub'

    def setUp(self):
        from webapp import access_control, google_oidc, ledger_board as board
        self.board_module = board
        self.previous = (board._STORE, board._ACCESS, board._OIDC, access_control.session_adapter())
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.store = LedgerStore(str(self.root / 'board.sqlite'))
        self.access = access_control.attach_to_ledger_store(self.store)
        self.access.ensure_schema()
        self.access.ensure_owner(self.OWNER)
        self.snapshot = self.root / 'google-snapshot.json'
        self.snapshot.write_text(json.dumps({'schema': google_authority.SCHEMA,
                                             'sources': {}, 'trips': []}), encoding='utf-8')
        self.env = patch.dict(os.environ, {
            'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1',
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.snapshot)})
        self.env.start()

        class FakeVerifier(google_oidc.GoogleAuthTokenVerifier):
            def __init__(self):
                super().__init__(client_id=AuthHttpTests.CLIENT_ID)
                self.claims = {}
                self._idinfo_loader = lambda token: dict(self.claims)

        class FakeExchange:
            def __call__(self, **kwargs):
                return {'id_token': 'synthetic-id-token', 'access_token': 'discarded'}

        cfg = google_oidc.OIDCConfig.from_env({
            google_oidc.ENV_CLIENT_ID: self.CLIENT_ID,
            google_oidc.ENV_CLIENT_SECRET: 'synthetic-client-secret',
            google_oidc.ENV_SESSION_SECRET: self.SECRET,
            google_oidc.ENV_PUBLIC_BASE_URL: 'https://ledger.synthetic.test',
            google_oidc.ENV_OWNER_SUB: self.OWNER})
        self.oidc_module = google_oidc
        self.flow = google_oidc.connect_oidc(cfg, self.access,
                                             verifier=FakeVerifier(), exchange=FakeExchange())
        board.bind_store(self.store)
        board.bind_access(self.access)
        board.bind_oidc(self.flow)
        self.server = board.serve(port=0, db_path=self.root / 'http-board.sqlite',
                                  with_worker=False, seed_demo=False)
        CardFlow(self.server.card_store)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = build_opener(NoRedirect)

    def tearDown(self):
        from webapp import access_control
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server.card_store.close()
        old_store, old_access, old_oidc, old_adapter = self.previous
        self.board_module.bind_store(old_store)
        self.board_module.bind_access(old_access)
        self.board_module.bind_oidc(old_oidc)
        access_control.bind_sessions(old_adapter)
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def _request(self, path, cookie=None):
        headers = {}
        if cookie:
            headers['Cookie'] = f'{self.oidc_module.COOKIE_NAME}={cookie}'
        request = Request(f'http://127.0.0.1:{self.port}{path}', headers=headers)
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        return response.code, response.read().decode('utf-8')

    def _owner_cookie(self):
        account = self.access.account(self.OWNER)
        identity = {'sub': self.OWNER, 'name': self.OWNER, 'email': f'{self.OWNER}@synthetic.test'}
        return self.flow.adapter.issue_cookie(identity, generation=account['session_generation'])

    def test_home_still_requires_login_and_owner_sees_the_panel(self):
        code, body = self._request('/')
        self.assertEqual(code, 401)
        self.assertNotIn('수집 상태', body)
        code, body = self._request('/', cookie=self._owner_cookie())
        self.assertEqual(code, 200)
        self.assertIn("aria-label='수집 상태'", body)
        self.assertIn('기록 없음', body)
        _assert_clean(_collection_block(body))


if __name__ == '__main__':
    unittest.main()
