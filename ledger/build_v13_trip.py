# -*- coding: utf-8 -*-
"""여행(실체) 기준 재구성: 기존 워크북(classified_v12, 카드검증 완료) +
수기장부(여행 마스터) 미포함건을 카드매칭으로 추가 → classified_v13.
금액은 카드 우선(rule A1), 탭·성격은 수기. 비카드는 증빙유형 표기."""
import openpyxl, csv, re, sys, json, hashlib
from collections import Counter, defaultdict
from pathlib import Path
from domain.card_group_matching import (
    balanced_blank_merchant_card_groups,
    balanced_exact_card_groups,
    classify_unresolved_card_lineage,
    enrich_unique_card_identifiers,
    unique_exact_structural_card_links,
    unique_approval_card_links,
)
from domain.hana_events import expand_hana_row, reconcile_hana_billing_projection
from domain.cancellation_lifecycle import zero_net_cancellation_approvals
from domain.master_enrichment import enrich_from_master
from domain.lineage_gates import (
    lineage_semantic_counts,
    require_protected_uids_preserved,
    require_raw_cancellation_signs,
    require_valid_nonposting_aliases,
    require_zero_non_agoda_unresolved,
)
from domain.refund_projection import (
    exact_full_refund_pairs,
    repair_standalone_cancellation_signs,
)
from domain.p0_release_guard import validate_frozen_stage

DRY_RUN = '--dry-run' in sys.argv
def _option_path(flag, default):
    try:
        return Path(sys.argv[sys.argv.index(flag)+1])
    except (ValueError, IndexError):
        return Path(default)

INPUT_PATH=_option_path('--input','data/classified_v12.csv')
_input_sha=hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest()
OUTPUT_PATH=_option_path(
    '--output',
    '../outputs/20260728_pipeline_recovery/classified_v13_candidate_%s.csv'
    % _input_sha[:8],
)
if OUTPUT_PATH.resolve()==INPUT_PATH.resolve():
    raise RuntimeError('입력 projection 인플레이스 덮어쓰기는 금지됩니다.')
_input_gate=validate_frozen_stage(Path(__file__).resolve().parents[1],'canonical_rebuild')

def i(x):
    try: return int(round(float(str(x).replace(',','').replace('원','').strip())))
    except: return 0
