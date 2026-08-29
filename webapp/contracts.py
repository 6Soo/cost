from __future__ import annotations

import hashlib
import json
import math


LEDGER_DOMAIN = b"cost-operator-ledger-v1"
LEDGER_SCHEMA_VERSION = 1
AXES_SCHEMA_VERSION = "axes-v1"
GENESIS_HASH = "GENESIS"

COST_TYPES = ("여행원가", "판관비")
ACTIONS = (
    "propose",
    "shadow_review_confirmed",
    "correct",
    "reject",
    "withdraw",
    "attach_evidence",
)
CHAINING_ACTIONS = (
    "shadow_review_confirmed",
    "correct",
    "reject",
    "withdraw",
    "attach_evidence",
)
TERMINAL_ACTIONS = ("reject", "withdraw")
EXCLUDED_AXES = ("vat_tag",)


class ContractError(ValueError):
    pass


class AxesError(ContractError):
    pass


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_text(obj) -> str:
    return canonical_bytes(obj).decode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def domain_event_hash(payload: dict) -> str:
    digest = hashlib.sha256()
    digest.update(LEDGER_DOMAIN)
    digest.update(b"\x00")
    digest.update(canonical_bytes(payload))
    return digest.hexdigest()


def validate_axes(axes) -> None:
    if not isinstance(axes, dict):
        raise AxesError("axes must be an object")
    allowed = {"account", "cost_type", "allocation_target", "vat_tag"}
    unknown = sorted(set(axes) - allowed)
    if unknown:
        raise AxesError(f"unknown axes fields: {unknown}")
    account = axes.get("account")
    if not isinstance(account, str) or not account.strip():
        raise AxesError("account must be a non-empty string")
    cost_type = axes.get("cost_type")
    if cost_type not in COST_TYPES:
        raise AxesError(f"cost_type must be one of {COST_TYPES}")
    target = axes.get("allocation_target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise AxesError("allocation_target must be a non-empty string or null")
    vat = axes.get("vat_tag")
    if vat is not None and (not isinstance(vat, str) or not vat.strip()):
        raise AxesError("vat_tag must be a non-empty string or null")


def normalize_amount(value) -> int:
    if isinstance(value, bool) or value is None:
        raise ContractError("amount must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ContractError("amount must be finite")
    rounded = round(number)
    if abs(number - rounded) > 1e-6:
        raise ContractError("amount must be an integer KRW value")
    return int(rounded)
