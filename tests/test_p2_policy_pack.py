"""Opt-in P2 context packet tests; no live AI, payments or Google writes."""
import copy
import json
import re

import pytest

from app import p2_case, p2_policy_pack
from webapp.tests.test_autonomous_cleanup import setup, receive, make_weak_rows, create_trip, response_for
from app import ai_classification


def _prepared(board):
    trip = create_trip(board)
    batch, rows = receive(board, 1)
    ids = make_weak_rows(board, batch, rows, trip)
    trips = [dict(trip_id=trip, starts_on='2026-10-01', ends_on='2026-10-05',
                  destination='합성 여행')]
    return ai_classification.prepare(board.conn, trips, ids), trips


def test_compact_rule_packet_preserves_exact_source_and_sensitive_boundaries():
    full = p2_case.policy_context(('link', 'refund'))
    short = p2_case.policy_context(('link', 'refund'), compact=True)
    assert set(short) == set(full) == {'CORE', 'process', 'trip', 'item', 'date', 'link', 'refund'}
    assert short['CORE'] == full['CORE']
    assert len(json.dumps(short, ensure_ascii=False)) < 0.70 * len(json.dumps(full, ensure_ascii=False))
    for area, required in {
        'process': ('PROC-010', 'PROC-011', 'PROC-014', 'PROC-072'),
        'trip': ('TRIP-042', 'TRIP-045', 'TRIP-048', 'TRIP-049', 'TRIP-069', 'TRIP-071', 'TRIP-099'),
        'item': ('ITEM-080', 'ITEM-024', 'ITEM-082'),
        'date': ('DATE-023', 'DATE-109'),
        'link': ('LINK-002', 'LINK-003', 'LINK-024', 'LINK-025', 'LINK-030', 'LINK-044'),
        'refund': ('RFND-004', 'RFND-018', 'RFND-029'),
    }.items():
        for rule in required:
            assert rule in short[area]
    # All selected rule IDs must exist in the canonical source file. PROC
    # safety rules may be selected even if the legacy full packet omitted them.
    for area in set(short) - {'CORE'}:
        source = (p2_case.ROOT / 'docs/policy' / (area + '.md')).read_text(encoding='utf-8')
        for section in short[area].split('\n\n### '):
            if not section.strip():
                continue
            fragment = section if section.startswith('### ') else '### ' + section
            assert fragment.split('\n', 1)[0] in source


def test_compact_assemble_does_not_change_cases_or_evidence(setup):
    request, trips = _prepared(setup)
    full = p2_case.assemble(setup.conn, trips, request)
    short = p2_case.assemble(setup.conn, trips, request, compact_policy=True)
    assert short['cases'] == full['cases']
    assert short['evidence'] == full['evidence']
    assert short['policy']['CORE'] == full['policy']['CORE']
    assert short['policy_digest'] == p2_case.digest(short['policy'])
    assert short['request_digest'] == full['request_digest']
    assert len(p2_case.prompt(short).encode('utf-8')) < len(p2_case.prompt(full).encode('utf-8'))


def test_unknown_new_rule_catalog_falls_back_to_full(tmp_path, monkeypatch):
    source = p2_case.ROOT
    policy_dir = tmp_path / 'docs/policy'
    policy_dir.mkdir(parents=True)
    (tmp_path / 'docs/DECISION_POLICY.md').write_bytes(
        (source / 'docs/DECISION_POLICY.md').read_bytes())
    for area in ('process', 'trip', 'item', 'date'):
        (policy_dir / (area + '.md')).write_bytes(
            (source / 'docs/policy' / (area + '.md')).read_bytes())
    trip = policy_dir / 'trip.md'
    # newline='' keeps LF off Windows; CRLF alone would change the catalog
    # fingerprint and make this pass without the rule that is under test.
    trip.write_text(trip.read_text(encoding='utf-8', newline='')
                    + '\n### TRIP-999 · 정책이 추가된 미검수 사례\n\n*보호*\n\n정본 미검수.\n',
                    encoding='utf-8', newline='')
    assert p2_policy_pack.compact_policy_context(tmp_path) is None
    monkeypatch.setattr(p2_case, 'ROOT', tmp_path)
    assert p2_case.policy_context(compact=True) == p2_case.policy_context(compact=False)


