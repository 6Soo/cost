"""
Deterministic only. No model call, no code execution, no network call, and no
new normalization loop.

Condition sources come from the card source contract, not from the editable
row. `card_import.classify_parsed` returns `merchant`, `event_kind`, and the
optional `card_kind` column of the card profile. `import_row` stores those as
`source_merchant`, `event_kind`, and `card_kind` on the row, and
`LedgerStore.card_source_keys` resolves the same three keys for a row that
predates that change by reading `card_import_rows.raw_json` through the same
`classify_parsed`. A stored row and a new upload are therefore evaluated with
identical keys, and an existing row and a future row mean the same thing.

`description` is never read as a condition source because the owner can edit
it, and nothing is inferred from the amount sign. A subject with no card source
keeps the field missing, the rule does not match it, and the preview reports
the missing source count instead of hiding it.

Allowed rule conditions: merchant_normalized, card_kind, transaction_direction.
Allowed optional conditions: amount_range, date_or_service_period.
Allowed effects: display_tab_id, item, description_template.
Amount and transaction-date effects are rejected, so source amounts and dates
stay protected. A later rule never wins by being newer: a conflict is reported
with both conditions and a concrete example row, and the earlier rule stays
active until it is explicitly superseded.
"""

from __future__ import annotations

import re
from datetime import date as _calendar_date

from .contracts import canonical_text, sha256_text

