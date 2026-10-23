"""Phase 6B provider-neutral dialog turns.

The app owns the conversation. A provider only answers one attempt; it never
owns the conversation id, the rule version, the questions and answers, or the
handoff summary. This module holds that policy and nothing else:

* a provider adapter is injected from the server side and is never chosen by
  the request body,
* an explicit Muse failure may switch to the configured Gemini exactly once
  per turn, and a third attempt is not possible,
* every attempt gets its own `attempt_id`, and only the adopted attempt may
  become the turn result, so a late or repeated answer cannot overwrite it,
* if both providers fail, the turn waits. Row saves and already confirmed
  rules do not depend on this module.

No real network call exists in this module. `synthetic_adapter` is marked
`is_real_call = False` and must not be reported as a Muse or Gemini call. No
API key is read, stored, or logged anywhere.

The provider protocols themselves live in `provider_transport.py`, which models
the request and reply shapes of both providers over an injected transport. This
module stays provider-neutral on purpose: it decides *whether* an attempt is
adopted and *whether* one switch is allowed, and it never learns a wire format.
The key comes from `provider_config`, which is read server-side only.
"""

from __future__ import annotations

# Failure reasons that are allowed to trigger the single fallback switch.
EXPLICIT_FAILURES = (
    "connection_refused",
    "rate_limited",
    "timeout",
    "auth_failed",
    "service_error",
    "free_quota_exhausted",
)
# Reasons that leave the turn waiting. They are still explicit failures, but
# they never switch again and never touch billing.
WAITING_FAILURES = ("free_quota_exhausted", "budget_exhausted", "not_configured")
OK_STATUS = "ok"
# The provider took the request and has not answered. This is neither a success
# nor an explicit failure, so the turn waits for the answer. A process restart
# abandons it, and a late answer for an abandoned turn is refused.
PENDING_STATUS = "pending"
STATE_LABELS = {
    "pending": "응답 대기 중",
    "answered": "응답 받음",
    "waiting": "연결 대기 중",
    "abandoned": "중단됨(프로세스 종료)",
}

# Context allowlist. Everything else is dropped before a provider sees it.
# `qa` carries the allowed question and answer pairs, `rule` carries the
# structured rule, and `handoff` carries a guarded summary plus its digest, so
# a provider never depends on the summary alone.
ALLOWED_CONTEXT_FIELDS = (
    "row_id",
    "row_kind",
    "row_revision",
    "item",
    "merchant_normalized",
    "event_kind",
    "card_kind",
    "amount_bucket_krw",
    "occurred_month",
    "current_tab_id",
    "rule_id",
    "rule_version",
    "conversation_id",
    "turn_id",
    "task",
    "qa",
    "rule",
    "handoff",
)
# Never sent: card customer names, reservation numbers, memo free text, and
# any secret. The list is explicit so a test can assert it.
EXCLUDED_CONTEXT_FIELDS = (
    "customer_name",
    "nickname",
    "reservation_no",
    "rsv",
    "operator_note",
    "memo",
    "email",
    "api_key",
    "gemini_key",
)


class TurnOutcome:
    """Result of one turn, including which provider was adopted."""

    def __init__(self, turn_id, state, attempts, adopted_attempt_id=None,
                 provider=None, model_id=None, reason_code=None, draft=None,
                 summary=None, is_real_call=False, switch_count=0):
        self.turn_id = turn_id
        self.state = state
        self.attempts = attempts
        self.adopted_attempt_id = adopted_attempt_id
        self.provider = provider
        self.model_id = model_id
        self.reason_code = reason_code
        self.draft = draft
        self.summary = summary
        self.is_real_call = is_real_call
        self.switch_count = switch_count

    @property
    def adopted(self):
        return self.adopted_attempt_id is not None

    def as_dict(self):
        return {
            "turn_id": self.turn_id,
            "state": self.state,
            "attempts": self.attempts,
            "adopted_attempt_id": self.adopted_attempt_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "reason_code": self.reason_code,
            "draft": self.draft,
            "summary": self.summary,
            "is_real_call": self.is_real_call,
            "switch_count": self.switch_count,
            "fallback_notice": (
                None if not self.switch_count
                else "Muse 연결 실패로 Gemini fallback 사용 중"
            ),
            "state_label": STATE_LABELS.get(self.state, self.state),
        }


