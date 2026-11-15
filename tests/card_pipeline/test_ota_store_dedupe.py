"""메일 1통이 늘어도 기존 메일 근거를 새 판으로 다시 쓰지 않고, 읽기 결과는 이전 방식과 같아야 한다."""
import json

from app import ota_payments
from app.agoda_capture import parse_detail
from app.ota_store import OtaStore, catalog_rows, direct_facts, encoded
from tests.card_pipeline.test_agoda_capture import capture
from tests.card_pipeline.test_booking_mail import message, hotel
from tests.card_pipeline.test_forest_mail import body_notice


def legacy_evidence(self, provider, ref, revision, key, kind, fact, account='legacy-owner'):
    """변경 전 쓰기 방식: 판마다 같은 사실을 새 행으로 넣는다."""
    from app.ota_store import sha
    if not provider or not ref:
        return
    identity = sha(encoded([provider, account, str(ref)]))
    self.conn.execute('INSERT OR IGNORE INTO ota_bookings VALUES(?,?,?,?)', (identity, provider, account, str(ref)))
    self.conn.execute('INSERT OR IGNORE INTO ota_booking_evidence VALUES(?,?,?,?,?)',
                      (identity, revision, key, kind, encoded(fact)))


def legacy_observations(self, messages, revision):
    from app import forest_mail
    inserted = 0
    for event in forest_mail.collect(messages):
        key = forest_mail.catalog_reference(event)
        source_id, = event['source_ids']
        inserted += self.conn.execute('INSERT OR IGNORE INTO ota_reservation_observations VALUES(?,?,?,?,?,?,?)',
            (key, revision, source_id.removeprefix('mail:'), event['provider'], event.get('booking_ref'),
             event['source_digest'], encoded(event))).rowcount
    return inserted


def cancel_mail(booking):
    return {'id': 'agoda-cancel-verified', 'internal_date': '1792587733653', 'owner_collected': True,
            'payload': {'headers': [{'name': 'From', 'value': 'customerservice@agoda.com'},
                {'name': 'Subject', 'value': '취소된 예약 - 아고다 예약 번호: ' + booking},
                {'name': 'Date', 'value': 'Wed, 21 Oct 2026 13:02:13 +0000'}],
                'body': {'content': '예약 번호: ' + booking + '\n예약 취소일: October 21, 2026'}}}


def trip(n):
    return message(hotel(ref=f'{n}' * 16), subject='[Trip.com] 결제 완료 안내', identity=f'trip-{n}')


def forest(n):
    return body_notice(f'2026-10-0{n} 합성자연휴양림 가상실 객실 예약완료', identity=f'forest-{n}',
                       subject='숲나들e 예약완료 안내')


def write(folder, messages):
    folder.mkdir(exist_ok=True)
    (folder / 'gmail.json').write_text(json.dumps({'responses': messages}, ensure_ascii=False), encoding='utf-8')
    return folder


def run(tmp_path, name, legacy, monkeypatch):
    raw = capture()
    raw['observed_at'] = '2026-10-21T02:54:54Z'
    booking = parse_detail(raw)['booking_number']
    direct = tmp_path / (name + '-direct.json')
    direct.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    base = [trip(1), trip(2), cancel_mail(booking), forest(1), forest(2)]
    folder = tmp_path / (name + '-mail')
    if legacy:
        monkeypatch.setattr(OtaStore, '_evidence', legacy_evidence)
        monkeypatch.setattr(OtaStore, 'index_reservation_observations', legacy_observations)
    store = OtaStore(tmp_path / (name + '.sqlite'))
    store.import_capture(direct)
    store.import_mail(write(folder, base))
    first = store.summary()
    store.import_mail(write(folder, base + [trip(3)]))
    store.import_mail(write(folder, base + [trip(3), forest(3)]))
    return store, first, folder


def view(store):
    facts = [(row['booking_id'], fact, conflicts) for row, fact, conflicts in direct_facts(store.conn)]
    return sorted(facts, key=lambda item: encoded(item)), sorted(encoded(r) for r in catalog_rows(store.conn))


