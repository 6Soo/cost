# -*- coding: utf-8 -*-
"""수기장부(원장) 여행탭 지출내용 → manual_v3.csv/manual_v4.csv 재생성(2026-07-24).

이전 세션에서부터 지적된 갭: manual_v3.csv/manual_v4.csv(엔진이 수기 매칭에 쓰는 flat 파일)를
만드는 스크립트가 저장소에 없어서, 원장이 갱신돼도 이 파일들이 절대 최신화되지 않았다
("스냅샷이 06:39에 멈춰있다" 문제). 이 스크립트가 그 갭을 근본적으로 닫는다 — data/ledger_current.xlsx
(P8: Drive 최신본)를 직접 파싱해 매번 재생성한다.

원장 여행탭의 "지출 내용" 섹션은 두 레이아웃이 섞여 있다(사용자가 확정된 탭에 rev 산출물을
그대로 붙여넣으면서 레이아웃이 바뀌기 때문 — 탭마다 다르고 시간이 지나면 더 바뀔 수 있어
헤더 구조로 자동판별한다):
  · Layout A(예약번호 열이 명시적): B거래일자 C항목 D내용 E기간 F예약번호 G증빙유형 H금액
  · Layout B(원본 그대로): B거래일자 D항목 F내용(기간 텍스트 포함) H증빙유형 I금액,
    예약번호는 명시 열 없이 I열 오른쪽 어딘가에 느슨하게 존재(스캔해서 찾음)

출력 스키마(build_v13_trip.py가 그대로 읽음): manual_v3.csv(tab,date,item,desc,card,amount,book),
manual_v4.csv(tab,row,date,item,desc,card,amount,book) — row는 원장의 실제 엑셀 행번호
("수기N행" 인용이 원장에서 실제로 찾아갈 수 있게).
"""
import openpyxl, re, csv, datetime, sys

LEDGER = 'data/ledger_current.xlsx'
TRIP_TAB_RE = re.compile(r'^(\d{4}_|\d+월_)')

def fmt_date(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime('%y.%m.%d')
    s = str(v or '').strip()
    return s

def find_booking(cells, start_col):
    for v in cells[start_col:]:
        if isinstance(v, (int, float)) and v >= 10000000:
            return str(int(v))
        if isinstance(v, str) and re.match(r'^\d{8,19}$', v.strip()):
            return v.strip()
    return None

def detect_layout(ws, header_row):
    row = [ws.cell(header_row, c).value for c in range(1, 10)]
    if row[2] == '항목' and row[6] == '증빙유형':   # C=항목, G=증빙유형 (1-idx: col3,col7)
        return 'A'
    if row[3] == '항목' and row[7] == '증빙유형':   # D=항목, H=증빙유형 (col4,col8)
        return 'B'
    return None

def extract_tab(ws, tab):
    out = []
    start = None
    for r in range(1, ws.max_row + 1):
        if str(ws.cell(r, 2).value or '').strip() == '지출 내용':
            start = r + 1
            break
    if start is None:
        return out
    layout = detect_layout(ws, start)
    if layout is None:
        print('  ⚠ %s: 지출내용 헤더를 인식 못함(레이아웃 불명) — 스킵' % tab, file=sys.stderr)
        return out
    for r in range(start + 1, ws.max_row + 1):
        cells = [ws.cell(r, c).value for c in range(1, 20)]
        if layout == 'A':
            date, item, desc, book_c, card, amt = cells[1], cells[2], cells[3], cells[5], cells[6], cells[7]
            book = str(int(book_c)) if isinstance(book_c, (int, float)) else (str(book_c).strip() if book_c else None)
        else:
            date, item, desc, card, amt = cells[1], cells[3], cells[5], cells[7], cells[8]
            book = find_booking(cells, 8)
        if not item and not amt:
            continue
        if isinstance(item, str) and item.strip().startswith('총'):
            break
        out.append(dict(tab=tab, row=r, date=fmt_date(date), item=str(item or '').strip(),
                         desc=str(desc or '').strip(), card=str(card or '').strip(),
                         amount=amt if isinstance(amt, (int, float)) else str(amt or ''),
                         book=book or ''))
    return out

def main():
    wb = openpyxl.load_workbook(LEDGER, data_only=True)
    all_rows = []
    for tab in wb.sheetnames:
        if not TRIP_TAB_RE.match(tab):
            continue
        rows = extract_tab(wb[tab], tab)
        all_rows.extend(rows)
        print('  %-20s %3d행' % (tab, len(rows)))

    FN3 = ['tab', 'date', 'item', 'desc', 'card', 'amount', 'book']
    with open('data/manual_v3.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FN3)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r[k] for k in FN3})

    FN4 = ['tab', 'row', 'date', 'item', 'desc', 'card', 'amount', 'book']
    with open('data/manual_v4.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FN4)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r[k] for k in FN4})

    print('gen_manual_v34: %d개 탭 %d행 → manual_v3.csv/manual_v4.csv 재생성 완료' %
          (len({r['tab'] for r in all_rows}), len(all_rows)))

if __name__ == '__main__':
    main()
