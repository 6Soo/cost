import json

import pytest

from app import mail_collect, ota_payments
from app.ota_store import OtaStore


def _message(message_id, text='Booking ID 123 Check in October 13, 2026'):
    return {'id': message_id, 'internal_date': '1760000000000',
            'payload': {'headers': [{'name': 'From', 'value': 'Agoda <customer-service@agoda.com>'},
                                    {'name': 'Subject', 'value': 'synthetic ' + message_id}],
                        'mime_type': 'text/plain', 'body': {'data': 'Qm9va2luZyBJRCAxMjM='}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    directory = tmp_path / 'ota-mail'
    directory.mkdir()
    OtaStore(tmp_path / 'ota.sqlite').close()
    (tmp_path / 'ota-sources.json').write_text(json.dumps({
        'schema_version': 'ota-sources-v1', 'unified_database': str(tmp_path / 'ota.sqlite')}), encoding='utf-8')
    (directory / 'gmail-a.json').write_text(json.dumps({'responses': [_message('m1')]}), encoding='utf-8')
    (directory / 'collection.json').write_text(json.dumps({'last_run': '1'}), encoding='utf-8')
    calls = []
    real = ota_payments.extract_payment_fact
    monkeypatch.setattr(ota_payments, 'extract_payment_fact', lambda m: calls.append(m['id']) or real(m))
    return directory, calls


def test_unchanged_originals_skip_load_and_extract(env, monkeypatch, capsys):
    directory, calls = env
    mail_collect.sync_unified_store(directory)
    assert calls == ['m1']
    loads = []
    real = OtaStore.import_mail
    monkeypatch.setattr(OtaStore, 'import_mail', lambda self, d: loads.append(d) or real(self, d))
    calls.clear()
    mail_collect.sync_unified_store(directory)
    assert loads == [] and calls == []
    assert 'mail import skipped' in capsys.readouterr().out


def test_collection_json_alone_changing_skips(env, monkeypatch):
    directory, calls = env
    mail_collect.sync_unified_store(directory)
    calls.clear()
    (directory / 'collection.json').write_text(json.dumps({'last_run': '2'}), encoding='utf-8')
    mail_collect.sync_unified_store(directory)
    assert calls == []


def test_added_removed_or_changed_original_imports(env):
    directory, calls = env
    mail_collect.sync_unified_store(directory)
    calls.clear()
    added = directory / 'gmail-b.json'
    added.write_text(json.dumps({'responses': [_message('m2')]}), encoding='utf-8')
    mail_collect.sync_unified_store(directory)
    assert 'm2' in calls
    calls.clear()
    added.write_text(json.dumps({'responses': [_message('m2'), _message('m3')]}), encoding='utf-8')
    mail_collect.sync_unified_store(directory)
    assert 'm3' in calls


def test_removal_is_not_skipped(env, monkeypatch):
    directory, _ = env
    mail_collect.sync_unified_store(directory)
    (directory / 'gmail-b.json').write_text(json.dumps({'responses': [_message('m2')]}), encoding='utf-8')
    mail_collect.sync_unified_store(directory)
    (directory / 'gmail-b.json').unlink()
    loads = []
    real = OtaStore.import_mail
    monkeypatch.setattr(OtaStore, 'import_mail', lambda self, d: loads.append(d) or real(self, d))
    mail_collect.sync_unified_store(directory)
    assert loads == [directory]


def test_retry_after_failed_import_is_not_skipped(env, monkeypatch):
    directory, calls = env
    real = OtaStore.import_mail

    def fail(self, d):
        raise ValueError('boom')
    monkeypatch.setattr(OtaStore, 'import_mail', fail)
    with pytest.raises(ValueError):
        mail_collect.sync_unified_store(directory)
    monkeypatch.setattr(OtaStore, 'import_mail', real)
    mail_collect.sync_unified_store(directory)
    assert calls == ['m1']


def test_parser_modules_the_import_depends_on_are_watched(env):
    directory, _ = env
    names = {row[0] for row in OtaStore.mail_stamp(directory)}
    assert {'code:ota_store.py', 'code:ota_mail.py', 'code:toyoko_mail.py', 'code:ota_sources.py'} <= names


def test_failing_stamp_write_is_logged_not_raised(env, monkeypatch, caplog):
    directory, _ = env
    monkeypatch.setattr('app.ota_store.os.replace', lambda *a: (_ for _ in ()).throw(PermissionError('locked')))
    with caplog.at_level('WARNING'):
        mail_collect.sync_unified_store(directory)
    assert 'mail stamp not written' in caplog.text
