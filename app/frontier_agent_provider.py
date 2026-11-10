"""Direct subscription Codex adapter with tools disabled by CLI configuration.

This is an application tool-surface restriction, not an OS isolation claim.
No Claude/Paseo fallback is registered without equivalent verification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from .connected_agent_provider import AgentUnavailable, MAX_OUTPUT_BYTES, _run_bounded
from . import p2_case

MODEL = 'gpt-6.1-sol'
TIMEOUT_SECONDS = 180
# Feature names checked against Codex 0.160.0 `features list`; exec uses
# strict-config to reject unsupported keys on each invocation. Ignore user
# config keeps authentication but removes user MCP/plugin/provider hooks.
DISABLED_FEATURES = (
    'shell_tool', 'unified_exec', 'unified_exec_tty', 'shell_snapshot',
    'apps', 'plugins', 'remote_plugin', 'plugin_sharing',
    'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
    'computer_use', 'in_app_browser', 'in_app_local_automation', 'view_image',
    'image_generation', 'multi_agent', 'multi_agent_v2', 'agent_message_board',
    'hooks', 'code_mode', 'code_mode_host', 'code_mode_only', 'code_mode_prewarm',
    'skill_search', 'skill_mcp_dependency_install', 'workspace_dependencies',
    'request_permissions_tool', 'default_mode_request_user_input', 'auth_elicitation',
    'tool_suggest', 'tool_call_mcp_elicitation', 'sleep_tool', 'goals', 'memories',
    'standalone_web_search',
    'realtime_conversation', 'daemon_auto_start',
)
CODE_MODE_DISABLED_NOTICE = ('Code Mode is unavailable because code-mode host is disabled. '
    'Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.')


def schema_path():
    return Path(__file__).with_name('p2_output.schema.json')


def bundle_budget():
    # Reserve actual schema UTF-8 bytes plus bounded execution/instruction text.
    return p2_case.MAX_BYTES - len(schema_path().read_bytes()) - 2048


def _executable():
    found = os.environ.get('WEBLEDGER_CODEX_EXE') or shutil.which('codex.exe') or shutil.which('codex')
    if not found:
        return None
    path = Path(found)
    if path.suffix.lower() in ('.ps1', '.cmd', '.bat'):
        vendor = path.parent / 'node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
        return str(vendor) if vendor.is_file() else None
    return str(path)


def config_args():
    values = ['approval_policy="never"', 'web_search="disabled"', 'mcp_servers={}',
              'project_doc_max_bytes=0', 'skills.bundled.enabled=false',
              'analytics.enabled=false', 'feedback.enabled=false']
    values.extend('features.' + name + '=false' for name in DISABLED_FEATURES)
    return [arg for value in values for arg in ('-c', value)]


def _error(value):
    text = json.dumps(value).lower()
    if any(word in text for word in ('rate limit', 'usage limit', 'quota', '429', 'limit reached')):
        raise AgentUnavailable('AGENT_RATE_LIMITED', 300)
    raise AgentUnavailable('AGENT_EXECUTION_FAILED')


def parse_events(raw):
    if len(raw) > MAX_OUTPUT_BYTES:
        raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
    final, complete, turn_started = None, False, False
    try:
        for line in raw.decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event['type']
            if kind in ('error', 'turn.failed'):
                _error(event)
            if kind in ('item.started', 'item.updated', 'item.completed'):
                item = event['item']
                if item.get('type') == 'error':
                    if not turn_started and item.get('message') == CODE_MODE_DISABLED_NOTICE:
                        continue
                    _error(item)
                if item.get('type') not in ('agent_message', 'reasoning'):
                    raise AgentUnavailable('AGENT_TOOL_EXECUTION_DETECTED')
                if kind == 'item.completed' and item.get('type') == 'agent_message':
                    final = item['text']
            elif kind == 'turn.completed':
                complete = True
            elif kind == 'turn.started':
                turn_started = True
            elif kind not in ('thread.started', 'turn.started'):
                # Fail closed for newly introduced event/tool surfaces.
                raise AgentUnavailable('AGENT_TOOL_EXECUTION_DETECTED')
        result = json.loads(final) if complete and final is not None else None
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise AgentUnavailable('AGENT_RESPONSE_INVALID') from None


def run_agent(request, *, bundle=None, repository=None, runner=None, model=MODEL, timeout=TIMEOUT_SECONDS,
              evidence_rounds_remaining=2):
    if model != MODEL:
        raise AgentUnavailable('AGENT_MODEL_NOT_ALLOWED')
    if bundle is None:
        raise AgentUnavailable('AGENT_CASE_REQUIRED')
    executable = _executable()
    if executable is None:
        raise AgentUnavailable('AGENT_CODEX_NOT_FOUND')
    execution = dict(kind='connected_agent', provider='codex', model=model, run_id=uuid.uuid4().hex)
    schema = schema_path()
    text = (p2_case.prompt(bundle) + '\nEXECUTION:' + json.dumps(execution) + '\n'
            + 'Copy request_digest=' + request['digest'] + ' and EXECUTION exactly.\n'
            + f'more_evidence rounds remaining: {evidence_rounds_remaining}. '
            + ('Return all final decisions and empty more_evidence now.\n' if not evidence_rounds_remaining else '\n')
            + 'OUTPUT_SCHEMA:' + schema.read_text(encoding='utf-8'))
    input_bytes = text.encode('utf-8')
    if len(input_bytes) > p2_case.MAX_BYTES:
        raise AgentUnavailable('AGENT_PROMPT_TOO_LARGE')
    # The model cwd is empty; schema is CLI-owned, never a model file tool.
    # Ephemeral mode suppresses session persistence of customer material.
    with tempfile.TemporaryDirectory(prefix='cost-p2-empty-') as cwd:
        command = [executable, 'exec', '--ignore-user-config', '--ignore-rules', '--strict-config',
                   '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
                   '--model', MODEL, '--output-schema', str(schema), '--json', *config_args(), '-']
        try:
            proc = (runner or _run_bounded)(command, cwd=cwd, env=dict(os.environ),
                                           timeout=min(timeout, TIMEOUT_SECONDS), input_bytes=input_bytes)
        except subprocess.TimeoutExpired:
            raise AgentUnavailable('AGENT_TIMEOUT') from None
        except OSError:
            raise AgentUnavailable('AGENT_EXECUTION_FAILED') from None
        if proc.returncode:
            # Never log provider text (it can echo the input).
            _error((proc.stdout + (proc.stderr or b'')).decode('utf-8', errors='replace'))
        response = parse_events(proc.stdout)
    if response.get('execution') != execution or response.get('request_digest') != request['digest']:
        raise AgentUnavailable('AGENT_EXECUTION_MISMATCH')
    return response


def configured_model(config_path):
    return MODEL
