"""A Plush row detail reads the trip list once per request, not once per use.

``_row_detail`` looked at two consumers in one request for an owner-editable
row: resolving the row's trip and building the ``display_tab_id`` options for the
edit form.  Each consumer called ``_visible_trips`` separately, and unlike the
bootstrap/home/ledger projections the detail is not wrapped in ``read_scope``,
so the memo in ``_cached_trips`` cannot share the read: the store's
``list_trips(include_archived=True)`` ran once per consumer.

The detail must still resolve the same trip and publish the same options; the
read is shared, the value is not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webapp import access_control
from webapp import ledger_board
from webapp import plush_api
from webapp.ledger_store import LedgerStore


class Handler:
    command = "GET"

    def __init__(self, user: str | None):
        self.headers = {}
        if user:
            self.headers[access_control.SyntheticSessionAdapter.HEADER] = user
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


@pytest.fixture()
def bound_store(tmp_path):
    store = LedgerStore(tmp_path / "plush.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def _call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0],
                             query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


def test_row_detail_reads_the_trip_list_once(bound_store, monkeypatch):
    store, _ = bound_store
    reads = {"n": 0}
    original = store.list_trips

    def counting(*args, **kwargs):
        reads["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "list_trips", counting)

    status, detail = _call("/api/plush/row?id=expense-demo-c1", "syn-owner", store)
    assert status == 200
    # The trip lookup and the edit form's trip options share one store read.
    assert reads["n"] == 1, "owner row detail must not read the trip list twice"
    assert detail["edit_fields"], "editable detail keeps its fields"
    trip_field = next(field for field in detail["edit_fields"]
                      if field["name"] == "display_tab_id")
    assert trip_field["options"], "trip options come from the same single read"
