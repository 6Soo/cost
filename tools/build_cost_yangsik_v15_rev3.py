import pathlib, json, sqlite3, csv
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.worksheet.properties import PageSetupProperties
import sys
sys.path.insert(0, r"C:\AX\cost")
from ledger.domain.direct_trip_schedule_authority import load_document

# Force utf-8 output
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Source files
SRC_DB = pathlib.Path(r"C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite")
AUTH_JSON = pathlib.Path(r"C:\AX\cost\ledger\data\trip_schedule_authority_v3.json")
C_MAP_IMPROVED = pathlib.Path(r"C:\AX\cost\ledger\data\c_mapping_improved.json")
OTA_BOOKINGS_DB = pathlib.Path(r"C:\AX\cost\outputs\ota-integrated-bookings-v1.sqlite")
MERCHANT_JSON = pathlib.Path(r"C:\AX\cost\ledger\data\merchant_map_v15.json")
OUT_XLSX = pathlib.Path(r"C:\AX\cost\outputs\법인경리_비용_전체_5328_48tabs_v15_20260901.xlsx")

# Load merchant map (korean names)
merchant_map = {}
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

# Load C-column mapping
c_column_map = {}
if C_MAP_IMPROVED.exists():
    with open(C_MAP_IMPROVED, encoding='utf-8') as f:
        map_data = json.load(f)
        for key_str, user in map_data.items():
            use_date, krw = key_str.split('|')
            c_column_map[(use_date, krw)] = user
    print(f"Loaded C-column mapping: {len(c_column_map)} entries")

# Load OTA bookings
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

# Load payments
conn = sqlite3.connect(str(SRC_DB))
cur = conn.cursor()
cur.execute("SELECT id, merchant, amount_krw, occurred_on FROM payment_transactions")
rows = cur.fetchall()
conn.close()

# Group by trip (정확한 매칭)
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

print(f"원본 결제: {len(rows)}건, 시트: {len(by_trip)}개")
for k, v in sorted(by_trip.items()):
    print(f"  {k:30s}  {len(v)}건")

# Create output workbook
wb = Workbook()
wb.remove(wb.active)

# Styles
title_font = Font(name='맑은 고딕', bold=True, size=12)
title_font_big = Font(name='맑은 고딕', bold=True, size=14)
header_font = Font(name='맑은 고딕', bold=True, size=11)
personnel_font = Font(name='맑은 고딕', bold=True, size=12)
section_font = Font(name='맑은 고딕', bold=True, size=12)
total_font = Font(name='맑은 고딕', bold=True, size=11)
body_font = Font(name='맑은 고딕', size=10)
check_font = Font(name='맑은 고딕', bold=True, size=11, color='FF0000')

