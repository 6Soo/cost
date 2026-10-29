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


def test_batch_size_and_offset_validation(tmp_path):
    client = Cloud()
    # batch_size must be exact int in 1..100
    for bad_size in (0, 101, -1, '10', True, False, 1.5):
        with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_CONFIG_INVALID'):
            run(client, tmp_path, batch_size=bad_size)

    # batch_offset must be non-negative int
    for bad_offset in (-1, '0', True, False, 1.5):
        with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_CONFIG_INVALID'):
            run(client, tmp_path, batch_size=10, batch_offset=bad_offset)

    # offset > 0 rejected when apply=True
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_CONFIG_INVALID'):
        run(client, tmp_path, apply=True, batch_size=10, batch_offset=1)

    # offset > 0 rejected when batch_size is None
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_CONFIG_INVALID'):
        run(client, tmp_path, batch_offset=1)


def test_default_mode_preserves_exact_legacy_return_structure(tmp_path):
    result = run(Cloud(), tmp_path)
    assert set(result.keys()) == {
        'mode', 'indexed', 'existing', 'new', 'appended', 'download_bytes', 'enumeration_complete'
    }
    assert 'selected' not in result
    assert 'remaining_new' not in result
    assert 'batch_offset' not in result


def test_batch_preview_counts_slicing_and_zero_writes(tmp_path):
    identities = ('a1', 'b2', 'c3', 'd4', 'e5')
    client = Cloud(identities)

    # Slice 0: offset 0, size 2 -> a1, b2
    r0 = run(client, tmp_path, batch_size=2, batch_offset=0)
    assert r0['mode'] == 'DRY_RUN'
    assert r0['indexed'] == 5
    assert r0['existing'] == 0
    assert r0['new'] == 5
    assert r0['selected'] == 2
    assert r0['remaining_new'] == 3
    assert r0['batch_offset'] == 0
    assert r0['appended'] == 0
    assert client.downloaded == ['manifest', 'a1', 'b2']
    assert list(tmp_path.iterdir()) == []

    # Slice 1: offset 2, size 2 -> c3, d4
    client.downloaded.clear()
    r1 = run(client, tmp_path, batch_size=2, batch_offset=2)
    assert r1['new'] == 5
    assert r1['selected'] == 2
    assert r1['remaining_new'] == 1
    assert r1['batch_offset'] == 2
    assert client.downloaded == ['manifest', 'c3', 'd4']
    assert list(tmp_path.iterdir()) == []

    # Slice 2: offset 4, size 2 -> e5 (only 1 item remaining)
    client.downloaded.clear()
    r2 = run(client, tmp_path, batch_size=2, batch_offset=4)
    assert r2['new'] == 5
    assert r2['selected'] == 1
    assert r2['remaining_new'] == 0
    assert r2['batch_offset'] == 4
    assert client.downloaded == ['manifest', 'e5']
    assert list(tmp_path.iterdir()) == []

    # Slice 3: offset 6, size 2 -> empty slice past end
    client.downloaded.clear()
    r3 = run(client, tmp_path, batch_size=2, batch_offset=6)
    assert r3['new'] == 5
    assert r3['selected'] == 0
    assert r3['remaining_new'] == 0
    assert r3['batch_offset'] == 6
    assert client.downloaded == ['manifest']
    assert list(tmp_path.iterdir()) == []


def test_unselected_raw_download_zero(tmp_path):
    client = Cloud(('a1', 'b2', 'c3'))
    run(client, tmp_path, batch_size=1, batch_offset=0)
    assert 'b2' not in client.downloaded
    assert 'c3' not in client.downloaded


def test_metadata_error_outside_slice_fails_before_any_raw_download_or_write(tmp_path):
    client = Cloud(('a1', 'b2', 'c3'))
    # Corrupt c3 digest metadata in manifest
    del client.document['messages']['c3']['sha256']
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_DIGEST_REQUIRED'):
        run(client, tmp_path, batch_size=1, batch_offset=0)
    # Manifest was downloaded, but raw a1 was NEVER downloaded because metadata check runs first
    assert 'a1' not in client.downloaded
    assert list(tmp_path.iterdir()) == []


def test_metadata_target_conflict_outside_slice_fails_before_downloads(tmp_path):
    client = Cloud(('a1', 'b2', 'c3'))
    # Local conflict for c3
    conflict = tmp_path / 'gmail-cloud-c3.json'
    conflict.write_text('{}', encoding='utf-8')
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_LOCAL_CONFLICT'):
        run(client, tmp_path, batch_size=1, batch_offset=0)
    assert 'a1' not in client.downloaded


