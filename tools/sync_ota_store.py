"""새 OTA 원문을 단일 DB에 원자적으로 추가한다. 장부·확정 저장소는 쓰지 않는다."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ota_mail
from app.ota_store import OtaStore, is_store
from tools.consolidate_ota_sources import database_digest


def mail_input_error(directory):
    """Validate explicit mail inputs before opening a writer; return only safe codes.

    An empty responses list is empty input, not malformed mail. A nonempty batch
    must contain only structurally valid messages; never silently skip bad rows.
    Provider recognition is deliberately not required for raw evidence storage.
    """
    try:
        if not directory.is_dir():
            return 'OTA_STORE_MAIL_INPUT_INVALID'
        paths = sorted(directory.glob('gmail*.json'))
        if not paths:
            return 'OTA_STORE_MAIL_NO_SUPPORTED_FILES'
        for path in paths:
            batch = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(batch, dict) or not isinstance(batch.get('responses'), list):
                return 'OTA_STORE_MAIL_INPUT_INVALID'
            for message in batch['responses']:
                if (not isinstance(message, dict)
                        or not isinstance(message.get('id'), str) or not message['id'].strip()
                        or not isinstance(message.get('payload'), dict)):
                    return 'OTA_STORE_MAIL_INPUT_INVALID'
                headers = message['payload'].get('headers', [])
                if not isinstance(headers, list) or any(
                        not isinstance(header, dict)
                        or not isinstance(header.get('name'), str)
                        or not isinstance(header.get('value'), str) for header in headers):
                    return 'OTA_STORE_MAIL_INPUT_INVALID'
        messages, inventory = ota_mail.load_messages_from([directory])
        if any(row.get('error') for row in inventory):
            return 'OTA_STORE_MAIL_INPUT_INVALID'
        if not messages:
            return 'OTA_STORE_MAIL_NO_MESSAGES'
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        # Parser/IO exceptions may contain customer paths, IDs or body fragments.
        return 'OTA_STORE_MAIL_INPUT_INVALID'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--capture-root', type=Path, action='append', default=[])
    parser.add_argument('--mail-directory', type=Path, action='append', default=[])
    parser.add_argument('--portal-database', type=Path, action='append', default=[])
    parser.add_argument('--reference-document', type=Path, action='append', default=[])
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    for directory in args.mail_directory:
        error = mail_input_error(directory)
        if error:
            parser.error(error)
    if not is_store(args.db):
        parser.error('기존 통합 OTA DB가 필요합니다')
    if args.backup.exists() or args.backup.resolve() == args.db.resolve():
        parser.error('새 복구 사본 경로가 필요합니다')
    store = OtaStore(args.db)
    try:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        expected = database_digest(store)
        with sqlite3.connect(args.backup) as backup:
            store.conn.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('OTA_STORE_BACKUP_INTEGRITY_FAILED')
        restored = OtaStore(args.backup)
        try:
            if database_digest(restored) != expected:
                raise ValueError('OTA_STORE_BACKUP_ROWS_DIFFER')
        finally:
            restored.close()
        store.conn.execute('BEGIN IMMEDIATE')
        before = store.summary()
        for folder in args.mail_directory:
            store.import_mail(folder)
        for database in args.portal_database:
            store.import_portal(database)
        for document in args.reference_document:
            store.import_reference(document)
        for root in args.capture_root:
            for folder in ('pages', 'details'):
                for path in sorted((root / folder).glob('*.json')):
                    store.import_capture(path)
        if store.conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('OTA_STORE_INTEGRITY_FAILED')
        store.conn.commit()
        result = {'status':'PASS', 'before':before, 'after':store.summary(),
                  'scope':'unified_evidence_only_no_ledger_writes'}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        store.close()


if __name__ == '__main__':
    main()
