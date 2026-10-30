"""참가자·수입 대조 화면의 소유자 경계.

합성 Google 자료와 합성 명단만 쓴다. 실명·운영 DB는 이 파일에 들어오지 않는다.
"""
import datetime as dt
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import openpyxl

from app import google_authority as ga
from app import participant_roster as pr
from webapp import access_control
from webapp import google_ledger_page as gl
from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-P"
VIEWER = "syn-viewer-P"
NOW = dt.datetime(2026, 10, 20, 9, 0, tzinfo=ga.KST)
PARTICIPANT = "가람-합성"
NAME_ONLY = "다온-합성"
INCOME = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]


def workbook(title="0630_오제", *, unnamed_amount=False, zero_deposit=False):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(title)
    ws["B4"] = "수입 내용"
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    ws["B6"], ws["C6"], ws["H6"] = dt.date(2027, 6, 30), PARTICIPANT, 100000
    if zero_deposit:
        # 실제 0원 구성액이다. 공란과 구분되어야 한다.
        ws["E6"] = 0
    ws["C7"] = NAME_ONLY
    if unnamed_amount:
        # 이름이 공란인 실제 금액 행이다. 이름 인덱스만 보면 사라진다.
        ws["B8"], ws["H8"] = dt.date(2027, 6, 30), 50000
    ws["C9"] = "=sum(H6:H7)"
    ws["B10"] = "지출 내용"
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}11"] = label
    ws["B12"], ws["C12"], ws["H12"] = dt.date(2027, 6, 30), "지출처-합성", 30000
    ws["C13"] = "=SUM(H12:H12)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def write_roster(root: Path, *, tab_id: str, name: str = PARTICIPANT, batch_id: str = "batch-syn-p",
                 roster_id: str = "roster-syn-p", row_label: str = "1") -> Path:
    batch = root / ("batch-" + batch_id)
    (batch / "sources").mkdir(parents=True, exist_ok=True)
    (batch / "sources" / "page-01.png").write_bytes(b"synthetic-roster-source")
    import hashlib
    manifest = {
        "schema_version": 1, "batch_id": batch_id, "roster_id": roster_id,
        "revision": 1, "authority": "owner_confirmed_insurance",
        "trip_ref": {"cost_trip_id": tab_id, "google_trip_key": "0630_오제"},
        "submitted_by": "local-roster-agent", "submitted_at": "2026-10-20T18:00:00+09:00",
        "coverage": {"scope": "partial", "received_pages": [1], "expected_pages": None,
                     "declared_people": None},
        "sources": [{"source_id": "source-syn-p", "path": "sources/page-01.png",
                     "sha256": hashlib.sha256(b"synthetic-roster-source").hexdigest()}],
    }
    participants = {"schema_version": 1, "items": [
        {"source_item_id": f"item-{roster_id}", "source_id": "source-syn-p", "page": 1,
         "row_label": row_label, "name": name, "nickname": None, "english_name": None,
         "transcription_status": "verified"}]}
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (batch / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")
    store = pr.ParticipantStore.open(root / "participant.sqlite")
    try:
        pr.register_roster(store, batch,
                           trip_resolver=pr.mapping_resolver({"0630_오제": tab_id}))
    finally:
        store.close()
    return root / "participant.sqlite"


class ParticipantIncomePageTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._dir.name)
        book = workbook()
        self.snapshot, self.rows = root / 'google-snapshot.json', root / 'google-rows-private.json'
        ga.sync(self.snapshot, self.rows,
                fetcher=lambda url: book, now=dt.datetime.now(ga.KST))
        self._env = patch.dict(os.environ, {
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': str(self.snapshot),
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': str(self.rows),
            'WEBLEDGER_PARTICIPANT_DB': str(root / 'participant.sqlite'),
            'WEBLEDGER_DB': str(root / 'phase.sqlite')})
        self._env.start()
        self.store = LedgerStore(root / 'phase.sqlite')
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.trip = self.store.create_trip(starts_on='2026-10-10', ends_on='2026-10-13',
                                           destination='합성 여행',
                                           client_request_id='participant-trip')['tab_id']
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER)
        gl.set_mapping(self.snapshot, key='0630_오제', tab_id=self.trip,
                       known_keys={'0630_오제'})
        gl.record_choice(self.snapshot, key='0630_오제', source='main', at='t')
        write_roster(root, tab_id=self.trip)

    def tearDown(self):
        board_mod.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        self._env.stop()
        self._dir.cleanup()

    def call(self, path, user=None, method='GET', payload=None, form=None):
        headers = {}
        data = None
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        if payload is not None:
            data = json.dumps(dict(payload, csrf=board_mod.CSRF_TOKEN)).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        elif form is not None:
            data = urllib.parse.urlencode(dict(form, csrf=board_mod.CSRF_TOKEN)).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=data,
                                         headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')
    def test_the_owner_sees_the_reconciliation_table(self):
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn(PARTICIPANT, body)
        self.assertIn('참가 확정', body)
        self.assertIn('이름 일치', body)

    def test_a_viewer_is_refused_and_no_name_is_shown(self):
        status, body = self.call(f'/participants?trip={self.trip}', VIEWER)
        self.assertEqual(status, 403, body)
        self.assertNotIn(PARTICIPANT, body)
        self.assertNotIn(NAME_ONLY, body)

    def test_an_anonymous_request_is_refused(self):
        status, body = self.call(f'/participants?trip={self.trip}')
        self.assertEqual(status, 401, body)
        self.assertNotIn(PARTICIPANT, body)

    def test_the_state_route_counts_the_people_and_the_income_rows(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        state = json.loads(body)
        self.assertEqual(state['counts']['participants'], 1)
        self.assertEqual(state['counts']['linked_income_rows'], 1)
        self.assertEqual(state['counts']['income_rows'], 2)

    def test_the_regular_board_does_not_show_the_roster(self):
        status, body = self.call(f'/board?tab={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertNotIn(PARTICIPANT, body)
        self.assertIn('data-participant-content', body)
        self.assertNotIn('participant_income_links', body)

    def test_the_lazy_trip_panel_is_owner_only(self):
        status, body = self.call(f'/api/participants/trip-panel?trip={self.trip}', VIEWER)
        self.assertEqual(status, 403, body)
        self.assertNotIn(PARTICIPANT, body)
        status, body = self.call(f'/api/participants/trip-panel?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn(PARTICIPANT, body)
        self.assertIn('data-income-ref=', body)
        self.assertIn("action='/api/participants/link'", body)

    def test_trip_income_owner_column_is_well_formed_and_viewer_rows_keep_contract(self):
        from html.parser import HTMLParser
        from webapp import ledger_board as board_mod
        from webapp.tests.test_google_ledger_page import _clean_trip, _clean_sources
        from webapp.tests.test_google_ledger_page import rows_doc
        original = board_mod.current_role
        trip = _clean_trip()
        key = trip['key']
        # Align the cached sheet total with the synthetic source rows so the
        # existing verified-income display contract renders its table.
        trip['income_total'] = 1000
        snapshot = {'synced_at': 't', 'sources': _clean_sources(), 'trips': [trip],
                    'rows_generation': 'gen'}
        income_block = rows_doc()['sources']['main']['trips'][key]['income']
        income_block[0]['amount'] = 1000
        class Cells(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.current = None
            def handle_starttag(self, tag, attrs):
                if tag == 'tr':
                    self.current = 0
                elif tag in ('td', 'th') and self.current is not None:
                    self.current += 1
            def handle_endtag(self, tag):
                if tag == 'tr' and self.current is not None:
                    self.rows.append(self.current)
                    self.current = None

        try:
            with patch.object(gl, 'snapshot_for_display', lambda data: data), \
                    patch.object(gl.google_authority, 'load_consistent', lambda *a: (snapshot, rows_doc()['sources'])), \
                    patch.object(gl, 'load_choices', lambda *a: {'choices': {key: 'main'}}), \
                    patch.object(gl, 'load_mapping', lambda *a: {key: self.trip}):
                board_mod.current_role = lambda: 'owner'
                owner_html = gl.trip_income_html(self.trip)
        finally:
            board_mod.current_role = original
        owner = Cells()
        owner.feed(owner_html)
        self.assertIn(7, owner.rows)
        self.assertIn(6, owner.rows)
        self.assertIn("+ (\"<th>보험 등록</th>\" if owner else \"\")",
                      __import__('inspect').getsource(gl.trip_income_html))

    def test_a_stale_decision_is_refused(self):
        status, body = self.call('/api/participants/link', OWNER, 'POST',
                                 payload={'trip': self.trip, 'participant_id': 'x',
                                          'income_ref': 'main|0630_오제|6',
                                          'input_fingerprint': 'stale'})
        self.assertEqual(status, 409, body)
        self.assertEqual(json.loads(body)['code'], 'STALE_RECONCILIATION')

    def test_a_decision_without_the_token_is_refused(self):
        headers = {access_control.SyntheticSessionAdapter.HEADER: OWNER,
                   'Content-Type': 'application/json'}
        data = json.dumps({'trip': self.trip, 'participant_id': 'x',
                           'income_ref': 'main|0630_오제|6'}).encode('utf-8')
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/participants/link',
                                         data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read().decode('utf-8')
        self.assertEqual(status, 403, body)
        self.assertEqual(json.loads(body)['code'], 'CSRF_REQUIRED')

    def test_the_owner_can_link_an_income_row_and_the_state_follows(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        state = json.loads(body)
        participant = state["participants"][0]
        target = next(row for row in state["income_rows"] if row["amount"] is None)
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
            'trip': self.trip, 'participant_id': participant["participant_id"],
            'income_ref': target["ref"], 'reason': '사용자 확인',
            'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 200, body)
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        linked = after["participants"][0]
        self.assertEqual(linked["state"], 'manual')
        self.assertEqual(linked["links"][0]["row"]["amount"], None)
        # 이름만 있는 행은 0원 수입으로 바뀌지 않는다.
        self.assertEqual(after["counts"]["linked_income_rows"], 2)

    def test_the_same_screen_saved_twice_is_refused(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        target = next(row for row in state["income_rows"] if row["amount"] is None)
        payload = {'trip': self.trip, 'participant_id': participant["participant_id"],
                   'income_ref': target["ref"], 'input_fingerprint': state["input_fingerprint"]}
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload=payload)
        self.assertEqual(status, 200, body)
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload=payload)
        self.assertEqual(status, 409, body)
        self.assertEqual(json.loads(body)['code'], 'STALE_RECONCILIATION')

    def test_a_write_without_the_fingerprint_is_refused(self):
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
            'trip': self.trip, 'participant_id': 'pt-x', 'income_ref': 'main|0630_오제|7'})
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)['code'], 'INVALID_VALUE')

    def test_a_write_to_an_income_row_that_is_not_there_is_refused(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
            'trip': self.trip, 'participant_id': participant["participant_id"],
            'income_ref': 'main|0630_오제|999',
            'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)['code'], 'INCOME_ROW_UNKNOWN')
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(after["counts"]["linked_income_rows"], 1)

    def test_a_write_for_a_person_of_another_trip_is_refused(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        target = next(row for row in state["income_rows"] if row["amount"] is None)
        status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
            'trip': self.trip, 'participant_id': 'pt-other-trip',
            'income_ref': target["ref"], 'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)['code'], 'PARTICIPANT_NOT_FOUND')

    def test_a_name_correction_needs_the_fingerprint_too(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        status, body = self.call('/api/participants/participant', OWNER, 'POST', payload={
            'trip': self.trip, 'action': 'rename', 'participant_id': participant["participant_id"],
            'name': '가람-합성-정정'})
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)['code'], 'INVALID_VALUE')
        status, body = self.call('/api/participants/participant', OWNER, 'POST', payload={
            'trip': self.trip, 'action': 'rename', 'participant_id': participant["participant_id"],
            'name': '가람-합성-정정', 'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 200, body)
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(after["participants"][0]["display_name"], '가람-합성-정정')

    def test_a_failed_write_leaves_nothing_behind(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        store = pr.ParticipantStore.open(Path(self._dir.name) / "participant.sqlite")
        try:
            events_before = len(store.events())
        finally:
            store.close()
        status, body = self.call('/api/participants/participant', OWNER, 'POST', payload={
            'trip': self.trip, 'action': 'rename', 'participant_id': participant["participant_id"],
            'name': '   ', 'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 422, body)
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(after["participants"][0]["display_name"], PARTICIPANT)
        self.assertEqual(after["counts"]["linked_income_rows"], 1)
        store = pr.ParticipantStore.open(Path(self._dir.name) / "participant.sqlite")
        try:
            self.assertEqual(len(store.events()), events_before)
        finally:
            store.close()

    def test_an_unverified_total_is_not_shown_as_a_confirmed_amount(self):
        # 수입 합계 수식이 깨진 장부다. 금액 행은 그대로 보이지만 확정 금액이 아니다.
        main = workbook()
        archive = workbook("0107_대만")
        ga.sync(self.snapshot, self.rows, now=dt.datetime.now(ga.KST),
                fetcher=lambda url: main if ga.SPREADSHEET_IDS['main'] in url else archive)
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        state = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertIn('확정', body)  # 합계가 확정 금액이 아니라는 설명이 있다.

    def test_a_joint_payment_says_the_individual_amount_is_not_settled(self):
        # 다른 참가자도 있다. 한 수입 행을 두 명이 나눠 낸 사람이 한 명이다.
        write_roster(Path(self._dir.name), tab_id=self.trip, name="이나래-합성",
                     batch_id="batch-syn-p2", roster_id="roster-syn-p2", row_label="2")
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        target = next(row for row in state["income_rows"] if row["amount"] is None)
        for entry in state["participants"]:
            status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
                'trip': self.trip, 'participant_id': entry["participant_id"],
                'income_ref': target["ref"], 'joint': True,
                'input_fingerprint': state["input_fingerprint"]})
            self.assertEqual(status, 200, body)
            state = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual([item["state"] for item in after["participants"]], ["joint", "joint"])
        # 같은 입금 행은 한 번만 센다. 참가자별 연결 수보다 작다.
        links = sum(len(item["links"]) for item in after["participants"])
        self.assertEqual(links, 3)
        self.assertEqual(after["counts"]["linked_income_rows"], 2)
        self.assertEqual(after["counts"]["participants"], 2)
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertIn('공동 입금', body)
        self.assertIn('개인별 금액 미확정', body)

    def test_an_unlinked_income_row_can_be_marked_reviewed(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        target = next(row for row in state["unlinked_income"] if row["state"] == 'not_in_roster')
        status, body = self.call('/api/participants/link', OWNER, 'POST', form={
            'trip': self.trip, 'decision': 'reviewed', 'income_ref': target["ref"],
            'reason': '참가자 아님', 'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 200, body)
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(after["counts"]["unlinked_income_rows"], 0)
        self.assertEqual(after["counts"]["reviewed_income_rows"], 1)
        self.assertNotIn('INCOME_UNCLASSIFIED', after["completion"]["blocked_by"])

    def test_missing_roster_preserves_readable_google_rows_and_refuses_writes(self):
        missing = Path(self._dir.name) / 'not-created.sqlite'
        with patch.dict(os.environ, {'WEBLEDGER_PARTICIPANT_DB': str(missing)}):
            status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
            state = json.loads(body)
            self.assertEqual(status, 200)
            self.assertFalse(state['configured'])
            self.assertGreater(len(state['income_rows']), 0)
            self.assertEqual(len(state['income_rows']), len(state['unlinked_income']))
            self.assertFalse(state['completion']['complete'])
            status, body = self.call(f'/participants?trip={self.trip}', OWNER)
            self.assertIn('id="site-shell-style"', body)
            self.assertIn(PARTICIPANT, body)
            self.assertNotIn('STORE_UNAVAILABLE', body)
            status, body = self.call('/api/participants/link', OWNER, 'POST', payload={
                'trip':self.trip, 'income_ref':state['income_rows'][0]['ref'],
                'participant_id':'invented', 'input_fingerprint':''})
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body)['code'], 'STORE_UNAVAILABLE')
            self.assertFalse(missing.exists())

    def test_missing_name_index_matches_known_rows_without_declaring_absence(self):
        from webapp import participant_income_page
        with patch.object(gl, 'owner_income_names', return_value=None):
            state = participant_income_page.build_state(self.trip)
        self.assertTrue(state['google']['available'])
        self.assertFalse(state['google']['name_index_complete'])
        self.assertGreater(state['counts']['linked_income_rows'], 0)
        self.assertFalse(state['completion']['complete'])

    def test_a_trip_with_one_copy_is_connected_without_a_choice(self):
        # 보관본에 같은 탭이 없으면 이 여행은 메인 한 사본뿐이다.
        main = workbook()
        archive = workbook("0107_대만")
        ga.sync(self.snapshot, self.rows, now=dt.datetime.now(ga.KST),
                fetcher=lambda url: main if ga.SPREADSHEET_IDS['main'] in url else archive)
        gl.choice_path(self.snapshot).write_text(json.dumps({"choices": {}, "history": []}),
                                                 encoding="utf-8")
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        state = json.loads(body)
        self.assertEqual(state["google"]["source"], "main")
        self.assertTrue(state["google"]["available"])
        self.assertEqual(state["counts"]["linked_income_rows"], 1)

    def test_an_amount_row_without_a_name_is_not_lost(self):
        main = workbook(unnamed_amount=True)
        archive = workbook("0107_대만")
        ga.sync(self.snapshot, self.rows, now=dt.datetime.now(ga.KST),
                fetcher=lambda url: main if ga.SPREADSHEET_IDS['main'] in url else archive)
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        # 이름이 공란인 금액 행도 미연결 목록에 남는다.
        self.assertEqual(state["counts"]["unlinked_income_rows"], 2)
        self.assertIn(50000, [row["amount"] for row in state["unlinked_income"]])

    def test_the_page_offers_the_owner_the_decisions_it_needs(self):
        # 같은 여행에 다른 참가자가 있으면 동일인 확인도 화면에서 할 수 있다.
        write_roster(Path(self._dir.name), tab_id=self.trip, name="이나래-합성",
                     batch_id="batch-syn-p2", roster_id="roster-syn-p2", row_label="2")
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn('action=\'/api/participants/link\'', body)
        self.assertIn('action=\'/api/participants/unlink\'', body)
        self.assertIn('action=\'/api/participants/participant\'', body)
        self.assertIn('value=\'rename\'', body)
        self.assertIn('value=\'alias\'', body)
        self.assertIn('value=\'same_person\'', body)
        self.assertIn('value=\'remap\'', body)
        self.assertIn('공동 입금', body)
        # 근거는 내부 상태 문자열이 아니라 설명으로 보인다.
        self.assertIn('명단으로 참가 확정', body)
        self.assertNotIn('>confirmed<', body)

    def test_the_trip_income_area_links_to_the_owner_page(self):
        from webapp import google_ledger_page as gl_page
        from webapp import ledger_board as board_mod
        original = board_mod.current_role
        board_mod.current_role = lambda: 'owner'
        try:
            body = gl_page.trip_income_html(self.trip)
        finally:
            board_mod.current_role = original
        self.assertIn('/participants?trip=', body)

    def test_browser_owner_links_a_name_only_income_row_once(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                context = browser.new_context(extra_http_headers={
                    access_control.SyntheticSessionAdapter.HEADER: OWNER})
                pg = context.new_page()
                response = pg.goto(f'http://127.0.0.1:{self.port}/participants?trip={self.trip}')
                self.assertEqual(response.status, 200)
                self.assertIn(PARTICIPANT, pg.content())
                form = pg.locator("form[action='/api/participants/link']").filter(
                    has=pg.locator("select[name='income_ref']")).first
                form.locator("select[name='income_ref']").select_option(value="main|0630_오제|7")
                with pg.expect_navigation():
                    form.locator("button").click()
                self.assertIn('"code": "OK"', pg.content())
                pg.goto(f'http://127.0.0.1:{self.port}/participants?trip={self.trip}')
                self.assertIn('수동 연결', pg.content())
            finally:
                browser.close()

    def test_browser_trip_tab_lazy_panel_drops_on_the_google_income_row(self):
        from playwright.sync_api import sync_playwright
        import zipfile
        import xml.etree.ElementTree as ET
        # Excel normally supplies cached formula totals; openpyxl does not.
        # Keep the real income-verification gate and provide a verified fixture.
        browser_book = openpyxl.load_workbook(io.BytesIO(workbook()))
        browser_book.active['H7'] = 50000
        browser_source = io.BytesIO()
        browser_book.save(browser_source)
        verified = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(browser_source.getvalue())) as source, zipfile.ZipFile(verified, 'w') as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == 'xl/worksheets/sheet1.xml':
                    sheet = ET.fromstring(data)
                    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    for cell in sheet.iter(ns + 'c'):
                        total = {'C9': '150000', 'C13': '30000'}.get(cell.get('r'))
                        if total is not None:
                            value = cell.find(ns + 'v')
                            if value is None:
                                value = ET.SubElement(cell, ns + 'v')
                            value.text = total
                    data = ET.tostring(sheet, encoding='utf-8')
                target.writestr(info, data)
        ga.sync(self.snapshot, self.rows, fetcher=lambda url: verified.getvalue(),
                now=dt.datetime.now(ga.KST))
        gl.record_choice(self.snapshot, key='0630_오제', source='main', at='synthetic-verified')
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            try:
                context = browser.new_context(extra_http_headers={
                    access_control.SyntheticSessionAdapter.HEADER: OWNER},
                    viewport={"width": 375, "height": 812})
                page = context.new_page()
                original_display = gl.snapshot_for_display
                gl.snapshot_for_display = lambda snapshot: snapshot
                self.addCleanup(setattr, gl, 'snapshot_for_display', original_display)
                response = page.goto(f'http://127.0.0.1:{self.port}/board?tab={self.trip}')
                self.assertEqual(response.status, 200)
                self.assertNotIn(PARTICIPANT, page.locator("#participant-trip-panel").inner_html())
                page.locator('#participant-trip-panel summary').click()
                page.locator('#participant-trip-panel .participant-cards li').first.wait_for()
                self.assertIn(PARTICIPANT, page.locator('#participant-trip-panel').inner_text())
                income_table = page.locator('#google-trip-income table#income-tbl')
                if income_table.count() == 0:
                    self.fail('Google 수입 표가 렌더되지 않음: ' + page.locator('#google-trip-income').inner_text())
                self.assertEqual(income_table.count(), 1)
                self.assertEqual(page.locator('#participant-trip-panel table').count(), 0)
                self.assertEqual(page.locator('.trip-flight').count(), 1)
                target = income_table.locator('.participant-insurance-cell').last
                self.assertEqual(target.count(), 1)
                row_ref = target.get_attribute('data-income-ref')
                self.assertTrue(row_ref.startswith('main|0630_오제|'))
                card = page.locator('#participant-trip-panel .participant-cards li[draggable=true]').first
                page.evaluate("""([source,target])=>{
                    const data={clearData(){},setData(){},effectAllowed:''};
                    const start=new Event('dragstart',{bubbles:true,cancelable:true});
                    Object.defineProperty(start,'dataTransfer',{value:data});source.dispatchEvent(start);
                    const over=new Event('dragover',{bubbles:true,cancelable:true});
                    Object.defineProperty(over,'dataTransfer',{value:data});target.dispatchEvent(over);
                    const drop=new Event('drop',{bubbles:true,cancelable:true});
                    Object.defineProperty(drop,'dataTransfer',{value:data});target.dispatchEvent(drop);
                }""", [card.element_handle(), target.element_handle()])
                dialog = page.locator('#participant-link-confirm')
                dialog.wait_for(state='visible')
                self.assertIn('연결할까요', dialog.inner_text())
                page.locator('#participant-link-confirm button[value=cancel]').click()
                self.assertEqual(page.locator('#participant-link-confirm').count(), 1)
                self.assertEqual(json.loads(self.call(
                    f'/api/participants/state?trip={self.trip}', OWNER)[1])['counts']['linked_income_rows'], 1)
                # A second explicit drop followed by confirmation uses the same
                # current fingerprinted write contract exactly once.
                page.evaluate("""([source,target])=>{
                    const data={clearData(){},setData(){},effectAllowed:''};
                    for(const type of ['dragstart']){const e=new Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:data});source.dispatchEvent(e);}
                    const e=new Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:data});target.dispatchEvent(e);
                }""", [card.element_handle(), target.element_handle()])
                with page.expect_response(lambda r: '/api/participants/link' in r.url and r.request.method == 'POST') as saved:
                    page.locator('#participant-link-confirm button[value=confirm]').click()
                self.assertEqual(saved.value.status, 200)
                page.wait_for_load_state('networkidle')
                self.assertIn('/board?', page.url)
                after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
                self.assertEqual(after['counts']['linked_income_rows'], 2)
            finally:
                browser.close()

    def test_the_trip_remap_form_moves_only_that_participant(self):
        gl.set_mapping(self.snapshot, key='0107_대만', tab_id='trip-demo-b',
                       known_keys={'0630_오제', '0107_대만'})
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn('name=\'target_trip\'', body)
        state = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        participant = state["participants"][0]
        form = {'trip': self.trip, 'action': 'remap',
                'participant_id': participant["participant_id"],
                'target_trip': 'trip-demo-b', 'reason': '다른 여행',
                'input_fingerprint': state["input_fingerprint"]}
        status, body = self.call('/api/participants/participant', OWNER, 'POST', form=form)
        self.assertEqual(status, 200, body)
        moved = json.loads(self.call(f'/api/participants/state?trip=trip-demo-b', OWNER)[1])
        self.assertEqual([item["display_name"] for item in moved["participants"]], [PARTICIPANT])
        left = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(left["participants"], [])

    def test_a_remap_to_a_trip_that_is_not_there_is_refused(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        status, body = self.call('/api/participants/participant', OWNER, 'POST', form={
            'trip': self.trip, 'action': 'remap',
            'participant_id': participant["participant_id"], 'target_trip': 'trip-nope',
            'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 422, body)
        self.assertEqual(json.loads(body)['code'], 'TRIP_UNKNOWN')
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(len(after["participants"]), 1)

    def test_a_remap_with_an_old_screen_is_refused(self):
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        participant = state["participants"][0]
        status, body = self.call('/api/participants/participant', OWNER, 'POST', form={
            'trip': self.trip, 'action': 'remap',
            'participant_id': participant["participant_id"], 'target_trip': 'trip-demo-b',
            'input_fingerprint': 'stale'})
        self.assertEqual(status, 409, body)
        self.assertEqual(json.loads(body)['code'], 'STALE_RECONCILIATION')

    def test_a_zero_amount_is_not_shown_as_a_blank(self):
        main = workbook(zero_deposit=True)
        archive = workbook("0107_대만")
        ga.sync(self.snapshot, self.rows, now=dt.datetime.now(ga.KST),
                fetcher=lambda url: main if ga.SPREADSHEET_IDS['main'] in url else archive)
        status, body = self.call(f'/participants?trip={self.trip}', OWNER)
        self.assertEqual(status, 200, body)
        self.assertIn('예약금 0원', body)
        self.assertNotIn('예약금 공란', body)

    def test_two_people_with_the_same_name_can_be_confirmed_as_different(self):
        write_roster(Path(self._dir.name), tab_id=self.trip, name=PARTICIPANT,
                     batch_id="batch-syn-p2", roster_id="roster-syn-p2", row_label="2")
        status, body = self.call(f'/api/participants/state?trip={self.trip}', OWNER)
        state = json.loads(body)
        self.assertEqual(state["counts"]["roster_confirmed"], 2)
        self.assertEqual(state["counts"]["duplicate_names"], 1)
        self.assertIn('DUPLICATE_UNRESOLVED', state["completion"]["blocked_by"])
        first, second = state["participants"]
        status, body = self.call('/api/participants/participant', OWNER, 'POST', form={
            'trip': self.trip, 'action': 'separate', 'participant_id': first["participant_id"],
            'other_participant_id': second["participant_id"], 'reason': '다른 사람',
            'input_fingerprint': state["input_fingerprint"]})
        self.assertEqual(status, 200, body)
        after = json.loads(self.call(f'/api/participants/state?trip={self.trip}', OWNER)[1])
        self.assertEqual(after["counts"]["roster_confirmed"], 2)
        self.assertEqual(after["counts"]["duplicate_names"], 0)
        self.assertNotIn('DUPLICATE_UNRESOLVED', after["completion"]["blocked_by"])


if __name__ == '__main__':
    unittest.main()
