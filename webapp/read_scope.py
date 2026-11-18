"""A memo that lives for one read-only render, so repeated reads share one result.

Only the outermost render is scoped. Nothing is kept after it returns, so a later
save is always read fresh.
"""
from contextvars import ContextVar
from functools import wraps

_MEMO = ContextVar("read_scope_memo", default=None)
# Separate from the memo dict on purpose: callers that seed a scope by setting
# _MEMO directly (tests, the p2 batch tools) hold only their own keys, so the
# bulk-read request must not be read out of their dict.
_BULK_BOARD_ROWS = ContextVar("read_scope_bulk_board_rows", default=False)


def scoped(render, *, bulk_board_rows=True):
    @wraps(render)
    def wrapped(*args, **kwargs):
        token = _MEMO.set({})
        bulk_token = _BULK_BOARD_ROWS.set(bulk_board_rows)
        try:
            return render(*args, **kwargs)
        finally:
            _MEMO.reset(token)
            _BULK_BOARD_ROWS.reset(bulk_token)
    return wrapped


def active():
    return _MEMO.get() is not None


def bulk_board_rows_enabled():
    """Whether this scope asked for every tab's rows in one scan."""
    return _MEMO.get() is not None and _BULK_BOARD_ROWS.get()


def remember(key, compute):
    memo = _MEMO.get()
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]
