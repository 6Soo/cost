"""Owner-confirmed reading notes in one local JSONL file. Nothing here trains the model.

A rule is one of the fixed templates below, chosen and confirmed by the owner, so a note typed for one
slip (a date, an amount, a name) never becomes a rule. Free-text notes are kept as records only.
The file is set by WEBLEDGER_RECEIPT_LEARNING and lives outside the release folder. Muse reads the rules
as guidance; the attached photo stays the source of truth.
"""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path

RULES = {
    'SMALL_TICKET_MISSED': 'Small printed tickets, including Japanese boarding tickets, are separate receipts. Look for every small slip before answering.',
    'IDENTICAL_MERGED': 'Tickets with the same amount or date at different positions are separate receipts. Never combine them.',
    'OVERLAPPING_SLIPS': 'Overlapping slips are separate documents. Judge each one by its own visible edges and text.',
    'KOREAN_MERCHANT_MISSED': 'Copy a Korean merchant name exactly as printed. Leave it empty when it cannot be read.',
    'TOTAL_CONFUSED': 'Use the final amount paid. Ignore subtotals, tax lines, tendered amounts and change on the same slip.',
}
NOTE_TYPES = tuple(RULES) + ('OTHER',)
SCOPES = ('general', 'this_photo')
MAX_RULES = 3
MAX_NOTE = 240

_LOCK = threading.RLock()
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_CONTACT = re.compile(r'\S+@\S+')
_NUMBERS = re.compile(r'\d{3,}')


class LearningUnavailable(Exception):
    pass


def path():
    value = os.environ.get('WEBLEDGER_RECEIPT_LEARNING')
    return Path(value) if value else None


def enabled() -> bool:
    return path() is not None


def _clean(text, limit):
    return _CONTROL.sub(' ', str(text or '')).strip()[:limit]


def redact(text) -> str:
    """Notes are stored without contact details or long numbers, which may be card, booking or amount digits."""
    text = _CONTACT.sub('[연락처]', _clean(text, MAX_NOTE))
    return _NUMBERS.sub('#', text)


def _read(p: Path):
    """Valid records, plus the raw lines that could not be read. Unreadable lines are kept as they are on write."""
    try:
        lines = p.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return [], []
    records, bad = [], []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad.append(line)
            continue
        if isinstance(record, dict) and isinstance(record.get('id'), str):
            records.append(record)
        else:
            bad.append(line)
    return records, bad


def _write(p: Path, records, bad=()) -> None:
    tmp = p.with_name(f'{p.name}.{uuid.uuid4().hex}.tmp')
    body = [json.dumps(r, ensure_ascii=False) for r in records] + list(bad)
    tmp.write_text(''.join(line + '\n' for line in body), encoding='utf-8')
    os.replace(tmp, p)


def add_feedback(*, note_type: str, scope: str, note: str = '') -> dict:
    p = path()
    if p is None:
        raise LearningUnavailable('LEARNING_DISABLED')
    if note_type not in NOTE_TYPES:
        raise ValueError('NOTE_TYPE_INVALID')
    if scope not in SCOPES:
        raise ValueError('SCOPE_INVALID')
    text = redact(note)
    key = hashlib.sha256(json.dumps([note_type, scope, text], ensure_ascii=False).encode('utf-8')).hexdigest()
    with _LOCK:
        records, bad = _read(p)
        if any(r.get('key') == key for r in records):
            return {'status': 'duplicate'}
        rule_type = note_type if (scope == 'general' and note_type in RULES) else None
        if rule_type is None:
            status = 'recorded'
        elif any(r.get('status') == 'active' and r.get('rule_type') == rule_type for r in records):
            status = 'merged'
        else:
            status = 'active'
        record = {'id': uuid.uuid4().hex[:12], 'key': key,
                  'created': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                  'type': note_type, 'scope': scope, 'note': text, 'confirmed': True,
                  'rule_type': rule_type, 'rule': RULES[rule_type] if status == 'active' else None,
                  'status': status, 'applied': 0}
        records.append(record)
        _write(p, records, bad)
        return {'status': status, 'id': record['id']}


def list_records() -> list:
    p = path()
    if p is None:
        return []
    with _LOCK:
        records, _ = _read(p)
    return [{k: r.get(k) for k in ('id', 'created', 'type', 'scope', 'note', 'rule', 'status', 'applied')}
            for r in records]


def set_status(record_id: str, action: str) -> dict:
    p = path()
    if p is None:
        raise LearningUnavailable('LEARNING_DISABLED')
    if action not in ('disable', 'enable', 'delete'):
        raise ValueError('ACTION_INVALID')
    with _LOCK:
        records, bad = _read(p)
        matches = [r for r in records if r['id'] == record_id]
        if not matches:
            raise KeyError('RECORD_NOT_FOUND')
        record = matches[0]
        if action == 'delete':
            records.remove(record)
            _write(p, records, bad)
            return {'status': 'deleted'}
        if not record.get('rule_type'):
            raise ValueError('NOT_A_RULE')
        if action == 'disable':
            if record.get('status') == 'active':
                record['status'] = 'disabled'
        else:
            if any(r is not record and r.get('status') == 'active' and r.get('rule_type') == record['rule_type']
                   for r in records):
                raise ValueError('RULE_CONFLICT')
            record['status'] = 'active'
            record['rule'] = RULES[record['rule_type']]
        _write(p, records, bad)
        return {'status': record['status']}


def rules_for_prompt(*, record_use: bool = False) -> list:
    """The newest active rule for each kind, at most MAX_RULES. A missing or unreadable file gives no rules."""
    p = path()
    if p is None:
        return []
    try:
        with _LOCK:
            records, bad = _read(p)
            active = [r for r in records if r.get('status') == 'active' and r.get('rule_type') in RULES]
            active.sort(key=lambda r: str(r.get('created', '')), reverse=True)
            chosen, kinds = [], set()
            for r in active:
                if r['rule_type'] in kinds:
                    continue
                kinds.add(r['rule_type'])
                chosen.append(r)
                if len(chosen) == MAX_RULES:
                    break
            if record_use and chosen:
                ids = {r['id'] for r in chosen}
                for r in records:
                    if r['id'] in ids:
                        r['applied'] = int(r.get('applied') or 0) + 1
                _write(p, records, bad)
            return [RULES[r['rule_type']] for r in chosen]
    except (OSError, ValueError, UnicodeError):
        return []


def guidance(*, rules, expected_count=None, known=(), hint=None):
    lines = []
    if rules:
        lines.append('Notes from earlier owner corrections (guidance only; the attached photo is the source of truth, '
                     'and nothing that is not visible in it may be added):')
        lines += [f'- {rule}' for rule in rules]
    if expected_count:
        lines.append(f'The owner counts {expected_count} receipts on this photo. Look for any not in the list below; '
                     'do not list the same receipt twice.')
    if known:
        lines.append('Already found (do not repeat these):')
        lines += [f'- {_clean(item, 160)}' for item in known]
    if hint:
        lines.append('Owner note for this photo: ' + _clean(hint, 200))
    return '\n'.join(lines) or None
