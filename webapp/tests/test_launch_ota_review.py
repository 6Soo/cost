"""card-flow.json의 OTA 검토 설정만 환경 변수를 정한다. 설정이 없으면 legacy다."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('launch_web_ledger', ROOT / 'tools' / 'launch_web_ledger.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)

VARS = ('WEBLEDGER_OTA_REVIEW_MODE', 'WEBLEDGER_OTA_REVIEW_DB', 'WEBLEDGER_OTA_AUTHORITY')


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

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(launcher._Refused):
            launcher.apply_ota_review({'ota_review': {'mode': 'shadow', 'review_db': self.db}})
