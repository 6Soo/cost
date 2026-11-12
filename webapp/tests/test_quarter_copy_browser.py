import datetime as dt
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from app import google_authority as ga
from tests.card_pipeline.fixtures import make_csv, domestic_row
from webapp import ledger_board as board, google_ledger_page as google
from webapp.card_flow import CardFlow
from webapp.tests.test_google_canonical_workflow import healthy_snapshot


class QuarterCopyBrowserTests(unittest.TestCase):
    def test_matching_quarter_copy_and_missing_next_quarter_without_booking(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            snapshot=healthy_snapshot()
            stamp=dt.datetime.now(ga.KST).isoformat()
            snapshot['synced_at']=stamp
            for source in snapshot['sources'].values():
                source.update(last_ok_at=stamp,checked_at=stamp)
            quarter=snapshot['trips'][0]
            quarter.update(key='3분기_기타비용',kind='quarter',quarter=3,ledger_year=2026)
            quarter['copies']['archive']=None
            quarter['copies']['main'].update(sheet='3분기_기타비용',kind='quarter',ledger_year=2026)
            (root/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
            with patch.dict(os.environ,{'WEBLEDGER_UNIFIED_DB':'1','WEBLEDGER_CARD_FLOW':'1',
                    'WEBLEDGER_REVIEW_FROM':'','WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT':str(root/'snapshot.json'),
                    'WEBLEDGER_GOOGLE_LEDGER_ROWS':str(root/'rows.json')}):
                previous=board._STORE;board.bind_access(None)
                server=board.serve(port=0,db_path=root/'board.sqlite',with_worker=False,seed_demo=False)
                flow=CardFlow(server.card_store)
                batch=flow.pipeline.receive(make_csv([
                    domestic_row(merchant='Synthetic quarter payee',amount=12000,approval='Q1',date='2026-09-30'),
                    domestic_row(merchant='Synthetic next quarter',amount=9000,approval='Q2',date='2026-10-01')]),'quarter.csv')['batch_id']
                for row in flow.pipeline.get_batch(batch)['rows']:
                    flow.pipeline.save_decision(row['transaction_id'],row['revision'],item='분기 기타비용',
                        display_tab_id='unclassified',tab_validator=flow.tab_valid,request_id='quarter-'+row['transaction_id'])
                originals=flow.pipeline.get_batch(batch)['rows']
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with sync_playwright() as api:
                        browser=api.chromium.launch()
                        context=browser.new_context(viewport={'width':390,'height':900},permissions=['clipboard-read','clipboard-write'])
                        page=context.new_page();base=f'http://127.0.0.1:{server.server_address[1]}'
                        # wave3 #799: 옛 검토 화면은 /import?batch&transaction 딥링크에서만 서빙된다.
                        first_row=flow.pipeline.get_batch(batch)['rows'][0]['transaction_id']
                        page.goto(base+'/import?batch='+batch+'&transaction='+first_row)
                        button=page.locator('[data-google-copy="quarter:2026:3"]');button.wait_for()
                        self.assertEqual(page.locator('[data-google-copy="quarter:2026:4"]').count(),0)
                        self.assertIn('2026년 4분기 기타비용',page.locator('.quarter-copy').last.inner_text())
                        denied=page.request.get(base+'/api/imports/'+batch+'/google-tsv?tab=quarter:2026:4')
                        self.assertEqual(denied.status,400)
                        # 4f1de321: 분기 복사 버튼 핸들러는 폐지됐다. 7열 TSV는 라이브 내보내기 API로 검증한다.
                        exported=page.request.get(base+'/api/imports/'+batch+'/google-tsv?tab=quarter:2026:3').json()
                        self.assertEqual(exported['row_count'],1)
                        text=exported['tsv']
                        self.assertEqual(len(text.splitlines()),1)
                        self.assertEqual(text.strip().split('\t')[-1],'12000')
                        self.assertEqual(len(text.strip().split('\t')),7)
                        self.assertNotIn('9000',text)
                        self.assertEqual(page.request.get(base+'/api/imports/'+batch+'/google-tsv?tab=unclassified').json()['row_count'],0)
                        self.assertEqual(server.card_store.conn.execute('SELECT COUNT(*) FROM board_rows').fetchone()[0],0)
                        self.assertEqual(flow.pipeline.get_batch(batch)['rows'],originals)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                        context.close();browser.close()
                finally:
                    server.shutdown();server.server_close();server.card_store.close()
                    thread.join(timeout=3);board.bind_store(previous)
