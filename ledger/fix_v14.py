# -*- coding: utf-8 -*-
"""trip-first 교정: classified_v13 → v14.
①TRIP중복(base와 여행탭+가맹 동일) → 병합(TRIP행 제거, base에 병합표시)
②계정 업종 재분류(카드 대조)  ③빈 use_date 카드 이용일로 보완  ④취소 orig_appr 승인번호 페어링"""
import csv, re, os, json, datetime, sys, hashlib
from collections import defaultdict, Counter
from pathlib import Path
from cardindex import build_cards, account, i, d10
from domain.candidate_selection import (
    select_bidirectionally_unique_candidates,
    select_unique_candidate,
)
from domain.p0_release_guard import validate_frozen_stage
from domain.lineage_gates import (
    lineage_semantic_counts,
    require_protected_uids_preserved,
    require_raw_cancellation_signs,
    require_valid_nonposting_aliases,
)

DRY_RUN = '--dry-run' in sys.argv
if '--input' not in sys.argv:
    raise RuntimeError(
        '--input은 필수입니다. build_v13 후보 경로를 명시해 단계 연결을 증명하세요.'
    )
def _option_path(flag, default):
    try:
        return Path(sys.argv[sys.argv.index(flag)+1])
    except (ValueError, IndexError):
        return Path(default)

INPUT_PATH=_option_path('--input','data/classified_v13.csv')
_input_sha=hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest()
OUTPUT_PATH=_option_path(
    '--output',
    '../outputs/20260728_pipeline_recovery/classified_v14_candidate_%s.csv'
    % _input_sha[:8],
)
if OUTPUT_PATH.resolve()==INPUT_PATH.resolve():
    raise RuntimeError('입력 projection 인플레이스 덮어쓰기는 금지됩니다.')
_input_gate=validate_frozen_stage(Path(__file__).resolve().parents[1],'canonical_rebuild')
# Lossless policy: suspected duplicates remain visible and block review.  They
# are never deleted merely because amount/merchant/description counts overlap.
LOSSLESS_NO_DELETE = True

