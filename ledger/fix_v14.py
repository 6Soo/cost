# -*- coding: utf-8 -*-
"""trip-first 교정: classified_v13 → v14.
①TRIP중복(base와 여행탭+가맹 동일) → 병합(TRIP행 제거, base에 병합표시)
②계정 업종 재분류(카드 대조)  ③빈 use_date 카드 이용일로 보완  ④취소 orig_appr 승인번호 페어링"""
import csv, re
from collections import defaultdict, Counter
from cardindex import build_cards, account, i, d10

cards=build_cards()
# 카드 조회: 승인번호별, (카드사,금액)별
by_appr={}; by_coamt=defaultdict(list)
for c in cards:
    if c['appr']: by_appr.setdefault((c['co'],c['appr']),c)
    by_coamt[(c['co'],abs(c['krw']))].append(c)
CO={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업','MAN':''}
def find_card(row):
    co=CO.get(row['src'],'')
    ap=re.sub(r'\D','',row.get('appr') or '')
    if ap and (co,ap) in by_appr: return by_appr[(co,ap)]
    cand=by_coamt.get((co,abs(i(row['krw']))),[])
    if not cand: return None
    # 이용일 근접 우선
    ud=row.get('use_date') or ''
    if ud:
        cand=sorted(cand,key=lambda c:abs((c['use']>ud)-(c['use']<ud)) if c['use'] else 9)
    # 가맹 유사 우선
    mm=re.sub(r'[^A-Z0-9가-힣]','',(row['merchant'] or '').upper())[:8]
    for c in cand:
        if mm and mm[:5] in re.sub(r'[^A-Z0-9가-힣]','',c['mer'].upper()): return c
    return cand[0]

rows=list(csv.DictReader(open('data/classified_v13.csv',encoding='utf-8')))
FN=list(rows[0].keys())
base=[r for r in rows if not r['uid'].startswith('TRIP-')]
trip=[r for r in rows if r['uid'].startswith('TRIP-')]

# ① TRIP 중복 제거(병합): base에 같은 여행탭+가맹점명+금액(±2%) 존재해야만 병합.
#    ★사용자 지적 실사고(KBO-2665 vs TRIP-0023): 같은 호텔 다객실 예약이 금액까지 근접(102,958 vs 104,092, 1.3%차)해
#    가맹+금액만으로 오매칭 → 실거래(TRIP-0023, 예약1694237901, 102,958)가 통째로 삭제되는 사고 발생.
#    **양쪽 다 예약번호가 있는데 서로 다르면 절대 병합 금지**(예약번호 최우선 진실).
def mk(m): return re.sub(r'[^A-Z0-9가-힣]','',(m or '').upper())[:12]
def bookno(note):
    m=re.search(r'예약\s*(\d{6,}|[A-Z0-9]{5,7})', note or '')
    return m.group(1) if m else ''
base_by_bucket=defaultdict(list)
for r in base: base_by_bucket[r['bucket']].append(r)
merged=0; kept=[]; blocked_by_book=0
for t in trip:
    a=abs(i(t['krw'])); tm=mk(t['merchant']); tb=bookno(t['note']); dup=None
    for b in base_by_bucket[t['bucket']]:
        if mk(b['merchant'])!=tm or abs(abs(i(b['krw']))-a)>max(2000,a*0.02): continue
        bb=bookno(b['note'])
        if tb and bb and tb!=bb: continue   # 예약번호 상충 → 다른 거래, 병합 금지
        dup=b; break
    if dup:
        if '수기병합' not in (dup['note'] or ''):
            rowtag_m=re.match(r'수기(\d+)행\s*\|', t['note'] or '')
            prefix='수기%s행 | '%rowtag_m.group(1) if rowtag_m else ''
            dup['note']=prefix+(dup['note'] or '')+' | 수기병합(일부기입)'
        merged+=1
    else:
        kept.append(t)
print('①TRIP중복→병합(가맹+금액+예약번호검증):', merged,'건 제거 / 잔여 TRIP', len(kept))

# ①B TRIP↔TRIP 수기 자체 중복입력 dedup (오제 등 in-progress 이중입력).
#     같은 여행탭·같은 금액·같은 desc핵심(사람이름/예약)=중복. 정상 다건(묘코 다른사람 ×5)은 desc가 달라 보존.
def desc_core(note):
    m=re.search(r'반영\([^)]*\)\s*\|\s*(.+)$', note or '')
    d=m.group(1).strip() if m else ''
    d=re.sub(r'항공_|숙박_|료칸_|렌터카_|교통_|입장_','',d)           # 카테고리 접두 제거
    d=re.sub(r'_?환불$|_?취소$','',d)                                # 환불/취소 접미 제거(부분환불 매칭용)
    d=re.sub(r'예약[A-Za-z0-9]+','',d)                              # 예약번호 제거
    d=re.sub(r'\d{4}_\d{4}|\d{6,}|\d{4}','',d)                     # 날짜·번호 제거
    return re.sub(r'[\s_]','',d)                                    # 공백 제거→사람이름 핵심
seen_key=set(); kept2=[]; dd=0; ddtot=0
for t in sorted(kept, key=lambda z:z['uid']):
    core=desc_core(t['note']); a=abs(i(t['krw'])); cx=str(t.get('cancel')).lower() in ('true','1')
    key=(t['bucket'], a, cx, core)
    if core and key in seen_key:      # 동탭·동액·동일 사람/예약 = 중복입력
        dd+=1; ddtot+=i(t['krw']); continue
    seen_key.add(key); kept2.append(t)
print('①B 수기 중복입력 dedup:', dd,'건 제거 (순액', format(ddtot,'+,'),')')
kept=kept2

# ①C 카드 정확금액 초과 dedup: 카드건(국민/하나/기업) 중 (카드사,정확금액,취소)가 카드원본 건수 초과 → 제거.
#    단 카드건수≥1일 때만(0이면 승인/청구 변형일 수 있어 보존). 정상 다건은 카드도 다건이라 보존.
#    ★base 선소비: base가 이미 쓰는 슬롯을 tripseen에 미리 반영(부산 하나건 등 base⇄수기 매칭 완료건을 TRIP이 재추가하는 이중계상 방지).
card_exact=Counter((c['co'],abs(c['krw']),c['cancel']) for c in cards)
tripseen=Counter(); kept3=[]; dd2=0; dd2tot=0
for b in base:
    bco=CO.get(b['src'],'')
    if bco:
        bk=i(b['krw'])
        if bk: tripseen[(bco,abs(bk),bk<0)]+=1
for t in sorted(kept, key=lambda z:z['uid']):
    co=CO.get(t['src'],'')
    if co and t['src']!='MAN':
        cx=str(t.get('cancel')).lower() in ('true','1'); a=abs(i(t['krw']))
        k=(co,a,cx); tripseen[k]+=1; cc=card_exact.get(k,0)
        if cc>=1 and tripseen[k]>cc:
            dd2+=1; dd2tot+=i(t['krw']); continue
    kept3.append(t)
print('①C 카드 정확초과 dedup:', dd2,'건 제거 (순액', format(dd2tot,'+,'),')')
kept=kept3

allrows=base+kept
# 카드 (카드사,금액,가맹prefix) 정밀 조회 — 날짜보완용(금액+가맹 동시일치만)
by_coamt_mer=defaultdict(list)
for c in cards: by_coamt_mer[(c['co'],abs(c['krw']))].append(c)
def card_by_mer_amt(row):
    co=CO.get(row['src'],''); a=abs(i(row['krw']))
    tm=re.sub(r'[^A-Z0-9가-힣]','',(row['merchant'] or '').upper())[:6]
    hit=[c for c in by_coamt_mer.get((co,a),[]) if tm and tm in re.sub(r'[^A-Z0-9가-힣]','',c['mer'].upper())]
    return hit[0] if len(hit)==1 else (hit[0] if hit else None)

# ②③④ — base는 절대 안 건드림. TRIP(kept)만 교정
acc_fixed=0; date_fixed=0; orig_set=0
for r in kept:
    # 수기 내용(desc) = note의 '| ' 뒤
    m=re.search(r'반영\([^)]*\)\s*\|\s*([^|]+)', r['note'] or '')
    desc=(m.group(1).strip() if m else '')
    desc=re.sub(r'\s*예약.*$','',desc)
    # ② 계정: 카드 업종 없이 가맹+수기내용으로 (person이름→항공 등)
    newacc=account('', r['merchant'], desc)
    if newacc!='기타' and newacc!=r['account']:
        r['account']=newacc; acc_fixed+=1
    # ③ 빈 날짜: 가맹+금액 동시일치 카드의 이용일로만
    if not r['use_date']:
        cm=card_by_mer_amt(r)
        if cm and cm['use']: r['use_date']=cm['use']; date_fixed+=1
    # ④ 취소행 orig_appr: ★승인번호 기준(사용자 확정 규칙) — 카드 취소전표의 괄호 원승인(국민)·동일행 승인(하나)만.
    #    가맹+금액으로 찾은 카드가 취소전표일 때 그 orig를 사용. orig 없는 카드사(기업·국민해외)는 연결하지 않음.
    if str(r.get('cancel')).lower() in ('true','1') and not r.get('orig_appr'):
        cm=card_by_mer_amt(r)
        if cm and cm.get('cancel'):
            og=cm.get('orig','') or (cm['appr'] if cm.get('src')=='HAN' else '')
            if og: r['orig_appr']=og; r['appr']=r['appr'] or cm['appr']; orig_set+=1
print('②TRIP계정교정',acc_fixed,'③TRIP날짜보완',date_fixed,'④TRIP취소원거래연결',orig_set)

# ⑤ 취소 계정 승계(원장 v46): 취소행 계정이 불명확(기타/숙박 기본)이면 원거래(같은탭·양수·동액) 계정 물려받음
pos_by=defaultdict(list)
for r in allrows:
    if str(r.get('cancel')).lower() not in ('true','1') and i(r['krw'])>0:
        pos_by[(r['bucket'],abs(i(r['krw'])))].append(r)
# ⑤(폐기, 엔진 재점검): 동액 기반 계정승계는 우연 동액 오승계 위험 — 승인번호 페어 승계(⑦f)로 대체됨
print('⑤취소 계정승계: 폐기(⑦f 승인번호 페어로 대체)')

# ⑥ 원거래 없는 취소 → 카드 원본에서 원거래(양수·동액·**동일 브랜드**) 찾아 양수행 추가(net-0 쌍)
#    사용자 지적: 트립닷컴↔마이트립은 별개회사인데 금액만으로 묶여 오매칭됨(ORIG-0003).
#    브랜드 불일치 또는 후보 승인번호가 base에 이미 있으면(=기존 실거래 도용) 팬텀 생성 금지.
def brand(m):
    u=(m or '').upper()
    for pat,tag in [('BOOKING','부킹'),('BKG','부킹'),('부킹','부킹'),('AGODA','아고다'),('아고다','아고다'),
                     ('마이트립','마이트립'),('MYTRIP','마이트립'),('TRIP.COM','트립닷컴'),('트립닷컴','트립닷컴'),('TRIP','트립닷컴'),
                     ('고투게이트','고투게이트'),('GOTOGATE','고투게이트'),('스카이티켓','스카이티켓'),('SKYTICKET','스카이티켓'),
                     ('제주항공','제주항공'),('대한항공','대한항공'),('아시아나','아시아나'),('ANA','ANA'),('진에어','진에어')]:
        if pat in u: return tag
    return re.sub(r'[0-9\s()]','',u)[:6]
base_appr_used=set(r.get('appr','') for r in base if r.get('appr'))
pos_key=defaultdict(int)
for r in allrows:
    if str(r.get('cancel')).lower() not in ('true','1') and i(r['krw'])>0:
        pos_key[(r['bucket'],abs(i(r['krw'])))]+=1
# 같은 탭·같은 예약(desc핵심) 양수 존재 = 부분환불(원거래가 다른 금액으로 이미 있음) → 그대로 둠(정당 차감), 팬텀탐색 대상 아님
pos_desc=defaultdict(list)
for r in allrows:
    if str(r.get('cancel')).lower() not in ('true','1') and i(r['krw'])>0:
        c=desc_core(r['note']) if r['uid'].startswith(('TRIP-','ORIG-')) else ''
        if c: pos_desc[(r['bucket'],c)].append(r)
paired=[]; pn=0; drop_uids=set(); unresolved=[]; partial=0
for r in kept:
    if str(r.get('cancel')).lower() in ('true','1') and pos_key.get((r['bucket'],abs(i(r['krw']))),0)==0:
        rc=desc_core(r['note'])
        if rc and pos_desc.get((r['bucket'],rc)):
            partial+=1; continue   # 부분환불: 원거래(다른 금액)가 이미 존재 → 손대지 않고 차감 유지
        a=abs(i(r['krw'])); co=CO.get(r['src'],''); rb=brand(r['merchant'])
        cand=[c for c in cards if not c['cancel'] and abs(c['krw'])==a and c['co']==co]
        cand=[c for c in cand if brand(c['mer'])==rb and c['appr'] not in base_appr_used]  # ★브랜드일치+base비도용
        if not cand:
            # 브랜드검증 원거래 못 찾음 → 국내12건 취소전표 선례와 동일하게 취소단독 방치 금지, 제외(양쪽 다 없던 걸로)
            drop_uids.add(r['uid']); unresolved.append(r); continue
        tm=re.sub(r'[^A-Z0-9가-힣]','',(r['merchant'] or '').upper())[:5]
        best=next((c for c in cand if tm and tm in re.sub(r'[^A-Z0-9가-힣]','',c['mer'].upper())), cand[0])
        pn+=1
        orow={k:'' for k in FN}
        orow.update(uid='ORIG-%04d'%pn, src=r['src'], use_date=best['use'], card4=r['card4'],
            merchant=best['mer'], country=r['country'], currency=r['currency'], foreign='0', krw=str(a),
            status='정상', bucket=r['bucket'], account=r['account'], cancel='False', cost_type='여행원가',
            vat_tag=r['vat_tag'], confidence='상',
            note='원거래 복원(취소쌍 net0, 브랜드일치확인) | %s'%(r['note'].split('|')[-1].strip() if '|' in r['note'] else ''),
            tax_conf='상', appr=best['appr'], orig_appr='')
        r['orig_appr']=orow['appr']
        paired.append(orow)
kept=[r for r in kept if r['uid'] not in drop_uids]
allrows=[r for r in allrows if r['uid'] not in drop_uids]   # ★버그수정: allrows는 kept 갱신 전에 고정됐었음, 실제 반영
print('⑥원거래 없는 취소', pn, '건 원거래 복원(브랜드일치) /', partial,'건 부분환불(원거래 다른금액 존재→차감유지)')
print('   브랜드검증 실패(원거래 불확실) →', len(unresolved),'건 양쪽 제외(국내12건 선례와 일관):', [(u['uid'],u['merchant'][:14],u['krw']) for u in unresolved])
allrows=allrows+paired

# ⑦ 나머지 안전 교정 (에이전트 감사 반영)
acc7=0; vat7=0; buk7=0
for r in allrows:
    n=r['note'] or ''
    # ⑦a 계정: 심우경=제주항공/마이트립 항공권, 함루=일식당(식비)  (net-0 취소쌍 표시교정)
    if r['uid'].startswith(('TRIP-','ORIG-')):
        if '심우경' in n and r['account']=='숙박비': r['account']='항공료'; acc7+=1
        if ('함루' in n or '함루' in (r['merchant'] or '')) and r['account']=='숙박비': r['account']='식비'; acc7+=1
    # ⑦b vat_tag 정규화: 비표준 '불공제_현금' → country로
    if r['vat_tag']=='불공제_현금':
        r['vat_tag']='불공제_국내' if r['country']=='KR' else '불공제_해외'; vat7+=1
    # 트래블로버 여행자보험(국내구매) → 불공제_국내
    if ('트래블로버' in (r['merchant'] or '') or '트래블로버' in n) and r['vat_tag']=='불공제_해외':
        r['vat_tag']='불공제_국내'; vat7+=1
    # ⑦c HAN-3089: OTA 실체 미확인(승인취소·미매입, 나가센도 예약 부재) → 여행_미배정 (에이전트2)
    if r['uid']=='HAN-3089' and r['bucket']=='0413_나가센도':
        r['bucket']='여행_미배정'
        r['note']=n+' | ⚠재배정: 승인302021 취소·미매입, 최종청구6/5(6월건), TOKYO=아고다청구지. 실체메일 소실→미배정'
        buk7+=1
    # HAN-3399/3400: 북해도 아고다 예약 부재(에이전트2) → 자동이동 말고 노트 플래그만
    if r['uid'] in ('HAN-3399','HAN-3400') and '재검토' not in n:
        r['note']=n+' | ⚠재검토(에이전트): 북해도 아고다예약 부재, 6월 묘코/아키타 권역 추정(메일 미검증)'
    # ⑦d 운전수당 → 인건비 (기사 수당, 실제 여행원가지만 숙박비 오분류)
    if '운전수당' in n and r['account']!='인건비':
        r['account']='인건비'; acc7+=1
print('⑦ 계정교정',acc7,'/ vat정규화',vat7,'/ 버킷·플래그',buk7)

# ⑦g base 취소행 승인번호 페어 보강: appr 비어있는 base 취소를 카드 취소전표(괄호 원승인)로 연결
base_cx_fixed=0
for r in allrows:
    if not r['uid'].startswith(('TRIP-','ORIG-')) and i(r['krw'])<0 and not (r.get('orig_appr') or '').strip():
        co=CO.get(r['src'],'')
        if co!='국민' or r['src']!='KBD': continue
        for c in cards:
            if c.get('src')=='KBD' and c.get('cancel') and c.get('orig') and abs(c['krw'])==abs(i(r['krw'])):
                if re.sub(r'[^A-Z0-9가-힣]','',(r['merchant'] or '').upper())[:5] in re.sub(r'[^A-Z0-9가-힣]','',c['mer'].upper()):
                    r['orig_appr']=c['orig']; r['appr']=(r['appr'] or c['appr']); base_cx_fixed+=1; break
print('⑦g base 취소 승인번호 보강:', base_cx_fixed)

# ⑦h 국민해외(KBO) 환불 페어링: 승인번호 없음 → 규칙 A2 '현지외화금액' 페어(사용자 방식 엔진화).
#    키=(카드4, 통화, |현지금액| 소수보존) 양수 원거래, 같은 버킷 우선, 소비형(1취소=1원거래).
#    합성 페어ID(KP####)를 원거래 appr(빈 경우)·취소 orig_appr에 부여 → 빌더가 원거래 바로 아래 배치.
def ff(x):
    try:
        v=round(float(str(x).replace(',','') or 0),2); return v
    except: return 0.0
kbo_pos=defaultdict(list)
for r in allrows:
    if r['src']=='KBO' and i(r['krw'])>0:
        kbo_pos[(r['card4'], r['currency'], abs(ff(r['foreign'])))].append(r)
kp=0; kbo_unpaired=[]
_kbo_used=set()
for r in allrows:
    if r['src']=='KBO' and i(r['krw'])<0 and not (r.get('orig_appr') or '').strip():
        key=(r['card4'], r['currency'], abs(ff(r['foreign'])))
        cand=[p for p in kbo_pos.get(key,[]) if id(p) not in _kbo_used]
        same_b=[p for p in cand if p['bucket']==r['bucket']] or cand
        if same_b:
            p=same_b[0]; _kbo_used.add(id(p)); kp+=1
            pid=p['appr'].strip() if (p.get('appr') or '').strip() else 'KP%04d'%kp
            p['appr']=pid; r['orig_appr']=pid
        else:
            kbo_unpaired.append(r)
print('⑦h KBO 현지외화 페어:', kp,'건 연결 / 원거래 기간밖(전기예약 등)', len(kbo_unpaired),'건')

# ⑦i 현금성(MAN) 부분환불 페어: 같은 버킷·같은 desc핵심(사람/예약) 양수에 합성ID 연결(배치용)
man_pos=defaultdict(list)
for r in allrows:
    if i(r['krw'])>0:
        c=desc_core(r['note'])
        if c: man_pos[(r['bucket'],c)].append(r)
man_amt=defaultdict(list)
for r in allrows:
    if i(r['krw'])>0:
        man_amt[(r['bucket'], mk(r['merchant']), abs(i(r['krw'])))].append(r)
mp=0; _mp_used=set()
for r in allrows:
    if r['src']=='MAN' and i(r['krw'])<0 and not (r.get('orig_appr') or '').strip():
        c=desc_core(r['note'])
        cand=[p for p in man_pos.get((r['bucket'],c),[]) if id(p) not in _mp_used] if c else []
        if not cand:   # 폴백: 같은 버킷·같은 가맹·동액 양수(완전취소쌍)
            cand=[p for p in man_amt.get((r['bucket'], mk(r['merchant']), abs(i(r['krw']))),[]) if id(p) not in _mp_used]
        if cand:
            p=cand[0]; _mp_used.add(id(p)); mp+=1
            pid=(p.get('appr') or '').strip() or 'MP%04d'%mp
            p['appr']=pid; r['orig_appr']=pid
print('⑦i 현금성 환불 페어(desc/동액):', mp,'건 연결')

# ⑦j 완전상쇄쌍 취소환불 격리(규칙4·P6): 페어ID로 연결된 원거래+취소 합이 0이면 여행탭에서 취소환불로 이동
pair_pos={}; pair_neg=defaultdict(list)
for r in allrows:
    ap=(r.get('appr') or '').strip(); og=(r.get('orig_appr') or '').strip()
    if i(r['krw'])>0 and ap: pair_pos.setdefault(ap,[]).append(r)
    if i(r['krw'])<0 and og: pair_neg[og].append(r)
moved=0
NT={'취소환불','전기예약_환불'}
for ap,poss in pair_pos.items():
    negs=pair_neg.get(ap,[])
    if not negs: continue
    for p in poss:
        if p['bucket'] in NT: continue
        if sum(i(n['krw']) for n in negs)+i(p['krw'])==0:
            p['bucket']='취소환불'
            for n2 in negs: n2['bucket']='취소환불'
            moved+=1+len(negs)
print('⑦j 완전상쇄쌍 취소환불 격리:', moved,'행 이동')

# ⑦f 취소 계정 승계(승인번호 페어): orig_appr로 연결된 원거래의 계정을 취소가 물려받음(원장 v46)
pos_ap={}
for r in allrows:
    if i(r['krw'])>0 and (r['appr'] or '').strip(): pos_ap[(r['appr'] or '').strip()]=r
inh2=0
for r in allrows:
    if i(r['krw'])<0 and (r['orig_appr'] or '').strip():
        p=pos_ap.get((r['orig_appr'] or '').strip())
        if p and p['account']!=r['account']:
            r['account']=p['account']; inh2+=1
print('⑦f 취소 계정승계(승인번호 페어):', inh2)

# ⑦e 카드이용대금 이체(정산성) 제외 — 회사카드 실결제와 이중계상(사용자 확정 "전자=제외")
before=len(allrows)
allrows=[r for r in allrows if '카드이용대금' not in (r['note'] or '')]
print('⑦e 카드이용대금 정산성 이체 제외:', before-len(allrows),'건')

# ⑦k 기업 승인취소 무청구 교정(엔진 전면 재점검 발견): A파일 '취소또는할인' 승인번호가 워크북에 양수로 반영된 4건
#    (CORP-2011 아고다 1,160,562·CORP-2043 11,595·CORP-2006 356,158·CORP-2005 356,418 = +1,884,733 과대).
#    승인취소=실청구 없음 → 무청구 관례(krw=0) 처리. 수기(아고다 2객실)가 옳았음.
corp_cx_appr={c['appr'].lstrip('0') for c in cards if c.get('src')=='CORP' and c.get('cancel')}
ck=0
for r in allrows:
    if r['src']=='CORP' and i(r['krw'])>0:
        ap=(r['appr'] or '').strip().lstrip('0')
        if ap and ap in corp_cx_appr:
            r['note']=(r['note'] or '')+' | ⚠승인취소(기업 취소또는할인)=무청구, 실청구 0 처리(원 %s원)'%format(i(r['krw']),',')
            r['krw']='0'; r['status']='승인취소'; ck+=1
print('⑦k 기업 승인취소 무청구 교정:', ck,'건')

# ⑦l 전수감사 발견 교정: ①아오모리 트립닷컴_그랜드 net0 취소쌍(수기122↙123행, 카드 30057825↔40901179) 복원—P6 취소환불
_has_grand=any('1400825417884289' in (r['note'] or '') for r in allrows)
if not _has_grand:
    for sgn,ap,og,st in [(1,'30057825','', '정상'),(-1,'','30057825','취소')]:
        nr={k:'' for k in FN}
        nr.update(uid='ORIG-0417G%s'%('P' if sgn>0 else 'N'), src='KBD', use_date='2026-04-20',
            card4='', merchant='트립닷컴_그랜드', country='KR', currency='KRW', foreign='0',
            krw=str(213274*sgn), status=st, bucket='취소환불', account='숙박비',
            cancel=str(sgn<0), cost_type='여행원가', vat_tag='불공제_해외', confidence='상',
            note='수기%d행 | 전수감사 복원: 그랜드 숙박 예약1400825417884289 완전취소쌍(net0, 카드 30057825↔40901179)'%(122 if sgn>0 else 123),
            tax_conf='상', appr=ap, orig_appr=og)
        allrows.append(nr)
    print('⑦l 아오모리 그랜드 net0 취소쌍 복원(+213,274/-213,274, 총액불변)')
# ②묘코 노트의 '추정 예약번호' 중복 표기 정리(감사기 오탐 방지: 예약번호는 확정건에만)
for r in allrows:
    if r['uid']=='KBO-2952' and '1737832515' in (r['note'] or ''):
        r['note']=r['note'].replace('예약1737832515, ','추정: ')

# ⑧ 수기장부 '2분기_기타비용' 시트 매칭 (사용자 지적: 이 시트에 기입한 건이 "수기장부 없음" 오판됨)
#    파서가 여행탭만 읽던 결함 보완. 매칭되면 성격=수기 우선(규칙1) → bucket 기타비용, 미입력추정 해제.
import openpyxl as _px, datetime as _dt
_lw=_px.load_workbook('data/ledger_current.xlsx',read_only=True,data_only=True)
_ws=_lw['2분기_기타비용']
etc_man=[]
for _ri,_r in enumerate(_ws.iter_rows(values_only=True),start=1):
    _r=list(_r)+[None]*10
    _d=_r[1]; _amt=_r[8]
    if isinstance(_d,(_dt.datetime,_dt.date)): _d=_d.strftime('%y.%m.%d')
    _d=str(_d or '')
    if not re.match(r"^'?\d{2}[.]\d{2}[.]\d{2}",_d): continue
    try: _a=int(round(float(str(_amt).replace(',',''))))
    except: continue
    etc_man.append(dict(row=_ri,date='20'+_d.replace('.','-'),item=str(_r[3] or '').strip(),
        desc=str(_r[5] or '').strip(),card=str(_r[7] or '').strip(),amt=_a))
SRC2CARD={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
def _sim(a,b):
    # 항목 유사: 정규화 후 한쪽 핵심(5자)이 다른쪽에 포함 (이니시스↔오륙도낙지 같은 딴회사 배제)
    na=re.sub(r'[^A-Z0-9가-힣]','',(a or '').upper()); nb=re.sub(r'[^A-Z0-9가-힣]','',(b or '').upper())
    return bool(na and nb and (na[:5] in nb or nb[:5] in na))
used_etc=set(); moved=0
for r in allrows:
    co=SRC2CARD.get(r['src'],'')
    a=abs(i(r['krw']))
    for e in etc_man:
        if e['row'] in used_etc: continue
        if e['card']!=co or e['amt']!=a: continue
        try: dd=abs((_dt.date.fromisoformat(r['use_date'])-_dt.date.fromisoformat(e['date'])).days)
        except: dd=99
        if dd>3: continue
        if not _sim(r['merchant'], e['item']): continue   # ★항목 유사 필수(금액·날짜 우연일치 배제)
        used_etc.add(e['row'])
        r['bucket']='기타비용'
        if not r['cost_type'] or r['cost_type']=='여행원가': r['cost_type']='판관비'
        n=(r['note'] or '').replace('미입력추정(수기장부 없음)','').strip(' |')
        r['note']='수기기타%d행 | ⇄수기기타:%s(%s) | %s'%(e['row'],e['item'],e['desc'],n)
        moved+=1; break
print('⑧ 수기 기타비용시트 매칭:', moved,'건 → 기타비용 이동·미입력해제 (시트', len(etc_man),'건 중)')

# ⑦n 카드 기명자 규칙(사용자 2026-07-21): 3820=김주형 기명법인카드(국내 상주).
#    국내결제(KBD)는 여행기간과 날짜가 겹쳐도 기타비용(판관비)이 기본 — 여행목적 결제(항공·보험·숙박·여행상품)만 여행탭 유지.
#    해외이용(KBO): 항공권=여행탭, 현지사용=답사여행→해당 일자 여행탭(유지).
TRIP_PURPOSE={'항공료','여행자보험','숙박비'}
def is_triptab(b): return bool(re.match(r'\d{4}_|\d{1,2}월_', b or ''))
n7=0
for r in allrows:
    if r['card4']=='3820' and r['src']=='KBD' and is_triptab(r['bucket']):
        if r['account'] in TRIP_PURPOSE: continue          # 항공·보험·숙박 등 여행목적 결제는 유지
        if '여행상품' in (r['note'] or ''): continue
        if re.search(r'⇄수기\[', r['note'] or '') or '트립닷컴' in (r['note'] or ''):
            # 수기장부가 이 여행탭에 기입·매칭한 건은 수기 우선(규칙 A1) — 이동 금지. 항공PG면 계정만 교정.
            if r['account'] not in TRIP_PURPOSE and ('트립닷컴' in (r['note'] or '') or '항공' in (r['note'] or '')):
                r['account']='항공료'
            continue
        old=r['bucket']; r['bucket']='기타비용'; r['cost_type']='판관비'
        if r['account'] in ('기타비용','식비'): r['account']='복리후생비'
        r['note']=(r['note'] or '')+' | 3820 김주형 기명카드 국내결제→기타비용(카드기명 규칙, 이전:%s)'%old
        n7+=1
print('⑦n 3820 기명카드 국내결제 기타비용 정정:', n7,'건')

# ⑦o 대장(가이드) 지급카드 → 전용 탭 분리(사용자 2026-07-21, 07-22 갱신): 5836=현수 / 4813=바로바로 / 8831=엘레나.
#    ★전달일 게이트: 8831은 2026-07 엘레나 전달 — 7/1 이전 사용분은 대장 구분 없이 일반 여행탭 유지.
LEADER_CARDS={'5836':('대장_현수',None),'4813':('대장_바로바로',None),'8831':('대장_엘레나','2026-07-01')}
n_o=0
for r in allrows:
    ent=LEADER_CARDS.get(r['card4'])
    lt = ent[0] if ent and (not ent[1] or (r.get('use_date') or '') >= ent[1]) else None
    if lt and r['bucket']!=lt:
        old=r['bucket']; r['bucket']=lt
        r['note']=(r['note'] or '')+' | 대장카드 전용탭 분리(이전:%s)'%old
        n_o+=1
print('⑦o 대장카드 전용탭 분리:', n_o,'건')

# ⑦m 태그 자기교정: '수기N행' 태그가 가리키는 실제 수기행과 (예약번호 또는 금액) 상충하면 태그 소거
#    (잘못된 참조는 무참조보다 해롭다 — 오제 _A시트 모호 등. 상설 전수감사와 짝을 이루는 자기치유)
_m4={}
try:
    for _r4 in csv.DictReader(open('data/manual_v4.csv',encoding='utf-8')):
        _t={'0630_오제_A':'0630_오제','0704_야마가타':'0704_아키타'}.get(_r4['tab'],_r4['tab'])
        _m4[(_t,_r4['row'])]=_r4
except FileNotFoundError: pass
tag_purged=0
for r in allrows:
    tg=re.match(r'수기(\d+)행 \| ', r['note'] or '')
    if not tg: continue
    mr=_m4.get((r['bucket'],tg.group(1)))
    if mr is None: continue   # 격리버킷 이동 등은 판정 불가 — 유지
    wb_bk=re.search(r'예약\s*(\d{6,19}|[A-Z0-9]{5,7})(?![0-9])', r['note'] or '')
    mn_bk=(mr.get('book') or '').strip()
    wa=abs(i(r['krw']));  ma=abs(i(mr['amount']))
    conflict=(wb_bk and mn_bk and wb_bk.group(1)!=mn_bk) or (ma and abs(wa-ma)>max(3000,ma*0.03))
    if conflict:
        r['note']=re.sub(r'^수기\d+행 \| ','',r['note']); tag_purged+=1
print('⑦m 상충 태그 소거:', tag_purged,'건')

with open('data/classified_v14.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(allrows)
tot=sum(i(r['krw']) for r in allrows)
print('classified_v14:',len(allrows),'행 krw합',format(tot,','),'(v13대비 병합제거로',format(tot-316386294,'+,'),')')
