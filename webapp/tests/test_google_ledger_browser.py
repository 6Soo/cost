import datetime as dt
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import openpyxl
from playwright.sync_api import sync_playwright

from app import google_authority as ga
from webapp import google_ledger_page as page
from webapp import ledger_board

INCOME = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=ga.KST)


def workbook(title, income, expense):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(title)
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    ws["B6"], ws["C6"], ws["D6"], ws["H6"] = dt.date(2027, 2, 6), income[0], income[1], income[2]
    ws["C8"] = "=sum(H6:H6)"
    ws["B10"] = "지출 내용"
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}11"] = label
    ws["B12"], ws["C12"], ws["D12"], ws["E12"], ws["F12"], ws["G12"], ws["H12"] = (
        dt.date(2027, 2, 7), expense[0], expense[1], "2027-02-07", "RESV-9", "카드", expense[2])
    ws["C13"] = "=SUM(H12:H12)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class GoogleLedgerBrowserTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.snapshot = root / 'google-snapshot.json'
        self.rows = root / 'google-rows-private.json'
        main = workbook("0630_오제", ("ALICE-NAME", "ALI", 900000), ("PAYEE-SHOP", "식비", 120000))
        archive = workbook("0107_대만의 사본", ("BOB-NAME", "BOB", 300000), ("SHOP-B", "교통비", 50000))
        self.good = {"main": main, "archive": archive}
        ga.sync(self.snapshot, self.rows, fetcher=self.fetcher(self.good), now=NOW)
        self._env = patch.dict(os.environ, {'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.snapshot),
                                            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(self.rows),
                                            'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1'})
        self._env.start()
        self._previous = ledger_board._STORE
        ledger_board.bind_access(None)
        self.server = ledger_board.serve(port=0, db_path=root / 'board.sqlite', with_worker=False,
                                         seed_demo=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.card_store.close()
        self.thread.join(timeout=3)
        ledger_board.bind_store(self._previous)
        self._env.stop()
        self._dir.cleanup()

    @staticmethod
    def fetcher(books):
        def fetch(url):
            for role, sheet_id in ga.SPREADSHEET_IDS.items():
                if sheet_id in url:
                    if isinstance(books[role], Exception):
                        raise books[role]
                    return books[role]
            raise AssertionError(url)
        return fetch

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + urllib.parse.quote(path, safe='/?=&%_')) as response:
                return response.status, response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')

    def test_direct_urls_are_refused_without_an_owner_session(self):
        for path in ('/google-ledger', '/api/google-ledger', '/google-ledger/rows?key=0630_오제&source=main'):
            status, body = self.get(path)
            self.assertEqual(status, 403, path)
            self.assertNotIn('ALICE', body)

    def test_owner_list_and_detail_pages_in_chromium_at_both_widths(self):
        owner = patch.object(page, 'caller', return_value=(True, 'boss'))
        with owner, sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            for width, height in ((390, 844), (1440, 900)):
                pg = browser.new_context(viewport={'width': width, 'height': height}).new_page()
                pg.goto(self.base + '/google-ledger')
                pg.get_by_text('0630_오제').wait_for()
                pg.get_by_role('link', name='main 상세').first.click()
                pg.get_by_role('heading', name='수입').wait_for()
                body = pg.content()
                self.assertIn('<th>이름</th><th>닉네임</th><th>예약금</th>', body)
                self.assertIn('<th>지급처</th><th>분류</th><th>기간</th><th>예약번호</th><th>증빙</th>', body)
                self.assertIn('ALICE-NAME', body)
                self.assertEqual(pg.evaluate('document.documentElement.scrollWidth - innerWidth'), 0)
                pg.close()
            browser.close()

    def test_sync_failure_keeps_the_last_good_view_and_says_so(self):
        owner = patch.object(page, 'caller', return_value=(True, 'boss'))
        with owner:
            failing = {"main": ga.SourceError("SOURCE_UNREACHABLE"), "archive": self.good["archive"]}
            ga.sync(self.snapshot, self.rows, fetcher=self.fetcher(failing), now=NOW)
            status, body = self.get('/google-ledger')
            self.assertEqual(status, 200)
            self.assertIn('0630_오제', body)
            self.assertIn('SOURCE_UNREACHABLE', body)
            self.assertIn('마지막 정상', body)
            status, detail = self.get('/google-ledger/rows?key=0630_%EC%98%A4%EC%A0%9C&source=main')
            self.assertEqual(status, 200)
            self.assertIn('ALICE-NAME', detail)

    def test_revoked_grant_leaves_the_viewer_without_the_trip_in_the_browser(self):
        page.set_mapping(self.snapshot, key='0630_오제', tab_id='tab-A', known_keys={'0630_오제'})
        page.set_grants(self.snapshot, user_id='viewer-1', keys=['0630_오제'], granted=True, at='t')
        visible = type('Access', (), {'visible_tabs': staticmethod(lambda user_id, now=None: {'tab-A'})})
        with patch.object(page, 'caller', return_value=(False, 'viewer-1')), \
                patch.object(ledger_board, '_ACCESS', visible()), sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            pg = browser.new_context(viewport={'width': 390, 'height': 844}).new_page()
            pg.goto(self.base + '/google-ledger')
            pg.get_by_text('0630_오제').wait_for()
            self.assertNotIn('main 상세', pg.content())
            page.set_grants(self.snapshot, user_id='viewer-1', keys=['0630_오제'], granted=False, at='t2')
            pg.goto(self.base + '/google-ledger')
            pg.wait_for_load_state()
            self.assertNotIn('0630_오제', pg.content())
            browser.close()