def load(f):
    wb=openpyxl.load_workbook('newcard/conv/%s.xlsx'%f,read_only=True); ws=wb[wb.sheetnames[0]]
    return [[('' if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]

def d10(s):
    s=str(s).replace('.','-')
    m=re.search(r'(\d{2,4})-(\d{2})-(\d{2})',s)
    if not m: return ''
    y=m.group(1);  y='20'+y if len(y)==2 else y
    return '%s-%s-%s'%(y,m.group(2),m.group(3))

def _norm_merchant(value):
    return re.sub(r'[^0-9A-Z가-힣]', '', str(value or '').upper())

def _merchant_compatible(left, right):
    a,b=_norm_merchant(left),_norm_merchant(right)
    return bool(a and b and (a in b or b in a or (len(a)>=8 and len(b)>=8 and a[:8]==b[:8])))

def is_cancel_status(value):
    text=str(value or '').replace(' ', '')
    return '취소' in text or '리버설' in text or 'REVERSAL' in text.upper()

# ---- 통합 카드 인덱스 (정상+취소, 금액→상세) ----
cards=[]
for _rn,r in enumerate(load('E')[1:],start=2):
    if len(r)>16 and i(r[16]):
        cards.append(dict(raw_record_id='E:%d'%_rn,co='국민',use=d10(r[1]) or d10(r[0]),bill=d10(r[0]),c4=r[4][-4:],amt=i(r[16]),mer=r[7],fx=r[11],cur=r[10],sub='해외',src='KBO',cx=is_cancel_status(r[6]),appr=''))
for _rn,r in enumerate(load('F')[1:],start=2):
    if len(r)>15 and i(r[11]):
        _m=re.match(r'^\s*(\d+)\((\d+)\)\s*$', str(r[15]).strip())
        _ap,_og=(_m.group(1),_m.group(2)) if _m else (re.sub(r'\D','',r[15]),'')
        cards.append(dict(raw_record_id='F:%d'%_rn,co='국민',use=d10(r[1]),c4=r[5][-4:],amt=abs(i(r[11])),mer=r[7],fx='',cur='',sub='국내',src='KBD',cx=(i(r[11])<0),appr=_ap,orig=_og))
for f in ('G','H'):
    for _rn,r in enumerate(load(f)[6:],start=7):
        if len(r)>14 and r[0] and r[0]!='NO' and i(r[5]):
            cards.extend(expand_hana_row('%s:%d'%(f,_rn), r, d10))
for _rn,r in enumerate(load('A_20260720'),start=1):
    if len(r)>13 and i(r[6]):
        gu='해외' if r[1].startswith('해외') else '국내'
        cards.append(dict(raw_record_id='A_20260720:%d'%_rn,co='기업',use=str(r[2])[:10],c4=r[3][-4:],amt=i(r[6]),mer=r[5],fx=(r[7] or '').split()[0] if r[7] else '',cur='JPY' if 'JPY' in (r[7] or '') else '',sub=gu,src='CORP',cx=(r[0]=='취소또는할인'),appr=re.sub(r'\D','',r[13])))
byamt=defaultdict(list)
for c in cards: byamt[(c['amt'],c['cx'])].append(c)
amts=sorted(set(a for a,_ in byamt))
_used_card=set()   # 안정 원천행 ID 소비형: 한 카드 레코드는 한 수기행에만 배정
def card_key(c): return '%s:%s'%(c['src'],c['raw_record_id'])
def card_match(a, co, want_cx=False, use_date='', merchant=''):
    # ★부호(취소여부) 일치 + 카드사 일치 필수(타사 폴백 금지) + 소비형(1카드=1행).
    cand=byamt.get((a,want_cx),[])
    # Nearby amounts are candidates, not proof.  The old +/-2% fallback could
    # consume a different transaction, so this projection requires exact KRW.
    pool=[c for c in cand if c['co']==co and card_key(c) not in _used_card]
    if use_date: pool=[c for c in pool if c.get('use')==use_date]
    if merchant: pool=[c for c in pool if _merchant_compatible(c.get('mer'),merchant)]
    if len(pool)!=1: return None
    best=pool[0]
    _used_card.add(card_key(best))
    return best

# ---- 기존 워크북 (classified_v12) ----
FN=['uid','source_event_id','source_event_members','source_event_disposition','source_event_alias_of','src','use_date','post_date','card4','user','merchant','biz','country','currency','foreign','krw','vat','tax_type','status','biz_no','extra','bucket','account','cancel','cost_type','vat_tag','confidence','note','tax_conf','appr','orig_appr']
cls=list(csv.DictReader(INPUT_PATH.open(encoding='utf-8')))
_input_legacy_uids={str(row.get('uid') or '') for row in cls}
_SUPERSEDED_DUPLICATE_PROJECTIONS={
    # Confirmed duplicate legacy projections: keep the audit row, but never
    # recognize it as another cost or as another raw card event.
    'KBO-2771': 'KBO-2769',
    'KBO-2863': 'KBO-2853',
    'KBO-0351': 'cardinality-group:KBO-0349+KBO-0350',
    'KBO-0352': 'cardinality-group:KBO-0349+KBO-0350',
    'KBO-0355': 'KBO-2954',
}
_MANUAL_CLAIMED_CARD_WITHOUT_RAW={
    # A 20,000 KRW manual parking receipt was previously amount-linked to an
    # unrelated SkyPass annual-fee projection.  It is not raw-card evidence.
    'HAN-0495': 'manual:0408_교토:136',
}
_REJECTED_LEGACY_PROJECTIONS={
    # H:116 is a negative cancellation.  These positive legacy rows have no
    # supporting purchase event and must not own or consume that raw refund.
    'HAN-3460': 'card:HAN:H:116:refund',
    'HAN-0511': 'card:HAN:H:116:refund',
}
_NONPOSTING_PROJECTION_UIDS=(
    set(_SUPERSEDED_DUPLICATE_PROJECTIONS)
    | set(_MANUAL_CLAIMED_CARD_WITHOUT_RAW)
    | set(_REJECTED_LEGACY_PROJECTIONS)
)
# ``TRIP-0001`` is a presentation sequence, not a payment identity.  Keep an
# explicit lineage field from this point onward so a regenerated sequence
# cannot silently replace a different payment during DB import.
for _row in cls:
    _uid=_row.get('uid') or ''
    if _uid in _SUPERSEDED_DUPLICATE_PROJECTIONS:
        _alias_id='projection-alias:%s' % _uid
        _row.setdefault('source_event_id', _alias_id)
        _row.setdefault('source_event_members', _alias_id)
        _row.setdefault('source_event_disposition', 'superseded_duplicate_projection')
        _row.setdefault('source_event_alias_of', _SUPERSEDED_DUPLICATE_PROJECTIONS[_uid])
    elif _uid in _MANUAL_CLAIMED_CARD_WITHOUT_RAW:
        _claim_id='manual-claimed-card-no-raw:%s' % _uid
        _row.setdefault('source_event_id', _claim_id)
        _row.setdefault('source_event_members', _claim_id)
        _row.setdefault('source_event_disposition', 'manual_claimed_card_no_raw')
        _row.setdefault('source_event_alias_of', _MANUAL_CLAIMED_CARD_WITHOUT_RAW[_uid])
    elif _uid in _REJECTED_LEGACY_PROJECTIONS:
        _rejected_id='rejected-legacy-projection:%s' % _uid
        _row.setdefault('source_event_id', _rejected_id)
        _row.setdefault('source_event_members', _rejected_id)
        _row.setdefault('source_event_disposition', 'rejected_legacy_projection')
        _row.setdefault('source_event_alias_of', _REJECTED_LEGACY_PROJECTIONS[_uid])
    elif i(_row.get('krw')) == 0:
        # A zero legacy row does not identify one card event.  Preserve it as
        # a non-postable adjustment disposition; P5 already audits these as
        # cancelled authorization or split-cancellation representations.
        _adjustment_id='adjustment:%s' % (_row.get('uid') or '')
        _row.setdefault('source_event_id', _adjustment_id)
        _row.setdefault('source_event_members', _adjustment_id)
        _row.setdefault('source_event_disposition', 'projection_adjustment_pending_review')
        _row.setdefault('source_event_alias_of', '')
    else:
        _row.setdefault('source_event_id', 'legacy:%s' % (_row.get('uid') or ''))
        _row.setdefault('source_event_members', '')
        _row.setdefault('source_event_disposition', 'raw_card_pending')
        _row.setdefault('source_event_alias_of', '')
try:
    _master_rows=list(csv.DictReader(open('master_ledger.csv',encoding='utf-8-sig')))
except FileNotFoundError:
    _master_rows=[]
_master_enrichment=enrich_from_master(cls, _master_rows)
print(
    'card master enrichment: %d updated, %d conflicts, %d unresolved'
    % (
        len(_master_enrichment['updated']),
        len(_master_enrichment['conflicts']),
        len(_master_enrichment['unresolved']),
    )
)
_hana_reconciliation=reconcile_hana_billing_projection(cls, cards)
print(
    'Hana billing reconciliation: %d updated, %d conflicts'
    % (
        len(_hana_reconciliation['updated']),
        len(_hana_reconciliation['conflicts']),
    )
)
_standalone_cancellation_repairs=repair_standalone_cancellation_signs(cls, cards)
print(
    'standalone cancellation sign repairs: %d'
    % len(_standalone_cancellation_repairs)
)
_identifier_enrichment=enrich_unique_card_identifiers(cls, cards)
print('card identifier enrichment: %d'%len(_identifier_enrichment))
_used_card.update(_hana_reconciliation['consumed_card_keys'])
# KBO-9002 remains an immutable card event.  A later allocation may link it
# to a manual trip row, but projection code must never delete the source row.
# ★base 선소비: base가 이미 대응하는 카드 레코드를 _used_card에 등록(승인번호 우선, 없으면 카드사+금액+부호 첫 건).
#   부산 하나건처럼 base가 이미 ⇄수기 매칭한 거래를 TRIP이 또 추가(appr 도용·이중계상)하는 것 방지.
_co_of={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
_classified_by_uid = {str(row.get("uid") or ""): row for row in cls}
# Explicit approval identity always precedes structural N:N coverage.  Otherwise
# repeated same-amount refunds can be consumed as a set before their distinct
# cancellation approvals are allowed to identify each event.
_direct_links = unique_approval_card_links(
    [row for row in cls if (row.get('uid') or '') not in _NONPOSTING_PROJECTION_UIDS],
    cards,
    _co_of,
    _used_card,
)
_direct_linked_uids = {link["uid"] for link in _direct_links}
for _link in _direct_links:
    _used_card.add(_link["raw_id"])
    _row = _classified_by_uid.get(_link["uid"])
    if _row is not None:
        _row['source_event_id'] = 'card:%s' % _link['raw_id']
        _row['source_event_members'] = _link['raw_id']
        _row['source_event_disposition'] = 'raw_card_linked'
        _row["note"] = (
            (_row.get("note") or "")
            + " | source_identity=direct;"
            + f"raw_record_id={_link['raw_id']}"
        ).strip(" |")
# Repeated identical charges are separate events, not duplicates.  Consume an
# exact N:N structural group only when both sides have the same cardinality.
_balanced_groups = balanced_exact_card_groups(
    [
        row
        for row in cls
        if str(row.get("uid") or "") not in (_direct_linked_uids | _NONPOSTING_PROJECTION_UIDS)
    ],
    [card for card in cards if card_key(card) not in _used_card],
    _co_of,
)
_balanced_group_members={
    str(group['group_id']): '|'.join(sorted(str(raw_id) for raw_id in group['raw_ids']))
    for group in _balanced_groups
}
_normal_grouped_uids=set()
for _group in _balanced_groups:
    if _group["match_scope"] == "multiset_exact":
        _used_card.update(_group['raw_ids'])
        for _uid in _group["base_ids"]:
            _row = _classified_by_uid.get(_uid)
            if _row is not None:
                # Exact repeated approval-less events prove coverage only as a
                # group.  Keep the group identity rather than inventing a 1:1 raw
                # row assignment.
                _row['source_event_id'] = '%s:%s' % (_group['group_id'], _uid)
                _row['source_event_members'] = _balanced_group_members[str(_group['group_id'])]
                _row['source_event_disposition'] = 'raw_card_group_coverage'
                _row["note"] = (
                    (_row.get("note") or "")
                    + " | source_identity=group_only;"
                    + f"match_group={_group['group_id']}"
                ).strip(" |")
                _normal_grouped_uids.add(_uid)
    elif len(_group['base_ids']) == len(_group['raw_ids']) == 1:
        # An exact 1:1 structural group has an individual raw identity even
        # when the source does not expose a usable approval number.
        _uid=_group['base_ids'][0]
        _raw_id=_group['raw_ids'][0]
        _row=_classified_by_uid.get(_uid)
        if _row is not None:
            _used_card.add(_raw_id)
            _row['source_event_id']='card:%s' % _raw_id
            _row['source_event_members']=_raw_id
            _row['source_event_disposition']='raw_card_linked'
            _row['note']=((_row.get('note') or '') + ' | source_identity=unique_exact;'
                          + f"raw_record_id={_raw_id}").strip(' |')
            _normal_grouped_uids.add(_uid)

# When issuer/card/date/signed amount are exact but card-origin merchant text
# is blank, preserve only an explicit N:M coverage group.  Never assign its
# raw rows to individual classified merchants.
_blank_merchant_groups=balanced_blank_merchant_card_groups(
    [row for row in cls if str(row.get('uid') or '') not in (_direct_linked_uids | _normal_grouped_uids | _NONPOSTING_PROJECTION_UIDS)],
    [card for card in cards if card_key(card) not in _used_card],
    _co_of,
)
_used_card.update(raw_id for group in _blank_merchant_groups for raw_id in group['raw_ids'])
_blank_grouped_uids={uid for group in _blank_merchant_groups for uid in group['base_ids']}
_grouped_uids=_normal_grouped_uids | _blank_grouped_uids
_blank_group_members={
    str(group['group_id']): '|'.join(sorted(str(raw_id) for raw_id in group['raw_ids']))
    for group in _blank_merchant_groups
}
for _group in _blank_merchant_groups:
    _members='|'.join(sorted(str(raw_id) for raw_id in _group['raw_ids']))
    for _uid in _group['base_ids']:
        _row=_classified_by_uid.get(_uid)
        if _row is not None:
            _row['source_event_id']='%s:%s' % (_group['group_id'], _uid)
            _row['source_event_members']=_members
            _row['source_event_disposition']='raw_card_group_coverage'
            _row['note']=((_row.get('note') or '') + ' | source_identity=blank_merchant_group;'
                          + f"match_group={_group['group_id']}").strip(' |')

# One remaining event can be linked only by its complete structural facts;
# approval is deliberately not an input to this pass.
_safe_structural_links=unique_exact_structural_card_links(
    [
        row for row in cls
        if str(row.get('uid') or '') not in (_direct_linked_uids | _grouped_uids | _NONPOSTING_PROJECTION_UIDS)
    ],
    [card for card in cards if card_key(card) not in _used_card],
    _co_of,
    _used_card,
)
_safe_structural_uids={link['uid'] for link in _safe_structural_links}
_card_by_key={card_key(card): card for card in cards}
for _link in _safe_structural_links:
    _used_card.add(_link['raw_id'])
    _row=_classified_by_uid.get(_link['uid'])
    if _row is not None:
        _row['source_event_id']='card:%s' % _link['raw_id']
        _row['source_event_members']=_link['raw_id']
        _row['source_event_disposition']='raw_card_linked'
        if _link.get('source_identity') == 'structural_exact_post_date_repair':
            _raw_card=_card_by_key[_link['raw_id']]
            _row['use_date']=str(_raw_card.get('use') or '')[:10]
        _row['note']=((_row.get('note') or '') + ' | source_identity=%s;'
                      % _link.get('source_identity', 'structural_exact')
                      + f"raw_record_id={_link['raw_id']}").strip(' |')
_unresolved_base_lineage=[
    row.get('uid','') for row in cls
    if str(row.get('source_event_id') or '').startswith('legacy:')
]
if _unresolved_base_lineage:
    for _row in cls:
        if _row.get('uid','') in _unresolved_base_lineage:
            _row['source_event_disposition']='raw_card_unresolved'
    _unresolved_reasons=classify_unresolved_card_lineage(
        [row for row in cls if row.get('uid','') in _unresolved_base_lineage],
        cards,
        _co_of,
        _used_card,
    )
    _unresolved_message=(
        'base card source lineage is unresolved; do not project positional IDs: '
        'count=%d reasons=%s examples=%s'
        % (len(_unresolved_base_lineage), _unresolved_reasons, ', '.join(_unresolved_base_lineage[:10]))
    )
    # Agoda may remain in the explicit OTA-review queue, but every other
    # issuer must be resolved or have a deliberate non-posting disposition.
    require_zero_non_agoda_unresolved(cls)
    if DRY_RUN:
        print('LINEAGE REVIEW:', _unresolved_message)
    else:
        raise RuntimeError(_unresolved_message)

# base에 이미 담긴 예약참조(숫자+알파PNR) — dedup 안전장치
book_in=set()
for r in cls:
    blob=(r['note'] or '')+' '+(r['appr'] or '')
    for m in re.findall(r'\d{8,}', blob): book_in.add(m)
    for m in re.findall(r'\b[A-Z0-9]{5,7}\b', blob):
        if re.search(r'[A-Z]',m) and re.search(r'[0-9]',m): book_in.add(m)

# ---- 수기장부 ----
man=list(csv.DictReader(open('data/manual_v3.csv',encoding='utf-8')))
# 수기장부 실제 행번호 인덱스(manual_v4.csv=재파싱, row열 보유). 탭명 변형 정규화 후 tab+date+item+금액으로 매칭.
TABMAP={'0630_오제_A':'0630_오제','0704_야마가타':'0704_아키타'}
def normtab(t): return TABMAP.get(t, t)
rowidx={}; bookidx={}; manual_v4_rows=[]
try:
    for r4 in csv.DictReader(open('data/manual_v4.csv',encoding='utf-8')):
        try: a4=round(float(r4['amount']))
        except: continue
        manual_v4_rows.append(r4)
        rowidx.setdefault((normtab(r4['tab']), r4['date'], r4['item'], a4), []).append(r4['row'])
        b4=(r4.get('book') or '').strip()
        if b4: bookidx.setdefault((normtab(r4['tab']), b4), []).append(r4['row'])
except FileNotFoundError:
    pass

def _booking_refs(value):
    return set(re.findall(r'(?:\d{4}-\d{3}-\d{3}|\d{6,19})', str(value or '')))

# 카드 소비와 수기 증거 소비를 분리한다. base가 이미 RAW 카드를 소비했더라도
# exact 수기행은 기존 결제에 연결해야 하며, 새 결제를 만들지 않는다는 이유로
# "수기장부 없음" 결론을 유지해서는 안 된다.
_issuer_for_src={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
_used_manual_v4=set()
for base in cls:
    issuer=_issuer_for_src.get(base.get('src',''),'')
    if not issuer: continue
    amount=abs(i(base.get('krw')))
    usedate=d10(base.get('use_date'))
    refs=_booking_refs(base.get('note'))
    candidates=[]
    for m4 in manual_v4_rows:
        key=(normtab(m4.get('tab','')), str(m4.get('row','')))
        if key in _used_manual_v4: continue
        if normtab(m4.get('tab','')) != normtab(base.get('bucket','')): continue
        if abs(i(m4.get('amount'))) != amount: continue
        if d10(m4.get('date')) != usedate: continue
        if m4.get('card','') != issuer: continue
        manual_ref=(m4.get('book') or '').strip()
        if refs and manual_ref and manual_ref not in refs: continue
        if not (refs and manual_ref) and not _merchant_compatible(base.get('merchant'),m4.get('item')): continue
        candidates.append(m4)
    if len(candidates) != 1: continue
    matched=candidates[0]
    _used_manual_v4.add((normtab(matched['tab']), str(matched['row'])))
    note=re.sub(
        r'(?:미입력(?:추정)?\s*\(\s*수기\s*장부\s*없음\s*\)|수기\s*(?:미기재|장부\s*없음))',
        '',
        base.get('note') or '',
    ).strip(' |')
    proof='수기%s행 | ⇄수기:%s'%(matched['row'],matched['item'])
    base['note']=proof + ((' | '+note) if note else '')

def manrow(r):
    # ★예약번호 우선(다객실 동일가에서 유일 식별) + 소비형(같은 키 재사용 금지 — 태그 오배정 방지)
    b=(r.get('book') or '').strip()
    if b:
        hit=bookidx.get((normtab(r['tab']), b))
        if hit: return hit.pop(0)
    try: a=round(float(r['amount']))
    except: return ''
    hit=rowidx.get((normtab(r['tab']), r['date'], r['item'], a))
    return hit.pop(0) if hit else ''
def is_q2(tab):
    m=re.match(r'(\d{2})(\d{2})',tab or ''); mm=re.match(r'(\d+)월',tab or '')
    if m: return 4<=int(m.group(1))<=6
    if mm: return 4<=int(mm.group(1))<=6
    return False

def account_of(item,desc):
    s=(desc or '')+' '+(item or '')
    if '항공' in s or '航空' in s: return '항공료'
    if '숙박' in s or '료칸' in s or 'ryokan' in s.lower(): return '숙박비'
    if '렌터카' in s or 'RENT' in s.upper(): return '렌터카'
    if '통행' in s: return '통행료'
    if '교통' in s or 'TRAIN' in s.upper() or 'BUS' in s.upper(): return '교통비'
    if '식' in s or 'FAMILYMART' in s.upper(): return '식비'
    if '입장' in s: return '입장료'
    if '보험' in s or '트래블로버' in s or '트래블로버' in item: return '여행자보험'
    # 브랜드 기반
    if any(k in item for k in ['AGODA','Agoda','아고다','Booking','BOOKING','트립닷컴','Trip.com','Mercure','Hotel','HOTEL','호텔']): return '숙박비'
    if any(k in item for k in ['마이트립','고투게이트','제주항공','대한항공','아시아나','ANA','진에어','스카이티켓','에어']): return '항공료'
    return '숙박비'
def src_of(card,item,acct):
    if card=='하나' or re.match(r'4595|5483|3923|4140|4336',card or ''): return 'HAN','하나'
    if card=='기업' or re.match(r'4971|4985|8972',card or ''): return 'CORP','기업'
    if card=='국민' or re.match(r'8835|3804|3820|4886|8895|0906',card or ''):
        # 국내 PG(원화결제) vs 해외
        if any(k in item for k in ['NICE','마이트립','이니시스','고투게이트','_NICE','제주항공','대한항공','진에어','아시아나','(주)']): return 'KBD','국민'
        return 'KBO','국민'
    return 'MAN', (card or '기타')  # 현금/이체/영수증

CARDSET={'국민','하나','기업'}
def is_card(cd): return cd in CARDSET or bool(re.match(r'\d{4}',cd or ''))

new=[]; n=0; addtot=0; cashtot=0
percard=Counter(); pertab=defaultdict(float)
for r in man:
    # The accounting period of the trip is not the payment source window.
    # Keep Q1 prepayments and Q2 refunds even when the trip tab is October.
    a=i(r['amount'])
    if a==0: continue
    book=str(r.get('book','')).strip()
    sd=d10(r['date'])   # 수기 결제(승인)일
    # 연도 오기 보정: 미래 날짜(오늘 이후)는 전년도 결제의 오타('26.12.31'→2025-12-31 실카드 확인됨)
    if sd and sd>'2026-07-20':
        sd=str(int(sd[:4])-1)+sd[4:]
    # dedup 안전장치: 예약참조가 base에 이미 있으면 skip
    if book and book in book_in: continue
    # 결제일 규칙(2026-07-22 구조 수정): 카드건은 '수기 기재일'이 아니라 '카드 매칭 실재'로 판정.
    #   base(승인-Q2) 카드는 선소비 잠금으로 여기서 매칭 자체가 불가 → 매칭되면 비-base(Q1 선결제) 실거래.
    #   ★경계 공백 실측(에히메 아고다 2건 332,038): 승인 3/31(Q1)+수기 기재 4/1 → 구가정(기재일<4/1만 추가)에서 누락.
    cm=None
    if is_card(r['card']):
        # ★끝4자리 카드열(8835 등)을 발급사로 변환해 매칭 확장하는 시도는 2026-07-22 기각:
        #   ±2% 퍼지 매칭이 THB 거래(유럽 Adria)·동일금액 APA 4건 중 2건 등 오매칭 양산 실측.
        #   금액 변경 없는 명칭 카드열(국민/하나/기업)만 매칭 — 끝4자리 무일자 건은 수기 그대로 두고 보고.
        cm=card_match(
            abs(a),
            {'국민':'국민','하나':'하나','기업':'기업'}.get(r['card'],''),
            want_cx=(a<0),
            use_date=sd,
            merchant=r['item'],
        )
        if cm is None:
            # The exact raw event was already consumed by the base, or this
            # manual card entry has no card-source support.  In either case,
            # do not manufacture another payment from the manual row.
            continue
    # === 미포함(Q1 선결제 or 현금) → 추가 ===
    n+=1
    acct=account_of(r['item'],r['desc'])
    src,issuer=src_of(r['card'],r['item'],acct)
    cardcell = a  # 금액: 카드 우선
    fx='';cur='';country='해외'; ap=''; oap=''
    if is_card(r['card']):
        if cm:
            cardcell = cm['amt'] if a>=0 else -cm['amt']
            fx=cm['fx']; cur=cm['cur']; ap=cm.get('appr','')
            if cm['sub']=='국내': country='KR'
            # ★규칙(사용자 확정): 환불→원거래 연결은 '승인번호' 기준. 국민국내=괄호형 원승인, 하나=동일행 승인번호.
            if a<0: oap=cm.get('orig','') or (ap if cm.get('src')=='HAN' else '')
        percard[issuer]+=1
    else:
        cashtot+=abs(a); country='KR'
    # VAT/원가: 해외여행 원가 대부분 불공제_해외 (부가세 영향 0). 국내(부산 등)만 확인.
    dom = r['tab'].endswith('부산') or (src=='MAN')
    vat_tag='확인' if (dom and src!='MAN') else ('불공제_국내' if src=='MAN' else '불공제_해외')
    if src=='MAN': vat_tag='불공제_현금'
    cancel = a<0
    row={k:'' for k in FN}
    mr=manrow(r)
    if cm is None and not mr:
        # A positional TRIP UID would make this row look stable while it is
        # not.  Stop for evidence instead of assigning an order-dependent
        # fallback identity.
        raise RuntimeError(
            'manual source row is required for lossless lineage: %s / %s / %s'
            % (r.get('tab',''), r.get('item',''), r.get('amount',''))
        )
    rowtag='수기%s행 | '%mr if mr else ''
    # 예약번호→체크인일 오버라이드(2026-07-22 사용자 확정서 제공): 무일자 6건 — 현지결제 APA/카즈베기는
    #   체크인=결제일, 아드리아는 선결제라 체크인일 대용. 확정서 금액은 수기값과 일치 확인됨.
    BOOK_DATE={'1721756989':'2026-04-26','1721757952':'2026-04-26','1721758806':'2026-04-26','1721761805':'2026-04-26',
               '1715820607':'2026-05-10','1717093956':'2026-05-15'}
    # APA 가나자와 4건 금액교체(2026-07-22 사용자 확정): 편의환율 604,800→실제 카드 총결제 2,287,848÷4=571,962.
    #   (카드는 JPY241,920 1건 합산청구, 4행 균등배분. 대표님 다른 국민해외건과 총결제금액 기준 통일.)
    BOOK_KRW={'1721756989':571962,'1721757952':571962,'1721758806':571962,'1721761805':571962}
    if book in BOOK_KRW: cardcell = BOOK_KRW[book] if a>=0 else -BOOK_KRW[book]
    # 날짜 fallback: 수기 기재일이 깨졌으면(에히메 55행 '25.0' 실측) 매칭 카드 승인일 사용
    source_event_id = (
        'card:%s' % card_key(cm)
        if cm is not None
        else 'manual:%s:%s' % (normtab(r['tab']), mr)
    )
    source_event_members = card_key(cm) if cm is not None else source_event_id
    source_event_disposition = 'raw_card_linked' if cm is not None else 'manual_source'
    row.update(uid='TRIP-%04d'%n, source_event_id=source_event_id, source_event_members=source_event_members, source_event_disposition=source_event_disposition, src=src, use_date=BOOK_DATE.get(book, sd or d10(r['date']) or (cm.get('use','') if cm else '')), post_date='', card4=(r['card'] if re.match(r'\d{4}',r['card'] or '') else ''),
        merchant=r['item'], country=country, currency=cur or ('KRW' if is_card(r['card']) else ''), foreign=fx or '0',
        krw=str(cardcell), vat='0.0', status=('취소' if cancel else '정상'), extra='', bucket=r['tab'], account=acct,
        cancel=str(cancel), cost_type='여행원가', vat_tag=vat_tag, confidence='상',
        note='%s수기장부 선결제 반영(%s) | %s%s'%(rowtag, issuer, r['desc'], ' 예약'+book if book else ''),
        tax_conf='상', appr=(ap if not cancel else ''), orig_appr=oap)
    new.append(row); addtot+=cardcell; pertab[r['tab']]+=cardcell

# Exact full refunds are an audit relation, not an unassigned expense.
_refund_rows=[]
for _original,_refund in exact_full_refund_pairs(cls+new, cards, _used_card):
    _used_card.add(card_key(_refund))
    _previous_bucket=_original.get('bucket','')
    _original['bucket']='취소환불'
    _original['note']=(
        (_original.get('note') or '')
        + ' | 전액환불쌍:%s'%_refund.get('raw_record_id')
    ).strip(' |')
    _refund_row={k:'' for k in FN}
    _refund_row.update(_original)
    _refund_row.update(
        uid='REFUND-%s'%str(_refund.get('raw_record_id')).replace(':','-'),
        source_event_id='card:%s:%s' % (_refund.get('src'), _refund.get('raw_record_id')),
        source_event_members='%s:%s' % (_refund.get('src'), _refund.get('raw_record_id')),
        source_event_disposition='raw_card_linked',
        krw=str(-abs(int(_refund.get('amt') or 0))),
        status='취소',
        cancel='True',
        bucket='취소환불',
        orig_appr=_refund.get('appr',''),
        note='원거래 %s 전액환불 | 이전배분:%s'%(
            _original.get('uid',''),
            _previous_bucket,
        ),
    )
    _refund_rows.append(_refund_row)
new += _refund_rows

# ── 옵션① (사용자 2026-07-23 "1번으로 가야해"): 미매칭 실카드 → 여행_미배정 ──
#   base(classified_v12)·수기매칭 어디에서도 소비 안 된 카드 = 워크북 어디에도 없는 실결제(진에어30k 등 누락 근본원인).
#   Q2 승인(2026-04~06)만 대상. 날짜근접 자동귀속은 하지 않고(사용자가 ②를 기각) 여행_미배정에 담아 대표님 검토.
_mi=0; misc=[]; misctot=0; miscissuer=Counter()
_ISS={'KBO':'국민','KBD':'국민','HAN':'하나','CORP':'기업'}
_zero_net_approvals = zero_net_cancellation_approvals(cls + new)
for c in cards:
    if card_key(c) in _used_card: continue
    _lifecycle_key = (
        str(c.get('src') or '').strip().upper(),
        str(c.get('appr') or '').strip().lstrip('0'),
    )
    if _lifecycle_key in _zero_net_approvals:
        _used_card.add(card_key(c))
        continue
    u=c.get('use') or ''
    if not ('2026-04-01'<=u<='2026-06-30'): continue   # Q2 승인만(Q1 선결제 미매칭은 여기 제외 — 대응 여행탭 불명)
    _mi+=1
    amt = -c['amt'] if c['cx'] else c['amt']
    issuer=_ISS.get(c['src'],'기타'); miscissuer[issuer]+=1
    acct=account_of(c['mer'],'')
    row={k:'' for k in FN}
    row.update(uid='MISC-%04d'%_mi, source_event_id='card:%s' % card_key(c), source_event_members=card_key(c), source_event_disposition='raw_card_linked', src=c['src'], use_date=u, post_date='',
        card4=c.get('c4',''), merchant=c['mer'], country=('KR' if c['sub']=='국내' else '해외'),
        currency=c['cur'] or 'KRW', foreign=c['fx'] or '0', krw=str(amt), vat='0.0',
        status=('취소' if c['cx'] else '정상'), bucket='여행_미배정', account=acct,
        cancel=str(c['cx']), cost_type='여행원가', vat_tag='불공제_해외', confidence='하',
        note='⚠수기 미기재 실카드결제(%s) — 대표님 검토요망: 여행탭 귀속/판관비 판정 필요'%issuer,
        tax_conf='하', appr=c.get('appr',''), orig_appr='')
    misc.append(row); misctot+=amt; _used_card.add(card_key(c))
print('옵션① 미매칭 Q2 실카드 → 여행_미배정: %d건 %s (합 %s)'%(_mi, dict(miscissuer), format(misctot,'+,')))
if DRY_RUN:
    for _candidate in misc[:20]:
        print(
            '  REVIEW %s %s %s %s %s'
            % (
                _candidate['src'],
                _candidate['use_date'],
                _candidate['krw'],
                _candidate['merchant'],
                _candidate['appr'],
            )
        )
new += misc

# Append-only human decision projection (2026-07-26).
# Keep this narrowly keyed by the stable card event UID: KSNET is only a
# payment gateway, so merchant/card suffix alone must never classify every
# KSNET transaction as late-night transport.
_USER_CONFIRMED_EXPENSE_OVERRIDES = {
    'KBD-1095': {
        'bucket': '기타비용',
        'account': '여비교통비',
        'cost_type': '판관비',
        'confidence': '상',
        'tax_conf': '상',
        'note': '사용자 확정: 카드 3820 KSNET_N 21,000원은 야근 교통비',
    },
}
for _row in cls + new:
    _override = _USER_CONFIRMED_EXPENSE_OVERRIDES.get(_row.get('uid'))
    if _override:
        _row.update(_override)

# ── 대사 게이트 (사용자 "왜 계속 누락"): Q2 승인 카드가 base·수기·미배정 어디에도 없으면 누락 → 경고 ──
_lost=[c for c in cards if card_key(c) not in _used_card and '2026-04-01'<=(c.get('use') or '')<='2026-06-30']
if _lost:
    print('⚠️ 대사 실패: Q2 승인 카드 %d건이 어디에도 편입 안 됨(누락):'%len(_lost))
    for c in _lost[:20]: print('   ', c['co'], c['use'], format(c['amt'],','), (c['mer'] or '')[:24])
else:
    print(
        'Q2 카드 원천 범위 내 누락 0: base·수기·여행_미배정에 존재'
        ' (정본 전체 재현 판정은 최종 P0 gate에서만 수행)'
    )

out=cls+new
_lineage_ids=[str(row.get('source_event_id') or '') for row in out]
_missing_lineage=[row.get('uid','') for row in out if not row.get('source_event_id')]
_missing_disposition=[row.get('uid','') for row in out if not row.get('source_event_disposition')]
_duplicate_lineage=[key for key,count in Counter(_lineage_ids).items() if count>1]
if _missing_lineage or _missing_disposition or _duplicate_lineage:
    raise RuntimeError(
        'source event lineage must be non-empty and one projection per source event; '
        'missing=%s disposition=%s duplicate=%s'
        % (', '.join(_missing_lineage[:5]), ', '.join(_missing_disposition[:5]), ', '.join(_duplicate_lineage[:5]))
    )

# An exact N:M group is deliberately not assigned to arbitrary individual
# rows.  Its raw members must nevertheless be carried unchanged on every
# participating projection row so later stages can verify coverage.
for _row in out:
    _event_id=str(_row.get('source_event_id') or '')
    _members=str(_row.get('source_event_members') or '')
    if _event_id.startswith(('card-group:', 'card-group-blank-merchant:')):
        _group_id=_event_id.rsplit(':',1)[0]
        _expected_members=_balanced_group_members.get(_group_id, _blank_group_members.get(_group_id))
        if _members != _expected_members:
            raise RuntimeError('invalid exact-group source membership for %s' % _event_id)
    elif _event_id.startswith('card:'):
        if _members != _event_id[len('card:'):]:
            raise RuntimeError('invalid card source membership for %s' % _event_id)
    elif _event_id.startswith('manual:') and _members != _event_id:
        raise RuntimeError('invalid manual source membership for %s' % _event_id)
    elif _event_id.startswith('adjustment:'):
        if _members != _event_id or _row.get('source_event_disposition') != 'projection_adjustment_pending_review':
            raise RuntimeError('invalid zero-amount adjustment disposition for %s' % _event_id)
    elif _event_id.startswith('projection-alias:'):
        if (
            _members != _event_id
            or _row.get('source_event_disposition') != 'superseded_duplicate_projection'
            or not _row.get('source_event_alias_of')
        ):
            raise RuntimeError('invalid superseded duplicate alias for %s' % _event_id)
    elif _event_id.startswith('manual-claimed-card-no-raw:'):
        if (
            _members != _event_id
            or _row.get('source_event_disposition') != 'manual_claimed_card_no_raw'
            or not str(_row.get('source_event_alias_of') or '').startswith('manual:')
        ):
            raise RuntimeError('invalid manual claimed/no-raw alias for %s' % _event_id)
    elif _event_id.startswith('rejected-legacy-projection:'):
        if (
            _members != _event_id
            or _row.get('source_event_disposition') != 'rejected_legacy_projection'
            or not _row.get('source_event_alias_of')
        ):
            raise RuntimeError('invalid rejected legacy projection for %s' % _event_id)

_direct_card_members=[
    str(row.get('source_event_members') or '')
    for row in out
    if str(row.get('source_event_id') or '').startswith('card:')
]
_duplicate_direct_members=[key for key,count in Counter(_direct_card_members).items() if count>1]
if _duplicate_direct_members:
    raise RuntimeError(
        'one raw card event is projected more than once: %s'
        % ', '.join(_duplicate_direct_members[:5])
    )

require_protected_uids_preserved(
    ({'uid': uid} for uid in _input_legacy_uids), out, {'KBO-9002'}
)
require_valid_nonposting_aliases(out)
require_raw_cancellation_signs(out)
if DRY_RUN:
    print(
        'LINEAGE SEMANTIC COUNTS:',
        json.dumps(lineage_semantic_counts(out), ensure_ascii=False, sort_keys=True),
    )

if not DRY_RUN:
    if OUTPUT_PATH.exists():
        raise FileExistsError('기존 후보를 덮어쓰지 않습니다: %s'%OUTPUT_PATH)
    OUTPUT_PATH.parent.mkdir(parents=True,exist_ok=True)
    with OUTPUT_PATH.open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(out)
oldtot=sum(abs(i(r['krw'])) for r in cls); newtot=sum(i(r['krw']) for r in out)
print('추가 %d건 (증빙별 %s), 현금계열 합 %s'%(n, dict(percard), format(cashtot,',')))
print('classified_v13 후보: %s / 입력SHA %s / %d행, krw합 %s (기존 221,040,838 → 증가 %s)'%(OUTPUT_PATH,_input_sha,len(out),format(newtot,','),format(newtot-221040838,'+,')))
print('-- 여행탭별 추가액 --')
for t,s in sorted(pertab.items(),key=lambda x:-x[1]):
    print('  {:16} {:+,}'.format(t,round(s)))
