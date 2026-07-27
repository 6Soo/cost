# -*- coding: utf-8 -*-
"""classified_v14 재현가능 수기패치 (엔진 재작성 후, 2026-07-24).
엔진(build_v13_trip 옵션①·Q2필터제거·순액)이 자동편입하지 못하는 '수기 마스터' 잔여건만 복원.
  · 자동편입되어 스킵: 전용진 4,280,000(TRIP-0218), 진에어 30,000(TRIP-0346) — 재주입시 이중계상.
  · RF-TOYOKO(-94,641)는 원거래 +94,641과 net0 완전상쇄쌍인데 양쪽 다 리빌드에서 빠짐 → 순액 불변, 미복원.
복원 대상(카드/엔진으로 재현 불가한 확정 수기건):
  · MAN-FALAISE  241,350  팔레즈 현금영수증(무카드, 유로환산) — 5월_유럽
  · MERC-342280  342,280  국민8835 2/6 AGODA MERCURE(Q1선결제, 묘코 6월) — 수기 대조 확정
  · MERC-556929  556,929  국민8835 2/8 AGODA MERCURE(Q1선결제, 묘코 6월, 수기 r112) — 확정
  · RF-AIR1/2는 엔진이 원 카드 환불(TRIP-0374/0375)을 보존하므로 더 이상 별도 복원하지 않음.
  · MAN-OZE-LODGE-3472049 3,472,049 모인 이체(오제산장 숙박비) — 0630_오제
  · KBO-2882 말라르 예약번호 노트 재부착(트립닷컴 1400826104587865, 582.18유로)
"""
import argparse, csv, hashlib, json, re
from pathlib import Path
from domain.p0_release_guard import (
    validate_candidate_against_frozen_canonical,
    validate_frozen_stage,
)

RESTORE={
    'MAN-FALAISE','MERC-342280','MERC-556929',
    'MAN-OZE-LODGE-3472049',
}
MALAR_NOTE=('⇄수기:HOTEL MALAR.VPC | 파리 7구 Hotel Malar 549EUR | '
            '예약1400826104587865(트립닷컴 말라르 6/7~10, 582.18유로=VPC객실+현장세금 합산)')
KOMAGANE_BOOKING='1400824130566434'

parser=argparse.ArgumentParser()
parser.add_argument(
    '--input',
    type=Path,
    required=True,
    help='직전 fix_v14 후보 경로. 정본을 암묵적으로 다시 읽지 않습니다.',
)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
input_bytes=args.input.read_bytes()
input_sha=hashlib.sha256(input_bytes).hexdigest()
output_path=args.output or (
    Path('../outputs/20260728_pipeline_recovery')
    / ('classified_v15_candidate_%s.csv'%input_sha[:8])
)
if output_path.resolve()==args.input.resolve():
    raise RuntimeError('정본 인플레이스 덮어쓰기는 금지됩니다.')
if output_path.exists():
    raise FileExistsError('기존 후보를 덮어쓰지 않습니다: %s'%output_path)
_input_gate=validate_frozen_stage(Path(__file__).resolve().parents[1],'canonical_rebuild')

rows=list(csv.DictReader(args.input.open(encoding='utf-8')))
FN=list(rows[0].keys())
present={r['uid'] for r in rows}
special=json.load(open('data/manual_special_rows.json',encoding='utf-8'))
try:
    ota_links=json.load(open('data/ota_event_links_verified.json',encoding='utf-8'))
except FileNotFoundError:
    ota_links={}

added=0
for s in special:
    if s['uid'] not in RESTORE or s['uid'] in present: continue
    rows.append({k:s.get(k,'') for k in FN}); added+=1

# 말라르 노트 재부착(리빌드에서 base note가 원복됨)
mal=0
for r in rows:
    if r['uid']=='KBO-2882' and '1400826104587865' not in (r['note'] or ''):
        r['note']=MALAR_NOTE; mal=1

# 고마가네 4/14~15 숙박은 Gmail Trip.com 확정메일에서 동일 예약번호로 확인된 객실 분할결제 그룹.
# 동일금액 62,496원도 카드 원본이 2건이므로 두 행 모두 보존한다.
komagane=0
for r in rows:
    if r['bucket']=='0413_나가센도' and '고마가네' in (r['merchant'] or ''):
        if KOMAGANE_BOOKING not in (r['note'] or ''):
            r['note']=(r['note'] or '')+' | 예약%s(Trip.com Gmail 확정, 0414_0415 분할결제)'%KOMAGANE_BOOKING
        komagane+=1

# Gmail 등 원문에서 검증한 OTA 주문번호/PNR/기간을 UID 단위로 연결한다.
# 예약번호는 그룹키이며 카드 이벤트 PK(appr/uid)를 대체하거나 행을 합치는 데 사용하지 않는다.
ota_enriched=0
for r in rows:
    link=ota_links.get(r['uid'])
    if not link: continue
    ref=str(link.get('booking_id') or link.get('order_id') or link.get('pnr') or '').strip()
    pnr=str(link.get('pnr') or '').strip()
    period=str(link.get('period') or '').strip()
    category=str(link.get('category') or '').strip()
    linked_uid=str(link.get('linked_uid') or '').strip()
    additions=[]
    if ref:
        label='예약%s'%ref if ref.isdigit() else '예약코드%s'%ref
        if label not in (r['note'] or ''): additions.append(label)
    if pnr:
        label='PNR%s'%pnr
        if label not in (r['note'] or ''): additions.append(label)
    if period and re.fullmatch(r'\d{4}(?:_\d{4})?',period):
        marker='검증기간%s%s'%(('_'+category) if category else '', '_'+period)
        if marker not in (r['note'] or ''): additions.append(marker)
    if linked_uid:
        r['note']=re.sub(r'\s*\|\s*연결대기 환불\(원거래 미확인·삭제금지\)', '', r['note'] or '')
        marker='연결환불_%s'%linked_uid
        if marker not in (r['note'] or ''): additions.append(marker)
    if additions:
        r['note']=((r['note'] or '')+' | '+' | '.join(additions)).strip(' |')
    ota_enriched+=1

# 전용진 자동편입행 계정 교정(TRIP-***, merchant 전용진 → 가이드정산; 숙박비 오분류 방지)
jy=0
for r in rows:
    if '전용진' in (r['merchant'] or '') and r['account'] in ('숙박비','기타비용') and float(str(r['krw']).replace(',','') or 0)>0:
        r['account']='가이드정산'; jy+=1

_canonical_gate=validate_candidate_against_frozen_canonical(
    Path(__file__).resolve().parents[1],
    rows,
)
output_path.parent.mkdir(parents=True,exist_ok=True)
with output_path.open('x',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(rows)

def i(x):
    try: return round(float(str(x).replace(',','') or 0))
    except: return 0
tot=sum(i(r['krw']) for r in rows)
print('patch_v14: 입력 %s / 출력 %s / canonical_gate %s / 복원 %d건, 말라르노트 %d, 고마가네예약 %d건, OTA검증연결 %d건, 전용진계정 %d건 → %d행 krw합 %s'%(input_sha,output_path,_canonical_gate,added,mal,komagane,ota_enriched,jy,len(rows),format(tot,',')))