@pytest.mark.parametrize('scenario,requirements', [
    ('ota_one_to_one', {'link': ['LINK-002', 'LINK-003']}),
    ('ota_m_to_n_undated', {'item': ['ITEM-080'], 'link': ['LINK-003']}),
    ('ota_unrelated_non_pg', {'date': ['DATE-023'], 'link': ['LINK-002']}),
    ('lodging_stay_nights', {'trip': ['TRIP-039', 'TRIP-042']}),
    ('flight_departure_arrival', {'trip': ['TRIP-040'], 'item': ['ITEM-082']}),
    ('service_date_unverified', {'date': ['DATE-109'], 'trip': ['TRIP-038']}),
    ('refund_one_to_many', {'refund': ['RFND-004', 'RFND-018', 'RFND-029']}),
    ('closed_quarter', {'process': ['PROC-072']}),
    ('p2_unmatched_evidence', {'process': ['PROC-010'], 'link': ['LINK-044']}),
    ('payment_cutoff_owner_decision', {'trip': ['TRIP-099']}),
    ('discount_exception_proof', {'link': ['LINK-024', 'LINK-025']}),
    ('cancelled_booking_is_not_a_trip', {'trip': ['TRIP-048', 'TRIP-097']}),
])
def test_synthetic_scenario_rule_coverage(scenario, requirements):
    """Coverage of explicitly identified policy clauses, not model answer parity."""
    policy = p2_case.policy_context(('link', 'refund'), compact=True)
    for area, ids in requirements.items():
        present = set(re.findall(r'(?m)^### ([A-Z]{3,6}-\d{3}) · ', policy[area]))
        assert set(ids) <= present, f'{scenario}: missing required {area} rule'


def test_changed_existing_policy_body_forces_full_fallback(tmp_path, monkeypatch):
    source = p2_case.ROOT
    catalog = tmp_path / 'docs/policy'
    catalog.mkdir(parents=True)
    (tmp_path / 'docs/DECISION_POLICY.md').write_bytes(
        (source / 'docs/DECISION_POLICY.md').read_bytes())
    for area in ('process', 'trip', 'item', 'date'):
        (catalog / (area + '.md')).write_bytes(
            (source / 'docs/policy' / (area + '.md')).read_bytes())
    trip = catalog / 'trip.md'
    original = trip.read_text(encoding='utf-8', newline='')
    assert '### TRIP-042 ·' in original
    # Same catalog and no new ID, so only the changed *body* can trigger fallback.
    trip.write_text(original + '\n<!-- New unreviewed policy note -->\n',
                    encoding='utf-8', newline='')
    assert p2_policy_pack.compact_policy_context(tmp_path) is None
    monkeypatch.setattr(p2_case, 'ROOT', tmp_path)
    assert p2_case.policy_context(compact=True) == p2_case.policy_context(compact=False)


@pytest.mark.parametrize('status,refund_expected', [
    ('confirmed', False),
    ('cancelled', True),
])
def test_ota_refund_assemble_preserves_source_and_case_setup(
        setup, status, refund_expected):
    """Same synthetic case/evidence, with only policy packet reduced."""
    request, trips = _prepared(setup)

    class Portal:
        def select(self, case, row):
            return [dict(transaction_id=case['transaction_id'],
                         ref='portal:synthetic', kind='portal',
                         content={'reservation_status': status,
                                  'text': 'SYNTHETIC OTA booking'})]

    repo = Portal()
    before = '\n'.join(setup.conn.iterdump())
    full = p2_case.assemble(setup.conn, trips, request, repository=repo)
    compact = p2_case.assemble(
        setup.conn, trips, request, repository=repo, compact_policy=True)
    assert before == '\n'.join(setup.conn.iterdump())
    assert compact['cases'] == full['cases']
    assert compact['evidence'] == full['evidence']
    assert compact['omitted_evidence'] == full['omitted_evidence']
    assert compact['truncated'] == full['truncated']
    assert ('refund' in compact['policy']) is refund_expected
    assert 'link' in compact['policy']
    assert set(compact['policy']) == set(full['policy'])
    assert 'LINK-003' in compact['policy']['link']
    assert compact['policy_digest'] == p2_case.digest(compact['policy'])
    assert len(p2_case.prompt(compact).encode()) < len(p2_case.prompt(full).encode())



def _synthetic_p2_response(request):
    answer = response_for(request)
    answer['more_evidence'] = []
    for row in answer['results']:
        row.update(service_start='', service_end='', evidence_refs=[],
                   rule_ids=['PROC-001'])
    return answer


