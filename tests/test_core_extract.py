"""M6 synthetic evidence copy -> Python parser bridge -> Rust extractor -> exact baseline bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import ota_payments as op
from app.ota_store import OtaStore
from tools.core_bridge.cli import handle
from tools.core_bridge.extract_golden import event, expected, records, stages
from tools.core_bridge.extract_sources import collect, forest_name_keys
from tools.core_bridge.ota_input import _sources
from tests.card_pipeline.test_booking_mail import message
from tests.card_pipeline.test_ota_sources_registry import portal_database, write_mail

ROOT = Path(__file__).resolve().parents[1]


def test_new_synthetic_goldens_still_equal_unchanged_python_helpers():
    saved = [json.loads(line) for line in (ROOT / 'core/golden/synthetic/extract.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(saved) >= 50
    assert saved == list(records())


def synthetic_store(tmp_path):
    mail = write_mail(tmp_path / 'mail', [message('예약번호: SYNTH12345\n총 금액 30,000원',
                      subject='[Trip.com] 결제 완료 안내', identity='synthetic-payment')])
    portal = portal_database(tmp_path / 'portal.sqlite')
    path = tmp_path / 'evidence-copy.sqlite'
    store = OtaStore(path)
    try:
        store.import_mail(mail)
        store.import_portal(portal)
    finally:
        store.conn.close()
    return path


def test_bridge_parses_a_nonempty_synthetic_store_without_changing_it(tmp_path):
    evidence = synthetic_store(tmp_path)
    before = evidence.read_bytes()
    response = handle('extract-sources', {'ota_evidence': str(evidence), 'host_root': str(tmp_path / 'host')})
    assert response['ok'], response
    stages = response['result']
    assert stages['schema_version'] == 'ota-extract-stages/1'
    assert len(stages['mail_events']) == 1 and len(stages['portal_events']) == 1
    assert evidence.read_bytes() == before


@pytest.mark.parametrize('kind', ['missing', 'diagnostics', 'registered', 'references'])
def test_source_validation_does_not_return_a_partial_stage_set(tmp_path, kind):
    sources = {'mail_directories': [], 'portal_databases': []}
    if kind in ('missing', 'diagnostics'):
        sources[kind] = [{'kind': 'synthetic-failure'}]
    elif kind == 'registered':
        sources['registered'] = {'portal_databases': [tmp_path / 'missing.sqlite']}
    else:
        path = tmp_path / 'bad-reference.json'
        path.write_text('invalid json', encoding='utf-8')
        sources['reference_documents'] = [path]
    with pytest.raises(op.OtaSourcesError):
        collect(sources)


def test_bridge_refuses_live_alias_missing_and_required_inputs(tmp_path):
    assert handle('extract-sources', {}, sha='')['error']['code'] == 'OTA_EVIDENCE_REQUIRED'
    assert handle('extract-sources', {'ota_evidence': str(tmp_path / 'missing')}, sha='')['error']['code'] == 'DB_NOT_FOUND'
    live = tmp_path / 'host/data/ota-evidence.sqlite'
    live.parent.mkdir(parents=True)
    store = OtaStore(live)
    store.conn.close()
    for path in [live, live.parent / '../data/ota-evidence.sqlite']:
        response = handle('extract-sources', {'ota_evidence': str(path), 'host_root': str(tmp_path / 'host')}, sha='')
        assert response['error']['code'] == 'DB_IS_LIVE'
    alias = tmp_path / 'hardlink.sqlite'
    os.link(live, alias)
    response = handle('extract-sources', {'ota_evidence': str(alias), 'host_root': str(tmp_path / 'host')}, sha='')
    assert response['error']['code'] == 'DB_IS_LIVE'


def run_extract(args):
    binary = os.environ.get('COSTCORE_TEST_BIN')
    assert binary and Path(binary).is_file(), 'COSTCORE_TEST_BIN is required (no skipped verification)'
    result = subprocess.run([binary, 'extract', '--repo-root', str(ROOT), '--python', sys.executable, *map(str, args)],
                            capture_output=True, encoding='utf-8', timeout=60)
    assert result.stderr == ''
    return result, json.loads(result.stdout)


@pytest.mark.costcore_bin
def test_rust_extract_copy_is_byte_identical_to_python_baseline_and_public_output_is_aggregate(tmp_path):
    evidence = synthetic_store(tmp_path)
    before = evidence.read_bytes()
    from tools.core_bridge.extract_baseline import sqlite_logical_fingerprint

    sources = _sources(evidence, tmp_path)
    sources['portal_content_fingerprints'] = {'0': sqlite_logical_fingerprint(evidence)}
    expected = op.build_ota_payment_events(sources)
    raw = json.dumps({'events': expected}, ensure_ascii=False, sort_keys=True).encode('utf-8')
    assert len(expected) == 2
    host = tmp_path / 'host'
    backups = host / 'data/backups'
    backups.mkdir(parents=True)
    out = backups / 'extract/events.json'
    args = ['--ota-evidence', evidence, '--host-root', host, '--out', out]
    result, response = run_extract(args)
    assert result.returncode == 0 and response['ok']
    assert out.read_bytes() == raw
    assert response['result'] == {'events': 2, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert 'SYNTH12345' not in result.stdout and 'synthetic-payment' not in result.stdout
    assert evidence.read_bytes() == before
    result, response = run_extract(args)
    assert result.returncode != 0 and not response['ok']
    assert out.read_bytes() == raw


@pytest.mark.costcore_bin
def test_rust_extract_rejects_outside_output_and_invalid_stages_without_creating_files(tmp_path):
    host = tmp_path / 'host'
    backups = host / 'data/backups'
    backups.mkdir(parents=True)
    source = tmp_path / 'stages.json'
    source.write_text('{}', encoding='utf-8')
    for out, code in [(tmp_path / 'public.json', 'PRIVATE_PATH_REJECTED'),
                      (backups / 'events.json', 'EXTRACT_INPUT_INVALID')]:
        result, response = run_extract(['--stages', source, '--host-root', host, '--out', out])
        assert result.returncode != 0 and response['error']['code'] == code
        assert not out.exists()
    result, response = run_extract(['--allow-live', 'yes'])
    assert result.returncode != 0 and response['error']['code'] == 'USAGE_INVALID'


@pytest.mark.costcore_bin
def test_rust_extract_refuses_output_in_the_repo_even_with_a_synthetic_host_override(tmp_path):
    import tempfile
    archive = ROOT / '.local-archive'
    archive.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='m6-output-guard-', dir=archive) as work:
        host = Path(work)
        (host / 'data/backups').mkdir(parents=True)
        out = host / 'data/backups/never-created.json'
        result, response = run_extract(['--ota-evidence', tmp_path / 'missing.sqlite', '--host-root', host, '--out', out])
        assert result.returncode != 0 and response['error']['code'] == 'OUT_INSIDE_REPO'
        assert not out.exists()


@pytest.mark.costcore_bin
def test_rust_extract_stages_match_every_python_golden_and_sort_final_events(tmp_path):
    host = tmp_path / 'host'
    backups = host / 'data/backups'
    backups.mkdir(parents=True)
    cases = list(records())
    for index, case in enumerate(cases):
        source = tmp_path / 'stages.json'
        source.write_text(json.dumps(case['input'], ensure_ascii=False), encoding='utf-8')
        out = backups / f'case-{index}.json'
        result, response = run_extract(['--stages', source, '--host-root', host, '--out', out])
        assert result.returncode == 0, (case['case_id'], response)
        assert out.read_bytes() == json.dumps(case['expected'], ensure_ascii=False, sort_keys=True).encode('utf-8')
        assert response['result']['sha256'] == case['sha256']


@pytest.mark.costcore_bin
@pytest.mark.parametrize('left,right', [('30000', '3e4'),
    ('12345678901234567890123456789012345678901234567890', '12345678901234567890123456789012345678901234567890.000'),
    ('0.00000000000000000000000000000000000000000000001', '1e-47'),
    ('30000', '3_0000'), ('-0', '0.000')])
def test_native_decimal_comparisons_keep_all_source_digits(tmp_path, left, right):
    a, b = event('mail:precision', amount=left), event('portal:precision', amount=right, source_binding_ids=['mail:precision'])
    data = stages([a], [b])
    host = tmp_path / 'host'
    (host / 'data/backups').mkdir(parents=True)
    source, out = tmp_path / 'stages.json', host / 'data/backups/events.json'
    source.write_text(json.dumps(data), encoding='utf-8')
    result, response = run_extract(['--stages', source, '--host-root', host, '--out', out])
    assert result.returncode == 0, response
    assert json.loads(out.read_text(encoding='utf-8')) == expected(data)


@pytest.mark.costcore_bin
@pytest.mark.parametrize('name,folded', [('ﬃ 숲', 'ffi숲'), ('ſ 숲', 's숲'), ('Straße', 'STRASSE'), ('Ꭰ숲', 'ꭰ숲')])
def test_python_unicode_facility_keys_are_preserved_at_the_parser_boundary(tmp_path, name, folded):
    data = next(case['input'] for case in records() if case['case_id'] == 'forest-shared-period')
    data['mail_events'][0]['merchant_name'] = name
    data['forest_portal_events'][0]['hotel_name'] = folded
    data['forest_name_keys'] = forest_name_keys(data)
    host = tmp_path / 'host'
    (host / 'data/backups').mkdir(parents=True)
    source, out = tmp_path / 'stages.json', host / 'data/backups/events.json'
    source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    result, response = run_extract(['--stages', source, '--host-root', host, '--out', out])
    assert result.returncode == 0, response
    assert json.loads(out.read_text(encoding='utf-8')) == expected(data)
