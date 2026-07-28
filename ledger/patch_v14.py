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
import csv, json, re

RESTORE={
    'MAN-FALAISE','MERC-342280','MERC-556929',
    'MAN-OZE-LODGE-3472049',
    # ★APA 가나자와 합산청구 분해(사용자 확정 2026-07-29 + fable·gpt-5.6-sol 반박검증 절차):
    #   수기장부는 예약번호별 571,962원 4행, 카드는 KBO-2755 1건(¥241,920=2,287,848)으로 합산청구.
    #   엔진(build_v13_trip)은 `sd>=4/1 and not is_prepay`면 "base에 이미 존재"로 보고 skip하는데
    #   이 4개 예약번호는 base 예약참조집합(book_in)에 없음이 실측 확인돼 근거 없는 skip이었다.
    #   → 4행을 모두 보존하고(1721756989는 엔진이 TRIP-0166으로 편입), 합산청구 카드행은
    #     APA_LINKED_UID로 연결처리해 이중계상을 제거한다.
    'APA-1721758806','APA-1721757952','APA-1721761805',
}
# 합산청구 카드이벤트 → 분해행 연결. 카드이벤트는 삭제하지 않고 금액만 0으로 두어
# 이중계상을 막되, 원 청구액·외화·승인정보는 extra/note에 보존한다(불변규칙 1).
APA_LINKED_UID='KBO-2755'
APA_COMPONENTS=('1721756989','1721758806','1721757952','1721761805')
APA_TAB='0424_알펜루트'
MALAR_NOTE=('⇄수기:HOTEL MALAR.VPC | 파리 7구 Hotel Malar 549EUR | '
            '예약1400826104587865(트립닷컴 말라르 6/7~10, 582.18유로=VPC객실+현장세금 합산)')
KOMAGANE_BOOKING='1400824130566434'

rows=list(csv.DictReader(open('data/classified_v14.csv',encoding='utf-8')))
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

# APA 가나자와 합산청구 연결처리: 카드이벤트 KBO-2755는 분해 4행과 같은 돈이므로 금액을 0으로
# 두고 연결표시만 남긴다. 행 자체·승인정보·원 청구액은 보존한다(카드이벤트 삭제 금지).
# 귀속 탭은 반박검증 절차 결과(fable 확신도 상 / gpt-5.6-sol 확신도 중, 양측 결론 유지)에 따라
# 수기장부 기재와 동일한 0424_알펜루트로 통일한다.
apa=0
for r in rows:
    if r['uid']!=APA_LINKED_UID: continue
    if '합산청구_연결' not in (r['status'] or ''):
        orig=str(r['krw']).strip()
        r['extra']=('card_krw=%s;foreign=%s %s'%(orig, r['foreign'], r['currency'])).strip()
        r['krw']='0'
        r['status']='합산청구_연결'
        r['note']=('⇄수기[%s]:APAHOTEL | APA호텔 ¥241,920 단체 숙박(가나자와) | '
                   '★합산청구 %s원 = 예약 %s (571,962×4)로 분해 계상 — 본 행은 연결표시로 금액 0, '
                   '원 청구액은 extra 보존. 귀속탭 판정 2026-07-29(반박검증 절차)'
                   % (APA_TAB, format(int(orig),','), '+'.join(APA_COMPONENTS)))
    r['bucket']=APA_TAB
    apa+=1
# 분해행 4건(엔진 편입 TRIP-0166 포함)의 귀속 탭도 동일하게 맞춘다.
for r in rows:
    if any(('예약'+b) in (r['note'] or '') for b in APA_COMPONENTS) and 'APA' in (r['merchant'] or '').upper():
        r['bucket']=APA_TAB

# 여행자보험 가입기간 반영(사용자 지시 2026-07-29: "트래블로버 메일에 가입기간이 있다면
# 파싱하고 여행배정 근거로 삼도록 해"). 근거는 ledger/build_insurance_periods.py 가
# 메일 본문의 `보험기간 YYYY-MM-DD ~ YYYY-MM-DD` 를 파싱해 만든 검증값이며,
# 카드 금액이 메일 보험료와 **정확히 일치**하고 동일 보험료 메일이 유일할 때만 채택된다.
#   · 기간 표기는 note 에 붙인다.
#   · 귀속 탭이 다르면(suggested_tab_mmdd) 해당 MMDD 로 시작하는 실재 탭이 **유일할 때만** 옮긴다.
try:
    ins_periods=json.load(open('data/insurance_periods_verified.json',encoding='utf-8'))
except FileNotFoundError:
    ins_periods={}
ins_note=ins_move=0
_buckets={r['bucket'] for r in rows}
for r in rows:
    info=ins_periods.get(r['uid'])
    if not info: continue
    marker='보험기간%s'%info['period']
    if marker not in (r['note'] or ''):
        r['note']=((r['note'] or '')+' | %s(%s, 메일 본문 확정)'%(marker, info.get('destination') or '')).strip(' |')
        ins_note+=1
    mmdd=info.get('suggested_tab_mmdd')
    if mmdd:
        hits=sorted(b for b in _buckets if b.startswith(mmdd+'_'))
        if len(hits)==1 and r['bucket']!=hits[0]:
            r['note']=(r['note'] or '')+' | 귀속변경 %s→%s(보험기간 근거, 2026-07-29)'%(r['bucket'], hits[0])
            r['bucket']=hits[0]; ins_move+=1

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
print('patch_v14: 복원 %d건, 말라르노트 %d, 고마가네예약 %d건, OTA검증연결 %d건, APA합산연결 %d건, 보험기간 %d건(귀속변경 %d), 전용진계정 %d건 → %d행 krw합 %s'%(added, mal, komagane, ota_enriched, apa, ins_note, ins_move, jy, len(rows), format(tot,',')))
