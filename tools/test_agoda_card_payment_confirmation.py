import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import prepare_review_template as publication




class AgodaCardPaymentConfirmationTests(unittest.TestCase):
    def test_noreplace_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            final.write_bytes(b"old")
            # Keep the no-overwrite contract against a current repository CLI,
            # rather than restoring the removed private candidate builder.
            with self.assertRaises(publication._CliError) as caught:
                publication._publish(str(final), stage.read_bytes(), [])
            self.assertEqual(caught.exception.code, publication.CODE_OUTPUT_EXISTS)
            self.assertEqual(final.read_bytes(), b"old")
            self.assertEqual(stage.read_bytes(), b"new")

    def test_noreplace_cleans_only_its_own_link_after_failure(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            failure = publication._CliError(publication.CODE_INPUT_CHANGED_DURING_READ)
            # The input changes after the hard link was published. Only that
            # link may be removed during rollback.
            with mock.patch.object(publication, "_reverify", side_effect=[None, failure]):
                with self.assertRaises(publication._CliError) as caught:
                    publication._publish(str(final), stage.read_bytes(), [object()])
            self.assertEqual(caught.exception.code, failure.code)
            self.assertFalse(final.exists())
            self.assertEqual(list(root.iterdir()), [stage])

    def test_noreplace_does_not_delete_replaced_inode(self):
        with tempfile.TemporaryDirectory(prefix="agoda-confirmation-test-") as tmp:
            root = Path(tmp)
            stage = root / "stage"
            final = root / "final"
            stage.write_bytes(b"new")
            checks = 0

            def reverify_with_competitor(_input):
                nonlocal checks
                checks += 1
                if checks == 2:
                    final.unlink()
                    final.write_bytes(b"other process")
                    raise publication._CliError(publication.CODE_INPUT_CHANGED_DURING_READ)

            with mock.patch.object(publication, "_reverify", side_effect=reverify_with_competitor):
                with self.assertRaises(publication._CliError) as caught:
                    publication._publish(str(final), stage.read_bytes(), [object()])
            self.assertEqual(caught.exception.code, publication.CODE_INPUT_CHANGED_DURING_READ)
            self.assertEqual(final.read_bytes(), b"other process")
            self.assertEqual(stage.read_bytes(), b"new")
            self.assertEqual(set(root.iterdir()), {stage, final})


if __name__ == "__main__":
    unittest.main()
