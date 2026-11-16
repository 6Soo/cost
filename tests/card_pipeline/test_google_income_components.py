import datetime as dt

import openpyxl
import pytest

from app import google_authority as ga
from tests.card_pipeline.test_google_authority import rev_sheet


@pytest.mark.parametrize('amount,components,flag',[
    (None,[200000,None,None],'INCOME_COMPONENT_AMOUNT_MISSING'),
    (0,[200000,None,None],'INCOME_COMPONENT_TOTAL_MISMATCH'),
    (100,[50,60,None],'INCOME_COMPONENT_TOTAL_MISMATCH'),
    (100,['#REF!',None,None],'INCOME_COMPONENT_INVALID'),
])
def test_income_components_cannot_disappear_behind_blank_date_or_matching_total(amount,components,flag):
    wb=openpyxl.Workbook();ws=rev_sheet(wb,'0712_SYNTHETIC',[amount],[30])
    ws['B6']=None
    for col,value in zip('EFG',components):ws[f'{col}6']=value
    result=ga.parse_trip_sheet(ws,ws)
    assert flag in result['flags']
    assert result['income']['total'] is None and result['net'] is None
    assert not result['verified']
    assert ws['H6'].value==amount  # source cells are never repaired in memory


def test_exact_components_and_direct_amount_without_components_remain_supported():
    wb=openpyxl.Workbook();ws=rev_sheet(wb,'0712_SYNTHETIC',[100,50],[30])
    ws['E6'],ws['F6'],ws['G6']=20,90,-10
    flags=set();rows=[]
    total,count,*_=ga._sum_block(6,7,ws,ws,flags,rows,[])
    assert (total,count,flags)==(150,2,set())
