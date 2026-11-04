"""Explicit, serialized route control; never reads or changes customer data."""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.ledger_gateway import STATUS_FRESH_SECONDS, atomic_json, read_route
from webapp.deployment_role import route_lock


def ready(port):
    for path, expected in (('/healthz', 200), ('/readyz', 200), ('/api/imports/ota', 401)):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        if status != expected:
            raise ValueError('BACKEND_NOT_READY')


def drained(route, status, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_route(route)
        report = json.loads(Path(status).read_text(encoding='utf-8-sig'))
        if not state['paused']:
            raise ValueError('ROUTE_NOT_PAUSED')
        if (report['generation'] == state['generation'] and time.time() - report['updated_at'] < STATUS_FRESH_SECONDS
                and all(count == 0 for count in report['active'].values())):
            return
        time.sleep(.05)
    raise ValueError('DRAIN_TIMEOUT')


def change(route, status, action, port=None, timeout=30):
    if action == 'pause':
        with route_lock(route):
            state = read_route(route)
            atomic_json(route, dict(state, paused=True, generation=uuid.uuid4().hex))
        # On timeout the caller must resume the old route, never kill requests.
        drained(route, status, timeout)
    elif action == 'activate':
        ready(port)
        with route_lock(route):
            drained(route, status, timeout)
            atomic_json(route, dict(port=port, paused=False, generation=uuid.uuid4().hex))
    elif action == 'resume':
        # Abort a failed drain on the same backend. Never changes its identity.
        with route_lock(route):
            state = read_route(route)
            atomic_json(route, dict(state, paused=False, generation=uuid.uuid4().hex))
    else:
        raise ValueError('ACTION_INVALID')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pause', 'activate', 'resume'))
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--status', type=Path, required=True)
    parser.add_argument('--port', type=int)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    change(args.route, args.status, args.action, args.port, args.timeout)
    print(json.dumps({'status': 'PASS', 'action': args.action}))


if __name__ == '__main__':
    main()