class ProviderTransportError(Exception):
    """A send attempt failed in a way that counts as an explicit failure.

    Adapters raise this for connection refusal, timeout, and similar transport
    problems so the turn can still make its single fallback switch. Any other
    exception is a programming error and must not be treated as a provider
    answer.
    """

    def __init__(self, reason="service_error", message=""):
        super().__init__(message or reason)
        self.reason = reason


TRANSPORT_REASONS = {
    "connection_refused": "connection_refused",
    "timeout": "timeout",
    "service_unavailable": "service_error",
    # A reason the transport can raise that is *not* an outage to route around.
    # Without these, an adapter reporting `not_configured` would be collapsed
    # into `service_error` and would spend the single fallback on a provider
    # the owner deliberately left unconfigured.
    "not_configured": "not_configured",
    "free_quota_exhausted": "free_quota_exhausted",
    "budget_exhausted": "budget_exhausted",
    "rate_limited": "rate_limited",
    "auth_failed": "auth_failed",
    "service_error": "service_error",
    "provider_refused": "provider_refused",
}


def classify_send_error(exc):
    """Map a send exception to (reason_code, safe_label).

    Only the exception class name is reported. The message is never stored, so
    a secret or a URL with a key cannot leak into the conversation.
    """
    if isinstance(exc, ProviderTransportError):
        return TRANSPORT_REASONS.get(exc.reason, "service_error"), "transport_error"
    if isinstance(exc, (TimeoutError,)):
        return "timeout", "transport_error"
    if isinstance(exc, ConnectionError):
        return "connection_refused", "transport_error"
    return "adapter_error", type(exc).__name__


class ProviderResult:
    """One provider answer. `draft` is untrusted until the validator runs."""

    def __init__(self, status, provider, model_id, reason_code=None, draft=None,
                 summary=None, is_real_call=False):
        self.status = status
        self.provider = provider
        self.model_id = model_id
        self.reason_code = reason_code
        self.draft = draft
        self.summary = summary
        self.is_real_call = is_real_call

    def as_dict(self):
        return {
            "status": self.status, "provider": self.provider,
            "model_id": self.model_id, "reason_code": self.reason_code,
            "draft": self.draft, "summary": self.summary,
            "is_real_call": self.is_real_call,
        }


class SyntheticAdapter:
    """Deterministic stand-in used for verification only.

    It is never a Muse or Gemini call. `is_real_call` stays False so the
    stored turn record cannot be mistaken for a real provider answer.
    """

    is_real_call = False

    def __init__(self, name, model_id, status=OK_STATUS, reason_code=None,
                 draft=None, summary=None, calls=None):
        self.name = name
        self.model_id = model_id
        self.status = status
        self.reason_code = reason_code
        self.draft = draft
        self.summary = summary
        self.calls = calls if calls is not None else []

    def send(self, request):
        self.calls.append(request)
        return ProviderResult(
            status=self.status, provider=self.name, model_id=self.model_id,
            reason_code=self.reason_code, draft=self.draft, summary=self.summary,
            is_real_call=False,
        )


