"""Natural language to a structured rule candidate.

A provider answers in prose. This module turns that prose into a *candidate*
draft and nothing more. The chain is deliberately narrow:

    provider text
      -> extract a bounded, quoted span          (parse_provider_text)
      -> map it onto allowlisted fields only     (rule_candidate)
      -> hand it to classification_rules.normalize_draft for validation
      -> preview, then the owner confirms

Three properties matter and each is enforced here rather than by convention:

* **Provider text is never applied.** `rule_candidate` returns a candidate with
  `applied: False` and no rule id the store would accept on its own. A caller
  that wants an applied rule has to go through the existing preview and confirm
  path, which re-reads the rule hash and the row revisions.
* **A model cannot widen its own scope.** The parser only recognises the
  allowlisted condition and effect fields, the four applicability values, and
  the effect set in `classification_rules`. Anything else is reported as an
  unrecognised token rather than guessed at, and an unrecognised span produces
  no candidate.
* **Impact is never taken from the model.** A candidate carries no count and no
  total. The caller shows the preview API's numbers or nothing.

The parser is a local, deterministic contract. It is not a second opinion on
the provider, and it does not call anything.
"""

from __future__ import annotations

import re

from .classification_rules import (
    ALLOWED_CONDITIONS,
    ALLOWED_EFFECTS,
    APPLICABILITY_VALUES,
    DIRECTION_VALUES,
    RuleError,
    normalize_draft,
)

# The maximum prose we will look at. A long answer is truncated rather than
# mined, so a provider cannot push extra instructions past a length check.
MAX_TEXT_CHARS = 2000
# One candidate per answer. A provider that offers three different rules gets
# the first one parsed and the rest reported, not a merged guess.
MAX_CANDIDATES = 1

APPLICABILITY_LABELS = {
    "existing": "확인한 기존 행만",
    "future": "새 사건에만",
    "existing_and_future": "기존 행과 새 사건 모두",
}
APPLICABILITY_HINTS = (
    ("existing_and_future", ("기존", "과거", "이후", "앞으로", "미래", "모두", "전부")),
    ("future", ("새로 들어", "새 사건", "앞으로 들어", "향후", "이후 새로")),
    ("existing", ("기존 행만", "확인한 행만", "지금 있는 것만", "현재 행만")),
)
DIRECTION_LABELS = {
    "purchase": ("매입", "구매", "결제"),
    "refund": ("환불", "반환", "취소 후 환불"),
    "cancellation": ("취소", "해제", "무효"),
}
# Effect phrases the operator actually uses, mapped to the allowlisted field.
EFFECT_HINTS = {
    "display_tab_id": ("여행", "여행으로", "배정", "归属", "_tab"),
    "item": ("항목", "분류"),
    "description_template": ("설명", "용도 문구", "템플릿"),
}
CONDITION_HINTS = {
    "merchant_normalized": ("가맹점", "가맹점명", "商户"),
    "card_kind": ("카드", "카드 종류"),
    "transaction_direction": ("거래 방향", "방향", "환불 여부"),
}
# A trip id inside prose. There is a leading word boundary but deliberately no
# trailing one: Korean text follows a latin id directly ("trip-demo-b로 옮기면"),
# and `\b` would not match between "b" and "로" because both are word
# characters. The id charset itself is the boundary.
TRIP_RE = re.compile(r"\b(trip-[A-Za-z0-9_\-]+)")
# A JSON block is the only machine-readable shape we accept from prose, and
# even then it is a candidate, not a rule.
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
BARE_JSON_RE = re.compile(r"(\{[^{}]*\})")

# Fields a provider must never be able to set by itself.
FORBIDDEN_PROVIDER_FIELDS = (
    "rule_id", "version", "base_rule_version", "learning_case_id",
    "evidence_case_ids", "scope", "note", "exceptions", "row_id", "revision",
    "applied", "preview_id", "client_request_id",
)
# Values the server supplies, so a model never invents a trip, a year, or the
# text of an effect. The owner or the authoritative schedule is the only source.
OPERATOR_FIELDS = ("trip_id", "event_year", "item", "description_template")


