import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app import sync_schedule as ss

T0 = dt.datetime(2026, 10, 11, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def test_second_run_is_refused_while_the_first_holds_the_lock(tmp_path: Path):
    lock_path = tmp_path / "sync.lock"
    with ss.SyncLock(lock_path, now=T0):
        with pytest.raises(ss.LockHeld, match="SYNC_ALREADY_RUNNING"):
            with ss.SyncLock(lock_path, now=T0 + dt.timedelta(minutes=1)):
                pass
    with ss.SyncLock(lock_path, now=T0 + dt.timedelta(minutes=2)):
        pass  # released after the first run, so a later run gets it


def test_old_timestamp_does_not_let_a_second_run_take_over_a_live_lock(tmp_path: Path):
    lock_path = tmp_path / "sync.lock"
    with ss.SyncLock(lock_path, now=T0):
        with pytest.raises(ss.LockHeld):
            with ss.SyncLock(lock_path, now=T0 + dt.timedelta(days=2)):
                pass


def test_release_keeps_the_lock_file_and_a_later_run_can_take_it(tmp_path: Path):
    lock_path = tmp_path / "sync.lock"
    with ss.SyncLock(lock_path, now=T0):
        pass
    assert lock_path.exists()
    with ss.SyncLock(lock_path, now=T0 + dt.timedelta(hours=1)):
        pass


def test_a_leftover_file_with_no_holder_does_not_block(tmp_path: Path):
    lock_path = tmp_path / "sync.lock"
    lock_path.write_text('{"started_at": "%s", "pid": 1}' % T0.isoformat(), encoding="utf-8")
    with ss.SyncLock(lock_path, now=T0 + dt.timedelta(minutes=1)):
        pass


def test_lock_is_released_even_when_the_run_fails(tmp_path: Path):
    lock_path = tmp_path / "sync.lock"
    with pytest.raises(RuntimeError):
        with ss.SyncLock(lock_path, now=T0):
            raise RuntimeError("boom")
    with ss.SyncLock(lock_path, now=T0):
        pass  # released despite the failure


def test_failures_back_off_exponentially_and_cap(tmp_path: Path):
    state_path = tmp_path / "state.json"
    waits = []
    now = T0
    for _ in range(8):
        state = ss.record_result(state_path, ok=False, now=now, error_code="SOURCE_UNREACHABLE")
        waits.append(dt.datetime.fromisoformat(state["next_attempt_at"]) - now)
        now = dt.datetime.fromisoformat(state["next_attempt_at"])
    assert waits[0] == ss.BACKOFF_BASE and waits[1] == ss.BACKOFF_BASE * 2
    assert max(waits) == ss.BACKOFF_CAP
    assert ss.read_state(state_path)["last_error"] == "SOURCE_UNREACHABLE"


def test_success_clears_backoff_and_records_time(tmp_path: Path):
    state_path = tmp_path / "state.json"
    ss.record_result(state_path, ok=False, now=T0, error_code="X")
    state = ss.record_result(state_path, ok=True, now=T0 + dt.timedelta(hours=1))
    assert state["consecutive_failures"] == 0 and state["next_attempt_at"] is None
    assert ss.may_attempt(state, T0)


@pytest.mark.parametrize('failures', [40, 10000])
def test_long_outage_keeps_capped_retry_and_can_recover(tmp_path, failures):
    import json
    state_path = tmp_path / 'state.json'
    state_path.write_text(json.dumps({'consecutive_failures': failures, 'last_ok_at': T0.isoformat(),
                                      'last_error': 'SOURCE_UNREACHABLE', 'next_attempt_at': None}))
    failed = ss.record_result(state_path, ok=False, now=T0, error_code='SOURCE_UNREACHABLE')
    assert failed['consecutive_failures'] == failures + 1
    assert dt.datetime.fromisoformat(failed['next_attempt_at']) == T0 + ss.BACKOFF_CAP
    assert failed['last_ok_at'] == T0.isoformat()
    recovered = ss.record_result(state_path, ok=True, now=T0 + ss.BACKOFF_CAP)
    assert recovered['consecutive_failures'] == 0 and recovered['next_attempt_at'] is None


def test_retry_is_refused_inside_the_backoff_window(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state = ss.record_result(state_path, ok=False, now=T0, error_code="X")
    assert not ss.may_attempt(state, T0 + dt.timedelta(minutes=1))
    assert ss.may_attempt(state, T0 + ss.BACKOFF_BASE)


def test_example_task_is_disabled_hourly_and_points_nowhere_real():
    xml_path = Path(__file__).resolve().parents[2] / "tools" / "google_authority_sync.task.example.xml"
    root = ET.parse(xml_path).getroot()
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find("t:Settings/t:Enabled", ns).text == "false"
    trigger = root.find("t:Triggers/t:CalendarTrigger", ns)
    assert trigger.find("t:Enabled", ns).text == "false"
    assert trigger.find("t:Repetition/t:Interval", ns).text == "PT1H"
    assert trigger.find("t:StartBoundary", ns).text.startswith("2026-10-12T00:00:00+09:00")
    arguments = root.find("t:Actions/t:Exec/t:Arguments", ns).text
    assert "PLACEHOLDER" in arguments and "D:" not in arguments  # placeholders only


def test_cli_refuses_while_backing_off_and_does_not_read_google(tmp_path: Path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "google_authority_sync", Path(__file__).resolve().parents[2] / "tools" / "google_authority_sync.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    snapshot = tmp_path / "snapshot.json"
    ss.record_result(tmp_path / "sync-state.json", ok=False, now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))),
                     error_code="SOURCE_UNREACHABLE")
    monkeypatch.setattr(cli.google_authority, "sync", lambda *a, **k: pytest.fail("must not read Google"))
    assert cli.main(["--snapshot", str(snapshot), "--rows", str(tmp_path / "rows.json")]) == 3


