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

2026-07-24 추가: 원장(수기장부) 전수조사(Q2 13개 여행탭 지출내용 예약번호 138건 대조) 결과, 아래
4건은 이미 "메일확정" 경로로 정확히 배치돼 있었으나(카드거래=원장 예약번호 금액 일치 확인), 엔진의
수기 매칭 소스(manual_v3/v4.csv)가 원장과 동기화가 안 돼 "미입력(수기장부 없음)" 태그가 잘못 남아
있었다. 태그만 교정(배치·금액은 원래부터 정확했음, 이중계상 아님):
  · KBO-0360  222,217  0620_묘코 AGODA LOTTE ARAI(원장 예약1740166023, 22,734엔) — 원장에 날짜·KRW
    환산 누락(작성중 추정)이라 manual_v3.csv 자동추출 대상에서 빠졌음.
  · KBD-0377/KBD-0384/HAN-0512  0630_오제 트립닷컴 Daiwa Link Hotel 3건(예약1400826994473108·
    1400827050342414·1400826994474326) — 원장 0630_오제 지출내용에 동일 예약번호로 정상 존재.
전수조사에서 발견됐으나 **수정 불가(사용자 확인 필요)**: 원장 `0417_아오모리` 지출내용에 FORESTHOTELANNEX
예약 2건(1669457233·1669459410)이 날짜·금액·카드 전부 공란으로 남아있음 — 대응 카드거래를 특정할 금액이
없어 자동 배치 불가. 원장에 직접 확정 정보를 채워야 함.
"""
import csv, json, re

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

# 원장 예약번호 재대조로 확인된 "미입력" 잔존태그 교정(2026-07-24 전수조사, uid: 예약번호)
CONFIRMED_BOOK={'KBO-0360':'1740166023','KBD-0377':'1400826994473108',
                'KBD-0384':'1400827050342414','HAN-0512':'1400826994474326'}
conf=0
for r in rows:
    b=CONFIRMED_BOOK.get(r['uid'])
    if not b: continue
    n=r['note'] or ''
    if '미입력' not in n: continue
    r['note']=re.sub(r'\s*\|\s*미입력(추정)?\(수기장부 없음\)', '', n)+f' | ⇄원장확인:예약{b} 재대조'
    if r['tax_conf'] in ('중','하'): r['tax_conf']='상'
    conf+=1

with open('data/classified_v14.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(rows)

def i(x):
    try: return round(float(str(x).replace(',','') or 0))
    except: return 0
tot=sum(i(r['krw']) for r in rows)
print('patch_v14: 복원 %d건, 말라르노트 %d, 전용진계정 %d건, 미입력잔존태그교정 %d건 → %d행 krw합 %s'%(added, mal, jy, conf, len(rows), format(tot,',')))
