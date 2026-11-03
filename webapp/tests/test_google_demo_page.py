import json
from urllib.parse import urlparse

import pytest

from webapp import google_demo_page as page


def trip(key, net, **over):
    base = {"key": key, "closure": "closed", "closure_current": True, "canonical_source": "archive",
            "income_total": net + 100, "expense_total": 100, "net": net, "verified": True, "review": [],
            "copies": {"archive": {"layout": "rev", "income": {"verified": True, "total": net + 100},
                                     "expense": {"verified": True, "total": 100}}}}
    base.update(over)
    return base


def snap(trips, *, synthetic=True, status="ok"):
    doc = {"synced_at": "2026-10-11T10:00:00+09:00", "sources": {"main": {"status": status}},
           "trips": trips}
    if synthetic:
        doc["synthetic"] = True
    return doc


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send_json(self, value, code=200, extra_headers=None):
        self.sent.append(("json", code, value))

    def _send(self, text, code=200):
        self.sent.append(("html", code, text))


@pytest.fixture
def demo_file(tmp_path, monkeypatch):
    path = tmp_path / "demo-snapshot.json"
    path.write_text(json.dumps(snap([trip("SYN-A", 900), trip("SYN-B", 700), trip("SYN-C", 500),
                                     trip("SYN-D", 100)])), encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_DEMO_SNAPSHOT", str(path))
    return path


def get(path):
    handler = FakeHandler()
    assert page.dispatch(handler, urlparse(path)) is True
    return handler.sent[0]


def test_off_without_setting(monkeypatch):
    monkeypatch.delenv("WEBLEDGER_DEMO_SNAPSHOT", raising=False)
    assert page.dispatch(FakeHandler(), urlparse("/api/demo/top3")) is False


def test_real_snapshot_without_synthetic_flag_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "real.json"
    path.write_text(json.dumps(snap([trip("REAL", 1)], synthetic=False)), encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_DEMO_SNAPSHOT", str(path))
    kind, code, body = get("/api/demo/top3")
    assert code == 503 and body["code"] == "DEMO_NOT_SYNTHETIC"


def test_json_carries_rank_and_amounts_but_no_titles_or_keys(demo_file):
    _, code, body = get("/api/demo/top3")
    assert code == 200 and [e["net"] for e in body["entries"]] == [900, 700, 500]
    text = json.dumps(body, ensure_ascii=False)
    assert "SYN-" not in text and "key" not in body["entries"][0] and "sheet" not in text


def test_html_has_no_titles(demo_file):
    _, code, html_text = get("/demo")
    assert code == 200 and "SYN-" not in html_text and "900원" in html_text


def test_failed_sync_shows_the_last_safe_ranking_marked_stale(demo_file):
    get("/api/demo/top3")  # stores the safe payload
    demo_file.write_text(json.dumps(snap([trip("SYN-A", 1)], status="error")), encoding="utf-8")
    _, code, body = get("/api/demo/top3")
    assert body["stale"] is True and [e["net"] for e in body["entries"]] == [900, 700, 500]


def test_unchanged_projection_does_not_rewrite_cache(demo_file, monkeypatch):
    get('/api/demo/top3')
    def refuse_replacement(*args):
        raise AssertionError('unchanged projection must not replace cache')
    monkeypatch.setattr(page.os, 'replace', refuse_replacement)
    assert get('/api/demo/top3')[1] == 200


def test_write_methods_are_refused(demo_file):
    handler = FakeHandler()
    page.dispatch(handler, urlparse("/api/demo/top3"), raw=b"{}")
    assert handler.sent[0][:2] == ("json", 405)


def test_other_paths_are_not_ours(demo_file):
    assert page.dispatch(FakeHandler(), urlparse("/import")) is False


def test_production_projection_requires_both_current_sources_and_filters_sensitive_data():
    import datetime as dt
    now = dt.datetime.fromisoformat('2026-10-11T10:00:00+09:00')
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now.isoformat()}
    trips = [trip('SECRET-A', 900, owner_id='aslan', kind='trip'),
             trip('SECRET-B', 700, owner_id='aslan', kind='trip'),
             trip('SECRET-C', 500, owner_id='aslan', kind='trip'),
             trip('SECRET-Q', 9999, owner_id='aslan', kind='quarter')]
    snapshot = {'schema': 'google-authority-readonly-v2', 'synced_at': now.isoformat(),
                'sources': {'main': dict(source), 'archive': dict(source)}, 'trips': trips}
    payload = page.prepare_real_demo(snapshot, {}, now=now)
    assert [entry['net'] for entry in payload['entries']] == [900, 700, 500]
    assert 'SECRET' not in json.dumps(payload)
    snapshot['sources'].pop('archive')
    assert page.prepare_real_demo(snapshot, {}, now=now)['status'] == 'preparing'


def test_production_projection_refuses_wrong_figures_and_stale_sources():
    import datetime as dt
    now = dt.datetime.fromisoformat('2026-10-11T10:00:00+09:00')
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now.isoformat()}
    bad = trip('SECRET', 500, owner_id='aslan', kind='trip')
    bad['net'] = 1
    snapshot = {'schema': 'google-authority-readonly-v2', 'synced_at': now.isoformat(),
                'sources': {'main': dict(source), 'archive': dict(source)}, 'trips': [bad]}
    assert page.prepare_real_demo(snapshot, {}, now=now)['entries'] == []
    snapshot['sources']['main']['last_ok_at'] = '2026-10-10T10:00:00+09:00'
    assert page.prepare_real_demo(snapshot, {}, now=now)['status'] == 'preparing'


