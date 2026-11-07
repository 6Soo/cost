from webapp.ledger_store import LedgerStore


def test_trips_page_uses_one_summary_read_instead_of_per_trip_delete_previews(tmp_path, monkeypatch):
    from webapp import ledger_board

    store = LedgerStore(tmp_path / "trips-page.sqlite", seed_demo=True)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        expected = store.preview_tab_delete("trip-demo-a")
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
        assert f"수입 {expected['income_count']}건 {expected['income_total']:,}원" in html
        assert f"지출 {expected['expense_count']}건 {expected['expense_total']:,}원" in html
    finally:
        ledger_board.bind_store(previous)
        store.close()


def test_summary_read_failure_is_not_shown_as_zero_costs(tmp_path, monkeypatch):
    from webapp import ledger_board
    store = LedgerStore(tmp_path / 'failed-summary.sqlite', seed_demo=True)
    previous = ledger_board._STORE
    ledger_board.bind_store(store)
    try:
        monkeypatch.setattr(store, 'trip_management_summaries',
            lambda: (_ for _ in ()).throw(ValueError('TRIP_SUMMARY_ROW_UNREADABLE')))
        html = ledger_board.trips_page(role='owner')
        assert '여행 집계를 읽지 못했습니다' in html
        assert '수입 0건 0원' not in html
    finally:
        ledger_board.bind_store(previous)
        store.close()


def test_aggregate_matches_authoritative_preview_with_correction_and_allocations(tmp_path):
    store = LedgerStore(tmp_path / 'allocated-summary.sqlite', seed_demo=True)
    try:
        import json
        source = next(row for row in store.list_tab_rows('trip-demo-a') if row['row_kind'] == 'income')
        payload = json.loads(store.conn.execute('SELECT payload_json FROM board_rows WHERE row_id=?',
                                               (source['row_id'],)).fetchone()[0])
        payload['source_kind'] = '은행'
        store.conn.execute('UPDATE board_rows SET payload_json=? WHERE row_id=?',
                           (json.dumps(payload), source['row_id']))
        store.conn.execute('INSERT INTO income_corrections '
            '(correction_id,row_id,corrected_amount_krw,reason,actor,created_at,client_request_id) '
            'VALUES (?,?,?,?,?,?,?)', ('synthetic-correction',source['row_id'],123456,'synthetic','test','2026-11-08','correction'))
        corrected = store.trip_management_summaries()['trip-demo-a']
        assert corrected['income_total'] == store.preview_tab_delete('trip-demo-a')['income_total']
        for index, source_id in enumerate((source['row_id'],'synthetic-absent-source')):
            store.conn.execute('INSERT INTO income_allocations '
                '(allocation_id,source_row_id,display_tab_id,amount_krw,source_revision,created_at,client_request_id) '
                'VALUES (?,?,?,?,?,?,?)', (str(index),source_id,'trip-demo-b',123456,source['revision'],'2026-11-08',str(index)))
        before = list(store.conn.iterdump())
        summaries = store.trip_management_summaries()
        assert list(store.conn.iterdump()) == before
        for tab in ('trip-demo-a','trip-demo-b'):
            authoritative = store.preview_tab_delete(tab)
            assert summaries[tab] == {name:authoritative[name] for name in
                ('income_count','income_total','expense_count','expense_total')}
    finally:
        store.close()