@pytest.mark.parametrize('state_text', [
    'PRIVATE-INVALID-JSON', '[]', '{}',
    '{"consecutive_failures": -1, "last_ok_at": null, "last_error": null, "next_attempt_at": null}',
    '{"consecutive_failures": true, "last_ok_at": null, "last_error": null, "next_attempt_at": null}',
    '{"consecutive_failures": "1", "last_ok_at": null, "last_error": null, "next_attempt_at": null}',
    '{"consecutive_failures": 1, "last_ok_at": null, "last_error": "X", "next_attempt_at": "2026-10-11T09:00:00"}',
    '{"consecutive_failures": 1, "last_ok_at": "PRIVATE-BAD-TIME", "last_error": "X", "next_attempt_at": null}',
])
def test_cli_refuses_invalid_retry_state_without_touching_last_good(tmp_path, monkeypatch, capsys, state_text):
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location(
        'sync_cli_invalid_state_test', Path(__file__).resolve().parents[2] / 'tools' / 'google_authority_sync.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    state = tmp_path / 'sync-state.json'
    state.write_text(state_text, encoding='utf-8')
    snapshot = tmp_path / 'snapshot.json'
    rows = tmp_path / 'rows.json'
    snapshot.write_bytes(b'LAST-GOOD-SNAPSHOT')
    rows.write_bytes(b'LAST-GOOD-PRIVATE-ROWS')
    monkeypatch.setattr(cli.google_authority, 'sync', lambda *a, **k: pytest.fail('must not read Google'))
    assert cli.main(['--snapshot', str(snapshot), '--rows', str(rows)]) == 6
    assert json.loads(capsys.readouterr().out) == {'code': 'SYNC_STATE_UNAVAILABLE'}
    assert snapshot.read_bytes() == b'LAST-GOOD-SNAPSHOT'
    assert rows.read_bytes() == b'LAST-GOOD-PRIVATE-ROWS'
    assert state.read_text(encoding='utf-8') == state_text
    with ss.SyncLock(tmp_path / 'sync.lock', now=T0):
        pass


@pytest.mark.parametrize('snapshot_error', [False, True])
def test_cli_holds_lock_while_reading_backoff_and_recording_result(tmp_path, monkeypatch, snapshot_error):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'sync_cli_lock_test', Path(__file__).resolve().parents[2] / 'tools' / 'google_authority_sync.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    held = False
    calls = []

    class Lock:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            nonlocal held
            held = True

        def __exit__(self, *args):
            nonlocal held
            held = False

    def read_state(path):
        assert held, 'backoff must be read after acquiring the writer lock'
        calls.append('read')
        return {'next_attempt_at': None}

    def sync(*args, **kwargs):
        assert held
        calls.append('sync')
        if snapshot_error:
            raise cli.google_authority.SnapshotError('SYNTHETIC_FAILURE')
        return {'sources': {}, 'trips': []}

    def record_result(*args, **kwargs):
        assert held, 'release only after recording the retry state'
        calls.append('record')
        assert kwargs['ok'] is (not snapshot_error)

    monkeypatch.setattr(cli.sync_schedule, 'SyncLock', Lock)
    monkeypatch.setattr(cli.sync_schedule, 'read_state', read_state)
    monkeypatch.setattr(cli.sync_schedule, 'record_result', record_result)
    monkeypatch.setattr(cli.google_authority, 'sync', sync)
    status = cli.main(['--snapshot', str(tmp_path / 'snapshot.json'), '--rows', str(tmp_path / 'rows.json')])
    assert status == (2 if snapshot_error else 0)
    assert calls == ['read', 'sync', 'record'] and held is False


def test_a_separate_live_process_keeps_the_lock(tmp_path: Path):
    import subprocess
    import sys
    lock_path = tmp_path / "sync.lock"
    repo = Path(__file__).resolve().parents[2]
    script = (
        "import sys, time, datetime as dt\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from app.sync_schedule import SyncLock\n"
        f"with SyncLock({str(lock_path)!r}, now=dt.datetime.now(dt.timezone.utc)):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(4)\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(ss.LockHeld):
            with ss.SyncLock(lock_path, now=T0 + dt.timedelta(days=1)):
                pass
    finally:
        holder.wait(timeout=30)
    with ss.SyncLock(lock_path, now=T0):
        pass  # the holder exited, so the lock is free again