class TextRuleError(ValueError):
    """The provider text could not become a candidate. Never applied."""

    def __init__(self, code, message, unrecognised=None):
        super().__init__(message)
        self.code = code
        self.unrecognised = list(unrecognised or ())


def extract_json_block(text):
    """Return a parsed JSON object from prose, or None.

    A provider that volunteers structured output is convenient, not trusted:
    the result still goes through `normalize_draft` and the confirm path.
    """
    if not isinstance(text, str):
        return None
    body = text[:MAX_TEXT_CHARS]
    for pattern in (JSON_BLOCK_RE, BARE_JSON_RE):
        match = pattern.search(body)
        if not match:
            continue
        try:
            import json

            parsed = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_provider_text(text):
    """Split provider prose into the pieces a candidate may be built from.

    Returns a dict with `trip_hint`, `applicability_hint`, `condition_hints`,
    `effect_hints`, and `unrecognised`. It performs no validation and produces
    no rule, so it is safe to call on anything a provider returns.
    """
    body = "" if text is None else str(text)[:MAX_TEXT_CHARS]
    result = {
        "trip_hint": None,
        "applicability_hint": None,
        "condition_hints": [],
        "effect_hints": [],
        "unrecognised": [],
        "truncated": len(str(text or "")) > MAX_TEXT_CHARS,
    }
    trip = TRIP_RE.search(body)
    if trip:
        result["trip_hint"] = trip.group(1)
    lowered = body.casefold()
    for value, needles in APPLICABILITY_HINTS:
        if any(needle.casefold() in lowered for needle in needles):
            result["applicability_hint"] = value
            break
    for field, needles in CONDITION_HINTS.items():
        if any(needle.casefold() in lowered for needle in needles):
            result["condition_hints"].append(field)
    for field, needles in EFFECT_HINTS.items():
        if any(needle.casefold() in lowered for needle in needles):
            result["effect_hints"].append(field)
    # Tokens that look like an instruction to change something we do not allow.
    for match in re.finditer(
            r"(?i)\b(amount_krw|occurred_on|reservation_no|customer_name|"
            r"nickname|release_eligible|rule_hash)\b", body):
        token = match.group(1)
        if token not in result["unrecognised"]:
            result["unrecognised"].append(token)
    return result


def _conditions_from(parsed, row):
    """Conditions the row itself already evidences.

    A condition is only carried when the row proves it, so the candidate cannot
    assert a merchant or a card type that the stored row does not have. This is
    the difference between a candidate and a guess.
    """
    conditions = {}
    merchant = row.get("source_merchant")
    if merchant and "merchant_normalized" in parsed["condition_hints"]:
        conditions["merchant_normalized"] = {"op": "eq", "value": merchant}
    card_kind = row.get("card_kind")
    if card_kind and "card_kind" in parsed["condition_hints"]:
        conditions["card_kind"] = {"op": "eq", "value": card_kind}
    direction = row.get("event_kind")
    if direction and direction in DIRECTION_VALUES \
            and "transaction_direction" in parsed["condition_hints"]:
        conditions["transaction_direction"] = {"op": "eq", "value": direction}
    if not conditions:
        # No hint, but the row still has a merchant. The operator is most often
        # fixing a trip placement on one merchant, so the merchant is the
        # evidence and the candidate says so.
        if merchant:
            conditions["merchant_normalized"] = {"op": "eq", "value": merchant}
    return conditions