# Fills
header_fill = PatternFill(start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
total_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
section_fill_in = PatternFill(start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
section_fill_out = PatternFill(start_color='FCE4D6', end_color='FCE4D6', fill_type='solid')
diff_fill = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

# Borders
thin_border = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)
medium_left_border = Border(
    left=Side(style='medium'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)

# Alignments
center_align = Alignment(horizontal='center', vertical='center')
right_align = Alignment(horizontal='right', vertical='center')
left_align = Alignment(horizontal='left', vertical='center')

# 함수: 항목 분류
def categorize(merchant):
    if not merchant:
        return '기타'
    m = merchant.upper()
    if any(k in m for k in ['AGODA', '아고다', 'BOOKING', '부킹', 'KLOOK', '클룩', 'TRIP.COM', '트립닷컴', 'HOTEL', '호텔', 'RYOKAN', '료칸']):
        return '숙박'
    if any(k in m for k in ['항공', 'AIR', '항공권', 'JINAIR', 'JEJU', "T'WAY", '에어', '이스타', 'ANAAIR', '제주항공']):
        return '항공'
    if any(k in m for k in ['인보험', 'INSURANCE', '트래블', 'TRAVEL']):
        return '여행자보험'
    if any(k in m for k in ['JR', '지하철', 'BUS', '버스', 'TAXI', '택시', 'HIGHWAY', 'TOLL', '고속도로', '교통', 'KT', 'PARKING']):
        return '교통'
    if any(k in m for k in ['FAMILYMART', 'LAWSON', 'SEVEN', '편의점', '스타벅스', 'STARBUCKS', '맥도날드', '치킨', 'PIZZA', 'RESTAURANT', 'CAFE', '커피', '음식', '식당', 'TKMART']):
        return '식음료'
    if any(k in m for k in ['주유', 'GAS', 'OIL', 'ENEOS', '코스트코', 'COSTCO']):
        return '주유/차량'
    return '기타'

# 함수: 증빙유형
def receipt_type(merchant):
    if not merchant:
        return '국민'
    m = merchant.upper()
    if 'JP' in m or 'TOKYO' in m or 'JAPAN' in m or 'TAIPE' in m or 'TAICH' in m or 'NANTO' in m or 'TAITU' in m or 'HUALI' in m or 'KAOHS' in m:
        return '영수증'
    return '국민'

for trip, lst in sorted(by_trip.items()):
    ws = wb.create_sheet(title=trip[:31])
    info = trip_info.get(trip)

    # === Row 2: Title ===
    ws['B2'] = "㈜숲길여행"
    ws['B2'].font = title_font
    ws['B2'].border = medium_left_border
    ws['B2'].alignment = left_align
    ws.row_dimensions[2].height = 21.0

    if info:
        mm = info["month"]
        region = info["region"]
        s = info["start"]
        e = info["end"]
        smmdd = s[5:7] + s[8:10]
        emmdd = e[5:7] + e[8:10]
        ws['C2'] = f"2026년 {mm}월 매출 확인자료_{region}_{smmdd}_{emmdd}"
    else:
        if trip == '2025_종결_권위':
            ws['C2'] = "2025년 종결 권위 비용"
        elif trip == '기타비용':
            ws['C2'] = "기타 비용"
        else:
            ws['C2'] = trip
    ws['C2'].font = title_font_big
    ws['C2'].border = medium_left_border
    ws['C2'].alignment = center_align

    # === Row 4: 작성일자 / 담당자 ===
    ws['D4'] = "작성일자 :      "
    ws['D4'].font = personnel_font
    ws['D4'].alignment = right_align
    ws['E4'] = "26.09.02"
    ws['E4'].font = personnel_font
    ws['E4'].alignment = center_align
    ws['H4'] = "담당자 : 김주형"
    ws['H4'].font = personnel_font
    ws['H4'].alignment = right_align
    ws.row_dimensions[4].height = 17.25

    # === Row 6: 수입 내용 (섹션) ===
    ws['B6'] = "수입 내용"
    ws['B6'].font = section_font
    ws['B6'].fill = section_fill_in
    ws['B6'].border = medium_left_border
    ws['B6'].alignment = left_align
    ws.row_dimensions[6].height = 18.0

    # === Row 7: 수입 내용 헤더 ===
    in_headers = ['거래일자', '이름', '닉네임', '예약금', '잔금', '추가금', '금액(원)']
    ws.row_dimensions[7].height = 16.5
    for col_idx, h in enumerate(in_headers, 2):
        cell = ws.cell(row=7, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        if col_idx == 8:
            cell.alignment = right_align
        else:
            cell.alignment = center_align

    # === Rows 8-27: 수입 내용 데이터 (빈 표) ===
    for r in range(8, 28):
        ws.row_dimensions[r].height = 16.5
        if r == 8:  # H8에만 수식
            cell = ws.cell(row=r, column=8, value="=sum(E8:G8)")
            cell.font = body_font
            cell.border = thin_border
            cell.alignment = right_align
            cell.number_format = '#,##0;-#,##0;;@'
        else:
            for col_idx in range(2, 9):
                cell = ws.cell(row=r, column=col_idx, value="")
                cell.font = body_font
                cell.border = thin_border
                if col_idx == 8:
                    cell.alignment = right_align
                    cell.number_format = '#,##0;-#,##0;;@'
                else:
                    cell.alignment = center_align

    # === Row 28: 총 금액 (A) ===
    ws.row_dimensions[28].height = 17.25
    cell = ws.cell(row=28, column=2, value="총 금액 (A)")
    cell.font = total_font
    cell.fill = total_fill
    cell.border = medium_left_border
    cell.alignment = center_align
    cell = ws.cell(row=28, column=3, value="=sum(H8:H27)")
    cell.font = total_font
    cell.fill = total_fill
    cell.alignment = center_align
    cell.number_format = '#,##0'

    # === Row 30: 지출 내용 (섹션) ===
    ws['B30'] = "지출 내용"
    ws['B30'].font = section_font
    ws['B30'].fill = section_fill_out
    ws['B30'].border = medium_left_border
    ws['B30'].alignment = left_align
    ws.row_dimensions[30].height = 18.0

    # === Row 31: 지출 내용 헤더 ===
    out_headers = ['거래일자', '항목', '내용', '기간', '예약번호', '증빙유형', '금액(원)']
    ws.row_dimensions[31].height = 16.5
    for col_idx, h in enumerate(out_headers, 2):
        cell = ws.cell(row=31, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = section_fill_out
        cell.border = thin_border
        if col_idx == 8:
            cell.alignment = right_align
        else:
            cell.alignment = center_align

    # === Rows 32+: 지출 내용 데이터 (상한 없음) ===
    out_start_row = 32
    for i, (pid, mer, amt, occ) in enumerate(lst):
        r = out_start_row + i
        ws.row_dimensions[r].height = 16.5

        # B: 거래일자
        cell = ws.cell(row=r, column=2, value=occ)
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = center_align

        # C: 항목 (가맹점 한글명)
        cell = ws.cell(row=r, column=3, value=korean_name(mer))
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = left_align

        # D: 내용 (분류)
        cell = ws.cell(row=r, column=4, value=categorize(mer))
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = center_align

        # E: 기간
        period = ""
        if info:
            period = f"{info['start'].replace('-', '')[4:]}_{info['end'].replace('-', '')[4:]}"
        elif trip == '2025_종결_권위':
            period = "2025_종결"
        else:
            period = ""
        cell = ws.cell(row=r, column=5, value=period)
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = center_align

        # F: 예약번호
        booking_id = f"{mer[:10].strip()}_{occ.replace('-', '')}"
        cell = ws.cell(row=r, column=6, value=booking_id[:30])
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = center_align

        # G: 증빙유형
        cell = ws.cell(row=r, column=7, value=receipt_type(mer))
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = center_align

        # H: 금액(원)
        cell = ws.cell(row=r, column=8, value=amt)
        cell.font = body_font
        cell.border = thin_border
        cell.alignment = right_align
        cell.number_format = '#,##0;-#,##0;;@'

    # 총 금액 (B) - 지출 합계
    out_last_row = out_start_row + len(lst) - 1
    if out_last_row < out_start_row:
        out_last_row = out_start_row
    total_b_row = out_last_row + 2
    ws.row_dimensions[total_b_row].height = 17.25
    cell = ws.cell(row=total_b_row, column=2, value="총 금액 (B)")
    cell.font = total_font
    cell.fill = total_fill
    cell.border = medium_left_border
    cell.alignment = center_align
    cell = ws.cell(row=total_b_row, column=3, value=f"=sum(H{out_start_row}:H{out_last_row})")
    cell.font = total_font
    cell.fill = total_fill
    cell.alignment = center_align
    cell.number_format = '#,##0'

    # (A)-(B) 회사수익인식
    diff_row = total_b_row + 2
    ws.row_dimensions[diff_row].height = 17.25
    cell = ws.cell(row=diff_row, column=2, value="(A)-(B) 회사수익인식")
    cell.font = total_font
    cell.fill = diff_fill
    cell.border = medium_left_border
    cell.alignment = center_align
    cell = ws.cell(row=diff_row, column=3, value="=C28-C{}".format(total_b_row))
    cell.font = total_font
    cell.fill = diff_fill
    cell.alignment = center_align
    cell.number_format = '#,##0;-#,##0;;@'

    # 확인 메시지
    check_row = diff_row + 2
    ws.row_dimensions[check_row].height = 18.0
    cell = ws.cell(row=check_row, column=3, value="A와 B 합계 잘 확인하기 !!")
    cell.font = check_font
    cell.alignment = center_align

    # === Column widths ===
    ws.column_dimensions['B'].width = 17.5
    ws.column_dimensions['C'].width = 25.0
    ws.column_dimensions['D'].width = 16.0
    ws.column_dimensions['E'].width = 14.0
    ws.column_dimensions['F'].width = 20.0
    ws.column_dimensions['G'].width = 12.0
    ws.column_dimensions['H'].width = 14.88

    # Page setup
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

wb.save(str(OUT_XLSX))
print(f"\n생성: {OUT_XLSX} ({OUT_XLSX.stat().st_size/1024:.0f} KB, {len(wb.sheetnames)}시트)")
print(f"총 지출 데이터: {sum(len(v) for v in by_trip.values())}건")
