"""Integrate the verified frozen candidate while the owned host is paused."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'docs/handoff/2026-10-01'
CONFIG = Path('D:/WebLedgerHost/config/reserve-source.json')
STATE = REPORTS / 'reserve-operational-integration.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    if os.environ.get('WEBLEDGER_MAINTENANCE') != 'RESERVE_CANDIDATE':
        raise RuntimeError('MAINTENANCE_CONTEXT_REQUIRED')
    files = load(REPORTS / 'reserve-candidate-hashes.json')['files']
    baseline = load(REPORTS / 'reserve-before-integration-hashes.json')['manifest']
    if '--rollback' in sys.argv:
        state = load(STATE)
        for name in reversed(state['copied_files']):
            target = ROOT / name
            if sha(target) != files[name]:
                raise RuntimeError('ROLLBACK_FOREIGN_CHANGE')
            if baseline[name]['exists']:
                original = REPORTS / 'reserve-before-integration' / name
                if sha(original) != baseline[name]['sha256']:
                    raise RuntimeError('ROLLBACK_BASELINE_MISMATCH')
                target.write_bytes(original.read_bytes())
            else:
                target.unlink()
        if state.get('config_created'):
            if sha(CONFIG) != state['config_sha256']:
                raise RuntimeError('ROLLBACK_CONFIG_FOREIGN_CHANGE')
            CONFIG.unlink()
        state['rolled_back'] = True
        STATE.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
        return
    backup = load(REPORTS / 'operational-backup-restore-evidence.json')
    recorded = datetime.datetime.fromisoformat(backup['recorded_at'])
    if (datetime.datetime.now(datetime.timezone.utc) - recorded).total_seconds() > 120:
        raise RuntimeError('FRESH_BACKUP_REQUIRED')
    if not all(backup[key] is True for key in ('live_state_unchanged',
            'all_database_tables_and_columns_compared', 'source_files_hash_compared',
            'restored_review_binding_equal')):
        raise RuntimeError('BACKUP_VERIFICATION_REQUIRED')
    delivery = load(REPORTS / 'reserve-final-delivery-preflight.json')
    if not delivery['success'] or not delivery['worker_final_report_received']:
        raise RuntimeError('FINAL_DELIVERY_REQUIRED')
    for name, expected in files.items():
        if sha(REPORTS / 'reserve-bunny-candidate' / name) != expected:
            raise RuntimeError('CANDIDATE_CHANGED')
        target = ROOT / name
        before = baseline[name]
        if target.exists() != before['exists']:
            raise RuntimeError('ORIGINAL_EXISTENCE_CHANGED')
        if before['exists'] and sha(target) != before['sha256']:
            raise RuntimeError('ORIGINAL_CHANGED')
    validation = load(REPORTS / 'reserve-protected-validation.json')
    if not validation['success'] or not validation['strict_validation']:
        raise RuntimeError('SOURCE_VALIDATION_REQUIRED')
    prepared = Path(validation['prepared_config'])
    config = load(prepared)
    if CONFIG.exists():
        raise RuntimeError('RUNTIME_CONFIG_ALREADY_EXISTS')
    if sha(Path(config['path'])) != config['file_sha256']:
        raise RuntimeError('SOURCE_CHANGED')
    sys.path.insert(0, str(ROOT))
    from ledger.domain.reservation_access_snapshot import parse_reservation_access_snapshot
    snapshot = parse_reservation_access_snapshot(Path(config['path']).read_bytes())
    if snapshot['digest'] != config['digest']:
        raise RuntimeError('SOURCE_DIGEST_CHANGED')
    state = dict(recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 backup_directory=backup['backup_directory'], copied_files=[],
                 config_created=False, config_sha256=sha(prepared),
                 actual_roster_applied=False, actual_employee_approved=False,
                 actual_cost_applied=False, success=False)
    def persist():
        STATE.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    persist()
    for name in files:
        (ROOT / name).write_bytes((REPORTS / 'reserve-bunny-candidate' / name).read_bytes())
        state['copied_files'].append(name)
        persist()
        if sha(ROOT / name) != files[name]:
            raise RuntimeError('INTEGRATED_HASH_MISMATCH')
    with CONFIG.open('xb') as stream:
        stream.write(prepared.read_bytes())
    state['config_created'] = True
    state['success'] = True
    persist()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)
