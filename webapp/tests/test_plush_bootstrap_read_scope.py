"""A Plush projection reads the Google snapshot once per request, not once per trip.

The bootstrap walks every trip and each trip loads the same snapshot and row
files through ``plush_income``. Without one `read_scope` around the projection
that read repeats for every mapped trip (72 reads on the operational ledger),
which is the reported slow first load.
"""

from __future__ import annotations

from types import SimpleNamespace

from webapp import access_control
from webapp import google_ledger_page as page
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


def _call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0], query="")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    return handler.responses[-1]


def test_bootstrap_reads_snapshot_once_for_every_mapped_trip(tmp_path, monkeypatch):
    from webapp.tests.test_google_canonical_workflow import healthy_snapshot
    from webapp.tests.test_google_ledger_page import rows_doc

    store = LedgerStore(tmp_path / "plush.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)

    snapshot = healthy_snapshot()
    key_a, key_b = (trip["key"] for trip in snapshot["trips"])
    mapping = {key_a: "trip-demo-a", key_b: "trip-demo-b"}
    reads = {"n": 0}

    def counting_load(*_args):
        reads["n"] += 1
        return snapshot, rows_doc()["sources"]

    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(tmp_path / "snapshot.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    monkeypatch.setattr(page, "load_mapping", lambda *_: mapping)
    monkeypatch.setattr(page, "load_choices", lambda *_: {"choices": {key_a: "main", key_b: "main"}})
    monkeypatch.setattr(page, "snapshot_for_display", lambda data: data)
    monkeypatch.setattr(page.google_authority, "load_consistent", counting_load)

    try:
        status, body = _call("/api/plush/bootstrap", "syn-owner", store)
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()

    assert status == 200
    assert len(body["trips"]) > 1
    assert reads["n"] == 1, "every mapped trip in one bootstrap must share the single snapshot read"
