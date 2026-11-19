"""Windows-only extended-path (`\\\\?\\`) refusal for the OTA solver-input tool.

`\\\\?\\` is Windows path syntax: on Linux that string is an ordinary relative
name, so the assertion would pass or fail for the wrong reason. The hard-link
form of the same refusal stays in tests/test_core_bridge_ota_input.py and runs on
every platform.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from tools.core_bridge import golden  # noqa: E402
from tools.core_bridge.cli import handle  # noqa: E402
from tests.test_core_bridge_ota_input import request  # noqa: E402


def test_live_file_is_refused_through_an_extended_path(tmp_path):
    req = request(tmp_path)
    live = Path(req['host_root']) / 'data' / 'board.sqlite'
    shutil.copy(req['db'], live)
    given = '\\\\?\\' + str(live.resolve())
    response = handle('ota-input', dict(req, db=given), sha='')
    assert not response['ok'] and response['error']['code'] == 'DB_IS_LIVE'
    assert not Path(req['out']).exists()
