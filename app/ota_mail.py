"""보존한 예약 메일과 카드 원행을 엄격하게 대조한다. 메일을 보내지 않는다."""
import base64
import collections
import datetime
import hashlib
import html
import json
import re
import unicodedata
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
import threading


def as_directories(directory):
    """단일 디렉터리와 목록을 같은 형태로 읽는다. 한 곳만 주면 한 목록이 된다."""
    if directory is None:
        return []
    if isinstance(directory,(str,Path)):
        return [Path(directory)]
    return [Path(item) for item in directory]


def collection_of(directory):
    """한 수집 범위의 진행 상태. 여러 범위일 때 각각 남는다."""
    path=Path(directory)/'collection.json'
    if not path.is_file():
        return {}
    collection=json.loads(path.read_text(encoding='utf-8'))
    return {key:collection[key] for key in ('after','before','query_exhausted','fetched')
            if key in collection}


_MESSAGES_MEMO = {}
_MESSAGES_LOCK = threading.RLock()
# id(message) -> (message, body text computed while loading it); the stored message keeps the id valid.
_BODY_TEXT = {}


def message_text(message):
    """The body text of a loaded message, from the load that produced it, else computed now."""
    entry = _BODY_TEXT.get(id(message))
    if entry is not None and entry[0] is message:
        return entry[1]
    return body_text(message.get('payload', {}))


def load_messages_from(directories):
    """The mail files read once per content state; callers only read the result.

    Keyed by the content stamps of the files, so a changed or added mail is read
    again and an unchanged set is never parsed twice in one process.
    """
    from app import ota_sources
    listed = as_directories(directories)
    with _MESSAGES_LOCK:
        key = (tuple(str(Path(d)) for d in listed),
               json.dumps(ota_sources.mail_stamps(listed), sort_keys=True))
        if key not in _MESSAGES_MEMO:
            _MESSAGES_MEMO.clear()
            _BODY_TEXT.clear()
            _MESSAGES_MEMO[key] = _load_messages_uncached(directories)
        return _MESSAGES_MEMO[key]


