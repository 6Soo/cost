"""양식_rev 7열(거래일자|이름|닉네임|증빙|단가|추가금|금액) 복제+값주입 빌더"""
import pathlib, json, sqlite3, openpyxl
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from copy import copy

TEMPLATE_URL = "https://docs.google.com/spreadsheets/d/1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU/export?format=xlsx"
TEMPLATE_LOCAL = pathlib.Path(r'C:\Users\kkokk\AppData\Local\Temp\opencode\ledger_full.xlsx')
SRC = pathlib.Path(r'C:\AX\cost\outputs\agoda-card-accounting-draft-v5-ota-extended.sqlite')
AUTH = pathlib.Path(r'C:\AX\cost\ledger\data\trip_schedule_authority_v3.json')
OUT = pathlib.Path(r'C:\AX\cost\outputs\매출확인자료_양식_rev_48tabs_v9_20260829.xlsx')

# 템플릿 다운로드 (또는 로컬 캐시 사용)
import urllib.request
if not TEMPLATE_LOCAL.exists():
    req = urllib.request.Request(TEMPLATE_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        TEMPLATE_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        TEMPLATE_LOCAL.write_bytes(r.read())

# 권위 일정 로드
auth = json.loads(AUTH.read_text(encoding='utf-8'))['records']
trip_by_code = {r['trip_code']: r for r in auth}

# 템플릿 열기
tpl = openpyxl.load_workbook(str(TEMPLATE_LOCAL), data_only=True)
# 양식_rev 시트 찾기
tpl_sheet_name = None
for name in tpl.sheetnames:
    if '양식' in name and 'rev' in name:
        tpl_sheet_name = name
        break
if not tpl_sheet_name:
    raise RuntimeError("양식_rev 시트 없음")
tpl_ws = tpl[tpl_sheet_name]

# 7열 양식 헤더 추출
headers = []
for col in range(1, 8):
    headers.append(tpl_ws.cell(row=7, column=col).value)
print(f"양식_rev 헤더 7열: {headers}")

# 양식_rev 전체 복제
def copy_sheet_template(src_ws, target_ws):
    for row in src_ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                target_ws.cell(row=cell.row, column=cell.column, value=cell.value)
    for col_letter, col_dim in src_ws.column_dimensions.items():
        target_ws.column_dimensions[col_letter].width = col_dim.width
    for row_idx, row_dim in src_ws.row_dimensions.items():
        target_ws.row_dimensions[row_idx].height = row_dim.height

# 출금 DB 로드
conn = sqlite3.connect(str(SRC)); cur = conn.cursor()
cur.execute("SELECT payment_id, allocation_target, amount_krw, service_start_on, service_end_on, merchant, target_match_status FROM draft_rows ORDER BY allocation_target, service_start_on")
rows = cur.fetchall()
print(f"draft_rows: {len(rows)}건")

# 48탭 워크북 생성
wb_out = openpyxl.Workbook()
wb_out.remove(wb_out.active)
total = 0
by_trip = {}
for r in rows:
    by_trip.setdefault(r[1], []).append(r)

for trip in auth:
    code = trip['trip_code']
    sheet_name = (f"{code}_{trip['starts_on']}")[:31] if code == '2025_종결_권위' else code[:31]
    ws = wb_out.create_sheet(title=sheet_name)
    copy_sheet_template(tpl_ws, ws)
    # 9행부터 데이터 입력 (8행은 0행 비워둠)
    data_rows = by_trip.get(code, [])
    for i, r in enumerate(data_rows):
        # r = (payment_id, allocation_target, amount_krw, service_start_on, service_end_on, merchant, status)
        pid, _, amt, ss, se, mer, status = r
        if status == 'review_needed':
            continue
        # 양식_rev 7열 매핑
        ws.cell(row=9+i, column=1, value=ss)  # 거래일자 (체크인)
        ws.cell(row=9+i, column=2, value=f"고객{pid}")  # 이름
        ws.cell(row=9+i, column=3, value="")  # 닉네임
        ws.cell(row=9+i, column=4, value="영수증" if mer in ('아고다_나이스','AGODA_NICE-Agoda') else mer[:20])  # 증빙
        ws.cell(row=9+i, column=5, value=amt)  # 단가
        ws.cell(row=9+i, column=6, value=0)  # 추가금
        ws.cell(row=9+i, column=7, value=f"=E{9+i}+F{9+i}")  # 금액(수식)
    total += len(data_rows)

# 기타비용 시트
ws_other = wb_out.create_sheet(title="기타비용")
copy_sheet_template(tpl_ws, ws_other)
ws_other.cell(row=9, column=1, value="2025-Q2")
ws_other.cell(row=9, column=2, value="기타비용")
ws_other.cell(row=9, column=4, value="영수증")
ws_other.cell(row=9, column=5, value=407507688)
ws_other.cell(row=9, column=7, value="=E9+F9")

# 저장
wb_out.save(str(OUT))
print(f"생성: {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
print(f"탭 수: {len(wb_out.sheetnames)}")
print(f"총 데이터 행: {total}")
