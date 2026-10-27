"""Flight display refresh is independent of financial reconciliation."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from webapp import flight_booking_index as index, ota_snapshot


def test_mail_only_refresh_persistence_and_fail_closed(tmp_path, monkeypatch):
    mail = tmp_path / 'mail'
    mail.mkdir()
    source = mail / 'gmail-synthetic.json'
    source.write_text('{}', encoding='utf-8')
    # Use the actual environment constant rather than a production path.
    from webapp.ota_payment_review import SOURCES_ENV
    monkeypatch.setenv(SOURCES_ENV, json.dumps({'mail_directories': [str(mail)],
                          'missing': [{'kind': 'portal_database', 'path': 'unavailable-finance'}]}))
    booking = {'SYNTH': {'source_digests': ['synthetic'], 'passengers': [],
                          'cancellation_status': 'CANCELLED', 'conflict': True}}
    board = SimpleNamespace(path=tmp_path / 'board.sqlite',
                            _ota_snapshot_service=SimpleNamespace(held=lambda: (None, False)))
    factory = ota_snapshot.OtaSnapshotService
    def manual_service(**kwargs):
        return factory(**kwargs, start=False)
    with patch.object(index.ota_snapshot, 'OtaSnapshotService', side_effect=manual_service), \
            patch('webapp.ota_payment_review.review_db_path', return_value=tmp_path / 'review.sqlite'), \
            patch('webapp.ota_payment_review._passenger_index', return_value=booking) as parse:
        service = index.service_for(board)
        assert index.passenger_index_for(board) == {}
        assert index.source_status(board) == 'LOADING'
        service.check_now()
        assert index.passenger_index_for(board) == booking
        assert index.source_status(board) == 'VERIFIED'
        parse.assert_called_once_with([str(mail)], strict=True)
        # Restart loads the mail/parser-bound cache, even with finance unavailable.
        other = SimpleNamespace(path=board.path)
        restored = index.service_for(other)
        restored.check_now()
        assert index.passenger_index_for(other) == booking
        assert parse.call_count == 1
        # Failed changed input must never expose the old index as current.
        source.write_text('{"changed":true}', encoding='utf-8')
        parse.side_effect = ValueError('synthetic parsing failure')
        service.check_now()
        assert index.passenger_index_for(board) == {}
        assert index.source_status(board) == 'UNAVAILABLE'
        source.unlink()
        mail.rmdir()
        restored.check_now()
        assert index.passenger_index_for(other) == {}


def test_parse_failure_propagates_in_strict_mode():
    from webapp.ota_payment_review import _passenger_index
    with patch('app.flight_evidence.collect_flight_evidence', side_effect=ValueError('synthetic')):
        import pytest
        with pytest.raises(ValueError):
            _passenger_index([], strict=True)
        assert _passenger_index([]) == {}
