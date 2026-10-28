"""Pure schema, credential masking, fingerprinting, and validation for provider configuration.

Enforces pure schema rules without IO, file system, or network dependencies:
- Model name regex and required checks
- Timeout float parsing and range checks [1.0, 120.0]
- Secret length [8, 512], whitespace/control character checks
- Credential masking (redact) across arbitrary structures
- Non-reversible SHA256 fingerprinting
- ConfigError definition
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

DEFAULT_TIMEOUT = 20.0
# A key we would accept from the owner. Long enough to be a real key, short
# enough that a test key is obvious in review.
MIN_SECRET_LENGTH = 8
MAX_SECRET_LENGTH = 512
# Known prefixes. Used for redaction, never for validation: a real key can have
# any shape, so a shape check must not become a way to reject a valid key.
SECRET_PREFIXES = ("sk-", "AIza", "ya29.", "gsk_", "xai-", "api-", "key-")
MODEL_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
TIMEOUT_MIN = 1.0
TIMEOUT_MAX = 120.0


class ConfigError(ValueError):
    """A configuration request was refused. The message is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _looks_secret(text: Any) -> bool:
    return (isinstance(text, str) and len(text) >= 16
            and text.startswith(SECRET_PREFIXES))


def redact(value: Any) -> Any:
    """Replace anything that looks like a credential, anywhere in a structure.

    Used on anything that is about to be logged or returned, so a secret cannot
    reach a response by being nested inside an unexpected field.
    """
    if isinstance(value, dict):
        return {key: ("[redacted]" if _looks_secret(value[key])
                      else redact(value[key]))
                for key in value}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if _looks_secret(value):
            return "[redacted]"
        # Also catch a key glued to other text, such as a full request line.
        out = []
        for token in value.replace("\n", " ").split(" "):
            out.append("[redacted]" if _looks_secret(token.strip('",'))
                       else token)
        return " ".join(out)
    return value


def fingerprint(secret: str | None) -> str | None:
    """A non-reversible marker. Not a key, and not usable as one."""
    if not secret:
        return None
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def validate_model(value: Any, field: str = "모델 이름") -> str:
    text = str(value or "").strip()
    if not text:
        raise ConfigError("INVALID_VALUE", f"{field}이 필요해요")
    if not MODEL_RE.match(text):
        # A model id goes into a URL path, so anything else is refused rather
        # than escaped.
        raise ConfigError("INVALID_VALUE", f"{field} 형식이 달라요")
    return text


_validate_model = validate_model


def validate_timeout(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError("INVALID_VALUE", "제한 시간이 숫자가 아니에요")
    if not TIMEOUT_MIN <= number <= TIMEOUT_MAX:
        raise ConfigError("INVALID_VALUE", "제한 시간이 허용 범위를 벗어났어요")
    return number


_validate_timeout = validate_timeout


def validate_secret(value: Any, field: str = "키") -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError("INVALID_VALUE", f"{field} 형식이 달라요")
    text = value.strip()
    if not text:
        return ""
    if not MIN_SECRET_LENGTH <= len(text) <= MAX_SECRET_LENGTH:
        raise ConfigError("INVALID_VALUE", f"{field} 길이가 허용 범위를 벗어났어요")
    if any(ch in text for ch in "\r\n\t"):
        raise ConfigError("INVALID_VALUE", f"{field}에 허용되지 않은 문자가 있어요")
    return text


_validate_secret = validate_secret


__all__ = [
    "DEFAULT_TIMEOUT",
    "MIN_SECRET_LENGTH",
    "MAX_SECRET_LENGTH",
    "SECRET_PREFIXES",
    "MODEL_RE",
    "TIMEOUT_MIN",
    "TIMEOUT_MAX",
    "ConfigError",
    "_looks_secret",
    "redact",
    "fingerprint",
    "validate_model",
    "_validate_model",
    "validate_timeout",
    "_validate_timeout",
    "validate_secret",
    "_validate_secret",
]
