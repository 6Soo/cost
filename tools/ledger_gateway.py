"""Loopback TCP gateway. Never parses, logs, or retries a financial request.

An atomic route file selects the backend for each connection. Pausing accepts
new connections but holds them while old connections drain. Existing sockets
remain pinned to their original backend, including uploads and streaming.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import threading
import time

HEARTBEAT_SECONDS = 30
STATUS_FRESH_SECONDS = HEARTBEAT_SECONDS + 15
STAT_THROTTLE_SECONDS = 0.25


def read_route(path):
    state = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if type(state.get('port')) is not int or not 1024 <= state['port'] <= 65535:
        raise ValueError('INVALID_BACKEND')
    if type(state.get('paused')) is not bool:
        raise ValueError('INVALID_PAUSE')
    return state


def atomic_json(path, state):
    path = Path(path)
    temporary = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    temporary.write_text(json.dumps(state), encoding='utf-8')
    try:
        for attempt in range(100):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 99:
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)


def _stat_key(observed):
    return (observed.st_dev, observed.st_ino, observed.st_mtime_ns, observed.st_size)


class RouteCache:
    """stat-key cache for the route file; a changed file is re-read at once.

    At most one os.stat per STAT_THROTTLE_SECONDS while the file is unchanged.
    The file's mtime, size and inode are part of the key, so an atomic replace
    is never missed. Failures raise to the caller, never swallowed.
    """

    def __init__(self, path, min_interval=STAT_THROTTLE_SECONDS, clock=time.monotonic):
        self.path = Path(path)
        self.min_interval = min_interval
        self.clock = clock
        self._pending = None
        self._stat_key = None
        self._checked_at = 0.0
        self.file_reads = 0
        self.stat_checks = 0

    def get(self, force=False):
        now = self.clock()
        if not force and self._pending is not None and now - self._checked_at < self.min_interval:
            return self._pending
        self._checked_at = now
        self.stat_checks += 1
        observed = os.stat(self.path)
        key = _stat_key(observed)
        if self._pending is not None and key == self._stat_key:
            return self._pending
        self.file_reads += 1
        state = read_route(self.path)
        self._pending = state
        self._stat_key = key
        return state


class Gateway(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, port, route, status):
        self.route, self.status = Path(route), Path(status)
        self.route_cache = RouteCache(self.route)
        self.lock = threading.Lock()
        self.active = {}
        self.last_publish = 0.0
        self.last_generation = None
        self.counts_dirty = False
        self.next_retry = 0.0
        super().__init__(('127.0.0.1', port), Relay)

    def publish(self):
        # Called with lock held; counts are acknowledged only after publication.
        state = self.route_cache.get(force=True)
        atomic_json(self.status, dict(pid=os.getpid(), updated_at=time.time(),
                    active=self.active, generation=state.get('generation')))
        self.last_publish = time.monotonic()
        self.last_generation = state.get('generation')

    def _try_publish_locked(self):
        try:
            self.publish()
        except (OSError, ValueError):
            self.next_retry = time.monotonic() + HEARTBEAT_SECONDS
            return False
        self.next_retry = 0.0
        return True

    def _publish_due_locked(self, state, now):
        return (self.last_publish == 0.0 or state.get('generation') != self.last_generation
                or self.counts_dirty or now - self.last_publish >= HEARTBEAT_SECONDS)

    def note_activity(self):
        with self.lock:
            self.counts_dirty = True
            if self.next_retry and time.monotonic() < self.next_retry:
                return
            if self._try_publish_locked():
                self.counts_dirty = False

    def service_actions(self):
        with self.lock:
            try:
                state = self.route_cache.get()
            except (OSError, ValueError):
                return  # A stale acknowledgement blocks switching, not serving.
            now = time.monotonic()
            if self.next_retry and now < self.next_retry:
                return
            if self._publish_due_locked(state, now):
                if self._try_publish_locked():
                    self.counts_dirty = False

    def handle_error(self, request, client_address):
        pass  # No request bytes, credentials, addresses, or exception payloads.


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        backend = None
        counted = False
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                with server.lock:
                    state = read_route(server.route)
                    if not state['paused']:
                        port = state['port']
                        # Count before connect so drain cannot miss a connection.
                        server.active[str(port)] = server.active.get(str(port), 0) + 1
                        counted = True
                        break
                time.sleep(.025)
            else:
                return
            if counted:
                server.note_activity()
            backend = socket.create_connection(('127.0.0.1', port), timeout=5)
            backend.settimeout(None)
            incoming = {self.request: backend, backend: self.request}
            while incoming:
                readable, _, _ = select.select(list(incoming), [], [], 120)
                if not readable:
                    return
                for source in readable:
                    destination = incoming[source]
                    data = source.recv(65536)
                    if not data:
                        if source is backend:
                            return
                        del incoming[source]
                        destination.shutdown(socket.SHUT_WR)
                    else:
                        destination.sendall(data)
        except (OSError, ValueError, KeyError):
            pass  # In particular: never replay a partially transmitted POST.
        finally:
            if backend:
                backend.close()
            if counted:
                with server.lock:
                    server.active[str(port)] -= 1
                server.note_activity()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--status', type=Path, required=True)
    args = parser.parse_args()
    if read_route(args.route)['port'] == args.port:
        parser.error('gateway cannot route to itself')
    with Gateway(args.port, args.route, args.status) as server:
        server.serve_forever(poll_interval=.05)


if __name__ == '__main__':
    main()
