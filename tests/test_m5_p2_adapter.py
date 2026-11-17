"""Exercise the prepared-request boundary without a subscription model call."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.connected_agent_provider import AgentUnavailable
from app.frontier_agent_provider import DISABLED_FEATURES
from tools import m5_p2_adapter as adapter


def request():
    payload = {'merchants': [{'merchant_id': 'synthetic-a', 'merchant': '합성 상점'}],
               'allowed_items': ['사무용품비'], 'policy': '합성 규칙'}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {**payload, 'run_id': 'abc123', 'request_digest': digest}


def answer(payload):
    return {'request_digest': payload['request_digest'], 'run_id': payload['run_id'],
            'results': [{'merchant_id': 'synthetic-a', 'item': '사무용품비',
                         'confidence': '높음', 'basis': '합성 문구류 구매 근거'}]}


def events(result, *, tool=False):
    values = [{'type': 'thread.started'}, {'type': 'turn.started'}]
    if tool:
        values.append({'type': 'item.completed', 'item': {'type': 'command_execution', 'text': 'untrusted'}})
    values.extend([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(result)}},
                   {'type': 'turn.completed'}])
    return '\n'.join(json.dumps(value) for value in values).encode()


def test_queue_binding_and_tool_blocking_survive_actual_adapter_command(monkeypatch):
    payload = request()
    monkeypatch.setattr(adapter.provider, '_executable', lambda: 'synthetic-codex.exe')

    def runner(command, *, cwd, env, timeout, input_bytes):
        assert list(Path(cwd).iterdir()) == []
        assert timeout == 240
        assert {'--ignore-user-config', '--ignore-rules', '--strict-config', '--ephemeral'} <= set(command)
        assert command[command.index('--model') + 1] == 'gpt-6.1-sol'
        assert 'approval_policy="never"' in command and 'model_provider="openai"' in command
        assert all('features.' + name + '=false' in command for name in DISABLED_FEATURES)
        assert payload['request_digest'] in input_bytes.decode('utf-8')
        assert json.loads(Path(command[command.index('--output-schema') + 1]).read_text(encoding='utf-8'))['additionalProperties'] is False
        return subprocess.CompletedProcess(command, 0, events(answer(payload)), b'')

    assert adapter.run(payload, runner=runner) == answer(payload)


@pytest.mark.parametrize('mutation', ['digest', 'duplicate', 'run_id'])
def test_bad_queue_binding_is_rejected_before_model_discovery(monkeypatch, mutation):
    payload = request()
    if mutation == 'digest':
        payload['request_digest'] = '0' * 64
    elif mutation == 'duplicate':
        payload['merchants'].append(payload['merchants'][0])
    else:
        payload['run_id'] = 'not-hex'
    monkeypatch.setattr(adapter.provider, '_executable', lambda: pytest.fail('model must not start'))
    with pytest.raises(ValueError, match='BATCH_(REQUEST|BINDING)_INVALID'):
        adapter.run(payload)


def test_provider_tool_event_and_wrong_run_are_rejected(monkeypatch):
    payload = request()
    monkeypatch.setattr(adapter.provider, '_executable', lambda: 'synthetic-codex.exe')
    with pytest.raises(AgentUnavailable) as error:
        adapter.run(payload, runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, events(answer(payload), tool=True), b''))
    assert error.value.code == 'AGENT_TOOL_EXECUTION_DETECTED'
    forged = answer(payload)
    forged['run_id'] = 'def456'
    with pytest.raises(ValueError, match='BATCH_BINDING_INVALID'):
        adapter.run(payload, runner=lambda *a, **k: subprocess.CompletedProcess(a, 0, events(forged), b''))


def test_empty_bound_batch_never_starts_a_provider(monkeypatch):
    payload = request()
    payload['merchants'] = []
    binding = {key: payload[key] for key in ('merchants', 'allowed_items', 'policy')}
    payload['request_digest'] = hashlib.sha256(
        json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    monkeypatch.setattr(adapter.provider, '_executable', lambda: pytest.fail('empty batch must not call provider'))
    assert adapter.run(payload) == {'request_digest': payload['request_digest'],
                                    'run_id': payload['run_id'], 'results': []}


def test_cli_failure_never_echoes_source_or_parser_exception():
    source = b'{"customer-secret": "synthetic-private-value"}'
    done = subprocess.run([sys.executable, '-I', str(Path(adapter.__file__))],
                          input=source, capture_output=True, timeout=15)
    assert done.returncode == 2
    assert json.loads(done.stdout)['error'] == 'BATCH_REQUEST_INVALID'
    assert b'synthetic-private-value' not in done.stdout + done.stderr
