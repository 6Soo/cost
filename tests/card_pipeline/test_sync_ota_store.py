"""CLI input gates use synthetic files and isolated SQLite stores only."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ota_store import OtaStore, connect_read
from tools.consolidate_ota_sources import database_digest


SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'sync_ota_store.py'
MESSAGE = {'id': 'private-synthetic-id', 'payload': {
    'headers': [], 'body': {'content': 'private-synthetic-body'}}}


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def create_store(path):
    store = OtaStore(path)
    store.close()
    return path


def digest(path):
    conn = connect_read(path)
    try:
        return database_digest(SimpleNamespace(conn=conn))
    finally:
        conn.close()


def run_cli(database, backup, report, *inputs):
    return subprocess.run([sys.executable, '-B', str(SCRIPT), '--db', str(database),
        '--backup', str(backup), '--report', str(report), *map(str, inputs)],
        capture_output=True, text=True, encoding='utf-8')


@pytest.mark.parametrize('filename,content,code', [
    (None, None, 'OTA_STORE_MAIL_NO_SUPPORTED_FILES'),
    ('messages.json', {'responses': [MESSAGE]}, 'OTA_STORE_MAIL_NO_SUPPORTED_FILES'),
    ('gmail.json', {'responses': []}, 'OTA_STORE_MAIL_NO_MESSAGES'),
    ('gmail.json', '{private-synthetic-body', 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', [], 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': {}}, 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [None]}, 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [{'id': '', 'payload': {}}]}, 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [{'id': 'private-synthetic-id', 'payload': None}]},
     'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [{'id': 'private-synthetic-id', 'payload': {'headers': [None]}}]},
     'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [MESSAGE, {'id': 'broken'}]}, 'OTA_STORE_MAIL_INPUT_INVALID'),
    ('gmail.json', {'responses': [{'id': 'private-synthetic-id', 'payload': {'body': 7}}]},
     'OTA_STORE_MAIL_INPUT_INVALID'),
])
def test_invalid_mail_fails_before_any_database_or_backup_write(tmp_path, filename, content, code):
    database = create_store(tmp_path / 'store.sqlite')
    before = database.read_bytes()
    folder = tmp_path / 'private-input-path'
    folder.mkdir()
    if filename:
        if isinstance(content, str):
            (folder / filename).write_text(content, encoding='utf-8')
        else:
            write_json(folder / filename, content)
    backup = tmp_path / 'new-backup-directory' / 'backup.sqlite'
    report = tmp_path / 'new-report-directory' / 'report.json'
    result = run_cli(database, backup, report, '--mail-directory', folder)
    assert result.returncode == 2
    assert result.stdout == ''
    assert code in result.stderr
    assert all(secret not in result.stderr for secret in (
        str(folder), 'private-synthetic-id', 'private-synthetic-body', 'Traceback'))
    assert database.read_bytes() == before
    assert not backup.parent.exists()
    assert not report.parent.exists()
    assert not Path(str(database) + '-wal').exists()
    assert not Path(str(database) + '-shm').exists()


def test_valid_raw_mail_and_same_input_reimport_are_supported(tmp_path):
    database = create_store(tmp_path / 'store.sqlite')
    initial = digest(database)
    folder = tmp_path / 'mail'
    folder.mkdir()
    write_json(folder / 'gmail.json', {'responses': [MESSAGE]})
    first_backup = tmp_path / 'first-backup.sqlite'
    first = run_cli(database, first_backup, tmp_path / 'first.json', '--mail-directory', folder)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result['after']['ota_messages'] == 1
    assert digest(first_backup) == initial
    after = digest(database)
    repeat = run_cli(database, tmp_path / 'repeat-backup.sqlite', tmp_path / 'repeat.json',
                     '--mail-directory', folder)
    assert repeat.returncode == 0, repeat.stderr
    assert digest(database) == after
    assert digest(tmp_path / 'repeat-backup.sqlite') == after


def test_all_mail_directories_are_checked_before_combined_import(tmp_path):
    database = create_store(tmp_path / 'store.sqlite')
    before = database.read_bytes()
    valid = tmp_path / 'valid'
    invalid = tmp_path / 'empty'
    valid.mkdir()
    invalid.mkdir()
    write_json(valid / 'gmail.json', {'responses': [MESSAGE]})
    reference = tmp_path / 'reference.json'
    write_json(reference, {'synthetic': 'reference'})
    result = run_cli(database, tmp_path / 'backup.sqlite', tmp_path / 'report.json',
                     '--mail-directory', valid, '--reference-document', reference,
                     '--mail-directory', invalid)
    assert result.returncode == 2
    assert database.read_bytes() == before
    assert not (tmp_path / 'backup.sqlite').exists()


@pytest.mark.parametrize('with_mail', [False, True])
def test_other_input_types_work_alone_and_combined_with_mail(tmp_path, with_mail):
    database = create_store(tmp_path / 'store.sqlite')
    reference = tmp_path / 'reference.json'
    write_json(reference, {'synthetic': 'reference'})
    inputs = ['--reference-document', reference]
    if with_mail:
        folder = tmp_path / 'mail'
        folder.mkdir()
        write_json(folder / 'gmail.json', {'responses': [MESSAGE]})
        inputs += ['--mail-directory', folder]
    result = run_cli(database, tmp_path / 'backup.sqlite', tmp_path / 'report.json', *inputs)
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)['after']
    assert counts['ota_sources'] == 1 + int(with_mail)
    assert counts['ota_messages'] == int(with_mail)


def test_portal_capture_reference_and_mail_can_share_one_cli_transaction(tmp_path):
    from tests.card_pipeline.test_agoda_capture import capture
    from tests.card_pipeline.test_ota_sources_registry import portal_database

    database = create_store(tmp_path / 'store.sqlite')
    portal = portal_database(tmp_path / 'portal.sqlite')
    capture_root = tmp_path / 'capture'
    (capture_root / 'details').mkdir(parents=True)
    write_json(capture_root / 'details' / 'synthetic.json', capture())
    reference = tmp_path / 'reference.json'
    write_json(reference, {'synthetic': 'reference'})
    folder = tmp_path / 'mail'
    folder.mkdir()
    write_json(folder / 'gmail.json', {'responses': [MESSAGE]})
    result = run_cli(database, tmp_path / 'backup.sqlite', tmp_path / 'report.json',
                     '--portal-database', portal, '--capture-root', capture_root,
                     '--reference-document', reference, '--mail-directory', folder)
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)['after']
    assert counts['ota_sources'] == 4
    assert counts['ota_messages'] == 1
    assert counts['ota_portal_rows'] > 0
    assert counts['ota_booking_evidence'] > 0


def test_ui_capture_metadata_is_preserved_as_reference_without_creating_mail_or_payment(tmp_path):
    from app import ota_payments
    from app.ota_store import reference_bundles

    database = create_store(tmp_path / 'store.sqlite')
    reference = tmp_path / 'messages.json'
    raw = [{'source_url': 'https://example.invalid/synthetic',
            'tree': 'synthetic UI text', 'capture_kind': 'synthetic-ui',
            'authentication_verified': False} for _ in range(4)]
    write_json(reference, raw)
    result = run_cli(database, tmp_path / 'backup.sqlite', tmp_path / 'report.json',
                     '--reference-document', reference)
    assert result.returncode == 0, result.stderr
    assert [value for _, value in reference_bundles(database)] == [raw]
    counts = json.loads(result.stdout)['after']
    assert counts['ota_messages'] == 0
    assert counts['ota_bookings'] == 0
    assert counts['ota_booking_evidence'] == 0
    assert ota_payments.build_ota_payment_events({'reference_documents': [database]}) == []
