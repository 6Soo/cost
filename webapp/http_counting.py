"""Content-free request hooks; telemetry failures never alter HTTP behavior."""
from contextlib import contextmanager


def begin(handler):
    if getattr(handler, '_http_observation', None) is not None:
        return
    counter = getattr(handler.server, 'http_request_counts', None)
    if counter is not None and hasattr(handler, 'path'):
        try:
            handler._http_observation = counter.observe_begin(
                handler.path, getattr(handler, 'command', None))
        except Exception:
            pass


class _Stream:
    def __init__(self, stream, handler, response):
        self._stream, self._handler, self._response = stream, handler, response

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def _count(self, count):
        handler = self._handler
        observation = getattr(handler, '_http_observation', None)
        if observation is None or (self._response and not handler._http_body_started):
            return
        try:
            counter = handler.server.http_request_counts
            method = counter.observe_response_write if self._response else counter.observe_request_read
            method(observation, count)
        except Exception:
            pass

    def read(self, *args):
        value = self._stream.read(*args)
        self._count(len(value))
        return value

    def readline(self, *args):
        value = self._stream.readline(*args)
        self._count(len(value))
        return value

    def readinto(self, *args):
        count = self._stream.readinto(*args)
        if count is not None:
            self._count(count)
        return count

    def write(self, value):
        count = self._stream.write(value)
        if count is not None:
            self._count(count)
        return count


@contextmanager
def request(handler):
    handler._http_observation = None
    handler._http_status = None
    handler._http_body_started = False
    old_read, old_write = handler.rfile, handler.wfile
    counter = getattr(handler.server, 'http_request_counts', None)
    if counter is not None:
        handler.rfile = _Stream(old_read, handler, False)
        handler.wfile = _Stream(old_write, handler, True)
    aborted = False
    try:
        yield
    except BaseException:
        aborted = True
        raise
    finally:
        handler.rfile, handler.wfile = old_read, old_write
        observation = handler._http_observation
        if observation is not None:
            try:
                method = counter.observe_abort if aborted else counter.observe_finish
                method(observation, handler._http_status)
            except Exception:
                pass


def attach(server, data_root, port):
    """One stable file per server port; no raw URL/header/body is retained."""
    from pathlib import Path
    from app.http_request_counts import RequestCounts
    try:
        server.http_request_counts = RequestCounts(
            Path(data_root) / 'metrics' / f'http-{int(port)}.json')
    except Exception:
        # A disk or metrics failure must not prevent the ledger from starting.
        server.http_request_counts = None
