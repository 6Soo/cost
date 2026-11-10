"""Local connected-agent provider for unattended P2 review.

Derived-facts-only request in, strict response out. Free model, no tools,
no customer raw text, no paid fallback. The caller owns authorization: this
module only reports whether a local OpenCode free agent can answer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import threading

MODEL = 'opencode/glm-5.3-flash-free'
SPACE_BUNNY = 'opencode/deepseek-v4.1-flash-free'
MIMO = 'opencode/mimo-v2.6-flash-free'
DEFAULT_MODEL = MODEL
MODELS = (MODEL, SPACE_BUNNY, MIMO)
MAX_OUTPUT_BYTES = 512 * 1024
TIMEOUT_SECONDS = 180
COOLDOWN = {'AGENT_RATE_LIMITED': 300, 'AGENT_PROVIDER_UNAVAILABLE': 60, 'AGENT_EXECUTION_FAILED': 60,
            'AGENT_EXECUTION_DENIED': 300, 'AGENT_TIMEOUT': 60, 'AGENT_COMMAND_LINE_TOO_LONG': 60}
NETWORK_WORDS = ('fetch failed', 'econnreset', 'etimedout', 'econnrefused', 'socket', 'overloaded', 'unavailable', 'timed out')

SCHEMA = '{"request_digest":"<string>","execution":{"kind":"connected_agent","provider":"opencode","model":"<string>","run_id":"<string>"},"results":[{"transaction_id":"<string>","trip_id":"<string or empty>","item":"<string>","basis":"<string>","uncertainty":"<string>"}]}'
AGENT_INSTRUCTION = ('You are the COST connected-agent reviewer. You receive a JSON request of derived facts only. '
                     'Never call tools, never read files, never ask for more data. '
                     'Reply with a single JSON object matching exactly this schema and no other keys: ' + SCHEMA + '. '
                     'Copy request_digest from the request unchanged. Set execution to kind connected_agent, provider opencode, '
                     'the model you are running as, and the run_id supplied in the request. '
                     'One results entry per case, exactly once. trip_id must be one of the case trips trip_id values, '
                     'item must be one of the case allowed_items. basis is one short Korean sentence with the evidence used; '
                     'uncertainty states what could not be verified. No markdown, no code fence, no explanation.')


class AgentUnavailable(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


def enabled(config_path):
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        return options.get('autonomous_ai_review') is True
    except FileNotFoundError:
        return os.environ.get('WEBLEDGER_AUTONOMOUS_AI_REVIEW') == '1'
    except (OSError, ValueError, AttributeError):
        return False


def configured_model(config_path):
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        model = options.get('autonomous_ai_review_model')
        return model if model in MODELS else DEFAULT_MODEL
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODEL


def daily_cap(config_path):
    try:
        options = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        cap = options.get('autonomous_ai_review_daily_cap')
        return cap if isinstance(cap, int) and cap >= 0 else 200
    except (OSError, ValueError, AttributeError):
        return 200


def _real_executable(path):
    """A .cmd shim re-parses its arguments in cmd.exe and breaks multi-line prompts."""
    candidate = Path(path)
    if candidate.suffix.lower() in ('.cmd', '.bat'):
        actual = candidate.parent / 'node_modules' / 'opencode-ai' / 'bin' / 'opencode.exe'
        if actual.is_file():
            return str(actual)
    return str(candidate)


def _executable():
    configured = os.environ.get('WEBLEDGER_OPENCODE_EXE', '').strip()
    if configured and Path(configured).is_file():
        return _real_executable(configured)
    found = shutil.which('opencode')
    if found:
        return _real_executable(found)
    appdata = os.environ.get('APPDATA', '')
    if appdata and (Path(appdata) / 'npm' / 'opencode.cmd').is_file():
        return _real_executable(Path(appdata) / 'npm' / 'opencode.cmd')
    return None


def parse_events(raw):
    if len(raw) > MAX_OUTPUT_BYTES:
        raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
    texts = []
    try:
        for line in raw.decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError()
            if event.get('type') == 'error':
                _provider_error(event)
            if event.get('type') == 'text':
                part = event.get('part')
                if (isinstance(part, dict) and part.get('type') == 'text'
                        and isinstance(part.get('text'), str) and not part.get('synthetic')
                        and not (part.get('metadata') or {}).get('compaction_continue')):
                    texts.append(part['text'])
    except AgentUnavailable:
        raise
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise AgentUnavailable('AGENT_RESPONSE_INVALID') from None
    answer = '\n'.join(texts).strip()
    if answer.startswith('```'):
        answer = re.sub('^```(?:json)?', '', answer, flags=re.I)
        answer = re.sub('```$', '', answer.strip()).strip()
    match = re.search(r'\{.*\}', answer, flags=re.S)
    if not match:
        raise AgentUnavailable('AGENT_RESPONSE_INVALID')
    try:
        result = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise AgentUnavailable('AGENT_RESPONSE_INVALID') from None
    if not isinstance(result, dict) or 'results' not in result or 'execution' not in result:
        raise AgentUnavailable('AGENT_RESPONSE_INVALID')
    return result


def _provider_error(event):
    error = event.get('error') if isinstance(event.get('error'), dict) else {}
    data = error.get('data') if isinstance(error.get('data'), dict) else {}
    status = data.get('statusCode')
    message = str(data.get('message') or error.get('name') or '').lower()
    if status in (401, 403):
        raise AgentUnavailable('AGENT_PROVIDER_ERROR')
    headers = data.get('responseHeaders') if isinstance(data.get('responseHeaders'), dict) else {}
    retry = str(headers.get('retry-after') or '').strip()
    if status == 429 or any(word in message for word in ('rate limit', 'usage limit', 'quota')):
        raise AgentUnavailable('AGENT_RATE_LIMITED', int(retry) if retry.isdigit() else None)
    if status in (500, 502, 503, 504) or any(word in message for word in NETWORK_WORDS):
        raise AgentUnavailable('AGENT_PROVIDER_UNAVAILABLE')
    raise AgentUnavailable('AGENT_PROVIDER_ERROR')


def _owned_job(process):
    """Own descendants for cleanup even when their parent exits first (Windows)."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes as wt
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wt.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active_limit', wt.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wt.DWORD), ('scheduling', wt.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [wt.LPVOID, wt.LPCWSTR], wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: lifecycle, not sandbox.
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        if handle:
            kernel.CloseHandle(handle)
        process.kill()
        process.wait()
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    if not kernel.AssignProcessToJobObject(handle, wt.HANDLE(int(process._handle))):
        kernel.CloseHandle(handle)
        process.kill()
        process.wait()
        raise AgentUnavailable('AGENT_PROCESS_BOUNDARY_UNAVAILABLE')
    return lambda: kernel.CloseHandle(handle)


