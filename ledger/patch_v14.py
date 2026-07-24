# -*- coding: utf-8 -*-
"""classified_v14 재현가능 수기패치 (엔진 재작성 후, 2026-07-24).
엔진(build_v13_trip 옵션①·Q2필터제거·순액)이 자동편입하지 못하는 '수기 마스터' 잔여건만 복원.
  · 자동편입되어 스킵: 전용진 4,280,000(TRIP-0218), 진에어 30,000(TRIP-0346) — 재주입시 이중계상.
  · RF-TOYOKO(-94,641)는 원거래 +94,641과 net0 완전상쇄쌍인데 양쪽 다 리빌드에서 빠짐 → 순액 불변, 미복원.
복원 대상(카드/엔진으로 재현 불가한 확정 수기건):
  · MAN-FALAISE  241,350  팔레즈 현금영수증(무카드, 유로환산) — 5월_유럽
  · MERC-342280  342,280  국민8835 2/6 AGODA MERCURE(Q1선결제, 묘코 6월) — 수기 대조 확정
  · MERC-556929  556,929  국민8835 2/8 AGODA MERCURE(Q1선결제, 묘코 6월, 수기 r112) — 확정
  · RF-AIR1/2   -293,400×2 단체항공 1인취소 환불(수기 r75/r76, 원거래 TRIP-0377/0378 별개) — 순감
  · KBO-2882 말라르 예약번호 노트 재부착(트립닷컴 1400826104587865, 582.18유로)
"""
import csv, json

RESTORE={'MAN-FALAISE','MERC-342280','MERC-556929','RF-AIR1','RF-AIR2'}
MALAR_NOTE=('⇄수기:HOTEL MALAR.VPC | 파리 7구 Hotel Malar 549EUR | '
            '예약1400826104587865(트립닷컴 말라르 6/7~10, 582.18유로=VPC객실+현장세금 합산)')

rows=list(csv.DictReader(open('data/classified_v14.csv',encoding='utf-8')))
FN=list(rows[0].keys())
present={r['uid'] for r in rows}
special=json.load(open('data/manual_special_rows.json',encoding='utf-8'))

added=0
for s in special:
    if s['uid'] not in RESTORE or s['uid'] in present: continue
    rows.append({k:s.get(k,'') for k in FN}); added+=1

# 말라르 노트 재부착(리빌드에서 base note가 원복됨)
mal=0
for r in rows:
    if r['uid']=='KBO-2882' and '1400826104587865' not in (r['note'] or ''):
        r['note']=MALAR_NOTE; mal=1

# 전용진 자동편입행 계정 교정(TRIP-***, merchant 전용진 → 가이드정산; 숙박비 오분류 방지)
jy=0
for r in rows:
    if '전용진' in (r['merchant'] or '') and r['account'] in ('숙박비','기타비용') and float(str(r['krw']).replace(',','') or 0)>0:
        r['account']='가이드정산'; jy+=1

with open('data/classified_v14.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(rows)

def i(x):
    try: return round(float(str(x).replace(',','') or 0))
    except: return 0
tot=sum(i(r['krw']) for r in rows)
print('patch_v14: 복원 %d건, 말라르노트 %d, 전용진계정 %d건 → %d행 krw합 %s'%(added, mal, jy, len(rows), format(tot,',')))
