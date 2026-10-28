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
