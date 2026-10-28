"""Static-map safety and connectivity contracts using synthetic tracked sources."""
import json
import subprocess


def repository(tmp_path, sources):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for name, source in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    return tmp_path


def test_route_service_repository_sql_chain_without_literals_or_imports(tmp_path):
    from tools.refactor_call_map import build_map
    root = repository(tmp_path, {
        'webapp/api.py': 'from app.service import run\n@router.get("/PRIVATE_SENTINEL")\ndef handler():\n    return run()\n',
        'app/service.py': 'from .repo import save\ndef run():\n    return save()\n',
        'app/repo.py': 'raise RuntimeError("MUST_NOT_IMPORT")\ndef save():\n    conn.execute("INSERT INTO rows VALUES (?)", ("SECRET_SENTINEL",))\n',
    })
    result = build_map(root)
    assert result['errors'] == []
    edges = {(e['source'], e.get('target')) for e in result['calls']}
    assert ('webapp/api.py:handler', 'app/service.py:run') in edges
    assert ('app/service.py:run', 'app/repo.py:save') in edges
    assert result['routes'][0]['symbol'] == 'handler'
    assert result['effects'][0]['table'] == 'rows'
    assert result['effects'][0]['owner'] == 'app/repo.py:save'
    assert result['repositories'] == [{'path': 'app/repo.py', 'symbol': 'save', 'line': 2,
                                       'status': 'STATIC_CANDIDATE'}]
    assert result['services'] == [{'path': 'app/service.py', 'symbol': 'run', 'line': 2,
                                   'status': 'STATIC_CANDIDATE'}]
    assert result['tables'][0]['table'] == 'rows'
    encoded = json.dumps(result)
    assert 'PRIVATE_SENTINEL' not in encoded
    assert 'SECRET_SENTINEL' not in encoded
    assert 'MUST_NOT_IMPORT' not in encoded


def test_dynamic_receivers_stay_unresolved_and_nested_scopes_do_not_leak(tmp_path):
    from tools.refactor_call_map import build_map
    result = build_map(repository(tmp_path, {'webapp/api.py':
        'def save(): pass\nclass Handler:\n    def save(self): pass\n    def handle(self, other):\n        self.save()\n        other.save()\n        def nested():\n            save()\n'}))
    calls = result['calls']
    assert any(e.get('target') == 'webapp/api.py:Handler.save' for e in calls)
    assert any(e['call'] == 'other.save' and e['status'] == 'OPEN_QUESTION' for e in calls)
    assert any(e['source'] == 'webapp/api.py:Handler.handle.nested' for e in calls)


def test_untracked_non_python_and_indirect_files_are_not_read(tmp_path):
    from tools.refactor_call_map import build_map
    root = repository(tmp_path, {'app/safe.py': 'def run(): pass', 'app/original.json': 'SECRET_SENTINEL'})
    (root / 'app/untracked.py').write_text('broken SENTINEL', encoding='utf-8')
    result = build_map(root)
    assert [f['path'] for f in result['files']] == ['app/safe.py']
    assert 'SENTINEL' not in json.dumps(result)


def test_route_tuple_and_unknown_sql_and_effect_locations(tmp_path):
    from tools.refactor_call_map import build_map
    result = build_map(repository(tmp_path, {'webapp/api.py':
        'class App:\n    def routes(self):\n        return [("GET", "PRIVATE_SENTINEL", self.handle)]\n    def handle(self):\n        conn.execute(sql)\n        subprocess.run(["SECRET_SENTINEL"])\n'}))
    assert any(r['symbol'] == 'App.handle' for r in result['routes'])
    assert any(e['status'] == 'OPEN_QUESTION' and e['kind'] == 'sql_unknown' for e in result['effects'])
    assert any(e['kind'] == 'external_candidate' for e in result['effects'])
    assert 'SENTINEL' not in json.dumps(result)


