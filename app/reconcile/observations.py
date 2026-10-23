"""Read OTA inputs and describe extraction outcomes without changing them."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import Path

from app import ota_mail, ota_portal


def inspect_observations(sources, events):
    """Return privacy-neutral counts and skipped raw observation descriptors.

    The returned descriptors contain only a local source coordinate and reason;
    callers must pseudonymize the coordinate before writing any report.
    """
    sources = sources or {}
    event_sources = {
        str(source)
        for event in events or ()
        for source in event.get("identity_source_ids", event.get("source_ids", ()))
    }
    skipped = []
    mail_count = 0
    for directory_index, directory in enumerate(sources.get("mail_directories") or ()):
        try:
            messages, inventory = ota_mail.load_messages_from([directory])
        except Exception as exc:
            skipped.append({"source": f"mail-directory:{directory_index}",
                            "reason": "SOURCE_UNREADABLE", "error_type": type(exc).__name__})
            continue
        mail_count += len(messages)
        for message_id in messages:
            source_id = f"mail:{message_id}"
            if source_id not in event_sources:
                skipped.append({"source": source_id, "reason": "NO_PAYMENT_EVENT"})
        for item in inventory or ():
            if item.get("error"):
                skipped.append({"source": f"mail-inventory:{directory_index}",
                                "reason": "SOURCE_UNREADABLE",
                                "error_type": "SOURCE_READ_ERROR"})

    portal_count = 0
    portal_databases_by_id = defaultdict(set)
    portal_payloads_by_hash = defaultdict(set)
    for database_index, database in enumerate(ota_portal.as_databases(sources.get("portal_databases"))):
        path = Path(database).resolve()
        if not path.is_file():
            skipped.append({"source": f"portal-database:{database_index}",
                            "reason": "SOURCE_MISSING"})
            continue
        try:
            rows = ota_portal._read_records(path, database_index)
        except Exception as exc:
            skipped.append({"source": f"portal-database:{database_index}",
                            "reason": "SOURCE_UNREADABLE", "error_type": type(exc).__name__})
            continue
        portal_count += len(rows)
        for row in rows:
            local_id = str(row.get("id", ""))
            portal_databases_by_id[local_id].add(database_index)
            payload = str(row.get("payload_json") or "").encode("utf-8")
            if payload:
                portal_payloads_by_hash[hashlib.sha256(payload).hexdigest()].add(database_index)
            source_id = f"portal:record:{local_id}:payment:row-{local_id}-part-0"
            if not any(value.startswith(f"portal:record:{local_id}:") for value in event_sources):
                reasons = []
                if row.get("conflict_count") or row.get("evidence_status") != "observed":
                    reasons.append("SOURCE_CONFLICT")
                if not str(row.get("payload_json") or ""):
                    reasons.append("RAW_PAYLOAD_MISSING")
                if not reasons:
                    reasons.append("PAYMENT_COMPONENT_MISSING_OR_UNVERIFIED")
                skipped.append({"source": f"portal:{database_index}:{local_id}",
                                "reason": reasons})
    collisions = [local_id for local_id, databases in portal_databases_by_id.items()
                  if local_id and len(databases) > 1]
    for local_id in collisions:
        skipped.append({"source": f"portal-record:{local_id}", "reason": "SOURCE_ID_COLLISION"})
    possible_copies = [digest for digest, databases in portal_payloads_by_hash.items()
                       if len(databases) > 1]
    for digest in possible_copies:
        skipped.append({"source": f"portal-payload:{digest}", "reason": "POSSIBLE_SOURCE_COPY"})
    reason_counts = Counter()
    for item in skipped:
        values = item["reason"] if isinstance(item["reason"], list) else [item["reason"]]
        reason_counts.update(values)
    return {
        "raw_mail_observations": mail_count,
        "raw_portal_observations": portal_count,
        "raw_observations": mail_count + portal_count,
        "skipped_observation_count": len(skipped),
        "skipped_reason_counts": dict(sorted(reason_counts.items())),
        "portal_local_id_reuse_count": len(collisions),
        "possible_source_copy_count": len(possible_copies),
        "skipped": skipped,
    }
