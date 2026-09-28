"""Concrete provider adapters and the transport contract they sit on.

This module models the *shape* of a Muse or Gemini call so the boundary can be
built and tested locally, and so the real wiring later is a substitution rather
than a rewrite. What it deliberately does not do is open a socket.

* A `Transport` is the only thing that would ever touch a network. It is
  injected. `HttpTransport` is not implemented here on purpose: shipping a
  half-written network client would let a turn report `is_real_call = True`
  for a call that never left the process.
* `MuseAdapter` and `GeminiAdapter` build a provider-shaped request from the
  allowlisted context, hand it to the transport, and parse the reply into a
  `ProviderResult`. They differ in request shape, in which free-text field
  carries the answer, and in how a failure is recognised.
* Every failure is mapped to exactly one reason code. The mapping is total for
  the shapes the transports raise, and anything unrecognised becomes
  `service_error` rather than being guessed at.

The key is supplied by the caller from a server-side secret store. An adapter
never reads a key out of the request, never puts one in a request body it logs,
and never copies a key into a result. `request_log_entry` is the only view of
a request that is safe to keep, and it carries the key's presence, never its
value.
"""

from __future__ import annotations

import json

from .dialog_turn import (
    OK_STATUS,
    PENDING_STATUS,
    ProviderResult,
    ProviderTransportError,
    WAITING_FAILURES,
)

# Reason codes the turn policy understands. `EXPLICIT_FAILURES` comes from
# dialog_turn; this is the transport's own vocabulary, mapped onto it below.
REASON_CONNECTION_REFUSED = "connection_refused"
REASON_TIMEOUT = "timeout"
REASON_AUTH_FAILED = "auth_failed"
REASON_RATE_LIMITED = "rate_limited"
REASON_FREE_QUOTA_EXHAUSTED = "free_quota_exhausted"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_NOT_CONFIGURED = "not_configured"
REASON_SERVICE_ERROR = "service_error"
REASON_PROVIDER_REFUSED = "provider_refused"

# The default connect+read budget. A Muse call is a local PC; a Gemini call is
# a remote API. Both are bounded so a turn cannot hang the request thread.
DEFAULT_TIMEOUT_SECONDS = 20.0


class TransportUnavailable(RuntimeError):
    """No transport is bound, so a real call is impossible.

    Raised instead of pretending to call a provider. It maps to
    `not_configured`, which is a waiting reason, so a missing transport parks
    the turn instead of burning the one allowed fallback.
    """


class TransportResponse:
    """One HTTP-shaped reply from a transport.

    `status` is the HTTP status. `body` is already-decoded JSON when the
    transport could decode it, otherwise raw text. Neither is logged.
    """

    def __init__(self, status, body=None, headers=None):
        self.status = int(status)
        self.body = body
        self.headers = dict(headers or {})

    def json(self):
        if isinstance(self.body, (dict, list)):
            return self.body
        if isinstance(self.body, (bytes, bytearray)):
            return json.loads(self.body.decode("utf-8"))
        if isinstance(self.body, str):
            return json.loads(self.body)
        return None

    def __repr__(self):
        # The body is omitted on purpose: a provider error body can echo the
        # request, and the request can echo a key.
        return f"TransportResponse(status={self.status})"


class RecordingTransport:
    """Injected transport that answers from a script. Never a network call.

    Each entry is `(status, body)` or an exception instance. It is the only
    transport used in the tests, and it is what makes "did a real call happen?"
    a question with a checkable answer: `calls` records what the adapter asked
    for, including whether a key was attached.
    """

    is_real_call = False

    def __init__(self, script=None):
        # A dict keyed by provider, or one shared list.
        self.script = script if script is not None else []
        self.calls = []

    def send(self, *, provider, url, headers, payload, timeout):
        record = {
            "provider": provider,
            "url": url,
            "timeout": timeout,
            "payload": payload,
            # Presence, never the value.
            "auth_header_names": sorted(headers),
            "auth_header_count": len(headers),
        }
        self.calls.append(record)
        if not self.script:
            raise TransportUnavailable("no scripted response")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, body = item
        return TransportResponse(status, body)


