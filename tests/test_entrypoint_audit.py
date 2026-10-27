import json
import subprocess
from tools.audit_entrypoints import analyze, inventory


def test_routes_handlers_async_and_calls_without_source_literals():
    result = analyze('''
class Handler:
    def do_POST(self):
        if parsed.path == '/api/save':
            store.save('CUSTOMER_SENTINEL')
        elif parsed.path.startswith('/api/events/'):
            dispatch()
async def background():
    await worker.run()
if __name__ == '__main__':
    main()
''', 'webapp/synthetic.py')
    assert [(x['route'], x['method']) for x in result['routes']] == [('/api/save', 'POST'), ('/api/events/', 'POST')]
    assert result['main_guard_candidate']
    assert result['callables'][-1]['async']
    assert all(x['resolution'] == 'UNVERIFIED' for x in result['calls'])
    assert 'CUSTOMER_SENTINEL' not in json.dumps(result)


def test_tracked_source_only_and_syntax_error_metadata(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    for relative, source in [('app/safe.py', 'def main(): pass'), ('webapp/broken.py', 'def broken(:'),
                             ('tests/test_ignored.py', 'raise RuntimeError()'), ('outputs/raw.py', 'raise RuntimeError()')]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    (tmp_path / 'app/untracked.py').write_text('raise RuntimeError()', encoding='utf-8')
    result = inventory(tmp_path)
    assert [x['path'] for x in result['modules']] == ['app/safe.py']
    assert result['errors'] == [{'path': 'webapp/broken.py', 'code': 'SYNTAX_ERROR', 'line': 1}]


def test_source_is_not_executed_and_dynamic_dispatch_stays_unresolved():
    result = analyze("raise RuntimeError('DO_NOT_RUN')\nhandler = registry[key]\nhandler()", 'app/synthetic.py')
    assert result['routes'] == []
    assert result['calls'][-1]['resolution'] == 'UNVERIFIED'
    assert 'DO_NOT_RUN' not in json.dumps(result)
