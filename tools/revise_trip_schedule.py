"""Preview/apply/undo an owner-confirmed end-date revision. Never opens a database.

Active authority keeps one record per trip. Immutable evidence and the verified
receipt retain the superseded record and original authority bytes for recovery.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ledger.domain.direct_trip_schedule_authority import load_document, validate_document


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plan_revision(authority: Path, evidence_root: Path, change: dict) -> dict:
    required = {'trip_code', 'ends_on', 'rule_id', 'decided_on', 'reason'}
    if set(change) != required or any(not isinstance(v, str) or not v.strip() for v in change.values()):
        raise ValueError('SCHEDULE_CHANGE_INVALID')
    dt.date.fromisoformat(change['decided_on'])
    original = authority.read_bytes()
    records, loaded_sha256 = load_document(authority)
    if loaded_sha256 != digest(original):
        raise ValueError('AUTHORITY_CHANGED')
    matches = [r for r in records if r.trip_code == change['trip_code']]
    if len(matches) != 1 or not matches[0].is_authoritative:
        raise ValueError('AUTHORITATIVE_TRIP_REQUIRED')
    old = matches[0].as_dict()
    schedule = {k: v for k, v in old.items() if k not in ('source_locator', 'source_sha256')}
    schedule.update(ends_on=change['ends_on'], authority_kind='user_confirmed_schedule')
    evidence = encoded({'schema_version': 'owner-trip-schedule-v1', 'schedule': schedule,
                        'basis': {**change, 'supersedes': old}})
    source = evidence_root.resolve() / ('owner-schedule-' + digest(evidence)[:24] + '.json')
    new = {**schedule, 'source_locator': str(source) + '#schedule', 'source_sha256': digest(evidence)}
    document = json.loads(original)
    document['records'] = [new if r['trip_code'] == old['trip_code'] else r for r in document['records']]
    validate_document(document)
    return {'before': original, 'after': encoded(document), 'evidence': evidence,
            'source': source, 'old': old, 'new': new, 'decision': change}


def atomic_write(path: Path, raw: bytes):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def revision_lock(authority: Path):
    lock = authority.with_name(authority.name + '.revision.lock')
    stream = lock.open('x', encoding='utf-8')
    try:
        yield
    finally:
        stream.close()
        lock.unlink()


def apply_revision(authority: Path, plan: dict, receipt: Path, expected_sha256: str):
    if digest(plan['before']) != expected_sha256:
        raise ValueError('PREVIEW_SHA_MISMATCH')
    with revision_lock(authority):
        if authority.read_bytes() != plan['before']:
            raise ValueError('AUTHORITY_CHANGED')
        receipt.mkdir(parents=True, exist_ok=False)
        (receipt / 'authority.before.json').write_bytes(plan['before'])
        (receipt / 'authority.after.json').write_bytes(plan['after'])
        # Read/parse the recovery copy independently before any authority mutation.
        load_document(receipt / 'authority.before.json')
        load_document(receipt / 'authority.after.json')
        if (receipt / 'authority.before.json').read_bytes() != authority.read_bytes():
            raise ValueError('BACKUP_RESTORE_VERIFICATION_FAILED')
        manifest = {'schema': 'trip-schedule-revision-v1', 'authority': str(authority.resolve()),
                    'before_sha256': digest(plan['before']), 'after_sha256': digest(plan['after']),
                    'decision': plan['decision'], 'old': plan['old'], 'new': plan['new'],
                    'created_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        (receipt / 'manifest.json').write_bytes(encoded(manifest))
        source = plan['source']
        source.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open('xb') as stream:
                stream.write(plan['evidence'])
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if source.read_bytes() != plan['evidence']:
                raise ValueError('EVIDENCE_CONFLICT')
        if digest(source.read_bytes()) != plan['new']['source_sha256']:
            raise ValueError('EVIDENCE_DIGEST_MISMATCH')
        if authority.read_bytes() != plan['before']:
            raise ValueError('AUTHORITY_CHANGED')
        atomic_write(authority, plan['after'])
        (receipt / 'applied.json').write_bytes(encoded({'status': 'applied'}))


def rollback_revision(authority: Path, receipt: Path, *, apply: bool = False):
    manifest = json.loads((receipt / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['schema'] != 'trip-schedule-revision-v1' or manifest['authority'] != str(authority.resolve()):
        raise ValueError('RECEIPT_AUTHORITY_MISMATCH')
    before = (receipt / 'authority.before.json').read_bytes()
    after = (receipt / 'authority.after.json').read_bytes()
    if digest(before) != manifest['before_sha256'] or digest(after) != manifest['after_sha256']:
        raise ValueError('RECEIPT_DIGEST_MISMATCH')
    load_document(receipt / 'authority.before.json')
    if authority.read_bytes() != after:
        raise ValueError('AUTHORITY_CHANGED')
    if apply:
        with revision_lock(authority):
            if authority.read_bytes() != after:
                raise ValueError('AUTHORITY_CHANGED')
            atomic_write(authority, before)
            (receipt / 'rolled-back.json').write_bytes(encoded({
                'status': 'rolled_back', 'created_at': dt.datetime.now(dt.timezone.utc).isoformat()}))
    return {'status': 'rolled_back' if apply else 'rollback_preview', 'trip_code': manifest['old']['trip_code']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authority', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--change', type=Path, help='JSON: trip_code, ends_on, rule_id, decided_on, reason')
    parser.add_argument('--receipt', type=Path, help='New private directory for verified recovery copies')
    parser.add_argument('--expected-sha256', help='Authority SHA256 from the reviewed preview')
    parser.add_argument('--rollback', type=Path, help='Receipt directory; preview unless --apply')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            result = rollback_revision(args.authority, args.rollback, apply=args.apply)
        else:
            if not args.evidence_root or not args.change:
                raise ValueError('CHANGE_AND_EVIDENCE_ROOT_REQUIRED')
            plan = plan_revision(args.authority, args.evidence_root,
                                 json.loads(args.change.read_text(encoding='utf-8-sig')))
            if args.apply:
                if not args.receipt or not args.expected_sha256:
                    raise ValueError('RECEIPT_AND_PREVIEW_SHA_REQUIRED')
                apply_revision(args.authority, plan, args.receipt, args.expected_sha256)
            result = {'status': 'applied' if args.apply else 'preview',
                      'trip_code': plan['old']['trip_code'], 'old_end': plan['old']['ends_on'],
                      'new_end': plan['new']['ends_on'], 'before_sha256': digest(plan['before']),
                      'after_sha256': digest(plan['after'])}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
