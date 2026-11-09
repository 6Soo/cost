"""Rakuten booking evidence supplies dates, never a claim that a payment completed."""
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from app import ota_mail


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def collect(messages, inventory):
    events=[]
    for mid,message in sorted(messages.items()):
        authenticated=ota_mail.authenticated_headers(message,('travel.rakuten.com',))
        if not authenticated:
            continue
        headers,_=authenticated
        subject=headers.get('subject','')
        if (not re.search(r'라쿠텐\s*트래블',subject)
                or not (re.search(r'예약\s*확정\s*(?=[:：(]|$)',subject)
                        or re.search(r'예약\s*취소',subject))):
            continue
        text=ota_mail.message_text(message).translate(ota_mail._format_char_table())
        refs=set(re.findall(r'예약\s*ID\s*[:：]?\s*([A-Z0-9]{6,32})',subject+'\n'+text,re.I))
        if len(refs)!=1:
            continue
        reserved=set(re.findall(r'예약일\s*[:：]?\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',text))
        try:
            reserved_on=date(*map(int,next(iter(reserved)))).isoformat() if len(reserved)==1 else None
        except ValueError:
            reserved_on=None
        quotes=set(re.findall(r'금액\s*합계\s*[:：]?\s*(KRW|JPY|₩|¥|￥)\s*'
                              r'((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)(?![0-9.,])',text,re.I))
        quoted=None
        if len(quotes)==1:
            currency,amount=next(iter(quotes))
            value=Decimal(amount.replace(',',''))
            if value>0:
                quoted={'currency':{'₩':'KRW','¥':'JPY','￥':'JPY'}.get(currency.upper(),currency.upper()),'amount':str(value)}
        tails=set(re.findall(r'(?:\*{4}\s*){3}(\d{4})\b',text))
        source='mail:'+mid;digest=_digest(message)
        cancelled=(ota_mail.reservation_cancelled(subject)
                   or bool(re.search(r'예약\s*취소\s*(?=[:：(]|$)',subject)))
        cancellation_pending=not cancelled and bool(re.search(r'예약\s*취소',subject))
        events.append({'provider':'rakuten','booking_ref':next(iter(refs)),
            'supplier_booking_refs':sorted(set(re.findall(r'예약\s*번호\s*[:：]?\s*([A-Z0-9]{6,32})',text,re.I))),
            'ota_event_id':'ota_'+_digest([source]),'event_type':'reservation','item':'숙박비',
            'paid_on':None,'paid_on_semantics':'missing','payment_status':'unknown',
            'payment_id':None,'payment_event_id':None,'amount':None,'amount_krw':None,'currency':'',
            'reservation_on':reserved_on,'reservation_amount':quoted,
            'card_last4':next(iter(tails)) if len(tails)==1 else None,
            'service_period':ota_mail.service_period(text),
            'reservation_status':'cancelled' if cancelled else 'evidence_pending' if cancellation_pending else 'confirmed',
            'refund_status':'none_displayed','evidence_status':'reservation_only',
            'source_trust':'authenticated_mail','source_digest':digest,'source_digests':[digest],
            'source_ids':[source],'identity_source_ids':[source],
            'evidence_kind':'authenticated_reservation_mail','source_inventory':inventory})
    groups=defaultdict(list)
    for event in events:
        groups[event['booking_ref']].append(event)
    for group in groups.values():
        cancelled=any(e['reservation_status']=='cancelled' for e in group)
        pending=any(e['reservation_status']=='evidence_pending' for e in group)
        periods={json.dumps(e['service_period'],sort_keys=True) for e in group if e['service_period']}
        amounts={json.dumps(e['reservation_amount'],sort_keys=True) for e in group if e['reservation_amount']}
        for event in group:
            if cancelled:event['reservation_status']='cancelled'
            elif pending:event['reservation_status']='evidence_pending'
            if len(periods)>1:event.update(service_period=None,service_period_conflict=True)
            if len(amounts)>1:event['reservation_amount_conflict']=True
    return events


def search_candidates(event, transactions, *, max_comparisons=250000):
    from app.ota_payments import _foreign_decimal
    empty={'status':'NO_CANDIDATE','candidates':[],'rejected':[],'comparisons':0,'reservation_only':True}
    if (event.get('reservation_status') not in ('confirmed','observed','completed')
            or event.get('evidence_status')!='reservation_only' or not event.get('source_digest')
            or event.get('source_trust')!='authenticated_mail'
            or event.get('refund_status') not in (None,'','none_displayed','no_refund')
            or any(event.get(k) for k in ('evidence_missing','evidence_changed','period_conflict',
                   'service_period_conflict','reservation_amount_conflict'))
            or not event.get('service_period') or not event.get('reservation_on')
            or not re.fullmatch(r'\d{4}',str(event.get('card_last4') or ''))):
        return empty
    quote=event.get('reservation_amount') or {}
    try:
        target=Decimal(quote['amount'])
        if not target.is_finite() or target<=0:return empty
    except (KeyError,InvalidOperation,TypeError):
        return empty
    candidates=[];comparisons=0
    for row in transactions:
        if not re.search(r'^rakuten\s+travel(?:\s|$)',str(row.get('merchant') or '').strip(),re.I):
            continue
        comparisons+=1
        if comparisons>max_comparisons:
            return dict(empty,status='SEARCH_LIMIT_EXCEEDED',comparisons=comparisons)
        if (row.get('transaction_direction')!='purchase' or not row.get('source_hash')
                or any(row.get(k) for k in ('duplicate_of','parse_error','conflict_reason',
                                           'ota_review_held','reservation_refund_blocked'))
                or row.get('refund_status') in ('refund_pending','refund_requested','refunded','refund_completed')
                or str(row.get('card_tail') or '')!=event['card_last4']
                or row.get('approval_date')!=event['reservation_on']):
            continue
        native=str(row.get('foreign_currency') or '').upper()
        if native:
            if native!=quote.get('currency'):continue
            raw=row.get('foreign_amount')
        elif quote.get('currency')=='KRW' and row.get('foreign_amount') in (None,''):
            raw=row.get('amount_krw')
        else:
            continue
        try:
            amount=_foreign_decimal(raw)
            if not amount.is_finite() or amount<=0 or amount!=target:continue
        except (InvalidOperation,ValueError,TypeError):
            continue
        candidates.append({'transaction_id':row['transaction_id'],'provider_status':'MATCH',
            'reservation_date_status':'MATCH','card_tail_status':'MATCH','amount_status':'MATCH',
            'date_status':'UNKNOWN','resolution_allowed':False,'payment_verified':False,
            'confidence':'HIGH','basis':'RESERVATION_DATE_NATIVE_AMOUNT_AND_CARD_TAIL'})
    return dict(empty,status='CANDIDATES_FOUND' if candidates else 'NO_CANDIDATE',
                candidates=candidates,comparisons=comparisons)
