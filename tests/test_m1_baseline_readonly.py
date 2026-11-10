"""Exercise the baseline guards in isolated children using synthetic files only."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


TOOL = Path(__file__).resolve().parents[1] / 'docs/agents/artifacts/m1-baseline-20261111.py'
PROBE = r'''
import importlib.util,json,os,socket,sqlite3,subprocess,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('baseline_probe',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
path=Path(sys.argv[2])
action=sys.argv[3]
module.install_read_only_guards()
if action=='read':
    conn=module.read_connection(path)
    assert conn.execute('PRAGMA query_only').fetchone()[0]==1
    assert conn.execute('SELECT value FROM probe').fetchone()[0]=='SYNTHETIC_ONLY'
    conn.close()
    outcome='allowed'
else:
    def attempt():
        if action=='sql_write':
            conn=module.read_connection(path)
            conn.execute("UPDATE probe SET value='MUTATED'")
        elif action=='write_connection':
            sqlite3.connect(path)
        elif action=='rw_uri':
            sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
        elif action=='file_write':
            path.write_bytes(b'MUTATED')
        elif action=='file_delete':
            path.unlink()
        elif action=='network':
            socket.socket()
        elif action=='subprocess':
            subprocess.run([sys.executable,'--version'],check=True)
        elif action=='shell':
            os.system('exit 0')
        else:
            raise AssertionError('unknown probe')
    try:
        attempt()
    except (RuntimeError,sqlite3.OperationalError):
        outcome='refused'
    else:
        raise AssertionError('effect unexpectedly allowed')
print(json.dumps({'outcome':outcome}))
'''


@pytest.mark.parametrize('action', [
    'read', 'sql_write', 'write_connection', 'rw_uri', 'file_write',
    'file_delete', 'network', 'subprocess', 'shell',
])
def test_baseline_guards_allow_reads_and_refuse_effects_in_child(tmp_path, action):
    database = tmp_path / 'synthetic.sqlite'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE probe(value TEXT NOT NULL)')
        conn.execute("INSERT INTO probe VALUES('SYNTHETIC_ONLY')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, '-I', '-c', PROBE, str(TOOL), str(database), action],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'outcome': 'allowed' if action == 'read' else 'refused'}
    assert database.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ['synthetic.sqlite']
