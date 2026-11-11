"""Turn AI merchant-to-item proposals into a reusable, conflict-checked rule table.

Pure standard-library helpers. Nothing here reads or writes customer data; callers
pass in already-sourced proposals.
"""

import json

KEEP_ITEM = "기존 항목 유지"

COUNTRY_CODES = frozenset({
    "JP", "KR", "US", "TH", "VN", "TW", "HK", "SG", "FR", "IT", "AT", "DE", "ES", "GB",
})

REGION_NAMES = frozenset({
    "TOKYO", "OSAKA", "KYOTO", "HOKKAIDO", "SAITAMA", "YAMANASHI", "NAGANO",
    "AOMORI", "FUKUOKA", "OKINAWA", "SEOUL", "BUSAN", "JEJU",
})

REASON_KEEP = "keep"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_EMPTY_MERCHANT = "empty_merchant"
REASON_BELOW_MIN_ROWS = "below_min_rows"


def normalize_merchant(name: str) -> str:
    """Canonical merchant key: trimmed, whitespace-collapsed, upper-cased.

    A trailing country code and/or a trailing region name is stripped, but either
    is kept when it is the only remaining word.
    """
    if not isinstance(name, str):
        return ""
    tokens = " ".join(name.split()).upper().split()

    if len(tokens) >= 2 and tokens[-1] in COUNTRY_CODES:
        tokens = tokens[:-1]
    if len(tokens) >= 2 and tokens[-1] in REGION_NAMES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _row_count(proposal: dict) -> int:
    rows = proposal.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int):
        return 0
    return rows


def _make_rule(key: str, item: str, rows: int, variants: list, basis: str, run_ids: list) -> dict:
    return {
        "merchant_key": key,
        "item": item,
        "rows": rows,
        "variants": variants,
        "basis": basis,
        "run_ids": run_ids,
    }


def build_rule_table(proposals: list, min_rows: int = 1) -> dict:
    """Build rules from proposals, reporting conflicts and skipped entries."""
    skipped: list = []
    groups: dict = {}

    for proposal in proposals:
        merchant = proposal.get("merchant")
        item = proposal.get("item")
        confidence = proposal.get("confidence")
        if item == KEEP_ITEM or confidence != "높음":
            reason = REASON_KEEP if item == KEEP_ITEM else REASON_LOW_CONFIDENCE
            skipped.append({"merchant": merchant, "reason": reason})
            continue
        key = normalize_merchant(merchant)
        if key == "":
            skipped.append({"merchant": merchant, "reason": REASON_EMPTY_MERCHANT})
            continue
        groups.setdefault(key, []).append(proposal)

    rules: list = []
    conflicts: list = []

    for key in sorted(groups):
        group = groups[key]
        item_rows: dict = {}
        for proposal in group:
            item = proposal.get("item")
            item_rows[item] = item_rows.get(item, 0) + _row_count(proposal)
        total_rows = sum(item_rows.values())
        variants = sorted({p["merchant"] for p in group})
        run_ids = sorted({p["run_id"] for p in group if p.get("run_id")})

        best_basis = None
        best_rows = None
        for proposal in group:
            count = _row_count(proposal)
            if best_rows is None or count > best_rows:
                best_rows = count
                best_basis = proposal.get("basis")
        basis = best_basis if best_basis is not None else ""

        if len(item_rows) == 1:
            item = next(iter(item_rows))
            rules.append(_make_rule(key, item, total_rows, variants, basis, run_ids))
            continue

        ranked = sorted(item_rows.items(), key=lambda pair: (-pair[1], pair[0]))
        top_item, top_rows = ranked[0]
        resolved = top_item if top_rows * 3 >= total_rows * 2 else None
        conflicts.append({"merchant_key": key, "items": dict(item_rows), "resolved": resolved})
        if resolved is not None:
            rules.append(_make_rule(key, resolved, total_rows, variants, basis, run_ids))

    kept: list = []
    for rule in rules:
        if rule["rows"] < min_rows:
            skipped.append({"merchant": rule["merchant_key"], "reason": REASON_BELOW_MIN_ROWS})
        else:
            kept.append(rule)

    kept.sort(key=lambda rule: rule["merchant_key"])
    conflicts.sort(key=lambda entry: entry["merchant_key"])
    skipped.sort(key=lambda entry: entry["merchant"] if isinstance(entry.get("merchant"), str) else "")

    stats = {
        "proposals": len(proposals),
        "rules": len(kept),
        "rule_rows": sum(rule["rows"] for rule in kept),
        "conflicts": len(conflicts),
        "skipped": len(skipped),
    }
    return {"rules": kept, "conflicts": conflicts, "skipped": skipped, "stats": stats}


def to_jsonl(rules: list) -> str:
    """One compact, key-sorted JSON object per rule; trailing newline each."""
    return "".join(
        json.dumps(rule, ensure_ascii=False, sort_keys=True) + "\n" for rule in rules
    )
