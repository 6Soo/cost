# -*- coding: utf-8 -*-
"""수정된 엔진 기반 2분기 매출확인자료 최종 출력 스크립트.
규칙 2: 끝에 (1)이 붙은 시트 무시
규칙 3: 수기장부와 100% 일치하는 탭은 출력에서 제외하고, 차이가 있는 탭만 최종 출력 파일로 생성.
"""
import openpyxl, os, sys, copy

def filter_and_output():
    sys.stdout.reconfigure(encoding='utf-8')
    
    src_consolidated = '매출확인자료_2분기_통합_v5.xlsx' if os.path.exists('매출확인자료_2분기_통합_v5.xlsx') else 'data/매출확인자료_2분기_통합_v5.xlsx'
    manual_file = 'ledger_latest_new.xlsx' if os.path.exists('ledger_latest_new.xlsx') else 'data/ledger_latest_new.xlsx'
    out_file = 'data/매출확인자료_2분기_차이반영본.xlsx'
    
    wb_manual = openpyxl.load_workbook(manual_file, data_only=True)
    wb_out = openpyxl.load_workbook(src_consolidated)
    
    removed_sheets = []
    kept_sheets = []
    
    print("=== 수기장부 대비 100% 일치 탭 필터링 검사 ===")
    
    for sheetname in list(wb_out.sheetnames):
        if sheetname in ['표지', '요약', '총괄', '2분기_통합']:
            continue
            
        if sheetname not in wb_manual.sheetnames or sheetname.endswith(' (1)'):
            print(f"시트 [{sheetname:15s}]: 신규/차이 탭 -> 유지")
            kept_sheets.append(sheetname)
            continue
            
        ws_m = wb_manual[sheetname]
        ws_o = wb_out[sheetname]
        
        rows_m = [tuple(str(c or '').strip() for c in r if c is not None and str(c).strip() != '') 
                  for r in ws_m.iter_rows(values_only=True) if any(r)]
        rows_o = [tuple(str(c or '').strip() for c in r if c is not None and str(c).strip() != '') 
                  for r in ws_o.iter_rows(values_only=True) if any(r)]
                  
        rows_m_clean = [r for r in rows_m if not any('총' in x or '(A)-(B)' in x for x in r)]
        rows_o_clean = [r for r in rows_o if not any('총' in x or '(A)-(B)' in x for x in r)]
        
        is_identical = (rows_m_clean == rows_o_clean)
        
        if is_identical:
            print(f"시트 [{sheetname:15s}]: 100% 일치 -> [제외]")
            removed_sheets.append(sheetname)
            wb_out.remove(wb_out[sheetname])
        else:
            diff_len = len(rows_o_clean) - len(rows_m_clean)
            print(f"시트 [{sheetname:15s}]: 차이 존재 ({diff_len:+d}행 변동) -> [유지]")
            kept_sheets.append(sheetname)
            
    wb_out.save(out_file)
    print(f"\n==========================================")
    print(f"최종 출력 파일 생성 완료: {out_file}")
    print(f" - 수기 100% 일치 제외 시트 ({len(removed_sheets)}개): {removed_sheets}")
    print(f" - 차이 반영 출력 시트 ({len(kept_sheets)}개): {kept_sheets}")
    print(f"==========================================")

if __name__ == '__main__':
    filter_and_output()
