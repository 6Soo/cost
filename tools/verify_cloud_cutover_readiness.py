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
MESSAGE_ID = re.compile(r"^[a-fA-F0-9]+$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class ReadinessError(ValueError):
    pass


def batch_digest(messages, ids):
    if (not isinstance(ids, list) or any(not isinstance(identity, str) or identity not in messages
                                       for identity in ids)):
        raise ReadinessError('CLOUD_MAIL_BATCH_COVERAGE_INVALID')
    entries = []
    for identity in ids:
        entry = messages[identity]
        if not isinstance(entry, dict) or not HEX.fullmatch(str(entry.get('sha256', ''))):
            raise ReadinessError('CLOUD_MAIL_DIGEST_REQUIRED')
        entries.append([identity, entry['sha256']])
    return hashlib.sha256(json.dumps(entries, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _read(path):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReadinessError("CLOUD_MAIL_READINESS_INPUT_INVALID") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessError("CLOUD_MAIL_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def verify(bundle):
    if not isinstance(bundle, dict):
        raise ReadinessError("CLOUD_MAIL_READINESS_INPUT_INVALID")
    manifest = bundle.get("manifest", bundle)
    if not isinstance(manifest, dict) or manifest.get("schema") != "cost-cloud-mail-v1":
        raise ReadinessError("CLOUD_MAIL_READINESS_MANIFEST_INVALID")
    messages = manifest.get("messages")
    if not isinstance(messages, dict):
        raise ReadinessError("CLOUD_MAIL_READINESS_MANIFEST_INVALID")
    if any(not isinstance(identity, str) or not MESSAGE_ID.fullmatch(identity)
           or not isinstance(entry, dict) for identity, entry in messages.items()):
        raise ReadinessError("CLOUD_MAIL_READINESS_MANIFEST_INVALID")
    if manifest.get("pending", []) not in ([], None):
        raise ReadinessError("CLOUD_MAIL_PENDING")
    watermark = manifest.get("last_complete")
    if (manifest.get("query") is not None or not isinstance(watermark, str)
            or not UTC_TIMESTAMP.fullmatch(watermark)):
        raise ReadinessError("CLOUD_MAIL_ENUMERATION_INCOMPLETE")
    if any(manifest.get(key) not in (None, '') for key in ('nextPageToken', 'next_page_token')):
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
        if any(not isinstance(identity, str) for identity in ids):
            raise ReadinessError('CLOUD_MAIL_BATCH_COVERAGE_INVALID')
        if type(coverage.get('count')) is not int or coverage['count'] != len(ids) or len(set(ids)) != len(ids) or seen.intersection(ids):
            raise ReadinessError("CLOUD_MAIL_BATCH_COVERAGE_INVALID")
        if any(message_id not in messages for message_id in ids):
            raise ReadinessError("CLOUD_MAIL_BATCH_COVERAGE_INVALID")
        if batch['sha256'] != batch_digest(messages, ids):
            raise ReadinessError('CLOUD_MAIL_BATCH_HASH_INVALID')
        seen.update(ids)
        digest_inputs.extend(ids)
    if set(messages) != seen:
        raise ReadinessError("CLOUD_MAIL_COVERAGE_INCOMPLETE")
    expected = hashlib.sha256("\n".join(digest_inputs).encode()).hexdigest()
    if bundle.get("batch_coverage_sha256") != expected:
        raise ReadinessError("CLOUD_MAIL_BATCH_HASH_INVALID")
    existing = bundle.get("existing")
    new = bundle.get("new")
    indexed = bundle.get("indexed")
    if not all(type(value) is int and value >= 0 for value in (existing, new, indexed)):
        raise ReadinessError("CLOUD_MAIL_COUNTS_INVALID")
    if indexed != len(messages) or indexed != existing + new:
        raise ReadinessError("CLOUD_MAIL_COUNTS_INVALID")
    return {"status": "PREVIEW_VERIFIED", "indexed": indexed, "batches": len(batches),
            "pending": 0, "has_next_page": False, 'operational_cutover_allowed': False,
            'remaining_gate': 'fresh live manifest, content preview, writer pause and verified backup/restore'}


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
