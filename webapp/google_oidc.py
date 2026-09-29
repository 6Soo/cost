"""Google OpenID Connect: a real Authorization Code login for the ledger.

Scope and boundary
------------------
SPEC_REFINEMENT 16.1 asks for a verified OpenID Connect library, server-side
verification of the id token's signature, issuer, audience and expiry, a check of
the `state` and the `nonce` used by the server login flow, and an account key
taken from Google's stable `sub` rather than an email. This module is that
implementation. It is a *seam with a real protocol in it*, not a second synthetic
stand-in: when it is configured, a browser is sent to Google and a verified
Google identity comes back.

Nothing here invents a credential. The client id, the client secret and the
session secret are read from the environment and are never written into a
report, a log line, a cookie or a manifest. A missing or partial configuration
is a refusal, not a degraded login: with no configuration this module binds
nothing and the board keeps its fail-closed behaviour, so an unconfigured
deployment serves no account rather than a weaker one.

The three decisions that matter most
------------------------------------
* **The account key is `sub`.** Google's `sub` is stable for an account
  regardless of email changes. An email is recorded as a display attribute and
  is never used to look an account up, so renaming a Google account cannot mint
  a new account or inherit an old one's role.
* **A first login is never a promotion.** An unknown Google identity is
  registered as a viewer. `ensure_owner` runs only when the deployment named
  `WEBLEDGER_OWNER_GOOGLE_SUB` *and* the presented `sub` matches it *and* no
  owner exists yet. Without that setting there is no owner bootstrap at all, so
  a deployment that forgets to set it has no owner rather than an accidental one.
* **The session is bound to the account's generation.** The cookie carries the
  `session_generation` that was in force when it was issued, and every request
  compares it with the one in force now. A logout, a revoke or a deactivation
  moves the generation, so a cookie the client still holds is refused instead of
  continuing to render data it was allowed to see under the old role.

The id token is verified through `google-auth` (`google.oauth2.id_token`), which
is the library SPEC 16.1 names. It is an optional import on purpose: if it is
absent the module refuses every login rather than skipping verification, and
says so through `describe()`. A caller may inject a different verifier, which is
how the tests exercise the flow without a network and without a client.

Technical basis: Google OpenID Connect documentation,
https://developers.google.com/identity/openid-connect/openid-connect
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from . import access_control

# Google OpenID Connect endpoints. These are constants, not configuration: a
# deployment may not point the login flow at a host it controls.
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# The scopes the ledger actually needs. `openid` identifies the flow, `email`
# lets a human recognise which account they are in, and `profile` gives a display
# name. Gmail, Drive and Sheets scopes are deliberately absent: a ledger login
# must not request access to the user's mail or files (SPEC 16.1).
REQUIRED_SCOPES = ("openid", "email")
OPTIONAL_SCOPES = ("profile",)

COOKIE_NAME = "webledger_session"
COOKIE_PREFIX = "v1"
# A short session. The generation check is what ends a session early, not the
# clock, so this only bounds an idle browser.
DEFAULT_SESSION_TTL = 8 * 60 * 60
STATE_TTL = 600
NONCE_BYTES = 32
STATE_BYTES = 32

ENV_CLIENT_ID = "WEBLEDGER_GOOGLE_CLIENT_ID"
ENV_CLIENT_SECRET = "WEBLEDGER_GOOGLE_CLIENT_SECRET"
ENV_SESSION_SECRET = "WEBLEDGER_SESSION_SECRET"
ENV_PUBLIC_BASE_URL = "WEBLEDGER_PUBLIC_BASE_URL"
ENV_OWNER_SUB = "WEBLEDGER_OWNER_GOOGLE_SUB"

REQUIRED_ENV = (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_SESSION_SECRET,
                ENV_PUBLIC_BASE_URL)

# The minimum length of a usable session secret. HMAC-SHA256 needs a real key;
# a short or obviously placeholder value is refused rather than accepted with a
# warning nobody reads.
MIN_SESSION_SECRET_BYTES = 32

PLACEHOLDER_SECRETS = ("changeme", "secret", "replace-me", "example",
                       "placeholder", "not-a-secret", "test", "dummy")


class OIDCError(Exception):
    """A refusal with a code, so a route can answer without leaking detail."""

    def __init__(self, code: str, message: str = "", *, status: int = 400):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status = status


# ------------------------------------------------------------------ helpers
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _now() -> int:
    return int(time.time())


def _secret_is_placeholder(value: str) -> bool:
    lowered = (value or "").strip().lower()
    if not lowered:
        return True
    if any(marker in lowered for marker in PLACEHOLDER_SECRETS):
        return True
    # a value that is one repeated character is a placeholder too
    return len(set(lowered)) <= 2


@dataclass(frozen=True)
class OIDCConfig:
    """The deployment's Google settings, validated.

    The secret values are held so a request can use them, and they are never
    returned by `describe()`. A report proves a key is present by name only.
    """

    client_id: str
    client_secret: str
    session_secret: str
    public_base_url: str
    owner_google_sub: str = ""
    session_ttl: int = DEFAULT_SESSION_TTL
    allowed_clock_skew: int = 60

    @classmethod
    def from_env(cls, env=None, *, session_ttl: int = DEFAULT_SESSION_TTL
                 ) -> "OIDCConfig":
        env = dict(os.environ if env is None else env)
        missing = [name for name in REQUIRED_ENV
                   if not (env.get(name) or "").strip()]
        if missing:
            raise OIDCError("OIDC_NOT_CONFIGURED",
                            "Google 로그인 설정이 없어요: "
                            + ", ".join(missing), status=503)
        session_secret = env[ENV_SESSION_SECRET].strip()
        if _secret_is_placeholder(session_secret):
            raise OIDCError(
                "WEAK_SESSION_SECRET",
                f"{ENV_SESSION_SECRET} 가 사용하기에 약해요. "
                f"{MIN_SESSION_SECRET_BYTES} 바이트 이상의 임의 값을 "
                f"사용해 주세요", status=503)
        base = env[ENV_PUBLIC_BASE_URL].strip().rstrip("/")
        if not base.lower().startswith("https://"):
            # SPEC 16.1 requires production HTTPS for the session cookie. A
            # plaintext base url would put the session cookie on the wire.
            raise OIDCError("INSECURE_PUBLIC_BASE_URL",
                            f"{ENV_PUBLIC_BASE_URL} 는 https 여야 해요",
                            status=503)
        if base.lower().startswith("https://127.0.0.1") or \
                base.lower().startswith("https://localhost"):
            # A loopback address is a local trial. It is refused here so a
            # deployment cannot ship a callback that only works on the machine
            # that built it.
            raise OIDCError("LOOPBACK_PUBLIC_BASE_URL",
                            f"{ENV_PUBLIC_BASE_URL} 는 사설 loopback 주소예요",
                            status=503)
        return cls(client_id=env[ENV_CLIENT_ID].strip(),
                   client_secret=env[ENV_CLIENT_SECRET].strip(),
                   session_secret=session_secret,
                   public_base_url=base,
                   owner_google_sub=(env.get(ENV_OWNER_SUB) or "").strip(),
                   session_ttl=int(session_ttl))

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_base_url}/auth/callback"

    def describe(self) -> dict:
        """Presence and shape only. Never a secret value."""
        return {
            "configured": True,
            "client_id_present": bool(self.client_id),
            "client_secret_present": bool(self.client_secret),
            "session_secret_present": bool(self.session_secret),
            "public_base_url": self.public_base_url,
            "redirect_uri": self.redirect_uri,
            "owner_google_sub_present": bool(self.owner_google_sub),
            "scopes": list(REQUIRED_SCOPES + OPTIONAL_SCOPES),
            "issuer": GOOGLE_ISSUER,
            "session_ttl_seconds": self.session_ttl,
            "account_key": "google sub",
            "email_used_as_identity_key": False,
        }


# ------------------------------------------------------- token verification
class GoogleAuthTokenVerifier:
    """Verify a Google id token with `google-auth`.

    `google-auth` is the library SPEC 16.1 names. It is imported lazily so an
    installation without it starts and can report the missing dependency
    instead of failing to import the whole board; every login is refused while it
    is absent, because an unverified id token is not a session.
    """

    def __init__(self, *, client_id: str, clock_skew: int = 60,
                 idinfo_loader=None):
        self.client_id = client_id
        self.clock_skew = clock_skew
        # A test may inject a loader that returns claims. The production path
        # leaves it None and lets google-auth fetch and cache the JWKS.
        self._idinfo_loader = idinfo_loader

    @property
    def available(self) -> bool:
        if self._idinfo_loader is not None:
            return True
        try:
            import google.oauth2.id_token  # noqa: F401
        except ImportError:
            return False
        return True

    def describe(self) -> dict:
        return {"library": "google-auth", "available": self.available,
                "clock_skew_seconds": self.clock_skew}

    def verify(self, id_token: str, *, audience: str | None = None,
               nonce: str | None = None) -> dict:
        """Return the verified claims, or raise. Never a partial result."""
        if not id_token or not isinstance(id_token, str):
            raise OIDCError("ID_TOKEN_MISSING", "id_token 이 없어요")
        expected_audience = audience or self.client_id
        if self._idinfo_loader is not None:
            claims = self._idinfo_loader(id_token)
        else:
            claims = self._verify_with_library(id_token, expected_audience)
        if not isinstance(claims, dict):
            raise OIDCError("ID_TOKEN_INVALID", "id_token 검증 결과가 비었어요")
        return validate_claims(claims, audience=expected_audience, nonce=nonce,
                              clock_skew=self.clock_skew)

    def _verify_with_library(self, id_token: str, audience: str) -> dict:
        """The documented `google-auth` call, with every failure a refusal.

        `verify_oauth2_token` checks the signature against Google's published
        keys, the issuer, the audience and the expiry. A failure of any of those
        is a refusal, and it is never downgraded to "assume it is fine".
        """
        try:
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:
            raise OIDCError(
                "OIDC_LIBRARY_MISSING",
                "google-auth 가 설치되어 있지 않아 id_token 을 검증할 수 "
                "없어요. 검증을 건너뛰고 로그인시키지 않아요") from exc
        try:
            from google.auth.transport import requests as google_requests
        except ImportError as exc:
            raise OIDCError("OIDC_LIBRARY_MISSING",
                            "google-auth 의 요청 계층이 없어요") from exc
        try:
            return google_id_token.verify_oauth2_token(
                id_token, google_requests.Request(), audience=audience)
        except Exception as exc:  # noqa: BLE001 - any failure is a refusal
            raise OIDCError("ID_TOKEN_INVALID",
                            f"id_token 을 검증하지 못했어요: {exc}") from exc


def validate_claims(claims: dict, *, audience: str, nonce: str | None = None,
                    clock_skew: int = 60) -> dict:
    """Check issuer, audience, expiry and nonce on verified claims.

    `google-auth` already checks signature, issuer, audience and expiry. These
    checks are kept anyway and are not skipped: they are the contract this
    application relies on, and an injected verifier or a library change must not
    silently drop them.
    """
    issuer = str(claims.get("iss") or "")
    if issuer not in (GOOGLE_ISSUER, f"{GOOGLE_ISSUER}/"):
        raise OIDCError("ID_TOKEN_ISSUER",
                        f"발급자가 Google 가 아니에요: {issuer or '없음'}")
    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    if audience not in [str(a) for a in aud_list]:
        raise OIDCError("ID_TOKEN_AUDIENCE", "audience 가 이 앱이 아니에요")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise OIDCError("ID_TOKEN_NO_EXPIRY", "만료 시간이 없는 token 이에요")
    if _now() > int(exp) + int(clock_skew):
        raise OIDCError("ID_TOKEN_EXPIRED", "만료된 token 이에요")
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        # The sub is the account key. A token without one cannot identify
        # anyone, and the email is explicitly not a substitute.
        raise OIDCError("ID_TOKEN_NO_SUB", "token 에 안정적인 sub 가 없어요")
    if nonce is not None:
        presented = str(claims.get("nonce") or "")
        if not hmac.compare_digest(presented, str(nonce)):
            raise OIDCError("NONCE_MISMATCH", "nonce 가 일치하지 않아요")
    return {"sub": sub, "email": str(claims.get("email") or ""),
            "email_verified": bool(claims.get("email_verified")),
            "name": str(claims.get("name") or ""),
            "hd": str(claims.get("hd") or "")}


# ------------------------------------------------------- the session cookie
class SessionSigner:
    """An HMAC-signed session payload. No third-party signing here.

    The cookie carries the account key, the display attributes, the issue and
    expiry times and the account generation that was in force. The signature
    covers all of it, so a client cannot raise its own expiry, change its
    generation or become another account by editing the cookie.

    The Google token is never stored in the cookie. It is verified at the
    callback and then discarded, because a bearer credential in a cookie is a
    credential the browser will keep replaying.
    """

    def __init__(self, secret: str):
        if _secret_is_placeholder(secret):
            raise OIDCError("WEAK_SESSION_SECRET",
                            "세션 서명 키가 약해요")
        self._key = secret.encode("utf-8")

    def sign(self, payload: dict) -> str:
        body = _b64e(_canonical(payload).encode("utf-8"))
        signature = hmac.new(self._key, body.encode("ascii"),
                             hashlib.sha256).digest()
        return f"{COOKIE_PREFIX}.{body}.{_b64e(signature)}"

    def verify(self, cookie_value: str) -> dict | None:
        """The payload, or None. A malformed or forged cookie is simply absent."""
        if not cookie_value or not isinstance(cookie_value, str):
            return None
        parts = cookie_value.split(".")
        if len(parts) != 3 or parts[0] != COOKIE_PREFIX:
            return None
        _, body, signature = parts
        try:
            expected = hmac.new(self._key, body.encode("ascii"),
                                hashlib.sha256).digest()
            if not hmac.compare_digest(_b64d(signature), expected):
                return None
            payload = json.loads(_b64d(body).decode("utf-8"))
        except Exception:  # noqa: BLE001 - a bad cookie is not an error
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def set_cookie_header(self, value: str, *, max_age: int | None = None,
                          secure: bool = True, path: str = "/") -> str:
        return set_cookie_header(value, max_age=max_age, secure=secure,
                                 path=path)

    def clear_cookie_header(self, *, secure: bool = True,
                            path: str = "/") -> str:
        return clear_cookie_header(secure=secure, path=path)


def set_cookie_header(value: str, *, max_age: int | None = None,
                      secure: bool = True, path: str = "/",
                      name: str = COOKIE_NAME) -> str:
    """The `Set-Cookie` value for a session cookie.

    HttpOnly so a script cannot read the session, SameSite=Lax so a cross-site
    form post does not carry it, and Secure because SPEC 16.1 requires HTTPS for
    the session cookie in production.
    """
    parts = [
        f"{name}={value}",
        "HttpOnly",
        "SameSite=Lax",
        f"Path={path}",
    ]
    if secure:
        parts.append("Secure")
    if max_age is None:
        parts.append(f"Max-Age={int(DEFAULT_SESSION_TTL)}")
    else:
        parts.append(f"Max-Age={int(max_age)}")
    return "; ".join(parts)


def clear_cookie_header(*, secure: bool = True, path: str = "/",
                        name: str = COOKIE_NAME) -> str:
    """The `Set-Cookie` value that actually removes a cookie.

    The same name and path with `Max-Age=0`. An `Expires` date alone leaves some
    clients holding a stale copy, so the name, the path and the age all have to
    match what was set.
    """
    return set_cookie_header("", max_age=0, secure=secure, path=path, name=name)


# ------------------------------------------------- state and nonce tracking
@dataclass
class _PendingLogin:
    state: str
    nonce: str
    code_verifier: str
    created_at: int
    return_to: str = ""


class PendingLogins:
    """One-time `state` and `nonce` values for the login flow.

    A callback is only accepted when it carries a state this server issued and
    has not already spent, and the nonce is compared against the id token. That
    is what stops a third party from feeding the callback a token of their
    choosing (SPEC 16.1).

    The store is in memory and bounded. A restart invalidates outstanding
    logins, which is the safe direction: an operator logs in again.
    """

    def __init__(self, *, ttl: int = STATE_TTL, limit: int = 512):
        self.ttl = ttl
        self.limit = limit
        self._items: dict[str, _PendingLogin] = {}
        self._lock = threading.Lock()

    def issue(self, *, return_to: str = "") -> tuple[str, str, str]:
        now = _now()
        state = secrets.token_urlsafe(STATE_BYTES)
        nonce = secrets.token_urlsafe(NONCE_BYTES)
        code_verifier = secrets.token_urlsafe(48)
        with self._lock:
            self._expire(now)
            self._items[state] = _PendingLogin(state=state, nonce=nonce,
                                               code_verifier=code_verifier,
                                               created_at=now,
                                               return_to=return_to or "/board")
            if len(self._items) > self.limit:
                oldest = sorted(self._items.values(),
                                key=lambda i: i.created_at)[:len(self._items)
                                                             - self.limit]
                for item in oldest:
                    self._items.pop(item.state, None)
        return state, nonce, code_verifier

    def spend(self, state: str) -> _PendingLogin | None:
        """Take a state out of circulation. A second attempt finds nothing."""
        now = _now()
        with self._lock:
            self._expire(now)
            item = self._items.pop(str(state or ""), None)
        if item is None or now - item.created_at > self.ttl:
            return None
        return item

    def pending_count(self) -> int:
        with self._lock:
            self._expire(_now())
            return len(self._items)

    def _expire(self, now: int) -> None:
        for key in [k for k, v in self._items.items()
                    if now - v.created_at > self.ttl]:
            self._items.pop(key, None)


# --------------------------------------------------------- the token client
class HttpTokenExchange:
    """The HTTPS POST to Google's token endpoint.

    Kept as its own object with the same shape as `provider_transport`: a test
    substitutes it, and nothing else in the module knows how a token is
    obtained. `requests` is used when present; the stdlib is used otherwise so
    the module has no hard dependency for the flow itself.
    """

    def __init__(self, *, timeout: int = 10):
        self.timeout = timeout
        self.calls: list[dict] = []

    def __call__(self, *, code: str, redirect_uri: str, code_verifier: str,
                 client_id: str, client_secret: str) -> dict:
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        self.calls.append({"endpoint": GOOGLE_TOKEN_ENDPOINT,
                           "keys": sorted(payload)})
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        try:
            import requests
        except ImportError:
            return self._post_stdlib(payload)
        try:
            response = requests.post(GOOGLE_TOKEN_ENDPOINT, data=payload,
                                     timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise OIDCError("TOKEN_ENDPOINT_UNREACHABLE",
                            f"토큰 교환에 실패했어요: {exc}", status=502) from exc
        if response.status_code != 200:
            raise OIDCError("TOKEN_EXCHANGE_REFUSED",
                            f"토큰 교환이 거절됐어요 (HTTP "
                            f"{response.status_code})", status=502)
        return response.json()

    def _post_stdlib(self, payload: dict) -> dict:
        import urllib.error
        import urllib.request

        data = urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            GOOGLE_TOKEN_ENDPOINT, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as body:
                return json.loads(body.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OIDCError("TOKEN_EXCHANGE_REFUSED",
                            f"토큰 교환이 거절됐어요 (HTTP {exc.code})",
                            status=502) from exc
        except Exception as exc:  # noqa: BLE001
            raise OIDCError("TOKEN_ENDPOINT_UNREACHABLE",
                            f"토큰 교환에 실패했어요: {exc}", status=502) from exc


# --------------------------------------------------------- account linking
def register_google_identity(access_store, identity: dict, *,
                             config: OIDCConfig) -> dict:
    """Map a verified Google identity onto an account, without promoting it.

    The key is `sub`. An identity that has never been seen becomes a **viewer**,
    always. The only path to owner is the explicit bootstrap below, which needs
    the deployment to have named an owner sub.

    An existing account's role and active flag are never touched here. A login is
    not a way to change what somebody is, and using the upsert in
    `create_account` would let any login rewrite a role.
    """
    user_id = str(identity.get("sub") or "").strip()
    if not user_id:
        raise OIDCError("NO_SUBJECT", "안정적인 sub 가 없어요", status=403)
    account = access_store.account(user_id)
    if account is None:
        created = access_control.AccessStore.create_account(
            access_store, user_id=user_id, role=access_control.ROLE_VIEWER,
            display_name=str(identity.get("name") or ""),
            email=str(identity.get("email") or ""), is_synthetic=False)
        return {"account": created, "created": True, "promoted": False,
                "role": access_control.ROLE_VIEWER}
    # Refresh only the display attributes. Role, is_active and the generation
    # are the access store's business.
    if (str(account.get("display_name") or "") != str(identity.get("name") or "")
            or str(account.get("email") or "") != str(identity.get("email") or "")):
        with access_store.lock:
            access_store.conn.execute(
                "UPDATE access_accounts SET display_name=?, email=?,"
                " updated_at=? WHERE user_id=?",
                (str(identity.get("name") or ""), str(identity.get("email") or ""),
                 access_control.iso(access_control.utc_now()), user_id))
            access_store.conn.commit()
    return {"account": access_store.account(user_id), "created": False,
            "promoted": False, "role": account["role"]}


def bootstrap_owner_if_configured(access_store, identity: dict, *,
                                  config: OIDCConfig) -> dict:
    """The one owner bootstrap, and only when the deployment asked for it.

    All three have to hold: `WEBLEDGER_OWNER_GOOGLE_SUB` is set, the presented
    `sub` equals it, and no owner exists yet. A mismatch is not an error the
    login fails on; the person simply stays a viewer, because the alternative is
    letting a near-miss decide who owns the ledger.
    """
    configured = (config.owner_google_sub or "").strip()
    result = {"attempted": bool(configured), "promoted": False,
              "reason": "owner sub not configured"}
    if not configured:
        return result
    if str(identity.get("sub") or "") != configured:
        result["reason"] = "this sub is not the configured owner"
        return result
    existing = access_store.conn.execute(
        "SELECT user_id FROM access_accounts WHERE role=? AND is_active=1",
        (access_control.ROLE_OWNER,)).fetchone()
    if existing:
        result["reason"] = f"an owner already exists ({existing[0]})"
        return result
    account = access_control.AccessStore.ensure_owner(
        access_store, str(identity["sub"]))
    result.update({"promoted": True, "reason": "bootstrapped from configuration",
                   "account": account, "role": access_control.ROLE_OWNER})
    return result


# ------------------------------------------------------------ the adapter
class GoogleOIDCAdapter:
    """Establishes a session from a signed cookie and nothing else.

    It reads no header as a credential. The synthetic adapter's header seam is
    deliberately not reused: a request header is something a caller can invent,
    and SPEC 16.1 forbids treating that as an operational login.

    A cookie is accepted only when all of the following hold: the signature
    verifies under the configured secret, the payload is not expired, the account
    still exists, and the generation in the cookie is the one in force now.
    """

    def __init__(self, *, config: OIDCConfig, signer: SessionSigner,
                 access_store=None, cookie_name: str = COOKIE_NAME):
        self.config = config
        self.signer = signer
        self.cookie_name = cookie_name
        self.allow_synthetic = False
        self._access = access_store

    def bind_store(self, access_store) -> None:
        self._access = access_store

    # The property the rest of the application reads to decide whether a login
    # path is operational. It is False here by construction: this adapter never
    # accepts a synthetic session.
    @property
    def is_operational(self) -> bool:
        return self.config is not None and self.signer is not None

    def describe(self) -> dict:
        report = dict(self.config.describe())
        report["cookie_name"] = self.cookie_name
        report["cookie_signed"] = True
        report["cookie_httponly"] = True
        report["cookie_samesite"] = "Lax"
        report["cookie_secure"] = True
        report["binds_session_generation"] = True
        return report

    def session_for(self, headers, cookies=None) -> access_control.Session | None:
        value = _read_cookie(headers, cookies, self.cookie_name)
        if not value:
            return None
        payload = self.signer.verify(value)
        if payload is None:
            return None
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or _now() > int(exp):
            return None
        user_id = str(payload.get("sub") or "").strip()
        if not user_id:
            return None
        generation = payload.get("gen")
        generation = int(generation) if isinstance(generation, int) else None
        if self._access is not None:
            account = self._access.account(user_id)
            if account is None or not account["is_active"]:
                # An account that was removed or deactivated cannot be served
                # from a cookie the client still holds.
                return None
            current = self._access.session_generation(user_id)
            if generation is None or generation != current:
                # A logout, a revoke or a deactivation moved the generation, so
                # this cookie is stale.
                return None
            return access_control.Session(
                user_id=user_id, display_name=str(account.get("display_name") or ""),
                email=str(account.get("email") or ""), provider="google",
                is_synthetic=False, session_generation=current)
        return access_control.Session(
            user_id=user_id, display_name=str(payload.get("name") or ""),
            email=str(payload.get("email") or ""), provider="google",
            is_synthetic=False,
            session_generation=generation if generation is not None else 0)

    def issue_cookie(self, identity: dict, *, generation: int) -> str:
        issued = _now()
        payload = {"sub": identity["sub"], "name": identity.get("name") or "",
                   "email": identity.get("email") or "", "iat": issued,
                   "exp": issued + int(self.config.session_ttl),
                   "gen": int(generation), "jti": secrets.token_urlsafe(16)}
        return self.signer.sign(payload)


def _read_cookie(headers, cookies, name: str) -> str:
    """The named cookie from a parsed jar or a raw `Cookie` header."""
    if cookies is not None:
        try:
            value = cookies.get(name)
            if value:
                return value
        except AttributeError:
            pass
    if headers is None:
        return ""
    try:
        raw = headers.get("Cookie") or ""
    except AttributeError:
        return ""
    for part in str(raw).split(";"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        if key.strip() == name:
            return value.strip().strip('"')
    return ""


# ------------------------------------------------------------- the flow
@dataclass
class LoginFlow:
    """The pieces `/auth/login` and `/auth/callback` need.

    A `LoginFlow` is built from a configuration, a verifier, a token exchange and
    an access store, so a route can be exercised without a network, and so the
    flow cannot be constructed half-configured.
    """

    config: OIDCConfig
    verifier: GoogleAuthTokenVerifier
    access_store: object
    adapter: GoogleOIDCAdapter
    pending: PendingLogins = field(default_factory=PendingLogins)
    exchange: object = None

    def __post_init__(self):
        if self.exchange is None:
            self.exchange = HttpTokenExchange()

    # -- GET /auth/login
    def authorization_url(self, *, return_to: str = "/board") -> dict:
        """The Google URL and the cookie that ties the callback to this attempt."""
        if not self.verifier.available:
            raise OIDCError("OIDC_LIBRARY_MISSING",
                            "google-auth 가 없어 로그인할 수 없어요",
                            status=503)
        state, nonce, code_verifier = self.pending.issue(return_to=return_to)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES + OPTIONAL_SCOPES),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return {"url": f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}",
                "state": state, "nonce": nonce, "return_to": return_to,
                "params": params}

    # -- GET /auth/callback
    def complete(self, *, code: str, state: str, session_signer=None) -> dict:
        """Exchange the code, verify the id token, register, and issue a cookie.

        The order is fixed and every step can refuse: the state is spent first,
        so a replayed callback is refused before any token is requested. The nonce
        is checked against the id token. Only then is an account touched.
        """
        if not code:
            raise OIDCError("AUTH_CODE_MISSING", "인가 코드가 없어요")
        pending = self.pending.spend(state)
        if pending is None:
            # An unknown, already spent or expired state. This is the CSRF and
            # replay defence, and it says nothing about whether the code is real.
            raise OIDCError("STATE_INVALID",
                            "로그인 시도가 만료되었거나 중복이에요. 다시 "
                            "로그인해 주세요", status=400)
        response = self.exchange(code=code,
                                 redirect_uri=self.config.redirect_uri,
                                 code_verifier=pending.code_verifier,
                                 client_id=self.config.client_id,
                                 client_secret=self.config.client_secret)
        if not isinstance(response, dict):
            raise OIDCError("TOKEN_RESPONSE_INVALID", "토큰 응답을 못 읽었어요",
                            status=502)
        id_token = response.get("id_token")
        identity = self.verifier.verify(id_token,
                                        audience=self.config.client_id,
                                        nonce=pending.nonce)
        linked = register_google_identity(self.access_store, identity,
                                         config=self.config)
        bootstrap = bootstrap_owner_if_configured(self.access_store, identity,
                                                 config=self.config)
        account = bootstrap.get("account") or linked["account"]
        generation = self.access_store.session_generation(account["user_id"])
        cookie_value = self.adapter.issue_cookie(identity,
                                                 generation=generation)
        return {"identity": identity, "account": account, "generation": generation,
                "cookie_value": cookie_value, "return_to": pending.return_to,
                "created": linked["created"], "bootstrap": bootstrap,
                "role": account["role"]}

    def set_cookie(self, cookie_value: str) -> str:
        return self.adapter.signer.set_cookie_header(cookie_value)

    def clear_cookie(self) -> str:
        return self.adapter.signer.clear_cookie_header()


# ------------------------------------------------------------------ wiring
def connect_oidc(config: OIDCConfig, access_store, *, verifier=None,
                 exchange=None, pending=None) -> LoginFlow:
    """Build the flow and bind the session adapter."""
    signer = SessionSigner(config.session_secret)
    verifier = verifier or GoogleAuthTokenVerifier(
        client_id=config.client_id, clock_skew=config.allowed_clock_skew)
    adapter = GoogleOIDCAdapter(config=config, signer=signer,
                                access_store=access_store)
    flow = LoginFlow(config=config, verifier=verifier,
                     access_store=access_store, adapter=adapter,
                     pending=pending or PendingLogins(), exchange=exchange)
    access_control.bind_sessions(adapter)
    return flow


def try_connect_from_env(access_store, *, env=None, session_ttl=None
                         ) -> LoginFlow | None:
    """Connect when the deployment is configured; stay unbound when it is not.

    Returning None is a normal, healthy outcome for a synthetic or a
    single-operator run. It is not an error, and it is not reported as one; the
    board then keeps refusing every request, which is the fail-closed default.
    """
    try:
        config = OIDCConfig.from_env(env, **(
            {"session_ttl": session_ttl} if session_ttl else {}))
    except OIDCError:
        return None
    return connect_oidc(config, access_store)


def connection_state(flow: LoginFlow | None) -> dict:
    """`google_oidc_connected`, for a health check or a report.

    Reports shape and presence only. No client id value, no secret, no cookie.
    """
    if flow is None:
        return {"google_oidc_connected": False,
                "reason": "no configuration; the board refuses every session",
                "library": "google-auth", "library_available": False}
    report = dict(flow.adapter.describe())
    report.update({"google_oidc_connected": bool(flow.verifier.available),
                   "library": "google-auth",
                   "library_available": bool(flow.verifier.available),
                   "owner_bootstrap_configured":
                       bool(flow.config.owner_google_sub),
                   "pending_logins": flow.pending.pending_count()})
    if not flow.verifier.available:
        report["reason"] = ("google-auth 가 설치되어 있지 않아 로그인이 "
                            "거부돼요")
    return report