ALLOWED_CONDITIONS = ("merchant_normalized", "card_kind", "transaction_direction")
ALLOWED_OPTIONAL = ("amount_range", "date_or_service_period")
ALLOWED_EFFECTS = ("display_tab_id", "item", "description_template")
APPLICABILITY_VALUES = ("existing", "future", "existing_and_future")
RULE_STATUSES = ("draft", "active", "historical_only", "superseded")
DIRECTION_VALUES = ("purchase", "refund", "cancellation")
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
ALLOWED_PLACEHOLDERS = ("merchant",)
# Fields a rule may never write. Source amounts, dates, and source identity
# stay owned by the source contract.
FORBIDDEN_EFFECT_FIELDS = (
    "amount_krw", "occurred_on", "sign", "currency", "merchant", "description",
    "source_event_id", "source_kind", "evidence_type", "reservation_no",
    "service_period", "operator_note", "classification_state", "revision",
    "row_id", "row_kind", "income_kind", "customer_id", "customer_name",
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
INT_RE = re.compile(r"[+-]?\d+")

# Condition source keys. A subject provides these either from the card source
# lineage (an already stored row) or from the card import event (a new upload),
# through the same `classify_parsed` contract, so an existing row and a future
# row are evaluated with identical keys.
#
#   source_merchant  card source merchant text, never the edited description
#   event_kind       purchase | refund | cancellation, from the source row
#   card_kind        card kind column of the card source profile
#
# Nothing here is derived from the amount sign or from an edited description.
# A subject without a card source simply has no value, and a rule that needs
# the missing field does not match that subject.
SOURCE_KEYS = ("source_merchant", "event_kind", "card_kind")


class RuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_merchant(text) -> str:
    """Explicit adapter that folds only case and whitespace.

    The webapp pipeline has no merchant normalizer of its own: the existing
    source contract keeps the raw merchant text in `classify_parsed` and
    `content_digest`. So this adapter reuses that exact source string and only
    makes comparison stable across case and repeated spaces. It never builds a
    second merchant identification system, never reclassifies, and never reads
    the editable `description` field.
    """
    if text is None:
        return ""
    return " ".join(str(text).split()).casefold()


def strict_int(value, field: str) -> int:
    """Accept integers only.

    Rejects bool, float, and any string that would truncate silently such as
    "100.5" or "1e3".
    """
    if isinstance(value, bool):
        raise RuleError("RULE_CONDITION_TYPE", f"정수 값이 필요해요: {field}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise RuleError("RULE_CONDITION_TYPE", f"실수는 허용하지 않아요: {field}")
    if isinstance(value, str):
        text = value.strip()
        if not INT_RE.fullmatch(text):
            raise RuleError("RULE_CONDITION_TYPE", f"정수 값이 필요해요: {field}")
        return int(text)
    raise RuleError("RULE_CONDITION_TYPE", f"정수 값이 필요해요: {field}")


def check_date(value, field: str) -> str:
    """Format check plus real calendar validity."""
    text = str(value or "").strip()
    if not DATE_RE.fullmatch(text):
        raise RuleError("RULE_CONDITION_TYPE", f"날짜 형식이 달라요: {field}")
    try:
        _calendar_date.fromisoformat(text)
    except ValueError:
        raise RuleError("RULE_CONDITION_TYPE", f"실제 없는 날짜예요: {field}")
    return text


def _scalar(value, field: str):
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, str):
        return value
    raise RuleError("RULE_CONDITION_TYPE", f"조건 값 형식이 달라요: {field}")


def _condition_entry(field: str, raw):
    if isinstance(raw, dict):
        unknown = sorted(set(raw) - {"op", "value"})
        if unknown:
            raise RuleError("RULE_FIELD_NOT_ALLOWED", f"조건에 허용되지 않은 항이 있어요: {unknown}")
        op = str(raw.get("op") or "eq")
        if op not in ("eq", "in", "neq"):
            raise RuleError("RULE_OPERATOR_NOT_ALLOWED", f"조건 연산자는 eq/in/neq만 가능해요: {field}")
        value = raw.get("value")
    else:
        op = "in" if isinstance(raw, list) else "eq"
        value = raw
    if op == "in":
        if not isinstance(value, list) or not value:
            raise RuleError("RULE_CONDITION_TYPE", f"in 조건은 값 목록이 필요해요: {field}")
        return {"op": op, "value": [_scalar(v, field) for v in value]}
    if op == "neq":
        return {"op": op, "value": _scalar(value, field)}
    return {"op": "eq", "value": _scalar(value, field)}


def normalize_draft(draft: dict, *, learning_case_id: str = "",
                    rule_id: str = "", version: int = 1,
                    base_rule_version: int = 0) -> dict:
    """Validate one structured draft and return the canonical rule.

    Rejects unknown condition/effect fields, amount or date effects, template
    placeholders other than {merchant}, non-scalar condition values, and a
    travel placement effect without trip, year, and applicability.
    """
    if not isinstance(draft, dict):
        raise RuleError("INVALID_VALUE", "규칙 초안 형식이 달라요")
    unknown_top = sorted(set(draft) - {
        "conditions", "optional_conditions", "effects", "scope", "exceptions",
        "note", "learning_case_id", "rule_id", "version", "base_rule_version",
    })
    if unknown_top:
        raise RuleError("RULE_FIELD_NOT_ALLOWED", f"초안에 허용되지 않은 항이 있어요: {unknown_top}")

    conditions_in = draft.get("conditions") or {}
    if not isinstance(conditions_in, dict) or not conditions_in:
        raise RuleError("INVALID_VALUE", "최소 한 개의 분류 조건이 필요해요")
    conditions = {}
    for field, raw in conditions_in.items():
        if field not in ALLOWED_CONDITIONS:
            raise RuleError("RULE_FIELD_NOT_ALLOWED", f"허용되지 않은 조건이에요: {field}")
        entry = _condition_entry(field, raw)
        if field == "merchant_normalized":
            if entry["op"] == "in":
                entry["value"] = [normalize_merchant(v) for v in entry["value"]]
            else:
                entry["value"] = normalize_merchant(entry["value"])
        if field == "transaction_direction":
            values = entry["value"] if entry["op"] == "in" else [entry["value"]]
            for value in values:
                if value not in DIRECTION_VALUES:
                    raise RuleError("RULE_CONDITION_TYPE", "거래 방향 값이 달라요")
        conditions[field] = entry

    optional_in = draft.get("optional_conditions") or {}
    if not isinstance(optional_in, dict):
        raise RuleError("INVALID_VALUE", "선택 조건 형식이 달라요")
    unknown_opt = sorted(set(optional_in) - set(ALLOWED_OPTIONAL))
    if unknown_opt:
        raise RuleError("RULE_FIELD_NOT_ALLOWED", f"허용되지 않은 선택 조건이에요: {unknown_opt}")
    optional = {}
    if "amount_range" in optional_in:
        raw = optional_in["amount_range"] or {}
        if not isinstance(raw, dict) or sorted(set(raw) - {"min", "max"}):
            raise RuleError("RULE_FIELD_NOT_ALLOWED", "금액 범위는 min/max만 가능해요")
        entry = {}
        if raw.get("min") is not None:
            entry["min"] = strict_int(raw["min"], "amount_range.min")
        if raw.get("max") is not None:
            entry["max"] = strict_int(raw["max"], "amount_range.max")
        if not entry:
            raise RuleError("INVALID_VALUE", "금액 범위를 입력해 주세요")
        if "min" in entry and "max" in entry and entry["min"] > entry["max"]:
            raise RuleError("INVALID_VALUE", "금액 범위 순서가 달라요")
        optional["amount_range"] = entry
    if "date_or_service_period" in optional_in:
        raw = optional_in["date_or_service_period"] or {}
        if not isinstance(raw, dict) or sorted(set(raw) - {"from", "to"}):
            raise RuleError("RULE_FIELD_NOT_ALLOWED", "기간 조건은 from/to만 가능해요")
        entry = {}
        if raw.get("from"):
            entry["from"] = check_date(raw["from"], "date_or_service_period.from")
        if raw.get("to"):
            entry["to"] = check_date(raw["to"], "date_or_service_period.to")
        if not entry:
            raise RuleError("INVALID_VALUE", "기간 조건을 입력해 주세요")
        if "from" in entry and "to" in entry and entry["from"] > entry["to"]:
            raise RuleError("INVALID_VALUE", "기간 순서가 달라요")
        optional["date_or_service_period"] = entry

    effects_in = draft.get("effects") or {}
    if not isinstance(effects_in, dict) or not effects_in:
        raise RuleError("INVALID_VALUE", "규칙이 바꿀 항목을 선택해 주세요")
    for field in effects_in:
        if field in FORBIDDEN_EFFECT_FIELDS:
            raise RuleError("RULE_EFFECT_FORBIDDEN", f"규칙은 금액·날짜·원천 항목을 바꿀 수 없어요: {field}")
        if field not in ALLOWED_EFFECTS:
            raise RuleError("RULE_FIELD_NOT_ALLOWED", f"허용되지 않은 효과예요: {field}")
    effects = {}
    for field, value in effects_in.items():
        if field == "display_tab_id":
            tab = str(value or "").strip()
            if not tab:
                raise RuleError("INVALID_VALUE", "여행 탭을 선택해 주세요")
            effects[field] = tab
        elif field == "item":
            item = str(value or "").strip()
            if not item:
                raise RuleError("INVALID_VALUE", "항목을 입력해 주세요")
            effects[field] = item
        else:
            template = str(value or "")
            if not template.strip():
                raise RuleError("INVALID_VALUE", "내용 양식을 입력해 주세요")
            for name in PLACEHOLDER_RE.findall(template):
                if name not in ALLOWED_PLACEHOLDERS:
                    raise RuleError("RULE_TEMPLATE_FORBIDDEN", f"사용할 수 없는placeholder예요: {{{name}}}")
            effects[field] = template

    scope_in = draft.get("scope") or {}
    if not isinstance(scope_in, dict) or sorted(set(scope_in) - {"trip_id", "event_year", "applicability"}):
        raise RuleError("RULE_FIELD_NOT_ALLOWED", "범위는 trip_id/event_year/applicability만 가능해요")
    scope = {
        "trip_id": str(scope_in.get("trip_id") or "").strip(),
        "event_year": (strict_int(scope_in["event_year"], "scope.event_year")
                       if scope_in.get("event_year") not in (None, "") else None),
        "applicability": str(scope_in.get("applicability") or "").strip(),
    }
    if "display_tab_id" in effects:
        if not scope["trip_id"] or scope["event_year"] is None or not scope["applicability"]:
            raise RuleError("RULE_SCOPE_INCOMPLETE", "여행 배정 규칙은 여행·연도·적용 범위가 모두 필요해요")
    if scope["applicability"] and scope["applicability"] not in APPLICABILITY_VALUES:
        raise RuleError("RULE_CONDITION_TYPE", "적용 범위 값이 달라요")

    exceptions_in = draft.get("exceptions") or []
    if not isinstance(exceptions_in, list):
        raise RuleError("INVALID_VALUE", "제외 조건 형식이 달라요")
    exceptions = []
    for item in exceptions_in:
        if not isinstance(item, dict) or sorted(set(item) - {"field", "op", "value"}):
            raise RuleError("RULE_FIELD_NOT_ALLOWED", "제외 조건은 field/op/value만 가능해요")
        field = str(item.get("field") or "")
        if field not in ALLOWED_CONDITIONS:
            raise RuleError("RULE_FIELD_NOT_ALLOWED", f"허용되지 않은 제외 조건이에요: {field}")
        op = str(item.get("op") or "eq")
        if op not in ("eq", "in", "neq"):
            raise RuleError("RULE_OPERATOR_NOT_ALLOWED", f"제외 연산자는 eq/in/neq만 가능해요: {op}")
        value = item.get("value")
        if op == "in":
            if not isinstance(value, list) or not value:
                raise RuleError("RULE_CONDITION_TYPE", "in 제외 조건은 값 목록이 필요해요")
            value = [normalize_merchant(v) if field == "merchant_normalized" else _scalar(v, field) for v in value]
        else:
            value = normalize_merchant(value) if field == "merchant_normalized" else _scalar(value, field)
        exceptions.append({"field": field, "op": op, "value": value})

    evidence = draft.get("learning_case_id") or learning_case_id
    if evidence is not None and not str(evidence).strip():
        evidence = None
    rule = {
        "rule_id": str(rule_id or draft.get("rule_id") or "").strip(),
        "version": strict_int(draft.get("version") or version, "version"),
        "base_rule_version": strict_int(
            draft.get("base_rule_version") or base_rule_version, "base_rule_version"),
        "conditions": conditions,
        "optional_conditions": optional,
        "effects": effects,
        "scope": scope,
        "exceptions": exceptions,
        "evidence_case_ids": [str(evidence)] if evidence else [],
        "note": str(draft.get("note") or ""),
    }
    if not rule["rule_id"]:
        raise RuleError("INVALID_VALUE", "규칙 식별자가 필요해요")
    return rule


def rule_hash(rule: dict) -> str:
    return sha256_text(canonical_text(rule))


def subject_values(subject: dict) -> tuple[dict, list]:
    """Return the condition values one subject provides plus its missing fields.

    A subject is a stored board row payload enriched with its card source keys,
    or a card import event. Both go through the same `classify_parsed` source
    contract, so an existing row and a future upload evaluate identically.
    `description` is deliberately not read: the user can edit it, so it is not
    a source of truth. A row without a card source keeps the field missing and
    the rule does not match it.
    """
    values = {}
    if subject.get("event_kind"):
        values["transaction_direction"] = str(subject["event_kind"])
    if subject.get("source_merchant"):
        values["merchant_normalized"] = normalize_merchant(subject["source_merchant"])
    if subject.get("card_kind"):
        values["card_kind"] = str(subject["card_kind"])
    if subject.get("amount_krw") is not None:
        values["amount_krw"] = strict_int(subject["amount_krw"], "amount_krw")
    if subject.get("occurred_on"):
        values["occurred_on"] = str(subject["occurred_on"])
    if subject.get("service_period"):
        values["service_period"] = str(subject["service_period"])
    missing = [field for field in ALLOWED_CONDITIONS if field not in values]
    return values, missing


def condition_source_report(rule: dict, subjects) -> dict:
    """Count how many subjects provide each condition field of the rule.

    Reported from the data, not from a hardcoded assumption. A field with
    missing sources stays a mismatch instead of being silently ignored.
    """
    report = {}
    for field in rule.get("conditions") or {}:
        with_source = 0
        for subject in subjects:
            values, missing = subject_values(subject)
            if field not in missing:
                with_source += 1
        report[field] = {"subjects": len(subjects), "with_source": with_source,
                         "missing_source": len(subjects) - with_source}
    return report


def _match_entry(entry: dict, actual) -> bool:
    op, expected = entry["op"], entry["value"]
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    return actual in expected


def rule_matches(rule: dict, subject: dict) -> dict:
    """Evaluate one rule against one subject.

    Returns `matched`, `reason`, and `unavailable`. A rule with an unavailable
    condition never matches, and the reason says which field is missing.
    """
    values, missing = subject_values(subject)
    unavailable = [field for field in missing if field in rule["conditions"]]
    if unavailable:
        return {"matched": False, "unavailable": unavailable,
                "reason": f"조건 원천이 없어요: {', '.join(sorted(unavailable))}"}
    for field, entry in rule["conditions"].items():
        if not _match_entry(entry, values.get(field)):
            return {"matched": False, "unavailable": [],
                    "reason": f"조건 불일치: {field}"}
    optional = rule.get("optional_conditions") or {}
    amount_range = optional.get("amount_range")
    if amount_range:
        amount = values.get("amount_krw")
        if amount is None:
            return {"matched": False, "unavailable": ["amount_range"],
                    "reason": "금액 원천이 없어요"}
        if "min" in amount_range and amount < amount_range["min"]:
            return {"matched": False, "unavailable": [], "reason": "금액 범위 밖"}
        if "max" in amount_range and amount > amount_range["max"]:
            return {"matched": False, "unavailable": [], "reason": "금액 범위 밖"}
    period = optional.get("date_or_service_period")
    if period:
        occurred = values.get("occurred_on") or values.get("service_period") or ""
        if not occurred:
            return {"matched": False, "unavailable": ["date_or_service_period"],
                    "reason": "기간 원천이 없어요"}
        if "from" in period and occurred < period["from"]:
            return {"matched": False, "unavailable": [], "reason": "기간 밖"}
        if "to" in period and occurred > period["to"]:
            return {"matched": False, "unavailable": [], "reason": "기간 밖"}
    for item in rule.get("exceptions") or []:
        if item["field"] in values and _match_entry(
                {"op": item["op"], "value": item["value"]}, values[item["field"]]):
            return {"matched": False, "unavailable": [],
                    "reason": f"제외 조건에 해당: {item['field']}"}
    return {"matched": True, "unavailable": [], "reason": "조건 일치"}


def resolve_effect(rule: dict, row: dict, field: str):
    """Return the value a rule would write for one field, change or not."""
    if field not in rule["effects"]:
        return None
    if field == "description_template":
        merchant = row.get("source_merchant")
        if merchant is None:
            merchant = row.get("merchant") or ""
        return str(rule["effects"][field]).replace("{merchant}", str(merchant))
    return rule["effects"][field]


def plan_effect(rule: dict, row: dict, locked_fields=()) -> dict:
    """Return the field changes for one row, skipping manually locked fields."""
    locked = set(locked_fields or ())
    changes = {}
    merchant = row.get("source_merchant")
    if merchant is None:
        merchant = row.get("merchant") or ""
    for field, value in rule["effects"].items():
        target = "description" if field == "description_template" else field
        if field in locked or target in locked:
            continue
        if field == "description_template":
            new_value = str(value).replace("{merchant}", str(merchant))
        else:
            new_value = value
        if row.get(target) != new_value:
            changes[target] = new_value
    return changes


def rule_conditions_view(rule: dict) -> dict:
    """Condition summary used in conflict reports and confirmations."""
    view = dict(rule.get("conditions") or {})
    if rule.get("optional_conditions"):
        view["optional_conditions"] = rule["optional_conditions"]
    if rule.get("exceptions"):
        view["exceptions"] = rule["exceptions"]
    return view


def _example_row(rule: dict, row: dict, field: str) -> dict:
    target = "description" if field == "description_template" else field
    return {
        "row_id": row.get("row_id"),
        "revision": row.get("revision"),
        "field": field,
        "current_value": row.get(target),
        "source_merchant": row.get("source_merchant") or row.get("merchant") or "",
        "event_kind": row.get("event_kind") or "",
        "card_kind": row.get("card_kind") or "",
        "amount_krw": row.get("amount_krw"),
        "occurred_on": row.get("occurred_on") or "",
        "new_rule_would_write": resolve_effect(rule, row, field),
    }


def find_conflicts(rule: dict, row: dict, active_records) -> list:
    """Report active rules that assert a different value on the same field.

    `active_records` are stored rule records with `rule` and `status`. The
    report carries both sides' conditions and one concrete example row so the
    user can see the real case, and it never resolves the conflict by itself.
    """
    conflicts = []
    for record in active_records or ():
        other = record.get("rule") or {}
        if record.get("rule_id") == rule.get("rule_id"):
            continue
        if record.get("status") != "active":
            continue
        if not rule_matches(other, row).get("matched"):
            continue
        for field in (other.get("effects") or {}):
            if field not in rule["effects"]:
                continue
            mine = resolve_effect(rule, row, field)
            theirs = resolve_effect(other, row, field)
            if mine is not None and theirs is not None and mine != theirs:
                conflicts.append({
                    "rule_id": record.get("rule_id"),
                    "rule_version": record.get("version"),
                    "field": field,
                    "existing_value": theirs,
                    "new_rule_value": mine,
                    "existing_conditions": rule_conditions_view(other),
                    "new_conditions": rule_conditions_view(rule),
                    "example": _example_row(rule, row, field),
                    "resolution": "explicit_supersede_or_narrow_draft",
                    "auto_resolved": False,
                })
    return conflicts


def find_same_effect_rules(rule: dict, row: dict, active_records) -> list:
    """Active rules that already write the same value on the same field.

    Reported so a duplicated effect is visible, and used to keep a second
    application from writing the same value again.
    """
    same = []
    for record in active_records or ():
        other = record.get("rule") or {}
        if record.get("rule_id") == rule.get("rule_id"):
            continue
        if record.get("status") != "active":
            continue
        if not rule_matches(other, row).get("matched"):
            continue
        for field in (other.get("effects") or {}):
            if field not in rule["effects"]:
                continue
            mine = resolve_effect(rule, row, field)
            theirs = resolve_effect(other, row, field)
            if mine is not None and theirs is not None and mine == theirs:
                same.append({
                    "rule_id": record.get("rule_id"), "field": field, "value": mine,
                })
    return same


# The question set is derived from the case row, the draft, and the answers
# already stored. Nothing here calls a model, and every count comes from the
# server. Answers already given are never asked again, and a draft that is
# already complete produces no further question.
MAX_QUESTIONS = 5

QUESTION_SPECS = (
    {
        "key": "rule_kind",
        "prompt": "이번 거래에만 적용할까요, 비슷한 거래에도 적용할까요?",
        "options": ("this_only", "repeatable"),
    },
    {
        "key": "evidence_basis",
        "prompt": "이렇게 분류한 근거는 무엇인가요?",
        "options": ("schedule_or_booking", "merchant_service", "one_off_exception"),
    },
    {
        "key": "trip_scope",
        "prompt": "어느 여행에 적용할까요?",
        "options": ("same_trip", "other_trip", "no_trip"),
    },
    {
        "key": "event_year",
        "prompt": "어느 연도에 적용할까요?",
        "options": ("this_year",),
    },
    {
        "key": "period",
        "prompt": "적용 기간을 제한할까요?",
        "options": ("no_period_limit", "limited_period"),
    },
)

# Stored values stay as internal enums. The screen shows these labels.
OPTION_LABELS = {
    "this_only": "이번 거래에만",
    "repeatable": "비슷한 거래에도",
    "schedule_or_booking": "일정·예약 근거",
    "merchant_service": "가맹점의 특정 서비스",
    "one_off_exception": "이번 건만 예외",
    "same_trip": "이 행과 같은 여행",
    "other_trip": "다른 여행",
    "no_trip": "여행 지정 안 함",
    "this_year": "이번 연도",
    "no_period_limit": "기간 제한 없음",
    "limited_period": "기간을 정함",
}

SYNTHETIC_MODE_NOTE = "합성 모드입니다. 실제 AI 모델은 연결되지 않았습니다."

# Screen labels for the stored states. The values stay as they are.
DIALOG_STATE_LABELS = {
    "not_started": "시작 전",
    "open": "진행 중",
    "closed": "닫힘",
    "one_off": "이번 거래만 적용",
}

REASON_LABELS = {
    "connection_refused": "연결 거부",
    "timeout": "시간 초과",
    "auth_failed": "인증 실패",
    "service_error": "서비스 오류",
    "rate_limited": "요청 한도 초과",
    "free_quota_exhausted": "무료 한도 소진",
    "budget_exhausted": "예산 소진",
    "not_configured": "연결 설정 없음",
    "adapter_error": "연결 모듈 오류",
    "transport_error": "전송 오류",
    "process_restart": "프로세스 종료로 중단",
    "unknown_owner": "소유 프로세스를 확인할 수 없음",
    "owner_pid_reused": "같은 pid를 다른 프로세스가 쓰는 중으로 의심",
    "owner_still_leased": "임대 기한 안이라 소유자가 살아 있을 수 있음",
    "owner_state_unknown": "소유 프로세스 상태를 확인할 수 없음",
}


def dialog_state_label(value):
    return DIALOG_STATE_LABELS.get(value, value)


def reason_label(value):
    return REASON_LABELS.get(value, value)

# An answer that means "this transaction only" ends the dialog. No permanent
# rule is created, so no further question, preview, or apply may follow.
ONE_OFF_ANSWERS = ("this_only", "one_off_exception")


def option_label(value):
    return OPTION_LABELS.get(value, value)


def question_view(question):
    """Screen view of one stored question. Values stay internal enums."""
    return {
        "question_id": question.get("question_id"),
        "question_key": question.get("question_key"),
        "prompt": question.get("prompt"),
        "options": [{"value": value, "label": option_label(value)}
                    for value in (question.get("options") or ())],
        "answer": question.get("answer"),
        "answer_label": option_label(question.get("answer")) if question.get("answer") else None,
        "answered": question.get("answer") is not None,
    }


PROVIDER_INFO = {
    "provider": "synthetic-fixture",
    "model": None,
    # Both spellings name the same fact: no real model was called.
    "is_real_call": False,
    "is_real_model_call": False,
    "network_call": False,
    "note": SYNTHETIC_MODE_NOTE,
    "mode_label": SYNTHETIC_MODE_NOTE,
}


def needed_questions(draft: dict, answers: dict) -> list:
    """Return only the questions that are still needed, at most five.

    A question is skipped when the draft already answers it or when the stored
    answers already cover it, so a complete draft yields an empty list.
    """
    given = dict(answers or {})
    if dialog_blocks_rule(given):
        return []
    effects = (draft or {}).get("effects") or {}
    scope = (draft or {}).get("scope") or {}
    optional = (draft or {}).get("optional_conditions") or {}
    needed = []
    for spec in QUESTION_SPECS:
        key = spec["key"]
        if key in given:
            continue
        if key == "rule_kind" and (draft or {}).get("rule_kind"):
            continue
        if key == "evidence_basis" and (draft or {}).get("evidence_basis"):
            continue
        if key == "trip_scope" and (not effects.get("display_tab_id") or scope.get("trip_id")):
            continue
        if key == "event_year" and scope.get("event_year"):
            continue
        if key == "period" and optional.get("date_or_service_period"):
            continue
        needed.append({
            "question_key": key, "prompt": spec["prompt"],
            "options": list(spec["options"]), "answered": False,
        })
    return needed[:MAX_QUESTIONS]


def dialog_blocks_rule(answers: dict) -> bool:
    """A one-off answer ends the dialog without creating a permanent rule."""
    given = dict(answers or {})
    return any(given.get(key) in ONE_OFF_ANSWERS
               for key in ("rule_kind", "evidence_basis"))