def test_small_byte_budget_fails_single_run_succeeds_in_batches(tmp_path, monkeypatch):
    client = Cloud(('a1', 'b2'))
    # Each synthetic original is ~280 bytes. Total is ~560 bytes.
    # Set byte budget to 400 bytes.
    monkeypatch.setattr(cloud_mail, '_MAX_TOTAL', 400)
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', lambda _: None)

    # Single run fails because total_bytes exceeds 400
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_BATCH_TOO_LARGE'):
        run(client, tmp_path, apply=True)
    assert list(tmp_path.iterdir()) == []

    # Batch run 1 (size 1, offset 0) succeeds: 1 original ~280 bytes <= 400 bytes
    b1 = run(client, tmp_path, apply=True, batch_size=1)
    assert b1['appended'] == 1
    assert b1['selected'] == 1
    assert b1['new'] == 2
    assert b1['remaining_new'] == 1
    assert len(list(tmp_path.iterdir())) == 1

    # Batch run 2 (size 1, offset 0) picks up the next remaining new message
    b2 = run(client, tmp_path, apply=True, batch_size=1)
    assert b2['appended'] == 1
    assert b2['selected'] == 1
    assert b2['new'] == 1
    assert b2['remaining_new'] == 0
    assert len(list(tmp_path.iterdir())) == 2


def test_batch_apply_rejects_incomplete_enumeration_with_zero_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', lambda _: None)
    client = Cloud(('a1', 'b2'))
    client.document['query'] = 'label:unread'
    client.document['last_complete'] = None

    # Preview succeeds and indicates enumeration_complete=False
    prev = run(client, tmp_path, batch_size=1, batch_offset=0)
    assert not prev['enumeration_complete']

    # Default apply contract preserved
    # But batch apply MUST reject
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_ENUMERATION_INCOMPLETE'):
        run(client, tmp_path, apply=True, batch_size=1)
    assert list(tmp_path.iterdir()) == []


def test_batch_apply_rejects_pending_or_next_page_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', lambda _: None)
    for key, value in (('pending', ['a1']), ('nextPageToken', 'next'), ('has_next_page', True)):
        client = Cloud(('a1', 'b2'))
        client.document[key] = value
        for options in ({'batch_size': 1}, {}):
            with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_ENUMERATION_INCOMPLETE'):
                run(client, tmp_path, apply=True, **options)
        assert list(tmp_path.iterdir()) == []


def test_readiness_cli_verifies_whole_manifest_batches_and_counts(tmp_path):
    from tools.verify_cloud_cutover_readiness import verify, ReadinessError, batch_digest
    client = Cloud(('a1', 'b2'))
    ids = ['a1', 'b2']
    evidence = {'manifest': client.document, 'batches': [
        {'sha256': batch_digest(client.document['messages'], ids), 'ids': ids, 'coverage': {'complete': True, 'count': 2}}],
        'existing': 0, 'new': 2, 'indexed': 2}
    import hashlib
    evidence['batch_coverage_sha256'] = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
    assert verify(evidence)['status'] == 'PREVIEW_VERIFIED'
    assert verify(evidence)['operational_cutover_allowed'] is False
    evidence['batches'][0]['sha256'] = '0' * 64
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_BATCH_HASH_INVALID'):
        verify(evidence)
    evidence['batches'][0]['sha256'] = batch_digest(client.document['messages'], ids)
    evidence['manifest']['pending'] = ['a1']
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_PENDING'):
        verify(evidence)


def test_readiness_rejects_invalid_watermark_and_message_identity():
    from tools.verify_cloud_cutover_readiness import verify, ReadinessError, batch_digest
    client = Cloud(('a1', 'b2'))
    ids = ['a1', 'b2']
    evidence = {'manifest': client.document, 'batches': [
        {'sha256': batch_digest(client.document['messages'], ids), 'ids': ids,
         'coverage': {'complete': True, 'count': 2}}],
        'existing': 0, 'new': 2, 'indexed': 2}
    import hashlib
    evidence['batch_coverage_sha256'] = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
    client.document['last_complete'] = 'yesterday'
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_ENUMERATION_INCOMPLETE'):
        verify(evidence)
    client.document['last_complete'] = '2026-10-28T00:00:00Z'
    client.document['messages']['../bad'] = client.document['messages'].pop('a1')
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_READINESS_MANIFEST_INVALID'):
        verify(evidence)


