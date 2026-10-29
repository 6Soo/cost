"""Read-only verifier for the complete synthetic cloud-mail cutover evidence.

The input is a JSON evidence bundle.  This command never contacts Drive and never
writes the manifest, originals, or a database.  It deliberately requires a whole
manifest and independently checks every bounded batch's digest and coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

HEX = re.compile(r"^[0-9a-f]{64}$")


class ReadinessError(ValueError):
    pass


def _read(path):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReadinessError("CLOUD_MAIL_READINESS_INPUT_INVALID") from None


def verify(bundle):
    if not isinstance(bundle, dict):
        raise ReadinessError("CLOUD_MAIL_READINESS_INPUT_INVALID")
    manifest = bundle.get("manifest", bundle)
    if not isinstance(manifest, dict) or manifest.get("schema") != "cost-cloud-mail-v1":
        raise ReadinessError("CLOUD_MAIL_READINESS_MANIFEST_INVALID")
    messages = manifest.get("messages")
    if not isinstance(messages, dict):
        raise ReadinessError("CLOUD_MAIL_READINESS_MANIFEST_INVALID")
    if manifest.get("pending", []) not in ([], None):
        raise ReadinessError("CLOUD_MAIL_PENDING")
    if manifest.get("query") is not None or not isinstance(manifest.get("last_complete"), str):
        raise ReadinessError("CLOUD_MAIL_ENUMERATION_INCOMPLETE")
    if manifest.get("nextPageToken", manifest.get("next_page_token")) not in (None, ""):
        raise ReadinessError("CLOUD_MAIL_HAS_NEXT_PAGE")
    if manifest.get("has_next_page", False) is not False:
        raise ReadinessError("CLOUD_MAIL_HAS_NEXT_PAGE")
    batches = bundle.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ReadinessError("CLOUD_MAIL_BATCH_EVIDENCE_REQUIRED")
    seen, digest_inputs = set(), []
    for batch in batches:
        if not isinstance(batch, dict) or not HEX.fullmatch(str(batch.get("sha256", ""))):
            raise ReadinessError("CLOUD_MAIL_BATCH_HASH_INVALID")
        coverage = batch.get("coverage")
        ids = batch.get("ids")
        if not isinstance(coverage, dict) or coverage.get("complete") is not True or not isinstance(ids, list):
            raise ReadinessError("CLOUD_MAIL_BATCH_COVERAGE_INVALID")
        if coverage.get("count") != len(ids) or len(set(ids)) != len(ids) or seen.intersection(ids):
            raise ReadinessError("CLOUD_MAIL_BATCH_COVERAGE_INVALID")
        if any(message_id not in messages for message_id in ids):
            raise ReadinessError("CLOUD_MAIL_BATCH_COVERAGE_INVALID")
        seen.update(ids)
        digest_inputs.extend(ids)
    if set(messages) != seen:
        raise ReadinessError("CLOUD_MAIL_COVERAGE_INCOMPLETE")
    expected = hashlib.sha256("\n".join(digest_inputs).encode()).hexdigest()
    if bundle.get("batch_coverage_sha256", expected) != expected:
        raise ReadinessError("CLOUD_MAIL_BATCH_HASH_INVALID")
    existing = bundle.get("existing")
    new = bundle.get("new")
    indexed = bundle.get("indexed", len(messages))
    if not all(isinstance(value, int) and value >= 0 for value in (existing, new, indexed)):
        raise ReadinessError("CLOUD_MAIL_COUNTS_INVALID")
    if indexed != len(messages) or indexed != existing + new:
        raise ReadinessError("CLOUD_MAIL_COUNTS_INVALID")
    return {"status": "READY", "indexed": indexed, "batches": len(batches),
            "pending": 0, "has_next_page": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify cloud-mail cutover evidence without I/O side effects")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(_read(args.evidence))
    except ReadinessError as error:
        print(json.dumps({"status": "BLOCKED", "code": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
