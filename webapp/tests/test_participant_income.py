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


def workbook():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("0630_오제")
    ws["B4"] = "수입 내용"
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    ws["B6"], ws["C6"], ws["H6"] = dt.date(2027, 6, 30), PARTICIPANT, 100000
    ws["C7"] = NAME_ONLY
    ws["C9"] = "=sum(H6:H7)"
    ws["B10"] = "지출 내용"
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}11"] = label
    ws["B12"], ws["C12"], ws["H12"] = dt.date(2027, 6, 30), "지출처-합성", 30000
    ws["C13"] = "=SUM(H12:H12)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def write_roster(root: Path, *, tab_id: str, name: str = PARTICIPANT) -> Path:
    batch = root / "batch"
    (batch / "sources").mkdir(parents=True)
    (batch / "sources" / "page-01.png").write_bytes(b"synthetic-roster-source")
    import hashlib
    manifest = {
        "schema_version": 1, "batch_id": "batch-syn-p", "roster_id": "roster-syn-p",
        "revision": 1, "authority": "owner_confirmed_insurance",
        "trip_ref": {"cost_trip_id": tab_id, "google_trip_key": "0630_오제"},
        "submitted_by": "local-roster-agent", "submitted_at": "2026-10-20T18:00:00+09:00",
        "coverage": {"scope": "partial", "received_pages": [1], "expected_pages": None,
                     "declared_people": None},
        "sources": [{"source_id": "source-syn-p", "path": "sources/page-01.png",
                     "sha256": hashlib.sha256(b"synthetic-roster-source").hexdigest()}],
    }
    participants = {"schema_version": 1, "items": [
        {"source_item_id": "item-syn-p", "source_id": "source-syn-p", "page": 1,
         "row_label": "1", "name": name, "nickname": None, "english_name": None,
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
                fetcher=lambda url: book, now=NOW)
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


if __name__ == '__main__':
    unittest.main()