@pytest.mark.parametrize('watermark', [
    '', '2026-99-99T00:00:00Z', '2026-10-30T25:61:61Z',
    '2026-10-30T00:00:00', '2026-10-30T00:00:00+00:00',
])
def test_readiness_rejects_nonexistent_or_non_utc_watermarks(watermark):
    from tools.verify_cloud_cutover_readiness import verify, ReadinessError, batch_digest
    client = Cloud(('a1', 'b2'))
    ids = ['a1', 'b2']
    evidence = {'manifest': client.document, 'batches': [
        {'sha256': batch_digest(client.document['messages'], ids), 'ids': ids,
         'coverage': {'complete': True, 'count': 2}}],
        'existing': 0, 'new': 2, 'indexed': 2}
    import hashlib
    evidence['batch_coverage_sha256'] = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
    client.document['last_complete'] = watermark
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_ENUMERATION_INCOMPLETE'):
        verify(evidence)


def test_readiness_file_rejects_duplicate_json_keys(tmp_path):
    from tools.verify_cloud_cutover_readiness import _read, ReadinessError
    path = tmp_path / 'evidence.json'
    path.write_text('{"status":"first","status":"second"}', encoding='utf-8')
    with pytest.raises(ReadinessError, match='CLOUD_MAIL_DUPLICATE_JSON_KEY'):
        _read(path)


def test_prepare_cloud_mail_release_copies_only_validated_sources(tmp_path, capsys):
    from tools import prepare_cloud_mail_release
    output = tmp_path / 'release'
    assert prepare_cloud_mail_release.main(['--output', str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'PREPARED'
    assert result['remote_written'] is False and result['credentials_included'] is False
    assert {path.name for path in output.iterdir()} == {'CloudMail.gs', 'appsscript.json'}
    assert json.loads((output / 'appsscript.json').read_text(encoding='utf-8'))
    with pytest.raises(SystemExit):
        prepare_cloud_mail_release.main(['--output', str(output)])


def test_cli_batch_flags(tmp_path, monkeypatch):
    client = Cloud(('a1', 'b2'))
    monkeypatch.setattr(cloud_mail, 'DriveClient', lambda: client)
    args = [
        '--directory', str(tmp_path),
        '--folder-id', 'folder',
        '--account', ACCOUNT,
        '--batch-size', '1',
        '--batch-offset', '0',
    ]
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = cloud_mail.main(args)
    assert ret == 0
    out = json.loads(buf.getvalue())
    assert out['mode'] == 'DRY_RUN'
    assert out['new'] == 2
    assert out['selected'] == 1
    assert out['remaining_new'] == 1
    assert out['batch_offset'] == 0


def test_batch_content_validation_failure_installs_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_mail, 'sync_unified_store', lambda _: None)
    client = Cloud(('a1', 'b2'))
    # b2 content is corrupted
    client.data['b2'] += b'corrupted'
    with pytest.raises(cloud_mail.CloudMailError, match='CLOUD_MAIL_DIGEST_MISMATCH'):
        run(client, tmp_path, apply=True, batch_size=2)
    # Neither a1 nor b2 should be installed on disk
    assert list(tmp_path.iterdir()) == []


def test_batch_retry_preserves_originals_headers_and_db(tmp_path):
    from app.ota_store import OtaStore
    from app.ota_mail import load_messages_from
    directory = tmp_path / 'ota-mail'
    directory.mkdir()
    database = tmp_path / 'ota.sqlite'
    store = OtaStore(database)
    store.close()
    (tmp_path / 'ota-sources.json').write_text(json.dumps({
        'schema_version': 'ota-sources-v1', 'unified_database': str(database)}), encoding='utf-8')
    client = Cloud(('a1', 'b2'))

    # Batch 1: applies a1
    res1 = run(client, directory, apply=True, batch_size=1)
    assert res1['appended'] == 1
    messages1, _ = load_messages_from([database])
    assert set(messages1) == {'a1'}
    assert messages1['a1']['payload']['headers'] == original('a1')['responses'][0]['payload']['headers']

    # Batch 2: applies b2
    res2 = run(client, directory, apply=True, batch_size=1)
    assert res2['appended'] == 1
    messages2, _ = load_messages_from([database])
    assert set(messages2) == {'a1', 'b2'}
    assert messages2['b2']['payload']['headers'] == original('b2')['responses'][0]['payload']['headers']

    # Repeat batch apply is no-op, preserves originals and headers
    res3 = run(client, directory, apply=True, batch_size=1)
    assert res3['appended'] == 0
    messages3, _ = load_messages_from([database])
    assert set(messages3) == {'a1', 'b2'}