def test_real_snapshot_requires_separate_gate_and_never_returns_source_fields(tmp_path, monkeypatch):
    import datetime as dt
    from webapp import google_ledger_page
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now}
    doc = {'schema': 'google-authority-readonly-v2', 'synced_at': now,
           'sources': {'main': dict(source), 'archive': dict(source)},
           'trips': [trip('SECRET-A', 900, owner_id='aslan', kind='trip'),
                     trip('SECRET-B', 700, owner_id='aslan', kind='trip'),
                     trip('SECRET-C', 500, owner_id='aslan', kind='trip')]}
    path = tmp_path / 'authority.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_DEMO_SNAPSHOT', str(path))
    monkeypatch.delenv('WEBLEDGER_DEMO_REAL_PUBLICATION', raising=False)
    monkeypatch.setattr(google_ledger_page, 'load_choices', lambda _: {})
    assert get('/api/demo/top3')[1] == 503
    monkeypatch.setenv('WEBLEDGER_DEMO_REAL_PUBLICATION', '1')
    _, status, body = get('/api/demo/top3')
    assert status == 200 and [item['net'] for item in body['entries']] == [900, 700, 500]
    assert 'SECRET' not in json.dumps(body)
    assert 'SECRET' not in (tmp_path / 'demo-real-last-safe.json').read_text(encoding='utf-8')


def test_real_projection_uses_owner_copy_choice_and_rejects_ambiguous_identity():
    import datetime as dt
    now = dt.datetime.fromisoformat('2026-10-11T10:00:00+09:00')
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now.isoformat()}
    value = trip('SECRET-A', 900, owner_id='aslan', kind='trip')
    value['copies']['main'] = {'layout': 'rev', 'income': {'verified': True, 'total': 500},
                               'expense': {'verified': True, 'total': 100}}
    snapshot = {'schema': 'google-authority-readonly-v2', 'synced_at': now.isoformat(),
                'sources': {'main': dict(source), 'archive': dict(source)}, 'trips': [value]}
    assert page.prepare_real_demo(snapshot, {}, now=now)['entries'] == []
    chosen = page.prepare_real_demo(snapshot, {'choices': {'SECRET-A': 'main'}}, now=now)
    assert chosen['entries'][0]['net'] == 400
    value['review'] = ['POSSIBLE_DUPLICATE']
    assert page.prepare_real_demo(snapshot, {'choices': {'SECRET-A': 'main'}}, now=now)['entries'] == []


def test_real_projection_rejects_identifying_text_in_timestamp():
    snapshot = {'schema': 'google-authority-readonly-v2', 'synced_at': 'SECRET-NAME',
                'sources': {}, 'trips': []}
    assert 'SECRET' not in json.dumps(page.prepare_real_demo(snapshot, {}))


@pytest.mark.parametrize('stamp', ['2020-01-01T00:00:00+09:00', '2030-01-01T00:00:00+09:00'])
def test_real_projection_rejects_stale_or_future_snapshot_timestamp(stamp):
    import datetime as dt
    now = dt.datetime.fromisoformat('2026-10-11T10:00:00+09:00')
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now.isoformat()}
    snapshot = {'schema': 'google-authority-readonly-v2', 'synced_at': stamp,
                'sources': {'main': dict(source), 'archive': dict(source)},
                'trips': [trip('SECRET', 900, owner_id='aslan', kind='trip')]}
    assert page.prepare_real_demo(snapshot, {}, now=now)['entries'] == []


def test_real_failure_never_reuses_synthetic_cache(demo_file, monkeypatch):
    assert get('/api/demo/top3')[2]['entries']
    monkeypatch.setenv('WEBLEDGER_DEMO_REAL_PUBLICATION', '1')
    assert get('/api/demo/top3')[2]['entries'] == []
    demo_file.unlink()
    assert get('/api/demo/top3')[2]['entries'] == []