def rule_candidate(*, text=None, payload=None, row=None, learning_case_id="",
                    rule_id="", version=1, base_rule_version=0,
                    operator=None):
    """Build a validated, non-applied rule candidate from a provider answer.

    `payload` is optional structured output the provider volunteered. `text` is
    prose. At least one is required.

    `operator` carries the values the *server* already knows and the provider
    must never supply: the trip the row is being placed into, the event year,
    and any effect text the owner typed. Keys are `trip_id`, `event_year`,
    `item`, `description_template`. Anything the provider says about these is
    ignored; the whole point is that a trip placement comes from the
    authoritative schedule and a template comes from the operator, not from a
    model. This is also why a prose-only answer can still become a candidate:
    the missing pieces are filled from the server, not invented.

    On success the return value carries `rule` (already through
    `normalize_draft`), `rule_hash`, `applied: False`, and the reason it is not
    applied. On failure a `TextRuleError` is raised with a code, and no partial
    rule is returned.

    `rule_id` is supplied by the caller, not by the provider, so a model cannot
    name or overwrite an existing rule.
    """
    row = row or {}
    supplied = {key: value for key, value in (operator or {}).items()
                if key in OPERATOR_FIELDS and value not in (None, "")}
    parsed = parse_provider_text(text if text is not None else "")
    structured = payload if isinstance(payload, dict) else extract_json_block(text)
    if structured is not None:
        candidate = _from_structured(structured, row, parsed, supplied)
    else:
        candidate = _from_prose(parsed, row, supplied)
    if not candidate:
        raise TextRuleError(
            "RULE_TEXT_UNRECOGNISED",
            "제공자 답변에서 규칙 초안을 읽지 못했어요",
            unrecognised=parsed["unrecognised"])
    candidate["learning_case_id"] = str(learning_case_id or "")
    candidate["version"] = int(version)
    candidate["base_rule_version"] = int(base_rule_version)
    # Validation is the gate. A candidate that does not pass is not a rule.
    rule = normalize_draft(
        candidate, learning_case_id=learning_case_id, rule_id=rule_id,
        version=version, base_rule_version=base_rule_version)
    from .classification_rules import rule_hash

    return {
        "rule": rule,
        "rule_hash": rule_hash(rule),
        # Never applied here. The preview and the owner confirm are separate
        # steps, and this value is the proof that they were not skipped.
        "applied": False,
        "requires_owner_confirm": True,
        "source": "provider_text" if structured is None else "provider_json",
        "unrecognised": parsed["unrecognised"],
        "truncated": parsed["truncated"],
        # Impact deliberately absent: the model does not get to state a count or
        # a total. The preview API is the only source for those.
    }


def _from_prose(parsed, row, supplied):
    """A candidate from prose, completed only from server-supplied values.

    Prose can name *which* field to change, but it cannot supply a condition
    value, a template, a trip, or a year. So each missing piece is either taken
    from `supplied` (which the owner or the schedule provided) or the whole
    candidate is refused. Nothing is invented and nothing is guessed.
    """
    if not parsed["effect_hints"]:
        return None
    effects = {}
    for field in parsed["effect_hints"]:
        if field not in ALLOWED_EFFECTS:
            continue
        if field == "display_tab_id":
            # A prose trip name is a destination, not a tab id, so it is only
            # used when it is already a tab id. Otherwise the server must have
            # supplied the trip.
            value = parsed["trip_hint"] or supplied.get("trip_id") or ""
            if not str(value).startswith("trip-"):
                value = supplied.get("trip_id") or ""
            if not str(value).startswith("trip-"):
                return None
            effects["display_tab_id"] = str(value)
        else:
            value = supplied.get(field)
            if not value:
                # The provider named the field but the owner did not supply the
                # text, so there is no effect to validate.
                return None
            effects[field] = value
    if not effects:
        return None
    candidate = {"conditions": _conditions_from(parsed, row), "effects": effects}
    scope = _scope_from(supplied, parsed)
    if scope:
        candidate["scope"] = scope
    return candidate


