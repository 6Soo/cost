"""버전 관리되는 OTA 대조 기본 설정을 읽는다."""

from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def load_defaults():
    path = Path(__file__).resolve().parents[1] / "config" / "ota-matching-defaults.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "ota-matching-defaults-v1":
        raise ValueError("OTA_MATCHING_DEFAULTS_SCHEMA_INVALID")
    return value


def provider_for_merchant(merchant):
    """Resolve a merchant descriptor through the shared, versioned OTA aliases."""
    value = str(merchant or "").casefold()
    if not value:
        return None
    defaults = load_defaults()
    aliases = []
    for provider, candidates in defaults.get("provider_merchant_aliases", {}).items():
        aliases.extend((str(alias), provider) for alias in candidates)
    for provider, records in defaults.get("provider_merchant_alias_records", {}).items():
        aliases.extend((str(item.get("alias") or ""), provider) for item in records
                       if item.get("status") == "approved" and item.get("version") and item.get("source"))
    for alias, provider in sorted(aliases, key=lambda pair: len(pair[0]), reverse=True):
        if alias and alias.casefold() in value:
            return provider
    return None
