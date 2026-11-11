"""보존된 아고다 페이지의 기존 결제 근거를 읽기 전용으로 대조한다."""
import datetime
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.reconciliation import OTA_PORTAL_ORIGIN


def evidence_path(data_directory):
    configured=os.environ.get('WEBLEDGER_AGODA_PORTAL_DB')
    if configured:
        return Path(configured)
    current=Path(data_directory)/'agoda-portal.sqlite'
    if current.is_file():
        return current
    # 경량화 전에 사용자가 전수조사한 원본을 삭제하거나 새로 수집하지 않는다.
    return Path(__file__).resolve().parents[1]/'outputs/agoda-paseo-staging-20260822.sqlite'


def as_databases(databases):
    """단일 DB와 목록을 같은 형태로 읽는다. 한 곳만 주면 한 목록이 된다."""
    if databases is None:
        return []
    if isinstance(databases,(str,Path)):
        return [Path(databases)]
    return [Path(item) for item in databases]


# 재현된 레거시 양식. 확정 문구를 완료로 바꾸지 않고 그대로 읽는다.
LEGACY_CONFIRMED_PAID='고객님의 예약은 확정되었으며 결제가 성공적으로 처리되었습니다'
LEGACY_PAYMENT_DONE='결제 완료됨'
LEGACY_PAYMENT_STATE='paid_today'
# 예약은 확정되어도 결제는 아직 예정인 경우. 실제 결제 근거로 쓰지 않는다.
SCHEDULED_MARKERS=('결제될 예정','결제 예정입니다','결제 예정','will be charged',
                   'payment is scheduled','scheduled to be charged')
# Signed-in Agoda booking-detail evidence: the page snapshot and the page's own detail API.
DETAIL_FORMATS=('agoda-aside-v1','agoda-api-v1')
REQUIRED_EVIDENCE_ROLES={'identity','service_period','portal_payment_claim',
                         'portal_card_observation','lifecycle'}
# 같은 예약에 대해 자료끼리 정면으로 어긋난다는 뜻인 사유만 상충으로 본다.
# 근거가 부족하다는 것과 다른 자료와 다르다는 것은 다르다.
CONFLICTING_REASONS={'future_payment','evidence_conflict','refund_or_cancellation',
                     'booking_identity_mismatch','service_period_conflict',
                     'card_observation_missing','amount_conflict'}


def price_amounts(fact):
    """실제 결제된 금액만 통화쌍으로 모은다. 예약 상태와 무관하게 읽는다."""
    amounts=set()
    try:
        for component in fact.get('price_components',[]) or []:
            if component.get('kind')!='paid_today':
                continue
            amount=Decimal(str(component['decimal_text']).replace(',',''))
            if (not amount.is_finite() or amount<=0
                    or amount*(Decimal(10)**component['scale'])!=component['minor_units']):
                raise ValueError('OTA_PORTAL_AMOUNT_CONFLICT')
            amounts.add((component['currency'],amount))
    except (InvalidOperation,KeyError,TypeError,ValueError,AttributeError):
        return set()
    return amounts


def scheduled_payment(fact):
    """결제가 아직 예정인지 본문과 상태에서 함께 확인한다."""
    state=str(fact.get('portal_payment_state') or '')
    status=str(fact.get('payment_status') or '')
    if state in ('scheduled','pending','will_charge','scheduled_charge') or 'scheduled' in state:
        return True
    if status=='scheduled':
        return True
    return any(marker in status for marker in SCHEDULED_MARKERS)


def payment_verdict(fact, booking_status):
    """명시된 실제 결제 근거를 확인한다. 예약 확정이 이용 완료를 뜻하지 않는다.

    반환은 `paid`(실제 결제 근거 있음), `scheduled`(결제 예정이라 보류),
    `unverified`(근거 없음) 셋이다. 레거시 확정+완료 양식은 조건이 모두
    명시되었을 때만 `paid` 다. absent collection 은 이 경우에만 허용한다.
    """
    if scheduled_payment(fact):
        return 'scheduled'
    # Aside의 명시 결제 표시를 읽는다. 수집일이나 예약 완료를 결제일로 바꾸지 않는다.
    if (fact.get('evidence_format') in DETAIL_FORMATS
            and fact.get('portal_payment_state') == 'paid_observed'
            and fact.get('payment_status') == 'paid'
            and re.fullmatch(r'\d{4}', str(fact.get('card_last4') or ''))
            and len(price_amounts(fact)) == 1):
        return 'paid'
    canonical=(fact.get('reservation_status')=='completed' and booking_status=='completed'
               and fact.get('payment_status')=='paid'
               and fact.get('collection_model')=='agoda_collect')
    legacy=(fact.get('reservation_status')==LEGACY_CONFIRMED_PAID
            and booking_status=='confirmed'
            and fact.get('payment_status')==LEGACY_PAYMENT_DONE
            and fact.get('portal_payment_state')==LEGACY_PAYMENT_STATE)
    if legacy and 'collection_model' not in fact:
        return 'paid'
    if canonical:
        return 'paid'
    return 'unverified'


