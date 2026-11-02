"""입력 → 검토·규칙 → 출력 한 사이클을 실제 브라우저와 HTTP로 검증한다. 합성 자료만 쓴다."""
import csv
import io
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

from webapp import ledger_board
from webapp.card_flow import CardFlow

DATA = Path(__file__).resolve().parents[2] / "tests" / "card_pipeline" / "data"
KB_HEADERS = ['매입일', '승인일', '승인시간', '부서번호', '부서명', '카드번호', '이용자명', '가맹점명', '업종명',
              '결제방법', '할부개월수', '승인금액', '부가세', '승인구분', '승인방식', '승인번호', '상태', '과세유형',
              '가맹점상태', '가맹점번호', '가맹점사업자등록번호', '대표자성명', '가맹점주소', '가맹점전화번호']


def kb_row(merchant, amount, approval, day="2026.10.07"):
    return [day, day, '12:00:00', "'00002", '합성 주식회사', '5585-26**-****-3820', '김*형', merchant, '편의점',
            '일시불', '0', str(amount), '0', '국내', 'IC', approval, '정상', '과세', '정상', '1', '1', '홍', '서울', '02']


def kb_csv(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(KB_HEADERS)
    writer.writerows(rows)
    return ("﻿" + buffer.getvalue()).encode("utf-8")


class LedgerWorkflowBrowserTests(unittest.TestCase):
    def test_upload_review_rule_export_cycle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'WEBLEDGER_UNIFIED_DB': '1', 'WEBLEDGER_CARD_FLOW': '1', 'WEBLEDGER_REVIEW_FROM': ''}):
            previous = ledger_board._STORE
            ledger_board.bind_access(None)
            server = ledger_board.serve(port=0, db_path=Path(directory) / 'board.sqlite',
                                        with_worker=False, seed_demo=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            store = server.card_store
            base = f'http://127.0.0.1:{server.server_address[1]}'
            csv_path = Path(directory) / 'new-card.csv'
            csv_path.write_bytes(kb_csv([kb_row('합성다른상점', 12000, '81000001'),
                                         kb_row('합성다른상점', 8000, '81000002', "2026.10.08")]))
            valid_trip = patch.object(CardFlow, 'trip_valid', side_effect=lambda _flow, identity: identity == tab, autospec=True)
            valid_trip.start()
            try:
                with sync_playwright() as api:
                    browser = api.chromium.launch(headless=True)
                    context = browser.new_context(viewport={'width': 1440, 'height': 900})
                    page = context.new_page()

                    trip = store.create_trip(starts_on='2026-10-05', ends_on='2026-10-09', destination='Synthetic',
                                             display_key='1005_Synthetic', client_request_id='trip-1')
                    tab = trip['tab_id'] if 'tab_id' in trip else trip['trip']['tab_id']

                    # STAGE 1: a real binary .xls goes through the same upload screen
                    page.goto(base + '/import#newupload')
                    page.evaluate("document.getElementById('newupload').open = true")
                    page.set_input_files('#file', str(DATA / 'kb-domestic-acquired-synthetic.xls'))
                    page.get_by_role('button', name='카드 사용내역 업로드하고 분류').click()
                    page.wait_for_load_state('networkidle')
                    page.locator('#upload-results a').first.wait_for(timeout=15000)
                    xls_rows = store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
                    self.assertEqual(xls_rows, 3)
                    # the same file again changes nothing
                    page.reload()
                    page.evaluate("document.getElementById('newupload').open = true")
                    page.set_input_files('#file', str(DATA / 'kb-domestic-acquired-synthetic.xls'))
                    page.get_by_role('button', name='카드 사용내역 업로드하고 분류').click()
                    page.wait_for_load_state('networkidle')
                    page.locator('#upload-results a').first.wait_for(timeout=15000)
                    self.assertEqual(store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0], 3)
                    self.assertEqual(store.conn.execute('SELECT COUNT(*) FROM import_batches').fetchone()[0], 1)

                    # new statement as CSV, then record it from the preview
                    page.reload()
                    page.evaluate("document.getElementById('newupload').open = true")
                    page.set_input_files('#file', str(csv_path))
                    page.get_by_role('button', name='카드 사용내역 업로드하고 분류').click()
                    page.wait_for_load_state('networkidle')
                    page.locator('#upload-results a').first.wait_for(timeout=15000)
                    upload_href = page.locator('#upload-results a').first.get_attribute('href')
                    page.locator('[data-review-state="all"]').click()
                    for index in range(2):
                        page.locator('#preview [data-edit]').nth(index).click()
                        form = page.locator('#questions form[data-index]').first
                        form.locator('select[name=display_tab_id]').select_option(tab)
                        form.locator('input[name=item]').fill('Initial item')
                        with page.expect_response('**/decision') as decision:
                            form.locator('button').click()
                        self.assertEqual(decision.value.status, 200)
                        page.wait_for_url('**/rules?case=*')
                        page.goto(base + upload_href)
                        page.locator('[data-review-state="all"]').click()
                    rows = store.conn.execute(
                        "SELECT row_id, payload_json FROM board_rows WHERE row_kind='expense' ORDER BY row_id"
                    ).fetchall()
                    import json
                    booked = [(rid, json.loads(pj)) for rid, pj in rows
                              if json.loads(pj).get('source_approval_number') in {'81000001', '81000002'} and json.loads(pj).get('source_merchant') == '합성다른상점']
                    self.assertEqual(sorted(d['amount_krw'] for _, d in booked), [8000, 12000])
                    self.assertEqual({d['display_tab_id'] for _, d in booked}, {tab})
                    total_before = sum(d['amount_krw'] for _, d in booked)

                    # STAGE 2: correct one row and learn the rule for the other
                    first, second = booked[0][0], booked[1][0]
                    page.goto(f'{base}/board?tab={tab}&row={first}')
                    panel = page.locator('aside.panel')
                    panel.locator('input[name=item]').fill('소모품비')
                    panel.locator('select[name=change_mode]').select_option('rule_change')
                    panel.get_by_role('button', name=re.compile('저장')).click()
                    page.get_by_text('규칙 대화 열기').first.wait_for(timeout=15000)
                    other_before = store.get_row(second)['item']
                    self.assertNotEqual(other_before, '소모품비')
                    page.get_by_text('규칙 대화 열기').first.click()
                    page.get_by_role('button', name=re.compile('내 수정 내용으로 규칙 초안')).click()
                    page.get_by_text('적용 조건').wait_for(timeout=15000)
                    text = re.sub(r'\s+', ' ', page.inner_text('body'))
                    self.assertIn('가맹점 = 합성다른상점', text)
                    self.assertIn('모든 여행·모든 카드', text)
                    # a draft has not touched the other row
                    self.assertEqual(store.get_row(second)['item'], other_before)
                    page.locator('input[name=apply_existing]').set_checked(True)
                    page.locator('input[name=apply_future]').set_checked(False)
                    page.get_by_role('button', name=re.compile('영향 미리보기')).click()
                    page.get_by_role('button', name=re.compile('이 범위로 적용')).click()
                    page.get_by_text('적용했습니다', exact=False).wait_for(timeout=15000)
                    self.assertEqual(store.get_row(second)['item'], '소모품비')
                    self.assertEqual(store.active_future_rules(), [])

                    # the board shows it without a restart
                    page.goto(f'{base}/board?tab={tab}')
                    self.assertGreaterEqual(page.locator('table tr', has_text='소모품비').count(), 2)

                    # STAGE 3: export the trip and read the workbook
                    page.goto(f'{base}/export?tab={tab}')
                    for box in page.locator('input[name=tab_ids]').all():
                        box.set_checked(box.get_attribute('value') == tab)
                    with page.expect_response(lambda r: '/api/exports/xlsx' in r.url
                                              and r.request.method == 'POST') as posted:
                        page.get_by_role('button', name='출력').click()
                    self.assertEqual(posted.value.status, 303)
                    href = posted.value.headers['location']
                    self.assertRegex(href, r'^/api/exports/xlsx-[0-9a-f]+/download$')
                    response = page.request.get(base + href)
                    self.assertEqual(response.status, 200)
                    target = Path(directory) / 'out.xlsx'
                    target.write_bytes(response.body())
                    browser.close()
                workbook = load_workbook(target, data_only=True)
                self.assertEqual(workbook.sheetnames, ['1005_Synthetic'])
                cells = [value for row in workbook['1005_Synthetic'].iter_rows(values_only=True) for value in row
                         if value is not None]
                self.assertEqual(sum(1 for value in cells if value == '소모품비'), 2)
                amounts = sorted(value for value in cells if isinstance(value, (int, float)) and value in (8000, 12000))
                self.assertEqual(amounts, [8000, 12000])
                total_after = sum(json.loads(pj)['amount_krw'] for _, pj in store.conn.execute(
                    "SELECT row_id, payload_json FROM board_rows WHERE row_kind='expense'")
                    if json.loads(pj).get('source_approval_number') in {'81000001', '81000002'} and json.loads(pj).get('source_merchant') == '합성다른상점')
                self.assertEqual(total_after, total_before)
            finally:
                valid_trip.stop()
                server.shutdown()
                server.server_close()
                store.close()
                thread.join(timeout=3)
                ledger_board.bind_store(previous)


if __name__ == '__main__':
    unittest.main()
