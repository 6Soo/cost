import json, sys, hashlib
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')
from openpyxl import load_workbook
import re
q1_path=r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx"
auth_path="ledger/data/trip_schedule_authority_v3.json"
wb=load_workbook(q1_path, read_only=True, data_only=False)
YEAR_RE=re.compile(r'(\d{4})년')
DATE_RANGE_RE=re.compile(r'(?<![0-9])(\d{2})(\d{2})[_-](\d{2})(\d{2})(?![0-9])')

# workbook sha256 for source
import hashlib as hl
wb_sha=hl.sha256(open(q1_path,'rb').read()).hexdigest()

with open(auth_path, encoding='utf-8') as f:
    auth=json.load(f)
existing={r['trip_code'] for r in auth['records']}
print(f"existing {len(existing)}: {sorted(existing)[:5]}...")

new=[]
for name in wb.sheetnames:
    if "기타" in name or "총괄" in name:
        continue
    ws=wb[name]
    title=None
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        for v in row:
            if v and "매출 확인자료" in str(v):
                title=str(v)
                break
        if title:
            break
    if not title:
        print(f"skip {name}: no title")
        continue
    ym=YEAR_RE.search(title)
    rm=DATE_RANGE_RE.search(title)
    if not ym or not rm:
        print(f"skip {name}: parse fail title={title}")
        continue
    event_year=int(ym.group(1))
    sm,sd,em,ed=map(int, rm.groups())
    try:
        starts=date(event_year, sm, sd)
        end_year=event_year if (em,ed) >= (sm,sd) else event_year+1
        ends=date(end_year, em, ed)
    except ValueError as e:
        print(f"skip {name}: invalid date {e}")
        continue
    # canonical tab name logic same as manual_tab: strip suffix etc – use sheet name as trip_code
    trip_code=name
    if trip_code in existing:
        print(f"skip {trip_code}: already exists")
        continue
    # region from title: after _ and before _MMDD
    # title like "2026년 1월 매출 확인자료_대만_0107_0114"
    parts=title.split("_")
    region=parts[1] if len(parts)>=2 else ""
    # for titles like 0203_다카야마(고마츠)_0203_0207, region is parts[1] maybe?
    # better extract: between 매출 확인자료_ and _\d{4}_\d{4}
    m=re.search(r'매출 확인자료_(.+?)_\d{4}_\d{4}', title)
    if m:
        region=m.group(1)
    rec={
        "trip_code": trip_code,
        "event_year": event_year,
        "starts_on": starts.isoformat(),
        "ends_on": ends.isoformat(),
        "region": region,
        "authority_kind": "explicit_trip_registry",
        "source_locator": f"{q1_path}#sheets={name}",
        "source_sha256": wb_sha[:16],
        "authority_status": "authoritative",
        "end_semantics": "inclusive_last_service_date"
    }
    new.append(rec)
    print(f"ADD {trip_code} | {starts} ~ {ends} | {region}")

wb.close()
auth['records'].extend(new)
auth['records'].sort(key=lambda r: r['starts_on'])
with open(auth_path, 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)
print(f"\nadded {len(new)}, total {len(auth['records'])}")
