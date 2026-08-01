import hashlib
import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from ledger.domain import direct_receipt_airfare_provenance as auth


class AuthenticatedProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.pdf = b"%PDF-1.4\nsynthetic\n%%EOF\n"
        self.text = b"deterministic text"
        for name, value in (("only.pdf", self.pdf), ("only.txt", self.text),
                            ("key", b"k" * 32)):
            (self.root / name).write_bytes(value)
            os.chmod(self.root / name, 0o600)
        message = EmailMessage()
        message["Message-ID"] = "<immutable@example.invalid>"
        message["Delivered-To"] = "owner@example.invalid"
        message["From"] = "provider@trip.com"
        message["Authentication-Results"] = "mx.example; dkim=pass header.d=trip.com"
        message["DKIM-Signature"] = "v=1; a=rsa-sha256; d=trip.com; s=test; b=opaque"
        message.set_content("receipt")
        message.add_attachment(self.pdf, maintype="application", subtype="pdf",
                               filename="receipt.pdf")
        (self.root / "raw_0.eml").write_bytes(message.as_bytes())
        os.chmod(self.root / "raw_0.eml", 0o600)
        self.docs = {"only": (hashlib.sha256(self.pdf).hexdigest(),
                              hashlib.sha256(self.text).hexdigest(), 1)}
        self.extract = patch.object(auth, "_run_extractor",
                                    return_value={"only": (self.text, 1)})

    def tearDown(self):
        self.tmp.cleanup()

    def _sidecar(self):
        with self.extract:
            raw = auth.build_authenticated_sidecar(
                self.root, self.root / "key", self.docs, Path("/unused/python"))
        path = self.root / "provenance.json"
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        return path

    def test_signed_mime_attachment_and_fresh_text_pass(self):
        path = self._sidecar()
        with patch.object(auth, "_run_extractor",
                          return_value={"only": (self.text, 1)}):
            result = auth.verify_authenticated_inputs(
                self.root, path, self.root / "key", self.docs, Path("/unused/python"))
        self.assertEqual((result["status"], result["documents"]), ("valid", 1))

    def test_hmac_tamper_fails_closed(self):
        path = self._sidecar()
        data = path.read_bytes().replace(b'"raw_mime_size":', b'"raw_mime_size":9')
        path.write_bytes(data)
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ValueError, "provenance_hmac_invalid"):
            auth.verify_authenticated_inputs(
                self.root, path, self.root / "key", self.docs, Path("/unused/python"))

    def test_duplicate_json_key_fails_closed(self):
        path = self.root / "provenance.json"
        path.write_bytes(b'{"schema_version":2,"schema_version":2}\n')
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            auth.verify_authenticated_inputs(
                self.root, path, self.root / "key", self.docs, Path("/unused/python"))

    def test_wrong_extracted_bytes_rejected(self):
        with patch.object(auth, "_run_extractor",
                          return_value={"only": (b"wrong", 1)}):
            with self.assertRaisesRegex(ValueError, "fresh_extraction_mismatch"):
                auth.build_authenticated_sidecar(
                    self.root, self.root / "key", self.docs, Path("/unused/python"))

    def test_misaligned_attacker_dkim_is_rejected(self):
        raw=(self.root/"raw_0.eml").read_bytes().replace(b"header.d=trip.com",b"header.d=evil.example").replace(b"d=trip.com",b"d=evil.example")
        with self.assertRaisesRegex(ValueError,"outer_auth_invalid"):auth._mime_facts(raw)

    def test_non_regular_private_input_is_rejected(self):
        fake=type("S",(),{"st_mode":0o010600,"st_uid":os.getuid(),"st_nlink":1,"st_dev":1,"st_ino":1,"st_size":0,"st_mtime_ns":1})()
        real=auth.os.fstat
        calls=iter([real(os.open(self.root,os.O_RDONLY)),fake])
        with patch.object(auth.os,"fstat",side_effect=lambda fd:next(calls)):
            with self.assertRaisesRegex(ValueError,"authenticated_file_invalid"):auth._private_bytes(self.root/"key")


if __name__ == "__main__":
    unittest.main()
