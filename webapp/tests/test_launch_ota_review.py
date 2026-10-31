"""card-flow.json의 OTA 검토 설정만 환경 변수를 정한다. 설정이 없으면 legacy다."""
import importlib.util
import os
import tempfile
import unittest
import json
import pytest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('launch_web_ledger', ROOT / 'tools' / 'launch_web_ledger.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

VARS = ('WEBLEDGER_OTA_REVIEW_MODE', 'WEBLEDGER_OTA_REVIEW_DB', 'WEBLEDGER_OTA_AUTHORITY')


def test_product_features_use_explicit_opt_in_and_durable_paths(tmp_path):
    with patch.dict(os.environ):
        launcher.apply_product_features({'receipts': {'enabled': True, 'ocr': 'windows'},
                                         'google_ledger': {'enabled': True}}, tmp_path)
        assert os.environ['WEBLEDGER_RECEIPTS_STORE'] == str(tmp_path / 'receipts/receipts.json')
        assert os.environ['WEBLEDGER_RECEIPT_OCR'] == 'windows'
        assert os.environ['WEBLEDGER_GOOGLE_LEDGER_ROWS'] == str(tmp_path / 'google-authority/rows.json')
        launcher.apply_product_features({}, tmp_path)
        assert not any(os.environ.get(key) for key in ('WEBLEDGER_RECEIPTS_STORE', 'WEBLEDGER_RECEIPT_OCR', 'WEBLEDGER_GOOGLE_LEDGER_ROWS'))


def test_passenger_feature_requires_explicit_opt_in_and_uses_durable_database(tmp_path):
    keys = ('WEBLEDGER_FLIGHT_PASSENGER_MATCHING', 'WEBLEDGER_FLIGHT_PASSENGER_DB')
    with patch.dict(os.environ, {key:'inherited' for key in keys}):
        launcher.apply_product_features({}, tmp_path)
        assert not any(key in os.environ for key in keys)
        launcher.apply_product_features({'flight_passengers':{'enabled':True}}, tmp_path)
        assert os.environ[keys[0]] == '1'
        assert os.environ[keys[1]] == str(tmp_path/'flight-passenger.sqlite')
        assert not (tmp_path/'flight-passenger.sqlite').exists()
        launcher.apply_product_features({'flight_passengers':{'enabled':False}}, tmp_path)
        assert not any(key in os.environ for key in keys)


def test_insurance_manifest_requires_opt_in_absolute_existing_file_and_resets(tmp_path):
    key = 'WEBLEDGER_INSURANCE_REVIEW_MANIFEST'
    manifest = tmp_path / 'synthetic-manifest.json'
    manifest.write_text('{}', encoding='utf-8')
    with patch.dict(os.environ, {key: 'inherited'}):
        launcher.apply_product_features({}, tmp_path)
        assert key not in os.environ
        for invalid in ('relative.json', str(tmp_path / 'missing.json'), str(tmp_path)):
            with pytest.raises(launcher._Refused):
                launcher.apply_product_features({'insurance_review': {'enabled': True, 'manifest_path': invalid}}, tmp_path)
        launcher.apply_product_features({'insurance_review': {'enabled': True, 'manifest_path': str(manifest)}}, tmp_path)
        assert os.environ[key] == str(manifest)
        launcher.apply_product_features({'insurance_review': {'enabled': False}}, tmp_path)
        assert key not in os.environ


@pytest.mark.parametrize('options,expected', [
    (None, None),
    ({'enabled': True, 'reserve_trip_sync': False}, None),
    ({'enabled': False, 'reserve_trip_sync': True}, None),
    ({'enabled': True, 'reserve_trip_sync': True}, '1'),
])
def test_launcher_reserve_sync_requires_explicit_enabled_config(tmp_path, options, expected, capsys):
    data = tmp_path / 'data'
    if options is not None:
        options = dict(options, trip_authority_path=str(tmp_path / 'synthetic-authority.json'))
        config = tmp_path / 'config' / 'card-flow.json'
        config.parent.mkdir()
        config.write_text(json.dumps(options), encoding='utf-8')
    # Stop before credentials, operational SQLite or a server are opened.
    with patch.dict(os.environ, {'WEBLEDGER_RESERVE_TRIP_SYNC': '1'}), \
            patch.object(launcher, '_read_oauth_file', side_effect=launcher._Refused('OAUTH_FILE')):
        assert launcher.main(['--checkout', str(tmp_path), '--data-root', str(data),
                              '--oauth-file', str(tmp_path / 'synthetic-oauth.json'),
                              '--session-secret-file', str(tmp_path / 'synthetic-secret')]) == 2
        actual = os.environ.get('WEBLEDGER_RESERVE_TRIP_SYNC')
        assert actual == expected
    assert 'OAUTH_FILE' in capsys.readouterr().err


class ApplyOtaReviewTests(unittest.TestCase):

    def setUp(self):
        self.db = str(Path(tempfile.gettempdir()) / 'synthetic-review.sqlite')
        self.env = patch.dict(os.environ, {name: 'inherited' for name in VARS})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_absent_config_clears_inherited_variables(self):
        launcher.apply_ota_review({})
        self.assertFalse(any(name in os.environ for name in VARS))

    def test_isolated_sets_mode_and_absolute_db_without_authority(self):
        launcher.apply_ota_review({'ota_review': {'mode': 'isolated', 'review_db': self.db}})
        self.assertEqual(os.environ['WEBLEDGER_OTA_REVIEW_MODE'], 'isolated')
        self.assertEqual(os.environ['WEBLEDGER_OTA_REVIEW_DB'], self.db)
        self.assertNotIn('WEBLEDGER_OTA_AUTHORITY', os.environ)

    def test_authority_adds_the_guard(self):
        launcher.apply_ota_review({'ota_review': {'mode': 'authority', 'review_db': self.db}})
        self.assertEqual(os.environ['WEBLEDGER_OTA_AUTHORITY'], 'authority')

    def test_relative_db_path_is_refused(self):
        with self.assertRaises(launcher._Refused):
            launcher.apply_ota_review({'ota_review': {'mode': 'isolated', 'review_db': 'relative.sqlite'}})

    def test_missing_db_path_is_refused(self):
        with self.assertRaises(launcher._Refused):
            launcher.apply_ota_review({'ota_review': {'mode': 'isolated'}})

    def test_unrelated_settings_are_left_alone(self):
        with patch.dict(os.environ, {'WEBLEDGER_TRIP_AUTHORITY': 'trip.json', 'WEBLEDGER_REVIEW_FROM': '2026-04-01'}):
            launcher.apply_ota_review({'ota_review': {'mode': 'authority', 'review_db': self.db}})
            self.assertEqual(os.environ['WEBLEDGER_TRIP_AUTHORITY'], 'trip.json')
            self.assertEqual(os.environ['WEBLEDGER_REVIEW_FROM'], '2026-04-01')

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(launcher._Refused):
            launcher.apply_ota_review({'ota_review': {'mode': 'shadow', 'review_db': self.db}})