def redact(text):
    """Remove anything that looks like a credential from free text.

    The prefix comparison is case-insensitive, which matters: a key that starts
    with `AIza` or `sk-` has meaningful capitals, so folding the token to lower
    case *before* the prefix test would stop every real key from matching.
    """
    if not isinstance(text, str):
        return text
    out = []
    for token in text.replace("\n", " ").split(" "):
        bare = token.strip('",')
        if len(bare) >= 16 and bare.lower().startswith(_SECRET_PREFIXES):
            out.append("[redacted]")
            continue
        out.append(token)
    return " ".join(out)


# Kept lower-case so `bare.lower().startswith(...)` is a direct comparison.
_SECRET_PREFIXES = ("sk-", "aiza", "ya29.", "gsk_", "xai-", "api-", "key-")


# ----------------------------------------------------------------- mapping
def reason_for_status(status, body=None):
    """Map one HTTP status, plus any provider error hint, to a reason code.

    The order matters. A 429 that the provider labels as a free-tier limit is
    a quota wait, not a plain rate limit, and the turn policy treats the two
    differently: only some reasons are allowed to spend the fallback.
    """
    detail = _error_text(body)
    status = int(status)
    if status in (401, 403):
        return REASON_AUTH_FAILED
    if status == 429:
        if _mentions(detail, ("quota", "free tier", "free-tier",
                              "insufficient_quota", "billing")):
            return REASON_FREE_QUOTA_EXHAUSTED
        return REASON_RATE_LIMITED
    if status == 402:
        return REASON_BUDGET_EXHAUSTED
    if status == 408 or status == 504:
        return REASON_TIMEOUT
    if status == 404:
        # A wrong endpoint is a configuration problem, not a service fault.
        return REASON_NOT_CONFIGURED
    if 500 <= status <= 599:
        return REASON_SERVICE_ERROR
    if status == 400:
        return REASON_PROVIDER_REFUSED
    return REASON_SERVICE_ERROR


def _error_text(body):
    """Pull the provider's error string without keeping the whole payload."""
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        try:
            body = body.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - defensive
            return ""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return body[:200].lower()
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            parts = [str(error.get("status", "")), str(error.get("message", "")),
                     str(error.get("code", ""))]
            return " ".join(parts).lower()
        if isinstance(error, str):
            return error.lower()
        return json.dumps(body, ensure_ascii=False)[:200].lower()
    return str(body)[:200].lower()


def _mentions(text, needles):
    return any(needle in text for needle in needles)


def classify_exception(exc):
    """Map a transport exception to a reason code.

    An adapter re-raises as `ProviderTransportError` so `run_turn` can make its
    single fallback decision. This is the only place that decision's input is
    produced, so the mapping is worth testing directly.
    """
    if isinstance(exc, TransportUnavailable):
        return REASON_NOT_CONFIGURED
    if isinstance(exc, ProviderTransportError):
        return exc.reason
    if isinstance(exc, TimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, ConnectionError):
        return REASON_CONNECTION_REFUSED
    if isinstance(exc, OSError):
        text = str(exc).lower()
        if "timed out" in text or "timeout" in text:
            return REASON_TIMEOUT
        if "refused" in text or "unreachable" in text or "reset" in text:
            return REASON_CONNECTION_REFUSED
        return REASON_SERVICE_ERROR
    return REASON_SERVICE_ERROR