def test_verified_compact_preview_matches_full_decision_without_any_write(setup):
    """Full and compact validated P2 yield identical classification decisions.

    Evidence/policy digests are intentionally different and may not be reused.
    This compares a deterministic synthetic answer, not independent LLM output.
    """
    request, trips = _prepared(setup)
    full = p2_case.assemble(setup.conn, trips, request)
    compact = p2_case.assemble(setup.conn, trips, request, compact_policy=True)
    response = _synthetic_p2_response(request)
    before = '\n'.join(setup.conn.iterdump())
    old = ai_classification.preview(setup.conn, trips, request, response, bundle=full)
    new = ai_classification.preview(setup.conn, trips, request, response, bundle=compact)
    assert before == '\n'.join(setup.conn.iterdump())
    assert len(old['corrections']) == len(new['corrections']) == len(request['cases'])
    fields = ('transaction_id', 'source_hash', 'revision', 'trip_id', 'item',
              'basis', 'classification_source', 'execution')
    assert ([{k: row[k] for k in fields} for row in old['corrections']] ==
            [{k: row[k] for k in fields} for row in new['corrections']])


def test_forged_compact_policy_is_rejected_even_with_recomputed_bundle_digest(setup):
    request, trips = _prepared(setup)
    compact = p2_case.assemble(setup.conn, trips, request, compact_policy=True)
    response = _synthetic_p2_response(request)
    tampered = copy.deepcopy(compact)
    tampered['policy']['trip'] += '\n### TRIP-999 · Unreviewed exception\n'
    tampered['policy_digest'] = p2_case.digest(tampered['policy'])
    tampered['digest'] = p2_case.digest({k: v for k, v in tampered.items() if k != 'digest'})
    before = '\n'.join(setup.conn.iterdump())
    with pytest.raises(ValueError, match='AI_POLICY_STALE'):
        ai_classification.preview(setup.conn, trips, request, response, bundle=tampered)
    assert before == '\n'.join(setup.conn.iterdump())


def _blob_hashes(root):
    import hashlib
    from pathlib import Path
    return {area: hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
            for area, path in {'CORE': 'docs/DECISION_POLICY.md',
                               **{key: 'docs/policy/' + key + '.md'
                                 for key in ('process', 'trip', 'item', 'date', 'link', 'refund')}}.items()
            for raw in [(Path(root) / path).read_bytes()]}


def test_every_approved_revision_matches_one_reviewed_snapshot():
    """The checked-out snapshot must itself be approved, or compact silently degrades.

    PR #1016 rewrote two unpinned rule bodies on main after this branch was cut,
    which made every compact request fall back to the full packet until the
    exact blob set was added here. This test fails as soon as that happens again.
    """
    assert _blob_hashes(p2_case.ROOT) in p2_policy_pack.APPROVED_POLICY_REVISIONS.values(), (
        'the checked-out policy snapshot is not an approved revision, so compact '
        'silently degrades to the full packet')
    for name, revision in p2_policy_pack.APPROVED_POLICY_REVISIONS.items():
        assert set(revision) == {'CORE', 'process', 'trip', 'item', 'date', 'link', 'refund'}, name


def test_the_checked_out_snapshot_is_approved_and_gated_by_exact_blobs(
        tmp_path, monkeypatch):
    """Two guards in one place: today's snapshot approves, any other does not.

    The exact blob check is what keeps a same-catalog snapshot out, so it has to
    fail when a rule body changes inside an unpinned rule. ``newline=''`` keeps
    LF: TextIOWrapper would otherwise write CRLF on Windows, change the catalog
    fingerprint, and let the test pass without the blob gate.
    """
    catalog = tmp_path / 'docs/policy'
    catalog.mkdir(parents=True)
    (tmp_path / 'docs/DECISION_POLICY.md').write_bytes(
        (p2_case.ROOT / 'docs/DECISION_POLICY.md').read_bytes())
    for area in ('process', 'trip', 'item', 'date', 'link', 'refund'):
        (catalog / (area + '.md')).write_bytes(
            (p2_case.ROOT / 'docs/policy' / (area + '.md')).read_bytes())
    assert p2_policy_pack.compact_policy_context(tmp_path, ('link', 'refund')) is not None

    text = (catalog / 'trip.md').read_text(encoding='utf-8', newline='')
    anchor = '\n### TRIP-043 ·'
    assert anchor in text
    note = '\n- 미검수 메모.\n'
    (catalog / 'trip.md').write_text(
        text.replace(anchor, note + anchor, 1), encoding='utf-8', newline='')
    assert p2_policy_pack.compact_policy_context(tmp_path, ('link', 'refund')) is None
