"""등록된 OTA 원문·메일·포털 근거를 단일 DB로 복사하고 기존 읽기와 비교한다."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ota_mail, ota_payments, ota_sources
from app.ota_store import OtaStore, encoded


def database_digest(store):
    result = {}
    for name, in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        columns = len(store.conn.execute('PRAGMA table_info("' + name + '")').fetchall())
        rows = store.conn.execute('SELECT * FROM "' + name + '" ORDER BY '
                                 + ','.join(str(i + 1) for i in range(columns)))
        digest = hashlib.sha256()
        for row in rows:
            normalized = [{'blob_sha256':hashlib.sha256(value).hexdigest()} if isinstance(value, bytes)
                          else value for value in row]
            digest.update(encoded(normalized).encode())
            digest.update(b'\n')
        result[name] = digest.hexdigest()
    return result


def consolidate(manifest_path, destination, *, extra_portals=(), capture_roots=()):
    manifest_path, destination = Path(manifest_path), Path(destination).resolve()
    sources = ota_sources.resolve_sources(manifest_path.parent, manifest_file=manifest_path)
    if sources.get('unified_database') or sources['missing']:
        raise ValueError('OTA_STORE_COMPLETE_LEGACY_INPUT_REQUIRED')
    if destination.exists():
        raise ValueError('OTA_STORE_NEW_DESTINATION_REQUIRED')
    baseline_mail, baseline_inventory = ota_mail.load_messages_from(sources['mail_directories'])
    baseline_events = ota_payments.build_ota_payment_events(sources)
    baseline_references = ota_mail.load_reference_documents(sources['reference_documents'])
    store = OtaStore(destination)
    try:
        for path in sources['mail_directories']:
            store.import_mail(path)
        for path in sources['portal_databases']:
            store.import_portal(path)
        for path in sources['reference_documents']:
            store.import_reference(path)
        unified = dict(mail_directories=[destination], portal_databases=[destination],
                       reference_documents=[destination])
        messages, inventory = ota_mail.load_messages_from([destination])
        events = ota_payments.build_ota_payment_events(unified)
        references = ota_mail.load_reference_documents([destination])
        checks = {'mail_exact': encoded(messages) == encoded(baseline_mail),
                  'mail_inventory_exact': encoded(inventory) == encoded(baseline_inventory),
                  'payment_events_exact': encoded(events) == encoded(baseline_events),
                  'references_exact': encoded(references) == encoded(baseline_references)}
        if not all(checks.values()):
            # 원문이 달라졌거나 같은 ID가 섞이면 운영 전환을 하지 않는다.
            return {'status':'HOLD', 'checks':checks, 'summary':store.summary()}
        before = database_digest(store)
        for path in sources['mail_directories']:
            store.import_mail(path)
        for path in sources['portal_databases']:
            store.import_portal(path)
        for path in sources['reference_documents']:
            store.import_reference(path)
        checks['repeat_all_rows_exact'] = before == database_digest(store)
        for path in extra_portals:
            store.import_portal(path)
        for root in capture_roots:
            for folder in ('pages', 'details'):
                for path in sorted((Path(root) / folder).glob('*.json')):
                    store.import_capture(path)
        checks['integrity'] = store.conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        candidate = {'schema_version':ota_sources.SCHEMA_VERSION, 'unified_database':str(destination)}
        return {'status':'PASS' if all(checks.values()) else 'HOLD', 'checks':checks,
                'summary':store.summary(), 'candidate_manifest':candidate,
                'legacy_event_count':len(baseline_events), 'mail_count':len(messages),
                'scope':'evidence_only_no_board_or_review_writes'}
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--extra-portal', type=Path, action='append', default=[])
    parser.add_argument('--capture-root', type=Path, action='append', default=[])
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = consolidate(args.manifest, args.db, extra_portals=args.extra_portal,
                         capture_roots=args.capture_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'candidate_manifest'}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