def _read_records(path, index):
    """포털 DB 한 곳의 근거 행. DB마다 같은 숫자 ID가 있으므로 DB를 함께 구분한다."""
    from app.ota_store import is_store, portal_rows
    if is_store(path):
        return portal_rows(path, index)
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    from .p2_source_io import guard_connection
    guard_connection(conn)
    try:
        records=conn.execute(
            "SELECT b.booking_number,b.service_start_on,b.service_end_on,b.status,"
            "d.id,d.payload_json,d.source_sha256,e.evidence_role,e.evidence_status,e.conflict_count "
            "FROM bookings b JOIN booking_source_evidence e ON e.booking_id=b.id "
            "JOIN direct_source_records d ON d.id=e.direct_source_record_id "
            "WHERE b.provider='agoda' AND d.source_kind='agoda_portal_detail'").fetchall()
    finally:
        conn.close()
    return [dict(row, database=index) for row in records]


def collect_portal_facts(databases):
    """등록된 포털 DB를 모두 읽어 예약별 사실과 보류 사유를 함께 정리한다.

    `facts` 는 실제 결제 근거가 다섯 역할까지 확인된 예약이고, `rejected`
    는 카드·금액·기간 등 대조에 쓸 값과 함께 왜 쓰이지 않았는지 reasons
    남긴다. 진단이 금액을 추측하지 않고 이 관계를 읽도록 하기 위한 준비다.
    """
    paths=[path for path in (Path(item).resolve() for item in as_databases(databases))
           if path.is_file()]
    records=[]
    for index,path in enumerate(paths):
        records.extend(_read_records(path,index))
    # 숫자 source id는 DB마다 겹친다. DB까지 묶어야 서로 다른 근거가 합쳐지지 않는다.
    grouped=defaultdict(list)
    blocked=set()
    conflicting=set()
    for row in records:
        grouped[(row['database'],row['booking_number'],row['id'])].append(row)
        if row['conflict_count'] or row['evidence_status'] != 'observed':
            blocked.add(row['booking_number'])
            conflicting.add(row['booking_number'])
    facts=defaultdict(dict)
    rejected={}
    observations=defaultdict(list)
    def note(booking, reason, card_last4='', amounts=frozenset(), period=None, roles=0):
        # 자료 처리 순서와 무관하게 예약별 관측을 모두 모은다.
        observations[booking].append({'reason':reason,'card_last4':card_last4,
                                     'amounts':set(amounts),'period':period,'roles':roles})
        return observations[booking][-1]
    for (database,booking,source_id),evidence in grouped.items():
        first=evidence[0]
        roles=len({r['evidence_role'] for r in evidence})
        if booking in blocked:
            note(booking,'evidence_conflict',roles=roles)
            continue
        if not REQUIRED_EVIDENCE_ROLES <= {r['evidence_role'] for r in evidence}:
            note(booking,'evidence_incomplete',roles=roles)
            continue
        raw=first['payload_json']
        if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=first['source_sha256']:
            raise ValueError('OTA_PORTAL_PAYLOAD_HASH_MISMATCH')
        fact=json.loads(raw)
        card_last4=str(fact.get('card_last4') or '')
        period={'starts_on':fact.get('service_start_on'),'ends_on':fact.get('service_end_on')}
        # 보류로 넘어가는 예약도 카드와 금액을 남긴다. 진단이 근거 관계를 읽도록.
        amounts=price_amounts(fact)
        if (fact.get('reservation_status') in ('cancelled','refunded')
                or fact.get('refund_status') not in (None,'none_displayed')):
            blocked.add(booking)
            conflicting.add(booking)
            note(booking,'refund_or_cancellation',card_last4,amounts,period,roles)
            continue
        if fact.get('provider')!='agoda' or fact.get('booking_number')!=booking:
            note(booking,'booking_identity_mismatch',card_last4,amounts,period,roles)
            continue
        verdict=payment_verdict(fact,first['status'])
        if verdict!='paid':
            note(booking,'future_payment' if verdict=='scheduled' else 'unverified_payment',
                 card_last4,amounts,period,roles)
            continue
        if fact.get('refund_status')!='none_displayed':
            note(booking,'refund_or_cancellation',card_last4,amounts,period,roles)
            continue
        if not re.fullmatch(r'\d{4}',str(fact.get('card_last4') or '')):
            note(booking,'card_observation_missing',card_last4,amounts,period,roles)
            continue
        start=fact.get('service_start_on');end=fact.get('service_end_on')
        if start!=first['service_start_on'] or end!=first['service_end_on']:
            blocked.add(booking)
            conflicting.add(booking)
            note(booking,'service_period_conflict',card_last4,amounts,period,roles)
            continue
        if not start or not end:
            note(booking,'service_period_missing',card_last4,amounts,period,roles)
            continue
        try:
            if datetime.date.fromisoformat(start)>datetime.date.fromisoformat(end):
                note(booking,'service_period_invalid',card_last4,amounts,period,roles)
                continue
        except (TypeError,ValueError):
            note(booking,'service_period_invalid',card_last4,amounts,period,roles)
            continue
        if not amounts:
            note(booking,'amount_missing',card_last4,amounts,period,roles)
            continue
        if len(amounts)!=1:
            note(booking,'amount_ambiguous',card_last4,amounts,period,roles)
            continue
        if fact.get('evidence_format') in DETAIL_FORMATS and not fact.get('paid_on'):
            # 결제일 없는 새 관측이 기존 예정일·카드 원행의 검증된 연결을 가로채지 않는다.
            note(booking,'payment_date_unknown',card_last4,amounts,period,roles)
            continue
        currency,amount=next(iter(amounts))
        signature=(fact['card_last4'],currency,amount,start,end)
        facts[booking][signature]=dict(booking_ref=booking,card_last4=fact['card_last4'],
            currency=currency,amount=amount,period={'starts_on':start,'ends_on':end},
            source_sha256=first['source_sha256'],payment_format=(
                'legacy_confirmed_paid' if fact.get('reservation_status')==LEGACY_CONFIRMED_PAID
                else 'canonical_paid'))
        note(booking,'paid',card_last4,amounts,{'starts_on':start,'ends_on':end},roles)
    for booking,seen in observations.items():
        reasons={item['reason'] for item in seen}
        if booking in facts and reasons&CONFLICTING_REASONS:
            # 같은 예약이 여러 자료에서 정면으로 어긋나면 어느 한쪽도 정본으로 쓰지 않는다.
            blocked.add(booking)
            conflicting.add(booking)
            facts.pop(booking,None)
        for item in seen:
            if item['reason']!='paid':
                rejected[booking]=item
                break
    return {'facts':dict(facts),'rejected':rejected,'blocked':blocked,
            'conflicting':conflicting,'databases':paths}


