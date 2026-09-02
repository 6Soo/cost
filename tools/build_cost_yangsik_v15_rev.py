import pathlib, json, sqlite3, csv
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.worksheet.properties import PageSetupProperties
import sys
sys.path.insert(0, r"C:\AX\cost")
from ledger.domain.direct_trip_schedule_authority import load_document

# Source files
SRC_DB = pathlib.Path(r"C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite")
AUTH_JSON = pathlib.Path(r"C:\AX\cost\ledger\data\trip_schedule_authority_v3.json")
CLASSIFIED_CSV = pathlib.Path(r"C:\AX\cost\ledger\data\classified_v12.csv")
MERCHANT_JSON = pathlib.Path(r"C:\AX\cost\ledger\data\merchant_map_v15.json")
OTA_BOOKINGS_DB = pathlib.Path(r"C:\AX\cost\outputs\ota-integrated-bookings-v1.sqlite")
OUT_XLSX = pathlib.Path(r"C:\AX\cost\outputs\법인경리_비용_전체_5328_48tabs_v15_20260901.xlsx")

# Load merchant map
merchant_map = {
    'AGODA_NICE-Agoda': '아고다(나이스)',
    'AGODA.COM APA HOTEL': '아고다-아파호텔',
    'AGODA.COM': '아고다',
    'AGODA.COM IBUSUKI KA': '아고다-이부스키',
    'AGODA.COM OOEDO ONSE': '아고다-오오에도',
    'AGODA.COM MERCURE NA': '아고다-메르큐르',
    'AGODA.COM PLAZA HOTE': '아고다-플라자',
    'AGODA.COM LIVEMAX RE': '아고다-리브맥스',
    'AGODA.COM CMOR BY RE': '아고다-Cmor',
    'AGODA.COM LA CURACIO': '아고다-라쿠라시오',
    'AGODA.COM IBIS STYLE': '아고다-이비스',
    'AGODA.COM CIEL MINI': '아고다-시엘',
    'AGODA.COM WAFUYADO O': '아고다-와후야도',
    'AGODA.COM YUTORELO K': '아고다-유토렐로',
    'AGODA.COM HOTEL SEKI': '아고다-호텔세키',
    'AGODA.COM HOTEL PLAZ': '아고다-호텔플라자',
    'AGODA.COM MITO SANNO': '아고다-미토산노',
    'AGODA.COM ASTANA INT': '아고다-아스타나',
    'AGODA.COM SHONAI HOT': '아고다-쇼나이',
    'AGODA.COM WAFUYADO O': '아고다-와후야도',
    'AGODA                    TOKYO': '아고다-도쿄',
    'BKG*Booking.com Hotel  Amsterdam': '부킹닷컴-암스테르담',
    'BKG*BOOKING.COM HOTEL': '부킹닷컴',
    'KLOOK': '클룩',
    'Mytrip': '마이트립', 'mytrip': '마이트립',
    '트립닷컴(구)_NICE': '트립닷컴', '트립닷컴(ARS)_나이스': '트립닷컴(ARS)',
    'TRIP.COM': '트립닷컴', 'Trip.com': '트립닷컴',
    'Trip.com                 Tokyo        JP': '트립닷컴-도쿄', 'Trip.com                 Tokyo': '트립닷컴-도쿄',
    '아고다_나이스': '아고다(나이스)', '하나투어-트립닷컴': '하나투어-트립닷컴',
    'FAMILYMART               Tokyo        JP': '패밀리마트',
    'LAWSON                   Tokyo        JP': '로손',
    'SEVEN-ELEVEN             Tokyo': '세븐일레븐', 'SEVEN-ELEVEN             Tokyo        JP': '세븐일레븐',
    'SQ*KAMIKURA              OKAYAMA': '스퀘어-카미쿠라',
    'FUKUTAKE FOUNDATION': '후쿠타케재단',
    'HOTELGOZENSUI            Tokyo        JP': '고젠스이호텔',
    'FORESTHOTELANNEX         Aomori       JP': '포레스트호텔',
    'EN HOSPITALITY': 'EN호스피탈리티',
    'HOTELAREAONEHIROSHIMAWING': '아레아원호텔',
    'KYUKAMURA OHKUNOSHIMA    0846-26-0323': '큐카무라-오쿠노시마',
    'HIROSHIMAKENNRITUBIZYU   HIROSHIMA    JP': '히로시마현립미술관',
    'HIROSHIMAKENRITSUBIJUT': '히로시마현립미술관',
    'SONCHONOMISE             HIROSHIMA': '손초노미세',
    'ROUTE-INN GRANTIA HANYU S': '루트인그런티아',
    'MEIJITEI                 KITASAKU-GUN': '메이지테이',
    'YAMAHEI                  NAGANO': '야마헤이',
    'MAMPEI HOTEL             Tokyo': '만페이호텔',
    'RITSURIN GARDEN          KAGAWA       JP': '릿스린가든',
}
if MERCHANT_JSON.exists():
    j = json.loads(MERCHANT_JSON.read_text(encoding='utf-8'))
    merchant_map.update(j.get("full_map_additions", {}))

