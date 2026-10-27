import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from app.reconcile import trace
from tools.audit_ota_card_coverage import _canonical_results, main


def test_unknown_ota_date_keeps_candidate_trace_and_redacts_ids(monkeypatch):
    event = {"ota_event_id": "real-booking-event", "provider": "agoda", "event_type": "charge",
             "evidence_status": "paid_verified", "payment_status": "paid", "paid_on": None,
             "amount": "12000", "amount_krw": 12000, "currency": "KRW", "card_last4": "1234"}
    card = {"transaction_id": "real-card-row", "approval_date": "2026-10-01", "amount_krw": 12000,
            "transaction_direction": "purchase", "card_tail": "1234", "issuer": "issuer-x",
            "merchant": "Agoda", "merchant_normalized": "agoda"}
    summary, cases = trace.build_coverage_report(events=[event], cards=[card], run_secret=b"x" * 32)
    assert summary["candidate_recall_proxy"] == 1
    ota_case = next(case for case in cases if case["direction"] == "OTA_TO_CARD")
    assert ota_case["candidate_count"] == 1
    assert ota_case["candidates"][0]["basis"] == "DATE_UNKNOWN_CANDIDATE"
    serialized = json.dumps([summary, cases])
    assert "real-booking-event" not in serialized
    assert "real-card-row" not in serialized
    assert summary["automatic_link_approvals"] == 0


def test_audit_reads_synthetic_board_and_writes_redacted_reports(tmp_path):
    board = tmp_path / "board.sqlite"
    connection = sqlite3.connect(board)
    connection.execute("CREATE TABLE transactions (transaction_id TEXT, merchant TEXT, amount_krw INTEGER)")
    connection.execute("INSERT INTO transactions VALUES ('private-transaction-id', 'Private merchant', 12000)")
    connection.commit()
    connection.close()

    data = tmp_path / "data"
    data.mkdir()
    (data / "ota-mail").mkdir()
    (data / "ota-sources.json").write_text(
        json.dumps({"schema_version": "ota-sources-v1", "mail_directories": [],
                    "portal_databases": [], "reference_documents": []}), encoding="utf-8")
    before = board.read_bytes()
    output = tmp_path / "audit-output"
    assert main(["--read-only", "--board-db", str(board), "--data-dir", str(data),
                 "--output-dir", str(output)]) == 0
    summary = json.loads((output / "coverage-summary.json").read_text(encoding="utf-8"))

    assert summary["status"] == "COMPLETE_INPUTS"
    assert summary["run_mode"] == "READ_ONLY"
    assert summary["automatic_link_approvals"] == 0
    assert summary["snapshot"]["registered_input_version_sha256"]
    assert board.read_bytes() == before
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert "private-transaction-id" not in report_text
    assert "Private merchant" not in report_text
    assert {path.name for path in output.iterdir()} == {
        "coverage-summary.json", "unmatched-cases.jsonl", "legacy-diff.jsonl",
        "reconciliation-diff.jsonl"}


def test_global_matcher_divergence_is_redacted_and_counted():
    event = {"ota_event_id": "private-event", "evidence_status": "paid_verified"}
    card = {"transaction_id": "private-card"}
    summary, _ = trace.build_coverage_report(
        events=[event], cards=[card], legacy_links={"private-event": "private-card"},
        reconciliation_results=[{"ota_event_id": "private-event", "status": "HOLD_AMBIGUOUS"}],
        run_secret=b"y" * 32)
    assert summary["legacy_engine_divergence_count"] == 1
    assert summary["reconciliation_engine_status_counts"] == {"HOLD_AMBIGUOUS": 1}
    assert "private-event" not in json.dumps(summary)
    assert "private-card" not in json.dumps(summary)


def test_shadow_engine_only_receives_user_links_as_frozen_decisions(monkeypatch):
    import tools.audit_ota_card_coverage as audit

    calls = []
    monkeypatch.setattr(audit.ota_payments, "match_ota_payment_events",
                        lambda events, cards, **kwargs: calls.append((events, cards, kwargs)) or [])
    events, cards = [{"ota_event_id": "synthetic-event"}], [{"transaction_id": "synthetic-card"}]
    user_links = {"synthetic-event": {"transaction_id": "synthetic-card", "status": "MATCHED_USER"}}

    assert _canonical_results(events, cards, user_links, [{"event_ids": ["synthetic-event"]}]) == []
    assert calls == [(events, cards, {"existing_links": user_links,
                                      "frozen_groups": [{"event_ids": ["synthetic-event"]}]})]


PRIVATE = 'SYNTHETIC_PRIVATE_CUSTOMER_MESSAGE_' * 200