def portal_matches(databases, transactions, *, analysis=None):
    """등록된 포털 DB를 모두 함께 읽고, 전체 예약과 전체 거래를 한 번에 대조한다.

    DB마다 따로 매칭한 뒤 합치지 않는다. 다른 DB에 있는 예약이 모호성을
    만들면 그 자리에서 막힌다. 같은 예약·카드·기간·상태·금액이 여러 DB에
    같게 있으면 같은 사실이므로 무해하다.
    """
    analysis=collect_portal_facts(databases) if analysis is None else analysis
    facts=analysis['facts']
    blocked=analysis['blocked']
    if not facts:
        return []
    candidates=defaultdict(list)
    rows_by_booking=defaultdict(set)
    for row in unique_transactions(transactions):
        if (row.get('transaction_direction')!='purchase' or row.get('duplicate_of')
                or row.get('parse_error') or row.get('conflict_reason')
                or not re.match(r'^(?:AGODA(?:\b|[._ *-])|아고다)',str(row.get('merchant') or '').upper())):
            continue
        try:
            amounts={('KRW',Decimal(str(row['amount_krw'])))} if row.get('amount_krw') else set()
            if row.get('foreign_amount') and row.get('foreign_currency'):
                amounts.add((row['foreign_currency'],Decimal(str(row['foreign_amount']))))
        except InvalidOperation:
            continue
        for booking,versions in facts.items():
            if booking in blocked or len(versions)!=1:
                continue
            fact=next(iter(versions.values()))
            if row.get('card_tail')==fact['card_last4'] and (fact['currency'],fact['amount']) in amounts:
                candidates[row['transaction_id']].append((row,fact))
                rows_by_booking[booking].add(row['transaction_id'])
    matches=[]
    matched=set()
    for options in candidates.values():
        if len(options)!=1:
            continue
        row,fact=options[0]
        if len(rows_by_booking[fact['booking_ref']])!=1:
            continue
        matched.add(row['transaction_id'])
        matches.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
            merchant=row['merchant_normalized'],card_kind=row['card_kind'],direction='purchase',
            provider='agoda',booking_ref=fact['booking_ref'],item='숙박비',period=fact['period'],
            source_sha256=fact['source_sha256'],evidence_kind='portal_payment_claim',
            reservation_status='observed',strict_service_period=True,
            payment_format=fact.get('payment_format','canonical_paid'),
            basis=('아고다 전수조사 페이지의 예약 확정과 실제 결제 근거·결제액·통화·카드 끝자리'
                   '가 카드 원행과 일대일로 일치' if fact.get('payment_format')=='legacy_confirmed_paid'
                   else '아고다 전수조사 페이지의 완료 예약·실제 결제액·통화·카드 끝자리'
                        '와 카드 원행이 일대일로 일치')))
    matches+=_identical_group_matches(candidates, rows_by_booking, matched)
    return matches


