"""Read-only T1..T4 candidate measurement; matches are leads, never links."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import sqlite3
from .guard import normalize_dates

PROVIDERS = ('agoda', 'booking', 'trip.com', 'skyticket', 'klook', 'nice')
AMOUNTS = re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?)(?![\d.])')


def provider(text):
    return next((p for p in PROVIDERS if p in str(text).lower()), 'other')


def number(value):
    try:
        return Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        return None


def iso(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def conditions(row, evidence, trip=None):
    text = '\n'.join(str(evidence.get(k) or '') for k in ('subject', 'sender', 'sent_date', 'body')).lower()
    nums = {number(n) for n in AMOUNTS.findall(text)}
    prov = provider(row.get('merchant_normalized') or row.get('merchant'))
    same = prov != 'other' and prov in text
    card = iso(row.get('approval_date') or row.get('posting_date'))
    try:
        sent = parsedate_to_datetime(evidence.get('sent_date') or '').date()
    except (ValueError, TypeError, OverflowError):
        sent = None
    krw, foreign = number(row.get('amount_krw')), number(row.get('foreign_amount'))
    currency = str(row.get('foreign_currency') or '').lower()
    # KRW billing and foreign principal are separate amount/currency pairs.
    t1 = bool((krw is not None and krw in nums and re.search(r'\bkrw\b|원|₩', text)) or
              (foreign is not None and currency and foreign in nums and re.search(r'\b' + re.escape(currency) + r'\b', text)))
    start, end = iso((trip or {}).get('starts_on')), iso((trip or {}).get('ends_on'))
    dates = [iso(d) for d in normalize_dates(text)]
    return dict(T1=t1,
                T2=bool(same and card and sent and card-timedelta(days=3) <= sent <= card+timedelta(days=1)),
                T3=bool(same and card and sent and card-timedelta(days=3) <= sent <= card+timedelta(days=3)
                        and krw is not None and any(1000 <= abs(n-krw) <= 10000 for n in nums)),
                T4=bool(same and start and end and any(d and start <= d <= end for d in dates)))


def measure(rows, evidence, trips):
    details = []
    for row in rows:
        if (row.get('approval_date') or row.get('posting_date') or '') < '2026-04-01':
            continue
        counts = Counter()
        for entry in evidence:
            counts.update(k for k, matched in conditions(row, entry, trips.get(row.get('trip_id'))).items() if matched)
        details.append(dict(matches=dict(counts)))
    unions = {name: sum(any(d['matches'].get(k) for k in keys) for d in details)
              for name, keys in [('T1', ['T1']), ('T1_T2', ['T1', 'T2']),
                                 ('T1_T2_T3', ['T1', 'T2', 'T3']), ('all', ['T1', 'T2', 'T3', 'T4'])]}
    return dict(candidates=len(details), unions=unions, none=len(details)-unions['all'], details=details)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True)
    parser.add_argument('--cases', required=True, help='Private JSON: rows and trips')
    args = parser.parse_args()
    data = json.loads(Path(args.cases).read_text(encoding='utf-8-sig'))
    with sqlite3.connect(Path(args.index).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        result = measure(data['rows'], [dict(r) for r in conn.execute('SELECT * FROM evidence')], data['trips'])
    print(json.dumps(result))
