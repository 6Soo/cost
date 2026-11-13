"""Pure evidence helpers shared by Hana and IBK collection manifests."""
import hashlib


def count_check(parsed_count, screen_count):
    valid = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
    matched = valid(parsed_count) and valid(screen_count) and parsed_count == screen_count
    return {"status": "MATCHED" if matched else "FAILED",
            "parsedCount": parsed_count if valid(parsed_count) else None,
            "screenCount": screen_count if valid(screen_count) else None}


def file_evidence(content):
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
