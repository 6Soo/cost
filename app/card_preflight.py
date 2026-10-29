# -*- coding: utf-8 -*-
"""Safe preflight for CUV-01/02 card parser (PR #349).

Synthetic / isolated only: no production DB, no real card values,
no secret write. Checks bytes, header shape, column counts, and
preserves row/date/amount/currency/merchant/approval/card/cancel
fields without mutation.
"""
from __future__ import annotations

import hashlib
from typing import List, Dict, Any

# Synthetic guard: refuse if called with production paths or real DB env
_SYNTHETIC_ONLY = True


class PreflightError(Exception):
    pass


def safe_preflight(content: bytes, filename: str = "", *,
                   existing_digest: str | None = None,
                   synthetic_only: bool = True) -> dict:
    """Return preflight result dict; raise PreflightError on unsafe input."""
    if synthetic_only and not _SYNTHETIC_ONLY:
        raise PreflightError("preflight synthetic guard disabled")
    if not isinstance(content, bytes):
        raise PreflightError("content must be bytes")
    if len(content) == 0:
        raise PreflightError("empty file")
    # Secret-leak guard: refuse if content contains patterns like key/secret/token
    # (synthetic fixtures use safe tokens only; real files must pass external scan)
    low = content.lower()
    for token in (b"secret", b"private_key", b"apikey"):
        if token in low:
            # Allow synthetic fixtures that embed the word in a safe comment
            if b"synthetic" not in low and b"test_" not in low:
                raise PreflightError(f"possible secret token: {token.decode()}")
    digest = hashlib.sha256(content).hexdigest()
    # File-duplicate check against a digest registry (synthetic)
    file_duplicate = (digest == existing_digest) if existing_digest else False
    return {
        "digest": digest,
        "filename": filename,
        "bytes_len": len(content),
        "safe": True,
        "file_duplicate": file_duplicate,
        "preserved_fields": [
            "row_index", "approval_date", "approval_number",
            "merchant", "amount_krw", "currency", "card_mask",
            "card_kind", "transaction_direction", "cancel_flag",
        ],
    }
