"""WEBLEDGER_LINKS_PRODUCER: the refund-pair producer switch (default Python), its cache and its failure behaviour.

The Rust-versus-Python equivalence of the contract itself is fixed by the Rust golden tests. Here the adapter runs against
a stand-in `costcore` that answers `links refund` from the Python bridge (always), and against the real binary when
COSTCORE_TEST_BIN names one (tools/run_quality_checks.py builds it and sets the variable for files carrying the
`costcore_bin` marker; the equivalence runs below are parametrized over both).
"""
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

from app import core_links
from app import partial_refund as pr
from tools.core_bridge import commands, golden
from tools.core_bridge.synthetic import scenario_db

REAL = os.environ.get('COSTCORE_TEST_BIN', '')


def _cases(area='refund_pairing'):
    path = golden.GOLDEN_DIR / f'{area}.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def _scenarios():
    seen = []
    for area in ('refund_pairing', 'refund_groups'):
        for case in _cases(area):
            seen.append((f"{case['area']}-{case['case_id']}", case['input']['scenario']))
    return seen


def _build(tmp_path, scenario, name='board.sqlite'):
    target = tmp_path / name
    with scenario_db(scenario) as source, closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.commit()
    return target


class StandIn:
    """subprocess.run replacement: `--version` text and `links refund` answered from the Python bridge."""

    def __init__(self, version='costcore 9.9.9'):
        self.version, self.runs, self.fail = version, [], None

    def __call__(self, command, **kwargs):
        if command[1] == '--version':
            return subprocess.CompletedProcess(command, 0, stdout=self.version + '\n', stderr='')
        assert command[1:3] == ['links', 'refund'] and command[3] == '--db'
        self.runs.append(command[4])
        if self.fail:
            return subprocess.CompletedProcess(command, 2, stdout=json.dumps(
                {'ok': False, 'error': {'code': self.fail}}) + '\n', stderr='')
        saved = os.environ.pop(core_links.PRODUCER_ENV, None)  # the stand-in is the Python derivation
        try:
            result = commands.links({'kind': 'refund', 'db': command[4]})
        finally:
            if saved is not None:
                os.environ[core_links.PRODUCER_ENV] = saved
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({'ok': True, 'result': result}) + '\n', stderr='')


@pytest.fixture
def stand_in(monkeypatch, tmp_path):
    binary = tmp_path / 'costcore-stand-in'
    binary.write_text('stand-in', encoding='utf-8')
    monkeypatch.setenv(core_links.BIN_ENV, str(binary))
    fake = StandIn()
    monkeypatch.setattr(core_links.subprocess, 'run', fake)
    core_links.clear_cache()
    yield fake
    core_links.clear_cache()


@pytest.fixture(params=['stand-in', 'real'])
def producer(request, monkeypatch, tmp_path):
    """The binary the rust producer calls: the stand-in, or the real costcore when COSTCORE_TEST_BIN is set."""
    monkeypatch.delenv(core_links.PRODUCER_ENV, raising=False)
    core_links.clear_cache()
    if request.param == 'real':
        request.applymarker(pytest.mark.costcore_bin)
        if not REAL:
            pytest.skip('COSTCORE_TEST_BIN not set: real-binary equivalence not run here')
        monkeypatch.setenv(core_links.BIN_ENV, REAL)
        yield None
    else:
        binary = tmp_path / 'costcore-stand-in'
        binary.write_text('stand-in', encoding='utf-8')
        monkeypatch.setenv(core_links.BIN_ENV, str(binary))
        fake = StandIn()
        monkeypatch.setattr(core_links.subprocess, 'run', fake)
        yield fake
    core_links.clear_cache()


def _observe(path):
    """Everything the call sites read, through the public functions of partial_refund."""
    with closing(sqlite3.connect(path)) as conn:
        ids = [r[0] for r in conn.execute('SELECT transaction_id FROM transactions ORDER BY transaction_id')]
        links = pr.refund_links(conn, ids)
        originals = sorted({link['original_id'] for link in links.values()})
        return {
            'links': links,
            'originals': pr.refund_original_links(conn, ids),
            'groups': {o: pr.refund_group(conn, o) for o in originals},
            'exclusions': {o: pr.partial_group_exclusion(conn, o) for o in originals},
            'held': pr.count_held_cancellations(conn),
            'review': pr.refund_review_originals(conn),
            'kakao': pr.kakao_refund_candidates(conn),
        }


def _both(monkeypatch, path):
    monkeypatch.delenv(core_links.PRODUCER_ENV, raising=False)
    python = _observe(path)
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    return python, _observe(path)


