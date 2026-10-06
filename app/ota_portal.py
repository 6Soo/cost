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


def evidence_path(data_directory):
    configured=os.environ.get('WEBLEDGER_AGODA_PORTAL_DB')
    if configured:
        return Path(configured)
    current=Path(data_directory)/'agoda-portal.sqlite'
    if current.is_file():
        return current
    # 경량화 전에 사용자가 전수조사한 원본을 삭제하거나 새로 수집하지 않는다.
    return Path(__file__).resolve().parents[1]/'outputs/agoda-paseo-staging-20260822.sqlite'


def portal_matches(database, transactions):
    path=Path(database).resolve()
    if not path.is_file():
        return []
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        records=conn.execute(
            "SELECT b.booking_number,b.service_start_on,b.service_end_on,b.status,"
            "d.id,d.payload_json,d.source_sha256,e.evidence_role,e.evidence_status,e.conflict_count "
            "FROM bookings b JOIN booking_source_evidence e ON e.booking_id=b.id "
            "JOIN direct_source_records d ON d.id=e.direct_source_record_id "
            "WHERE b.provider='agoda' AND d.source_kind='agoda_portal_detail'").fetchall()
    finally:
        conn.close()
    grouped=defaultdict(list)
    blocked=set()
    for row in records:
        grouped[(row['booking_number'],row['id'])].append(row)
        if row['conflict_count'] or row['evidence_status'] != 'observed':
            blocked.add(row['booking_number'])
    required={'identity','service_period','portal_payment_claim','portal_card_observation','lifecycle'}
    facts=defaultdict(dict)
    for (booking,source_id),evidence in grouped.items():
        first=evidence[0]
        if booking in blocked or not required <= {r['evidence_role'] for r in evidence}:
            continue
        raw=first['payload_json']
        if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=first['source_sha256']:
            raise ValueError('OTA_PORTAL_PAYLOAD_HASH_MISMATCH')
        fact=json.loads(raw)
        if (fact.get('reservation_status') in ('cancelled','refunded')
                or fact.get('refund_status') not in (None,'none_displayed')):
            blocked.add(booking)
        if (fact.get('provider')!='agoda' or fact.get('booking_number')!=booking
                or fact.get('reservation_status')!='completed' or first['status']!='completed'
                or fact.get('payment_status')!='paid' or fact.get('collection_model')!='agoda_collect'
                or fact.get('refund_status')!='none_displayed'
                or not re.fullmatch(r'\d{4}',str(fact.get('card_last4') or ''))):
            continue
        start=fact.get('service_start_on');end=fact.get('service_end_on')
        if start!=first['service_start_on'] or end!=first['service_end_on']:
            blocked.add(booking)
            continue
        try:
            if datetime.date.fromisoformat(start)>datetime.date.fromisoformat(end):
                continue
            amounts=set()
            for component in fact.get('price_components',[]):
                if component.get('kind')!='paid_today':
                    continue
                amount=Decimal(str(component['decimal_text']).replace(',',''))
                if (not amount.is_finite() or amount<=0
                        or amount*(Decimal(10)**component['scale'])!=component['minor_units']):
                    raise ValueError('OTA_PORTAL_AMOUNT_CONFLICT')
                amounts.add((component['currency'],amount))
        except (InvalidOperation,KeyError,TypeError,ValueError):
            continue
        if len(amounts)!=1:
            continue
        currency,amount=next(iter(amounts))
        signature=(fact['card_last4'],currency,amount,start,end)
        facts[booking][signature]=dict(booking_ref=booking,card_last4=fact['card_last4'],
            currency=currency,amount=amount,period={'starts_on':start,'ends_on':end},
            source_sha256=first['source_sha256'])
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
    for options in candidates.values():
        if len(options)!=1:
            continue
        row,fact=options[0]
        if len(rows_by_booking[fact['booking_ref']])!=1:
            continue
        matches.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
            merchant=row['merchant_normalized'],card_kind=row['card_kind'],direction='purchase',
            provider='agoda',booking_ref=fact['booking_ref'],item='숙박비',period=fact['period'],
            source_sha256=fact['source_sha256'],evidence_kind='portal_payment_claim',
            reservation_status='observed',strict_service_period=True,
            basis='아고다 전수조사 페이지의 완료 예약·실제 결제액·통화·카드 끝자리와 카드 원행이 일대일로 일치'))
    return matches


def extend_report(report, database, transactions):
    """메일과 페이지를 함께 쓰되 서로 다른 예약을 제안하면 여행 연결을 보류한다."""
    matches=portal_matches(database,transactions)
    if not matches:
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
            optional={'source_hash':source},effects={'item':'숙박비','description':'예약 '+fact['booking_ref']},
            origin='ota-portal-live',note=fact['basis']))
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
    return report


def unique_transactions(transactions):
    return list({(row['transaction_id'],row['source_hash']):row for row in transactions}.values())
