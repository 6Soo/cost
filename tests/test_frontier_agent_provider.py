import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import frontier_agent_provider as provider
from app.connected_agent_provider import AgentUnavailable


def stream(answer, item=None):
    events = [{'type': 'thread.started', 'thread_id': 'synthetic-thread'}]
    if item:
        events.append({'type': 'item.completed', 'item': item})
    events.extend([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}},
                   {'type': 'turn.completed', 'usage': {}}])
    return '\n'.join(json.dumps(e) for e in events).encode()


def test_extract_only_final_completed_response():
    assert provider.parse_events(stream({'results': [], 'more_evidence': []}))['results'] == []


@pytest.mark.parametrize('kind', ['command_execution', 'mcp_tool_call', 'web_search',
                                  'image_view', 'collab_tool_call', 'file_change', 'unknown_tool'])
def test_reject_any_tool_event_even_if_final_json_valid(kind):
    with pytest.raises(AgentUnavailable, match='AGENT_TOOL_EXECUTION_DETECTED'):
        provider.parse_events(stream({'results': []}, {'type': kind, 'status': 'completed'}))


def test_rate_limit_and_incomplete_turn():
    with pytest.raises(AgentUnavailable, match='AGENT_RATE_LIMITED'):
        provider.parse_events(b'{"type":"turn.failed","error":{"message":"usage limit reached"}}')
    with pytest.raises(AgentUnavailable, match='AGENT_RESPONSE_INVALID'):
        provider.parse_events(b'{"type":"thread.started","thread_id":"x"}')


def test_runner_receives_stdin_empty_cwd_and_tool_disabled_config(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, '_executable', lambda: 'synthetic-codex.exe')
    monkeypatch.setattr(provider, 'schema_path', lambda: tmp_path / 'schema.json')
    (tmp_path / 'schema.json').write_text('{}')
    observed = []

    def runner(command, *, cwd, env, timeout, input_bytes):
        observed.append((command, input_bytes))
        assert list(Path(cwd).iterdir()) == []
        assert b'raw synthetic evidence' in input_bytes
        assert 'raw synthetic evidence' not in ' '.join(command)
        assert '--ignore-user-config' in command and '--strict-config' in command
        assert command[command.index('--sandbox') + 1] == 'read-only'
        assert 'approval_policy="never"' in command
        assert 'mcp_servers={}' in command and 'web_search="disabled"' in command
        for feature in ('shell_tool', 'unified_exec', 'apps', 'plugins', 'remote_plugin',
                        'browser_use', 'computer_use', 'view_image', 'multi_agent', 'hooks'):
            assert 'features.' + feature + '=false' in command
        run_id = json.loads(input_bytes.decode().split('\nEXECUTION:')[1].split('\n', 1)[0])['run_id']
        answer = dict(request_digest='digest', execution=dict(kind='connected_agent', provider='codex',
                      model='gpt-6.1-sol', run_id=run_id), results=[], more_evidence=[])
        return subprocess.CompletedProcess(command, 0, stream(answer), b'')

    result = provider.run_agent({'digest': 'digest'}, bundle={'evidence': 'raw synthetic evidence'}, runner=runner)
    assert result['execution']['provider'] == 'codex'
    assert len(observed) == 1


def test_made_up_execution_identity_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, '_executable', lambda: 'synthetic-codex.exe')
    monkeypatch.setattr(provider, 'schema_path', lambda: tmp_path / 'schema.json')
    (tmp_path / 'schema.json').write_text('{}')
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stream(dict(request_digest='digest',
            execution=dict(kind='connected_agent', provider='codex', model='gpt-6.1-sol', run_id='invented'),
            results=[], more_evidence=[])), b'')
    with pytest.raises(AgentUnavailable, match='AGENT_EXECUTION_MISMATCH'):
        provider.run_agent({'digest': 'digest'}, bundle={}, runner=runner)


def test_bounded_subprocess_stdin_and_actual_output_cap(tmp_path):
    from app.connected_agent_provider import _run_bounded
    import os
    result = _run_bounded([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'],
                          cwd=tmp_path, env=dict(os.environ), timeout=5, input_bytes='합성 stdin'.encode())
    assert result.stdout.decode() == '합성 stdin'
    with pytest.raises(AgentUnavailable, match='AGENT_RESPONSE_TOO_LARGE'):
        _run_bounded([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(b"x"*1000000)'],
                     cwd=tmp_path, env=dict(os.environ), timeout=5)
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded([sys.executable, '-c', 'import time; time.sleep(15)'],
                     cwd=tmp_path, env=dict(os.environ), timeout=.1)
    assert time.monotonic() - started < 5