cards=build_cards()
# 카드 조회: 승인번호별, (카드사,금액)별
CO={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업','MAN':''}
    # 이용일 근접 우선
    # 가맹 유사 우선


def validate_source_lineage(rows, label):
    """Validate lossless event identity without inventing N:M pairings."""
    missing=[r.get('uid','') for r in rows if not r.get('source_event_id') or not r.get('source_event_members') or not r.get('source_event_disposition')]
    counts=Counter(str(r.get('source_event_id') or '') for r in rows)
    duplicates=[event_id for event_id,count in counts.items() if count>1]
    legacy=[r.get('uid','') for r in rows if str(r.get('source_event_id') or '').startswith('legacy:')]
    if missing or duplicates or legacy:
        raise RuntimeError(
            '%s lineage invalid: missing=%s duplicate=%s legacy=%s'
            % (label, ', '.join(missing[:5]), ', '.join(duplicates[:5]), ', '.join(legacy[:5]))
        )

    groups=defaultdict(list)
    for row in rows:
        event_id=str(row['source_event_id'])
        members=str(row['source_event_members'])
        if event_id.startswith(('card-group:', 'card-group-blank-merchant:')):
            groups[event_id.rsplit(':',1)[0]].append(members)
        elif event_id.startswith('card:') and members != event_id[len('card:'):]:
            raise RuntimeError('%s card member mismatch: %s' % (label, event_id))
        elif event_id.startswith('manual:') and members != event_id:
            raise RuntimeError('%s manual member mismatch: %s' % (label, event_id))
        elif event_id.startswith('adjustment:') and (
            members != event_id
            or row.get('source_event_disposition') != 'projection_adjustment_pending_review'
        ):
            raise RuntimeError('%s adjustment disposition mismatch: %s' % (label, event_id))
        elif event_id.startswith('projection-alias:') and (
            members != event_id
            or row.get('source_event_disposition') != 'superseded_duplicate_projection'
            or not row.get('source_event_alias_of')
        ):
            raise RuntimeError('%s superseded duplicate alias mismatch: %s' % (label, event_id))
        elif event_id.startswith('manual-claimed-card-no-raw:') and (
            members != event_id
            or row.get('source_event_disposition') != 'manual_claimed_card_no_raw'
            or not str(row.get('source_event_alias_of') or '').startswith('manual:')
        ):
            raise RuntimeError('%s manual/no-raw alias mismatch: %s' % (label, event_id))
        elif event_id.startswith('rejected-legacy-projection:') and (
            members != event_id
            or row.get('source_event_disposition') != 'rejected_legacy_projection'
            or not row.get('source_event_alias_of')
        ):
            raise RuntimeError('%s rejected legacy projection mismatch: %s' % (label, event_id))
    for group_id, member_lists in groups.items():
        if len(set(member_lists)) != 1:
            raise RuntimeError('%s exact-group membership changed: %s' % (label, group_id))
        members=[member for member in member_lists[0].split('|') if member]
        if len(members) != len(member_lists) or len(set(members)) != len(members):
            raise RuntimeError('%s exact-group cardinality invalid: %s' % (label, group_id))
    return {str(r['source_event_id']): str(r['source_event_members']) for r in rows}

rows=list(csv.DictReader(INPUT_PATH.open(encoding='utf-8')))
v13_total=sum(i(r['krw']) for r in rows)
FN=list(rows[0].keys())
# A projection may reclassify an event, but it must never make an identified
# source event disappear.  In particular, TRIP-* is a generated display key
# and cannot be used as the coverage key.
if LOSSLESS_NO_DELETE:
    _input_source_events=validate_source_lineage(rows, 'v13 input')
    _input_source_dispositions={r['source_event_id']: r['source_event_disposition'] for r in rows}
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
    if dup and not LOSSLESS_NO_DELETE:
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
    res=re.sub(r'[\s_]','',d)                                      # 공백 제거→사람이름 핵심
    if res in ('항공', '숙박', '렌트', '렌터카', '식비', '교통', '교통비', '입장', '입장료', '기타', '유류비', '보험', '여행자보험'):
        return ''
    return res
def bookno_t(note):   # ★예약번호(다객실 동일가 유일 식별) — dedup 키에 포함해 다른 예약 오제거 방지
    m=re.search(r'예약\s*(\d{6,}|[A-Z0-9]{5,7})(?![0-9])', note or '')
    return m.group(1) if m else ''
seen_key=set(); kept2=[]; dd=0; ddtot=0
for t in sorted(kept, key=lambda z:z['uid']):
    # ★영수증/현금/이체(MAN, 비카드)는 수기장부가 마스터(2026-07-23 사용자 확정 "영수증은 수기가 마스터"):
    #   카드 원거래가 없어 건수로 중복판정 불가 → dedup 제외, 수기 기재 건수 그대로 인정.
    if t.get('src')=='MAN':
        kept2.append(t); continue
    core=desc_core(t['note']); a=abs(i(t['krw'])); cx=str(t.get('cancel')).lower() in ('true','1')
    bk=bookno_t(t['note'])
    key=(t['bucket'], a, cx, core, bk)   # ★예약번호 포함(규칙5·P10): 예약번호 다르면 별개 거래, 절대 병합/제거 금지
    if (not LOSSLESS_NO_DELETE) and (core or bk) and key in seen_key:
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
        if (not LOSSLESS_NO_DELETE) and cc>=1 and tripseen[k]>cc:
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
    # A date/approval enrichment is not allowed to choose the first raw row.
    # Ambiguous card facts stay unchanged for manual review.
    return hit[0] if len(hit)==1 else None

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
paired=[]; pn=0; drop_uids=set(); unresolved=[]; ambiguous=[]; partial=0
restoration_targets=[]
for r in kept:
    if str(r.get('cancel')).lower() in ('true','1') and pos_key.get((r['bucket'],abs(i(r['krw']))),0)==0:
        rc=desc_core(r['note'])
        if rc and any(r['bucket']==b and (rc in c or c in rc) for (b,c) in pos_desc.keys()):
            partial+=1; continue   # 부분환불: 원거래(다른 금액 또는 그룹명단)가 이미 존재 → 손대지 않고 차감 유지
        if r['uid'].startswith('TRIP-'):
            partial+=1; continue   # 수기장부 마이너스 기입건: 정당한 수기 환불/취소 내역이므로 차감 유지

        restoration_targets.append(r)

def _raw_original_candidates(r):
    a=abs(i(r['krw'])); co=CO.get(r['src'],''); rb=brand(r['merchant'])
    cand=[c for c in cards if not c['cancel'] and abs(c['krw'])==a and c['co']==co]
    cand=[c for c in cand if brand(c['mer'])==rb and c['appr'] not in base_appr_used]  # ★브랜드일치+base비도용
    return cand

_restored_selected,_restored_statuses=select_bidirectionally_unique_candidates(
    restoration_targets,
    _raw_original_candidates,
    candidate_key=lambda c: (c['src'],c['raw_record_id']),
)
for r in restoration_targets:
    best=_restored_selected.get(id(r))
    candidate_status=_restored_statuses[id(r)]
    if best is None:
        # The missing original is a review problem, not authority to
        # erase the cancellation source event.  Retain it in clearing so
        # a later raw-card link can resolve the relation without losing
        # the event or its amount.
        (ambiguous if candidate_status=='ambiguous' else unresolved).append(r)
        r['bucket']='취소환불'
        r['confidence']='하'
        r['note']=((r.get('note') or '').strip(' |')
                   + (
                       ' | 원거래 복수후보: 자동연결 금지·취소환불 검토대기'
                       if candidate_status=='ambiguous'
                       else ' | 원거래 미확인: 취소환불 검토대기(원천 이벤트 보존)'
                   ))
        continue
    pn+=1
    a=abs(i(r['krw']))
    orow={k:'' for k in FN}
    orow.update(uid='ORIG-%04d'%pn, source_event_id='card:%s:%s' % (best['src'], best['raw_record_id']), source_event_members='%s:%s' % (best['src'], best['raw_record_id']), source_event_disposition='raw_card_linked', src=r['src'], use_date=best['use'], card4=r['card4'],
        merchant=best['mer'], country=r['country'], currency=r['currency'], foreign='0', krw=str(a),
        status='정상', bucket=r['bucket'], account=r['account'], cancel='False', cost_type='여행원가',
        vat_tag=r['vat_tag'], confidence='상',
        note='원거래 복원(취소쌍 net0, 브랜드일치확인) | %s'%(r['note'].split('|')[-1].strip() if '|' in r['note'] else ''),
        tax_conf='상', appr=best['appr'], orig_appr='')
    r['orig_appr']=orow['appr']
    paired.append(orow)
kept=[r for r in kept if r['uid'] not in drop_uids]
allrows=[r for r in allrows if r['uid'] not in drop_uids]
print('⑥원거래 없는 취소', pn, '건 원거래 복원(브랜드일치) /', partial,'건 부분환불(원거래 다른금액 존재→차감유지)')
print('   브랜드검증 실패(원거래 불확실) →', len(unresolved),'건 취소환불 검토대기(원천 보존):', [(u['uid'],u['merchant'][:14],u['krw']) for u in unresolved])
print('   원거래 복수후보 →', len(ambiguous),'건 자동연결 금지:', [(u['uid'],u['merchant'][:14],u['krw']) for u in ambiguous])
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
    # ⑦e KBD-1084: 결제 상세 전표로 음식점 이용을 확인했고,
    # 사용자 확인으로 참석자는 운영이사 및 엘레나 대장(사내 인원)이다.
    # 외부인 접대가 아닌 내부 운영회의 식대로 분류한다.
    if r['uid']=='KBD-1084':
        r['bucket']='기타비용'
        r['account']='회의비'
        r['cost_type']='판관비'
        r['vat_tag']='공제후보'
        r['confidence']='상'
        r['tax_conf']='중'
        r['note']=(
            '카드매출전표 확인: 2026-06-18 강태현스시 매장 이용, 109,000원'
            ' | 참석자: 운영이사, 엘레나 대장(사내 인원)'
            ' | 내부 운영회의 식대: 회의비'
            ' | 부가세 공제후보(구체적 회의 목적·안건 증빙 보관 필요)'
        )
        acc7+=1; vat7+=1
    # ⑦f 사용자 단건 판정: 국내 식사 2건은 회의비,
    # 집사의하루는 반려동물 업종이 아니라 카페이며 운영이사의 업무공간 사용분이다.
    if r['uid'] in ('KBD-0401', 'KBD-0378'):
        r['bucket']='기타비용'
        r['account']='회의비'
        r['cost_type']='판관비'
        r['vat_tag']='공제후보'
        r['confidence']='상'
        r['tax_conf']='중'
        r['note']=(
            f'사용자 확정: {r["merchant"]} 회의비'
            ' | 국내 업무회의 식대'
            ' | 부가세 공제후보(참석자·회의 목적 증빙 보관 필요)'
        )
        acc7+=1; vat7+=1
    if r['uid'] in ('KBD-0954', 'KBD-0955'):
        r['bucket']='기타비용'
        r['account']='복리후생비'
        r['cost_type']='판관비'
        r['vat_tag']='공제후보'
        r['confidence']='상'
        r['tax_conf']='중'
        r['note']=(
            '사용자 확정: 집사의 하루는 카페'
            ' | 운영이사의 업무용 워크스페이스 사용'
            ' | 복리후생비·부가세 공제후보(업무일지 등 업무관련성 증빙 보관)'
        )
        acc7+=1; vat7+=1
print('⑦ 계정교정',acc7,'/ vat정규화',vat7,'/ 버킷·플래그',buk7)

# ⑦g base 취소행 승인번호 페어 보강: appr 비어있는 base 취소를 카드 취소전표(괄호 원승인)로 연결
base_cancellations=[
    r for r in allrows
    if not r['uid'].startswith(('TRIP-','ORIG-'))
    and i(r['krw'])<0
    and not (r.get('orig_appr') or '').strip()
    and CO.get(r['src'],'')=='국민'
    and r['src']=='KBD'
]
def _base_cancellation_candidates(r):
    prefix=re.sub(r'[^A-Z0-9가-힣]','',(r['merchant'] or '').upper())[:5]
    return [
        c for c in cards
        if c.get('src')=='KBD' and c.get('cancel') and c.get('orig')
        and abs(c['krw'])==abs(i(r['krw']))
        and prefix in re.sub(r'[^A-Z0-9가-힣]','',c['mer'].upper())
    ]
_base_selected,_base_statuses=select_bidirectionally_unique_candidates(
    base_cancellations,
    _base_cancellation_candidates,
    candidate_key=lambda c: (c['src'],c['raw_record_id']),
)
base_cx_fixed=0; base_cx_ambiguous=[]
for r in base_cancellations:
    c=_base_selected.get(id(r))
    candidate_status=_base_statuses[id(r)]
    if c is not None:
        r['orig_appr']=c['orig']; r['appr']=(r['appr'] or c['appr']); base_cx_fixed+=1
    elif candidate_status=='ambiguous':
        base_cx_ambiguous.append(r['uid'])
print('⑦g base 취소 승인번호 보강:', base_cx_fixed, '/ 복수후보 보류', len(base_cx_ambiguous))

# ⑦h 국민해외(KBO) 환불 페어링: 승인번호 없음 → 규칙 A2 '현지외화금액' 페어(사용자 방식 엔진화).
#    키=(카드4, 통화, |현지금액| 소수보존) 양수 원거래. 복수 후보면 버킷으로 좁히지 않고 보류한다.
#    합성 페어ID(KP####)를 원거래 appr(빈 경우)·취소 orig_appr에 부여 → 빌더가 원거래 바로 아래 배치.
def ff(x):
    try:
        v=round(float(str(x).replace(',','') or 0),2); return v
    except: return 0.0
kbo_pos=defaultdict(list)
for r in allrows:
    if r['src']=='KBO' and i(r['krw'])>0:
        kbo_pos[(r['card4'], r['currency'], abs(ff(r['foreign'])))].append(r)
kbo_refunds=[
    r for r in allrows
    if r['src']=='KBO' and i(r['krw'])<0
    and not (r.get('orig_appr') or '').strip()
]
_kbo_selected,_kbo_statuses=select_bidirectionally_unique_candidates(
    kbo_refunds,
    lambda r: kbo_pos.get(
        (r['card4'], r['currency'], abs(ff(r['foreign']))), []
    ),
)
kp=0; kbo_unpaired=[]; kbo_ambiguous=[]
for r in kbo_refunds:
    p=_kbo_selected.get(id(r))
    candidate_status=_kbo_statuses[id(r)]
    if p is not None:
        kp+=1
        pid=p['appr'].strip() if (p.get('appr') or '').strip() else 'KP%04d'%kp
        p['appr']=pid; r['orig_appr']=pid
    elif candidate_status=='ambiguous':
        kbo_ambiguous.append(r)
    else:
        kbo_unpaired.append(r)
print('⑦h KBO 현지외화 페어:', kp,'건 연결 / 복수후보',len(kbo_ambiguous),'건 / 원거래 기간밖(전기예약 등)', len(kbo_unpaired),'건')

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
man_refunds=[
    r for r in allrows
    if r['src']=='MAN' and i(r['krw'])<0
    and not (r.get('orig_appr') or '').strip()
]
def _manual_refund_candidates(r):
    c=desc_core(r['note'])
    cand=list(man_pos.get((r['bucket'],c),[])) if c else []
    if not cand:   # 폴백: 같은 버킷·같은 가맹·동액 양수(완전취소쌍)
        cand=list(man_amt.get(
            (r['bucket'], mk(r['merchant']), abs(i(r['krw']))), []
        ))
    return cand
_man_selected,_man_statuses=select_bidirectionally_unique_candidates(
    man_refunds,
    _manual_refund_candidates,
)
mp=0; man_ambiguous=[]
for r in man_refunds:
    p=_man_selected.get(id(r))
    candidate_status=_man_statuses[id(r)]
    if p is not None:
        mp+=1
        pid=(p.get('appr') or '').strip() or 'MP%04d'%mp
        p['appr']=pid; r['orig_appr']=pid
    elif candidate_status=='ambiguous':
        man_ambiguous.append(r)
print('⑦i 현금성 환불 페어(desc/동액):', mp,'건 연결 / 복수후보',len(man_ambiguous),'건 보류')

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

# ⑦e 카드이용대금 이체: 회사카드(국민/하나/기업) 정산분만 제외(실결제와 이중계상, 사용자 확정 "전자=제외").
#    ★외부인(가이드 등) 개인카드 정산은 우리 카드데이터에 원거래가 없어 이중계상이 아닌 실비용 — 유지
#    (2026-07-23 사용자 지적: 전용진 4,280,000은 우리 국민/하나/기업에 원거래 0건인 개인카드 정산인데 오제외됨).
def _is_company_cardpay(r):
    if '카드이용대금' not in (r.get('note') or ''): return False
    blob=(r.get('merchant') or '')+' '+(r.get('note') or '')
    return bool(re.search(r'국민|하나|기업|신한|삼성|비씨|\d{4}', r.get('merchant') or ''))
before=len(allrows)
allrows=[r for r in allrows if not _is_company_cardpay(r)]
print('⑦e 회사카드 카드이용대금 정산성 이체 제외:', before-len(allrows),'건 (외부 개인카드 정산은 유지)')

# ⑦k 기업 취소 이벤트 부호 교정: A파일 '취소또는할인'이 양수로 잘못 반영된 행
corp_cx_appr={c['appr'].lstrip('0') for c in cards if c.get('src')=='CORP' and c.get('cancel')}
ck=0
for r in allrows:
    if r['src']=='CORP' and i(r['krw'])>0:
        ap=(r['appr'] or '').strip().lstrip('0')
        if ap and ap in corp_cx_appr:
            n_clean = re.sub(r'KRW결제 아고다[^|]*', '', r['note'] or '').strip(' |')
            r['note'] = (n_clean if n_clean else '실카드 취소 전표') + ' | 카드원천 취소또는할인 부호 교정'
            # This source row is a cancellation event, not a zero-value
            # placeholder. Preserve its amount with the correct sign.
            r['krw'] = str(-abs(i(r['krw'])))
            r['cancel'] = 'True'
            r['status'] = '\uCDE8\uC18C'
            r['bucket'] = '\uCDE8\uC18C\uD658\uBD88'
            r['confidence'] = '상'
            r['tax_conf'] = '상'
            ck += 1
print('⑦k 기업 취소 이벤트 부호 교정:', ck,'건')

# ⑦m 상충 태그 소거: note에 "미청구_예약확정" 또는 "수기미입력" 표기인데 bucket이 탭으로 정정된 행 →상충 태그 소거
clr=0
for r in allrows:
    if r['bucket'] not in ('여행_미배정','미청구_예약확정','취소환불') and r['bucket']:
        n=r['note'] or ''
        if '미입력추정(수기장부 없음)' in n:
            n=n.replace('미입력추정(수기장부 없음)','수기 반영완료')
            r['note']=n; clr+=1
print('⑦m 상충 태그 소거:', clr, '건')

# ⑦p OTA 메일 전수 교차 대사 귀속 (Full OTA Mail Cross-Matching)
ota_matched_cnt = 0
if os.path.exists('data/ota_mail_index.json'):
    records = json.load(open('data/ota_mail_index.json', encoding='utf-8')).get('records', [])
    TAB_PATTERNS = [
        (r'아오모리|AOMORI', '0417_아오모리'),
        (r'교토|KYOTO', '0408_교토'),
        (r'알펜루트|고마츠|하네다', '0424_알펜루트'),
        (r'에히메|마츠야마', '0404_에히메'),
        (r'오사카|OSAKA|난바', '0420_오사카'),
        (r'나가센도|나고야', '0413_나가센도'),
        (r'부산', '0501_부산'),
        (r'북해도|삿포로|토마무|스스키노', '0613_북해도'),
        (r'레분|리시리|왓카나이', '0616_레분토&리시리'),
        (r'묘코|아라이|니가타|다자와코|요코테', '0620_묘코'),
        (r'아키타|쇼나이', '0625_아키타'),
        (r'오제|군마|미나카미', '0630_오제'),
        (r'유럽|스위스|프랑스|이탈리아', '5월_유럽'),
    ]
    for r in allrows:
        if r['bucket'] == '여행_미배정' or r['confidence'] in ('하', '중,하'):
            mer = (r['merchant'] or '').upper()
            dt_str = r['use_date']
            if not dt_str or dt_str == 'None': continue
            try: c_dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d')
            except: continue
            prov = (
                'agoda' if 'AGODA' in mer else
                'mytrip' if any(x in mer for x in ('MYTRIP', 'GOTOGATE', '마이트립', '고투게이트')) else
                'trip' if 'TRIP' in mer else
                'booking' if 'BOOKING' in mer else ''
            )
            if not prov: continue

            # 날짜·제목·가맹점 키워드만으로 자동확정하지 않는다. OTA 표시금액이
            # 카드 원화금액과 정확히 같고, 기존 예약번호가 있으면 그것도 일치해야 한다.
            row_refs = set(re.findall(r'(?:\d{4}-\d{3}-\d{3}|\d{6,19})', r.get('note') or ''))
            candidates = []
            for rec in records:
                if rec.get('provider') == prov:
                    amounts = {
                        int(round(float(str(value).replace(',', ''))))
                        for value in (rec.get('amounts') or [])
                        if str(value).replace(',', '').replace('.', '', 1).isdigit()
                    }
                    if abs(i(r['krw'])) not in {abs(value) for value in amounts}:
                        continue
                    rec_refs = {str(value) for value in (rec.get('bookingRefs') or [])}
                    if row_refs and rec_refs and not row_refs.intersection(rec_refs):
                        continue
                    sent_at = rec.get('sentAt', '')
                    m_dt = None
                    if sent_at:
                        try:
                            parts = sent_at.split()
                            if len(parts) >= 4:
                                m_dt = datetime.datetime.strptime(f'{parts[3]}-{parts[2]}-{parts[1]}', '%Y-%b-%d')
                        except: pass
                    if m_dt:
                        diff = abs((c_dt - m_dt).days)
                        if diff <= 10:
                            subj = rec.get('subject', '')
                            for pat, tab in TAB_PATTERNS:
                                if re.search(pat, subj, re.IGNORECASE):
                                    candidates.append((rec, tab, subj, diff))
                                    break
            # 같은 금액 후보가 둘 이상이면 N:M 그룹 검토 대상으로 남긴다.
            if len(candidates) == 1:
                rec, tab, subj, _ = candidates[0]
                r['bucket'] = tab
                r['confidence'] = '상'
                r['note'] = (r['note'] or '') + f" | ⚡OTA메일 금액·공급자 교차확정({tab}): {subj[:35]}"
                ota_matched_cnt += 1
print('⑦p OTA 메일 전수 교차 대사 귀속:', ota_matched_cnt, '건 완료')

# ⑦l 전수감사 발견 교정: ①아오모리 트립닷컴_그랜드 net0 취소쌍(수기122↙123행, 카드 30057825↔40901179) 복원—P6 취소환불
_has_grand=any('1400825417884289' in (r['note'] or '') for r in allrows)
if not _has_grand:
    def _grand_raw_source(is_refund):
        candidates=[
            card for card in cards
            if card.get('src')=='KBD'
            and abs(i(card.get('krw'))) == 213274
            and bool(card.get('cancel')) == is_refund
            and (
                (not is_refund and str(card.get('appr') or '')=='30057825')
                or (is_refund and str(card.get('orig') or '')=='30057825')
            )
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                'cannot reconstruct Grand cancellation pair without one exact raw card event '
                '(refund=%s, candidates=%d)' % (is_refund, len(candidates))
            )
        card=candidates[0]
        return '%s:%s' % (card['src'], card['raw_record_id'])

    for sgn,ap,og,st in [(1,'30057825','', '정상'),(-1,'','30057825','취소')]:
        raw_source=_grand_raw_source(sgn < 0)
        nr={k:'' for k in FN}
        nr.update(uid='ORIG-0417G%s'%('P' if sgn>0 else 'N'), source_event_id='card:%s' % raw_source, source_event_members=raw_source, source_event_disposition='raw_card_linked', src='KBD', use_date='2026-04-20',
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

# ⑦n 3820 기명카드 규칙: 3820 기명법인카드는 기타비용, 일반 공용카드는 날짜에 맞는 여행탭 귀속
TRIP_PURPOSE={'항공료','여행자보험','숙박비'}
def is_triptab(b): return bool(re.match(r'\d{4}_|\d{1,2}월_', b or ''))
n7=0
for r in allrows:
    if r['uid'] in ('KBD-0855', 'KBD-0872', 'KBD-0881'):
        c4 = r.get('card4', '').strip()
        if c4 == '3820':
            r['bucket'] = '기타비용'
            r['cost_type'] = '판관비'
            r['confidence'] = '상'
        else:
            r['bucket'] = '0501_부산'
            r['confidence'] = '상'
            r['note'] = (r['note'] or '') + ' | 공용카드(0501_부산 일자귀속 확정)'
            n7 += 1
    elif r.get('card4') == '3820' and r['src'] == 'KBD' and is_triptab(r['bucket']):
        if r['account'] not in TRIP_PURPOSE and '여행상품' not in (r['note'] or ''):
            old = r['bucket']; r['bucket'] = '기타비용'; r['cost_type'] = '판관비'
            if r['account'] in ('기타비용', '식비'): r['account'] = '복리후생비'
            r['note'] = (r['note'] or '') + ' | 3820 기명카드 국내결제→기타비용'
            n7 += 1
print('⑦n 3820 기명카드 규칙 및 공용카드 여행탭 귀속 교정:', n7, '건')

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

if LOSSLESS_NO_DELETE:
    _output_source_events=validate_source_lineage(allrows, 'v14 output')
    _output_source_dispositions={r['source_event_id']: r['source_event_disposition'] for r in allrows}
    _lost_source_events=sorted(set(_input_source_events)-set(_output_source_events))
    _mutated_source_members=sorted(
        event_id for event_id,members in _input_source_events.items()
        if _output_source_events.get(event_id) != members
    )
    _mutated_source_dispositions=sorted(
        event_id for event_id,disposition in _input_source_dispositions.items()
        if _output_source_dispositions.get(event_id) != disposition
    )
    if _lost_source_events or _mutated_source_members or _mutated_source_dispositions:
        raise RuntimeError(
            'lossless projection blocked: source event deleted, raw membership changed, or disposition changed; '
            'deleted=%s members=%s dispositions=%s'
            % (
                ', '.join(_lost_source_events[:10]),
                ', '.join(_mutated_source_members[:10]),
                ', '.join(_mutated_source_dispositions[:10]),
            )
        )

require_protected_uids_preserved(rows, allrows, {'KBO-9002'})
require_valid_nonposting_aliases(allrows)
require_raw_cancellation_signs(allrows)
if DRY_RUN:
    print(
        'LINEAGE SEMANTIC COUNTS:',
        json.dumps(lineage_semantic_counts(allrows), ensure_ascii=False, sort_keys=True),
    )

if not DRY_RUN:
    if OUTPUT_PATH.exists():
        raise FileExistsError('기존 후보를 덮어쓰지 않습니다: %s'%OUTPUT_PATH)
    OUTPUT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with OUTPUT_PATH.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(allrows)
tot=sum(i(r['krw']) for r in allrows)
print('classified_v14 후보:',OUTPUT_PATH,'입력SHA',_input_sha,'/',len(allrows),'행 krw합',format(tot,','),'(실제 v13 대비',format(tot-v13_total,'+,'),')')