def _identical_group_matches(candidates, rows_by_booking, matched):
    """Identical payments and identical bookings (same card, amount, currency and stay) cannot be told apart by amount,
    but they all land on the same trip. When a group has as many unmatched card rows as bookings, pair them one to one."""
    groups=defaultdict(lambda: {'rows':{}, 'bookings':set()})
    row_keys={}
    for tid,options in candidates.items():
        if tid in matched:
            continue
        keys={(fact['card_last4'],fact['currency'],str(fact['amount']),json.dumps(fact['period'],sort_keys=True,default=str))
              for _,fact in options}
        if len(keys)!=1:
            continue
        key=next(iter(keys))
        row_keys[tid]=key
        groups[key]['rows'][tid]=options[0][0]
    out=[]
    for key,group in groups.items():
        bookings={fact['booking_ref'] for tid in group['rows'] for _,fact in candidates[tid]}
        if len(bookings)!=len(group['rows']):
            continue
        if any(set(rows_by_booking[b])-set(group['rows']) or b in {f['booking_ref'] for tid in candidates if tid in matched for _,f in candidates[tid]} for b in bookings):
            continue
        fact_of={}
        for tid in group['rows']:
            for _,fact in candidates[tid]:
                fact_of.setdefault(fact['booking_ref'],fact)
        # 같은 카드·금액·기간의 예약은 어느 것인지 가릴 수 없다. 예약번호를 행마다 고르지 않고 묶음 건수와 여행 기간만 남긴다.
        representative=fact_of[min(bookings)]
        for tid in sorted(group['rows']):
            row=group['rows'][tid]
            out.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                merchant=row['merchant_normalized'],card_kind=row['card_kind'],direction='purchase',
                provider='agoda',booking_ref='',group_size=len(bookings),item='숙박비',period=representative['period'],
                source_sha256=representative['source_sha256'],evidence_kind='portal_payment_claim',
                reservation_status='observed',strict_service_period=True,
                payment_format=representative.get('payment_format','canonical_paid'),
                basis=f'아고다 전수조사 페이지의 같은 카드·금액·기간 예약 {len(bookings)}건과 카드 원행이 같은 수만큼 있어 묶음으로 대응(예약번호 미선택)'))
    return out


def portal_inventory(databases):
    """등록된 포털 DB의 열림 상태만 알려준다. 없으면 조용히 넘기지 않는다."""
    inventory=[]
    for path in (Path(item) for item in as_databases(databases)):
        entry={'kind':'portal_database','path':str(path),'usable':False}
        if not path.is_file():
            entry['error']='file_not_found'
        else:
            entry['usable']=True
            info=path.stat()
            entry['mtime_ns']=info.st_mtime_ns
            entry['size']=info.st_size
        inventory.append(entry)
    return {'sources':inventory,'errors':[entry for entry in inventory if entry.get('error')]}


SCHEDULED_CARD_DATE_EVIDENCE='portal_scheduled_card_date'
SCHEDULED_AUTO_CHARGE=re.compile(r'future_due:auto_charge_scheduled_(\d{4}-\d{2}-\d{2})')
AGODA_MERCHANT=re.compile(r'^(?:AGODA(?:\b|[._ *-])|아고다)')


def scheduled_card_date_enabled():
    from app.ota_matching_defaults import load_defaults
    return bool(load_defaults().get('portal_scheduled_card_date_enabled', False))