def test_all_external_report_text_is_finite_and_ids_remain_hmac():
    event = {'ota_event_id': PRIVATE, 'provider': PRIVATE, 'evidence_status': PRIVATE,
             'booking_ref': PRIVATE, 'source_ids': [PRIVATE], 'paid_on': PRIVATE}
    card = {'transaction_id': PRIVATE, 'merchant': PRIVATE, 'parse_error': PRIVATE}
    observations = {'raw_observations': PRIVATE, 'raw_mail_observations': PRIVATE,
        'skipped_reason_counts': {PRIVATE: 3, 'SOURCE_UNREADABLE': PRIVATE}, PRIVATE: PRIVATE,
        'skipped': [{'source': PRIVATE, 'reason': [PRIVATE, 'SOURCE_UNREADABLE'],
                     'error_type': PRIVATE, PRIVATE: PRIVATE}]}
    results = [{'ota_event_id': PRIVATE, 'status': PRIVATE}]
    before = deepcopy((event, card, observations, results))
    summary, cases = trace.build_coverage_report(events=[event], cards=[card],
        observation_report=observations, source_diagnostics=[PRIVATE, 'SOURCE_MISSING:' + PRIVATE],
        reconciliation_results=results, legacy_links={PRIVATE: PRIVATE}, run_secret=b'x' * 32)
    encoded = json.dumps([summary, cases])
    assert PRIVATE not in encoded and 'SYNTHETIC_PRIVATE_CUSTOMER_MESSAGE' not in encoded
    assert cases[0]['provider'] == cases[0]['evidence_status'] == 'UNKNOWN'
    assert summary['provider_event_counts'] == {'UNKNOWN': 1}
    assert summary['reconciliation_engine_status_counts'] == {'UNKNOWN': 1}
    assert summary['reconciliation_divergences'][0]['engine_status'] == 'UNKNOWN'
    assert summary['source_diagnostics'] == ['UNKNOWN', 'UNKNOWN']
    assert summary['observation_counts']['raw_observations'] == 'UNKNOWN'
    assert summary['observation_counts']['skipped'][0]['reason'] == ['UNKNOWN', 'SOURCE_UNREADABLE']
    assert cases[0]['id'] == trace.pseudonym(b'x' * 32, 'ota', PRIVATE)
    assert cases[1]['id'] == trace.pseudonym(b'x' * 32, 'card', PRIVATE)
    assert (event, card, observations, results) == before


@pytest.mark.parametrize('provider', sorted(trace.PROVIDERS))
def test_normal_provider_values_are_preserved(provider):
    summary, cases = trace.build_coverage_report(events=[{'ota_event_id': 'synthetic', 'provider': provider}], cards=[])
    assert cases[0]['provider'] == provider
    assert summary['provider_event_counts'] == {provider: 1}


@pytest.mark.parametrize('status', sorted(trace.EVIDENCE_STATUSES))
def test_normal_evidence_values_are_preserved(status):
    _, cases = trace.build_coverage_report(events=[{'ota_event_id': 'synthetic', 'evidence_status': status}], cards=[])
    assert cases[0]['evidence_status'] == status


@pytest.mark.parametrize('status', sorted(trace.ENGINE_STATUSES))
def test_normal_engine_values_are_preserved(status):
    summary, _ = trace.build_coverage_report(events=[{'ota_event_id': 'synthetic'}], cards=[],
        reconciliation_results=[{'ota_event_id': 'synthetic', 'status': status}],
        legacy_links={'synthetic': 'synthetic-legacy-card'})
    assert summary['reconciliation_engine_status_counts'] == {status: 1}
    assert summary['reconciliation_divergences'][0]['engine_status'] == status


def test_normal_observation_contract_is_preserved_without_copying_extra_fields():
    observations = {'raw_mail_observations': 2, 'raw_portal_observations': 3, 'raw_observations': 5,
        'skipped_observation_count': 1, 'portal_local_id_reuse_count': 0, 'possible_source_copy_count': 0,
        'skipped_reason_counts': {'EVIDENCE_ROLE_MISSING': 1},
        'skipped': [{'source': 'synthetic-source', 'reason': ['EVIDENCE_ROLE_MISSING'],
                     'error_type': 'ValueError'}]}
    summary, _ = trace.build_coverage_report(events=[], cards=[], observation_report=observations,
        source_diagnostics=['SOURCE_MISSING:portal_database', 'REVIEW_SOURCE_OperationalError'])
    safe = summary['observation_counts']
    assert safe['raw_observations'] == 5
    assert safe['skipped_reason_counts'] == {'EVIDENCE_ROLE_MISSING': 1}
    assert safe['skipped'][0]['reason'] == ['EVIDENCE_ROLE_MISSING']
    assert safe['skipped'][0]['error_type'] == 'ValueError'
    assert summary['source_diagnostics'] == ['SOURCE_MISSING:portal_database', 'REVIEW_SOURCE_OperationalError']