# --- default and selection -----------------------------------------------------------------

@pytest.mark.parametrize('value', [None, '', 'python', 'PYTHON', 'rusty', 'true', '1'])
def test_python_is_the_default_producer_and_every_other_value_keeps_it(monkeypatch, tmp_path, value, stand_in):
    if value is None:
        monkeypatch.delenv(core_links.PRODUCER_ENV, raising=False)
    else:
        monkeypatch.setenv(core_links.PRODUCER_ENV, value)
    assert core_links.selected() == 'python'
    monkeypatch.setattr(core_links, 'analyse', lambda conn: pytest.fail('core producer used'))
    path = _build(tmp_path, _scenarios()[2][1])
    assert _observe(path)['links']
    assert stand_in.runs == []


def test_only_rust_selects_the_core_and_unsetting_returns_to_python(monkeypatch):
    monkeypatch.setenv(core_links.PRODUCER_ENV, ' Rust ')
    assert core_links.selected() == 'rust'
    monkeypatch.delenv(core_links.PRODUCER_ENV)
    assert core_links.selected() == 'python'


def test_the_producer_switch_is_independent_of_the_classification_writer(monkeypatch):
    from app import core_writer
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    monkeypatch.delenv(core_writer.WRITER_ENV, raising=False)
    assert (core_links.selected(), core_writer.selected()) == ('rust', 'python')
    monkeypatch.delenv(core_links.PRODUCER_ENV)
    monkeypatch.setenv(core_writer.WRITER_ENV, 'rust')
    assert (core_links.selected(), core_writer.selected()) == ('python', 'rust')


# --- equivalence -----------------------------------------------------------------------------

@pytest.mark.parametrize('name,scenario', _scenarios(), ids=[n for n, _ in _scenarios()])
def test_rust_producer_equals_python_on_every_golden_scenario(producer, monkeypatch, tmp_path, name, scenario):
    path = _build(tmp_path, scenario)
    python, rust = _both(monkeypatch, path)
    assert rust == python


@pytest.mark.parametrize('case_id,expect', [
    ('refund_pairing-006', {'links': {'excess'}}),
    ('refund_pairing-012', {'links': set()}),
    ('refund_pairing-013', {'links': set()}),
    ('refund_pairing-014', {'links': set()}),
    ('refund_pairing-015', {'links': set()}),
    ('refund_pairing-016', {'exclusion': 'unclean_member'}),
    ('refund_pairing-017', {'exclusion': 'unclean_member'}),
    ('refund_pairing-018', {'exclusion': 'completed_period'}),
])
def test_protections_hold_through_the_same_functions_with_the_rust_producer(
        producer, monkeypatch, tmp_path, case_id, expect):
    """Excess refund, duplicate and ambiguous originals, conflicted or errored sources, completed periods."""
    scenario = next(c['input']['scenario'] for c in _cases() if c['case_id'] == case_id)
    path = _build(tmp_path, scenario)
    _python, rust = _both(monkeypatch, path)
    if 'links' in expect:
        assert {link['status'] for link in rust['links'].values()} == expect['links']
    if 'exclusion' in expect:
        assert set(rust['exclusions'].values()) == {expect['exclusion']}
    # The ledger's guards read these same functions: an excluded partial group stays out of recording.
    assert rust['review'] == sorted(set(rust['review']))


# --- cache -------------------------------------------------------------------------------------

def test_cache_hits_across_connections_and_ignores_columns_the_derivation_does_not_read(
        stand_in, monkeypatch, tmp_path):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    first = _observe(path)
    runs = len(stand_in.runs)
    assert runs == 1
    assert _observe(path) == first and len(stand_in.runs) == runs  # new connections, same content
    with closing(sqlite3.connect(path)) as conn:  # a classification write does not move a pairing input
        conn.execute("UPDATE transactions SET item='x', revision=revision+1, classification_state='decided'")
        conn.commit()
    assert _observe(path) == first and len(stand_in.runs) == runs


