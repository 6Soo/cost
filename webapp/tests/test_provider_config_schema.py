"""Pure unit tests and AST differential verification for provider_config_schema.

Verifies:
- Exact parameter signature and required positional argument contract
- AST differential identity against baseline 1122495
- Preservation of SecretStore and ProviderConfigService AST in provider_config.py
- Dynamic module-level dispatch / monkeypatch preservation
- ConfigError type identity and attributes
- Credential masking (redact) with synthetic tokens
- SHA256 non-reversible fingerprinting
- Model name regex and boundary validation
- Timeout range and numeric parsing
- Secret length, control character, and empty string handling
- Complete symbol identity between provider_config and provider_config_schema
"""

import ast
import hashlib
import inspect
from pathlib import Path
import subprocess
import unittest

from webapp import provider_config as pc
from webapp import provider_config_schema as pcs

SYN_KEY_SK = "sk-synthetictestkey00123"
SYN_KEY_AIZA = "AIzaSyntheticTestKey45678"
SYN_KEY_YA29 = "ya29.SyntheticToken98765"
SYN_NON_SECRET = "not-a-secret-plain-text"


class AstDifferentialTests(unittest.TestCase):
    """Verifies complete AST equivalence against baseline 1122495."""

    @classmethod
    def setUpClass(cls):
        proc = subprocess.run(
            ["git", "show", "1122495:webapp/provider_config.py"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        cls.baseline_tree = ast.parse(proc.stdout)
        cls.baseline_defs = {
            node.name: node
            for node in cls.baseline_tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }

        schema_src = Path("webapp/provider_config_schema.py").read_text(
            encoding="utf-8"
        )
        cls.schema_tree = ast.parse(schema_src)
        cls.schema_defs = {
            node.name: node
            for node in cls.schema_tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }

        pc_src = Path("webapp/provider_config.py").read_text(encoding="utf-8")
        cls.pc_tree = ast.parse(pc_src)
        cls.pc_defs = {
            node.name: node
            for node in cls.pc_tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }

    def test_schema_function_and_class_ast_identical(self):
        extracted_names = [
            "ConfigError",
            "_looks_secret",
            "redact",
            "fingerprint",
            "_validate_model",
            "_validate_timeout",
            "_validate_secret",
        ]
        for name in extracted_names:
            with self.subTest(definition=name):
                self.assertIn(name, self.baseline_defs)
                self.assertIn(name, self.schema_defs)
                baseline_ast = ast.dump(self.baseline_defs[name])
                schema_ast = ast.dump(self.schema_defs[name])
                self.assertEqual(
                    baseline_ast,
                    schema_ast,
                    f"AST divergence detected in extracted definition {name}",
                )

    def test_retained_classes_ast_identical(self):
        retained_names = [
            "SecretStore",
            "ProviderConfig",
            "ProviderConfigService",
        ]
        for name in retained_names:
            with self.subTest(cls=name):
                self.assertIn(name, self.baseline_defs)
                self.assertIn(name, self.pc_defs)
                baseline_ast = ast.dump(self.baseline_defs[name])
                pc_ast = ast.dump(self.pc_defs[name])
                self.assertEqual(
                    baseline_ast,
                    pc_ast,
                    f"AST divergence detected in retained class {name}",
                )


class SignatureContractTests(unittest.TestCase):
    def test_validate_model_signature_requires_field(self):
        sig = inspect.signature(pcs._validate_model)
        params = list(sig.parameters.values())
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0].name, "value")
        self.assertEqual(params[0].default, inspect.Parameter.empty)
        self.assertEqual(params[1].name, "field")
        self.assertEqual(params[1].default, inspect.Parameter.empty)

        with self.assertRaises(TypeError):
            pcs._validate_model("gemini-1.5-flash")  # missing field

    def test_validate_secret_signature_requires_field(self):
        sig = inspect.signature(pcs._validate_secret)
        params = list(sig.parameters.values())
        self.assertEqual(len(params), 2)
        self.assertEqual(params[0].name, "value")
        self.assertEqual(params[0].default, inspect.Parameter.empty)
        self.assertEqual(params[1].name, "field")
        self.assertEqual(params[1].default, inspect.Parameter.empty)

        with self.assertRaises(TypeError):
            pcs._validate_secret("sk-test12345678")  # missing field

    def test_validate_timeout_signature(self):
        sig = inspect.signature(pcs._validate_timeout)
        params = list(sig.parameters.values())
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].name, "value")
        self.assertEqual(params[0].default, inspect.Parameter.empty)