def _core_digest(core):
    return hashlib.sha256(json.dumps(core,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


_ADDRESS_HEADERS = ('from', 'to', 'cc', 'bcc', 'reply-to', 'sender', 'delivered-to', 'return-path')


def same_original_core(first, second):
    """The same message rendered by two extractors: header folding, quoting and the date spelling differ only."""
    from email.utils import getaddresses

    def normalized(core, message):
        headers = {}
        for name, value in core['headers'].items():
            value = ' '.join(str(value).split())
            if name in _ADDRESS_HEADERS:
                value = sorted((label.strip(), address.lower()) for label, address in getaddresses([value]))
            headers[name] = value
        return core['id'], headers, core['text'], receipt_times(message)

    (core_a, message_a), (core_b, message_b) = first, second
    left, right = normalized(core_a, message_a), normalized(core_b, message_b)
    # One copy may lack a spelling; any time both copies state must agree, and a copy
    # that contradicts itself only matches an identical contradiction.
    times_match = not left[3] or not right[3] or left[3] == right[3]
    return left[:3] == right[:3] and times_match


def receipt_times(message):
    """Every receipt time the message states, under either field spelling."""
    return frozenset(str(value) for value in (message.get('internal_date'), message.get('internalDate'))
                     if value not in (None, ''))


def needs_original_comparison(core, message):
    """The stored digest carries only internal_date; a missing or self-contradicting time needs the kept copy."""
    return core['internal_date'] in (None, '') or len(receipt_times(message)) > 1


def _load_messages_uncached(directories):
    """여러 디렉터리를 함께 읽는다.

    같은 ID와 같은 본문·서명 헤더는 한 메일로 합친다. 같은 ID인데 본문이
    다르면 기존과 같이 충돌로 중단한다. 한 디렉터리만 읽었다고 조기 종료하지
    않고 등록된 모든 범위를 읽은 뒤에 대조를 시작한다.
    """
    messages = {}
    fingerprints = {}
    inventory = []
    body_cache = {}
    def bundles():
        from app.ota_store import is_store, iter_mail_bundles
        for directory in as_directories(directories):
            path = Path(directory)
            if path.is_file() and is_store(path):
                yield from iter_mail_bundles(path)
            elif not path.is_dir():
                yield str(path), None, []
            else:
                loaded = (message for file_path in sorted(path.glob('gmail*.json'))
                          for message in json.loads(file_path.read_text(encoding='utf-8'))['responses'])
                yield str(path), collection_of(path), loaded
    for directory, collection, loaded in bundles():
        path=Path(directory)
        entry={'kind':'mail_directory','path':str(path),'messages':0,
               'collection':collection or {}}
        if collection is None:
            entry['error']='directory_not_found'
            inventory.append(entry)
            continue
        for message in loaded:
            identity = message['id']
            payload=message['payload']
            # 재수집 때 첨부 메타 정보가 추가되어도 같은 본문과 인증 헤더면 같은 메일이다.
            core = dict(id=identity,internal_date=message.get('internal_date'),
                        headers={h['name'].lower():h['value'] for h in payload.get('headers',[])},
                        text=body_text(payload))
            digest = _core_digest(core)
            if identity in fingerprints:
                kept_digest, kept_core, kept = fingerprints[identity]
                if ((kept_digest != digest or needs_original_comparison(core, message)
                     or needs_original_comparison(kept_core, kept))
                        and not same_original_core((kept_core, kept), (core, message))):
                    raise ValueError('OTA_MESSAGE_CONTENT_CONFLICT')
            fingerprints[identity] = (digest, core, message)
            previous = messages.get(identity)
            if previous is not None:
                body_cache.pop(id(previous), None)
            body_cache[id(message)] = (message, core['text'])
            messages[identity] = message
            entry['messages']+=1
        inventory.append(entry)
    # Failed/conflicting loads never publish partial bodies. Only the same
    # canonical message objects returned above remain strongly referenced.
    _BODY_TEXT.update(body_cache)
    return messages, inventory


def load_messages(directory):
    """중복 메일은 한 번 읽고 같은 ID의 다른 원문은 충돌로 중단한다."""
    return load_messages_from(directory)[0]


def authenticated_headers(message, domains):
    headers = {h['name'].lower():h['value'] for h in message['payload'].get('headers', [])}
    domain = parseaddr(headers.get('from',''))[1].split('@')[-1].lower()
    # domain 뒤 경계를 정확히 확인해 trip.com.example 같은 이름을 허용하지 않는다.
    canonical = next((base for base in domains if domain == base or domain.endswith('.'+base)), None)
    if canonical is None:
        return None
    # 소유자가 직접 수집한 메일은 발신 인증 헤더가 없어도 같은 발신 도메인이면 사용한다(소유자 지시 2026-10-15).
    if message.get('owner_collected') is True:
        return headers, canonical
    signatures = re.findall(r'dkim=pass\s+([^;]+)', headers.get('authentication-results',''), re.I)
    aligned = any(any(signed == canonical or signed.endswith('.'+canonical)
                      for signed in re.findall(r'header\.(?:i=@|d=)([a-z0-9.-]+)(?=\s|$)', part, re.I))
                  for part in signatures)
    if not aligned:
        return None
    return headers, canonical


def flight_period(text):
    """Outbound and return dates of a flight confirmation: 가는편 and 오는편 lines carry 'YYYY년 M월 D일'."""
    dates = {}
    for key, label in (('starts_on', '가는편'), ('ends_on', '오는편')):
        match = re.search(label + r':[^|]*\|\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', text)
        if not match:
            return None
        try:
            dates[key] = datetime.date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            return None
    return dates if dates['ends_on'] >= dates['starts_on'] else None


def rental_period(text):
    """Only the labeled pickup/return days; deposit and cancellation dates are unrelated."""
    days = []
    for label in (r'인수(?:\s*(?:시간|일시))?', r'반납(?:\s*(?:시간|일시))?'):
        values = set(re.findall(label + r'\s*[:：]\s*(\d{4}-\d{2}-\d{2})', text))
        if len(values) != 1:
            return None
        try:
            days.append(datetime.date.fromisoformat(next(iter(values))))
        except ValueError:
            return None
    if not 0 <= (days[1] - days[0]).days <= 366:
        return None
    return {'starts_on': days[0].isoformat(), 'ends_on': days[1].isoformat()}


def klook_rental_period(text):
    """A Klook rental's labelled pickup and return days; other dates in the notice are unrelated."""
    days = []
    for label in ('픽업', '반납'):
        values = set(re.findall(label + r'\s*날짜\s*및\s*시간\s*[:：]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', text))
        if len(values) != 1:
            return None
        try:
            days.append(datetime.date(*map(int, next(iter(values)))))
        except ValueError:
            return None
    if not 0 <= (days[1] - days[0]).days <= 366:
        return None
    return {'starts_on': days[0].isoformat(), 'ends_on': days[1].isoformat()}


def trip_rental_confirmation(subject):
    return bool(re.search(r'렌터카\s*예약(?:이|가)?\s*확정'
                          r'(?:되었습니다|됐습니다|[ \t]*(?:안내[ \t]*)?(?=[(:：\n]|$))', subject))


def payment_failed(text):
    """Uncompleted transaction statements; a conditional help instruction is not a status."""
    pattern = re.compile(
        r'결제(?:가|는|이|에)?\s*(?:실패|미완료|취소(?:되었습니다|됐습니다|완료)|'
        r'(?:완료\s*)?되지\s*않|이루어지지\s*않|(?:처리|진행)\s*중|'
        r'(?:(?:완료|처리|진행)(?:가|는|이)?\s*)?(?:될\s*)?(?:예정|대기))|'
        r'payment\s*(?:(?:was\s+|is\s+)?(?:failed|cancelled|declined|unsuccessful|pending)|'
        r'(?:was\s+|is\s+)?not\s+(?:completed|successful|received))|'
        r'will\s+be\s+charged|scheduled\s+payment', re.I)
    for match in pattern.finditer(text):
        if re.match(r'\s*(?:시(?:에는|에)?\b|할\s*경우|하면|할\s*때)', text[match.end():]):
            continue
        if re.search(r'\bif\s+(?:(?:your|the)\s+)?$', text[max(0, match.start()-24):match.start()], re.I):
            continue
        return True
    return False


def service_period(text):
    # Without any check-in or check-out wording no date can be read; the scan below would find nothing.
    if not re.search(r'check|체크', text, re.I):
        return None
    dates = {}
    for key,label in (('starts_on','체크인'),('ends_on','체크아웃')):
        values = set()
        marker = '(?:'+label+'|'+('check[ -]*in' if key=='starts_on' else 'check[ -]*out')+')'
        prefix=marker+r'(?:\s*(?:날짜|date))?\s*(?:[:：]\s*)?'
        for year,month,day in re.findall(prefix+r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',text,re.I):
            try: values.add(datetime.date(int(year),int(month),int(day)).isoformat())
            except ValueError: return None
        for value in re.findall(prefix+r'(\d{4}-\d{2}-\d{2})',text,re.I):
            try: values.add(datetime.date.fromisoformat(value).isoformat())
            except ValueError: return None
        weekday=r'(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?'
        for value in re.findall(prefix+weekday+r'([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})',text,re.I):
            parsed=None
            for format in ('%B %d, %Y','%b %d, %Y','%B %d %Y','%b %d %Y','%d %B %Y','%d %b %Y'):
                try:parsed=datetime.datetime.strptime(value,format).date().isoformat();break
                except ValueError:pass
            if parsed is None:return None
            values.add(parsed)
        if len(values)!=1: return None
        dates[key]=next(iter(values))
    return dates if dates['starts_on']<=dates['ends_on'] else None


def reservation_cancelled(subject):
    """취소 조건이나 위약금 안내를 실제 취소 완료로 처리하지 않는다."""
    return bool(re.search(r'취소(?:가|이)?\s*(?:완료|되었|됐|됨)|취소.*완료|cancelled|canceled|cancellation\s+confirmed',subject,re.I))


def scheduled_charge_day(text):
    """예약 메일에 명시된 자동 결제일만 읽는다. 예약일이나 체크인일은 쓰지 않는다."""
    values=set()
    prefix=r'(?:요금\s*자동\s*결제일은|자동\s*결제일|your\s+card\s+will\s+be\s+charged\s+on)\s*[:：\[]?\s*'
    for value in re.findall(prefix+r'(\d{4}-\d{2}-\d{2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})',text,re.I):
        parsed=None
        compact=re.sub(r'\s+',' ',value).strip()
        for format in ('%Y-%m-%d','%Y년 %m월 %d일','%Y년%m월%d일','%B %d, %Y','%B %d %Y','%b %d, %Y','%b %d %Y','%d %B %Y','%d %b %Y'):
            try:parsed=datetime.datetime.strptime(compact,format).date();break
            except ValueError:pass
        if parsed is None:return None
        values.add(parsed)
    return next(iter(values)) if len(values)==1 else None


def mail_categories(messages):
    """본문을 보고서에 복제하지 않고 메일 역할과 지원 범위를 집계한다."""
    counts=collections.Counter()
    domains=('trip.com','trip.co.kr','klook.com','agoda.com','booking.com','agoda-messaging.com')
    for message in messages.values():
        authenticated=authenticated_headers(message,domains)
        if not authenticated:
            counts['unsupported_or_unverified_sender']+=1
            continue
        subject=authenticated[0].get('subject','')
        if re.search(r'환불|refund',subject,re.I):kind='refund_notice'
        elif re.search(r'취소|cancel',subject,re.I):kind='cancellation_notice'
        elif re.search(r'결제.*완료|결제가 완료|payment.*(?:confirm|received|successful)',subject,re.I):kind='payment_receipt'
        elif re.search(r'체크인.*얼마|reminder',subject,re.I):kind='service_reminder'
        elif re.search(r'예약.*확정|예약내역|booking.*confirm',subject,re.I):kind='reservation_confirmation'
        else:kind='other_verified_mail'
        counts[kind]+=1
    return dict(counts)


def decimal_amount(value):
    """통화 기호 뒤 금액의 천 단위 구분과 소수점을 구분한다."""
    from decimal import Decimal, InvalidOperation
    value=value.strip()
    if ',' in value:
        if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?',value):
            value=value.replace(',','')
        elif re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+),\d{1,2}',value):
            value=value.replace('.','').replace(',','.')
        else:
            raise InvalidOperation('AMBIGUOUS_OTA_AMOUNT')
    amount=Decimal(value)
    if not amount.is_finite() or amount<0:raise InvalidOperation('INVALID_OTA_AMOUNT')
    return amount


def body_text(part):
    body = part.get('body') or {}
    value = body.get('content') or ''
    if not value and (body.get('base64_url_content') or body.get('data')):
        encoded = body.get('base64_url_content') or body['data']
        value = base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)).decode('utf-8','replace')
    # HTML과 plain text가 함께 있더라도 금액은 아래에서 집합으로 비교한다.
    value = re.sub(r'<!--.*?-->', '', value, flags=re.S)
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', value, flags=re.I|re.S)
    value = html.unescape(re.sub('<[^>]*>', '\n', value))
    return value+'\n'+'\n'.join(body_text(p) for p in (part.get('parts') or []))