def _from_structured(structured, row, parsed, supplied):
    """A candidate from volunteered JSON, re-checked field by field.

    Every key is filtered against the allowlists, so a provider cannot smuggle
    a scope, a rule id, a version, or an amount in through a JSON block. Trip
    and year come from `supplied` only.
    """
    conditions_in = structured.get("conditions") or {}
    if not isinstance(conditions_in, dict):
        raise TextRuleError("RULE_TEXT_UNRECOGNISED", "조건 형식이 달라요")
    conditions = {}
    for field, raw in conditions_in.items():
        if field not in ALLOWED_CONDITIONS:
            continue
        conditions[field] = raw
    optional_in = structured.get("optional_conditions") or {}
    optional = {}
    if isinstance(optional_in, dict):
        for field in ("amount_range", "date_or_service_period"):
            if field in optional_in:
                optional[field] = optional_in[field]
    effects_in = structured.get("effects") or {}
    if not isinstance(effects_in, dict):
        raise TextRuleError("RULE_TEXT_UNRECOGNISED", "효과 형식이 달라요")
    effects = {}
    for field, raw in effects_in.items():
        if field not in ALLOWED_EFFECTS:
            # A provider asking to change an amount or a date is dropped, not
            # reported back as a candidate.
            continue
        effects[field] = raw
    if not effects or not conditions:
        return None
    if "display_tab_id" in effects:
        # The trip is the server's value. A tab id in the payload is only
        # accepted when the server supplied the same one, which is the normal
        # path, and refused when they disagree.
        server_trip = supplied.get("trip_id")
        claimed = str(effects["display_tab_id"] or "").strip()
        if not claimed.startswith("trip-"):
            claimed = parsed["trip_hint"] or ""
        if not server_trip:
            if not claimed.startswith("trip-"):
                return None
        elif claimed and claimed != str(server_trip):
            # A model proposing a different trip than the one the operator has
            # selected is refused rather than silently replaced.
            raise TextRuleError(
                "RULE_TEXT_TRIP_MISMATCH",
                "제공자가 고른 여행이 지금 선택한 여행과 달라요")
        effects["display_tab_id"] = str(server_trip)
    for field in ("item", "description_template"):
        if field in effects and not str(effects[field] or "").strip():
            effects.pop(field)
        elif field in effects and field in supplied \
                and str(supplied[field]).strip() and \
                str(effects[field]).strip() != str(supplied[field]).strip():
            raise TextRuleError(
                "RULE_TEXT_EFFECT_MISMATCH",
                f"운영자가 입력한 {field}과 제공자 답변이 달라요")
    if not effects:
        return None
    candidate = {
        "conditions": conditions,
        "optional_conditions": optional,
        "effects": effects,
    }
    scope = _scope_from(supplied, parsed)
    if scope:
        candidate["scope"] = scope
    return candidate


def _scope_from(supplied, parsed):
    """Build a scope from server-supplied trip and year.

    A travel placement rule is invalid without a trip, a year, and an
    applicability. The trip and the year are the server's. The applicability may
    be hinted by the prose, but it is clamped to the four contract values and the
    owner still chooses per preview, so a hint can never widen the scope on its
    own.
    """
    trip = supplied.get("trip_id")
    year = supplied.get("event_year")
    if not trip or year in (None, ""):
        # Without all three there is no valid scope; the caller decides whether
        # that is acceptable for a non-travel effect.
        return None
    applicability = parsed.get("applicability_hint") or "existing"
    if applicability not in APPLICABILITY_VALUES:
        applicability = "existing"
    return {
        "trip_id": str(trip),
        "event_year": int(year),
        "applicability": applicability,
    }


def candidate_report(candidate):
    """A description safe to store on a turn and show in the panel.

    It names what the model proposed, in the operator's terms, and carries no
    count, no total, and no applied state.
    """
    rule = (candidate or {}).get("rule") or {}
    conditions = rule.get("conditions") or {}
    effects = rule.get("effects") or {}
    scope = rule.get("scope") or {}
    return {
        "conditions": {field: entry.get("op") for field, entry in conditions.items()},
        "effects": sorted(effects),
        "applicability": APPLICABILITY_LABELS.get(
            scope.get("applicability"), scope.get("applicability")),
        "applicability_value": scope.get("applicability"),
        "applied": False,
        "requires_owner_confirm": True,
        "rule_hash": (candidate or {}).get("rule_hash"),
        "source": (candidate or {}).get("source"),
        "unrecognised": (candidate or {}).get("unrecognised") or [],
    }


__all__ = [
    "TextRuleError", "candidate_report", "extract_json_block",
    "OPERATOR_FIELDS",
    "parse_provider_text", "rule_candidate", "APPLICABILITY_LABELS",
    "FORBIDDEN_PROVIDER_FIELDS", "MAX_TEXT_CHARS",
]