class DynamicDispatchMonkeypatchTests(unittest.TestCase):
    def test_dynamic_timeout_validator_patch(self):
        orig = pc._validate_timeout
        try:
            calls = []

            def custom_timeout(val):
                calls.append(val)
                return 42.0

            pc._validate_timeout = custom_timeout
            store = pc.SecretStore()
            store.set("test_provider", "timeout", 10.0)
            config = pc.ProviderConfig(store)
            res = config._timeout("test_provider")
            self.assertEqual(res, 42.0)
            self.assertEqual(calls, [10.0])
        finally:
            pc._validate_timeout = orig


class ConfigErrorIdentityTests(unittest.TestCase):
    def test_config_error_subclasses_value_error(self):
        self.assertTrue(issubclass(pcs.ConfigError, ValueError))

    def test_config_error_attributes_and_message(self):
        err = pcs.ConfigError("TEST_CODE", "테스트 오류 메시지")
        self.assertEqual(err.code, "TEST_CODE")
        self.assertEqual(str(err), "테스트 오류 메시지")
        self.assertIsInstance(err, ValueError)

    def test_reexport_identity(self):
        self.assertIs(pc.ConfigError, pcs.ConfigError)


class RedactMaskingTests(unittest.TestCase):
    def test_looks_secret_detection(self):
        self.assertTrue(pcs._looks_secret(SYN_KEY_SK))
        self.assertTrue(pcs._looks_secret(SYN_KEY_AIZA))
        self.assertTrue(pcs._looks_secret(SYN_KEY_YA29))
        self.assertFalse(pcs._looks_secret("sk-short"))  # len < 16
        self.assertFalse(pcs._looks_secret(SYN_NON_SECRET))
        self.assertFalse(pcs._looks_secret(12345))
        self.assertFalse(pcs._looks_secret(None))

    def test_redact_plain_strings(self):
        self.assertEqual(pcs.redact(SYN_KEY_SK), "[redacted]")
        self.assertEqual(pcs.redact(SYN_KEY_AIZA), "[redacted]")
        self.assertEqual(pcs.redact(SYN_NON_SECRET), SYN_NON_SECRET)

    def test_redact_in_sentences_and_quotes(self):
        text = f'Bearer "{SYN_KEY_SK}", client="test"'
        redacted = pcs.redact(text)
        self.assertNotIn(SYN_KEY_SK, redacted)
        self.assertIn("[redacted]", redacted)
        self.assertIn('client="test"', redacted)

    def test_redact_nested_structures(self):
        nested = {
            "auth": {
                "bearer": SYN_KEY_YA29,
                "prefix": "Bearer",
            },
            "keys": [SYN_KEY_SK, SYN_KEY_AIZA, "harmless"],
            "count": 3,
            "enabled": True,
            "extra": None,
        }
        res = pcs.redact(nested)
        self.assertEqual(res["auth"]["bearer"], "[redacted]")
        self.assertEqual(res["auth"]["prefix"], "Bearer")
        self.assertEqual(res["keys"], ["[redacted]", "[redacted]", "harmless"])
        self.assertEqual(res["count"], 3)
        self.assertEqual(res["enabled"], True)
        self.assertIsNone(res["extra"])

    def test_redact_preserves_non_string_types(self):
        self.assertEqual(pcs.redact(42), 42)
        self.assertEqual(pcs.redact(3.14), 3.14)
        self.assertEqual(pcs.redact(True), True)
        self.assertIsNone(pcs.redact(None))


class FingerprintTests(unittest.TestCase):
    def test_empty_or_none_returns_none(self):
        self.assertIsNone(pcs.fingerprint(None))
        self.assertIsNone(pcs.fingerprint(""))

    def test_fingerprint_format_and_determinism(self):
        fp1 = pcs.fingerprint(SYN_KEY_SK)
        fp2 = pcs.fingerprint(SYN_KEY_SK)
        self.assertEqual(fp1, fp2)
        self.assertTrue(fp1.startswith("sha256:"))
        expected = (
            "sha256:"
            + hashlib.sha256(SYN_KEY_SK.encode("utf-8")).hexdigest()[:12]
        )
        self.assertEqual(fp1, expected)
        self.assertEqual(len(fp1), 19)

    def test_fingerprint_is_non_reversible_and_discriminates(self):
        fp_sk = pcs.fingerprint(SYN_KEY_SK)
        fp_aiza = pcs.fingerprint(SYN_KEY_AIZA)
        self.assertNotEqual(fp_sk, fp_aiza)
        self.assertNotIn(SYN_KEY_SK, fp_sk)
        self.assertNotIn(SYN_KEY_AIZA, fp_aiza)