def mail_internal_date(message):
    """Read Gmail REST and archived field spellings without changing originals."""
    snake = message.get('internal_date')
    camel = message.get('internalDate')
    if snake not in (None, '') and camel not in (None, '') and str(snake) != str(camel):
        return None
    return snake if snake not in (None, '') else camel


def sent_day(message, headers):
    """수신 지연과 결제일을 구분하고 서명된 발송 날짜를 보존한다."""
    try:
        sent = parsedate_to_datetime(headers['date'])
        if sent.tzinfo is None:
            return None
        zone = datetime.timezone(datetime.timedelta(hours=9))
        received = datetime.datetime.fromtimestamp(int(mail_internal_date(message))/1000, zone)
        sent = sent.astimezone(zone)
        # 수신 지연은 허용하되 미래 발송일은 근거로 쓰지 않는다.
        if sent > received + datetime.timedelta(days=1):
            return None
        return sent.date()
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


_FORMAT_CHARS = None


def _format_char_table():
    """Unicode format characters (category Cf) as a translate table, built once."""
    global _FORMAT_CHARS
    if _FORMAT_CHARS is None:
        _FORMAT_CHARS = {code: None for code in range(0x110000) if unicodedata.category(chr(code)) == 'Cf'}
    return _FORMAT_CHARS


