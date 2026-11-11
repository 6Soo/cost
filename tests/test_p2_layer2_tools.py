import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zlib
import pytest
from tools.p2_layer2 import index, offline, reachability


def test_index_backup_unchanged(tmp_path, monkeypatch):
    source = tmp_path / 'backup.sqlite'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE ota_messages(message_id TEXT, payload_json BLOB)')
        data = dict(payload=dict(headers=[dict(name='Subject', value='SYNTHETIC')],
                                 parts=[dict(body=dict(content='KRW 25,000 / 2026-11-12'))]))
        conn.execute('INSERT INTO ota_messages VALUES(?,?)', ('SYNTHETIC', zlib.compress(json.dumps(data).encode())))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    # Private output is rooted beside the module; use an isolated synthetic tree.
    fake = tmp_path / 'repo/tools/p2_layer2/index.py'
    monkeypatch.setattr(index, '__file__', str(fake))
    out = tmp_path / 'repo/.local-archive/index.sqlite'
    assert index.build(source, out)['messages'] == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT body FROM evidence').fetchone()[0] == 'KRW 25,000 / 2026-11-12'
    with pytest.raises(ValueError):
        index.build(source, out)


def test_reachability_exact_amount_currency_and_boundaries():
    row = dict(merchant='Agoda', posting_date='2026-11-12', amount_krw=25000,
               foreign_amount='2000.50', foreign_currency='JPY')
    evidence = dict(body='Agoda KRW 25,000', sent_date='Wed, 11 Nov 2026 12:00:00 +0900')
    assert reachability.conditions(row, evidence)['T1']
    assert reachability.conditions(row, evidence)['T2']
    assert not reachability.conditions(row, dict(body='USD 25,000'))['T1']
    assert not reachability.conditions(row, dict(body='KRW 125,000'))['T1']
    assert reachability.conditions(row, dict(body='JPY 2000.50'))['T1']
    report = reachability.measure([dict(row, posting_date='2025-11-12')], [evidence], {})
    assert report['candidates'] == 0


def test_no_evidence_schema_prevents_all_changes():
    props = offline.schema({}, ['식비'])['properties']
    assert props['item']['enum'] == ['기존 항목 유지']
    assert props['trip_id']['enum'] == ['기존 여행 유지']
    assert props['service_start']['enum'] == ['']
    assert props['service_end']['enum'] == ['']
    assert props['evidence_refs']['maxItems'] == 0


def test_toolfree_call_guard_and_private_cwd(monkeypatch):
    monkeypatch.setattr(offline.provider, '_executable', lambda: 'synthetic-codex')
    raw = dict(item='식비', trip_id='T', service_start='2026-11-12', service_end='2026-11-13',
               confidence='중간', basis='synthetic', uncertainty='', evidence_refs=['E'])
    def runner(command, **kwargs):
        assert '--sandbox' in command and '--output-schema' in command
        assert list(Path(kwargs['cwd']).iterdir()) == []
        events = [dict(type='turn.started'), dict(type='item.completed', item=dict(type='agent_message', text=json.dumps(raw))), dict(type='turn.completed')]
        return SimpleNamespace(returncode=0, stderr=b'', stdout='\n'.join(json.dumps(e) for e in events).encode())
    result = offline.call(dict(candidate_trips=['T'], existing_trip='T', evidence=[dict(ref='E', excerpt='no dates')]), ['식비'], runner=runner)
    assert result['raw']['service_start'] == '2026-11-12'
    assert result['guarded']['service_start'] == result['guarded']['service_end'] == ''