def amount_bucket(value):
    """Coarse amount bucket. The exact amount is not sent to a provider."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    size = 100000 if abs(number) >= 100000 else 10000
    return (number // size) * size


import hashlib
import re

SUMMARY_LIMIT = 400
# A provider summary is free text. It is not trusted as context on its own, and
# it is only forwarded when it carries no secret-like or source-like value.
_SECRET_LIKE = re.compile(r"(?i)(api[_ -]?key|token|secret|password|bearer)")
_SOURCE_LIKE = re.compile(r"(?i)(rsv[-_ ]?[0-9a-z]{4,}|\d{2,6}-\d{4}-\d{6,})")


def guard_summary(text):
    """Return a forwarded summary or None, plus its digest and length.

    The digest lets both providers and a restarted server agree on the same
    summary without trusting its content.
    """
    raw = "" if text is None else str(text)
    digest = hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()
    stripped = raw.strip()
    if not stripped or len(stripped) > SUMMARY_LIMIT:
        return {"present": bool(stripped), "text": None, "sha256": digest,
                "length": len(stripped), "reason": "length"}
    if _SECRET_LIKE.search(stripped) or _SOURCE_LIKE.search(stripped):
        return {"present": True, "text": None, "sha256": digest,
                "length": len(stripped), "reason": "unverified_value"}
    return {"present": True, "text": stripped, "sha256": digest,
            "length": len(stripped), "reason": None}


def build_qa(items):
    """Keep only question keys whose answer is one of the allowed options.

    A free-text answer that is not an allowed option is reported as
    unrecognised and its text is not forwarded.
    """
    out = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        key = str(item.get("question_key") or "")
        if not key:
            continue
        options = [str(o) for o in (item.get("options") or ())]
        answer = item.get("answer")
        if answer is None:
            out.append({"question_key": key, "answer": None, "verified": False})
            continue
        answer_text = str(answer)
        if options and answer_text in options:
            out.append({"question_key": key, "answer": answer_text, "verified": True})
        else:
            out.append({"question_key": key, "answer": None, "verified": False,
                        "unrecognised": True})
    out.sort(key=lambda entry: entry["question_key"])
    return out


def build_rule_view(rule):
    """Structured rule context. Only validated fields are copied."""
    if not rule:
        return {"rule_id": None, "version": None, "status": None,
                "base_rule_version": None, "conditions": {}, "effects": {},
                "scope": {}, "optional_conditions": {}, "rule_hash": None}
    body = rule.get("rule") if isinstance(rule.get("rule"), dict) else rule
    return {
        "rule_id": rule.get("rule_id"),
        "version": rule.get("version"),
        "base_rule_version": rule.get("base_rule_version"),
        "status": rule.get("status"),
        "conditions": body.get("conditions") or {},
        "optional_conditions": body.get("optional_conditions") or {},
        "effects": body.get("effects") or {},
        "scope": body.get("scope") or {},
        "rule_hash": rule.get("rule_hash"),
    }


def build_context(*, conversation_id, turn_id, row, rule=None, answers=None,
                  handoff_summary="", qa=None):
    """Build the provider context from the allowlist only.

    The row is a stored board payload. Fields outside the allowlist are never
    copied, so customer names, reservation numbers, memo text, and secrets stay
    out by construction rather than by filtering later.
    """
    row = row or {}
    rule = rule or {}
    payload = {
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "task": "",
        "row_id": row.get("row_id"),
        "row_kind": row.get("row_kind"),
        "row_revision": row.get("revision"),
        "item": row.get("item") or "",
        "merchant_normalized": " ".join(str(row.get("source_merchant") or "").split()).casefold(),
        "event_kind": row.get("event_kind") or "",
        "card_kind": row.get("card_kind") or "",
        "amount_bucket_krw": amount_bucket(row.get("amount_krw")),
        "occurred_month": str(row.get("occurred_on") or "")[:7],
        "current_tab_id": row.get("display_tab_id"),
        "rule_id": rule.get("rule_id"),
        "rule_version": rule.get("version"),
        "qa": build_qa(qa) if qa is not None else build_qa(
            [{"question_key": key, "options": None, "answer": value}
             for key, value in (answers or {}).items()]),
        "rule": build_rule_view(rule),
        "handoff": guard_summary(handoff_summary),
    }
    return {key: payload[key] for key in ALLOWED_CONTEXT_FIELDS}


def send_attempt(adapter, request, max_retries=None):
    """One attempt, with an optional bounded retry for a transient limit.

    An adapter that provides its own bounded send is used as-is. A plain
    synthetic adapter is sent once: the retry budget belongs to the real
    transport layer, and adding a sleep loop to the test stand-in would only
    make the suite slow without testing anything new.
    """
    retry = getattr(adapter, "send_with_bounded_retry", None)
    if callable(retry):
        return retry(request, max_attempts=max_retries)
    return adapter.send(request)


def run_turn(*, turn_id, context, muse=None, gemini=None, max_retries=None,
             expire_attempts=None):
    """Run one turn. At most one provider switch, at most two attempts.

    `max_retries` bounds a retry *inside* one attempt for a transient limit. It
    never produces a second `attempt_id`, so a retry cannot be mistaken for a
    second provider attempt in the turn record.

    `expire_attempts` is a callable given the provider name before its send. It
    lets the caller mark an attempt from an earlier, still-outstanding request
    as expired before one new attempt is opened, which is what the contract asks
    for when the PC connection drops mid-question.
    """
    attempts = []
    adopted = None
    switch_count = 0
    seq = 0

    def attempt(adapter, slot):
        nonlocal seq
        if adapter is None:
            return None
        seq += 1
        attempt_id = f"{turn_id}-a{seq}"
        send_error = None
        request = dict(context)
        request["attempt_id"] = attempt_id
        request["slot"] = slot
        if expire_attempts is not None:
            try:
                expired = expire_attempts(adapter.name)
            except Exception:  # noqa: BLE001 - expiry must not block a send
                expired = []
            if expired:
                request["expired_attempt_ids"] = list(expired)
        try:
            result = send_attempt(adapter, request, max_retries)
        except Exception as exc:  # noqa: BLE001 - classified below
            reason_code, safe_label = classify_send_error(exc)
            failed = ProviderResult(
                status="failed", provider=adapter.name,
                model_id=adapter.model_id, reason_code=reason_code,
                is_real_call=False)
            result = failed
            send_error = safe_label
        record = {
            "attempt_id": attempt_id,
            "seq": seq,
            "slot": slot,
            "status": result.status,
            "provider": result.provider,
            "model_id": result.model_id,
            "reason_code": result.reason_code,
            "is_real_call": result.is_real_call,
        }
        if send_error is not None:
            record["send_error"] = send_error
        attempts.append(record)
        if result.status == OK_STATUS:
            record["adopted"] = True
            return ("adopt", attempt_id, result)
        record["adopted"] = False
        if result.status == PENDING_STATUS:
            record["ignored_reason"] = "awaiting_answer"
            return ("pending", attempt_id, result)
        if result.reason_code not in EXPLICIT_FAILURES:
            record["ignored_reason"] = "not_an_explicit_failure"
        return ("fail", attempt_id, result)

    first = attempt(muse, "primary")
    if first and first[0] == "adopt":
        adopted = first
    elif first and first[0] == "pending":
        # The request is outstanding. No second send, so the single switch stays
        # available for a later turn.
        return TurnOutcome(
            turn_id=turn_id, state="pending", attempts=attempts,
            provider=first[2].provider, model_id=first[2].model_id,
            reason_code=first[2].reason_code, is_real_call=False, switch_count=0)
    else:
        reason = first[2].reason_code if first else "not_configured"
        # A waiting reason leaves the turn parked. DETAILED_CONTRACT 7: a spent
        # free quota, an exhausted budget, or a provider that was never
        # configured must not spend the one allowed switch, because the
        # fallback cannot answer either and a second attempt would only turn a
        # wait into a wrong answer. The row, the rule draft, and the recorded
        # answers are all untouched, and the next turn starts over.
        if reason in EXPLICIT_FAILURES and reason not in WAITING_FAILURES:
            second = attempt(gemini, "fallback")
            if second is not None:
                # The switch happened and is recorded for the audit even when
                # the fallback fails too.
                switch_count = 1
            if second and second[0] == "adopt":
                adopted = second
            else:
                reason = (second[2].reason_code if second and second[2].reason_code
                          else reason)
        if adopted is None:
            state = "waiting"
            return TurnOutcome(
                turn_id=turn_id, state=state, attempts=attempts,
                reason_code=reason, switch_count=switch_count)

    result = adopted[2]
    return TurnOutcome(
        turn_id=turn_id, state="answered", attempts=attempts,
        adopted_attempt_id=adopted[1], provider=result.provider,
        model_id=result.model_id, reason_code=result.reason_code,
        draft=result.draft, summary=result.summary,
        is_real_call=result.is_real_call, switch_count=switch_count,
    )
