# -*- coding: utf-8 -*-
import openpyxl, csv, re, sys, datetime, shutil

def parse_ledger():
    src_file = 'data/ledger_latest_new.xlsx'
    shutil.copy(src_file, 'data/ledger_current.xlsx')
    shutil.copy(src_file, 'data/ledger_latest.xlsx')
    
    wb = openpyxl.load_workbook(src_file, data_only=True)
    
    rows_v4 = []
    rows_v3 = []
    
    for sname in wb.sheetnames:
        if sname.endswith(' (1)'):
            print(f'Ignoring comparison sheet: {sname}')
            continue
        
        ws = wb[sname]
        rows = list(ws.iter_rows(values_only=True))
        
        start_row_idx = None
        for idx, r in enumerate(rows):
            if r and any('지출' in str(c) for c in r if c is not None):
                start_row_idx = idx
                break
                
        if start_row_idx is not None and start_row_idx + 1 < len(rows):
            header_row = [str(c or '').strip() for c in rows[start_row_idx + 1]]
            
            # Dynamically locate column indices
            idx_date = next((i for i, h in enumerate(header_row) if '일자' in h or '날짜' in h), 1)
            idx_item = next((i for i, h in enumerate(header_row) if '항목' in h), 3)
            idx_desc = next((i for i, h in enumerate(header_row) if '내용' in h or '적요' in h), 5)
            idx_card = next((i for i, h in enumerate(header_row) if '증빙' in h or '카드' in h), 7)
            idx_amt = next((i for i, h in enumerate(header_row) if '금액' in h), 8)
            idx_book = next((i for i, h in enumerate(header_row) if '예약' in h or '비고' in h or '노트' in h), -1)
            
            for r_idx in range(start_row_idx + 2, len(rows)):
                r = rows[r_idx]
                if not r or not any(r): continue
                
                d = r[idx_date] if idx_date < len(r) else None
                item = str(r[idx_item] if idx_item < len(r) else '' or '').strip()
                desc = str(r[idx_desc] if idx_desc < len(r) else '' or '').strip()
                card = str(r[idx_card] if idx_card < len(r) else '' or '').strip()
                amt = r[idx_amt] if idx_amt < len(r) else None
                book_val = r[idx_book] if (idx_book >= 0 and idx_book < len(r)) else None
                book = str(book_val).strip() if book_val is not None else ''

                if d is None or str(d).strip() == '' or '총' in str(d) or '합계' in str(d):
                    if amt is not None and str(amt).strip() != '' and (item or desc):
                        dm = re.search(r'0?(\d{2})_?(\d{2})', desc)
                        d_str = f"26.{dm.group(1)}.{dm.group(2)}" if dm else "26.04.19"
                    else:
                        continue
                elif isinstance(d, (datetime.date, datetime.datetime)):
                    d_str = d.strftime('%y.%m.%d')
                else:
                    d_str = str(d).strip().replace("'", "")
                
                card_map = {'8835': '국민', '4886': '국민', '3820': '국민', '4595': '하나', '3923': '하나', '0906': '하나', '5483': '하나', '4971': '기업', '4985': '기업', '8972': '기업'}
                card_clean = re.sub(r'\.0$', '', card).strip()
                card = card_map.get(card_clean, card)

                if not book or book.lower() in ('none', 'null', ''):
                    for cell_v in r:
                        if cell_v is not None:
                            c_str = re.sub(r'\.0$', '', str(cell_v).strip())
                            if re.match(r'^\d{10}$', c_str):
                                book = c_str
                                break

                try:
                    if amt is not None and str(amt).strip() != '':
                        amt_val = float(str(amt).replace(',', ''))
                    else:
                        continue
                except:
                    continue
                    
                row_v4 = {
                    'tab': sname,
                    'row': str(r_idx + 1),
                    'date': d_str,
                    'item': item,
                    'desc': desc,
                    'card': card,
                    'amount': str(amt_val),
                    'book': book
                }
                row_v3 = {
                    'tab': sname,
                    'date': d_str,
                    'item': item,
                    'desc': desc,
                    'card': card,
                    'amount': str(amt_val),
                    'book': book
                }
                rows_v4.append(row_v4)
                rows_v3.append(row_v3)
                
    with open('data/manual_v4.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['tab', 'row', 'date', 'item', 'desc', 'card', 'amount', 'book'])
        w.writeheader()
        w.writerows(rows_v4)
        
    with open('data/manual_v3.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['tab', 'date', 'item', 'desc', 'card', 'amount', 'book'])
        w.writeheader()
        w.writerows(rows_v3)

    print(f'Successfully updated manual_v4.csv and manual_v3.csv with {len(rows_v4)} non-(1) rows!')

if __name__ == '__main__':
    parse_ledger()