# --------------------------------------------------------------- adapters
class BaseProviderAdapter:
    """Shared request build, response parse, and secret hygiene.

    Subclasses supply the endpoint, the request shape, and where the answer
    sits in a successful reply.
    """

    name = "provider"
    # A class-level model id is only a label for the shape. A real adapter always
    # receives the owner's selected model, and an empty one means nothing was
    # selected, which is reported as `not_configured` rather than guessed.
    model_id = ""
    endpoint = ""
    is_real_call = False

    def __init__(self, *, secret, model_id=None, timeout=DEFAULT_TIMEOUT_SECONDS,
                 transport=None):
        self._secret = secret or ""
        self.model_id = model_id or self.model_id
        self.timeout = float(timeout)
        self.transport = transport
        self.sent_request_ids = []

    # -- secret hygiene ------------------------------------------------
    @property
    def configured(self):
        # A key alone is not enough: a model must have been selected too, or the
        # adapter would have to invent one.
        return bool(self._secret) and bool(self.model_id)

    def key_fingerprint(self):
        """A short, non-reversible marker so an operator can tell two keys apart
        without the value ever being readable or stored."""
        if not self._secret:
            return None
        import hashlib

        digest = hashlib.sha256(self._secret.encode("utf-8")).hexdigest()
        return f"sha256:{digest[:12]}"

    def auth_headers(self):
        if not self._secret:
            return {}
        return {"Authorization": f"Bearer {self._secret}"}

    # -- request -------------------------------------------------------
    def build_request(self, context):
        """Provider-shaped request. The key is never part of the payload."""
        return {
            "model": self.model_id,
            "system": _system_instruction(),
            "context": context,
        }

    def endpoint_url(self):
        return self.endpoint

    # -- response ------------------------------------------------------
    def extract_text(self, body):
        """Return the answer text, or None when the reply carried no content.

        A well-formed reply with nothing in it means the provider has not
        answered yet, which is pending. A reply missing the expected container
        is a shape the provider did not promise, which is a service error; the
        two are told apart by `reply_is_well_formed`.
        """
        raise NotImplementedError

    def reply_is_well_formed(self, body):
        """Whether the reply has the container this provider always sends."""
        raise NotImplementedError

    def interpret(self, *, body, status):
        """Turn a raw reply into a `ProviderResult`. Never raises for a reply."""
        if status in (200, 201):
            try:
                text = self.extract_text(body)
                well_formed = self.reply_is_well_formed(body)
            except Exception:  # noqa: BLE001 - a bad shape is a service error
                return ProviderResult(
                    status="failed", provider=self.name,
                    model_id=self.model_id, reason_code=REASON_SERVICE_ERROR,
                    is_real_call=self.is_real_call)
            if not well_formed:
                return ProviderResult(
                    status="failed", provider=self.name,
                    model_id=self.model_id, reason_code=REASON_SERVICE_ERROR,
                    is_real_call=self.is_real_call)
            if not text or not str(text).strip():
                # The provider accepted the request and has nothing to say. That
                # is pending, not an answer, so the turn waits rather than
                # adopting an empty draft.
                return ProviderResult(
                    status=PENDING_STATUS, provider=self.name,
                    model_id=self.model_id, is_real_call=self.is_real_call)
            return ProviderResult(
                status=OK_STATUS, provider=self.name, model_id=self.model_id,
                summary=redact(str(text))[:400], is_real_call=self.is_real_call)
        reason = reason_for_status(status, body)
        return ProviderResult(
            status="failed", provider=self.name, model_id=self.model_id,
            reason_code=reason, is_real_call=self.is_real_call)

    # -- send ----------------------------------------------------------
    def send(self, request):
        """One attempt. Raises `ProviderTransportError` on a transport fault."""
        context = dict(request or {})
        payload = self.build_request(context)
        if not self.configured:
            raise ProviderTransportError(REASON_NOT_CONFIGURED,
                                         "provider key is not configured")
        if self.transport is None:
            raise ProviderTransportError(REASON_NOT_CONFIGURED,
                                         "no transport is bound")
        attempt_id = str(context.get("attempt_id") or "")
        self.sent_request_ids.append(attempt_id)
        try:
            response = self.transport.send(
                provider=self.name, url=self.endpoint_url(),
                headers=self.auth_headers(), payload=payload,
                timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - re-raised as a classified error
            raise ProviderTransportError(classify_exception(exc), type(exc).__name__)
        return self.interpret(body=response.body, status=response.status)

    def send_with_bounded_retry(self, request, *, max_attempts=None, backoff=None):
        """`run_turn` calls this so one attempt may retry a transient limit.

        The retry stays inside the attempt: it reuses the same `attempt_id`, so
        the turn record still shows a single attempt for this slot.
        """
        return send_with_bounded_retry(
            self, request, max_attempts=max_attempts, backoff=backoff)


def _system_instruction():
    """The instruction text. It describes the contract, not a secret."""
    return (
        "You classify card and bank rows for a Korean travel agency ledger. "
        "Answer with a short Korean sentence naming what to change and why. "
        "Never invent a trip, a date, an amount, or a reservation number. "
        "You do not apply anything; the operator confirms every change."
    )


class MuseAdapter(BaseProviderAdapter):
    """Muse is the operator's own PC.

    It is reached over the local network, so connection refusal and timeout are
    the expected failures and mean "the PC is off", which the turn policy turns
    into the single Gemini fallback.
    """

    name = "muse"
    model_id = ""
    endpoint = "http://127.0.0.1:8765/v1/chat/completions"

    def build_request(self, context):
        body = super().build_request(context)
        # OpenAI-compatible shape, which is what a local server would accept.
        body["messages"] = [
            {"role": "system", "content": body.pop("system")},
            {"role": "user", "content": _context_to_text(context)},
        ]
        return body

    def extract_text(self, body):
        data = body if isinstance(body, dict) else json.loads(body)
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        return message.get("content")

    def reply_is_well_formed(self, body):
        data = body if isinstance(body, dict) else json.loads(body)
        return isinstance(data, dict) and "choices" in data


class GeminiAdapter(BaseProviderAdapter):
    """Gemini is the configured server fallback.

    Its reply shape is different and its quota is different: a free tier that is
    used up is a waiting reason, not a fault to retry elsewhere.
    """

    name = "gemini"
    model_id = ""
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models"

    def endpoint_url(self):
        # The model id belongs in the path, and it comes from server config.
        if not self.model_id:
            # No model was selected. Never guess one.
            return f"{self.endpoint}/UNSELECTED:generateContent"
        return f"{self.endpoint}/{self.model_id}:generateContent"

    def build_request(self, context):
        body = super().build_request(context)
        # The model id lives in the URL path for Gemini, so it is removed from
        # the body rather than sent twice.
        body.pop("model", None)
        body.pop("system", None)
        body["contents"] = [{
            "role": "user",
            "parts": [{"text": _system_instruction() + "\n\n" +
                       _context_to_text(context)}],
        }]
        # A generation config, not a credential.
        body["generationConfig"] = {"temperature": 0, "maxOutputTokens": 800}
        return body

    def extract_text(self, body):
        data = body if isinstance(body, dict) else json.loads(body)
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
        return "\n".join(texts) if texts else None

    def reply_is_well_formed(self, body):
        data = body if isinstance(body, dict) else json.loads(body)
        return isinstance(data, dict) and "candidates" in data


def _context_to_text(context):
    """Render the allowlisted context as the text a provider actually reads.

    Only allowlisted keys are read, and the rendering is explicit, so a field
    added to the context later cannot leak by accident.
    """
    from .dialog_turn import ALLOWED_CONTEXT_FIELDS

    lines = []
    for key in ALLOWED_CONTEXT_FIELDS:
        if key not in context:
            continue
        value = context[key]
        if value in (None, "", {}, []):
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False, default=str)}")
    return "\n".join(lines)