def korean_name(mer):
    if not mer:
        return ''
    s = mer.strip()
    if s in merchant_map:
        return merchant_map[s]
    for k, v in merchant_map.items():
        if k in s or s in k:
            return v
    if 'TOKYO' in s.upper():
        return s.split()[0][:12] + '-도쿄'
    if ' JP' in s or s.endswith('JP'):
        return s.split()[0][:12] + '-일본'
    return s[:20]

# Load classified for C열 mapping: key = (use_date, krw, merchant_prefix)
classified_map = {}
if CLASSIFIED_CSV.exists():
    with open(CLASSIFIED_CSV, encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row['use_date'], row['krw'], row['merchant'][:12])
            if key not in classified_map and row['user']:
                classified_map[key] = row['user']

# Load OTA bookings for additional name mapping
# Key: (service_start_on, paid_total_krw, card_last4) -> passenger names
ota_name_map = {}
if OTA_BOOKINGS_DB.exists():
    conn_ota = sqlite3.connect(str(OTA_BOOKINGS_DB))
    cur_ota = conn_ota.cursor()
    cur_ota.execute("""
        SELECT service_start_on, paid_total_krw, card_last4, property_name, provider
        FROM ota_integrated_bookings
        WHERE paid_total_krw IS NOT NULL
    """)
    for row in cur_ota.fetchall():
        svc_start, amt, card4, prop, prov = row
        if svc_start and amt:
            key = (svc_start, str(amt), card4 or '')
            if key not in ota_name_map:
                ota_name_map[key] = prop or prov
    conn_ota.close()
    print(f"OTA name map entries: {len(ota_name_map)}")

# Load authority for titles
auth_loaded, _ = load_document(AUTH_JSON)
trip_info = {}
for rec in auth_loaded:
    code = rec.trip_code
    start = rec.starts_on.isoformat()
    end = rec.ends_on.isoformat()
    month = int(start.split("-")[1])
    region = code.split("_", 1)[1] if "_" in code else code
    trip_info[code] = {"start": start, "end": end, "month": month, "region": region}

# Load payments from SQLite
conn = sqlite3.connect(str(SRC_DB))
cur = conn.cursor()
cur.execute("SELECT id, merchant, amount_krw, occurred_on FROM payment_transactions")
rows = cur.fetchall()
conn.close()

# Group by trip
by_trip = {}
for pid, mer, amt, occ in rows:
    matched = None
    for rec in auth_loaded:
        if rec.starts_on.isoformat() <= occ <= rec.ends_on.isoformat():
            matched = rec.trip_code
            break
    if not matched:
        matched = '2025_종결_권위' if occ.startswith('2025') else '기타비용'
    by_trip.setdefault(matched, []).append((pid, mer, amt, occ))

# Create output workbook
wb = Workbook()
wb.remove(wb.active)

# Styles
header_font = Font(bold=True)
title_font = Font(bold=True, size=12)
thin_border = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)
center_align = Alignment(horizontal='center', vertical='center')
wrap_align = Alignment(wrap_text=True, vertical='center')