def _scheduled_charge(fact):
    """자동결제 예정일과 총액. 실제 결제일이 아니므로 카드 원행의 이용일이 같을 때만 결제로 쓴다."""
    found=SCHEDULED_AUTO_CHARGE.fullmatch(str(fact.get('payment_status') or ''))
    if not found or fact.get('collection_model')!='agoda_collect_card_auto_charge':
        return None
    try:
        day=datetime.date.fromisoformat(found.group(1)).isoformat()
    except ValueError:
        return None
    parts={}
    for component in fact.get('price_components') or []:
        kind=component.get('kind')
        if kind in ('base','taxes_and_fees','gross_total'):
            if kind in parts:
                return None
            parts[kind]=component
    gross=parts.get('gross_total')
    if gross is None or str(gross.get('currency') or '').upper()!='KRW':
        return None
    try:
        amount=Decimal(str(gross['decimal_text']).replace(',',''))
        if (not amount.is_finite() or amount<=0
                or amount*(Decimal(10)**gross['scale'])!=gross['minor_units']):
            return None
        if 'base' in parts and 'taxes_and_fees' in parts:
            if sum(Decimal(str(parts[kind]['decimal_text']).replace(',','')) for kind in ('base','taxes_and_fees'))!=amount:
                return None
    except (InvalidOperation,KeyError,TypeError,ValueError):
        return None
    return dict(day=day,amount=amount)


def _status_progression_only(conflict_json):
    """이전 캡처의 예정 상태가 확정으로 바뀐 것만 허용한다. 다른 충돌이 하나라도 있으면 막는다."""
    try:
        items=json.loads(conflict_json or '[]')
    except (TypeError,ValueError):
        return False
    return bool(items) and all(isinstance(item,dict) and item.get('field')=='status'
                               and item.get('existing')=='upcoming' and item.get('incoming')=='confirmed'
                               for item in items)


def _read_scheduled_records(path,index):
    """_read_records와 같은 행을 읽되 충돌 상세도 함께 읽는다. 상세 열이 없는 자료는 충돌을 막는 쪽으로 읽는다."""
    from app.ota_store import is_store, portal_rows
    if is_store(path):
        return portal_rows(path,index,scheduled=True)
    query=("SELECT b.booking_number,b.service_start_on,b.service_end_on,b.status,"
           "d.id,d.payload_json,d.source_sha256,e.evidence_role,e.evidence_status,e.conflict_count,{detail} "
           "FROM bookings b JOIN booking_source_evidence e ON e.booking_id=b.id "
           "JOIN direct_source_records d ON d.id=e.direct_source_record_id "
           "WHERE b.provider='agoda' AND d.source_kind='agoda_portal_detail'")
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        try:
            records=conn.execute(query.format(detail='e.conflict_json AS conflict_json')).fetchall()
        except sqlite3.OperationalError:
            records=conn.execute(query.format(detail='NULL AS conflict_json')).fetchall()
    finally:
        conn.close()
    return [dict(row, database=index) for row in records]


