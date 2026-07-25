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

# 2026-06-13 이후는 AX 자동화를 위해 수기 기입을 의도적으로 최소화한 구간이다(P18).
# 수기 미기입만으로 저신뢰 처리하지 않으며, 카드·OTA·여행기간 같은 독립 근거를 쓴다.
post_ax=0
for r in rows:
    if (r.get('use_date') or '') < '2026-06-13':
        continue
    if (r.get('note') or '').strip() != '미입력추정(수기장부 없음)':
        continue
    r['note']='AX 자동화 구간(2026-06-13 이후): 수기 미기입은 정상; 카드·OTA 근거로 판정'
    if r.get('tax_conf') == '하':
        r['tax_conf']='중'
    post_ax+=1

# 사용자 확인 및 구조화 OTA 근거에 따른 귀속 교정.
for r in rows:
    if r.get('use_date')=='2026-06-30' and r.get('bucket')=='0625_아키타':
        r['bucket']='0630_오제'
        r['note']=(r.get('note') or '').strip(' |')+' | 사용자 확인: 2026-06-30 현지 결제는 0630_오제 귀속'
        if r['uid']=='HAN-0529':
            r['confidence']='상'; r['tax_conf']='중'
    elif r['uid']=='HAN-0517':
        r['bucket']='0625_아키타'
        r['confidence']='상'; r['tax_conf']='중'
        r['note']=('OTA 실증: SHONAI HOTEL SUIDEN TERRASSE 숙박_0625_0626 '
                   '예약 1696942614·1696943502·1696943284; 카드 승인 2026-06-26')

# KB 해외매입 원천에는 ANA AIRFOOOCM 412.57 USD/634,113원이 1행뿐이다.
# classified에만 생긴 두 번째 projection KBO-2863은 실거래가 아니므로 제거한다.
before_ana=len(rows)
rows=[r for r in rows if r['uid']!='KBO-2863']
for r in rows:
    if r['uid']=='KBO-2853':
        r['note']=re.sub(r'\s*\|\s*⚠동일일·동일액 2건.*$', '', r.get('note') or '')
print('P18 AX구간 수기미기입 단독 저신뢰 해제:', post_ax,
      '건; 2026-06-30 현지결제→0630_오제, HAN-0517→0625_아키타;',
      'ANA 원천초과 projection 제거:', before_ana-len(rows), '건')

with open('data/classified_v14.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(rows)

def i(x):
    try: return round(float(str(x).replace(',','') or 0))
    except: return 0
tot=sum(i(r['krw']) for r in rows)
print('patch_v14: 복원 %d건, 말라르노트 %d, 전용진계정 %d건 → %d행 krw합 %s'%(added, mal, jy, len(rows), format(tot,',')))
