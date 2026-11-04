"""Additional authenticated itinerary facts for search only, never payment matching."""
from __future__ import annotations

import copy
from datetime import date
import hashlib
import re

from app import flight_evidence as flights, ota_mail

SEARCH_SCHEMA = 'flight-search-v3-provider-itineraries'
_STAMP = re.compile(r'^(20\d{2})\.(\d{2})\.(\d{2})\s*\([^)]{1,4}\)\s+(\d{2}:\d{2})$')
_CITY = re.compile(r"[A-Za-z가-힣一-龥][A-Za-z가-힣一-龥 .()'\-]{0,39}")


def _notice_legs(tokens):
    """A bounded city pair followed immediately by a labelled calendar date."""
    result=[]
    for i,token in enumerate(tokens):
        match=re.fullmatch(r'(.{1,40}?)\s+-\s+(.{1,40})',token)
        if not match or not all(_CITY.fullmatch(value) for value in match.groups()):
            continue
        following=[t for t in tokens[i+1:i+4] if t!='|']
        if not following:
            continue
        day=flights._date_on(following[0])
        if not day:
            continue
        if any((leg['origin_city'],leg['destination_city'],leg['departure_on'])==(*match.groups(),day) for leg in result):
            continue
        leg=dict(label='여정 '+str(len(result)+1),origin_city=match[1],destination_city=match[2],
                 departure_on=day,segments=[])
        if leg not in result:
            result.append(leg)
    return result


def _inline_notice_tokens(text):
    """Provider route/date cells can arrive flattened into one text line."""
    result=[]
    for match in re.finditer(
            r'([A-Za-z가-힣一-龥]+(?:\s+(?:현|도))?)\s+-\s+'
            r'([A-Za-z가-힣一-龥]+(?:\s+(?:현|도))?)\s*\|\s*'
            r'(20\d{2}년\s*\d{1,2}월\s*\d{1,2}일)',text):
        result.extend([match[1]+' - '+match[2],match[3]])
    return result


def _jeju_itinerary(text):
    tokens=[line.strip() for line in text.splitlines() if line.strip()]
    refs=set(re.findall(r'예약번호\s*[:：]?\s*([A-Z0-9]{6})\b',text))
    if len(refs)!=1:
        return None
    people=[]
    for i,token in enumerate(tokens[:-1]):
        if re.fullmatch(r'(?:성인|소아|유아)\s+\d+',token):
            name=tokens[i+1]
            if re.fullmatch(r"[A-Z][A-Z '\-]*\s+[A-Z][A-Z '\-]*",name):
                # The passenger row identifies a literal name, not which word
                # is a surname. Keep the recorded order without inventing it.
                person=dict(surname='',given_name=name)
                if person not in people:
                    people.append(person)
    legs=[]
    for i,label in enumerate(tokens):
        if label not in ('가는편','오는편'):
            continue
        end=next((k for k in range(i+1,len(tokens)) if tokens[k] in ('가는편','오는편')),len(tokens))
        block=tokens[i+1:min(end,i+16)]
        airports=[(k,re.fullmatch(r'\(([A-Z]{3})\)',t)) for k,t in enumerate(block)]
        airports=[(k,m[1]) for k,m in airports if m]
        stamps=[_STAMP.fullmatch(t) for t in block]
        stamps=[m for m in stamps if m]
        numbers=re.findall(r'편명\s*([A-Z0-9]{2}\s?\d{1,4})',' '.join(block))
        if len(airports)!=2 or len(stamps)!=2 or len(numbers)!=1:
            continue
        try:
            start,finish=[date(*map(int,m.group(1,2,3))).isoformat() for m in stamps]
        except ValueError:
            continue
        if finish<start or any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',m[4]) for m in stamps):
            continue
        cities=[block[k-1] if k and _CITY.fullmatch(block[k-1]) else '' for k,_ in airports]
        legs.append(dict(label=label,origin_city=cities[0],destination_city=cities[1],departure_on=start,
            segments=[dict(flight_number=numbers[0].replace(' ',''),departure_airport=airports[0][1],
                           arrival_airport=airports[1][1],departure_time=stamps[0][4],arrival_time=stamps[1][4])]))
    return dict(booking_ref=next(iter(refs)),passengers=people,legs=legs,
                cancellation_status='NONE',booking_date_status='UNKNOWN') if legs else None