for trip, lst in sorted(by_trip.items()):
    ws = wb.create_sheet(title=trip[:31])

    # Row 1: empty (reserved)
    # Row 2: Title
    ws['B2'] = "숲길여행"
    ws['B2'].font = title_font
    info = trip_info.get(trip)
    if info:
        mm = info["month"]
        region = info["region"]
        s = info["start"]
        e = info["end"]
        smmdd = s[5:7] + s[8:10]
        emmdd = e[5:7] + e[8:10]
        ws['C2'] = f"2026년 {mm}월 매출 확인자료_{region}_{smmdd}_{emmdd}"
    else:
        ws['C2'] = trip
    ws['C2'].font = title_font

    # Row 3: empty
    # Row 4: 정산일자 / 담당자
    ws['H4'] = "담당자 : 숲길여행"
    ws['H4'].font = Font(size=10)

    # Row 5: empty
    # Row 6: 지출 내용
    ws['B6'] = "지출 내용"
    ws['B6'].font = Font(bold=True, size=11)

    # Row 7: Header
    headers = ['거래일자', '이름', '닉네임', '증빙', '단가', '추가금', '금액(합)']
    for col_idx, h in enumerate(headers, 2):  # B=2 to H=8
        cell = ws.cell(row=7, column=col_idx, value=h)
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border

    # Data rows starting from row 8
    for i, (pid, mer, amt, occ) in enumerate(lst):
        r = 8 + i
        # B: 거래일자
        ws.cell(row=r, column=2, value=occ).border = thin_border
        ws.cell(row=r, column=2).alignment = center_align

        # C: 이름 - try classified mapping first
        key = (occ, str(amt), mer[:12])
        user = classified_map.get(key, "")
        # Fallback: search by date+amount only
        if not user:
            for k, v in classified_map.items():
                if k[0] == occ and k[1] == str(amt):
                    user = v
                    break
        # Fallback: OTA booking map by (service_start, amount, card_last4)
        # Note: we don't have card_last4 in payment_transactions, try date+amount
        if not user:
            ota_key = (occ, str(amt), '')
            if ota_key in ota_name_map:
                user = ota_name_map[ota_key]
        ws.cell(row=r, column=3, value=user).border = thin_border
        ws.cell(row=r, column=3).alignment = center_align

        # D: 닉네임 - leave empty for now (no source)
        ws.cell(row=r, column=4, value="").border = thin_border
        ws.cell(row=r, column=4).alignment = center_align

        # E: 증빙 (가맹점 한글명)
        ws.cell(row=r, column=5, value=korean_name(mer)).border = thin_border
        ws.cell(row=r, column=5).alignment = center_align

        # F: 단가 - leave 0 (no natural split for card transactions)
        ws.cell(row=r, column=6, value=0).border = thin_border
        ws.cell(row=r, column=6).alignment = center_align
        ws.cell(row=r, column=6).number_format = '#,##0'

        # G: 추가금 - leave 0
        ws.cell(row=r, column=7, value=0).border = thin_border
        ws.cell(row=r, column=7).alignment = center_align
        ws.cell(row=r, column=7).number_format = '#,##0'

        # H: 금액(합) = SUM(E:G)
        ws.cell(row=r, column=8, value=f"=SUM(E{r}:G{r})").border = thin_border
        ws.cell(row=r, column=8).alignment = center_align
        ws.cell(row=r, column=8).number_format = '#,##0'

    # Row 28: 합계 금액 (A)
    last_data_row = 8 + len(lst) - 1
    total_row = last_data_row + 1
    # If less than 20 data rows, put total at row 28 per template
    if total_row < 28:
        total_row = 28
    ws.cell(row=total_row, column=2, value="합계 금액 (A)").font = Font(bold=True)
    ws.cell(row=total_row, column=3, value=f"=SUM(H8:H{last_data_row})").font = Font(bold=True)
    ws.cell(row=total_row, column=3).alignment = center_align
    ws.cell(row=total_row, column=3).number_format = '#,##0'

    # Row 30: 정산 내역
    settle_row = total_row + 2
    ws.cell(row=settle_row, column=2, value="정산 내역").font = Font(bold=True, size=11)

    # Set column widths
    ws.column_dimensions['B'].width = 12  # 거래일자
    ws.column_dimensions['C'].width = 15  # 이름
    ws.column_dimensions['D'].width = 15  # 닉네임
    ws.column_dimensions['E'].width = 25  # 증빙
    ws.column_dimensions['F'].width = 12  # 단가
    ws.column_dimensions['G'].width = 12  # 추가금
    ws.column_dimensions['H'].width = 14  # 금액(합)

    # Print settings
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

wb.save(str(OUT_XLSX))
print(f"생성: {OUT_XLSX} ({OUT_XLSX.stat().st_size/1024:.0f} KB, {len(wb.sheetnames)}시트)")

# Stats
c_mapped = sum(1 for _, _, amt, occ in sum(by_trip.values(), [])
               if classified_map.get((occ, str(amt), '')) or
                  any(k[0]==occ and k[1]==str(amt) for k in classified_map.keys()))
stats = {
    "sheets": len(wb.sheetnames),
    "total_payments": len(rows),
    "by_trip": {k: len(v) for k, v in by_trip.items()},
    "merchant_mapped": len(merchant_map),
    "classified_keys": len(classified_map),
    "c_column_mapped": c_mapped,
    "ota_name_map_entries": len(ota_name_map)
}
pathlib.Path(r"C:\AX\cost\ledger\data\v15_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"C열 매핑: {c_mapped}건 / 전체 {len(rows)}건")