def _run_bounded(command, *, cwd, env, timeout, input_bytes=None):
    process = subprocess.Popen(command, cwd=cwd, env=env,
                               stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    close_job = _owned_job(process)
    chunks, size, exceeded = [[], []], [0], threading.Event()
    mutex = threading.Lock()

    def read(pipe, index):
        try:
            while block := pipe.read(8192):
                with mutex:
                    size[0] += len(block)
                    if size[0] > MAX_OUTPUT_BYTES:
                        exceeded.set()
                    else:
                        chunks[index].append(block)
        finally:
            pipe.close()

    def write():
        try:
            process.stdin.write(input_bytes)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            process.stdin.close()

    threads = [threading.Thread(target=read, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=read, args=(process.stderr, 1), daemon=True)]
    if input_bytes is not None:
        threads.append(threading.Thread(target=write, daemon=True))
    for thread in threads:
        thread.start()
    started = time.monotonic()
    try:
        while process.poll() is None:
            if exceeded.wait(.02):
                raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
            if time.monotonic() - started >= timeout:
                raise subprocess.TimeoutExpired(command, timeout)
        for thread in threads:
            thread.join(timeout=max(.1, timeout - (time.monotonic() - started)))
        if any(thread.is_alive() for thread in threads):
            raise subprocess.TimeoutExpired(command, timeout)
        if exceeded.is_set():
            raise AgentUnavailable('AGENT_RESPONSE_TOO_LARGE')
        return subprocess.CompletedProcess(command, process.returncode, b''.join(chunks[0]), b''.join(chunks[1]))
    except BaseException:
        if close_job:
            close_job()
            close_job = None
        elif os.name == 'nt' and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            process.kill()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        if close_job:
            close_job()


def run_agent(request, *, model=None, runner=None, timeout=TIMEOUT_SECONDS):
    """Call the local free agent. The request carries derived facts only."""
    model = model or DEFAULT_MODEL
    executable = _executable()
    if executable is None:
        raise AgentUnavailable('AGENT_OPENCODE_NOT_FOUND')
    run_id = uuid.uuid4().hex
    prompt = AGENT_INSTRUCTION + '\n\nrun_id: ' + run_id + '\nmodel: ' + model + '\n\n' + json.dumps(request, ensure_ascii=False)
    config = {'$schema': 'https://opencode.ai/config.json',
              'agent': {'autonomous-review': {'description': 'COST autonomous derived-facts review, tools need approval',
                                              'mode': 'primary', 'model': model, 'prompt': AGENT_INSTRUCTION,
                                              'permission': {'*': 'ask'}}},
              'permission': {'*': 'ask'}}
    with tempfile.TemporaryDirectory(prefix='cost-autonomous-') as temporary:
        root = Path(temporary)
        (root / 'opencode.json').write_text(json.dumps(config), encoding='utf-8')
        isolated = root / 'config'
        (isolated / 'opencode').mkdir(parents=True)
        (isolated / 'opencode' / 'opencode.json').write_text(json.dumps(config), encoding='utf-8')
        environment = dict(os.environ, XDG_CONFIG_HOME=str(isolated))
        # Windows limits CreateProcess command lines to 32,767 characters. A
        # normal 20-case review can exceed that once derived trip context is
        # serialized, so keep the request out of argv and attach a private temp
        # file instead. The file is removed with the temporary directory.
        request_file = root / 'review-request.txt'
        request_file.write_text(prompt, encoding='utf-8')
        command = [executable, 'run', '--pure', '--model', model, '--agent', 'autonomous-review',
                   '--title', 'COST autonomous review (free)', '--format', 'json',
                   '--file', str(request_file), '--',
                   'Follow the attached COST review request and return only its required JSON.']
        started = time.monotonic()
        try:
            proc = (runner or _run_bounded)(command, cwd=str(root), env=environment, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AgentUnavailable('AGENT_TIMEOUT') from None
        except OSError as exc:
            winerror = getattr(exc, 'winerror', None)
            if winerror == 206:
                code = 'AGENT_COMMAND_LINE_TOO_LONG'
            elif winerror in (2, 3):
                code = 'AGENT_OPENCODE_NOT_FOUND'
            elif winerror == 5:
                code = 'AGENT_EXECUTION_DENIED'
            else:
                code = 'AGENT_EXECUTION_FAILED'
            raise AgentUnavailable(code) from None
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode:
            parse_events(proc.stdout)
            raise AgentUnavailable('AGENT_PROVIDER_UNAVAILABLE')
        response = parse_events(proc.stdout)
    execution = response.get('execution') if isinstance(response.get('execution'), dict) else {}
    if (execution.get('kind') != 'connected_agent' or execution.get('run_id') != run_id
            or not execution.get('provider') or not execution.get('model')):
        raise AgentUnavailable('AGENT_EXECUTION_MISMATCH')
    response['_duration_ms'] = elapsed_ms
    return response
