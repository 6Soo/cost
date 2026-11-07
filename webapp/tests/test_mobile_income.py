from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import pytest
from webapp import google_ledger_page as google
from webapp import ledger_board
from webapp.tests import test_ledger_design_state as state
from webapp.tests.test_google_canonical_workflow import healthy_snapshot
from webapp.tests.test_google_ledger_page import rows_doc


@pytest.mark.parametrize('raw,shown', [('2026-04-06','4월6일'), ('26.04.02','4월2일'),
    ('25.12.11~26.04.06','12월11일~4월6일'), ('4/6','4월6일'),
    ('2026-02-30','2026-02-30'), ('원문 확인','원문 확인')])
def test_short_date_never_changes_unclear_original(raw, shown):
    assert google.format_transaction_date(raw) == shown


class MobileIncomeTests(state.unittest.TestCase):
    setUp = state.ViewStateTests.setUp
    tearDown = state.ViewStateTests.tearDown
    _page = state.ViewStateTests._page
    _url = state.ViewStateTests._url

    def test_names_dates_and_large_total_fit_without_side_scroll(self):
        snapshot = healthy_snapshot()
        key = snapshot['trips'][0]['key']
        rows = rows_doc()['sources']
        base = rows['main']['trips'][key]['income'][0]
        lines = [deepcopy(base) for _ in range(3)]
        lines[0]['cells'].update(B='26.04.06', C='합성 이름', D='숨길 닉네임')
        lines[1]['cells'].update(B='25.12.11~26.04.06', C=' ', D='닉네임만')
        lines[2]['cells'].update(B='26.04.02', C='아주 긴 합성 이름이 있는 신청자', D='중복닉네임')
        for i, line in enumerate(lines):
            line['row'] = 6 + i
            line['amount'] = 54840000
        rows['main']['trips'][key]['income'] = lines
        snapshot['trips'][0]['copies']['main']['income'].update(
            total=164520000, row_sum=164520000, sheet_total=164520000)
        before = deepcopy(rows)
        with patch.object(google, 'enabled', return_value=True), \
             patch.object(ledger_board, '_income_rows', return_value=[]), \
             patch.object(google, '_snapshot_path', return_value=Path(self.tmp)/'snapshot.json'), \
             patch.object(google, '_rows_path', return_value=Path(self.tmp)/'rows.json'), \
             patch.object(google.google_authority, 'load_consistent', return_value=(snapshot, rows)), \
             patch.object(google, 'snapshot_for_display', side_effect=lambda s:s), \
             patch.object(google, 'load_mapping', return_value={key:'trip-demo-a'}), \
             patch.object(google, 'load_choices', return_value={'choices':{key:'main'}}):
            page = self._page(390)
            for width in (320,390):
                with self.subTest(width=width):
                    page.set_viewport_size({'width':width,'height':900})
                    page.goto(self._url('?tab=trip-demo-a'))
                    table = page.locator('#google-trip-income table')
                    self.assertEqual(table.locator('thead th:visible').count(),3)
                    self.assertEqual(table.locator('thead th:visible svg').count(),3)
                    self.assertIn('4월6일',table.inner_text())
                    self.assertIn('12월11일~4월6일',table.inner_text())
                    self.assertEqual(table.locator('tbody .income-date').first.inner_text(),'12월11일~4월6일')
                    self.assertIn('합성 이름',table.inner_text())
                    self.assertIn('닉네임만',table.inner_text())
                    self.assertNotIn('숨길 닉네임',table.inner_text())
                    self.assertNotIn('중복닉네임',table.inner_text())
                    self.assertTrue(page.locator('#google-trip-income > summary').inner_text().startswith('수입'))
                    self.assertNotIn('수입 내역이 없어요',page.locator('main').inner_text())
                    self.assertNotIn('수입 (COST 기록)',page.locator('main').inner_text())
                    scroll = page.locator('#google-trip-income .google-income-scroll')
                    self.assertEqual(scroll.evaluate('el => getComputedStyle(el).borderTopWidth'), '0px')
                    self.assertEqual(scroll.evaluate('el => getComputedStyle(el).borderRadius'), '0px')
                    for cell in table.locator('tbody .income-date, tbody .income-person, tbody .income-total').all():
                        self.assertTrue(cell.evaluate('el => el.scrollWidth <= el.clientWidth'))
                    insurance = table.locator('tbody .participant-insurance-cell').first
                    self.assertTrue(insurance.evaluate('el => el.scrollWidth <= el.clientWidth'))
                    self.assertEqual(insurance.bounding_box()['y'], insurance.locator('..').bounding_box()['y'])
                    expense = page.locator('.lst button[data-id]').first
                    self.assertEqual(expense.evaluate('el=>getComputedStyle(el).backgroundColor'),'rgba(0, 0, 0, 0)')
                    for cell in table.locator('tbody .income-total').all():
                        self.assertEqual(cell.inner_text(),'54,840,000원')
                        self.assertTrue(cell.evaluate('el=>el.scrollWidth<=el.clientWidth'))
                        box=cell.bounding_box()
                        self.assertLessEqual(box['x']+box['width'],width)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                    captures=Path('.local-archive/mobile-income');captures.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(captures/f'income-{width}.png'),full_page=True)
            self.assertEqual(rows,before)
