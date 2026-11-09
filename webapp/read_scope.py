"""A memo that lives for one read-only render, so repeated reads share one result.

Only the outermost render is scoped. Nothing is kept after it returns, so a later
save is always read fresh.
"""
from contextvars import ContextVar
from functools import wraps

_MEMO = ContextVar("read_scope_memo", default=None)


def scoped(render):
    @wraps(render)
    def wrapped(*args, **kwargs):
        token = _MEMO.set({})
        try:
            return render(*args, **kwargs)
        finally:
            _MEMO.reset(token)
    return wrapped


def active():
    return _MEMO.get() is not None


def remember(key, compute):
    memo = _MEMO.get()
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]
