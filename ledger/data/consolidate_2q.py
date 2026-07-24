# -*- coding: utf-8 -*-
"""2분기 통합: 4월(rev v5) 6탭 + 5·6월(rev v1) 7탭 + 2분기_기타비용(장부) → 단일 워크북.
   각 시트를 값+서식(폰트·배경·테두리·정렬·번호형식)·병합·행높이·열폭 그대로 셀단위 복제."""
import openpyxl
from copy import copy

OUT='매출확인자료_2분기_통합_v5.xlsx'
SRC=[('매출확인자료_4월_rev_v8.xlsx', None),           # None=전 시트
     ('매출확인자료_5-6월_rev_v5.xlsx', None)]
LEDGER=('ledger_latest.xlsx', ['2분기_기타비용'])

def copy_sheet(src_ws, dst_ws, max_r=None, max_c=None):
    mr=max_r or src_ws.max_row; mc=max_c or src_ws.max_column
    for r in range(1, mr+1):
        for c in range(1, mc+1):
            sc=src_ws.cell(r,c); dc=dst_ws.cell(r,c)
            if not isinstance(sc, openpyxl.cell.cell.MergedCell): dc.value=sc.value
            if sc.has_style:
                dc.font=copy(sc.font); dc.fill=copy(sc.fill); dc.border=copy(sc.border)
                dc.alignment=copy(sc.alignment); dc.number_format=sc.number_format
    for mrg in src_ws.merged_cells.ranges:
        if max_r is None or (mrg.min_row<=mr): dst_ws.merge_cells(str(mrg))
    for L,dim in src_ws.column_dimensions.items():
        dst_ws.column_dimensions[L].width=dim.width; dst_ws.column_dimensions[L].hidden=dim.hidden
    for i,dim in src_ws.row_dimensions.items():
        if max_r is None or i<=mr:
            if dim.height: dst_ws.row_dimensions[i].height=dim.height

out=openpyxl.Workbook(); out.remove(out.active)
for path,sheets in SRC:
    wb=openpyxl.load_workbook(path)
    for name in (sheets or wb.sheetnames):
        d=out.create_sheet(name); copy_sheet(wb[name], d)
# 기타비용: 총계행(157)까지만 복제
lwb=openpyxl.load_workbook(LEDGER[0])
for name in LEDGER[1]:
    sw=lwb[name]
    # 총 금액 행 찾기
    endr=sw.max_row
    for r in range(1,sw.max_row+1):
        if str(sw.cell(r,2).value or '').startswith('총'): endr=r; break
    d=out.create_sheet(name); copy_sheet(sw, d, max_r=endr, max_c=12)
out.save(OUT)
print('저장:', OUT, '| 시트', len(out.sheetnames), out.sheetnames)