def scheduled_card_date_matches(databases, transactions):
    """포털 자동결제 예정일이 카드 이용일과 같고 금액·카드 끝자리가 맞으면 그 카드 원행을 결제로 본다.

    포털에는 실제 결제일이 없어 기존 규칙으로는 막히던 예약이다. 카드 원행의 이용일이 예정일과 같을 때만
    쓴다(소유자 결정 2026-10-16). 예약이 예정에서 확정으로 바뀐 충돌만 허용하고 다른 충돌은 막는다.
    """
    if not scheduled_card_date_enabled():
        return []
    paths=[path for path in (Path(item).resolve() for item in as_databases(databases)) if path.is_file()]
    rows=[]
    for index,path in enumerate(paths):
        rows.extend(_read_scheduled_records(path,index))
    grouped=defaultdict(list)
    for row in rows:
        grouped[(row['database'],row['booking_number'],row['id'])].append(row)
    signatures=defaultdict(set)
    digests=defaultdict(set)
    excluded=set()
    for (database,booking,record_id),evidence in sorted(grouped.items(),key=lambda item:str(item[0])):
        first=evidence[0]
        raw=first['payload_json']
        if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=first['source_sha256']:
            raise ValueError('OTA_PORTAL_PAYLOAD_HASH_MISMATCH')
        fact=json.loads(raw)
        if fact.get('provider')!='agoda' or fact.get('booking_number')!=booking:
            excluded.add(booking)
            continue
        if (fact.get('reservation_status') in ('cancelled','refunded')
                or fact.get('refund_status') not in (None,'none_displayed')):
            excluded.add(booking)
            continue
        charge=_scheduled_charge(fact)
        if charge is None:
            if payment_verdict(fact,first['status'])=='paid':
                excluded.add(booking)
            continue
        card_last4=str(fact.get('card_last4') or '')
        start,end=fact.get('service_start_on'),fact.get('service_end_on')
        try:
            ok=(datetime.date.fromisoformat(start)<=datetime.date.fromisoformat(end))
        except (TypeError,ValueError):
            ok=False
        ok=(ok and REQUIRED_EVIDENCE_ROLES<={row['evidence_role'] for row in evidence}
            and all(row['evidence_status']=='observed' for row in evidence)
            and all(not row['conflict_count'] or _status_progression_only(row['conflict_json']) for row in evidence)
            and fact.get('status')=='confirmed' and re.fullmatch(r'\d{4}',card_last4) is not None
            and start==first['service_start_on'] and end==first['service_end_on'])
        if not ok:
            excluded.add(booking)
            continue
        signatures[booking].add((charge['day'],str(charge['amount']),card_last4,start,end))
        digests[booking].add(first['source_sha256'])
    facts={}
    for booking,options in signatures.items():
        if booking in excluded or len(options)!=1:
            continue
        day,amount,card_last4,start,end=next(iter(options))
        facts[booking]=dict(day=day,amount=Decimal(amount),card_last4=card_last4,
                            period={'starts_on':start,'ends_on':end},source_sha256=sorted(digests[booking])[0])
    candidates=defaultdict(list)
    rows_by_booking=defaultdict(set)
    for row in unique_transactions(transactions):
        if (row.get('transaction_direction')!='purchase' or row.get('duplicate_of') or row.get('parse_error')
                or row.get('conflict_reason') or not row.get('amount_krw')
                or not AGODA_MERCHANT.match(str(row.get('merchant') or '').upper())):
            continue
        for booking,fact in facts.items():
            if (row.get('card_tail')==fact['card_last4'] and row.get('approval_date')==fact['day']
                    and Decimal(str(row['amount_krw']))==fact['amount']):
                candidates[row['transaction_id']].append((row,booking,fact))
                rows_by_booking[booking].add(row['transaction_id'])
    matches=[]
    for options in candidates.values():
        if len(options)!=1:
            continue
        row,booking,fact=options[0]
        if len(rows_by_booking[booking])!=1:
            continue
        matches.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
            merchant=row['merchant_normalized'],card_kind=row['card_kind'],direction='purchase',
            provider='agoda',booking_ref=booking,item='숙박비',period=fact['period'],
            source_sha256=fact['source_sha256'],evidence_kind=SCHEDULED_CARD_DATE_EVIDENCE,
            scheduled_on=fact['day'],card_last4=fact['card_last4'],amount_krw=int(fact['amount']),
            reservation_status='observed',strict_service_period=True,payment_format='scheduled_card_date',
            basis='아고다 자동결제 예정일과 카드 이용일이 같고 금액·카드 끝자리가 카드 원행과 일대일로 일치'
                  '(포털에는 실제 결제일이 없음)'))
    return matches


