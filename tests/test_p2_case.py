import copy
import json

import pytest

from app import p2_case
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip
from app import ai_classification


def prepared(board):
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)
    trips = [dict(trip_id=trip, starts_on='2026-10-01', ends_on='2026-10-05', destination='합성 여행')]
    return ai_classification.prepare(board.conn, trips, ids), trips


class Evidence:
    def __init__(self, items):
        self.items = items

    def select(self, case, row):
        return [dict(item, transaction_id=case['transaction_id']) for item in self.items]


def test_bundle_is_deterministic_bound_and_read_only(setup):
    request, trips = prepared(setup)
    repo = Evidence([dict(ref='mail:2', kind='mail', content='합성 예약 2'),
                     dict(ref='mail:1', kind='mail', content='합성 예약 1')])
    before = '\n'.join(setup.conn.iterdump())
    bundle = p2_case.assemble(setup.conn, trips, request, repository=repo)
    repo.items.reverse()
    assert p2_case.assemble(setup.conn, trips, request, repository=repo) == bundle
    assert bundle['cases'][0]['transaction']['merchant'].startswith('SYNTHETIC')
    assert [e['ref'] for e in bundle['evidence']] == ['mail:1', 'mail:2']
    assert bundle['request_digest'] == request['digest']
    assert 'PROC-001' in bundle['policy']['CORE']
    assert '\n'.join(setup.conn.iterdump()) == before


def test_unicode_evidence_truncation_is_explicit_and_within_bytes(setup):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request, repository=Evidence([
        dict(ref='mail:big', kind='mail', content='한글' * 150000)]), max_bytes=196608)
    assert len(p2_case.prompt(bundle).encode('utf-8')) <= 196608
    assert bundle['evidence'][0]['truncated'] is True
    assert bundle['evidence'][0]['source_sha256']
    assert bundle['truncated'] is True


@pytest.mark.parametrize('ref', ['../secret', 'evidence/../../secret', 'C:\\secret', 'https://example.test'])
def test_evidence_refs_cannot_be_paths_or_commands(setup, ref):
    request, trips = prepared(setup)
    with pytest.raises(ValueError, match='P2_EVIDENCE_REF_INVALID'):
        p2_case.assemble(setup.conn, trips, request, repository=Evidence([
            dict(ref=ref, kind='mail', content='synthetic')]))


def test_secrets_removed_without_mutating_repository(setup):
    request, trips = prepared(setup)
    repo = Evidence([dict(ref='mail:one', kind='mail', content={
        'text': '예약 원문', 'access_token': 'DO-NOT-EXPORT', 'headers': {'Authorization': 'secret'}})])
    original = copy.deepcopy(repo.items)
    bundle = p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert 'DO-NOT-EXPORT' not in json.dumps(bundle)
    assert 'secret' not in json.dumps(bundle)
    assert repo.items == original


def test_registered_unparsed_mail_is_selected_but_unrelated_mail_is_not_exported(setup, tmp_path):
    import base64
    request, trips = prepared(setup)
    directory = tmp_path / 'mail'
    directory.mkdir()
    def message(identity, text):
        return dict(id=identity, internalDate='1791000000000', payload=dict(headers=[
            dict(name='Subject', value='Synthetic reservation')],
            mimeType='text/plain', body=dict(data=base64.urlsafe_b64encode(text.encode()).decode())))
    path = directory / 'gmail-fixture.json'
    path.write_text(json.dumps(dict(responses=[message('relevant', 'AUTONOMY 10000 예약 이용기간: 2026-10-01'),
                                             message('unrelated', 'UNRELATED PRIVATE LETTER 2026-10-03')]), ensure_ascii=False), encoding='utf-8')
    before = path.read_bytes()
    repo = p2_case.Repository(setup.conn, {'mail_directories': [directory]})
    bundle = p2_case.assemble(setup.conn, trips, request, repository=repo)
    assert any('예약 이용기간' in e['content'] for e in bundle['evidence'])
    assert 'UNRELATED PRIVATE LETTER' not in p2_case.prompt(bundle)
    assert path.read_bytes() == before


def test_policy_contract_includes_exceptions_process_and_attribution_domains(setup):
    request, trips = prepared(setup)
    bundle = p2_case.assemble(setup.conn, trips, request)
    assert {'CORE', 'process', 'trip', 'item', 'date'} <= set(bundle['policy'])
    assert '## 5. 사용자 예외' in bundle['policy']['CORE']
    for name, identity in [('process', 'PROC-001'), ('trip', 'TRIP-069'), ('date', 'DATE-001')]:
        assert identity in bundle['policy'][name]
    assert '대체된 옛 규칙:' not in json.dumps(bundle['policy'], ensure_ascii=False)
    with pytest.raises(ValueError, match='P2_PROMPT_BASE_TOO_LARGE'):
        p2_case.assemble(setup.conn, trips, request, max_bytes=110000)


def test_ota_and_refund_policy_domains_are_included(setup):
    request, trips = prepared(setup)
    tid = request['cases'][0]['transaction_id']
    setup.conn.execute("UPDATE transactions SET merchant='SYNTHETIC 예약',description_raw='refund 취소' WHERE transaction_id=?", (tid,))
    # Full required policies exceed the small prompt budget; no silent omission.
    bundle = p2_case.assemble(setup.conn, trips, request, repository=Evidence([
        dict(ref='portal:one', kind='portal', content='합성 예약')]), max_bytes=400000)
    assert 'LINK-002' in bundle['policy']['link']
    assert 'RFND-018' in bundle['policy']['refund']
    with pytest.raises(ValueError, match='P2_PROMPT_BASE_TOO_LARGE'):
        p2_case.assemble(setup.conn, trips, request, repository=Evidence([
            dict(ref='portal:one', kind='portal', content='합성 예약')]))