def test_new_mail_adds_only_its_own_evidence_and_reads_match_the_old_writer(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        old, old_first, folder = run(tmp_path, 'old', True, patch)
    new, new_first, _ = run(tmp_path, 'new', False, monkeypatch)
    try:
        mail_rows = "SELECT count(*) FROM ota_booking_evidence WHERE evidence_kind='mail'"
        # 판이 2번 늘어도 새 메일(trip-3) 분만 늘어난다. 이전 방식은 판마다 전체를 다시 쓴다.
        assert new.conn.execute(mail_rows).fetchone()[0] == 4
        assert old.conn.execute(mail_rows).fetchone()[0] == 3 + 4 + 4
        old_obs = old.conn.execute('SELECT count(*) FROM ota_reservation_observations').fetchone()[0]
        new_obs = new.conn.execute('SELECT count(*) FROM ota_reservation_observations').fetchone()[0]
        assert new_obs == 3 and old_obs == 2 + 2 + 3
        assert new.summary()['ota_source_revisions'] == old.summary()['ota_source_revisions'] == 4
        assert view(new) == view(old)
        assert sum(r.get('identity_kind') == 'reservation_observation' for r in catalog_rows(new.conn)) == 3
        events = lambda store: [{k: v for k, v in e.items() if k != 'source_inventory'} for e in
                                ota_payments.build_ota_payment_events({'mail_directories': [store.path]})]
        assert events(new) == events(old)
        # 원문과 관측 이력: 메시지는 그대로, 다시 관측된 행은 마지막 판·횟수가 남는다.
        assert new.summary()['ota_messages'] == old.summary()['ota_messages'] == 7
        current = new.conn.execute("SELECT current_revision FROM ota_sources WHERE kind='mail_directory'").fetchone()[0]
        seen = new.conn.execute("SELECT * FROM ota_row_seen WHERE kind='evidence' AND entry_key='trip-1'").fetchone()
        assert seen['last_revision'] == current and seen['seen_count'] == 3
        assert seen['first_revision'] != current and seen['first_observed_at'] <= seen['last_observed_at']
        # 같은 판을 다시 읽어도 관측 횟수는 늘지 않는다.
        new.import_mail(folder.parent / 'new-mail')
        assert new.conn.execute("SELECT seen_count FROM ota_row_seen WHERE kind='evidence' AND entry_key='trip-1'"
                                ).fetchone()[0] == 3
    finally:
        old.close()
        new.close()


def changed_parser(monkeypatch, status):
    from app import forest_mail, ota_payments as payments
    real_collect, real_extract = forest_mail.collect, payments.extract_payment_fact
    monkeypatch.setattr(forest_mail, 'collect',
                        lambda messages: [dict(e, reservation_status=status) for e in real_collect(messages)])
    monkeypatch.setattr(payments, 'extract_payment_fact',
                        lambda m: dict(real_extract(m), reservation_status=status) if real_extract(m) else None)


def observed(store):
    rows = [r for r in catalog_rows(store.conn) if r.get('identity_kind') == 'reservation_observation']
    return sorted((r['id'], r['status']) for r in rows)


def test_same_revision_rerun_with_changed_parser_keeps_one_current_fact(tmp_path, monkeypatch):
    base = [trip(1), forest(1), forest(2)]
    folder = write(tmp_path / 'mail', base)
    store = OtaStore(tmp_path / 'new.sqlite')
    try:
        store.import_mail(folder)
        first = observed(store)
        store.import_mail(write(folder, base + [trip(2)]))
        before = (observed(store), store.summary())
        assert before[0] == first
        changed_parser(monkeypatch, 'parser-v2')
        store.import_mail(folder)
        store.rebuild_reservation_observations()
        assert (observed(store), store.summary()) == before
        assert len(first) == 2 and len({i for i, _ in observed(store)}) == 2
    finally:
        store.close()


def test_changed_fact_in_new_revision_and_removed_mail_follow_the_old_writer(tmp_path, monkeypatch):
    results = []
    for legacy in (True, False):
        folder = tmp_path / ('mail-%s' % legacy)
        base = [trip(1), forest(1), forest(2)]
        with monkeypatch.context() as patch:
            if legacy:
                patch.setattr(OtaStore, '_evidence', legacy_evidence)
                patch.setattr(OtaStore, 'index_reservation_observations', legacy_observations)
            store = OtaStore(tmp_path / ('s-%s.sqlite' % legacy))
            steps = []
            store.import_mail(write(folder, base))
            steps.append((view(store), observed(store)))
            store.import_mail(write(folder, base + [trip(2)]))
            steps.append((view(store), observed(store)))
            with monkeypatch.context() as parser:
                changed_parser(parser, 'parser-v2')
                store.import_mail(write(folder, base + [trip(2), trip(3)]))
                steps.append((view(store), observed(store)))
            store.import_mail(write(folder, [trip(1), trip(2), trip(3), forest(2)]))
            steps.append((view(store), observed(store)))
            store.close()
        results.append(steps)
    assert results[0] == results[1]
    assert len(results[1][3][1]) == 1


def test_database_built_by_old_writer_continues_with_new_writer(tmp_path, monkeypatch):
    folder = tmp_path / 'mail'
    base = [trip(1), forest(1), forest(2)]
    with monkeypatch.context() as patch:
        patch.setattr(OtaStore, '_evidence', legacy_evidence)
        patch.setattr(OtaStore, 'index_reservation_observations', legacy_observations)
        store = OtaStore(tmp_path / 'm.sqlite')
        store.import_mail(write(folder, base))
        store.import_mail(write(folder, base + [trip(2)]))
        legacy_rows = store.summary()['ota_booking_evidence']
        store.close()
    store = OtaStore(tmp_path / 'm.sqlite')
    try:
        store.import_mail(write(folder, base + [trip(2), forest(3)]))
        summary = store.summary()
        assert summary['ota_booking_evidence'] == legacy_rows + 0
        assert summary['ota_reservation_observations'] == 4 + 1
        assert len(observed(store)) == 3
        again = store.summary()
        store.import_mail(folder)
        assert store.summary() == again
    finally:
        store.close()


def test_same_revision_a_b_a_keeps_the_first_fact_as_the_only_current_row(tmp_path, monkeypatch):
    base = [trip(1), forest(1), forest(2)]
    folder = write(tmp_path / 'mail', base)
    store = OtaStore(tmp_path / 'aba.sqlite')
    try:
        store.import_mail(folder)
        store.import_mail(write(folder, base + [trip(2)]))
        first = observed(store)
        counts = store.summary()
        with monkeypatch.context() as parser:
            changed_parser(parser, 'parser-v2')
            store.import_mail(folder)
            store.rebuild_reservation_observations()
        store.import_mail(folder)
        store.rebuild_reservation_observations()
        assert observed(store) == first and store.summary() == counts
    finally:
        store.close()


def test_deleted_observation_row_is_recreated_by_same_revision_reindex(tmp_path):
    folder = write(tmp_path / 'mail', [forest(1), forest(2)])
    store = OtaStore(tmp_path / 'del.sqlite')
    try:
        store.import_mail(folder)
        store.import_mail(write(folder, [forest(1), forest(2), trip(1)]))
        first = observed(store)
        store.conn.execute('DELETE FROM ota_reservation_observations')
        store.conn.commit()
        assert observed(store) == []
        assert store.rebuild_reservation_observations() == 2
        assert observed(store) == first
    finally:
        store.close()


def test_without_seen_table_same_fact_in_an_older_revision_is_still_written(tmp_path):
    folder = write(tmp_path / 'mail', [forest(1)])
    store = OtaStore(tmp_path / 'noseen.sqlite')
    try:
        store.import_mail(folder)
        store.import_mail(write(folder, [forest(1), trip(1)]))
        first = observed(store)
        store.conn.execute('DROP TABLE ota_row_seen')
        store.conn.execute('DELETE FROM ota_reservation_observations')
        store.conn.commit()
        assert store.rebuild_reservation_observations() == 1
        assert observed(store) == first
    finally:
        store.close()