def extend_report(report, database, transactions):
    """메일과 페이지를 함께 쓰되 서로 다른 예약을 제안하면 여행 연결을 보류한다."""
    # 자료가 하나도 연결되지 않아도 출처 목록과 진단은 남긴다.
    report['portal_sources']=portal_inventory(database)
    analysis=collect_portal_facts(database)
    matches=portal_matches(database,transactions,analysis=analysis)
    paid_rows={fact["transaction_id"] for fact in matches}
    matches+=[fact for fact in scheduled_card_date_matches(database,transactions)
              if fact["transaction_id"] not in paid_rows]
    if not matches:
        apply_diagnoses(report,portal_diagnoses(report,transactions,analysis))
        return report
    by_source={fact['source_hash']:fact for fact in report['matches']}
    for fact in matches:
        source=fact['source_hash'];previous=by_source.get(source)
        if previous:
            if (previous['booking_ref']!=fact['booking_ref']
                    or previous.get('reservation_status')=='cancelled'
                    or previous.get('period_conflict')
                    or previous.get('period') not in (None,fact['period'])):
                previous.update(period=None,period_conflict=True,booking_link_conflict=True)
                report['rules']=[rule for rule in report['rules']
                                 if rule.get('optional',{}).get('source_hash')!=source]
            elif previous.get('period') is None:
                previous.update(period=fact['period'],source_digests=[
                    previous['source_sha256'],fact['source_sha256']])
            continue
        report['matches'].append(fact)
        by_source[source]=fact
        report['rules'].append(dict(conditions={'merchant_normalized':fact['merchant'],
            'card_kind':fact['card_kind'],'transaction_direction':'purchase'},
            optional={'source_hash':source},effects={'item':'숙박비','description':(
                '예약 '+fact['booking_ref'] if fact.get('booking_ref') else f"예약 묶음 {fact.get('group_size', 1)}건(예약번호 미선택)")},
            origin=OTA_PORTAL_ORIGIN,note=fact['basis']))
    exact={fact['source_hash'] for fact in report['matches']}
    report['type_only_candidates']=[fact for fact in report.get('type_only_candidates',[])
                                   if fact['source_hash'] not in exact]
    report['rules']=[rule for rule in report['rules'] if
                     rule.get('optional',{}).get('source_hash') not in exact
                     or rule.get('effects',{}).get('description')]
    report['unmatched_transactions']=[fact for fact in report.get('unmatched_transactions',[])
                                     if fact['source_hash'] not in exact]
    report['booking_evidence_gaps']=[gap for gap in report.get('booking_evidence_gaps',[])
        if not by_source.get(gap['source_hash'],{}).get('period')]
    report['exact_matches']=len(report['matches'])
    report['type_only_matches']=len(report['type_only_candidates'])
    report['items']=dict(Counter(fact['item'] for fact in report['matches']))
    report['unmatched_reason_counts']=dict(Counter(fact['reason'] for fact in report['unmatched_transactions']))
    report['service_period_conflicts']=sum(bool(f.get('period_conflict')) for f in report['matches'])
    coverage=report.get('coverage',{})
    if coverage:
        purchases=[row for row in unique_transactions(transactions)
                   if row.get('transaction_direction')=='purchase' and (row.get('approval_date') or '')>='2026-04-01'
                   and any(marker in row['merchant'].upper() for marker in
                           ('TRIP.COM','트립닷컴','KLOOK','클룩','AGODA','아고다','BOOKING','부킹닷컴'))]
        kind_only={fact['source_hash'] for fact in report['type_only_candidates']}
        coverage.update(matched_purchase_rows=sum(row['source_hash'] in exact for row in purchases),
                        kind_only_rows=sum(row['source_hash'] in kind_only for row in purchases),
                        unmatched_purchase_rows=sum(row['source_hash'] not in exact|kind_only for row in purchases))
    apply_diagnoses(report,portal_diagnoses(report,transactions,analysis))
    return report


def apply_diagnoses(report, diagnoses):
    """화면과 보고서가 같은 미연결 사유를 사용한다."""
    report['portal_diagnoses']=diagnoses
    by_source={fact['source_hash']:fact['reason'] for fact in diagnoses}
    for row in report.get('unmatched_transactions',[]):
        reason=by_source.get(row['source_hash'])
        if reason and reason!=row.get('reason'):
            row.setdefault('mail_reason',row.get('reason'))
            row['reason']=reason
    report['unmatched_reason_counts']=dict(Counter(row['reason']
        for row in report.get('unmatched_transactions',[])))


def transaction_amounts(row):
    """카드 원행의 원화·외화 금액을 통화쌍으로 모은다."""
    amounts=set()
    try:
        if row.get('amount_krw'):
            amounts.add(('KRW',Decimal(str(row['amount_krw']))))
        if row.get('foreign_amount') and row.get('foreign_currency'):
            amounts.add((row['foreign_currency'],Decimal(str(row['foreign_amount'])).copy_abs()))
    except InvalidOperation:
        return set()
    return amounts


def is_agoda_purchase(row):
    return (row.get('transaction_direction')=='purchase' and not row.get('duplicate_of')
            and not row.get('parse_error') and not row.get('conflict_reason')
            and re.match(r'^(?:AGODA(?:\b|[._ *-])|아고다)',str(row.get('merchant') or '').upper()))


def _fact_amounts(versions):
    return {(fact['currency'],fact['amount']) for fact in versions.values()}


def _fact_periods(versions):
    return {tuple(sorted(fact['period'].items())) for fact in versions.values()}