# ------------------------------------------------------------- factory
def build_adapters(config, *, transport=None):
    """Build the adapter pair from server-side configuration only.

    `config` is a `provider_config.ProviderConfig`. Nothing here reads a request
    body, a header chosen by a caller, or a database row written by a viewer.
    A provider with no key comes back as an adapter that reports
    `not_configured`, which is a waiting reason: an unconfigured provider must
    not consume the one allowed fallback.

    The Gemini adapter is only built when the owner has both registered a key
    and turned the fallback on (APP_SPEC 9.3). With the switch off, `gemini` is
    None, so a Muse failure leaves the turn waiting rather than calling a
    provider that was deliberately switched off.

    `transport` may be a dict keyed by provider name, or one shared transport.
    """
    muse_transport = gemini_transport = transport
    if isinstance(transport, dict):
        muse_transport = transport.get("muse")
        gemini_transport = transport.get("gemini")
    muse = None
    gemini = None
    if config.muse_configured:
        muse = MuseAdapter(
            secret=config.muse_secret, model_id=config.muse_model,
            timeout=config.muse_timeout, transport=muse_transport)
    if config.gemini_configured and config.fallback_enabled:
        gemini = GeminiAdapter(
            secret=config.gemini_secret, model_id=config.gemini_model,
            timeout=config.gemini_timeout, transport=gemini_transport)
    return muse, gemini


def adapter_report(muse, gemini):
    """A description of the wiring that is safe to show and to store.

    It names the provider, the model, whether a key is present, and a
    fingerprint. It never contains a key, and a fingerprint is not a key.
    """
    def one(adapter):
        if adapter is None:
            return {"provider": None, "configured": False, "model_id": None,
                    "key_fingerprint": None, "is_real_call": False}
        return {
            "provider": adapter.name,
            "configured": adapter.configured,
            "model_id": adapter.model_id,
            "key_fingerprint": adapter.key_fingerprint(),
            "is_real_call": bool(adapter.is_real_call),
        }
    return {"muse": one(muse), "gemini": one(gemini),
            "waiting_reasons": list(WAITING_FAILURES)}


