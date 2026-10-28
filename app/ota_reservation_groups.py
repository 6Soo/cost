"""Pure, conservative grouping from explicitly verified reservation evidence.

This module does not infer reservation identity from provider/reference text,
mail lineage, portal database lineage, solver groups, or payment attributes.
Only a producer-attested, provider-scoped identity from verified portal
evidence or an authenticated provider mail's explicit booking binding
links and no conflict can place events in a shared reservation container.
Events and their independent payment/status axes are never rewritten.

Trust boundary: this pure projector can validate the shape and consistency of
an attestation, but cannot authenticate its author or prove that evidence-link
IDs refer to real evidence. A trusted upstream producer must establish those
facts. ``evidence_link_ids`` are required as linkage references, not treated as
proof by this module. Event-level evidence warnings/flags veto grouping; normal
payment HOLD or refund states do not imply reservation identity conflict.
"""
from collections.abc import Mapping


_VERIFIED = "verified"
_WARNINGS = {
    "missing_event_id": "EVENT_ID_MISSING",
    "duplicate_event_id": "EVENT_ID_DUPLICATE",
    "missing_attestation": "RESERVATION_IDENTITY_UNVERIFIED",
    "invalid_attestation": "RESERVATION_ATTESTATION_INVALID",
    "identity_conflict": "RESERVATION_IDENTITY_CONFLICT",
    "evidence_conflict": "RESERVATION_EVIDENCE_CONFLICT",
    "source_mismatch": "RESERVATION_SOURCE_MISMATCH",
    "unknown_state": "RESERVATION_ATTESTATION_UNKNOWN",
    "event_provider_missing": "EVENT_PROVIDER_MISSING",
    "event_provider_invalid": "EVENT_PROVIDER_INVALID",
    "provider_mismatch": "RESERVATION_PROVIDER_MISMATCH",
    "event_evidence_warning": "EVENT_EVIDENCE_UNVERIFIED",
}


def _attested_key(event):
    """Return a verified identity key and warning, without interpreting raw refs."""
    event_provider = event.get("provider")
    if event_provider is None or event_provider == "":
        return None, "event_provider_missing"
    if type(event_provider) is not str or not event_provider.strip():
        return None, "event_provider_invalid"
    attestation = event.get("reservation_identity_attestation")
    if not isinstance(attestation, Mapping):
        return None, "missing_attestation"
    # The producer-only private provenance is the trust channel. A caller
    # supplied public-shaped attestation by itself is never sufficient.
    provenance = event.get("_portal_reservation_provenance")
    mail_provenance = provenance is None
    if provenance is None:
        provenance = event.get('_mail_reservation_provenance')
        if isinstance(provenance, Mapping) and (
                provenance.get('kind') != 'authenticated_provider_booking' or
                provenance.get('booking_ref') != event.get('booking_ref') or
                provenance.get('source_digest') != event.get('source_digest')):
            return None, 'invalid_attestation'
    if not isinstance(provenance, Mapping):
        return None, "missing_attestation"
    provider = attestation.get("provider")
    identity = attestation.get("identity")
    if (type(provider) is not str or not provider.strip() or
            type(identity) is not str or not identity.strip()):
        return None, "invalid_attestation"
    if provider != event_provider:
        return None, "provider_mismatch"
    if (provenance.get("provider") != provider or
            provenance.get("identity") != identity or
            type(provenance.get("source_digest")) is not str or
            not provenance.get("source_digest") or
            provenance.get("source_lineage_id") != attestation.get("source_lineage_id")):
        return None, "invalid_attestation"
    if any(event.get(field) is True or
           (field in event and event.get(field) not in (None, False, ""))
           for field in ("evidence_changed", "evidence_missing", "evidence_conflict")):
        return None, "event_evidence_warning"
    if attestation.get("identity_status") == "conflict":
        return None, "identity_conflict"
    if attestation.get("evidence_status") == "conflict":
        return None, "evidence_conflict"
    if attestation.get("source_status") == "mismatch":
        return None, "source_mismatch"
    if (attestation.get("identity_status") != _VERIFIED or
            attestation.get("evidence_status") != _VERIFIED or
            attestation.get("source_status") != _VERIFIED or
            type(attestation.get("evidence_link_ids")) not in (list, tuple) or
            not attestation.get("evidence_link_ids")):
        return None, "unknown_state"
    links = attestation["evidence_link_ids"]
    if any(type(value) is not str or not value.strip() for value in links):
        return None, "invalid_attestation"
    if len(set(links)) != len(links):
        return None, "invalid_attestation"
    if mail_provenance:
        sources = event.get('source_ids')
        if (type(sources) not in (list, tuple) or any(type(s) is not str for s in sources)
                or any(link not in sources for link in links)):
            return None, 'invalid_attestation'
    return (provider, identity), None


def project_reservation_groups(events):
    """Project deterministic event membership and safe warnings.

    Input is an iterable of mappings. Output has no event payload copies: each
    event ID occurs exactly once in ``groups``. Duplicate/missing IDs are
    singleton rows with warnings and cannot participate in verified groups.
    """
    if isinstance(events, (str, bytes, Mapping)):
        raise ValueError("events must be an iterable of event mappings")
    try:
        rows = list(events)
    except Exception:
        raise ValueError("events must be an iterable of event mappings") from None

    ids = [row.get("ota_event_id") if isinstance(row, Mapping) else None for row in rows]
    counts = {}
    for event_id in ids:
        if type(event_id) is str and event_id.strip():
            counts[event_id] = counts.get(event_id, 0) + 1

    buckets = {}
    warnings_by_id = {}
    # Keep malformed/missing IDs addressable by input position, without
    # manufacturing a public event identity.
    for index, (row, event_id) in enumerate(zip(rows, ids)):
        valid_id = type(event_id) is str and bool(event_id.strip())
        warning = None
        key = None
        if not valid_id:
            warning = "missing_event_id"
        elif counts[event_id] > 1:
            warning = "duplicate_event_id"
        elif not isinstance(row, Mapping):
            warning = "invalid_attestation"
        else:
            key, warning = _attested_key(row)
        if warning:
            warnings_by_id[index] = _WARNINGS[warning]
        bucket_key = ("verified", key) if key is not None else ("singleton", index)
        buckets.setdefault(bucket_key, []).append((index, event_id if valid_id else None))

    projected = []
    for (kind, key), members in buckets.items():
        member_ids = [event_id for _, event_id in members]
        projected.append({
            "provider": key[0] if kind == "verified" else None,
            "identity": key[1] if kind == "verified" else None,
            "event_ids": sorted(value for value in member_ids if value is not None),
            "input_index": min(index for index, _ in members),
            "member_indices": sorted(index for index, _ in members),
            "member_count": len(members),
            "verified": kind == "verified",
            "warnings": sorted({warnings_by_id[index] for index, _ in members
                                if index in warnings_by_id}),
            "_order": min(index for index, _ in members),
        })
    projected.sort(key=lambda group: (group["_order"], group["event_ids"]))
    for group in projected:
        del group["_order"]
    verified_count = sum(group["verified"] for group in projected)
    return {
        "grouping": "producer_attested_reservation_identity",
        "fallback_status": "verified_groups_present" if verified_count else "all_singleton_fallback",
        "verified_group_count": verified_count,
        "singleton_fallback_count": len(projected) - verified_count,
        "groups": projected,
    }