def _reason_for(row, analysis, conflicted):
    """포털 사실과 카드 원행의 관계로 한 가지 원인을 정한다. 금액만 보고 추측하지 않는다."""
    facts=analysis['facts']
    rejected=analysis['rejected']
    blocked=analysis['blocked']
    amounts=transaction_amounts(row)
    tail=row.get('card_tail')
    # 카드 끝자리가 같은 예약만 본다. 다른 카드의 사실은 이 거래의 근거가 아니다.
    card_facts={booking:versions for booking,versions in facts.items()
                if any(fact['card_last4']==tail for fact in versions.values())}
    card_rejected={booking:note for booking,note in rejected.items() if note['card_last4']==tail}
    matched=[booking for booking,versions in card_facts.items()
             if _fact_amounts(versions)&amounts]
    if matched:
        if len(matched)>1:
            return 'ambiguous_booking'
        booking=matched[0]
        versions=card_facts[booking]
        if len(versions)!=1:
            return 'ambiguous_booking'
        if len(_fact_periods(versions))!=1:
            return 'ambiguous_booking'
        if booking in blocked:
            return 'booking_conflict'
        return 'no_exact_payment_evidence'
    rejected_hits=[note for booking,note in card_rejected.items()
                   if note['amounts']&amounts]
    if rejected_hits:
        reason=rejected_hits[0]['reason']
        if reason=='future_payment':
            return 'future_payment'
        if reason in ('service_period_conflict','service_period_invalid','service_period_missing'):
            return 'missing_period'
        if reason in ('refund_or_cancellation','evidence_conflict','booking_identity_mismatch'):
            return 'booking_conflict'
        if reason in ('unverified_payment','evidence_incomplete'):
            return 'unverified_payment'
        return 'booking_conflict'
    if card_facts or card_rejected:
        # 카드는 같은데 금액이 다르다. 근거가 있어도 이 금액과 맞지 않는다.
        return 'amount_mismatch'
    if conflicted:
        return 'booking_conflict'
    if row.get('amount_krw') is None and not (row.get('foreign_amount') and row.get('foreign_currency')):
        return 'payment_amount_unavailable'
    if row.get('amount_krw') is None and row.get('foreign_currency')=='USD':
        return 'foreign_receipt_or_krw_acquisition_required'
    return 'no_exact_payment_evidence'


def portal_diagnoses(report, transactions, analysis=None):
    """연결되지 않은 거래마다 구체 원인을 남긴다. 근거가 없으면 '자료 없음'이 아니다.

    같은 거래는 한 번만 적는다. 원인은 포털 사실의 카드·통화·금액·기간·
    상태·근거 역할 관계에서 정하며, 사실이 없으면 카드 원행 자체의
    부족을 그대로 보고한다.
    """
    exact={fact['source_hash'] for fact in report.get('matches',[])}
    kind_only={fact['source_hash'] for fact in report.get('type_only_candidates',[])}
    conflicted={fact['source_hash'] for fact in report.get('matches',[])
                if fact.get('booking_link_conflict') or fact.get('period_conflict')}
    unmatched={fact['source_hash']:fact for fact in report.get('unmatched_transactions',[])}
    analysis=collect_portal_facts(analysis or []) if not isinstance(analysis,dict) else analysis
    unique_rows=unique_transactions(transactions)
    rows={row['source_hash']:row for row in unique_rows}
    agoda_rows=[row for row in unique_rows if is_agoda_purchase(row)]
    booking_rows=defaultdict(set)
    booking_sources=defaultdict(set)
    for fact in analysis['facts'].values():
        for version in fact.values():
            for row in agoda_rows:
                if (row.get('card_tail')==version['card_last4']
                        and (version['currency'],version['amount']) in transaction_amounts(row)):
                    booking_rows[version['booking_ref']].add(row['transaction_id'])
                    booking_sources[version['booking_ref']].add(row['source_hash'])
    seen=defaultdict(set)
    for source_hash,row in rows.items():
        if (source_hash in exact|kind_only or row.get('transaction_direction')!='purchase'
                or not any(marker in str(row.get('merchant') or '').upper() for marker in
                           ('TRIP.COM','트립닷컴','KLOOK','클룩','AGODA','아고다','BOOKING','부킹닷컴'))):
            continue
        reason=(_reason_for(row,analysis,source_hash in conflicted)
                if is_agoda_purchase(row) else 'no_exact_payment_evidence')
        if reason=='no_exact_payment_evidence' and unmatched.get(source_hash):
            reason=unmatched[source_hash].get('reason') or reason
        seen[source_hash]={'source_hash':source_hash,'reason':reason,
                           'booking_ref_count':sum(
                               1 for booking,hashes in booking_rows.items()
                               if source_hash in booking_sources[booking] and len(hashes)>1)}
        if seen[source_hash]['booking_ref_count']:
            seen[source_hash]['reason']='ambiguous_transaction'
    return [seen[key] for key in sorted(seen)]


def unique_transactions(transactions):
    return list({(row['transaction_id'],row['source_hash']):row for row in transactions}.values())
