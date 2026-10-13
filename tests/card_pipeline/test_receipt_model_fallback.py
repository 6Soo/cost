import json
import subprocess

import pytest

from app import opencode_receipt_vision as vision

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
ALLOWED = {vision.MODEL, vision.SPACE_BUNNY, vision.INKLING}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    image = tmp_path / 'slip.png'
    image.write_bytes(PNG)
    monkeypatch.setenv('WEBLEDGER_RECEIPT_VISION', 'opencode-muse-free')
    monkeypatch.setenv('WEBLEDGER_OPENCODE_EXE', __file__)
    monkeypatch.delenv('WEBLEDGER_RECEIPT_INKLING', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    vision._COOLING.clear()
    return str(image)


def ok_text(receipts=None):
    text = json.dumps({'receipts': receipts if receipts is not None else [
        {'merchant': 'SHOP', 'date': '2026-10-01', 'amount': 820, 'currency': 'JPY', 'payment': 'cash',
         'category_hint': None, 'note': None}]}, ensure_ascii=False)
    return _proc(0, [{'type': 'text', 'part': {'type': 'text', 'text': text}}])


def provider_error(status, headers=None, message='provider said no'):
    data = {'message': message, 'statusCode': status, 'isRetryable': status in (429, 503)}
    if headers:
        data['responseHeaders'] = headers
    return _proc(1, [{'type': 'error', 'error': {'name': 'APIError', 'data': data}}])


def _proc(code, events):
    body = ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events).encode('utf-8')
    return type('Proc', (), {'returncode': code, 'stdout': body, 'stderr': b''})()


class Script:
    """Answers each model with a prepared outcome and records every call."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def __call__(self, command, *, cwd, env):
        model = command[command.index('--model') + 1]
        self.calls.append(model)
        assert model in ALLOWED, f'unexpected model {model}'
        assert '--pure' in command and any(a.startswith('--file=') for a in command)
        outcome = self.outcomes[model]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_muse_answers_and_nothing_else_is_called(ready):
    script = Script({vision.MODEL: ok_text})
    result = vision.recognize_with_fallback(ready, runner=script)
    assert script.calls == [vision.MODEL]
    assert result['label'] == 'Muse' and result['model'] == vision.MODEL and len(result['receipts']) == 1


def test_an_empty_muse_answer_is_a_result_not_a_failure(ready):
    script = Script({vision.MODEL: lambda: ok_text(receipts=[])})
    result = vision.recognize_with_fallback(ready, runner=script)
    assert result['receipts'] == [] and script.calls == [vision.MODEL]


def test_a_rate_limit_moves_to_space_bunny_and_muse_waits(ready):
    clock = Clock()
    script = Script({vision.MODEL: lambda: provider_error(429, {'retry-after': '120'}),
                     vision.SPACE_BUNNY: ok_text})
    result = vision.recognize_with_fallback(ready, runner=script, clock=clock)
    assert result['label'] == 'Space Bunny' and script.calls == [vision.MODEL, vision.SPACE_BUNNY]
    clock.now += 60
    script.calls.clear()
    again = vision.recognize_with_fallback(ready, runner=script, clock=clock)
    assert script.calls == [vision.SPACE_BUNNY] and again['label'] == 'Space Bunny'
    clock.now += 61
    script.calls.clear()
    vision.recognize_with_fallback(ready, runner=script, clock=clock)
    assert script.calls[0] == vision.MODEL


def test_an_outage_503_moves_to_space_bunny(ready):
    script = Script({vision.MODEL: lambda: provider_error(503), vision.SPACE_BUNNY: ok_text})
    assert vision.recognize_with_fallback(ready, runner=script)['label'] == 'Space Bunny'


def test_a_timeout_or_network_failure_is_treated_as_temporary(ready):
    script = Script({vision.MODEL: subprocess.TimeoutExpired('opencode', 120), vision.SPACE_BUNNY: ok_text})
    assert vision.recognize_with_fallback(ready, runner=script)['label'] == 'Space Bunny'
    script = Script({vision.MODEL: lambda: provider_error(500, message='fetch failed'), vision.SPACE_BUNNY: ok_text})
    vision._COOLING.clear()
    assert vision.recognize_with_fallback(ready, runner=script)['label'] == 'Space Bunny'


def test_both_free_models_down_without_inkling_ends_in_manual_entry(ready):
    script = Script({vision.MODEL: lambda: provider_error(429), vision.SPACE_BUNNY: lambda: provider_error(503)})
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(ready, runner=script)
    assert error.value.code == 'VISION_ALL_MODELS_UNAVAILABLE'
    assert script.calls == [vision.MODEL, vision.SPACE_BUNNY]


def test_inkling_is_not_called_without_owner_approval_even_with_a_key(ready, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'not-a-real-key')
    script = Script({vision.MODEL: lambda: provider_error(429), vision.SPACE_BUNNY: lambda: provider_error(503)})
    with pytest.raises(vision.VisionUnavailable):
        vision.recognize_with_fallback(ready, runner=script)
    assert vision.INKLING not in script.calls


def test_inkling_is_used_only_when_approved_and_connected(ready, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_RECEIPT_INKLING', 'approved')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'not-a-real-key')
    script = Script({vision.MODEL: lambda: provider_error(429), vision.SPACE_BUNNY: lambda: provider_error(503),
                     vision.INKLING: ok_text})
    result = vision.recognize_with_fallback(ready, runner=script)
    assert result['label'] == 'Inkling Free' and script.calls == [vision.MODEL, vision.SPACE_BUNNY, vision.INKLING]


def test_inkling_stays_off_when_approved_but_not_connected(ready, monkeypatch, tmp_path):
    monkeypatch.setenv('WEBLEDGER_RECEIPT_INKLING', 'approved')
    monkeypatch.setattr(vision.Path, 'home', classmethod(lambda cls: tmp_path))
    assert vision.inkling_enabled() is False and vision.INKLING not in vision.chain()


def test_a_forbidden_or_policy_refusal_is_never_routed_around(ready):
    script = Script({vision.MODEL: lambda: provider_error(403, message="OpenCode's free tier can only be used from within OpenCode")})
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(ready, runner=script)
    assert error.value.code == 'VISION_PROVIDER_ERROR' and script.calls == [vision.MODEL]


def test_an_unreadable_answer_is_a_quality_problem_not_an_outage(ready):
    bad = lambda: _proc(0, [{'type': 'text', 'part': {'type': 'text', 'text': 'not json at all'}}])
    script = Script({vision.MODEL: bad, vision.SPACE_BUNNY: ok_text})
    with pytest.raises(vision.VisionUnavailable):
        vision.recognize_with_fallback(ready, runner=script)
    assert script.calls == [vision.MODEL]


def test_a_missing_opencode_program_is_not_retried_on_another_model(ready, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_OPENCODE_EXE', 'C:/no/such/opencode.exe')
    monkeypatch.setattr(vision, '_opencode_executable', lambda: None)
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(ready, runner=Script({}))
    assert error.value.code == 'VISION_OPENCODE_NOT_FOUND'


def test_only_free_model_ids_can_ever_be_requested(ready):
    assert vision.MODEL.startswith('opencode/') and vision.SPACE_BUNNY.startswith('opencode/')
    assert ':free' in vision.INKLING and set(vision.chain()) <= ALLOWED
