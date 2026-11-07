from webapp.ledger_store import LedgerStore


def test_trips_page_uses_one_summary_read_instead_of_per_trip_delete_previews(tmp_path, monkeypatch):
    from webapp import ledger_board

    store = LedgerStore(tmp_path / "trips-page.sqlite", seed_demo=True)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        calls = []
        original = store.trip_management_summaries
        monkeypatch.setattr(
            store, "trip_management_summaries",
            lambda: (calls.append("summary"), original())[1],
        )
        monkeypatch.setattr(
            store, "preview_tab_delete",
            lambda *_: (_ for _ in ()).throw(
                AssertionError("list rendering must not build delete previews")
            ),
        )
        html = ledger_board.trips_page(role="owner")
        assert calls == ["summary"]
        assert "수입 1건 1,000,000원" in html
        assert "지출 2건 180,000원" in html
    finally:
        ledger_board.bind_store(previous)
        store.close()
