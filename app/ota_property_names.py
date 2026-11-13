"""Lodging names stated by authenticated Agoda and Trip.com booking mails (display evidence only)."""
import re
from collections import defaultdict

from app import ota_mail

_AGODA = ('agoda.com',)
_TRIP = ('trip.com', 'trip.co.kr')
_AGODA_REF = re.compile(r'예약\s*번호\s*[:：]?\s*(\d{6,12})')
_AGODA_NAME = re.compile(r'(?:예약\s*관리하기\s*){1,2}(?:&nbsp;|\s)*(.{3,200}?)\s*숙소\s*위치\s*확인', re.S)
_TRIP_NAME = re.compile(r'^\s*\[예약\s*확정\s*안내\]\s*(.+?)\s*예약이')
_LATIN_LEAD = re.compile(r"[A-Za-z][A-Za-z'&.\- ]*")


def _latin_lead(text):
    """The Latin-script name before its local-script name, digits or address."""
    found = _LATIN_LEAD.match(text.strip())
    return found.group(0).strip(' .-') if found else ''


def _agoda_fact(message, headers):
    subject = headers.get('subject', '')
    ref = _AGODA_REF.search(subject)
    if not ref or '확정서' not in subject:
        return None
    named = _AGODA_NAME.search(ota_mail.message_text(message))
    name = _latin_lead(named.group(1)) if named else ''
    return ('agoda', ref.group(1), name) if name else None


def _trip_fact(message, headers):
    named = _TRIP_NAME.match(headers.get('subject', ''))
    fact = ota_mail.extract_mail(message) if named else None
    if not fact or fact.get('provider') != 'trip' or fact.get('item') != '숙박비' or not fact.get('booking_ref'):
        return None
    return 'trip', str(fact['booking_ref']), named.group(1).strip()


def collect(mail_directories):
    """'provider:booking_ref' -> sorted lodging names the booking's mails state."""
    messages, _ = ota_mail.load_messages_from(mail_directories)
    names = defaultdict(set)
    for message in messages.values():
        try:
            for domains, read in ((_AGODA, _agoda_fact), (_TRIP, _trip_fact)):
                authenticated = ota_mail.authenticated_headers(message, domains)
                found = read(message, authenticated[0]) if authenticated else None
                if found and found[2]:
                    names[f'{found[0]}:{found[1]}'].add(found[2])
        except Exception:
            continue
    return {key: sorted(values) for key, values in names.items()}

