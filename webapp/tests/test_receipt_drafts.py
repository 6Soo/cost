"""Durable receipt drafts stay separate from registered expenses."""
import uuid
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from webapp import ledger_board, receipt_review as rr
from webapp.tests import test_receipt_review as review

PNG = review.PNG


@pytest.fixture
def receipt_app():
    fixture = review.ReceiptReviewTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.tearDown()


def test_draft_revision_conflict_preserves_both_saved_and_local_values(tmp_path):
    store = tmp_path / 'receipts.json'
    sha = rr.store_image(store, PNG)['sha256']
    draft_id = uuid.uuid4().hex
    group = {'sha': sha, 'kind': 'analysis', 'jobId': None,
             'receipts': [{'merchant': 'SYNTHETIC', 'amount': 100, 'currency': 'JPY', 'include': True}]}
    original = {'draft_id': draft_id, 'expected_revision': 0, 'trip_id': 'trip-1', 'groups': [group]}
    saved = rr.save_draft(store, original, valid_trips={'trip-1'})
    assert saved['revision'] == 1
    local = {**original, 'groups': [{**group, 'receipts': [{**group['receipts'][0], 'amount': 200}]}]}
    with pytest.raises(ValueError, match='DRAFT_STALE'):
        rr.save_draft(store, local, valid_trips={'trip-1'})
    data = rr.load(store)
    assert data['drafts'][0]['groups'][0]['receipts'][0]['amount'] == 100
    assert data['candidates'] == []
    assert local['groups'][0]['receipts'][0]['amount'] == 200


def test_draft_rejects_unknown_source_without_changing_store(tmp_path):
    store = tmp_path / 'receipts.json'
    rr.store_image(store, PNG)
    before = store.read_bytes()
    payload = {'draft_id': uuid.uuid4().hex, 'expected_revision': 0, 'trip_id': 'trip-1',
               'groups': [{'sha': 'a' * 64, 'kind': 'analysis', 'jobId': None, 'receipts': [], 'empty': True}]}
    with pytest.raises(ValueError, match='IMAGE_NOT_FOUND'):
        rr.save_draft(store, payload, valid_trips={'trip-1'})
    assert store.read_bytes() == before


def test_scan_commits_draft_and_result_together_and_replays_lost_response(tmp_path):
    store = tmp_path / 'receipts.json'
    sha = rr.store_image(store, PNG)['sha256']
    draft_id, operation_id = uuid.uuid4().hex, uuid.uuid4().hex
    group = {'sha': sha, 'kind': 'analysis', 'jobId': None,
             'receipts': [{'merchant': 'SYNTHETIC', 'date': '2026-10-12', 'amount': 100,
                           'currency': 'JPY', 'payment': 'cash', 'include': True}]}
    rr.save_draft(store, {'draft_id': draft_id, 'expected_revision': 0,
                          'trip_id': 'trip-1', 'groups': [group]}, valid_trips={'trip-1'})
    payload = {'image': sha, 'trip_id': 'trip-1',
               'regions': [{'merchant': 'SYNTHETIC', 'date': '2026-10-12', 'total': 100,
                            'currency': 'JPY', 'payment': 'cash', 'confidence': 1}],
               'draft': {'draft_id': draft_id, 'expected_revision': 1,
                         'operation_id': operation_id, 'remaining_groups': []}}
    with patch.object(rr, '_trip_ids', return_value={'trip-1'}), patch.object(rr, 'card_rows', return_value=[]):
        before = store.read_bytes()
        with patch.object(rr, '_save', side_effect=OSError('synthetic failure')):
            with pytest.raises(rr.ReceiptStoreError):
                rr.scan(store, payload)
        assert store.read_bytes() == before
        result = rr.scan(store, payload)
        assert result['added'] == 1
        assert rr.load(store)['drafts'][0]['groups'] == []
        assert rr.scan(store, payload) == result
        assert len(rr.load(store)['candidates']) == 1
        different = {**payload, 'regions': [{**payload['regions'][0], 'total': 200}]}
        with pytest.raises(ValueError, match='DRAFT_OPERATION_CONFLICT'):
            rr.scan(store, different)
        second_id = uuid.uuid4().hex
        rr.save_draft(store, {'draft_id': second_id, 'expected_revision': 0,
                              'trip_id': 'trip-1', 'groups': [group]}, valid_trips={'trip-1'})
        moved = {**different, 'draft': {**different['draft'], 'draft_id': second_id}}
        with pytest.raises(ValueError, match='DRAFT_OPERATION_CONFLICT'):
            rr.scan(store, moved)
        assert len(rr.load(store)['candidates']) == 1