def synthetic_inputs(tmp_path):
    board = tmp_path / 'synthetic-board.sqlite'
    with sqlite3.connect(board) as conn:
        conn.execute('CREATE TABLE transactions (transaction_id TEXT, merchant TEXT, amount_krw INTEGER)')
        conn.execute("INSERT INTO transactions VALUES ('synthetic-id', 'synthetic-merchant', 100)")
    data = tmp_path / 'synthetic-data'
    data.mkdir()
    (data / 'ota-mail').mkdir()
    manifest = data / 'ota-sources.json'
    manifest.write_text(json.dumps({'schema_version': 'ota-sources-v1',
        'mail_directories': [], 'portal_databases': [], 'reference_documents': []}), encoding='utf-8')
    return board, data, manifest


@pytest.mark.parametrize('populated', [False, True])
def test_existing_output_even_empty_is_rejected_before_reading_inputs(tmp_path, monkeypatch, populated):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    output = tmp_path / 'existing-output'
    output.mkdir()
    if populated:
        (output / 'coverage-summary.json').write_text('existing synthetic document', encoding='utf-8')
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    monkeypatch.setattr(audit, '_read_rows', lambda *a: pytest.fail('input read before output validation'))
    with pytest.raises(ValueError, match='OUTPUT_ALREADY_EXISTS'):
        audit.audit(board_db=board, data_dir=data, output_dir=output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


@pytest.mark.parametrize('relationship', ['ancestor', 'same-file', 'below-file', 'mail-child', 'registered-child', 'wal', 'shm'])
def test_output_cannot_overlap_input_files_or_directories(tmp_path, relationship):
    import tools.audit_ota_card_coverage as audit
    board, data, manifest = synthetic_inputs(tmp_path)
    if relationship == 'registered-child':
        source = tmp_path / 'registered-mail'
        source.mkdir()
        document = json.loads(manifest.read_text(encoding='utf-8'))
        document['mail_directories'] = [str(source.resolve())]
        manifest.write_text(json.dumps(document), encoding='utf-8')
        output = source / 'output'
    else:
        output = {'ancestor': tmp_path, 'same-file': board, 'below-file': board / 'output',
                  'mail-child': data / 'ota-mail' / 'output', 'wal': Path(str(board) + '-wal'),
                  'shm': Path(str(board) + '-shm')}[relationship]
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='OUTPUT_INPUT_OVERLAP'):
        audit.audit(board_db=board, data_dir=data, output_dir=output)
    assert {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_serialization_failure_creates_no_output(tmp_path, monkeypatch):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    output = tmp_path / 'new-output'
    monkeypatch.setattr(audit, 'build_coverage_report', lambda **kw: ({'bad': object()}, []))
    with pytest.raises(TypeError):
        audit.audit(board_db=board, data_dir=data, output_dir=output)
    assert not output.exists()


def test_io_failure_keeps_partial_output_without_publishing_summary_or_deleting_files(tmp_path, monkeypatch):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    output = tmp_path / 'partial-output'
    original = audit._write_jsonl
    def fail_second(path, payload):
        if path.name == 'legacy-diff.jsonl':
            (output / 'concurrent-user-file').write_text('preserve', encoding='utf-8')
            raise OSError('synthetic disk failure')
        original(path, payload)
    monkeypatch.setattr(audit, '_write_jsonl', fail_second)
    before = board.read_bytes()
    with pytest.raises(OSError):
        audit.audit(board_db=board, data_dir=data, output_dir=output)
    assert not (output / 'coverage-summary.json').exists()
    assert (output / 'unmatched-cases.jsonl').exists()
    assert (output / 'concurrent-user-file').read_text(encoding='utf-8') == 'preserve'
    assert board.read_bytes() == before


def test_actual_input_connection_rejects_writes_and_all_input_bytes_are_preserved(tmp_path, monkeypatch):
    import tools.audit_ota_card_coverage as audit
    board, data, manifest = synthetic_inputs(tmp_path)
    portal = tmp_path / 'synthetic-portal.sqlite'
    with sqlite3.connect(portal) as conn:
        conn.execute('CREATE TABLE bookings (id INTEGER, booking_number TEXT, service_start_on TEXT, service_end_on TEXT, status TEXT, provider TEXT)')
        conn.execute('CREATE TABLE booking_source_evidence (booking_id INTEGER, direct_source_record_id INTEGER, evidence_role TEXT, evidence_status TEXT, conflict_count INTEGER, conflict_json TEXT)')
        conn.execute('CREATE TABLE direct_source_records (id INTEGER, payload_json TEXT, source_sha256 TEXT, source_kind TEXT)')
    review = tmp_path / 'synthetic-review.sqlite'
    with sqlite3.connect(review) as conn:
        conn.execute('PRAGMA user_version=1')
    document = json.loads(manifest.read_text(encoding='utf-8'))
    document['portal_databases'] = [str(portal.resolve())]
    manifest.write_text(json.dumps(document), encoding='utf-8')
    original = sqlite3.connect
    opened = []
    def guarded_connect(database, *args, **kwargs):
        assert str(database).endswith('?mode=ro') and kwargs.get('uri') is True
        conn = original(database, *args, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('CREATE TABLE forbidden_write(value TEXT)')
        opened.append(str(database))
        return conn
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    audit.audit(board_db=board, data_dir=data, review_db=review, output_dir=tmp_path / 'new-output')
    assert all(any(path.as_uri() in opened_path for opened_path in opened) for path in (board, portal, review))
    assert all(Path(p).read_bytes() == content for p, content in before.items())


def test_all_four_files_and_stdout_redact_contaminated_sources(tmp_path, monkeypatch, capsys):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    dirty_event = {'ota_event_id': PRIVATE, 'provider': PRIVATE, 'evidence_status': PRIVATE}
    dirty_observations = {'raw_observations': 1, 'skipped_reason_counts': {PRIVATE: 1},
        'skipped': [{'source': PRIVATE, 'reason': PRIVATE, 'error_type': PRIVATE}], PRIVATE: PRIVATE}
    monkeypatch.setattr(audit.ota_payments, 'build_ota_payment_events', lambda *a, **kw: [dirty_event])
    monkeypatch.setattr(audit, 'inspect_observations', lambda *a: dirty_observations)
    monkeypatch.setattr(audit, '_canonical_results', lambda *a: [
        {'ota_event_id': PRIVATE, 'status': PRIVATE, 'transaction_id': PRIVATE}])
    monkeypatch.setattr(audit, '_source_digest', lambda *a: (PRIVATE, PRIVATE))
    output = tmp_path / 'clean-output'
    assert main(['--read-only', '--board-db', str(board), '--data-dir', str(data), '--output-dir', str(output)]) == 0
    encoded = capsys.readouterr().out + ''.join(p.read_text(encoding='utf-8') for p in output.iterdir())
    assert 'SYNTHETIC_PRIVATE_CUSTOMER_MESSAGE' not in encoded
    summary = json.loads((output / 'coverage-summary.json').read_text(encoding='utf-8'))
    assert summary['snapshot']['registered_input_version_sha256'] is None
    assert summary['snapshot']['input_stamp_error'] == 'UNKNOWN'


def test_exclusive_file_creation_preserves_a_concurrent_output_file(tmp_path, monkeypatch):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    output = tmp_path / 'new-output'
    original = audit._write_jsonl
    def concurrent_file(path, payload):
        path.write_text('concurrent synthetic user data', encoding='utf-8')
        original(path, payload)
    monkeypatch.setattr(audit, '_write_jsonl', concurrent_file)
    with pytest.raises(FileExistsError):
        audit.audit(board_db=board, data_dir=data, output_dir=output)
    assert (output / 'unmatched-cases.jsonl').read_text(encoding='utf-8') == 'concurrent synthetic user data'
    assert not (output / 'coverage-summary.json').exists()


def test_cli_never_echoes_output_path_or_arbitrary_exception_name(tmp_path, monkeypatch, capsys):
    import tools.audit_ota_card_coverage as audit
    board, data, _ = synthetic_inputs(tmp_path)
    output = tmp_path / 'SYNTHETIC_PRIVATE_OUTPUT_NAME'
    assert main(['--read-only', '--board-db', str(board), '--data-dir', str(data), '--output-dir', str(output)]) == 0
    assert 'SYNTHETIC_PRIVATE_OUTPUT_NAME' not in capsys.readouterr().out
    private_error = type('SYNTHETIC_PRIVATE_EXCEPTION_NAME', (Exception,), {})
    def fail(**kwargs):
        raise private_error(PRIVATE)
    monkeypatch.setattr(audit, 'audit', fail)
    assert main(['--read-only', '--board-db', str(board), '--output-dir', str(output)]) == 2
    assert json.loads(capsys.readouterr().out)['error_type'] == 'UNKNOWN'