def extract_mail(message):
    payload = message['payload']
    authenticated = authenticated_headers(message, ('trip.com','trip.co.kr','klook.com'))
    if not authenticated:
        return None
    headers,domain = authenticated
    provider = 'trip' if domain in ('trip.com','trip.co.kr') else 'klook' if domain=='klook.com' else ''
    text = message_text(message).translate(_format_char_table())
    subject = headers.get('subject','')
    cancelled = reservation_cancelled(subject)
    refs = set(re.findall(r'예약\s*번호\s*[:：]?\s*([A-Z0-9]{8,20})',text,re.I))
    ignored_guides=[]
    if provider=='klook' and '예약내역 안내' in subject and len(refs)>1:
        markers=list(re.finditer(r'예약\s*번호\s*[:：]?\s*([A-Z0-9]{8,20})',text,re.I))
        for index,marker in enumerate(markers):
            section=text[marker.end():markers[index+1].start() if index+1<len(markers) else len(text)]
            section=re.split(r'합계\s*[:：]',section,maxsplit=1)[0]
            amounts={int(n.replace(',','')) for n in re.findall(r'₩\s*([0-9][0-9,]*)',section)}
            if ('이딸로 & 트랜이탈리아 티켓 수령 가이드' in section and
                    re.search(r'총\s*금액\s*₩\s*0\b',section) and amounts=={0}):
                ignored_guides.append(marker.group(1))
        refs-=set(ignored_guides)
    if len(refs)!=1:
        return None
    item = ''
    updated_booking = False
    rental_confirmed = provider == 'trip' and trip_rental_confirmation(subject)
    if rental_confirmed:
        item = '렌터카'
    elif '항공권 예약 확정' in subject:
        item = '항공료'
    elif '예약 확정 안내' in subject and '체크인' in text and '체크아웃' in text:
        item = '숙박비'
    elif (provider == 'trip' and re.search(r'예약이\s*업데이트되었습니다', subject)
          and '체크인' in text and '체크아웃' in text):
        # 변경 안내의 총액은 새 예약 총액이다. 이번에 청구된 금액이 아니므로 아래에서 별도 필드로 옮긴다.
        item = '숙박비'
        updated_booking = True
    elif (provider == 'klook' and '예약내역 안내' in subject and re.search(r'렌터카\s*-', text)
          and klook_rental_period(text)):
        item = '렌터카'
    elif '예약확정' in subject:
        if '렌터카' in subject:
            item = '렌터카'
        elif re.search(r'기차|열차|철도|rail|train|SNCF|EUROSTAR|TGV|RENFE',subject+' '+text[:2500],re.I):
            item = '교통비'
        elif re.search(r'입장권|입장료|미술관|박물관',subject):
            item = '입장료'
    paid_on = sent_day(message, headers)
    if paid_on is None and not cancelled:
        return None
    paid = set()
    preauthorized = set()
    if rental_confirmed:
        if not cancelled and not payment_failed(text) and scheduled_charge_day(text) is None:
            amounts = {decimal_amount(n) for n in re.findall(
                r'온라인\s*선결제\s*[:：]?\s*(?:KRW|₩)\s*'
                r'((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)(?![0-9.,])', text, re.I)}
            paid = {int(n) for n in amounts if n.is_finite() and n > 0 and n == n.to_integral_value()}
            if len(amounts) != 1:
                paid = set()
    elif provider=='trip' and ('결제 완료 안내' in subject or item=='숙박비'):
        if item=='숙박비' and not re.search('온라인 사전 결제',text):
            preauthorized = {int(n.replace(',','')) for n in re.findall(
                r'(?:총\s*금액\s*)?사전\s*승인(?:\s*금액)?\s*[:：]?\s*([0-9][0-9,]*)\s*원',text)}
        else:
            paid = {int(n.replace(',','')) for n in re.findall(
                r'총\s*금액\s*(?:온라인\s*사전\s*결제\s*)?([0-9][0-9,]*)\s*원',text)}
        if '결제 완료 안내' in subject and re.search(r'총\s*금액\s*[0-9,]+\s*원\s*운임',text):
            item = '항공료'
    elif provider=='klook' and '예약내역 안내' in subject:
        # 렌터카는 현장 결제분을 포함한 총액 대신 실제 온라인 결제액을 사용한다.
        paid = {int(n.replace(',','')) for n in re.findall(
            r'온라인\s*결제(?:\s*완료)?(?:\s*금액은)?\s*₩\s*([0-9][0-9,]*)',text)}
        if not paid:
            paid = {int(n.replace(',','')) for n in re.findall(
                r'(?<![가-힣])금액:\s*₩\s*([0-9][0-9,]*)',text)}
        if not paid and re.search(r'전액을\s*결제\s*완료',text) and re.search(r'추가\s*결제\s*금액은\s*없습니다',text):
            # 포인트를 뺀 실제 결제액이 "결제 금액"으로 적힌 전액 결제 양식이다.
            paid = {int(n.replace(',','')) for n in re.findall(r'결제\s*금액\s*₩\s*([0-9][0-9,]*)',text)}
    updated_total = next(iter(paid)) if updated_booking and len(paid) == 1 else None
    if updated_booking:
        paid = set()
        preauthorized = set()
    flight_confirmed = '항공권 예약 확정' in subject
    confirmation = '확정' in subject
    period = (rental_period(text) if rental_confirmed
              else klook_rental_period(text) if provider == 'klook' and item == '렌터카'
              else service_period(text) if item=='숙박비'
              else flight_period(text) if flight_confirmed else None)
    digest=hashlib.sha256(json.dumps(message,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return dict(provider=provider,booking_ref=next(iter(refs)),item=item,
                paid_amount_krw=next(iter(paid)) if len(paid)==1 else None,
                paid_on=paid_on.isoformat() if paid_on else None,period=period,source_sha256=digest,
                preauthorized_amount_krw=next(iter(preauthorized)) if len(preauthorized)==1 else None,
                preauthorized_on=paid_on.isoformat() if paid_on and preauthorized else None,
                reservation_status='cancelled' if cancelled else 'confirmed' if confirmation else 'observed',
                message_id=message['id'],ignored_zero_cost_guides=sorted(set(ignored_guides)),
                updated_total_krw=updated_total)


def shared_lodging_period(facts, *, paid_on, amount_krw):
    """동액 예약들의 공통 이용기간만 반환하고 개별 예약번호는 고르지 않는다."""
    options=[f for f in facts if f['provider']=='trip' and f['paid_on']==paid_on
             and f['paid_amount_krw']==amount_krw]
    if not options or any(f['item']!='숙박비' or not f['period'] for f in options):
        return None
    refs={f['booking_ref'] for f in options}
    if any(f['booking_ref'] in refs and f['reservation_status']=='cancelled' for f in facts):
        return None
    periods={tuple(sorted(f['period'].items())) for f in options}
    if len(periods)!=1:
        return None
    return {'period':dict(next(iter(periods))), 'booking_count':len(refs),
            'source_digests':sorted({f['source_sha256'] for f in options})}


def _lodging_provider(row):
    merchant=str(row.get('merchant') or '').upper()
    return 'agoda' if 'AGODA' in merchant or '아고다' in merchant else 'booking' if 'BOOKING' in merchant or '부킹닷컴' in merchant else ''


def shared_lodging_stay(facts, *, provider, paid_on, amount_krw):
    """같은 결제일·원화 금액으로 실제 결제된 숙박 예약들의 이용기간이 모두 같을 때만 그 기간을 준다.
    예약번호는 고르지 않는다. 같은 제공자·금액의 취소 후보가 하나라도 있으면 배정하지 않는다."""
    from decimal import Decimal
    amount=Decimal(str(amount_krw))
    same=[f for f in facts if f['provider']==provider and ('KRW',amount) in f['amounts']]
    if any(f['cancelled'] for f in same):
        return None
    options=[f for f in same if f['paid'] and f['paid_on']==paid_on]
    if not options or any(not f['period'] for f in options):
        return None
    periods={tuple(sorted(f['period'].items())) for f in options}
    if len(periods)!=1:
        return None
    return {'period':dict(next(iter(periods))),'booking_count':len({f['booking_ref'] for f in options}),
            'source_digests':sorted({f['source_sha256'] for f in options})}


def reference_records(document, *, raw=None):
    """과거 정규화 인덱스·예약 후보 문서의 예약 번호와 상충 여부만 읽는다.

    원문 대조가 없는 참고 자료다. sha 값이 있어도 검증으로 보지 않는다.
    구조가 표준 records(list)이든 예약번호 기준 dict이든 예약 번호 집합으로
    낮춰서 진단에만 쓴다. 중첩된 records/rows/list 항목까지 함께 본다.
    """
    if raw is None:
        raw=json.loads(Path(document).read_text(encoding='utf-8'))
    entries=[]
    keyed={}
    def collect(value, depth=0, booking_key=''):
        if depth>6:
            return
        if isinstance(value,list):
            for item in value:collect(item,depth+1)
            return
        if not isinstance(value,dict):
            return
        entries.append((booking_key,value))
        for key in ('records','rows','list','items','entries'):
            if key in value:collect(value[key],depth+1)
    if isinstance(raw,list):
        collect(raw)
    elif isinstance(raw,dict):
        if isinstance(raw.get('records'),list):
            collect(raw['records'])
        else:
            # 예약번호를 바깥 키로 쓰는 형식. 안쪽 값과 함께 그 번호를 유지한다.
            for key,value in raw.items():
                if isinstance(value,(dict,list)):collect(value,1,key)
    refs=collections.defaultdict(set)
    transactions=collections.defaultdict(set)
    sources=collections.defaultdict(set)
    fields=collections.defaultdict(lambda:collections.defaultdict(set))
    for booking_key,entry in entries:
        found=_entry_booking_refs(entry)
        # 항목 안의 명시 예약 번호가 먼저다. 바깥 키는 그것이 없을 때만 쓴다.
        if (not found and booking_key and booking_key not in STRUCTURAL_KEYS
                and re.fullmatch(r'[A-Za-z0-9_-]{8,32}',booking_key)
                and re.search(r'\d',booking_key)):
            found={booking_key}
        for ref in found:
            refs[ref].add(json.dumps(sorted(entry),ensure_ascii=False,default=str))
            for name,value in _comparable_fields(entry):
                fields[ref][name].add(json.dumps(value,ensure_ascii=False,default=str,sort_keys=True))
        # 거래 식별은 명시된 transaction_id·source_hash 만 따른다.
        # 구형 uid/event_id 는 다른 사물의 다른 이름일 수 있다.
        marker=json.dumps(sorted(entry),ensure_ascii=False,default=str)
        for key in ('transaction_id','source_hash'):
            value=entry.get(key)
            if isinstance(value,str) and value.strip():
                (transactions if key=='transaction_id' else sources)[value.strip()].add(marker)
    # 같은 예약에서 같은 항목의 값이 다를 때만 내용 충돌로 본다.
    # 다른 메일·다른 보고서가 붙는 것은 정상이라 충돌이 아니다.
    conflicts=sorted(ref for ref,values in fields.items()
                     if any(len(seen)>1 for seen in values.values()))
    return {'booking_refs':sorted(refs),'records':len(entries),
            'conflicting_booking_refs':conflicts,
            'comparable_values':{ref:{name:sorted(values) for name,values in fields[ref].items()}
                                 for ref in sorted(fields)},
            'transaction_ids':sorted(transactions),'source_hashes':sorted(sources)}


# 문서 구조를 설명하는 바깥 키. 예약 번호가 아니다.
STRUCTURAL_KEYS={'rows','records','list','items','entries','metadata','meta','summary',
                  'result','results','data','total','totals','count','schema_version'}
# 같은 예약에서 값이 달라지면 상충으로 볼 항목.
COMPARABLE_FIELDS=('item','amount','currency','card_last4','status','provider','payment_status',
                   'check_in','check_out','service_start_on','service_end_on','guests','room')


def _entry_booking_refs(entry):
    """항목 안의 명시 예약 번호만. 내부 숫자 id 는 예약 번호가 아니다."""
    found=set()
    for key in ('bookingRefs','booking_ref','booking_number'):
        value=entry.get(key)
        items=value if isinstance(value,list) else ([value] if isinstance(value,str) else [])
        found|={str(item).strip() for item in items if str(item).strip()}
    value=entry.get('booking_id')
    if (isinstance(value,str) and value.strip()
            and (not value.strip().isdigit() or 8<=len(value.strip())<=20)):
        found.add(value.strip())
    return found


def _comparable_fields(entry):
    for name in COMPARABLE_FIELDS:
        if name in entry and entry[name] not in (None,''):
            yield name,entry[name]


def load_reference_documents(documents):
    """참고 문서들을 모두 읽어 진단용으로 모은다. 결측은 진단으로 남는다."""
    inventory=[]
    comparable=collections.defaultdict(lambda:collections.defaultdict(set))
    index={'by_booking_ref':collections.defaultdict(lambda:{'documents':set(),'conflicting':set()}),
            'by_transaction_id':collections.defaultdict(lambda:{'documents':set()}),
            'by_source_hash':collections.defaultdict(lambda:{'documents':set()})}
    def documents_with_raw():
        from app.ota_store import is_store, reference_bundles
        for document in as_directories(documents):
            if Path(document).is_file() and is_store(document):
                yield from reference_bundles(document)
            else:
                yield document, None
    for document, stored_raw in documents_with_raw():
        path=Path(document)
        entry={'kind':'reference_document','path':str(path),'records':0,
               'booking_refs':[],'conflicting_booking_refs':[],
               'transaction_ids':[],'source_hashes':[]}
        if stored_raw is None and not path.is_file():
            entry['error']='file_not_found'
            inventory.append(entry)
            continue
        try:
            found=reference_records(path, raw=stored_raw)
        except (OSError,ValueError) as exc:
            entry['error']=f'unreadable: {exc}'
            inventory.append(entry)
            continue
        entry['records']=found['records']
        entry['booking_refs']=found['booking_refs']
        entry['conflicting_booking_refs']=found['conflicting_booking_refs']
        entry['transaction_ids']=found['transaction_ids']
        entry['source_hashes']=found['source_hashes']
        for ref,fields in found['comparable_values'].items():
            for field,values in fields.items():
                comparable[ref][field].update(values)
        inventory.append(entry)
        for kind,keys in (('by_booking_ref',found['booking_refs']),
                          ('by_transaction_id',found['transaction_ids']),
                          ('by_source_hash',found['source_hashes'])):
            for key in keys:
                index[kind].setdefault(key,{'documents':set(),'conflicting':set()})
                index[kind][key]['documents'].add(str(path))
        for ref in found['conflicting_booking_refs']:
            index['by_booking_ref'][ref]['conflicting'].add(ref)
    for ref,fields in comparable.items():
        if any(len(values)>1 for values in fields.values()):
            index['by_booking_ref'][ref]['conflicting'].add(ref)
    return {'sources':inventory,
            'errors':[entry for entry in inventory if entry.get('error')],
            'by_booking_ref':{ref:{'documents':sorted(value['documents']),
                                   'conflicting':bool(value['conflicting'])}
                              for ref,value in sorted(index['by_booking_ref'].items())},
            'by_transaction_id':{key:len(value['documents'])
                                 for key,value in sorted(index['by_transaction_id'].items())},
            'by_source_hash':{key:len(value['documents'])
                              for key,value in sorted(index['by_source_hash'].items())}}


def reference_diagnosis(references, row=None, booking_ref=''):
    """이미 검증된 예약이나 같은 거래에 참고 자료가 얼마나 붙는지를 진단한다.

    참고 자료는 결제 권위가 아니다. 그래서 이 결과는 `reference_only` 로만
    남고, 매칭 수·분류·보류를 바꾸지 않는다. 본문을 복제하지 않고 개수와
    사유만 남긴다.
    """
    if not references:
        return None
    known=references.get('by_booking_ref',{}).get(booking_ref) if booking_ref else None
    row_hit=0
    if row:
        for key,table in (('transaction_id',references.get('by_transaction_id',{})),
                          ('source_hash',references.get('by_source_hash',{}))):
            value=row.get(key)
            if value and value in table:
                row_hit=max(row_hit,table[value])
    if not known and not row_hit:
        return None
    conflicting=bool(known and known['conflicting'])
    return {'reason':'reference_only' if not conflicting else 'reference_content_conflict',
            'unverified_reference':True,
            'documents':max(row_hit,len(known['documents']) if known else 0),
            'matched_by':'booking_ref' if known else 'transaction_identity',
            'conflicting':conflicting}


_MAIL_SIDE_MEMO = {}


def _mail_side(directory, source_key):
    """메일 파일 내용만으로 정해지는 파싱·추출 결과. 같은 자료 지문이면 거래가 바뀌어도 다시 읽지 않는다."""
    def read():
        messages,mail_sources=load_messages_from(directory)
        facts=[fact for message in messages.values() if (fact:=extract_mail(message))]
        return messages,mail_sources,facts,lodging_mail_facts(messages)
    if source_key is None:
        return read()
    key=(tuple(str(path) for path in as_directories(directory)), source_key)
    if key not in _MAIL_SIDE_MEMO:
        _MAIL_SIDE_MEMO.clear()
        _MAIL_SIDE_MEMO[key]=read()
    return _MAIL_SIDE_MEMO[key]


def match_mail(directory, transactions, source_key=None):
    # 같은 원행을 두 출처에서 전달한 경우만 합친다. 별도 거래는 모호성을 유지한다.
    unique = {}
    for index,row in enumerate(transactions):
        key=(row.get('transaction_id'),row.get('source_hash')) if row.get('transaction_id') and row.get('source_hash') else ('row',index)
        unique.setdefault(key,row)
    transactions=list(unique.values())
    messages,mail_sources,facts,lodging_facts=_mail_side(directory,source_key)
    groups=collections.defaultdict(list)
    for fact in facts:
        groups[(fact['provider'],fact['booking_ref'])].append(fact)
    receipts=collections.defaultdict(list)
    for (provider,ref), group in groups.items():
        items={f['item'] for f in group if f['item']}
        if len(items)!=1:
            continue
        periods={tuple(sorted(f['period'].items())) for f in group if f['period']}
        cancelled=any(f['reservation_status']=='cancelled' for f in group)
        period=dict(next(iter(periods))) if len(periods)==1 else None
        if cancelled:period=None
        for fact in group:
            if fact['paid_amount_krw'] and fact['paid_amount_krw']>0:
                receipts[(provider,fact['paid_on'],fact['paid_amount_krw'])].append(
                    dict(fact,item=next(iter(items)),period=period,
                         reservation_status='cancelled' if cancelled else 'confirmed' if any(
                             f['reservation_status']=='confirmed' for f in group) else 'observed',
                         period_conflict=len(periods)>1,
                         evidence_digests=sorted({f['source_sha256'] for f in group})))
    current=collections.defaultdict(list)
    for row in transactions:
        if not row.get('approval_date') or row['approval_date']<'2026-04-01' or row['transaction_direction']!='purchase':
            continue
        merchant=row['merchant'].upper()
        provider='trip' if any(x in merchant for x in ('TRIP.COM','트립닷컴')) else 'klook' if any(x in merchant for x in ('KLOOK','클룩')) else ''
        if provider:
            current[(provider,row['approval_date'],row['amount_krw'])].append(row)
    matches=[]
    type_only=[]
    ambiguous=0
    for key, rows in current.items():
        options=receipts.get(key,[])
        identities={(f['booking_ref'],f['item']) for f in options}
        if len(rows)!=1 or len(identities)!=1:
            ambiguous+=bool(options)
            items={f['item'] for f in options}
            if len(items)==1:
                for row in rows:
                    shared=shared_lodging_period([f for group in groups.values() for f in group],
                                                paid_on=key[1],amount_krw=key[2])
                    type_only.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                                          merchant=row['merchant_normalized'],card_kind=row['card_kind'],
                                          direction=row['transaction_direction'],item=next(iter(items)),
                                          shared_period=shared['period'] if shared else None,
                                          booking_count=shared['booking_count'] if shared else len(identities),
                                          source_digests=sorted({f['source_sha256'] for f in options})))
            continue
        row=rows[0]; fact=min(options,key=lambda f:(f['message_id'],f['source_sha256']))
        matches.append(dict(transaction_id=row['transaction_id'],source_hash=row['source_hash'],
                            merchant=row['merchant_normalized'],card_kind=row['card_kind'],
                            direction=row['transaction_direction'],**fact))
    # 결제 연결과 실제 이용기간은 별개다. 취소·기간 미확인은 여행 근거만 막는다.
    additional=lodging_mail_matches(directory,transactions,messages=messages,require_active_period=False,facts=lodging_facts)
    by_source={row['source_hash']:row for row in transactions}
    for fact in additional:
        row=by_source[fact['source_hash']]
        matches.append(dict(fact,transaction_id=row.get('transaction_id',fact['source_hash']),
                            merchant=row['merchant_normalized'],card_kind=row['card_kind'],
                            direction=row['transaction_direction']))
    # 같은 결제일·금액의 숙박 결제가 여러 예약에 걸리면 예약번호를 고르지 않고 공통 이용기간만 제안한다.
    matched_sources={fact['source_hash'] for fact in matches}
    group_rows=collections.Counter()
    for row in transactions:
        provider=_lodging_provider(row)
        if provider and row['transaction_direction']=='purchase' and row.get('approval_date') and (row.get('amount_krw') or 0)>0:
            group_rows[(provider,row['approval_date'],row['amount_krw'])]+=1
    for row in transactions:
        provider=_lodging_provider(row)
        if (not provider or row['transaction_direction']!='purchase' or row['source_hash'] in matched_sources
                or not row.get('approval_date') or (row.get('amount_krw') or 0)<=0 or row['approval_date']<'2026-04-01'):
            continue
        shared=shared_lodging_stay(lodging_facts,provider=provider,
                                   paid_on=datetime.date.fromisoformat(row['approval_date']),amount_krw=row['amount_krw'])
        if not shared or group_rows[(provider,row['approval_date'],row['amount_krw'])]>shared['booking_count']:
            continue
        type_only.append(dict(transaction_id=row.get('transaction_id'),source_hash=row['source_hash'],
            merchant=row['merchant_normalized'],card_kind=row['card_kind'],direction=row['transaction_direction'],
            provider=provider,item='숙박비',evidence_kind='payment_receipt',shared_period=shared['period'],
            booking_count=shared['booking_count'],reservation_status='confirmed',source_digests=shared['source_digests']))
    matches.sort(key=lambda f:(f['transaction_id'],f['booking_ref']))
    rules=[dict(conditions={'merchant_normalized':f['merchant'],'card_kind':f['card_kind'],
                            'transaction_direction':f['direction']},optional={'source_hash':f['source_hash']},
                effects={'item':f['item'],'description':'예약 '+f['booking_ref']},
                origin='history-recovery-20261003',
                note=f.get('basis') or '지정 Gmail의 서명 검증된 예약 메일과 결제일·원화 금액·유일한 예약번호 대조. 여행 배정은 별도 확인.')
           for f in matches]
    rules += [dict(conditions={'merchant_normalized':f['merchant'],'card_kind':f['card_kind'],
                               'transaction_direction':f['direction']},optional={'source_hash':f['source_hash']},
                   effects={'item':f['item']},origin='history-recovery-20261003',
                   note='결제일·금액이 일치하는 예약 후보의 상품 종류가 모두 일치. 예약번호와 여행 연결은 보류.')
              for f in type_only]
    review_rows=[row for row in transactions if (row.get('approval_date') or '')>='2026-04-01'
                 and any(marker in row['merchant'].upper() for marker in
                         ('TRIP.COM','트립닷컴','KLOOK','클룩','AGODA','아고다','BOOKING','부킹닷컴'))]
    purchases=[row for row in review_rows if row['transaction_direction']=='purchase']
    matched={match['source_hash'] for match in matches}
    kind_only={match['source_hash'] for match in type_only}-matched
    coverage=dict(review_purchase_rows=len(purchases),
                  matched_purchase_rows=sum(row['source_hash'] in matched for row in purchases),
                  kind_only_rows=sum(row['source_hash'] in kind_only for row in purchases),
                  unmatched_purchase_rows=sum(row['source_hash'] not in matched|kind_only for row in purchases),
                  non_purchase_rows_preserved=len(review_rows)-len(purchases))
    unmatched=[]
    for row in purchases:
        if row['source_hash'] in matched|kind_only:
            continue
        reason='no_exact_payment_evidence'
        if row.get('amount_krw') is None and not (row.get('foreign_amount') and row.get('foreign_currency')):
            reason='payment_amount_unavailable'
        elif (row.get('amount_krw') is None and row.get('foreign_currency')=='USD'):
            reason='foreign_receipt_or_krw_acquisition_required'
        unmatched.append(dict(transaction_id=row.get('transaction_id'),source_hash=row['source_hash'],reason=reason))
    collection={entry['path']:entry['collection'] for entry in mail_sources}
    # 한 곳뿐인 동안은 기존 형태를 그대로 두고, 여러 곳이면 범위를 함께 남긴다.
    single=next(iter(entry['collection'] for entry in mail_sources
                     if entry['collection']),{})
    return {'messages_read':len(messages),'authenticated_facts':len(facts),
            'mail_sources':mail_sources,'mail_collections':collection,
            'mail_source_errors':[entry for entry in mail_sources if entry.get('error')],
            'mail_collection':single,
            'unmatched_reason_counts':dict(collections.Counter(r['reason'] for r in unmatched)),
            'unmatched_transactions':unmatched,
            'mail_categories':mail_categories(messages),'coverage':coverage,
            'additional_lodging_matches':len(additional),
            'booking_evidence_gaps':[dict(provider=f['provider'],booking_ref=f['booking_ref'],
                source_hash=f['source_hash'],reason='service_period_not_collected')
                for f in additional if f.get('period') is None
                and f.get('reservation_status')!='cancelled' and not f.get('period_conflict')],
            'service_period_conflicts':sum(bool(f.get('period_conflict')) for f in matches),
            'cancelled_reservation_matches':sum(f.get('reservation_status')=='cancelled' for f in matches),
            'exact_matches':len(matches),'ambiguous_groups':ambiguous,
            'items':dict(collections.Counter(f['item'] for f in matches)),
            'type_only_matches':len(type_only),'type_only_candidates':type_only,
            'matches':matches,'rules':rules}


