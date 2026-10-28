"""Synthetic Drive responses and isolated local files; never contact a live account."""
import hashlib
import json

import pytest

from app import cloud_mail

ACCOUNT = 'owner@example.invalid'


def original(identity):
    return {'responses': [{'id': identity, 'internalDate': '1793138400000',
        'payload': {'headers': [{'name': 'Authentication-Results', 'value': 'synthetic pass'}],
                    'parts': [{'mimeType': 'text/plain', 'body': {'data': 'c3ludGhldGlj'}}]}}]}


class Cloud:
    def __init__(self, identities=('a1', 'b2')):
        self.data = {identity: json.dumps(original(identity)).encode() for identity in identities}
        self.document = {'schema': 'cost-cloud-mail-v1', 'account': ACCOUNT,
            'query': None, 'last_complete': '2026-10-28T00:00:00Z', 'messages': {
                identity: {'file_id': identity, 'name': f'gmail-{identity}.json',
                    'sha256': hashlib.sha256(self.data[identity]).hexdigest()} for identity in identities}}
        self.metadata = [{'id': identity, 'name': f'gmail-{identity}.json', 'parents': ['folder'],
                          'mimeType': 'application/json', 'shared': False} for identity in identities]
        self.metadata.append({'id': 'manifest', 'name': 'cloud-mail-manifest.json',
                              'parents': ['folder'], 'mimeType': 'application/json', 'shared': False})
        self.private = True
        self.downloaded = []

    def folder(self, identity):
        return {'id': identity, 'mimeType': 'application/vnd.google-apps.folder',
                'shared': not self.private, 'owners': [{'emailAddress': ACCOUNT}]}

    def list_files(self, identity):
        assert identity == 'folder'
        return self.metadata

    def download(self, identity, *, max_bytes):
        self.downloaded.append(identity)
        return json.dumps(self.document).encode() if identity == 'manifest' else self.data[identity]


def run(client, directory, **kwargs):
    return cloud_mail.sync(client, directory, folder_id='folder', expected_account=ACCOUNT, **kwargs)


def test_dry_run_validates_full_originals_without_files_or_import(tmp_path, monkeypatch):
    imports = []
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', imports.append)
    result = run(Cloud(), tmp_path)
    assert result['new'] == 2 and result['appended'] == 0 and result['enumeration_complete']
    assert list(tmp_path.iterdir()) == [] and imports == []


def test_apply_preserves_full_mime_and_repeat_is_noop_but_retries_import(tmp_path, monkeypatch):
    imports = []
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', imports.append)
    client = Cloud()
    assert run(client, tmp_path, apply=True)['appended'] == 2
    saved = tmp_path / 'gmail-cloud-a1.json'
    assert json.loads(saved.read_bytes()) == original('a1')
    before = saved.stat().st_mtime_ns
    client.downloaded.clear()
    assert run(client, tmp_path, apply=True)['new'] == 0
    assert saved.stat().st_mtime_ns == before and client.downloaded == ['manifest']
    assert imports == [tmp_path, tmp_path]
    assert len(list(tmp_path.iterdir())) == 2


def test_existing_local_id_keeps_first_original_even_if_cloud_labels_changed(tmp_path, monkeypatch):
    document = original('a1')
    document['responses'][0]['labelIds'] = ['SYNTHETIC-FIRST']
    saved = tmp_path / 'gmail-auto-first.json'
    saved.write_text(json.dumps(document), encoding='utf-8')
    before = saved.read_bytes()
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', lambda _: None)
    result = run(Cloud(), tmp_path, apply=True)
    assert result['existing'] == 1 and result['appended'] == 1
    assert saved.read_bytes() == before and not (tmp_path / 'gmail-cloud-a1.json').exists()


@pytest.mark.parametrize('failure,code', [
    ('digest', 'CLOUD_MAIL_DIGEST_MISMATCH'), ('account', 'CLOUD_MAIL_ACCOUNT_MISMATCH'),
    ('folder', 'CLOUD_MAIL_FOLDER_NOT_PRIVATE'), ('shared-file', 'CLOUD_MAIL_FILES_INVALID'),
    ('outside-folder', 'CLOUD_MAIL_FILES_INVALID'), ('duplicate-name', 'CLOUD_MAIL_FILES_INVALID'),
    ('missing', 'CLOUD_MAIL_ORIGINAL_MISSING'), ('invalid-id', 'CLOUD_MAIL_MANIFEST_INVALID'),
    ('unhashed', 'CLOUD_MAIL_DIGEST_REQUIRED'), ('original-id', 'CLOUD_MAIL_ORIGINAL_INVALID'),
])
def test_invalid_cloud_batch_never_partially_appends_or_imports(tmp_path, monkeypatch, failure, code):
    client = Cloud()
    if failure == 'digest': client.data['b2'] += b' '
    elif failure == 'account': client.document['account'] = 'other@example.invalid'
    elif failure == 'folder': client.private = False
    elif failure == 'shared-file': client.metadata[0]['shared'] = True
    elif failure == 'outside-folder': client.metadata[0]['parents'] = ['different']
    elif failure == 'duplicate-name': client.metadata.append(dict(client.metadata[0], id='other'))
    elif failure == 'missing': client.metadata.pop(0)
    elif failure == 'invalid-id': client.document['messages']['../path'] = {}
    elif failure == 'unhashed': del client.document['messages']['a1']['sha256']
    elif failure == 'original-id':
        client.data['b2'] = json.dumps(original('c3')).encode()
        client.document['messages']['b2']['sha256'] = hashlib.sha256(client.data['b2']).hexdigest()
    imports = []
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', imports.append)
    with pytest.raises(cloud_mail.CloudMailError, match=code): run(client, tmp_path, apply=True)
    assert list(tmp_path.iterdir()) == [] and imports == []


