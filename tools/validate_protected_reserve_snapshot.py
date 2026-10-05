"""Validate the explicit protected export and prepare inactive source config."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ledger.domain.reservation_access_snapshot import parse_reservation_access_snapshot

reports = ROOT / 'docs/handoff/2026-10-01'
result = {'read_only': True, 'operationally_applied': False, 'config_activated': False,
          'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
try:
    exported = json.loads((reports / 'reserve-protected-export.json').read_text(encoding='utf-8-sig'))
    if exported.get('success') is not True:
        raise ValueError('EXPORT_NOT_SUCCESSFUL')
    path = Path(exported['protected_path']).resolve()
    protected_root = Path('D:/WebLedgerHost/review/reservation-access').resolve()
    if path.parent != protected_root:
        raise ValueError('SOURCE_PATH_OUTSIDE_PROTECTED_ROOT')
    raw = path.read_bytes()
    physical_hash = hashlib.sha256(raw).hexdigest()
    if physical_hash != exported['file_sha256']:
        raise ValueError('EXPORT_HASH_MISMATCH')
    snapshot = parse_reservation_access_snapshot(raw)
    keys = {key for person in snapshot['persons'] for key in person['assignments']}
    conn = sqlite3.connect('file:D:/WebLedgerHost/data/board.sqlite?mode=ro', uri=True)
    try:
        targets = {row[0] for row in conn.execute('SELECT tab_id FROM trip_tabs WHERE deleted=0 AND archived=0')}
        result['database_integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        conn.close()
    config = {'path': str(path), 'file_sha256': physical_hash, 'digest': snapshot['digest']}
    prepared = protected_root / ('source-config-' + physical_hash[:16] + '.json')
    payload = (json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if prepared.exists():
        if prepared.read_bytes() != payload:
            raise ValueError('PREPARED_CONFIG_CONFLICT')
    else:
        with prepared.open('xb') as stream:
            stream.write(payload)
    result.update(success=True, strict_validation=True, persons=len(snapshot['persons']),
                  active_persons=sum(person['is_active'] for person in snapshot['persons']),
                  unique_source_identifiers=len(keys), available_targets=len(targets),
                  exact_target_matches=len(keys & targets), explicit_selection_required=len(keys - targets),
                  file_sha256=physical_hash, semantic_digest=snapshot['digest'],
                  source_revision=snapshot['snapshot_revision'], prepared_config=str(prepared))
except Exception as exc:
    result.update(success=False, error_type=type(exc).__name__)
(reports / 'reserve-protected-validation.json').write_bytes((json.dumps(result, indent=2) + '\n').encode('utf-8'))
if not result.get('success'):
    sys.exit(1)
