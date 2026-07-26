# -*- coding: utf-8 -*-
import csv, openpyxl, sys

def compare_all_tabs():
    sys.stdout.reconfigure(encoding='utf-8')
    
    # Load manual expenses from manual_v4.csv (non-1 sheets)
    man_expenses = {}
    with open('data/manual_v4.csv', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            tab = row['tab']
            if tab not in man_expenses:
                man_expenses[tab] = []
            man_expenses[tab].append(row)
            
    # Load AI classified expenses from classified_v14.csv
    ai_expenses = {}
    with open('data/classified_v14.csv', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            tab = row['bucket']
            if tab not in ai_expenses:
                ai_expenses[tab] = []
            ai_expenses[tab].append(row)
            
    q2_tabs = ['0404_에히메', '0408_교토', '0413_나가센도', '0417_아오모리', '0420_오사카', '0424_알펜루트', 
               '0501_부산', '5월_유럽', '0613_북해도', '0616_레분토&리시리', '0620_묘코', '0625_아키타', '0630_오제']
               
    identical_tabs = []
    different_tabs = []
    
    print("=== 2분기 여행 탭 수기장부 vs AI분류 엔진 전수 비교 ===")
    for tab in q2_tabs:
        m_list = man_expenses.get(tab, [])
        a_list = ai_expenses.get(tab, [])
        
        # Calculate sum of amounts
        m_sum = sum(float(x['amount']) for x in m_list if x['amount'])
        a_sum = sum(float(x['krw']) for x in a_list if x['krw'])
        
        diff_count = len(a_list) - len(m_list)
        diff_sum = a_sum - m_sum
        
        is_identical = (len(m_list) == len(a_list)) and (abs(diff_sum) < 1.0)
        
        if is_identical:
            identical_tabs.append(tab)
            status = "100% 일치 (출력 제외 대상)"
        else:
            different_tabs.append(tab)
            status = f"차이 존재 (출력 대상) -> 건수차: {diff_count:+d}건, 금액차: {diff_sum:+,}원"
            
        print(f"탭 [{tab:15s}]: 수기 {len(m_list):3d}건 ({m_sum:12,.0f}원) | AI {len(a_list):3d}건 ({a_sum:12,.0f}원) | {status}")
        
    print(f"\n총 13개 탭 중:")
    print(f" - 100% 일치하여 출력 제외할 탭 ({len(identical_tabs)}개): {identical_tabs}")
    print(f" - 변경/차이가 있어 재출력할 탭 ({len(different_tabs)}개): {different_tabs}")
    return identical_tabs, different_tabs

if __name__ == '__main__':
    compare_all_tabs()
