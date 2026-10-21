"""The Aside collector must verify the flight detail's booking number."""
import json
import shutil
import subprocess

import pytest

from tools.collect_agoda_aside import PRELUDE


def test_collector_prelude_compiles_after_repl_line_flattening():
    if not shutil.which('node'):
        pytest.skip('node is needed to execute the collector JavaScript')
    flattened = PRELUDE.replace('\r', '').replace('\n', ' ')
    script = 'void (' + flattened + ');'
    result = subprocess.run(['node', '--check', '--input-type=commonjs'],
                            input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_flight_detail_identity_uses_adjacent_booking_label():
    if not shutil.which('node'):
        pytest.skip('node is needed to execute the collector JavaScript')
    matcher = next(line.strip() for line in PRELUDE.splitlines()
                   if line.strip().startswith('const flightIds='))
    valid = '- text: "10월 15일 (수) 탑승객 2명•편도 예약 번호:"\n- generic "1625180324" [ref=e29]'
    invalid = '- text: "총 금액:"\n- generic "1625180324" [ref=e29]'
    for tree, expected in ((valid, ['1625180324']), (invalid, [])):
        script = 'const s={tree:' + json.dumps(tree, ensure_ascii=False) + '};\n'
        script += matcher + '\n'
        script += 'if(JSON.stringify(flightIds)!==' + json.dumps(json.dumps(expected)) + ')process.exit(1);'
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
