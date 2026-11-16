"""Source-bound attribution from the owner's manually entered historical ledger.

The protected review manifest identifies the original workbook and its selected
sheet mappings, not transaction answers. Matching is bijective across the entire
reviewed workbook and source-card population; a date/amount alone is never proof.
"""
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata

import openpyxl

from .google_expense_rows import day, read


KIND = 'google_manual_expense'


def _text(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', str(value or '')).casefold())


def match(cards, originals, *, digest):
    """Return unique exact source-row attributions; ambiguous candidates stay out."""
    by_key = defaultdict(list)
    for row in cards:
        by_key[(row.get('approval_date'), row.get('amount_krw'), row.get('issuer'))].append(row)
    candidates, reverse = defaultdict(list), defaultdict(list)
    for original in originals:
        cells = original['cells']
        date = day(cells.get('B'), original['year'])
        payee, issuer = _text(cells.get('C')), str(cells.get('G') or '').strip()
        amount = original['amount']
        if not date or len(payee) < 4 or amount <= 0:
            continue
        key = (original['sheet'], original['row'])
        for card in by_key.get((date, amount, issuer), []):
            merchant = _text(card.get('merchant'))
            if len(merchant) < 4 or not (payee in merchant or merchant in payee):
                continue
            tid = card['transaction_id']
            candidates[tid].append(original)
            reverse[key].append(tid)
    result = {}
    for card in cards:
        tid = card['transaction_id']
        options = candidates[tid]
        if (len(options) != 1 or len(reverse[(options[0]['sheet'], options[0]['row'])]) != 1
                or not card.get('source_hash') or card.get('transaction_direction') != 'purchase'
                or any(card.get(k) for k in ('parse_error', 'duplicate_of', 'conflict_reason'))):
            continue
        original = options[0]
        result[tid] = dict(kind=KIND, source_hash=card['source_hash'], trip_id=original['trip_id'],
            evidence_digest=digest, google_sheet=original['sheet'], google_row=original['row'],
            basis=f"GOOGLE_MANUAL_ROW · {original['sheet']}!{original['row']} · 원본 일자·금액·지급처·발급사 일치")
    return result


def load(conn, trips, directory):
    """Revalidate an immutable, privately reviewed original on every use; read-only."""
    root = Path(directory).resolve()
    manifest = root / 'manifest.json'
    if not manifest.exists():
        return {}
    def fail():
        raise ValueError('MANUAL_GOOGLE_EVIDENCE_INVALID')
    if manifest.stat().st_size > 2 * 1024 * 1024:
        fail()
    raw = manifest.read_bytes()
    data = json.loads(raw)
    reviewer = data.get('reviewer') or {}
    if (data.get('version') != 1 or reviewer.get('kind') != 'ai_review'
            or any(not isinstance(reviewer.get(k), str) or not reviewer[k].strip()
                   for k in ('provider', 'model', 'run_id'))):
        fail()
    source = data.get('source') or {}
    workbook_path = (root / source.get('path', '')).resolve()
    from .google_authority import SPREADSHEET_IDS
    if (source.get('role') != 'archive' or source.get('spreadsheet_id') != SPREADSHEET_IDS['archive']
            or not workbook_path.is_relative_to(root) or not workbook_path.is_file()
            or workbook_path.stat().st_size > 64 * 1024 * 1024):
        fail()
    content = workbook_path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    if content_hash != source.get('sha256'):
        fail()
    mappings = data.get('sheets')
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 100:
        fail()
    valid = {t.get('trip_id') or t.get('tab_id'): t for t in trips}
    originals, seen = [], set()
    values = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    formulas = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    try:
        for mapping in mappings:
            sheet, target = mapping.get('sheet'), mapping.get('trip_id')
            trip = valid.get(target)
            quarter = target in ('quarter:2026:1', 'quarter:2026:2')
            if (sheet in seen or sheet not in values.sheetnames or mapping.get('year') != 2026
                    or (quarter and sheet != target[-1] + '분기_기타비용')
                    or (not quarter and (not trip or trip.get('deleted')
                        or not '2026-01-01' <= (trip.get('starts_on') or '') < '2026-06-30'
                        or sheet != trip.get('display_key')))):
                fail()
            seen.add(sheet)
            parsed = read(formulas[sheet], values[sheet])
            if parsed['status'] != 'readable':
                fail()
            originals.extend(dict(row, sheet=sheet, trip_id=target, year=2026) for row in parsed['rows'])
        expected = {sheet for sheet in values.sheetnames if sheet in ('1분기_기타비용', '2분기_기타비용')
                    or (re.match(r'^\d{4}_\S', sheet) and '0101' <= sheet[:4] < '0630')}
        if seen != expected:
            # Omitting a historical sheet must not hide a competing original row.
            fail()
    finally:
        values.close()
        formulas.close()
    from .automatic_classification import _read
    digest = hashlib.sha256(raw + content_hash.encode()).hexdigest()
    return match(_read(conn), originals, digest=digest)


def choose(row, fact, *, valid, recorded=False, reconsider=False, refund=False):
    """No source/manual/refund bypass, no invented booking period or payment link."""
    from .classification_provenance import CODE_SOURCES
    calendar_rule = row.get('classification_source') == 'rule' and any(
        marker in (row.get('classification_basis') or '') for marker in ('AUTO_INFERRED', 'AUTO_TRIP_INFERRED'))
    if (not fact or fact.get('kind') != KIND or not row.get('source_hash')
            or fact.get('source_hash') != row['source_hash'] or refund
            or row.get('transaction_direction') != 'purchase'
            or type(row.get('amount_krw')) is not int or row['amount_krw'] <= 0
            or not (row.get('classification_source') in (*CODE_SOURCES, 'owner_card_residual') or calendar_rule)
            or row.get('decided_at') is not None or (recorded and not reconsider)):
        return None
    target = fact.get('trip_id')
    quarter = target in ('quarter:2026:1', 'quarter:2026:2')
    if not quarter and target not in valid:
        return None
    chosen = dict(row)
    from .automatic_classification import infer_item
    if quarter:
        chosen['item'] = '분기 기타비용'
    elif not chosen.get('item') or chosen['item'] == '분기 기타비용':
        chosen['item'] = infer_item(dict(chosen, item=''))[0]
    chosen.update(classification_state='classified', classification_source='inference',
                  classification_basis=fact['basis'], display_tab_id=target,
                  trip_id='' if quarter else target)
    return chosen