def test_unrelated_file_at_target_is_preserved(tmp_path, monkeypatch):
    file = tmp_path / 'gmail-cloud-a1.json'
    file.write_text(json.dumps(original('c3')), encoding='utf-8')
    before = file.read_bytes()
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_LOCAL_CONFLICT'):
        run(Cloud(), tmp_path, apply=True)
    assert file.read_bytes() == before and len(list(tmp_path.iterdir())) == 1


def test_failed_import_preserves_files_and_retry_completes_without_duplicate(tmp_path, monkeypatch):
    def fail(_): raise RuntimeError('synthetic DB contention')
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', fail)
    with pytest.raises(RuntimeError, match='synthetic DB contention'): run(Cloud(), tmp_path, apply=True)
    assert len(list(tmp_path.iterdir())) == 2
    imported = []
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', imported.append)
    assert run(Cloud(), tmp_path, apply=True)['appended'] == 0 and imported == [tmp_path]


def test_cloud_full_original_reaches_unified_store_with_schema_and_business_rows_preserved(tmp_path):
    from app.ota_store import OtaStore
    from app.ota_mail import load_messages_from
    directory = tmp_path / 'ota-mail'
    directory.mkdir()
    database = tmp_path / 'ota.sqlite'
    store = OtaStore(database)
    schemas = store.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    business = {name: store.conn.execute('SELECT * FROM "' + name + '"').fetchall()
                for name, _ in schemas if name not in (
                    'ota_sources', 'ota_source_revisions', 'ota_raw_entries', 'ota_messages',
                    'ota_mail_origins', 'ota_raw_blobs', 'sqlite_sequence')}
    store.close()
    (tmp_path / 'ota-sources.json').write_text(json.dumps({
        'schema_version': 'ota-sources-v1', 'unified_database': str(database)}), encoding='utf-8')
    assert run(Cloud(), directory, apply=True)['appended'] == 2
    messages, _ = load_messages_from([database])
    assert set(messages) == {'a1', 'b2'}
    assert messages['a1']['payload']['headers'] == original('a1')['responses'][0]['payload']['headers']
    assert messages['a1']['payload']['parts'] == original('a1')['responses'][0]['payload']['parts']
    assert run(Cloud(), directory, apply=True)['appended'] == 0
    store = OtaStore(database)
    try:
        assert store.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() == schemas
        for name, rows in business.items():
            assert store.conn.execute('SELECT * FROM "' + name + '"').fetchall() == rows, name
    finally:
        store.close()


def test_atomic_install_never_overwrites_competing_writer(tmp_path, monkeypatch):
    def race(source, target):
        target.write_bytes(b'synthetic competing writer')
        raise FileExistsError()
    monkeypatch.setattr(cloud_mail.os, 'link', race)
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_LOCAL_CONFLICT'):
        run(Cloud(), tmp_path, apply=True)
    assert (tmp_path / 'gmail-cloud-a1.json').read_bytes() == b'synthetic competing writer'
    assert not list(tmp_path.glob('.cloud-mail-*'))


class Response:
    def __init__(self, content, status=200):
        self.content, self.status_code, self.closed = content, status, False
    def iter_content(self, chunk_size): yield self.content
    def close(self): self.closed = True


def test_drive_client_follows_pages_with_bounded_no_redirect_gets():
    class Session:
        def __init__(self): self.calls = []; self.responses = []
        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            data = {'files': [{'id': 'b2'}]} if kwargs['params'].get('pageToken') else {
                'files': [{'id': 'a1'}], 'nextPageToken': 'next'}
            response = Response(json.dumps(data).encode()); self.responses.append(response); return response
    session = Session(); client = cloud_mail.DriveClient(session)
    assert [file['id'] for file in client.list_files('folder')] == ['a1', 'b2']
    assert len(session.calls) == 2
    assert all(kwargs['allow_redirects'] is False for _, kwargs in session.calls)
    assert all(response.closed for response in session.responses)


@pytest.mark.parametrize('status', [302, 401, 403, 404, 500])
def test_drive_failure_does_not_forward_credentials_or_expose_body(status):
    response = Response(b'synthetic private token and original body', status)
    class Session:
        def get(self, url, **kwargs): return response
    with pytest.raises(cloud_mail.CloudMailError) as caught:
        cloud_mail.DriveClient(Session()).download('a1', max_bytes=100)
    assert 'private token' not in str(caught.value) and response.closed
