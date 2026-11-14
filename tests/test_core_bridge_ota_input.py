"""OTA solver-input capture (M3 2nd cutover C1): same input as ``_data``, golden-equal results, live and repo-path refusals."""
import copy
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from tools.core_bridge import golden, ota_input
from tools.core_bridge.cli import handle
from tools.core_bridge.commands import canonical
from tools.core_bridge.synthetic import scenario_db

ROOT = Path(__file__).resolve().parents[1]
CASES = [(n, case) for n, case in enumerate(golden._ota_inputs()) if not case[3]]


class StubPayments:
    """The real solver, with the event builder replaced by synthetic events (no mail or portal sources)."""

    def __init__(self, events, record=None):
        from app import ota_payments
        self.real, self.events, self.record = ota_payments, events, record

    def __getattr__(self, name):
        return getattr(self.real, name)

    def build_ota_payment_events(self, sources, **kwargs):
        return copy.deepcopy(self.events)

    def match_ota_payment_events(self, events, transactions, **kwargs):
        if self.record is not None:
            self.record.append(canonical({'kind': 'ota', 'events': events, 'transactions': transactions,
                                          'existing_links': kwargs.get('existing_links'), 'rules': kwargs.get('rules'),
                                          'frozen_groups': kwargs.get('frozen_groups')}))
        return self.real.match_ota_payment_events(events, transactions, **kwargs)


def review_copy(folder):
    path = Path(folder) / 'ota-review.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE ota_review_marker(x)')
    conn.close()
    return path


def board_copy(cards, folder):
    with scenario_db({'rows': cards}) as path:
        target = Path(folder) / 'board-copy.sqlite'
        shutil.copy(path, target)
    return target


def host(tmp_path):
    (tmp_path / 'data' / 'backups').mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.mark.parametrize('index,case', CASES[:12], ids=[c[1][0][:30] for c in CASES[:12]])
def test_captured_input_equals_what_data_gives_the_solver_and_matches_the_golden(index, case, tmp_path):
    from webapp.ota_payment_review import CoreOtaPaymentBackend
    import app.ota_review as review
    note, events, cards, _extra = case
    board, review_db = board_copy(cards, tmp_path), review_copy(tmp_path)
    sources = {'mail_directories': []}
    captured = ota_input.solver_input(board, review_db, sources, payments=StubPayments(events))

    recorded = []
    with ota_input.closing(sqlite3.connect(board.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        backend = CoreOtaPaymentBackend(ota_input._ReadOnlyBoard(conn, board), str(review_db), read_only=True,
                                        payments=StubPayments(events, recorded), store_type=review.OtaReviewStore,
                                        sources=sources)
        try:
            backend._data()
        finally:
            backend.close()
    assert recorded == [canonical(captured)]

    expected = json.loads((golden.GOLDEN_DIR / 'ota_links.jsonl').read_text(encoding='utf-8').splitlines()[index])
    response = handle('links', canonical(captured), sha='')
    assert response['ok'] and response['result'] == expected['expected'], note


def test_written_file_is_the_solver_input_and_rust_shaped(tmp_path):
    note, events, cards, _extra = CASES[0][1]
    board, review_db = board_copy(cards, tmp_path), review_copy(tmp_path)
    data = ota_input.solver_input(board, review_db, {'mail_directories': []}, payments=StubPayments(events))
    out = host(tmp_path / 'host') / 'data' / 'backups' / 'ota-input.json'
    counts = ota_input.write_input(out, data)
    written = json.loads(out.read_text(encoding='utf-8'))
    assert written == canonical(data) and written['kind'] == 'ota'
    assert counts['events'] == 1 and counts['transactions'] == 1 and set(counts) >= {'sha256', 'rules'}
    with pytest.raises(FileExistsError):
        ota_input.write_input(out, data)


def request(tmp_path, **changes):
    from app.ota_store import OtaStore
    root = host(tmp_path / 'host')
    cards = [golden._card('syn-t1')]
    store = OtaStore(tmp_path / 'ota-evidence-copy.sqlite')
    store.conn.close()
    base = {'db': str(board_copy(cards, tmp_path)), 'ota_evidence': str(tmp_path / 'ota-evidence-copy.sqlite'),
            'review_db': str(review_copy(tmp_path)), 'host_root': str(root),
            'out': str(root / 'data' / 'backups' / 'c1' / 'ota-input.json')}
    return dict(base, **changes)


def test_command_writes_a_protected_file_from_copies(tmp_path):
    req = request(tmp_path)
    response = handle('ota-input', req, sha='')
    assert response['ok'], response
    assert response['result']['events'] == 0 and response['result']['transactions'] == 1
    assert Path(req['out']).is_file()


@pytest.mark.parametrize('name', ['board.sqlite', 'ota-evidence.sqlite', 'ota-review/ota-review.sqlite'])
def test_live_host_databases_are_refused(tmp_path, name):
    req = request(tmp_path)
    live = Path(req['host_root']) / 'data' / name
    live.parent.mkdir(parents=True, exist_ok=True)
    key = {'board.sqlite': 'db', 'ota-evidence.sqlite': 'ota_evidence'}.get(name, 'review_db')
    shutil.copy(req[key], live)
    response = handle('ota-input', dict(req, **{key: str(live)}), sha='')
    assert not response['ok'] and response['error']['code'] == 'DB_IS_LIVE'
    assert not Path(req['out']).exists()


@pytest.mark.parametrize('out,code', [
    (ROOT / 'outputs' / 'ota-input.json', 'OUT_INSIDE_REPO'),
    (ROOT / 'data' / 'backups' / 'ota-input.json', 'OUT_INSIDE_REPO'),
])
def test_output_inside_the_repository_is_refused(tmp_path, out, code):
    response = handle('ota-input', request(tmp_path, out=str(out)), sha='')
    assert not response['ok'] and response['error']['code'] == code
    assert not out.exists()


def test_output_outside_the_protected_folder_is_refused(tmp_path):
    response = handle('ota-input', request(tmp_path, out=str(tmp_path / 'elsewhere.json')), sha='')
    assert not response['ok'] and response['error']['code'] == 'OUT_NOT_PROTECTED'


def test_live_refusal_comes_before_any_read(tmp_path):
    req = request(tmp_path)
    live = Path(req['host_root']) / 'data' / 'board.sqlite'
    response = handle('ota-input', dict(req, db=str(live)), sha='')
    assert response['error']['code'] == 'DB_IS_LIVE' and not live.exists()


def test_cli_accepts_the_command_name():
    import subprocess
    proc = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'core_bridge' / 'cli.py'), 'ota-input'],
                          input='{}\n', text=True, capture_output=True, encoding='utf-8')
    assert json.loads(proc.stdout)['error']['code'] == 'DB_REQUIRED'