@pytest.mark.parametrize('change', [
    "UPDATE transactions SET duplicate_of='syn-r1' WHERE transaction_id='syn-r2'",
    "UPDATE transactions SET conflict_reason='x' WHERE transaction_id='syn-r1'",
    "UPDATE transactions SET parse_error='x' WHERE transaction_id='syn-r2'",
    "UPDATE transactions SET original_approval_number='SYN-A-r9' WHERE transaction_id='syn-r2'",
    "UPDATE transactions SET amount_krw=-3333 WHERE transaction_id='syn-r2'",
    "DELETE FROM transactions WHERE transaction_id='syn-r2'",
])
def test_changing_a_source_row_without_touching_revision_recomputes(stand_in, monkeypatch, tmp_path, change):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    before = _observe(path)
    assert before['links'] and len(stand_in.runs) == 1
    with closing(sqlite3.connect(path)) as conn:
        revisions = conn.execute('SELECT SUM(revision) FROM transactions').fetchone()
        conn.execute(change)
        conn.commit()
        assert conn.execute('SELECT SUM(revision) FROM transactions').fetchone()[0] <= revisions[0]
    after = _observe(path)
    assert len(stand_in.runs) == 2
    monkeypatch.delenv(core_links.PRODUCER_ENV)
    assert after == _observe(path)  # the recomputed Rust answer is the Python answer for the new rows
    assert after != before


def test_a_different_binary_version_or_file_state_recomputes(stand_in, monkeypatch, tmp_path):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    _observe(path)
    stand_in.version = 'costcore 9.9.10'
    _observe(path)
    assert len(stand_in.runs) == 1  # same file state: the version text is read once per file state
    Path(os.environ[core_links.BIN_ENV]).write_text('stand-in v2 replaced', encoding='utf-8')
    _observe(path)
    assert len(stand_in.runs) == 2


# --- failure ---------------------------------------------------------------------------------

def test_a_costcore_error_fails_the_call_and_never_falls_back_to_python(stand_in, monkeypatch, tmp_path):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    monkeypatch.setattr(pr, '_analyse_python', lambda conn: pytest.fail('quiet Python fallback'))
    path = _build(tmp_path, _scenarios()[2][1])
    stand_in.fail = 'STORE_ERROR'
    with closing(sqlite3.connect(path)) as conn:
        for call in (lambda: pr.refund_links(conn, ['syn-r2']), lambda: pr.refund_group(conn, 'syn-r1'),
                     lambda: pr.partial_group_exclusion(conn, 'syn-r1'), lambda: pr.count_held_cancellations(conn),
                     lambda: pr.refund_review_originals(conn)):
            with pytest.raises(RuntimeError, match='STORE_ERROR'):
                call()


def test_unusable_binary_output_and_missing_configuration_fail(monkeypatch, tmp_path, stand_in):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    monkeypatch.setattr(core_links.subprocess, 'run', lambda command, **kw: subprocess.CompletedProcess(
        command, 0, stdout='not json\n' if command[1] == 'links' else 'costcore 1\n', stderr=''))
    with closing(sqlite3.connect(path)) as conn, pytest.raises(RuntimeError, match='CORE_LINKS_NO_RESPONSE'):
        pr.refund_links(conn, ['syn-r2'])
    monkeypatch.delenv(core_links.BIN_ENV)
    with closing(sqlite3.connect(path)) as conn, pytest.raises(RuntimeError, match='CORE_LINKS_NOT_CONFIGURED'):
        pr.refund_links(conn, ['syn-r2'])


def test_an_in_memory_database_has_no_file_for_costcore_to_read(stand_in, monkeypatch):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    conn = sqlite3.connect(':memory:')
    with pytest.raises(RuntimeError, match='CORE_LINKS_NEEDS_FILE_DATABASE'):
        core_links.analyse(conn)


def test_uncommitted_source_rows_are_refused_but_an_unchanged_open_transaction_is_served(
        stand_in, monkeypatch, tmp_path):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE transactions SET item='x'")  # a transaction open, pairing inputs unchanged
        assert conn.in_transaction
        assert pr.refund_links(conn, ['syn-r2'])
        conn.execute("UPDATE transactions SET conflict_reason='x' WHERE transaction_id='syn-r1'")
        with pytest.raises(RuntimeError, match='CORE_LINKS_UNCOMMITTED_ROWS'):
            pr.refund_links(conn, ['syn-r2'])
        conn.rollback()
        assert pr.refund_links(conn, ['syn-r2'])


def test_an_original_the_core_did_not_link_is_an_error_not_a_guess(stand_in, monkeypatch, tmp_path):
    monkeypatch.setenv(core_links.PRODUCER_ENV, 'rust')
    path = _build(tmp_path, _scenarios()[2][1])
    with closing(sqlite3.connect(path)) as conn, pytest.raises(RuntimeError, match='CORE_LINKS_ORIGINAL_NOT_LINKED'):
        pr.partial_group_exclusion(conn, 'syn-r2')
