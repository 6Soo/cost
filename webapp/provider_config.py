"""Server-side provider configuration and the secret store boundary.

The rules this module exists to enforce:

* A key is set by the owner through a dedicated write path, and it is read from
  the store only when a request is actually being sent. It is never read from a
  request body, a query string, or a client-chosen header.
* A key never appears in a response body, a log line, a turn record, or the
  provider context. What is exposed instead is a `sha256:` fingerprint, which
  lets an operator tell two keys apart without the value being recoverable.
* Configuration lives outside the ledger DB. Storing a credential next to the
  rows it helps classify would put it inside the backup, the export, and the
  migration snapshot.
* This store is a local, file-backed fake. It is deliberately not a real
  credential vault, and `is_real_secret_store` stays False so nothing can
  report a real secret as stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile

# A local secret store, not a vault. Nothing here talks to a network.
is_real_secret_store = False

STORE_ENV = "WEBLEDGER_PROVIDER_SECRETS"
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

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _looks_secret(text):
    return (isinstance(text, str) and len(text) >= 16
            and text.startswith(SECRET_PREFIXES))


def redact(value):
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


def fingerprint(secret):
    """A non-reversible marker. Not a key, and not usable as one."""
    if not secret:
        return None
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _validate_model(value, field):
    text = str(value or "").strip()
    if not text:
        raise ConfigError("INVALID_VALUE", f"{field}이 필요해요")
    if not MODEL_RE.match(text):
        # A model id goes into a URL path, so anything else is refused rather
        # than escaped.
        raise ConfigError("INVALID_VALUE", f"{field} 형식이 달라요")
    return text


def _validate_timeout(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError("INVALID_VALUE", "제한 시간이 숫자가 아니에요")
    if not TIMEOUT_MIN <= number <= TIMEOUT_MAX:
        raise ConfigError("INVALID_VALUE", "제한 시간이 허용 범위를 벗어났어요")
    return number


def _validate_secret(value, field):
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


class SecretStore:
    """File-backed local secret store.

    The file is written with owner-only permissions where the platform allows
    it. It is created with a restrictive mode rather than inheriting the
    directory, because a credential is only as private as the file it lands in.
    """

    is_real_secret_store = False

    def __init__(self, path=None):
        if path is None:
            path = os.environ.get(STORE_ENV) or os.path.join(
                tempfile.gettempdir(), "webledger-provider-secrets.json")
        self.path = str(path)
        self._data = None

    # -- persistence ---------------------------------------------------
    def _load(self):
        if self._data is not None:
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {}
        except (ValueError, OSError):
            # A corrupt or unreadable store is treated as empty rather than
            # crashing a turn, and the caller sees "not configured".
            data = {}
        if not isinstance(data, dict):
            data = {}
        self._data = data
        return data

    def _flush(self):
        payload = json.dumps(self._data or {}, ensure_ascii=False, indent=2,
                             sort_keys=True)
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False,
            prefix=".secrets-", suffix=".tmp")
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        try:
            os.chmod(handle.name, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            # Windows may refuse; the file is still created.
            pass
        os.replace(handle.name, self.path)
        try:
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    # -- api -----------------------------------------------------------
    def get(self, provider, field):
        """Read one stored value.

        The stored form is normalised on the way out as well as on the way in.
        An earlier version returned only `str`, so a numeric value written as a
        float by `set` came back as an empty string and a configured timeout
        silently reverted to the default. The round trip is now exact for both
        text and numbers, and anything of an unexpected type is still refused
        rather than coerced.
        """
        entry = self._load().get(provider) or {}
        value = entry.get(field)
        if value is None or isinstance(value, str):
            return value if isinstance(value, str) else ""
        if isinstance(value, bool):
            # A bool is not a number here, and silently reading True as 1 would
            # turn a flag into a timeout.
            return ""
        if isinstance(value, (int, float)):
            return value
        return ""

    def set(self, provider, field, value):
        data = self._load()
        entry = data.setdefault(provider, {})
        if value in (None, ""):
            entry.pop(field, None)
        else:
            entry[field] = value
        if not entry:
            data.pop(provider, None)
        self._flush()

    def clear(self, provider=None):
        data = self._load()
        if provider is None:
            self._data = {}
        else:
            data.pop(provider, None)
        self._flush()

    def providers(self):
        return sorted(self._load().keys())

    def public_view(self):
        """What an owner may see: presence and a fingerprint, never a value."""
        out = {}
        for provider, entry in sorted(self._load().items()):
            if not isinstance(entry, dict):
                continue
            secret = entry.get("secret") or ""
            out[provider] = {
                "configured": bool(secret),
                "key_fingerprint": fingerprint(secret),
                "model": entry.get("model") or None,
                "timeout": entry.get("timeout"),
                "is_real_secret_store": is_real_secret_store,
            }
        return out


# ------------------------------------------------------------- config
class ProviderConfig:
    """Read-only view of the provider configuration for one send.

    Constructed from the store, never from a request. Adapters are built from
    this, so the only way a key reaches an adapter is through here.

    `fallback_enabled` is the owner-facing switch from APP_SPEC 9.3. It is False
    by default: a provider is not dialled at all until the owner both registers
    a key and turns the fallback on. Disabling it means the Gemini adapter is not
    built, so a Muse failure leaves the turn waiting rather than being routed
    somewhere the owner switched off.
    """

    SETTINGS_PROVIDER = "__settings__"

    def __init__(self, store=None, *, muse_enabled=True, gemini_enabled=True):
        self.store = store if store is not None else SecretStore()
        self.muse_enabled = bool(muse_enabled)
        self.gemini_enabled = bool(gemini_enabled)

    @property
    def fallback_enabled(self):
        return str(self.store.get(self.SETTINGS_PROVIDER,
                                  "fallback_enabled") or "").strip() in (
            "1", "true", "on", "yes")

    # -- available models and the project tier -------------------------
    #
    # IMPLEMENTATION_CONTRACT 7.1.1. Three separate facts, kept separate on
    # purpose, because conflating any two of them is the mistake the contract
    # warns about:
    #
    #   * the list of models the provider currently offers (fetched, not coded)
    #   * whether a given model is free-supported (per entry, may be unknown)
    #   * whether *this project* is on a free tier (checked in AI Studio)
    #
    # A successful list fetch does not imply the second, and neither implies the
    # third. A model is selectable only when the second is confirmed true, and
    # the whole thing reports `setting-required` until the third is recorded.
    def catalog(self, provider="gemini"):
        """The fetched model list. Empty when never fetched."""
        import json as _json

        raw = self.store.get(provider, "model_catalog")
        if not raw:
            return []
        try:
            parsed = _json.loads(raw)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []

    def catalog_fetched_at(self, provider="gemini"):
        return self.store.get(provider, "model_catalog_at") or None

    def selectable_models(self, provider="gemini"):
        """Only models whose free support is confirmed.

        `free_supported` of None is excluded: the provider did not say, and an
        unknown is not a yes.
        """
        return [entry for entry in self.catalog(provider)
                if entry.get("free_supported") is True]

    def model_is_selectable(self, provider, model_id):
        if not model_id:
            return False
        return any(entry["model_id"] == model_id
                   for entry in self.selectable_models(provider))

    def record_model_catalog(self, provider, entries, *, fetched_at):
        """Store a fetched list. `fetched_at` is when the server read it."""
        import json as _json

        if not isinstance(entries, list):
            raise ConfigError("INVALID_VALUE", "모델 목록 형식이 달라요")
        if not str(fetched_at or "").strip():
            raise ConfigError("INVALID_VALUE", "조회 시점이 필요해요")
        clean = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id") or "").strip()
            if not model_id:
                continue
            free = entry.get("free_supported")
            clean.append({
                "model_id": model_id,
                "display_name": str(entry.get("display_name") or model_id),
                "free_supported": free if isinstance(free, bool) else None,
            })
        self.store.set(provider, "model_catalog", _json.dumps(
            clean, ensure_ascii=False, sort_keys=True))
        self.store.set(provider, "model_catalog_at", str(fetched_at))
        return clean

    # -- project tier --------------------------------------------------
    def tier_state(self):
        """`verified`, `setting-required`, or `unknown`.

        `setting-required` is the state the contract asks for when the project
        tier has not been confirmed: the app keeps working but will not let the
        owner pick a paid model on the strength of a working key.
        """
        tier = str(self.store.get(self.SETTINGS_PROVIDER,
                                  "tier") or "").strip()
        verified_at = str(self.store.get(self.SETTINGS_PROVIDER,
                                         "tier_verified_at") or "").strip()
        if not tier and not verified_at:
            return "unknown"
        if tier != "free" or not verified_at:
            return "setting-required"
        return "verified"

    def tier_record(self):
        return {
            "state": self.tier_state(),
            "tier": self.store.get(self.SETTINGS_PROVIDER, "tier") or None,
            "verified_at": self.store.get(self.SETTINGS_PROVIDER,
                                          "tier_verified_at") or None,
            "checked_in": "Google AI Studio 프로젝트",
            "app_guarantees_free_billing": False,
        }

    def record_tier_verification(self, *, tier, verified_at):
        """Record what the owner saw in AI Studio, and when.

        This is a manual record of an *external* observation, not a check the app
        performs. It deliberately never claims to guarantee free billing: the
        contract is explicit that a working key does not promise that billing
        settings will not change later.

        The role check lives on `ProviderConfigService`, which is the only
        caller; this method is the storage half.
        """
        value = str(tier or "").strip().lower()
        if value not in ("free", "paid", "unknown"):
            raise ConfigError("INVALID_VALUE", "등급 값이 달라요")
        if not str(verified_at or "").strip():
            raise ConfigError("INVALID_VALUE", "확인 시점이 필요해요")
        self.store.set(ProviderConfig.SETTINGS_PROVIDER, "tier", value)
        self.store.set(ProviderConfig.SETTINGS_PROVIDER, "tier_verified_at",
                       str(verified_at))
        return self.tier_record()

    # -- reads ---------------------------------------------------------
    def secret_for(self, provider):
        """The stored key for one provider, for a server-side caller.

        Public so that the connection test and the catalog fetch read the key
        through one named door instead of reaching into a private helper.
        """
        return self._secret(provider)

    def _secret(self, provider):
        return self.store.get(provider, "secret")

    def _model(self, provider, default=""):
        """The owner's selected model, or empty when none was selected.

        There is deliberately no built-in default model name. The contract
        forbids hardcoding one and forbids paying for an unconfirmed model, so a
        provider with no selection has no model and reports `not_configured`
        rather than calling something nobody chose.
        """
        return self.store.get(provider, "model") or default

    def _timeout(self, provider, default=DEFAULT_TIMEOUT):
        try:
            return _validate_timeout(self.store.get(provider, "timeout") or default)
        except ConfigError:
            return default

    @property
    def muse_secret(self):
        return self._secret("muse")

    @property
    def muse_model(self):
        return self._model("muse")

    @property
    def muse_timeout(self):
        return self._timeout("muse")

    @property
    def gemini_secret(self):
        return self._secret("gemini")

    @property
    def gemini_model(self):
        return self._model("gemini")

    @property
    def gemini_timeout(self):
        return self._timeout("gemini")

    @property
    def muse_configured(self):
        return self.muse_enabled and bool(self.muse_secret) \
            and bool(self.muse_model)

    @property
    def gemini_configured(self):
        return self.gemini_enabled and bool(self.gemini_secret) \
            and bool(self.gemini_model)

    def public_view(self):
        return {
            "muse": {
                "enabled": self.muse_enabled,
                # Three separate facts, reported separately. Collapsing them into
                # one "configured" flag would hide which one is missing.
                "has_key": bool(self.muse_secret),
                "model": self.muse_model,
                "has_model": bool(self.muse_model),
                "configured": self.muse_configured,
                "key_fingerprint": fingerprint(self.muse_secret),
                "timeout": self.muse_timeout,
                "models": self.catalog("muse"),
                "models_fetched_at": self.catalog_fetched_at("muse"),
                "selectable_models": [
                    entry["model_id"] for entry in self.selectable_models("muse")],
            },
            "gemini": {
                "enabled": self.gemini_enabled,
                "has_key": bool(self.gemini_secret),
                "model": self.gemini_model,
                "has_model": bool(self.gemini_model),
                "configured": self.gemini_configured,
                "key_fingerprint": fingerprint(self.gemini_secret),
                "timeout": self.gemini_timeout,
                "models": self.catalog("gemini"),
                "models_fetched_at": self.catalog_fetched_at("gemini"),
                "selectable_models": [
                    entry["model_id"] for entry in
                    self.selectable_models("gemini")],
            },
            "fallback_enabled": self.fallback_enabled,
            "tier": self.tier_record(),
            "is_real_secret_store": is_real_secret_store,
        }


class ProviderConfigService:
    """The owner-facing write path for provider configuration.

    Every method takes the acting role and refuses a non-owner before touching
    the store, so a viewer cannot register a key even by guessing a path. The
    returned payload is always the public view, so a successful write never
    echoes the value back.
    """

    ALLOWED_PROVIDERS = ("muse", "gemini")
    ALLOWED_FIELDS = ("secret", "model", "timeout")

    def __init__(self, store=None):
        self.store = store if store is not None else SecretStore()
        self.config = ProviderConfig(self.store)
        self.audit = []

    def _require_owner(self, role):
        if role != "owner":
            raise ConfigError("ACTION_FORBIDDEN", "owner만 설정할 수 있어요")

    def _require_provider(self, provider):
        if provider not in self.ALLOWED_PROVIDERS:
            # Not naming the allowed set keeps the refusal cheap to probe but
            # still explicit.
            raise ConfigError("INVALID_VALUE", "알 수 없는 제공자예요")

    def set_provider(self, *, role, provider, secret=None, model=None,
                     timeout=None, client_request_id=""):
        self._require_owner(role)
        self._require_provider(provider)
        fields = {}
        if secret is not None:
            fields["secret"] = _validate_secret(secret, "키")
        if model is not None:
            # A model must come from the fetched list and be free-confirmed. A
            # free-text model name is refused, because the contract forbids
            # hardcoding a model name and forbids paying for one.
            if not self.config.model_is_selectable(provider, str(model).strip()):
                raise ConfigError(
                    "MODEL_NOT_SELECTABLE",
                    "서버에서 조회한 무료 지원 모델 중에서만 고를 수 있어요")
            fields["model"] = _validate_model(model, "모델 이름")
        if timeout is not None:
            fields["timeout"] = _validate_timeout(timeout)
        if not fields:
            raise ConfigError("INVALID_VALUE", "바꿀 항목이 없어요")
        for field, value in fields.items():
            self.store.set(provider, field, value)
        self.audit.append({
            "provider": provider,
            "fields": sorted(fields),
            "role": role,
            "request_id": str(client_request_id or ""),
        })
        # The secret is not in the audit, and the reply is the public view.
        return self.status(role=role)

    def refresh_model_catalog(self, *, role, provider, transport,
                              fetched_at):
        """Read the provider's available list and store it with its fetch time.

        Owner-gated, because a list fetch spends a request against the owner's
        key. A fetch failure is reported as such; it never replaces the stored
        list with an empty one, because "the list is empty" and "we could not
        read the list" lead the owner to different conclusions.
        """
        self._require_owner(role)
        self._require_provider(provider)
        from . import provider_transport as pt

        try:
            entries = pt.fetch_model_catalog(
                transport=transport, secret=self.config.secret_for(provider),
                provider=provider)
        except pt.ModelFetchError as exc:
            raise ConfigError("MODEL_LIST_UNAVAILABLE",
                              f"모델 목록을 읽지 못했어요 ({exc.reason})")
        self.config.record_model_catalog(provider, entries, fetched_at=fetched_at)
        self.audit.append({"provider": provider, "fields": ["model_catalog"],
                           "role": role, "count": len(entries)})
        return {"provider": provider, "count": len(entries),
                "fetched_at": fetched_at,
                "selectable": [e["model_id"] for e in
                               self.config.selectable_models(provider)],
                "tier": self.config.tier_record()}

    def run_connection_test(self, *, role, provider, muse=None, gemini=None):
        """Send one short synthetic request and report success and model id.

        Owner-gated. The request carries a fixed sentence and no ledger data, so
        a key is never tried against a real card or a customer record. The reply
        holds only whether it worked, the actual model id, and a reason code; it
        never holds the key, and it never claims to be a real call in this build.
        """
        self._require_owner(role)
        self._require_provider(provider)
        from . import provider_transport as pt

        adapter = muse if provider == "muse" else gemini
        if adapter is None:
            # The provider is not wired. Build one from the stored key so the
            # test can still say why it could not run.
            config = self.config
            if provider == "muse" and not config.muse_configured:
                adapter = pt.MuseAdapter(secret=config.muse_secret)
            elif provider == "gemini" and not config.gemini_configured:
                adapter = pt.GeminiAdapter(secret=config.gemini_secret,
                                           model_id=config.gemini_model)
        result = pt.connection_test(adapter)
        self.audit.append({"provider": provider, "fields": ["connection_test"],
                           "role": role, "ok": bool(result.get("ok"))})
        return result

    def record_tier_verification(self, *, role, tier, verified_at,
                                 client_request_id=""):
        self._require_owner(role)
        record = self.config.record_tier_verification(
            tier=tier, verified_at=verified_at)
        self.audit.append({"provider": "gemini", "fields": ["tier"],
                           "role": role,
                           "request_id": str(client_request_id or "")})
        return record

    def set_fallback(self, *, role, enabled, client_request_id=""):
        """Turn the configured Gemini fallback on or off (APP_SPEC 9.3).

        Off by default. Turning it off is a real behaviour change and not only a
        display preference: with the switch off no Gemini adapter is built, so a
        Muse failure leaves the turn waiting instead of calling a provider the
        owner switched off.
        """
        self._require_owner(role)
        if not isinstance(enabled, bool):
            raise ConfigError("INVALID_VALUE", "fallback 설정 형식이 달라요")
        self.store.set(ProviderConfig.SETTINGS_PROVIDER, "fallback_enabled",
                       "1" if enabled else "0")
        self.audit.append({"provider": "gemini", "fields": ["fallback_enabled"],
                           "role": role,
                           "request_id": str(client_request_id or "")})
        return self.status(role=role)

    def clear_provider(self, *, role, provider, client_request_id=""):
        self._require_owner(role)
        self._require_provider(provider)
        self.store.clear(provider)
        self.audit.append({"provider": provider, "fields": ["*"], "role": role,
                           "request_id": str(client_request_id or "")})
        return self.status(role=role)

    def status(self, *, role):
        self._require_owner(role)
        return self.public_status()

    def public_status(self):
        """Readable without a role, because it holds no secret value.

        The owner gate stays on `status` so a viewer still cannot reach the
        configuration surface at all; this method is for the server side and
        for the turn record.
        """
        view = self.config.public_view()
        view["is_real_secret_store"] = is_real_secret_store
        view["store_path"] = os.path.basename(self.store.path)
        return view


__all__ = [
    "ConfigError", "ProviderConfig", "ProviderConfigService", "SecretStore",
    "fingerprint", "redact", "is_real_secret_store", "STORE_ENV",
    "MIN_SECRET_LENGTH", "MAX_SECRET_LENGTH",
]
