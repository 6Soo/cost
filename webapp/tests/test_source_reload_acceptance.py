"""Independent acceptance checks for disk-config refresh, synthetic inputs only."""
import json
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webapp import real_review
from webapp.tests import review_fixtures as fx


class ConfigRefreshAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup_temp)
        self.root = Path(self.temp.name)
        self.config = self.root / "active.json"
        first = self.root / "first"
        first.mkdir()
        self.original = fx.write_case(first, rows=3)
        self.write_config(self.original)
        env = patch.dict(os.environ, {
            real_review.CONFIG_ENV: str(self.config),
            real_review.REFRESH_STATUS_ENV: "",
        })
        env.start()
        self.addCleanup(env.stop)
        self.clock = patch("webapp.real_review.time.monotonic", return_value=100.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        real_review.clear_real_review()
        self.addCleanup(real_review.clear_real_review)

    def cleanup_temp(self):
        assert self.root.parent.resolve() == Path(tempfile.gettempdir()).resolve()
        gc.collect()
        self.temp.cleanup()

    def write_config(self, manifest):
        self.config.write_text(json.dumps(manifest), encoding="utf-8")

    def advance(self):
        self.now.return_value += real_review.RECHECK_SECONDS + 1

    def newer(self):
        folder = self.root / "newer"
        folder.mkdir()
        manifest = fx.write_case(folder, rows=4)
        manifest["decisions_db_path"] = self.original["decisions_db_path"]
        return manifest

    def test_disk_config_change_loads_new_model_without_restart(self):
        old = real_review.active_service()
        self.assertEqual(len(old.model()["rows"]), 3)
        stamp = self.config.stat().st_mtime_ns
        self.write_config(self.newer())
        os.utime(self.config, ns=(stamp, stamp))
        self.advance()
        new = real_review.active_service()
        self.assertIsNot(new, old)
        self.assertEqual(len(new.model()["rows"]), 4)
        self.assertEqual(new.store.path, old.store.path)
        self.assertEqual(new.state()["counts"]["selected"], 0)

    def test_invalid_refresh_retains_last_good_and_reports_failure(self):
        old = real_review.active_service()
        old.model()
        Path(real_review.refresh_status_path()).write_text(
            json.dumps({"code": "REFRESH_NO_CHANGE"}), encoding="utf-8")
        self.config.write_text("{}", encoding="utf-8")
        self.advance()
        self.assertIs(real_review.active_service(), old)
        self.assertEqual(len(old.model()["rows"]), 3)
        self.assertEqual(old.state_only_payload()["refresh"]["code"],
                         real_review.CODE_CONFIG_INVALID)

    def test_restoring_the_last_good_config_clears_refresh_failure(self):
        old = real_review.active_service()
        old.model()
        self.config.write_text("{}", encoding="utf-8")
        self.advance()
        self.assertIs(real_review.active_service(), old)
        self.assertTrue(real_review.config_error())
        self.write_config(self.original)
        self.advance()
        self.assertIs(real_review.active_service(), old)
        self.assertEqual(real_review.config_error(), "")

    def test_initial_invalid_config_recovers_without_restart(self):
        self.config.write_text("{}", encoding="utf-8")
        self.assertIsNone(real_review.active_service())
        self.write_config(self.original)
        self.advance()
        service = real_review.active_service()
        self.assertIsNotNone(service)
        self.assertEqual(len(service.model()["rows"]), 3)
        self.assertEqual(real_review.config_error(), "")

    def test_old_service_cannot_save_after_valid_config_replacement(self):
        old = real_review.active_service()
        binding = old.model_binding()
        self.write_config(self.newer())
        with self.assertRaises(real_review.RealReviewError) as caught:
            old.save_decisions([
                {"ref": fx.source_ref(fx.FIRST_ROW), "value": "REJECT"},
            ], 0, binding)
        self.assertEqual(caught.exception.code, real_review.CODE_BINDING_CONFLICT)
        self.assertEqual(old.store.load(binding)["revision"], 0)

    def test_refresh_cannot_replace_the_decision_history_database(self):
        old = real_review.active_service()
        old.model()
        manifest = self.newer()
        manifest["decisions_db_path"] = str(self.root / "different.sqlite")
        self.write_config(manifest)
        self.advance()
        self.assertIs(real_review.active_service(), old)
        self.assertTrue(real_review.config_error())