def lodging_mail_facts(messages):
    """인증된 숙박 메일의 결제 사실. 메일 내용만 보므로 거래와 무관하게 한 번만 만든다."""
    from decimal import Decimal, InvalidOperation
    facts=[]
    currency_codes={'¥':'JPY','JPY':'JPY','€':'EUR','EUR':'EUR','US$':'USD','USD':'USD','₩':'KRW','KRW':'KRW'}
    for message in messages.values():
        authenticated=authenticated_headers(message,('agoda.com','booking.com'))
        if not authenticated:
            continue
        headers,domain=authenticated
        text=body_text(message['payload']);subject=headers.get('subject','')
        refs=set(re.findall(r'(?:예약\s*(?:번호|ID)|Booking ID)\s*[:：]?\s*(\d{6,15})',text+' '+subject,re.I))
        if len(refs)!=1:
            continue
        period=service_period(text)
        cancelled=reservation_cancelled(subject)
        paid=not cancelled and bool(re.search(r'결제가 완료|결제\s*완료|Payment confirmation|payment.*(?:received|successful)',subject,re.I))
        amounts=set()
        for currency,amount in re.findall(
                r'(?:총\s*금액|총\s*지불\s*금액|총\s*요금|Total(?:\s+price)?'+
                (r'|결제\s*완료' if paid else '')+r')\s*'
                r'(¥|€|US\$|₩|EUR|JPY|USD|KRW)\s*([0-9][0-9,.]*)',text,re.I):
            try:amounts.add((currency_codes.get(currency,currency.upper()),decimal_amount(amount)))
            except InvalidOperation:pass
        paid_on=sent_day(message,headers)
        if paid_on is None:continue
        scheduled=scheduled_charge_day(text) if domain=='agoda.com' and not cancelled else None
        evidence_kind='payment_receipt' if paid else 'scheduled_charge' if scheduled else ''
        if not paid and scheduled:
            paid_on=scheduled
        digest=hashlib.sha256(json.dumps(message,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        facts.append(dict(provider='agoda' if domain=='agoda.com' else 'booking',booking_ref=next(iter(refs)),
                          period=period,amounts=amounts,paid_on=paid_on,paid=paid,
                          cancelled=cancelled,source_sha256=digest,evidence_kind=evidence_kind,
                          reservation_status='cancelled' if cancelled else 'confirmed' if '확정' in subject else 'observed'))
    return facts


def lodging_mail_matches(directory, transactions, *, messages=None, require_active_period=True, facts=None):
    """숙박의 원화·외화 결제 영수증을 유일한 카드 원행과 이용기간에 연결한다."""
    from decimal import Decimal, InvalidOperation
    messages=load_messages_from(directory)[0] if messages is None else messages
    facts=lodging_mail_facts(messages) if facts is None else facts
    periods=collections.defaultdict(set)
    for fact in facts:
        if fact['period']:periods[(fact['provider'],fact['booking_ref'])].add(tuple(sorted(fact['period'].items())))
    cancelled={(f['provider'],f['booking_ref']) for f in facts if f['cancelled']}
    candidates=collections.defaultdict(list)
    rows_by_receipt=collections.defaultdict(set)
    for row in transactions:
        if row['transaction_direction']!='purchase' or (row['approval_date'] or '')<'2026-04-01':continue
        merchant=row['merchant'].upper()
        provider='agoda' if 'AGODA' in merchant or '아고다' in merchant else 'booking' if 'BOOKING' in merchant or '부킹닷컴' in merchant else ''
        if not provider:continue
        try:
            occurred=datetime.date.fromisoformat(row['approval_date'])
            krw=row.get('amount_krw')
            amounts={('KRW',Decimal(str(krw)))} if krw is not None and krw>0 else set()
            if row.get('foreign_amount') and row.get('foreign_currency'):
                amounts.add((row['foreign_currency'],Decimal(str(row['foreign_amount'])).copy_abs()))
        except (InvalidOperation,ValueError):continue
        for fact in facts:
            common=amounts & fact['amounts']
            valid={pair for pair in common if abs((occurred-fact['paid_on']).days)<=(0 if pair[0]=='KRW' else 1)}
            if (fact['provider']==provider and (fact['paid'] or fact['evidence_kind']=='scheduled_charge') and
                    valid):
                identity=(provider,fact['booking_ref'])
                candidates[row['source_hash']].append(fact);rows_by_receipt[identity].add(row.get('transaction_id',row['source_hash']))
    result=[]
    for source_hash,options in candidates.items():
        identities={(f['provider'],f['booking_ref']) for f in options}
        if len(identities)!=1:continue
        identity=next(iter(identities));service_periods=periods[identity]
        if len(rows_by_receipt[identity])!=1:continue
        inactive=identity in cancelled
        conflict=len(service_periods)>1
        if require_active_period and (inactive or len(service_periods)!=1):continue
        period=dict(next(iter(service_periods))) if len(service_periods)==1 and not inactive else None
        payment=min(options,key=lambda f:(not f['paid'],f['source_sha256']))
        basis=(('서명 검증된 예약의 자동 결제 예정일과 실제 카드 거래' if payment['evidence_kind']=='scheduled_charge' else '서명 검증된 결제 메일')+
               '의 통화·금액·결제일이 유일하게 일치(원화는 같은 날, 외화는 하루 이내); 예약 '+identity[1])
        if period:
            basis+='의 이용기간 '+period['starts_on']+'~'+period['ends_on']+'을 참고한 추론'
        result.append(dict(source_hash=source_hash,provider=identity[0],item='숙박비',period=period,booking_ref=identity[1],
                           strict_service_period=True,confidence='중간',
                           source_sha256=payment['source_sha256'],evidence_kind=payment['evidence_kind'],
                           evidence_digests=sorted({f['source_sha256'] for f in facts
                               if (f['provider'], f['booking_ref']) == identity}),
                           reservation_status='cancelled' if inactive else 'confirmed' if any(
                               f.get('reservation_status')=='confirmed' for f in facts
                               if (f['provider'], f['booking_ref']) == identity) else 'observed',
                           period_conflict=conflict,basis=basis))
    return result


def ledger_metadata(report, entry):
    """기존 대조 결과의 확정 사실만 장부 미리보기에 전달한다. 재대조하지 않는다."""
    empty = {'booking_ref': '', 'service_period': '', 'ota_evidence': {}}
    if (report is None or entry.get('transaction_direction') != 'purchase'
            or report.get('ota_source_errors')
            or report.get('ota_source_inventory',{}).get('missing')):
        return empty
    source = entry['source_hash']
    exact = [f for f in report.get('matches', []) if f['source_hash'] == source]
    facts = exact or [f for f in report.get('type_only_candidates', []) if f['source_hash'] == source]
    if not facts or any(f.get('transaction_id', entry['transaction_id']) != entry['transaction_id']
                        or f.get('item') != entry['item']
                        or f.get('reservation_status') in ('cancelled', 'refund_pending', 'evidence_pending')
                        or f.get('evidence_pending') or f.get('refund_pending')
                        or f.get('period_conflict') or f.get('booking_link_conflict')
                        for f in facts):
        return empty
    # 예약번호 모호성은 matcher의 type-only 결과를 그대로 따른다.
    refs = {f.get('booking_ref') for f in exact}
    group = bool(exact) and refs == {''} and all(f.get('group_size') for f in exact)
    if exact and not group and (len(refs) != 1 or not next(iter(refs))):
        return empty
    if exact and any(f.get('reservation_status') not in ('observed', 'confirmed', 'completed') for f in exact):
        return empty
    periods = [f.get('period') if exact else f.get('shared_period') for f in facts]
    if any(p != periods[0] for p in periods):
        return empty
    period = periods[0]
    if not period and (not exact or entry['item'] == '숙박비'):
        return empty
    digests = sorted({digest for f in facts for digest in
                      (list(f.get('source_digests') or []) + list(f.get('evidence_digests') or [])
                       + [f.get('source_sha256')])
                      if digest})
    if not digests:
        return empty
    inferred = any(f.get('inferred_link') for f in facts)
    allocations = sorted({f['allocation_basis'] for f in facts if f.get('allocation_basis')})
    ordered = any(value in ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                  for value in allocations)
    return {'booking_ref': '' if group or inferred or not exact else next(iter(refs)),
            'service_period': period['starts_on'] + '~' + period['ends_on'] if period else '',
            'ota_evidence': {'kind': 'inferred' if inferred else 'ordered_group' if ordered else
                                    'portal_group' if group else 'exact' if exact else 'shared_period',
                             **({'payment_date_verified': False} if inferred else {}),
                             **({'allocation_basis': allocations} if allocations else {}),
                             'source_digests': digests,
                             'providers': sorted({f['provider'] for f in facts if f.get('provider')}),
                             'evidence_kinds': sorted({f['evidence_kind'] for f in facts if f.get('evidence_kind')})}}


def europe_stays(directory):
    """사용자가 지정한 숙박 메일로 확인되는 유럽 체류 범위를 보존한다."""
    messages=load_messages_from(directory)[0]
    stays=[]
    selected={}
    cancellations={}
    cancel_messages={}
    for message in messages.values():
        authenticated=authenticated_headers(message,('trip.com','agoda-messaging.com'))
        if not authenticated:
            continue
        headers,domain=authenticated
        subject=headers.get('subject','')
        text=''.join(c for c in body_text(message['payload']) if unicodedata.category(c)!='Cf')
        if re.search('취소|cancel',subject,re.I):
            for ref in re.findall(r'예약\s*번호\s*[:：]?\s*(\d{16})',text):
                if int(message['internal_date'])>cancellations.get(ref,0):
                    cancellations[ref]=int(message['internal_date'])
                    cancel_messages[ref]=message
            continue
        ref='';period=None;countries=set()
        if domain=='trip.com':
            if not ('예약 확정 안내' in subject or '체크인이 얼마 남지' in subject):
                continue
            refs=set(re.findall(r'예약\s*번호\s*[:：]?\s*(\d{16})',text))
            dates=[]
            for label in ('체크인','체크아웃'):
                matches=set(re.findall(label+r'\s*[:：]?\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일',text))
                if len(matches)==1:
                    dates.append(datetime.date(*map(int,next(iter(matches)))).isoformat())
            if len(refs)==1 and len(dates)==2:
                ref=next(iter(refs));period={'starts_on':dates[0],'ends_on':dates[1]}
            lines=[s.strip() for s in text.splitlines() if s.strip()]
            addresses=[' '.join(lines[i+1:i+4]) for i,line in enumerate(lines) if line in ('주소','Address')]
            for name,code in [('프랑스','FR'),('France','FR'),('이탈리아','IT'),('Italy','IT'),('오스트리아','AT'),('Austria','AT')]:
                if any(name in address for address in addresses):countries.add(code)
        else:
            # 숙소 응답 메일의 예약 ID와 연도가 명시된 이용기간을 함께 읽는다.
            match=re.search(r'Booking ID:\s*(\d{8,12})\s*\(([A-Za-z]+) (\d{1,2})-(\d{1,2}), (\d{4})\)',subject)
            if not match:
                continue
            ref,month,start,end,year=match.groups()
            try:
                number=datetime.datetime.strptime(month,'%B').month
                period={'starts_on':datetime.date(int(year),number,int(start)).isoformat(),
                        'ends_on':datetime.date(int(year),number,int(end)).isoformat()}
            except ValueError:
                continue
            if 'Salzburg' in subject or 'innsbruck' in subject.lower():countries.add('AT')
            if 'Casa di Franz' in subject or 'Hotel La Pioppa' in subject:countries.add('IT')
        if not period or not countries or not ('2026-05-01'<=period['starts_on']<='2026-06-10'):
            continue
        stays.append(dict(booking_ref=ref,**period,countries=sorted(countries),message_id=message['id']))
        selected[message['id']]=message
    if not stays:
        return None
    # 같은 예약의 서로 다른 이용기간은 최신 확인 메일로 정해진 경우만 허용한다.
    latest={}
    for stay in stays:
        previous=latest.get(stay['booking_ref'])
        if previous is None or int(messages[stay['message_id']]['internal_date'])>int(messages[previous['message_id']]['internal_date']):
            latest[stay['booking_ref']]=stay
    final=[stay for ref,stay in latest.items()
           if cancellations.get(ref,0)<int(messages[stay['message_id']]['internal_date'])]
    if not final:
        return None
    return {'starts_on':min(s['starts_on'] for s in final),'ends_on':max(s['ends_on'] for s in final),
            'countries':sorted({c for s in final for c in s['countries']}), 'stays':final,
            'cancelled_booking_refs':sorted(ref for ref,stay in latest.items() if stay not in final),
            'messages':[selected[s['message_id']] for s in latest.values()]
                       +[cancel_messages[ref] for ref in latest if ref in cancel_messages],
            'instruction':'2026-10-03 사용자 지시: OTA 숙박메일로 유럽 일정을 파악. 체크아웃 날짜를 그대로 보존.'}