def test_successful_authority_sync_refreshes_safe_demo_before_any_public_request(tmp_path, monkeypatch):
    import datetime as dt
    from app import google_authority
    from tools import google_authority_sync as sync_cli
    from webapp import google_ledger_page

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now,
              'error_code': None, 'trips': []}
    snapshot = {'schema': google_authority.SCHEMA, 'synced_at': now,
                'sources': {'main': dict(source), 'archive': dict(source)},
                'trips': [trip('PRIVATE-TRIP', 900, owner_id='aslan', kind='trip')]}
    path, rows = tmp_path / 'authority.json', tmp_path / 'rows.json'
    monkeypatch.setenv('WEBLEDGER_DEMO_SNAPSHOT', str(path))
    monkeypatch.setenv('WEBLEDGER_DEMO_REAL_PUBLICATION', '1')
    monkeypatch.setattr(google_ledger_page, 'load_choices', lambda _: {})

    def sync(*args, **kwargs):
        path.write_text(json.dumps(snapshot), encoding='utf-8')
        return snapshot

    monkeypatch.setattr(google_authority, 'sync', sync)
    assert sync_cli.main(['--snapshot', str(path), '--rows', str(rows)]) == 0
    cache = tmp_path / 'demo-real-last-safe.json'
    assert cache.exists()
    content = cache.read_text(encoding='utf-8')
    assert 'PRIVATE-TRIP' not in content
    assert json.loads(content)['entries'][0]['net'] == 900
    snapshot['sources']['archive'].update(status='error', stale=True, error_code='SOURCE_UNREACHABLE')
    assert sync_cli.main(['--snapshot', str(path), '--rows', str(rows)]) == 1
    assert cache.read_text(encoding='utf-8') == content
    body = get('/api/demo/top3')[2]
    assert body['stale'] is True and body['entries'][0]['net'] == 900
    path.unlink()
    body = get('/api/demo/top3')[2]
    assert body['stale'] is True and body['entries'][0]['net'] == 900


def test_sync_refresh_is_disabled_by_default_and_requires_same_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'authority.json'
    monkeypatch.setenv('WEBLEDGER_DEMO_SNAPSHOT', str(path))
    monkeypatch.delenv('WEBLEDGER_DEMO_REAL_PUBLICATION', raising=False)
    assert page.refresh_after_sync(path) == 'disabled'
    monkeypatch.setenv('WEBLEDGER_DEMO_REAL_PUBLICATION', '1')
    assert page.refresh_after_sync(tmp_path / 'different.json') == 'different_snapshot'
    assert list(tmp_path.iterdir()) == []


def test_demo_refresh_failure_does_not_break_source_sync_or_leak_error(tmp_path, monkeypatch, capsys):
    from app import google_authority
    from tools import google_authority_sync as sync_cli
    source = {'status': 'ok', 'stale': False, 'error_code': None, 'trips': []}
    monkeypatch.setattr(google_authority, 'sync', lambda *a, **k: {
        'sources': {'main': dict(source), 'archive': dict(source)}, 'trips': []})

    def fail(_):
        raise RuntimeError('PRIVATE-SYNTHETIC-DETAIL')

    monkeypatch.setattr(page, 'refresh_after_sync', fail)
    assert sync_cli.main(['--snapshot', str(tmp_path / 'snapshot.json'),
                          '--rows', str(tmp_path / 'rows.json')]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['demo_refresh'] == 'unavailable'
    assert 'PRIVATE-SYNTHETIC-DETAIL' not in output


def test_busy_cache_returns_only_sanitized_last_safe_projection(demo_file):
    import datetime as dt
    from app import sync_schedule
    get('/api/demo/top3')
    cache = demo_file.with_name('demo-last-safe.json')
    old = json.loads(cache.read_text(encoding='utf-8'))
    old['private'] = 'PRIVATE-NAME'
    old['entries'][0]['private'] = 'PRIVATE-NAME'
    cache.write_text(json.dumps(old), encoding='utf-8')
    with sync_schedule.SyncLock(demo_file.with_name('demo-cache.lock'), now=dt.datetime.now(dt.timezone.utc)):
        body = get('/api/demo/top3')[2]
    assert body['stale'] is True
    assert body['entries'][0]['net'] == 900
    assert 'PRIVATE-NAME' not in json.dumps(body)


def test_owner_preview_is_read_only_and_never_exposes_source_fields(tmp_path, monkeypatch):
    import datetime as dt
    from webapp import google_ledger_page
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source = {'status': 'ok', 'stale': False, 'last_ok_at': now}
    doc = {'schema': 'google-authority-readonly-v2', 'synced_at': now,
           'sources': {'main': dict(source), 'archive': dict(source)},
           'trips': [trip('SECRET-A', 900, owner_id='aslan', kind='trip')]}
    path = tmp_path / 'authority.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(path))
    monkeypatch.delenv('WEBLEDGER_DEMO_REAL_PUBLICATION', raising=False)
    monkeypatch.setattr(google_ledger_page, 'load_choices', lambda _: {})
    denied = FakeHandler()
    assert page.dispatch_preview(denied, urlparse('/demo/preview'), is_owner=False)
    assert denied.sent[0][1] == 403
    owner = FakeHandler()
    assert page.dispatch_preview(owner, urlparse('/demo/preview'), is_owner=True)
    assert owner.sent[0][1] == 200 and '900원' in owner.sent[0][2]
    assert 'SECRET' not in owner.sent[0][2]
    assert sorted(p.name for p in tmp_path.iterdir()) == ['authority.json']
