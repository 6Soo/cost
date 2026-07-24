# -*- coding: utf-8 -*-
"""2분기 통합: 4월(rev v5) 6탭 + 5·6월(rev v1) 7탭 + 2분기_기타비용(장부) → 단일 워크북.
   각 시트를 값+서식(폰트·배경·테두리·정렬·번호형식)·병합·행높이·열폭 그대로 셀단위 복제.
   여행탭 중 원장(ledger_latest.xlsx)에 총 금액(A)·총 금액(B)이 이미 동일하게 반영돼 있으면
   (=사용자가 확정본을 원장에 직접 붙여넣어 확정처리한 탭) 중복 산출을 피하기 위해 제외한다."""
import openpyxl, subprocess, os, tempfile
from copy import copy
import versioning

# ★2026-07-24: 입력 파일명을 하드코딩(v8/v5)하지 않고 versioning 레지스트리에서 실제 현재
#   파일명을 읽는다 — gen_april_rev.py/gen_mayjun_rev.py가 내용변경으로 버전을 올려도
#   여기서 구버전 파일명을 찾다가 깨지지 않는다.
SRC=[(versioning.current_path('april_rev', '매출확인자료_4월_rev'), None),   # None=전 시트
     (versioning.current_path('mayjun_rev', '매출확인자료_5-6월_rev'), None)]
LEDGER=('ledger_latest.xlsx', ['2분기_기타비용'])

def recalc(paths):
    """LibreOffice 헤드리스로 수식 재계산 후 캐시값 포함된 사본 경로 dict{원경로: 재계산경로} 반환.
    입력·출력 디렉터리를 분리해야 한다 — 같으면 soffice가 조용히 변환을 건너뛴다."""
    src_d=tempfile.mkdtemp(prefix='consolidate_recalc_src_')
    out_d=tempfile.mkdtemp(prefix='consolidate_recalc_out_')
    import shutil
    for p in paths:
        shutil.copy(p, src_d)
    subprocess.run(['soffice','--headless','--convert-to','xlsx:Calc MS Excel 2007 XML',
                     '--outdir', out_d] + [os.path.join(src_d, os.path.basename(p)) for p in paths],
                    check=True, capture_output=True)
    return {p: os.path.join(out_d, os.path.basename(p)) for p in paths}

def find_totals(ws):
    """'총 금액 (A)'/'총 금액 (B)' 등 '총'으로 시작하는 라벨 행의 숫자값을 (라벨,값)로 수집."""
    tots={}
    for r in range(1, ws.max_row+1):
        for c in range(1, min(ws.max_column,10)+1):
            v=ws.cell(r,c).value
            if isinstance(v,str) and v.strip().startswith('총'):
                for c2 in range(c+1, ws.max_column+1):
                    v2=ws.cell(r,c2).value
                    if isinstance(v2,(int,float)): tots[v.strip()]=v2; break
    return tots

def already_archived(sheet_name, src_path, recalced):
    """해당 탭의 총액이 원장에 이미 동일하게 반영돼 있으면 True."""
    if sheet_name not in ledger_names: return False
    src_ws=openpyxl.load_workbook(recalced[src_path], data_only=True)[sheet_name]
    led_ws=openpyxl.load_workbook(recalced[LEDGER[0]], data_only=True)[sheet_name]
    st, lt = find_totals(src_ws), find_totals(led_ws)
    return bool(st) and st == lt

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

ledger_names=set(openpyxl.load_workbook(LEDGER[0], read_only=True).sheetnames)
recalced=recalc([p for p,_ in SRC]+[LEDGER[0]])

out=openpyxl.Workbook(); out.remove(out.active)
included, excluded = [], []
for path,sheets in SRC:
    wb=openpyxl.load_workbook(path)
    for name in (sheets or wb.sheetnames):
        if already_archived(name, path, recalced):
            excluded.append(name); continue
        d=out.create_sheet(name); copy_sheet(wb[name], d); included.append(name)
# 기타비용: 총계행(157)까지만 복제
lwb=openpyxl.load_workbook(LEDGER[0])
for name in LEDGER[1]:
    sw=lwb[name]
    # 총 금액 행 찾기
    endr=sw.max_row
    for r in range(1,sw.max_row+1):
        if str(sw.cell(r,2).value or '').startswith('총'): endr=r; break
    d=out.create_sheet(name); copy_sheet(sw, d, max_r=endr, max_c=12)
OUT = versioning.save_versioned('consolidated', '매출확인자료_2분기_통합', lambda p: out.save(p))
print('저장:', OUT, '| 포함', len(included), included)
print('제외(원장에 총액 동일하게 이미 확정반영됨):', len(excluded), excluded)
