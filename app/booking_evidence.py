"""카드 거래와 금액이 같은 예약 메일을 찾아 판단에 필요한 내용만 보여준다. 배정이나 기록은 하지 않는다."""
import re
from datetime import date, timedelta

from . import ota_mail

OTA_DOMAINS = ('trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com',
               'toyoko-inn.com', 'toyoko-inn.co.jp')
WINDOW_DAYS = 120
REFUND_WORDS = ('돌려드립니다', '보증금', '객실 확보', '환불')
NOTE_WORDS = ('결제', '취소 수수료', '무료 취소')
PAID_WORDS = ('결제 완료', '결제가 완료', '결제되었습니다', '결제가 처리되었습니다',
              '결제 처리 완료', '선결제 완료', '결제하셨습니다')
_KRW = re.compile(r'([0-9][0-9,]{3,})\s*원')
_REF = re.compile(r'예약\s*번호\s*[:：]?\s*\n?\s*([0-9A-Z]{8,20})', re.I)

_INDEX = {'source': None, 'by_amount': {}, 'by_ref': {}, 'count': 0}


def _sent_day(headers):
    value = headers.get('date', '')
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def summarize(subject, sent, text):
    """메일 한 통에서 판단에 필요한 사실만 뽑는다. 문장은 짧게 자른다."""
    refs = sorted(set(_REF.findall(text)))
    period = ota_mail.service_period(text) or {}
    toyoko = bool(re.search(r'토요코인|toyoko', subject, re.I))
    if toyoko:
        refs = sorted(set(re.findall(r'예약\s*번호\s*[:：]?\s*([0-9]{7,20})(?![0-9])', text)))
        # 토요코인 원문은 체크인/체크아웃 대신 숙박일과 숙박 수를 적는다.
        stays = set()
        for year, month, day, nights in re.findall(
                r'숙박일\s*[:：]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일'
                r'\s*(?:\([^\n)]*\))?\s*부터\s*(\d+)\s*박', text):
            try:
                start = date(int(year), int(month), int(day))
                count = int(nights)
                if 1 <= count <= 365:
                    stays.add((start.isoformat(), (start + timedelta(days=count)).isoformat()))
            except ValueError:
                continue
        if not period and len(stays) == 1:
            start, end = next(iter(stays))
            period = {'starts_on': start, 'ends_on': end}
    notes = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for words in (REFUND_WORDS, NOTE_WORDS):
        for line in lines:
            if any(word in line for word in words) and line[:120] not in notes:
                notes.append(line[:120])
            if len(notes) == 5:
                break
    amounts = []
    for value in _KRW.findall(text):
        number = int(value.replace(',', ''))
        if number not in amounts:
            amounts.append(number)
        if len(amounts) == 6:
            break
    # 예약 확정, 카드 사전승인, 현장 결제 예정은 결제 완료 증거가 아니다.
    # 인접한 줄에 다른 비용이 있을 수 있으므로 여러 금액을 임의로 결제액으로 보지 않는다.
    paid_amounts = set()
    if any(word in subject for word in PAID_WORDS) and not any(
            word in subject for word in ('미결제', '결제 실패', '결제 거부', '결제 취소', '결제 완료 예정')):
        if len(amounts) == 1:
            paid_amounts.add(amounts[0])
    for position, line in enumerate(lines):
        if any(word in line for word in PAID_WORDS) and not any(
                word in line for word in ('미결제', '결제 실패', '결제 거부', '결제 취소', '결제 완료 예정')):
            line_amounts = {int(value.replace(',', '')) for value in _KRW.findall(line)}
            if len(line_amounts) == 1:
                paid_amounts.update(line_amounts)
            elif not line_amounts and len(amounts) == 1:
                paid_amounts.add(amounts[0])
    if len(paid_amounts) != 1:
        paid_amounts.clear()
    paid_amounts.intersection_update(amounts)
    totals = {}
    hotel_name = ''
    if toyoko:
        for number, unit in re.findall(r'합계금액\s*[:：]\s*([0-9][0-9,]*)\s*(원|엔)', text):
            currency = 'KRW' if unit == '원' else 'JPY'
            totals.setdefault(currency, set()).add(int(number.replace(',', '')))
        totals = {currency: sorted(values) for currency, values in totals.items()}
        # 법인 예약 메일의 제목에는 지점이 없으므로 본문의 독립된 호텔명만 사용한다.
        for line in lines:
            if (re.fullmatch(r'토요코인\s+[가-힣A-Za-z0-9 .-]{1,40}', line)
                    and not any(word in line for word in ('클럽', '회원', '코퍼레이트', '예약', '바랍니다'))):
                hotel_name = line
                break
    return {'subject': subject, 'sent': sent.isoformat() if sent else '', 'refs': refs,
            'starts_on': period.get('starts_on', ''), 'ends_on': period.get('ends_on', ''),
            'amounts': amounts, 'notes': notes, 'paid_amounts': sorted(paid_amounts),
            'currency_totals': totals, 'hotel_name': hotel_name}


