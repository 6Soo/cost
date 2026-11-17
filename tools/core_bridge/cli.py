"""JSON bridge CLI: ``python -I tools/core_bridge/cli.py <command>`` (request on stdin, response on stdout)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # -I drops the working directory, so add the repo root explicitly
    sys.path.insert(0, str(ROOT))

from tools.core_bridge.commands import COMMANDS, BridgeError, canonical  # noqa: E402

PROTOCOL = 'core-bridge/1'


SHA_RE = re.compile(r'[0-9a-f]{40}')


def python_sha(root=None):
    """릴리스 폴더의 DEPLOYED_COMMIT, 없으면 git HEAD, 둘 다 없으면 ''(호출자가 오류로 처리)."""
    root = ROOT if root is None else Path(root)
    try:
        marker = (root / 'DEPLOYED_COMMIT').read_text(encoding='ascii')[:1024].strip().lower()
        if SHA_RE.fullmatch(marker):
            return marker
    except (OSError, ValueError):
        pass
    try:
        out = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        found = out.stdout.strip().lower()
        return found if out.returncode == 0 and SHA_RE.fullmatch(found) else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def handle(command, request, sha=None):
    """Return the response envelope for one request; never raises for a bad request."""
    derived = sha is None
    sha = python_sha() if derived else sha
    envelope = {'protocol': PROTOCOL, 'command': command, 'python_sha': sha, 'input_digest': digest(request)}
    if derived and not sha:
        return dict(envelope, ok=False, error={'code': 'PYTHON_SHA_UNAVAILABLE', 'detail': ''})
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
        sys.stderr.write('usage: cli.py <snapshot|facts|links|candidates|plan|classify|extract|trips|periods|ota-input|extract-baseline|extract-baseline-compare>\n')
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
