"""Aside에서 관측한 예약과 보존 메일을 로컬 증거 DB에 저장한다."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


SCHEMA = 'agoda-aside-capture-v1'
FORMAT = 'agoda-aside-v1'
PARSER_VERSION = 2  # 공개한 해석을 바꿀 때 올린다. DB는 원문과 이전 해석을 보존한다.
ROLES = ('identity', 'service_period', 'portal_payment_claim',
         'portal_card_observation', 'lifecycle')
CURRENCIES = r'(KRW|JPY|USD|EUR|GBP|GEL|₩|¥|€|US\$)'
NUMBER = r'((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d,.])'


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('CAPTURE_TIMEZONE_REQUIRED')
    return parsed.astimezone(timezone.utc).isoformat()


def visible_text(snapshot):
    """접근성 트리의 문자열만 읽는다. 링크 주소나 숨은 상태를 날짜로 사용하지 않는다."""
    texts = []
    for line in snapshot.splitlines():
        if not re.match(r'\s*- (?:text:|heading |link |button |paragraph:|alert:)', line):
            continue
        values = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        for value in values:
            try:
                texts.append(json.loads('"' + value + '"'))
            except ValueError:
                texts.append(value)
    return '\n'.join(texts)


def money(currency, raw, kind):
    currency = {'₩': 'KRW', '¥': 'JPY', '€': 'EUR', 'US$': 'USD'}.get(currency, currency)
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', raw):
        raise ValueError('CAPTURE_INVALID_MONEY')
    amount = Decimal(raw.replace(',', ''))
    scale = 0 if currency in ('KRW', 'JPY') else 2
    units = amount * (10 ** scale)
    if not amount.is_finite() or amount < 0 or units != units.to_integral_value():
        raise ValueError('CAPTURE_INVALID_MONEY')
    return {'kind': kind, 'currency': currency, 'decimal_text': str(amount),
            'minor_units': int(units), 'scale': scale, 'observed_text': currency + ' ' + raw}


def _days(label, text):
    found = set()
    pattern = label + r'\s*[:：]?\s*(?:(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일|(\d{4}-\d{2}-\d{2}))'
    for year, month, day, iso in re.findall(pattern, text):
        found.add(date.fromisoformat(iso).isoformat() if iso else date(int(year), int(month), int(day)).isoformat())
    return found


def _day(label, text):
    found = _days(label, text)
    return next(iter(found)) if len(found) == 1 else None


def parse_detail(capture):
    """현재 확인된 한국어 상세 형식. 지원하지 않는 상태는 진단과 원문으로 남긴다."""
    if capture.get('schema_version') != SCHEMA or capture.get('kind') != 'detail':
        raise ValueError('CAPTURE_SCHEMA_MISMATCH')
    booking = str(capture.get('booking_number') or '')
    if not re.fullmatch(r'\d{6,20}', booking):
        raise ValueError('CAPTURE_BOOKING_REQUIRED')
    proof = capture.get('entry_proof') or {}
    if (str(proof.get('booking_number')) != booking or
            not re.search(r'예약 확인/변경하기\s+' + re.escape(booking) + r'\b', str(proof.get('button_name') or ''))):
        raise ValueError('CAPTURE_ENTRY_PROOF_REQUIRED')
    text = visible_text(capture.get('snapshot_text') or '')
    identities = set(re.findall(r'예약\s*번호\s*[:：]?\s*(\d{6,20})\b', text))
    # Flight detail pages render the number in a separate generic node.
    # Only trust a number immediately following the booking-number label.
    identities.update(re.findall(
        r'- text: "[^"\n]*예약\s*번호\s*[:：]\s*"\s*\n\s*- generic "(\d{6,20})"',
        capture.get('snapshot_text') or ''))
    if identities != {booking}:
        raise ValueError('CAPTURE_BOOKING_IDENTITY_MISMATCH')
    starts, ends = _days('체크인', text), _days('체크아웃', text)
    for sy, sm, sd, ey, em, ed in re.findall(
        r'숙박\s*날짜\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일[^\d\n]*?[-–~]\s*'
        r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', text):
        starts.add(date(int(sy),int(sm),int(sd)).isoformat())
        ends.add(date(int(ey),int(em),int(ed)).isoformat())
    start = next(iter(starts)) if len(starts)==1 else None
    end = next(iter(ends)) if len(ends)==1 else None
    if start and end and end < start:
        raise ValueError('CAPTURE_INVALID_SERVICE_PERIOD')
    status = ('cancelled' if (re.search(r'예약이 취소되었습니다|취소된 예약|예약 취소됨', text)
              or _day('예약 취소일', text))
              else 'completed' if '투숙 완료' in text else
              'confirmed' if re.search(r'예약(?:은|이)\s*확정|예약\s*확정됨', text) else 'unknown')
    section = re.split(r'결제 정보', text, maxsplit=1)
    payment = re.split(r'결제 방법|이 예약으로 적립됨|도움말·문의', section[1], maxsplit=1)[0] if len(section) == 2 else ''
    cards = set(re.findall(r'카드\s*번호\s*[•●*Xx\s-]*(\d{4})\b', text))
    last4 = next(iter(cards)) if len(cards) == 1 else None
    paid = [money(c, n, 'paid_today') for c, n in re.findall(
        r'(?:오늘\s*결제됨|결제\s*완료(?:됨)?|지불\s*완료)\s*' + CURRENCIES + r'\s*' + NUMBER, payment)]
    paid = list({dump(x): x for x in paid}.values())
    scheduled = bool(re.search(r'결제될 예정|결제 예정|will be charged', payment, re.I))
    refund = bool(re.search(r'환불\s*(?:완료|처리됨)|refund completed', payment, re.I))
    refund_pending = bool(re.search(r'환불\s*(?:요청|예정|진행)', payment))
    payment_failed = bool(re.search(r'결제\s*관련\s*문제\s*발생|신용카드\s*결제\s*거부', text))
    deadlines = set(re.findall(r'(\d{1,2}월\s*\d{1,2}일\s*\d{1,2}:\d{2})\s*전에?\s*'
                              r'본\s*예약에\s*대한\s*결제를\s*완료', text))
    property_due = [money(c,n,'property_due') for c,n in re.findall(
        r'체크인 시[^\n]*?에서 결제\s*' + CURRENCIES + r'\s*' + NUMBER, payment)]
    property_due = list({dump(x):x for x in property_due}.values())
    cash_use = [money(c,n,'agoda_cash') for c,n in re.findall(
        r'AgodaCash\s*-\s*' + CURRENCIES + r'\s*' + NUMBER, payment)]
    cash_use = list({dump(x):x for x in cash_use}.values())
    expected_refund = [money(c,n,'refund_expected') for c,n in re.findall(
        r'환불될 금액\s*' + CURRENCIES + r'\s*' + NUMBER, payment)]
    expected_refund = list({dump(x):x for x in expected_refund}.values())
    refund_pending |= any(part['minor_units']>0 for part in expected_refund)
    diagnostics = []
    if status == 'unknown': diagnostics.append('reservation_status_unknown')
    if not start or not end: diagnostics.append('service_period_missing')
    if len(starts)>1 or len(ends)>1: diagnostics.append('service_period_conflict')
    if not last4 and not cash_use: diagnostics.append('card_observation_missing')
    if len(paid) > 1: diagnostics.append('amount_ambiguous')
    if refund or refund_pending: diagnostics.append('refund_layout_requires_review')
    if status == 'cancelled': diagnostics.append('cancelled_booking')
    if scheduled: diagnostics.append('scheduled_payment')
    if payment_failed: diagnostics.append('payment_failed')
    if property_due: diagnostics.append('pay_at_property_not_an_ota_charge')
    paid_on = _day(r'(?:결제일|결제 완료일)', payment)
    if not paid_on: diagnostics.append('payment_date_unknown')
    components = paid[:] + property_due + cash_use + expected_refund
    for label, kind in [('총 금액', 'gross_total'), ('세금 및 봉사료', 'taxes_and_fees')]:
        components.extend(money(c, n, kind) for c, n in re.findall(label + r'\s*' + CURRENCIES + r'\s*' + NUMBER, payment))
    # 사용과 적립을 구분한다. 아직 관측하지 않은 캐시/환불 양식은 기장 근거로 만들지 않는다.
    if not cash_use and re.search(r'AgodaCash\s*(?:사용|차감)|사용한\s*AgodaCash', payment, re.I):
        diagnostics.append('cash_layout_requires_review')
    observed_paid = bool(len(paid) == 1 and paid[0]['minor_units']>0 and not scheduled
                         and not refund and not refund_pending and not property_due and not payment_failed)
    confirmed_paid = bool(observed_paid and last4)
    roles = ['identity']
    if start and end: roles.append('service_period')
    if paid or scheduled or property_due or cash_use or payment_failed: roles.append('portal_payment_claim')
    if last4: roles.append('portal_card_observation')
    if status != 'unknown': roles.append('lifecycle')
    return {'provider': 'agoda', 'booking_number': booking,
            'service_start_on': start, 'service_end_on': end, 'reservation_status': status,
            'status': status, 'evidence_format': FORMAT, 'parser_version': PARSER_VERSION,
            'payment_status': ('failed' if payment_failed else
                               'cash_only' if cash_use and not any(p['minor_units']>0 for p in paid) and not property_due else
                               'pay_at_property' if property_due and not paid else
                               'scheduled' if scheduled else 'paid' if confirmed_paid else
                               'paid_observed_without_card' if observed_paid else 'unknown'),
            'portal_payment_state': 'payment_failed' if payment_failed else 'paid_observed' if observed_paid else 'unverified',
            'payment_deadline_display':next(iter(deadlines)) if payment_failed and len(deadlines)==1 else None,
            'refund_status': ('refund_pending' if refund_pending else 'refund_expected_zero' if expected_refund
                              else 'unknown' if refund else 'none_displayed'),
            'card_last4': last4, 'price_components': components, 'paid_on': paid_on,
            'scheduled_for': _day(r'(?:결제 예정일)', payment) if scheduled else None,
            'source_namespace': 'aside-v1', 'snapshot_sha256': digest(capture['snapshot_text']),
            'observed_at': utc(capture['observed_at']), 'roles': roles, 'diagnostics': diagnostics}


DDL = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS capture_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capture_pages(
 id TEXT PRIMARY KEY,run_id TEXT,list_status TEXT,page_no INTEGER,observed_at TEXT,
 snapshot_sha256 TEXT,snapshot_text TEXT,booking_numbers_json TEXT,next_disabled INTEGER);
CREATE TABLE IF NOT EXISTS bookings(
 id TEXT PRIMARY KEY,provider TEXT NOT NULL,booking_number TEXT NOT NULL,
 product_type TEXT NOT NULL DEFAULT 'lodging',label TEXT,service_start_on TEXT,
 service_end_on TEXT,status TEXT NOT NULL DEFAULT 'unknown',UNIQUE(provider,booking_number));
CREATE TABLE IF NOT EXISTS source_observations(
 id TEXT PRIMARY KEY,booking_id TEXT REFERENCES bookings(id),observed_at TEXT NOT NULL,
 snapshot_sha256 TEXT NOT NULL,snapshot_text TEXT NOT NULL,envelope_json TEXT NOT NULL,
 payload_json TEXT NOT NULL,UNIQUE(booking_id,snapshot_sha256));
CREATE TABLE IF NOT EXISTS portal_projection(
 id TEXT PRIMARY KEY,booking_id TEXT UNIQUE NOT NULL REFERENCES bookings(id),
 observation_id TEXT NOT NULL REFERENCES source_observations(id),payload_json TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,roles_json TEXT NOT NULL,conflict_json TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS direct_source_records AS
 SELECT id,'agoda_portal_detail' AS source_kind,id AS source_key,source_sha256,payload_json,
 'aside-v1' AS redaction_version FROM portal_projection;
CREATE VIEW IF NOT EXISTS booking_source_evidence AS
 SELECT p.booking_id,p.id AS direct_source_record_id,r.value AS evidence_role,
 'observed' AS evidence_status,json_array_length(p.conflict_json) AS conflict_count,
 p.conflict_json FROM portal_projection p,json_each(p.roles_json) r;
CREATE TABLE IF NOT EXISTS mail_sources(
 message_id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,
 authenticated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mail_facts(
 message_id TEXT PRIMARY KEY REFERENCES mail_sources(message_id),provider TEXT,
 booking_number TEXT,fact_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS booking_mail_links(
 booking_id TEXT REFERENCES bookings(id),message_id TEXT REFERENCES mail_sources(message_id),
 PRIMARY KEY(booking_id,message_id));
'''


class CaptureStore:
    """원문 스냅샷을 보존하고 현재 조회용 자료만 갱신한다."""

    def __init__(self, path, *, account_key='aside-u0'):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(DDL)
        saved = self.conn.execute("SELECT value FROM capture_meta WHERE key='account_key'").fetchone()
        if saved and saved[0] != account_key:
            self.conn.close()
            raise ValueError('CAPTURE_ACCOUNT_MISMATCH')
        self.account_key = account_key
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO capture_meta VALUES('account_key',?)", (account_key,))
            self.conn.execute("INSERT OR IGNORE INTO capture_meta VALUES('schema_version',?)", (SCHEMA,))

    def close(self):
        self.conn.close()

    def _booking(self, booking):
        return 'aside-v1:' + digest(self.account_key)[:16] + ':agoda:' + booking

    def _ensure_booking(self, booking):
        identity = self._booking(booking)
        self.conn.execute('INSERT OR IGNORE INTO bookings(id,provider,booking_number) VALUES(?,?,?)',
                          (identity, 'agoda', booking))
        return identity

    def ingest(self, capture, *, run_id='default'):
        if capture.get('schema_version') != SCHEMA or capture.get('account_key') != self.account_key:
            raise ValueError('CAPTURE_SCHEMA_OR_ACCOUNT_MISMATCH')
        observed = utc(capture['observed_at'])
        snapshot = capture.get('snapshot_text')
        if not isinstance(snapshot, str) or not snapshot.strip():
            raise ValueError('CAPTURE_SNAPSHOT_REQUIRED')
        if '# note: interactive' in snapshot:
            raise ValueError('CAPTURE_FULL_SNAPSHOT_REQUIRED')
        sha = digest(snapshot)
        if capture['kind'] == 'list':
            numbers = capture.get('booking_numbers')
            actual = re.findall(r'heading "ID (\d{6,20})"', snapshot)
            if not isinstance(numbers, list) or set(actual) != set(numbers) or len(actual) != len(numbers):
                raise ValueError('CAPTURE_LIST_IDENTITY_MISMATCH')
            if capture.get('list_status') not in ('upcoming', 'completed', 'cancelled'):
                raise ValueError('CAPTURE_LIST_STATUS_INVALID')
            if not isinstance(capture.get('next_disabled'), bool):
                raise ValueError('CAPTURE_PAGE_END_REQUIRED')
            identity = digest(dump([run_id, capture['list_status'], capture['list_page'], sha]))
            with self.conn:
                inserted = self.conn.execute('INSERT OR IGNORE INTO capture_pages VALUES(?,?,?,?,?,?,?,?,?)',
                    (identity, run_id, capture['list_status'], capture['list_page'], observed, sha,
                     snapshot, dump(numbers), int(capture['next_disabled']))).rowcount
                for booking in numbers: self._ensure_booking(str(booking))
            return bool(inserted)
        fact = parse_detail(capture)
        identity = self._booking(fact['booking_number'])
        with self.conn:
            self._ensure_booking(fact['booking_number'])
            observation = digest(dump([identity, sha]))
            inserted = self.conn.execute('INSERT OR IGNORE INTO source_observations VALUES(?,?,?,?,?,?,?)',
                (observation, identity, observed, sha, snapshot, dump(capture), dump(fact))).rowcount
            # Older captures may arrive later on disk. Ordering is by observation time, never import order.
            if inserted:
                self._project(identity)
            self._link_mail(identity, fact['booking_number'])
        return bool(inserted)

    def _project(self, identity):
        rows = self.conn.execute('SELECT * FROM source_observations WHERE booking_id=? ORDER BY observed_at,id',
                                 (identity,)).fetchall()
        current = rows[-1]
        fact = json.loads(current['payload_json'])
        conflicts = []
        # Missing data may be enriched. Contradictory period, card or paid amount requires review.
        for field in ('service_start_on', 'service_end_on', 'card_last4'):
            values = {json.loads(row['payload_json']).get(field) for row in rows} - {None, ''}
            if len(values) > 1: conflicts.append({'field': field, 'reason': 'observations_disagree'})
        paid = set()
        for row in rows:
            other = json.loads(row['payload_json'])
            components = sorted((p['currency'], p['decimal_text']) for p in other['price_components'] if p['kind'] == 'paid_today')
            if components: paid.add(dump(components))
        if len(paid) > 1: conflicts.append({'field': 'paid_amount', 'reason': 'observations_disagree'})
        terminal = False
        for row in rows:
            status = json.loads(row['payload_json'])['reservation_status']
            if terminal and status in ('confirmed', 'completed'):
                conflicts.append({'field': 'status', 'reason': 'active_after_cancellation'})
            terminal |= status == 'cancelled'
        raw = dump(fact)
        self.conn.execute('INSERT INTO portal_projection VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
            'observation_id=excluded.observation_id,payload_json=excluded.payload_json,source_sha256=excluded.source_sha256,'
            'roles_json=excluded.roles_json,conflict_json=excluded.conflict_json',
            (identity, identity, current['id'], raw, digest(raw), dump(fact['roles']), dump(conflicts)))
        self.conn.execute('UPDATE bookings SET service_start_on=?,service_end_on=?,status=? WHERE id=?',
            (fact['service_start_on'], fact['service_end_on'], fact['reservation_status'], identity))

    def _link_mail(self, identity, booking):
        self.conn.execute("INSERT OR IGNORE INTO booking_mail_links SELECT ?,message_id FROM mail_facts "
                          "WHERE provider='agoda' AND booking_number=?", (identity, booking))

    def ingest_mail(self, directories):
        from app import ota_mail, ota_payments
        messages, inventory = ota_mail.load_messages_from(directories)
        if any(row.get('error') for row in inventory):
            raise ValueError('CAPTURE_MAIL_INVENTORY_INCOMPLETE')
        added = 0
        with self.conn:
            for message_id, message in messages.items():
                raw = dump(message)
                sha = digest(raw)
                existing = self.conn.execute('SELECT source_sha256 FROM mail_sources WHERE message_id=?',
                                             (message_id,)).fetchone()
                if existing and existing[0] != sha:
                    raise ValueError('CAPTURE_MAIL_CONTENT_CONFLICT')
                authenticated = bool(ota_mail.authenticated_headers(message,
                    ('agoda.com', 'agoda-messaging.com', 'booking.com', 'trip.com', 'trip.co.kr', 'klook.com')))
                added += self.conn.execute('INSERT OR IGNORE INTO mail_sources VALUES(?,?,?,?)',
                    (message_id, sha, raw, int(authenticated))).rowcount
                fact = ota_mail.extract_mail(message) or ota_payments._extract_signed_payment_message(message)
                if not fact: continue
                self.conn.execute('INSERT OR IGNORE INTO mail_facts VALUES(?,?,?,?)',
                    (message_id, fact['provider'], fact['booking_ref'], dump(fact)))
                if fact['provider'] == 'agoda':
                    identity = self._ensure_booking(fact['booking_ref'])
                    self._link_mail(identity, fact['booking_ref'])
        return added

    def summary(self):
        result = {name: self.conn.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                  for name in ('capture_pages', 'bookings', 'source_observations', 'portal_projection',
                               'mail_sources', 'booking_mail_links')}
        result['conflicting_bookings'] = self.conn.execute(
            "SELECT count(*) FROM portal_projection WHERE conflict_json!='[]'").fetchone()[0]
        result['full_capture_pages'] = self.conn.execute(
            "SELECT count(*) FROM capture_pages WHERE snapshot_text NOT LIKE '%# note: interactive%'").fetchone()[0]
        return result
