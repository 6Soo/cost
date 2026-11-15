"""Receipt upload, analysis and candidate saving never require a trip choice (hotfix)."""
import re
import uuid

import pytest

from webapp import receipt_review as rr
from webapp.tests import test_receipt_review as review

PNG = review.PNG


def test_page_script_has_no_trip_gate(tmp_path):
    page = rr.render_html(rr.load(tmp_path / 'r.json'), 'csrf', [{'id': 't1', 'name': 'T'}])
    assert '여행을 먼저 선택하세요' not in page
    assert '분석 결과를 저장할 여행을 선택해 주세요' not in page


def test_draft_and_scan_without_trip_save_unassigned_candidate(tmp_path):
    store = tmp_path / 'receipts.json'
    sha = rr.store_image(store, PNG)['sha256']
    draft_id, operation_id = uuid.uuid4().hex, uuid.uuid4().hex
    group = {'sha': sha, 'kind': 'analysis', 'jobId': None,
             'receipts': [{'merchant': 'SYNTHETIC', 'date': '2026-11-01', 'amount': 100, 'currency': 'JPY',
                           'payment': 'cash', 'include': True}]}
    saved = rr.save_draft(store, {'draft_id': draft_id, 'expected_revision': 0, 'trip_id': '', 'groups': [group]}, valid_trips=set())
    assert saved['trip_id'] == ''
    again = rr.save_draft(store, {'draft_id': draft_id, 'expected_revision': 1, 'trip_id': None, 'groups': [group]}, valid_trips=set())
    assert again['revision'] == 2
    result = rr.scan(store, {'image': sha, 'regions': [{'box': None, 'merchant': 'SYNTHETIC', 'date': '2026-11-01', 'currency': 'JPY',
                                                          'total': 100, 'payment': 'cash', 'confidence': 1}],
                             'draft': {'draft_id': draft_id, 'expected_revision': 2, 'operation_id': operation_id,
                                       'remaining_groups': []}})
    assert result['added'] == 1
    candidate = rr.load(store)['candidates'][0]
    assert not candidate.get('trip_id')
