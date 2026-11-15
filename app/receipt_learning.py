"""Lessons that the reading model wrote during a re-analysis, kept in one local JSONL file.

A lesson is saved only after the owner registers a receipt that the re-analysis found. It must pass a check that
keeps it general: no digits, no contact details, no merchant name from the photo and no customer or payment
wording. A lesson that does not pass is not saved, and nothing is edited to make it pass. The file is set by
WEBLEDGER_RECEIPT_LEARNING. The reading model gets saved notes as guidance; the attached photo stays the source of truth.
"""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path

MAX_NOTES = 3
MAX_NOTE = 200
MAX_REQUEST = 300

_LOCK = threading.RLock()
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_CONTACT = re.compile(r'\S+@\S+')
_NUMBER_ANY = re.compile(r'\d')


def path():
    value = os.environ.get('WEBLEDGER_RECEIPT_LEARNING')
    return Path(value) if value else None


def enabled() -> bool:
    return path() is not None


def clean(text, limit=MAX_REQUEST) -> str:
    """The owner's request as typed, without control characters. Used for the current analysis only."""
    return _CONTROL.sub(' ', str(text or '')).strip()[:limit]


_DENIED = ('고객', '예약', '카드', '계좌', '여권', 'passport', 'card', 'customer')
LESSON_MIN = 8


def valid_lesson(text, names=()) -> bool:
    """A lesson is kept only as a general instruction: no digits (amounts, dates, numbers), no contact details,
    no merchant name from the photo and no customer or payment wording. Anything else is refused, not edited."""
    if not isinstance(text, str):
        return False
    t = _clean_lesson(text)
    if not LESSON_MIN <= len(t) <= MAX_NOTE or _NUMBER_ANY.search(t) or _CONTACT.search(t):
        return False
    lowered = t.lower()
    if any(word in lowered for word in _DENIED):
        return False
    return not any(isinstance(n, str) and len(n.strip()) >= 2 and n.strip().lower() in lowered for n in names)


def _clean_lesson(text) -> str:
    return _CONTROL.sub(' ', text).strip()


def _read(p: Path):
    """Valid notes, plus the raw lines that could not be read. Unreadable lines are kept as they are on write."""
    try:
        lines = p.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return [], []
    notes, bad = [], []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            bad.append(line)
            continue
        if isinstance(record, dict) and isinstance(record.get('id'), str) and isinstance(record.get('text'), str):
            notes.append(record)
        else:
            bad.append(line)
    return notes, bad


def _write(p: Path, notes, bad=()) -> None:
    tmp = p.with_name(f'{p.name}.{uuid.uuid4().hex}.tmp')
    body = [json.dumps(n, ensure_ascii=False) for n in notes] + list(bad)
    tmp.write_text(''.join(line + '\n' for line in body), encoding='utf-8')
    os.replace(tmp, p)


def remember_lesson(lesson: str, *, names=()) -> dict:
    """Stores a lesson that was written with a re-analysis and checked. Called only after a registration."""
    p = path()
    if p is None:
        return {'status': 'disabled'}
    if not valid_lesson(lesson, names):
        return {'status': 'refused'}
    text = _clean_lesson(lesson)
    key = hashlib.sha256(text.encode('utf-8')).hexdigest()
    with _LOCK:
        notes, bad = _read(p)
        if any(n.get('key') == key for n in notes):
            return {'status': 'duplicate'}
        note = {'id': uuid.uuid4().hex[:12], 'key': key, 'kind': 'lesson',
                'created': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'text': text}
        notes.append(note)
        _write(p, notes, bad)
    return {'status': 'saved', 'id': note['id']}


def list_notes() -> list:
    p = path()
    if p is None:
        return []
    with _LOCK:
        notes, _ = _read(p)
    return [{'id': n['id'], 'created': n.get('created'), 'text': n['text']} for n in notes]


def delete_note(note_id: str) -> dict:
    p = path()
    if p is None:
        return {'status': 'disabled'}
    with _LOCK:
        notes, bad = _read(p)
        kept = [n for n in notes if n['id'] != note_id]
        if len(kept) == len(notes):
            raise KeyError('NOTE_NOT_FOUND')
        _write(p, kept, bad)
    return {'status': 'deleted'}


def notes_for_prompt() -> list:
    """The newest few distinct notes. A missing or unreadable file gives none, and reading still runs."""
    p = path()
    if p is None:
        return []
    try:
        with _LOCK:
            notes, _ = _read(p)
    except (OSError, UnicodeError):
        return []
    notes.sort(key=lambda n: str(n.get('created', '')), reverse=True)
    chosen, seen = [], set()
    for note in notes:
        if note['text'] in seen:
            continue
        seen.add(note['text'])
        chosen.append(note['text'])
        if len(chosen) == MAX_NOTES:
            break
    return chosen


def guidance(*, notes=(), known=(), feedback=None):
    lines = []
    if notes:
        lines.append('Notes from earlier owner feedback (guidance only; the attached photo is the source of truth, '
                     'and add nothing that is not visible in it):')
        lines += [f'- {clean(note, MAX_NOTE)}' for note in notes]
    if known:
        lines.append('Already found (do not repeat these):')
        lines += [f'- {clean(item, 160)}' for item in known]
    if feedback:
        lines.append('Owner feedback for this photo: ' + clean(feedback, MAX_REQUEST))
    return '\n'.join(lines) or None