def build_search_index(directories, trip_index):
    """Keep Trip financial evidence intact; augment a separate display index."""
    index=copy.deepcopy(trip_index)
    messages,_=ota_mail.load_messages_from(directories)
    grouped={}
    receipts={}
    airline_metadata=None
    for mid,message in messages.items():
        authenticated=ota_mail.authenticated_headers(message,('trip.com','trip.co.kr','jejuair.net'))
        if not authenticated:
            continue
        headers,domain=authenticated
        subject=headers.get('subject','')
        body=ota_mail.message_text(message)
        digest=hashlib.sha256(str(mid).encode()).hexdigest()
        if domain=='jejuair.net':
            if not re.search(r'여정확인서\s*\(e-ticket\)',subject,re.I):
                continue
            parsed=_jeju_itinerary(body)
            if not parsed:
                continue
            key='jeju:'+parsed['booking_ref']
            fact=flights._received_fact(message,digest)
            if fact:
                receipts.setdefault(key,[]).append(fact)
            grouped.setdefault(key,[]).append(dict(parsed,source_digest=digest))
        elif re.search(r'항공|flight|전자항공권',subject,re.I):
            # A notice can mention several reservations without identifying
            # which passengers and routes belong to each one.
            if len(flights._booking_refs(flights._flight_tokens(body))) != 1:
                continue
            parsed=flights.parse_flight_text('Subject: '+subject+'\n'+body)
            if not parsed or not parsed.get('booking_ref') or not parsed.get('passengers'):
                continue
            key=parsed['booking_ref']
            old=index.get(key)
            # Full itinerary evidence stays authoritative for this display.
            if old and any(leg.get('segments') for leg in old.get('legs') or []):
                continue
            legs=_notice_legs(flights._flight_tokens(body)+_inline_notice_tokens(body))
            if not legs:
                continue
            grouped.setdefault(key,[]).append(dict(parsed,legs=legs,source_digest=digest))
    for key,parts in grouped.items():
        if key in index:
            old=index[key]
            parts=[dict(old,source_digest=d) for d in old.get('source_digests') or []]+parts
        merged=flights.merge_booking_evidence(parts)
        if key in index:
            merged['conflict']=bool(merged.get('conflict') or index[key].get('conflict'))
        if key.startswith('jeju:'):
            if airline_metadata is None:
                airline_metadata=flights.collect_flight_evidence(directories)
            metadata=airline_metadata.get(('jeju',merged['booking_ref'])) or {}
            merged['conflict']=bool(merged.get('conflict') or metadata.get('conflict'))
            if metadata.get('cancellation_status') not in (None,'NONE'):
                merged['cancellation_status']=metadata['cancellation_status']
            if metadata.get('booking_date_status') in ('EXPLICIT_LABEL','CONFLICT'):
                for field in ('reserved_on','booking_card_day','booking_date_status','booking_date_evidence'):
                    merged[field]=metadata.get(field)
            merged=flights._with_first_received_day(merged,receipts.get(key,[]))
            merged['provider']='jeju'
        merged['digest']=hashlib.sha256(flights._canonical({k:v for k,v in merged.items() if k!='digest'}).encode()).hexdigest()
        old=index.get(key) or {}
        # Search-only route projection must not invalidate a payment binding
        # when every source digest already belongs to the unchanged Trip evidence.
        if (not key.startswith('jeju:') and old.get('digest')
                and set(merged.get('source_digests') or []) <= set(old.get('source_digests') or [])):
            merged['search_digest']=merged['digest']
            merged['digest']=old['digest']
            merged['source_digests']=copy.deepcopy(old['source_digests'])
        index[key]=merged
    return index
