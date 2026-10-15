"""카드 거래와 금액이 같은 예약 메일을 찾아 판단에 필요한 내용만 보여준다. 배정이나 기록은 하지 않는다."""
import re
from datetime import date, timedelta

from . import ota_mail

OTA_DOMAINS = ('trip.com', 'trip.co.kr', 'klook.com', 'agoda.com', 'booking.com')
WINDOW_DAYS = 120
REFUND_WORDS = ('돌려드립니다', '보증금', '객실 확보', '환불')
NOTE_WORDS = ('결제', '취소 수수료', '무료 취소')
_KRW = re.compile(r'([0-9][0-9,]{3,})\s*원')
_REF = re.compile(r'예약\s*번호\s*[:：]?\s*\n?\s*([0-9A-Z]{8,20})', re.I)

_INDEX = {'source': None, 'by_amount': {}, 'count': 0}


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
    return {'subject': subject, 'sent': sent.isoformat() if sent else '', 'refs': refs,
            'starts_on': period.get('starts_on', ''), 'ends_on': period.get('ends_on', ''),
            'amounts': amounts, 'notes': notes}


def build_index(mail_directories):
    """예약 메일을 금액별로 묶은 색인. 메일 내용이 바뀌지 않으면 다시 만들지 않는다."""
    messages, _ = ota_mail.load_messages_from(mail_directories)
    if _INDEX['source'] is messages:
        return _INDEX
    by_amount = {}
    for message in messages.values():
        authenticated = ota_mail.authenticated_headers(message, OTA_DOMAINS)
        if not authenticated:
            continue
        headers, _ = authenticated
        text = ota_mail.message_text(message)
        entry = summarize(headers.get('subject', ''), _sent_day(headers), text)
        for amount in entry['amounts']:
            by_amount.setdefault(amount, []).append(entry)
    _INDEX.update(source=messages, by_amount=by_amount, count=len(messages))
    return _INDEX


def find(index, amount_krw, occurred_on):
    """같은 금액의 예약 메일 최대 3통과 검색한 메일 수. 날짜는 거래일 전후 120일 안에서 가까운 순으로 본다."""
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
    return found[:3], index['count']


def describe(entry):
    """판단에 필요한 줄만: 예약명·상태, 예약번호, 이용기간, 결제·환불 상태."""
    subject = entry['subject']
    status = '취소' if '취소' in subject else '확정' if '확정' in subject else ''
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