# ------------------------------------------------------- available models
#
# IMPLEMENTATION_CONTRACT 7.1.1: a model is chosen from a list the server
# fetched, whose free support has been confirmed, and a model name is never
# hardcoded. So the catalog is data that arrives from a transport call, and the
# code below only knows the two reply shapes.
MODEL_LIST_PATH = "https://generativelanguage.googleapis.com/v1beta/models"

# A transient limit may be retried, but a spent daily quota may not: retrying a
# daily limit only spends the same refusal, and the contract asks for a wait
# with the context preserved instead.
RETRYABLE_REASONS = (REASON_RATE_LIMITED, REASON_SERVICE_ERROR)
# A small, fixed ceiling. The provider's own retry guidance is honoured when the
# reply carries one, but never past this, so one turn cannot turn into a loop.
MAX_TRANSPORT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = (0.0, 0.5, 1.5)


class ModelFetchError(Exception):
    """The available-model list could not be read."""

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


def fetch_model_catalog(*, transport, secret, provider="gemini",
                        timeout=DEFAULT_TIMEOUT_SECONDS):
    """Read the provider's available model list.

    Returns a list of `{"model_id", "display_name", "free_supported"}` entries.
    `free_supported` is deliberately None rather than False when the provider
    does not say: an unknown free status is not a free confirmation, and the
    selection path treats None as "not selectable".

    This raises `ModelFetchError` rather than returning an empty list, because
    an empty list and a failed fetch mean different things to the owner.
    """
    if not secret:
        raise ModelFetchError(REASON_NOT_CONFIGURED, "키가 설정되지 않았어요")
    if transport is None:
        raise ModelFetchError(REASON_NOT_CONFIGURED, "전송 계층이 없습니다")
    url = (f"{MODEL_LIST_PATH}" if provider == "gemini"
           else "http://127.0.0.1:8765/v1/models")
    try:
        response = transport.send(
            provider=provider, url=url,
            headers={"Authorization": f"Bearer {secret}"},
            payload={}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - classified below
        raise ModelFetchError(classify_exception(exc), type(exc).__name__)
    if response.status != 200:
        raise ModelFetchError(reason_for_status(response.status, response.body),
                              f"status {response.status}")
    body = response.json()
    if not isinstance(body, dict):
        raise ModelFetchError(REASON_SERVICE_ERROR, "목록 형식이 달라요")
    raw = body.get("models")
    if not isinstance(raw, list):
        raise ModelFetchError(REASON_SERVICE_ERROR, "목록 항목이 없어요")
    catalog = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("name") or entry.get("id") or "").strip()
        if not model_id:
            continue
        # Gemini reports "models/xxx"; the id used in a call is the bare name.
        if "/" in model_id:
            model_id = model_id.rsplit("/", 1)[-1]
        free = entry.get("freeSupported")
        if free is None:
            free = entry.get("free_supported")
        catalog.append({
            "model_id": model_id,
            "display_name": str(entry.get("displayName")
                                or entry.get("display_name") or model_id),
            # None means "the provider did not say", which is not a yes.
            "free_supported": free if isinstance(free, bool) else None,
        })
    catalog.sort(key=lambda item: item["model_id"])
    return catalog


# --------------------------------------------------------- connection test
#
# IMPLEMENTATION_CONTRACT 7.1.1: the connection test sends a short synthetic
# request and returns only whether it worked and the actual model id. It must
# not try a key against a real card or a customer record, so the payload here
# is a fixed sentence with no ledger data in it at all.
CONNECTION_TEST_PROMPT = "ping"


