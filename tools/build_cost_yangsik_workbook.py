import pathlib, json, sqlite3, openpyxl, urllib.request, sys
sys.path.insert(0, r'C:\AX\cost')
from openpyxl.styles import Font
from ledger.domain.direct_trip_schedule_authority import load_document

TEMPLATE = pathlib.Path(r'C:\Users\kkokk\AppData\Local\Temp\opencode\ledger_full.xlsx')
SRC = pathlib.Path(r'C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite')
AUTH = pathlib.Path(r'C:\AX\cost\ledger\data\trip_schedule_authority_v3.json')
OUT = pathlib.Path(r'C:\AX\cost\outputs\법인경리_비용_전체_5328_48tabs_v12_20260829.xlsx')

if not TEMPLATE.exists():
    url = 'https://docs.google.com/spreadsheets/d/1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU/export?format=xlsx'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        TEMPLATE.write_bytes(r.read())

auth_loaded, _ = load_document(AUTH)
tpl = openpyxl.load_workbook(str(TEMPLATE), data_only=True)
# 비용 양식: '2분기_기타비용' 시트가 진짜 비용 양식
tpl_name = '2분기_기타비용' if '2분기_기타비용' in tpl.sheetnames else None
if not tpl_name:
    # fallback to 매출확인자료_양식_rev
    tpl_name = [n for n in tpl.sheetnames if '양식' in n][0]
ws_tpl = tpl[tpl_name]
print(f"템플릿 시트: {tpl_name}")
print(f"7행 헤더:")
for col in range(1, 10):
    v = ws_tpl.cell(row=7, column=col).value
    print(f"  열{col}={v}")

conn = sqlite3.connect(str(SRC)); cur = conn.cursor()
cur.execute("SELECT id, merchant, amount_krw, occurred_on FROM payment_transactions")
rows = cur.fetchall()
by_trip = {}
for pid, mer, amt, occ in rows:
    matched = None
    for rec in auth_loaded:
        if rec.starts_on.isoformat() <= occ <= rec.ends_on.isoformat():
            matched = rec.trip_code
            break
    if not matched:
        if occ.startswith('2025'):
            matched = '2025_종결_권위'
        else:
            matched = '기타비용'
    by_trip.setdefault(matched, []).append((pid, mer, amt, occ))

wb_out = openpyxl.Workbook()
wb_out.remove(wb_out.active)
for trip, lst in sorted(by_trip.items()):
    ws = wb_out.create_sheet(title=trip[:31])
    # 7행 헤더 정확히 복사
    for col in range(1, 10):
        v = ws_tpl.cell(row=7, column=col).value
        ws.cell(row=7, column=col, value=v)
        if v:
            ws.cell(row=7, column=col).font = Font(bold=True)
    # 1행 탭명
    ws['A1'] = trip
    ws['A1'].font = Font(bold=True, size=12)
    # 9행부터 데이터: 비용 양식 B~H열에 입력
    for i, (pid, mer, amt, occ) in enumerate(lst):
        ws.cell(row=9+i, column=2, value=occ)  # B 거래일자
        ws.cell(row=9+i, column=4, value=mer[:20])  # D 항목 (가맹점명)
        ws.cell(row=9+i, column=5, value=amt)  # E 단가
        # F 단위, G 메모 비움
        ws.cell(row=9+i, column=8, value=amt)  # H 금액

wb_out.save(str(OUT))
print(f"생성: {OUT} ({OUT.stat().st_size/1024:.0f} KB, {len(wb_out.sheetnames)}시트)")
