"""JSON bridge CLI: ``python -I tools/core_bridge/cli.py <command>`` (request on stdin, response on stdout)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # -I drops the working directory, so add the repo root explicitly
    sys.path.insert(0, str(ROOT))

from tools.core_bridge.commands import COMMANDS, BridgeError, canonical  # noqa: E402

PROTOCOL = 'core-bridge/1'


def python_sha():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def handle(command, request, sha=None):
    """Return the response envelope for one request; never raises for a bad request."""
    envelope = {'protocol': PROTOCOL, 'command': command, 'python_sha': python_sha() if sha is None else sha,
                'input_digest': digest(request)}
    if command not in COMMANDS:
        return dict(envelope, ok=False, error={'code': 'COMMAND_UNKNOWN', 'detail': command})
    try:
        return dict(envelope, ok=True, result=canonical(COMMANDS[command](request)))
    except BridgeError as exc:
        return dict(envelope, ok=False, error={'code': exc.code, 'detail': exc.detail})
    except Exception as exc:  # report the class only; messages can carry source text
        return dict(envelope, ok=False, error={'code': 'COMMAND_FAILED', 'detail': type(exc).__name__})


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.stderr.write('usage: cli.py <snapshot|facts|links|plan|classify|extract|trips|periods>\n')
        return 2
    sys.stdout.reconfigure(encoding='utf-8')
    exit_code = 0
    for line in sys.stdin.buffer.read().decode('utf-8-sig').splitlines():
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle(argv[0], request)
        except json.JSONDecodeError:
            response = {'protocol': PROTOCOL, 'command': argv[0], 'ok': False,
                        'error': {'code': 'REQUEST_NOT_JSON', 'detail': ''}}
        exit_code = exit_code or (0 if response['ok'] else 1)
        sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + '\n')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
