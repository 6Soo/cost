"""A memo that lives for one read-only render, so repeated reads share one result.

Only the outermost render is scoped. Nothing is kept after it returns, so a later
save is always read fresh.
"""
from contextvars import ContextVar
from functools import wraps

_MEMO = ContextVar("read_scope_memo", default=None)
_BULK_BOARD_ROWS = object()


def scoped(render, *, bulk_board_rows=True):
    @wraps(render)
    def wrapped(*args, **kwargs):
        token = _MEMO.set({_BULK_BOARD_ROWS: bulk_board_rows})
        try:
            return render(*args, **kwargs)
        finally:
            _MEMO.reset(token)
    return wrapped


def active():
    return _MEMO.get() is not None


def bulk_board_rows_enabled():
    memo = _MEMO.get()
    return memo is not None and memo[_BULK_BOARD_ROWS]


def remember(key, compute):
    memo = _MEMO.get()
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]