def test_draft_routes_require_owner_and_csrf_and_reject_stale_writes(receipt_app):
    app = receipt_app
    sha = app.request('/api/receipts/image', token=app.csrf(), raw=PNG)[1]['sha256']
    payload = {'draft_id': uuid.uuid4().hex, 'expected_revision': 0, 'trip_id': app.trip,
               'groups': [{'sha': sha, 'kind': 'analysis', 'jobId': None, 'receipts': [], 'empty': True}]}
    assert app.request('/api/receipts/drafts')[0] == 403
    assert app.request('/api/receipts/drafts', payload)[0] == 403
    assert app.request('/api/receipts/drafts', payload, token=app.csrf())[0] == 200
    assert app.request('/api/receipts/drafts', payload, token=app.csrf())[0] == 409
    status, result = app.request('/api/receipts/drafts', token=app.csrf())
    assert status == 200 and result['drafts'][0]['draft_id'] == payload['draft_id']
    assert 'drafts' not in app.request('/api/receipts')[1]
    with patch.object(ledger_board, '_receipts_owner_request', return_value=False):
        assert app.request('/api/receipts/drafts', token=app.csrf())[0] == 403


def test_two_processes_cannot_overwrite_the_same_draft_revision(tmp_path):
    store = tmp_path / 'receipts.json'
    sha = rr.store_image(store, PNG)['sha256']
    draft_id = uuid.uuid4().hex
    group = {'sha': sha, 'kind': 'analysis', 'jobId': None, 'receipts': [], 'empty': True}
    rr.save_draft(store, {'draft_id': draft_id, 'expected_revision': 0,
                          'trip_id': 'trip-1', 'groups': [group]}, valid_trips={'trip-1'})
    worker = r"""
import sys, time
from pathlib import Path
from webapp.receipt_review import save_draft
store, sha, draft_id, ready, go = sys.argv[1:]
Path(ready).touch()
while not Path(go).exists(): time.sleep(0.01)
try:
    save_draft(Path(store), {'draft_id': draft_id, 'expected_revision': 1, 'trip_id': 'trip-1',
               'groups': [{'sha': sha, 'kind': 'analysis', 'jobId': None, 'receipts': [], 'empty': True}]},
               valid_trips={'trip-1'})
    print('SAVED')
except ValueError as error:
    print(str(error))
"""
    go = tmp_path / 'go'
    ready = [tmp_path / 'ready1', tmp_path / 'ready2']
    root = Path(__file__).resolve().parents[2]
    processes = [subprocess.Popen([sys.executable, '-c', worker, str(store), sha, draft_id, str(mark), str(go)],
                                  cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for mark in ready]
    try:
        deadline = time.monotonic() + 20
        while not all(mark.exists() for mark in ready) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(mark.exists() for mark in ready)
        go.touch()
        results = [proc.communicate(timeout=20) for proc in processes]
        assert all(proc.returncode == 0 for proc in processes), results
        assert sorted(out.strip() for out, _ in results) == ['DRAFT_STALE', 'SAVED']
        assert rr.load(store)['drafts'][0]['revision'] == 2
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_two_processes_replay_one_registration_without_duplicate_cost(tmp_path):
    store = tmp_path / 'receipts.json'
    sha = rr.store_image(store, PNG)['sha256']
    draft_id, operation_id = uuid.uuid4().hex, uuid.uuid4().hex
    group = {'sha': sha, 'kind': 'analysis', 'jobId': None, 'receipts': [], 'empty': True}
    rr.save_draft(store, {'draft_id': draft_id, 'expected_revision': 0,
                          'trip_id': 'trip-1', 'groups': [group]}, valid_trips={'trip-1'})
    worker = r"""
import json, sqlite3, sys, time
from pathlib import Path
from webapp.receipt_review import scan
store, sha, draft_id, operation_id, ready, go = sys.argv[1:]
class Board:
    conn = sqlite3.connect(':memory:')
    def list_trips(self): return [{'tab_id': 'trip-1'}]
payload = {'image': sha, 'trip_id': 'trip-1',
           'regions': [{'merchant': 'SYNTHETIC', 'date': '2026-10-12', 'total': 100,
                        'currency': 'JPY', 'payment': 'cash', 'confidence': 1}],
           'draft': {'draft_id': draft_id, 'expected_revision': 1,
                     'operation_id': operation_id, 'remaining_groups': []}}
Path(ready).touch()
while not Path(go).exists(): time.sleep(0.01)
print(json.dumps(scan(Path(store), payload, board=Board())))
"""
    go = tmp_path / 'go-scan'
    ready = [tmp_path / 'ready-scan1', tmp_path / 'ready-scan2']
    root = Path(__file__).resolve().parents[2]
    processes = [subprocess.Popen([sys.executable, '-c', worker, str(store), sha, draft_id, operation_id,
                                   str(mark), str(go)], cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for mark in ready]
    try:
        deadline = time.monotonic() + 20
        while not all(mark.exists() for mark in ready) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(mark.exists() for mark in ready)
        go.touch()
        results = [proc.communicate(timeout=20) for proc in processes]
        assert all(proc.returncode == 0 for proc in processes), results
        assert results[0][0] == results[1][0]
        data = rr.load(store)
        assert len(data['candidates']) == 1
        assert data['drafts'][0]['groups'] == []
        assert len(data['drafts'][0]['operations']) == 1
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
