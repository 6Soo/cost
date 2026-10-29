# -*- coding: utf-8 -*-
"""Deterministic existing/new/ambiguous/file-duplicate matching (CUV-01/02, PR #349).

Uses normalized keys derived from preserved fields (date, amount, merchant,
approval, card, cancel) so results are reproducible across runs.
No production DB access; synthetic fixtures only.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib

try:
    from app.normalize import to_date, normalize_merchant, to_amount_krw
except Exception:
    # Fallback for isolated synthetic runs
    to_date = lambda s: str(s)[:10] if s else ""
    normalize_merchant = lambda s: str(s).strip().lower() if s else ""
    to_amount_krw = lambda s: Decimal(str(s).replace(",", "").replace("원", "").strip() or 0)


class MatchResult:
    EXISTING = "existing"
    NEW = "new"
    AMBIGUOUS = "ambiguous"
    FILE_DUPLICATE = "file_duplicate"


def _normalize_key(row_dict: dict) -> str:
    """Deterministic key from preserved fields."""
    dt = to_date(row_dict.get("approval_date") or row_dict.get("date") or "")
    amt = to_amount_krw(row_dict.get("amount_krw") or row_dict.get("amount") or "")
    merch = normalize_merchant(row_dict.get("merchant") or row_dict.get("merchant_name") or "")
    appr = str(row_dict.get("approval_number") or row_dict.get("approval_no") or "").strip()
    card = str(row_dict.get("card_mask") or row_dict.get("card") or row_dict.get("card_no") or "").strip()
    cancel = "1" if (str(row_dict.get("cancel_flag") or "").lower() in ("true", "1", "yes", "취소")) else "0"
    key_text = f"{dt}|{amt}|{merch}|{appr}|{card}|{cancel}"
    # Deterministic hash so comparison is order-independent and fast
    return hashlib.sha256(key_text.encode("utf-8")).hexdigest()[:32]


def match_row(row_dict: dict, existing_keys: set[str],
              file_digest_set: set[str] | None = None,
              file_digest: str | None = None) -> str:
    """Return one of EXISTING / NEW / AMBIGUOUS / FILE_DUPLICATE."""
    key = _normalize_key(row_dict)
    if file_digest and file_digest_set and file_digest in file_digest_set:
        return MatchResult.FILE_DUPLICATE
    if key in existing_keys:
        # Ambiguous only when key collides with more than one distinct source
        # (synthetic rule: single source = existing; multi-source = ambiguous)
        return MatchResult.EXISTING
    return MatchResult.NEW


def batch_match(rows: list[dict], existing_keys: set[str],
                file_digest_set: set[str] | None = None,
                file_digest: str | None = None) -> list[dict]:
    results = []
    for r in rows:
        outcome = match_row(r, existing_keys, file_digest_set, file_digest)
        r2 = dict(r)
        r2["match_outcome"] = outcome
        r2["match_key"] = _normalize_key(r)
        results.append(r2)
    # Ambiguous: when same key appears from different file digests
    key_counts = {}
    for r in results:
        k = r["match_key"]
        key_counts.setdefault(k, set()).add(r.get("_digest") or r.get("source_file") or "")
    for r in results:
        if len(key_counts.get(r["match_key"], set())) > 1 and r["match_outcome"] == MatchResult.EXISTING:
            r["match_outcome"] = MatchResult.AMBIGUOUS
    return results
