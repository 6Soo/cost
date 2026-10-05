"""Copy only accepted navigation files while the owned writers are paused."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'docs/handoff/2026-10-01'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prefix = sys.argv[1] if len(sys.argv) == 2 else 'reserve-navigation'
    contexts = {'reserve-navigation': 'RESERVE_NAVIGATION', 'google-cookie-jar': 'GOOGLE_COOKIE_JAR', 'reserve-mobile': 'RESERVE_MOBILE', 'owner-metadata': 'OWNER_METADATA', 'export-assignee-guidance': 'EXPORT_ASSIGNEE_GUIDANCE'}
    if prefix not in contexts or os.environ.get('WEBLEDGER_MAINTENANCE') != contexts[prefix]:
        raise RuntimeError('MAINTENANCE_CONTEXT_REQUIRED')
    backup = load(REPORTS / 'operational-backup-restore-evidence.json')
    age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(backup['recorded_at'])
    if age.total_seconds() > 120 or not backup['live_state_unchanged'] or not backup['restored_review_binding_equal']:
        raise RuntimeError('FRESH_VERIFIED_BACKUP_REQUIRED')
    accepted = load(REPORTS / (prefix + '-candidate-hashes.json'))
    if not accepted['parent_tests_passed']:
        raise RuntimeError('PARENT_ACCEPTANCE_REQUIRED')
    baseline = load(REPORTS / (prefix + '-before-integration-hashes.json'))
    files = accepted['files']
    if set(files) != set(baseline):
        raise RuntimeError('MANIFEST_SCOPE_MISMATCH')
    for name, digest in files.items():
        target = ROOT / name
        if sha(REPORTS / (prefix + '-candidate') / name) != digest:
            raise RuntimeError('CANDIDATE_CHANGED')
        before = baseline[name]
        if target.exists() != before['exists'] or (target.exists() and sha(target) != before['sha256']):
            raise RuntimeError('ORIGINAL_CHANGED')
    copied = []
    try:
        for name in files:
            (ROOT / name).write_bytes((REPORTS / (prefix + '-candidate') / name).read_bytes())
            copied.append(name)
            if sha(ROOT / name) != files[name]:
                raise RuntimeError('COPY_HASH_MISMATCH')
    except Exception:
        for name in reversed(copied):
            target = ROOT / name
            if sha(target) != files[name]:
                raise RuntimeError('ROLLBACK_FOREIGN_CHANGE')
            if baseline[name]['exists']:
                original = REPORTS / (prefix + '-before-integration') / name
                if sha(original) != baseline[name]['sha256']:
                    raise RuntimeError('ROLLBACK_BASELINE_CHANGED')
                target.write_bytes(original.read_bytes())
            else:
                target.unlink()
        raise
    result = dict(success=True, recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  files=files, backup_directory=backup['backup_directory'],
                  source_config_changed=False, actual_link_save=False,
                  actual_roster_applied=False, actual_employee_approved=False, actual_cost_applied=False)
    (REPORTS / (prefix + '-operational-integration.json')).write_bytes(
        (json.dumps(result, indent=2) + '\n').encode())


if __name__ == '__main__':
    main()