class ModelValidationTests(unittest.TestCase):
    def test_valid_model_names(self):
        valid_models = [
            "gemini-1.5-flash",
            "muse-local-v1",
            "gpt.4o_mini-2024",
            "model_123",
            "A",
            "a" * 64,
        ]
        for name in valid_models:
            with self.subTest(model=name):
                self.assertEqual(pcs._validate_model(name, "모델"), name)

    def test_model_whitespace_strip(self):
        self.assertEqual(
            pcs._validate_model("  gemini-pro  ", "모델"), "gemini-pro"
        )

    def test_empty_or_missing_model_raises_invalid_value(self):
        for bad in ["", "   ", None]:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_model(bad, "모델")
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("필요해요", str(caught.exception))

    def test_invalid_characters_or_length_raises_invalid_value(self):
        bad_models = [
            "model/with/slashes",
            "model with space",
            "model@domain",
            "model:tag",
            "a" * 65,
            "한글모델",
        ]
        for bad in bad_models:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_model(bad, "모델")
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("형식이 달라요", str(caught.exception))


class TimeoutValidationTests(unittest.TestCase):
    def test_valid_timeouts(self):
        cases = [
            (1.0, 1.0),
            (20, 20.0),
            (120.0, 120.0),
            ("15.5", 15.5),
            (pcs.DEFAULT_TIMEOUT, 20.0),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(pcs._validate_timeout(raw), expected)

    def test_out_of_range_timeouts(self):
        out_of_range = [0.99, 0.0, -1.0, 120.01, 300.0]
        for bad in out_of_range:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_timeout(bad)
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("허용 범위를 벗어났어요", str(caught.exception))

    def test_non_numeric_timeouts(self):
        non_numeric = ["fast", None, [], {}, ""]
        for bad in non_numeric:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_timeout(bad)
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("숫자가 아니에요", str(caught.exception))


class SecretValidationTests(unittest.TestCase):
    def test_empty_or_none_returns_empty_string(self):
        self.assertEqual(pcs._validate_secret(None, "키"), "")
        self.assertEqual(pcs._validate_secret("", "키"), "")
        self.assertEqual(pcs._validate_secret("   ", "키"), "")

    def test_valid_secret_length(self):
        key_8 = "12345678"
        key_512 = "k" * 512
        key_padded = "  " + key_8 + "  "
        self.assertEqual(pcs._validate_secret(key_8, "키"), key_8)
        self.assertEqual(pcs._validate_secret(key_512, "키"), key_512)
        self.assertEqual(pcs._validate_secret(key_padded, "키"), key_8)

    def test_non_string_secret_raises(self):
        for bad in [12345678, True, ["key"]]:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_secret(bad, "키")
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("형식이 달라요", str(caught.exception))

    def test_out_of_length_secret_raises(self):
        too_short = "1234567"  # 7 chars
        too_long = "k" * 513
        for bad in [too_short, too_long]:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_secret(bad, "키")
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("길이가 허용 범위를 벗어났어요", str(caught.exception))

    def test_forbidden_control_characters_raises(self):
        for bad in ["secret\nkey123", "secret\rkey123", "secret\tkey123"]:
            with self.subTest(bad=bad):
                with self.assertRaises(pcs.ConfigError) as caught:
                    pcs._validate_secret(bad, "키")
                self.assertEqual(caught.exception.code, "INVALID_VALUE")
                self.assertIn("허용되지 않은 문자", str(caught.exception))


class ProviderConfigReexportEquivalenceTests(unittest.TestCase):
    def test_symbols_are_identical_between_modules(self):
        self.assertIs(pc.ConfigError, pcs.ConfigError)
        self.assertIs(pc.redact, pcs.redact)
        self.assertIs(pc.fingerprint, pcs.fingerprint)
        self.assertIs(pc._looks_secret, pcs._looks_secret)
        self.assertIs(pc._validate_model, pcs._validate_model)
        self.assertIs(pc._validate_timeout, pcs._validate_timeout)
        self.assertIs(pc._validate_secret, pcs._validate_secret)

        self.assertEqual(pc.DEFAULT_TIMEOUT, pcs.DEFAULT_TIMEOUT)
        self.assertEqual(pc.MIN_SECRET_LENGTH, pcs.MIN_SECRET_LENGTH)
        self.assertEqual(pc.MAX_SECRET_LENGTH, pcs.MAX_SECRET_LENGTH)
        self.assertEqual(pc.SECRET_PREFIXES, pcs.SECRET_PREFIXES)
        self.assertEqual(pc.MODEL_RE.pattern, pcs.MODEL_RE.pattern)
        self.assertEqual(pc.TIMEOUT_MIN, pcs.TIMEOUT_MIN)
        self.assertEqual(pc.TIMEOUT_MAX, pcs.TIMEOUT_MAX)


if __name__ == "__main__":
    unittest.main()