def test_permission_signals_are_explicitly_unresolved_and_outputs_are_complete(tmp_path):
    from tools.refactor_call_map import build_map, summary
    result = build_map(repository(tmp_path, {'webapp/api.py':
        '@require_owner\ndef handle():\n    pass\n'}))
    assert result['permission_signals'] == [{'path': 'webapp/api.py', 'symbol': 'handle',
        'line': 2, 'signals': ['require_owner'], 'status': 'OPEN_QUESTION'}]
    assert summary(result)['counts']['permission_signals'] == 1


def test_invalid_source_reports_location_without_source(tmp_path):
    from tools.refactor_call_map import build_map
    result = build_map(repository(tmp_path, {'app/broken.py': 'def SECRET_SENTINEL(:'}))
    assert result['errors'] == [{'path': 'app/broken.py', 'code': 'SYNTAX_ERROR', 'line': 1}]
    assert 'SECRET_SENTINEL' not in json.dumps(result)


def test_http_dispatch_methods_are_entrypoints_even_without_decorators(tmp_path):
    from tools.refactor_call_map import build_map
    result = build_map(repository(tmp_path, {'webapp/api.py':
        'class Handler:\n    def do_GET(self):\n        self.service()\n    def service(self): pass\n'}))
    assert any(r['symbol'] == 'Handler.do_GET' for r in result['routes'])
    assert any(c.get('target') == 'webapp/api.py:Handler.service' for c in result['calls'])


def test_store_assignment_in_one_function_does_not_resolve_another_function(tmp_path):
    from tools.refactor_call_map import build_map
    root = repository(tmp_path, {
        'webapp/ledger_store.py': 'class LedgerStore:\n    def save(self): pass\n',
        'webapp/api.py': (
            'def _active_store(): pass\n'
            'def first():\n    store = _active_store()\n    store.save()\n'
            'def second():\n    store.save()\n'
        ),
    })
    result = build_map(root)
    second = next(c for c in result['calls'] if c['source'] == 'webapp/api.py:second')
    assert second['status'] == 'OPEN_QUESTION'
    assert 'target' not in second


def test_annotated_assignment_call_is_indexed_once(tmp_path):
    from tools.refactor_call_map import build_map
    result = build_map(repository(tmp_path, {
        'app/api.py': 'def run(): pass\ndef handler():\n    value: object = run()\n',
    }))
    calls = [c for c in result['calls'] if c['call'] == 'run']
    assert len(calls) == 1


def test_limit_output_preserves_valid_json_under_utf8_byte_cap():
    from tools.refactor_call_map import truncate_to_limit
    result = {
        'schema': 'rf001-call-map/v1',
        'mode': 'static_ast_only',
        'code_sha': 'a' * 40,
        'files': [{'path': '가나다' * 100, 'symbols': 1} for _ in range(50)],
        'symbols': [], 'calls': [], 'routes': [], 'effects': [], 'errors': [],
        'limitations': [],
    }
    limited = truncate_to_limit(result, limit=512)
    encoded = json.dumps(limited, ensure_ascii=False, indent=2).encode('utf-8')
    assert len(encoded) <= 512
    assert json.loads(encoded.decode('utf-8'))['truncated'] is True


def test_map_provenance_separates_base_revision_from_dirty_tracked_inputs(tmp_path):
    from tools.refactor_call_map import build_map
    root = repository(tmp_path, {'app/safe.py': 'def run(): pass\n'})
    subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Synthetic'], check=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'synthetic@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'baseline'], check=True)

    clean = build_map(root)
    assert clean['base_sha'] == clean['code_sha']
    assert clean['working_tree_dirty'] is False

    (root / 'app/safe.py').write_text('def changed(): pass\n', encoding='utf-8')
    dirty = build_map(root)
    assert dirty['base_sha'] == clean['base_sha']
    assert dirty['code_sha'] == clean['base_sha']
    assert dirty['working_tree_dirty'] is True