def connection_test(adapter, *, prompt=CONNECTION_TEST_PROMPT):
    """Try one short synthetic request. Never touches ledger data.

    Returns a dict with `ok`, `provider`, `model_id` (what the provider said it
    used, when it says), `reason_code`, and `is_real_call`. A key never appears,
    and the prompt is not echoed back.
    """
    if adapter is None or not adapter.configured or adapter.transport is None:
        return {"ok": False, "provider": getattr(adapter, "name", None),
                "model_id": None,
                "reason_code": REASON_NOT_CONFIGURED, "is_real_call": False}
    payload = adapter.build_request({"row_id": None, "item": prompt})
    try:
        response = adapter.transport.send(
            provider=adapter.name, url=adapter.endpoint_url(),
            headers=adapter.auth_headers(), payload=payload,
            timeout=adapter.timeout)
    except Exception as exc:  # noqa: BLE001 - classified below
        return {"ok": False, "provider": adapter.name, "model_id": None,
                "reason_code": classify_exception(exc),
                "is_real_call": False}
    if response.status not in (200, 201):
        return {"ok": False, "provider": adapter.name, "model_id": None,
                "reason_code": reason_for_status(response.status, response.body),
                "is_real_call": False}
    body = response.json()
    try:
        text = adapter.extract_text(body)
    except Exception:  # noqa: BLE001 - a bad shape is a service error
        text = None
    if not text or not str(text).strip():
        return {"ok": False, "provider": adapter.name, "model_id": None,
                "reason_code": REASON_SERVICE_ERROR, "is_real_call": False}
    # Prefer the id the provider reports over the one we asked for, because the
    # contract asks for the *actual* model id.
    return {"ok": True, "provider": adapter.name,
            "model_id": _reported_model_id(body) or adapter.model_id,
            "reason_code": None, "is_real_call": bool(adapter.is_real_call)}


def _reported_model_id(body):
    if not isinstance(body, dict):
        return None
    for key in ("modelVersion", "model_version", "model", "modelId"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rsplit("/", 1)[-1]
    return None


# ---------------------------------------------------------- bounded retry
def send_with_bounded_retry(adapter, request, *, max_attempts=None, backoff=None):
    """One logical send, with a small retry for a *transient* limit.

    The retry has to look at the result, not only at exceptions. A 429 or a 503
    is a transport that worked and a provider that refused, so the adapter
    returns a `failed` result rather than raising; retrying only on exceptions
    would therefore never retry the case that actually needs it.

    A rate limit or a service error may be retried, capped at
    `MAX_TRANSPORT_ATTEMPTS`. A spent free quota, a spent budget, an auth
    failure, and a missing key are never retried: they will not change, and the
    turn policy has its own waiting and fallback decision for each.

    The retry stays inside one attempt, so it never produces a second
    `attempt_id` and can never be mistaken for a second provider attempt in the
    turn record.
    """
    limit = int(max_attempts or MAX_TRANSPORT_ATTEMPTS)
    limit = max(1, min(limit, MAX_TRANSPORT_ATTEMPTS))
    delays = backoff if backoff is not None else DEFAULT_BACKOFF_SECONDS
    reason = None
    for index in range(limit):
        if index and delays:
            index_delay = delays[min(index, len(delays) - 1)]
            if index_delay:
                import time

                time.sleep(index_delay)
        try:
            result = adapter.send(request)
        except Exception as exc:  # noqa: BLE001 - classified below
            reason = classify_exception(exc)
            if reason not in RETRYABLE_REASONS:
                raise
            continue
        # A refusal is retried only when the reason is transient.
        if result.status == "failed" and result.reason_code in RETRYABLE_REASONS:
            reason = result.reason_code
            continue
        return result
    # Every attempt was refused as transient, or the transport kept faulting.
    # Raise so the turn policy sees the reason and can make its own
    # single-fallback decision, instead of seeing a bare "failed" with no reason.
    raise ProviderTransportError(reason or REASON_SERVICE_ERROR,
                                 "retry budget exhausted")


__all__ = [
    "BaseProviderAdapter", "MuseAdapter", "GeminiAdapter", "RecordingTransport",
    "TransportResponse", "TransportUnavailable", "build_adapters",
    "adapter_report", "classify_exception", "redact", "reason_for_status",
    "fetch_model_catalog", "ModelFetchError", "connection_test",
    "send_with_bounded_retry", "MODEL_LIST_PATH", "CONNECTION_TEST_PROMPT",
    "MAX_TRANSPORT_ATTEMPTS", "DEFAULT_BACKOFF_SECONDS", "RETRYABLE_REASONS",
    "REASON_AUTH_FAILED", "REASON_BUDGET_EXHAUSTED",
    "REASON_CONNECTION_REFUSED", "REASON_FREE_QUOTA_EXHAUSTED",
    "REASON_NOT_CONFIGURED", "REASON_PROVIDER_REFUSED", "REASON_RATE_LIMITED",
    "REASON_SERVICE_ERROR", "REASON_TIMEOUT", "DEFAULT_TIMEOUT_SECONDS",
]
