"""Single background writer across a prepared release and the serving release."""
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import threading
import time

_lock = threading.RLock()


@contextmanager
def route_lock(route):
    """The switcher uses this same lock before moving the writer role."""
    with _lock, Path(str(route) + '.lock').open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.05)
            stream.seek(0)
            if stream.read(1) == b'':
                stream.write(b'0')
                stream.flush()
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def is_active():
    route = os.environ.get('WEBLEDGER_DEPLOYMENT_ROUTE')
    if not route:
        return True
    try:
        state = json.loads(Path(route).read_text(encoding='utf-8-sig'))
        return not state['paused'] and state['port'] == int(os.environ['WEBLEDGER_DEPLOYMENT_PORT'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def writer():
    route = os.environ.get('WEBLEDGER_DEPLOYMENT_ROUTE')
    if not route:
        yield True
    else:
        with route_lock(route):
            yield is_active()


def active_writer(default=None):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with writer() as active:
                return function(*args, **kwargs) if active else default
        return wrapped
    return decorate