def build_index(mail_directories):
    """예약 메일을 금액별로 묶은 색인. 메일 내용이 바뀌지 않으면 다시 만들지 않는다."""
    messages, _ = ota_mail.load_messages_from(mail_directories)
    if _INDEX['source'] is messages:
        return _INDEX
    by_amount, by_ref = {}, {}
    for message in messages.values():
        authenticated = ota_mail.authenticated_headers(message, OTA_DOMAINS)
        if not authenticated:
            continue
        headers, _ = authenticated
        text = ota_mail.message_text(message)
        entry = summarize(headers.get('subject', ''), _sent_day(headers), text)
        entry['message_id'] = message.get('id', '')
        for amount in entry['amounts']:
            by_amount.setdefault(amount, []).append(entry)
        for ref in entry['refs']:
            by_ref.setdefault(ref, []).append(entry)
    _INDEX.update(source=messages, by_amount=by_amount, by_ref=by_ref, count=len(messages))
    return _INDEX


def find_refs(index, refs):
    """금액이나 발송 시점과 무관하게 같은 예약번호의 취소·환불 안내를 찾는다."""
    return [entry for ref in refs for entry in index.get('by_ref', {}).get(ref, ())]


def find(index, amount_krw, occurred_on, *, limit=3):
    """금액이 같은 메일을 가까운 순으로 찾는다. 화면에는 3통, 자동 판단에는 전부 사용한다."""
    amount = abs(int(amount_krw or 0))
    try:
        day = date.fromisoformat(str(occurred_on)[:10])
    except ValueError:
        day = None
    found = []
    for entry in index['by_amount'].get(amount, []):
        sent = date.fromisoformat(entry['sent']) if entry['sent'] else None
        if day and sent and abs((sent - day).days) > WINDOW_DAYS:
            continue
        found.append(entry)
    found.sort(key=lambda e: abs((date.fromisoformat(e['sent']) - day).days) if day and e['sent'] else 0)
    return (found[:limit] if limit is not None else found), index['count']


def _direct_hotel_key(value):
    """같은 지점의 띄어쓰기·호텔 접미사 표기를 통일한다."""
    compact = lambda value: re.sub(r'[^0-9a-z가-힣]', '', str(value or '').casefold())
    name = compact(value).replace('토요코인호텔', '토요코인').replace('toyokoinnhotel', 'toyokoinn')
    name = re.sub(r'ii$', '2', name)
    prefix = '토요코인' if name.startswith('토요코인') else 'toyokoinn' if name.startswith('toyokoinn') else ''
    return name if prefix and len(name) > len(prefix) else ''


def same_direct_hotel_branch(left, right):
    key = _direct_hotel_key(left)
    return bool(key and key == _direct_hotel_key(right))


def direct_hotel_branch_matches(entry, merchant):
    """취소 안내까지 포함해 동일 호텔 지점의 메일인지 확인한다."""
    name = _direct_hotel_key(merchant)
    subject = re.sub(r'[^0-9a-z가-힣]', '', str(entry.get('subject') or '').casefold())
    subject = subject.replace('토요코인호텔', '토요코인').replace('toyokoinnhotel', 'toyokoinn')
    return bool(name and (name in subject or same_direct_hotel_branch(entry.get('hotel_name'), merchant)))


def matches_direct_hotel(entry, merchant, *, amount=None):
    """지점·예약번호·기간과 결제 완료 근거가 모두 있는 호텔 예약만 연결한다."""
    if not direct_hotel_branch_matches(entry, merchant):
        return False
    notes = ' '.join(entry.get('notes') or ())
    if any(word in notes for word in ('돌려드립니다', '객실 확보', '보증금', '환불', '결제 실패', '결제 거부')):
        return False
    return ('확정' in entry.get('subject', '') and '취소' not in entry.get('subject', '')
            and bool(entry.get('refs')) and bool(entry.get('starts_on')) and bool(entry.get('ends_on'))
            and (amount is None or abs(int(amount)) in entry.get('paid_amounts', ())))


def describe(entry):
    """판단에 필요한 줄만: 예약명·상태, 예약번호, 이용기간, 결제·환불 상태."""
    subject = entry['subject']
    status = ('취소' if '취소' in subject else '확정' if '확정' in subject else
              '예약 확인' if re.search(r'예약\s*확인', subject) else '')
    name = re.split(r'\s*예약|\s*-NoReply', re.sub(r'^\[[^\]]*\]\s*', '', subject))[0].strip() or subject
    lines = [f"{name} · {status}" if status else name]
    if entry['refs']:
        lines.append('예약번호 ' + ', '.join(entry['refs']))
    if entry['starts_on'] or entry['ends_on']:
        lines.append(f"이용 {entry['starts_on'] or '?'} ~ {entry['ends_on'] or '?'}")
    notes = ' '.join(entry['notes'])
    state = []
    if '결제 완료' in notes or '온라인 사전 결제' in notes:
        state.append('결제 완료')
    if '돌려드립니다' in notes:
        state.append('체크아웃 후 돌려주는 보증금')
    elif '환불' in notes:
        state.append('환불 안내')
    if state:
        lines.append(' · '.join(state))
    return lines
