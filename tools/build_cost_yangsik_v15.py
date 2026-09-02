import pathlib, json, sqlite3, openpyxl, csv
from openpyxl.styles import Font
import sys
sys.path.insert(0, r"C:\AX\cost")
from ledger.domain.direct_trip_schedule_authority import load_document

TEMPLATE = pathlib.Path(r"C:\Users\kkokk\AppData\Local\Temp\opencode\ledger_full.xlsx")
SRC = pathlib.Path(r"C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite")
AUTH = pathlib.Path(r"C:\AX\cost\ledger\data\trip_schedule_authority_v3.json")
CLASSIFIED = pathlib.Path(r"C:\AX\cost\ledger\data\classified_v12.csv")
MERCHANT_JSON = pathlib.Path(r"C:\Users\kkokk\AppData\Local\Temp\opencode\merchant_map_v15.json")
OUT = pathlib.Path(r"C:\AX\cost\outputs\법인경리_비용_전체_5328_48tabs_v15_20260901.xlsx")

# load merchant map
existing = {
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
    'AGODA                    TOKYO': '아고다-도쿄',
    'BKG*Booking.com Hotel  Amsterdam': '부킹닷컴-암스테르담',
    'BKG*BOOKING.COM HOTEL': '부킹닷컴',
    'KLOOK': '클룩',
    'Mytrip': '마이트립','mytrip': '마이트립',
    '트립닷컴(구)_NICE': '트립닷컴','트립닷컴(ARS)_나이스': '트립닷컴(ARS)','TRIP.COM': '트립닷컴','Trip.com': '트립닷컴',
    'Trip.com                 Tokyo        JP': '트립닷컴-도쿄','Trip.com                 Tokyo': '트립닷컴-도쿄',
    '아고다_나이스': '아고다(나이스)','하나투어-트립닷컴': '하나투어-트립닷컴',
    'FAMILYMART               Tokyo        JP': '패밀리마트','LAWSON                   Tokyo        JP': '로손','SEVEN-ELEVEN             Tokyo': '세븐일레븐','SEVEN-ELEVEN             Tokyo        JP': '세븐일레븐',
    'SQ*KAMIKURA              OKAYAMA': '스퀘어-카미쿠라','FUKUTAKE FOUNDATION': '후쿠타케재단','HOTELGOZENSUI            Tokyo        JP': '고젠스이호텔','FORESTHOTELANNEX         Aomori       JP': '포레스트호텔','EN HOSPITALITY': 'EN호스피탈리티','HOTELAREAONEHIROSHIMAWING': '아레아원호텔',
    'KYUKAMURA OHKUNOSHIMA    0846-26-0323': '큐카무라-오쿠노시마','HIROSHIMAKENNRITUBIZYU   HIROSHIMA    JP': '히로시마현립미술관','HIROSHIMAKENRITSUBIJUT': '히로시마현립미술관','SONCHONOMISE             HIROSHIMA': '손초노미세','ROUTE-INN GRANTIA HANYU S': '루트인그런티아','MEIJITEI                 KITASAKU-GUN': '메이지테이','YAMAHEI                  NAGANO': '야마헤이','MAMPEI HOTEL             Tokyo': '만페이호텔','RITSURIN GARDEN          KAGAWA       JP': '릿스린가든',
}
if MERCHANT_JSON.exists():
    j=json.loads(MERCHANT_JSON.read_text(encoding='utf-8'))
    existing.update(j.get("full_map_additions",{}))

def korean_name(mer):
    if not mer: return ''
    s=mer.strip()
    if s in existing: return existing[s]
    for k,v in existing.items():
        if k in s or s in k:
            return v
    if 'TOKYO' in s: return s.split()[0][:12]+'-도쿄'
    if 'JP' in s: return s.split()[0][:12]+'-일본'
    return s[:20]

# load classified for C열 mapping: key = (use_date, krw, merchant_prefix)
classified_map={}
if CLASSIFIED.exists():
    with open(CLASSIFIED, encoding='utf-8', errors='replace') as f:
        r=csv.DictReader(f)
        for row in r:
            key=(row['use_date'], row['krw'], row['merchant'][:12])
            # keep first user
            if key not in classified_map and row['user']:
                classified_map[key]=row['user']

