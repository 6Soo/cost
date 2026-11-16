"""Extractor baseline (design §3.4): events from a read-only copy of the preserved originals, protected output."""
import json
import shutil
import sys
from pathlib import Path

import pytest

from tools.core_bridge.cli import handle
from tools.core_bridge.commands import canonical

ROOT = Path(__file__).resolve().parents[1]


def host(tmp_path):
    (tmp_path / 'data' / 'backups').mkdir(parents=True, exist_ok=True)
    return tmp_path


def evidence_copy(tmp_path):
    from app.ota_store import OtaStore
    store = OtaStore(tmp_path / 'ota-evidence-copy.sqlite')
    store.conn.close()
    return tmp_path / 'ota-evidence-copy.sqlite'


def request(tmp_path, **changes):
    root = host(tmp_path / 'host')
    base = {'ota_evidence': str(evidence_copy(tmp_path)), 'host_root': str(root),
            'out': str(root / 'data' / 'backups' / 'extractor-baseline' / 'events.json')}
    return dict(base, **changes)


def test_command_writes_a_protected_baseline_from_a_copy(tmp_path):
    req = request(tmp_path)
    response = handle('extract-baseline', req, sha='')
    assert response['ok'], response
    assert response['result']['events'] == 0 and set(response['result']) >= {'sha256'}
    out = Path(req['out'])
    assert out.is_file()
    assert json.loads(out.read_text(encoding='utf-8')) == canonical({'events': []})


def test_live_store_is_backed_up_read_only_and_left_unchanged(tmp_path):
    req = request(tmp_path)
    live = Path(req['host_root']) / 'data' / 'ota-evidence.sqlite'
    shutil.copy(req['ota_evidence'], live)
    before = live.read_bytes()
    response = handle('extract-baseline', dict(req, ota_evidence=str(live)), sha='')
    assert response['ok'], response
    assert response['result']['events'] == 0
    assert live.read_bytes() == before
    assert Path(req['out']).is_file()


@pytest.mark.parametrize('out,code', [
    (ROOT / 'outputs' / 'events.json', 'OUT_INSIDE_REPO'),
    (ROOT / 'data' / 'backups' / 'events.json', 'OUT_INSIDE_REPO'),
])
def test_output_inside_the_repository_is_refused(tmp_path, out, code):
    response = handle('extract-baseline', request(tmp_path, out=str(out)), sha='')
    assert not response['ok'] and response['error']['code'] == code
    assert not out.exists()


def test_output_outside_the_protected_folder_is_refused(tmp_path):
    response = handle('extract-baseline', request(tmp_path, out=str(tmp_path / 'elsewhere.json')), sha='')
    assert not response['ok'] and response['error']['code'] == 'OUT_NOT_PROTECTED'


def test_existing_output_is_not_overwritten(tmp_path):
    req = request(tmp_path)
    out = Path(req['out'])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('{}', encoding='utf-8')
    response = handle('extract-baseline', req, sha='')
    assert not response['ok'] and response['error']['code'] == 'OUT_EXISTS'
    assert out.read_text(encoding='utf-8') == '{}'


def test_missing_evidence_is_refused(tmp_path):
    req = request(tmp_path)
    Path(req['ota_evidence']).unlink()
    response = handle('extract-baseline', req, sha='')
    assert not response['ok'] and response['error']['code'] == 'DB_NOT_FOUND'
    assert not Path(req['out']).exists()


def test_cli_accepts_the_command_name():
    import subprocess
    proc = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'core_bridge' / 'cli.py'), 'extract-baseline'],
                          input='{}\n', text=True, capture_output=True, encoding='utf-8')
    assert json.loads(proc.stdout)['error']['code'] == 'OTA_EVIDENCE_REQUIRED'
