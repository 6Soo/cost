"""One read-only entrypoint for existing COST source audit tools.

The default prints a preview. Only --run executes the selected fixed command.
No arbitrary child arguments, shell commands, source values or host secrets are
accepted. Pytest collection, deploy, refresh/import and all writers are excluded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    'test-environment': ('audit_test_environment.py', '--summary'),
    'runtime-catalog': ('runtime_dependency_catalog.py', '--format', 'summary'),
    'call-map': ('refactor_call_map.py', '--summary', '--limit-output'),
    'write-boundaries': ('audit_write_boundaries.py',),
    'tracked-data': ('check_tracked_data.py', '--mode', 'inventory'),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=sorted(COMMANDS))
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    tool, *options = COMMANDS[args.command]
    path = ROOT / 'tools' / tool
    if not path.is_file() or path.is_symlink():
        print(json.dumps({'status': 'ERROR', 'code': 'AUDIT_TOOL_UNAVAILABLE'}))
        return 2
    if not args.run:
        print(json.dumps({'status': 'PREVIEW', 'command': args.command,
                          'script': 'tools/' + tool, 'arguments': options,
                          'executed': [], 'scope': 'tracked source metadata only'}))
        return 0
    try:
        return subprocess.run([sys.executable, str(path), *options],
                              cwd=ROOT, shell=False, check=False).returncode
    except OSError:
        print(json.dumps({'status': 'ERROR', 'code': 'AUDIT_LAUNCH_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
