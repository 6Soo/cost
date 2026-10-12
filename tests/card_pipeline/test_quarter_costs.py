from copy import deepcopy
import openpyxl
import pytest
from app import google_authority as ga, quarter_costs as qc
from app.google_tsv_adapter import tsv_for_tab


def row(**kw):
    return dict(transaction_id='syn', item='분기 기타비용', display_tab_id='unclassified',
                transaction_direction='purchase', amount_krw=12000, approval_date='2026-09-30', **kw)


def test_quarter_destination_preserves_original_and_calendar_boundary():
    original = row()
    before = deepcopy(original)
    assert qc.destination(original)['id'] == 'quarter:2026:3'
    assert qc.destination(dict(original, approval_date='2026-10-01'))['id'] == 'quarter:2026:4'
    assert qc.destination(dict(original, approval_date='2025-09-30'))['id'] == 'quarter:2025:3'
    for override in ({'item': '숙박비'}, {'display_tab_id': 'actual-trip'},
                     {'transaction_direction': 'cancellation'}, {'amount_krw': -12000}):
        assert qc.destination(dict(original, **override)) is None
    assert original == before


def test_quarter_paste_keeps_ids_holds_amount_and_duplicate_guards():
    originals = [row(), dict(row(), transaction_id='held'), dict(row(), transaction_id='other', approval_date='2026-10-01')]
    preview = [dict(r, occurred_on=r['approval_date'], merchant='Synthetic payee', blocked=None) for r in originals]
    preview[1]['blocked'] = 'user_hold'
    before = deepcopy((originals, preview))
    scoped = qc.scope(originals, preview, 'quarter:2026:3')
    result = tsv_for_tab(scoped, 'quarter:2026:3')
    assert result['row_count'] == 1 and result['total_krw'] == 12000
    assert '2026-09-30\tSynthetic payee\t분기 기타비용' in result['tsv']
    assert result['held'] == [{'transaction_id': 'held', 'reason': 'user_hold'}]
    assert tsv_for_tab(scoped + [scoped[0]], 'quarter:2026:3')['row_count'] == 0
    assert (originals, preview) == before


def quarter_sheet():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws['C2'] = '2026년 월 매출 확인자료'
    for col, label in zip('BCDEFGH', ga.EXPENSE_HEADER):
        ws[f'{col}5'] = label
    ws['B6'], ws['C6'], ws['H6'] = '2026-07-27', 'Synthetic', 12000
    ws['C8'] = '=SUM(H6:H7)'
    values = openpyxl.Workbook().active
    for cells in ws:
        for cell in cells:
            values[cell.coordinate] = cell.value
    values['C8'] = 12000
    return ws, values


def test_expense_only_quarter_checks_own_sum_and_exact_year():
    formulas, values = quarter_sheet()
    result = ga.parse_quarter_sheet(formulas, values, 3)
    assert result['kind'] == 'quarter' and result['ledger_year'] == 2026
    assert result['verified'] and result['expense']['total'] == 12000
    assert result['rows']['income'] == [] and len(result['rows']['expense']) == 1
    values['C8'] = 100
    assert not ga.parse_quarter_sheet(formulas, values, 3)['verified']
