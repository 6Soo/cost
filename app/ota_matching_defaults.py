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