# load authority for titles
auth_loaded,_=load_document(AUTH)
trip_info={}
for rec in auth_loaded:
    code=rec.trip_code
    start=rec.starts_on.isoformat()  # 2026-04-04
    end=rec.ends_on.isoformat()
    # month from start
    month=int(start.split("-")[1])
    # region from code suffix
    region=code.split("_",1)[1] if "_" in code else code
    trip_info[code]={"start": start, "end": end, "month": month, "region": region}

# template: use sheet index 2 (0404) for headers
wb_tpl = openpyxl.load_workbook(str(TEMPLATE), data_only=True)
ws_tpl = wb_tpl.worksheets[2]  # 0404_에히메 position
print(f"template sheet index 2 title={ws_tpl.title}")

conn=sqlite3.connect(str(SRC)); cur=conn.cursor()
cur.execute("SELECT id, merchant, amount_krw, occurred_on FROM payment_transactions")
rows=cur.fetchall()
by_trip={}
for pid, mer, amt, occ in rows:
    matched=None
    for rec in auth_loaded:
        if rec.starts_on.isoformat() <= occ <= rec.ends_on.isoformat():
            matched=rec.trip_code
            break
    if not matched:
        matched='2025_종결_권위' if occ.startswith('2025') else '기타비용'
    by_trip.setdefault(matched, []).append((pid, mer, amt, occ))

wb_out=openpyxl.Workbook()
wb_out.remove(wb_out.active)
for trip, lst in sorted(by_trip.items()):
    ws=wb_out.create_sheet(title=trip[:31])
    # copy rows 1-8 from template (A-J)
    for row in range(1,9):
        for col in range(1,11):
            v=ws_tpl.cell(row=row, column=col).value
            if v is not None:
                ws.cell(row=row, column=col, value=v)
                if row==7 and v:
                    ws.cell(row=row, column=col).font = Font(bold=True)
    # fix title row 2
    info=trip_info.get(trip)
    if info:
        mm=info["month"]
        region=info["region"]
        s=info["start"]  # 2026-04-04
        e=info["end"]
        # format MMDD
        smmdd=s[5:7]+s[8:10]
        emmdd=e[5:7]+e[8:10]
        ws['B2'] = "숲길여행"
        ws['C2'] = f"2026년 {mm}월 매출 확인자료_{region}_{smmdd}_{emmdd}"
    else:
        ws['B2'] = "숲길여행"
        ws['C2'] = trip
    # data from row 9
    for i,(pid, mer, amt, occ) in enumerate(lst):
        r=9+i
        ws.cell(row=r, column=2, value=occ)  # B 거래일자
        # C 이름: try classified mapping
        key=(occ, str(amt), mer[:12])
        user=classified_map.get(key, "")
        # fallback: try without merchant
        if not user:
            # search any classified with same date+amount
            for k,v in classified_map.items():
                if k[0]==occ and k[1]==str(amt):
                    user=v
                    break
        if user:
            ws.cell(row=r, column=3, value=user)  # C 이름
        else:
            ws.cell(row=r, column=3, value="")  # leave empty if no mapping
        # D 닉네임 empty
        ws.cell(row=r, column=5, value=korean_name(mer))  # E 증빙
        ws.cell(row=r, column=6, value=amt)  # F 단가
        ws.cell(row=r, column=7, value=0)  # G 추가금
        ws.cell(row=r, column=8, value=f"=F{r}+G{r}")  # H 금액 수식

wb_out.save(str(OUT))
print(f"생성: {OUT} ({OUT.stat().st_size/1024:.0f} KB, {len(wb_out.sheetnames)}시트) C열매핑 {len([k for k in classified_map])}건")
# also save stats
stats={"sheets": len(wb_out.sheetnames), "total_payments": len(rows), "by_trip": {k: len(v) for k,v in by_trip.items()}, "merchant_mapped": len(existing), "classified_keys": len(classified_map)}
pathlib.Path(r"C:\Users\kkokk\AppData\Local\Temp\opencode\v15_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
