"""Pure, read-only trip attribution decisions for card and OTA evidence."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re

from .trip_selection import canonical_trip_periods, regional_trips, period_or_preparation

POLICY_VERSION = "automatic-classification-v2"
MANUAL_STATES = {"USER_CONFIRMED", "MANUAL_UNASSIGNED", "MANUAL_HOLD", "MANUAL_EXCLUDED"}


def provisional_trip_decision(trip_id, *, basis, confidence="낮음"):
    """Build the shared decision DTO after an existing authority resolver validates the trip."""
    candidate = {"trip_id": str(trip_id), "basis": str(basis), "confidence": confidence}
    return _decision("CLASSIFIED", str(trip_id), candidate["basis"], [candidate], confidence)


def card_trip_candidates(transaction, trips, *, nets=None, _canonical=None):
    """Share the existing locality/date/net ordering, leaving semantic ties tied.

    Scores encode ordinal policy order, not a fabricated probability or margin.
    Booking service dates must be resolved by the caller before this fallback.
    _canonical is private, validated input from this same plan, never a cache.
    """
    authoritative = canonical_trip_periods(trips) if _canonical is None else _canonical
    try:
        day = date.fromisoformat(transaction.get("approval_date") or "")
    except (TypeError, ValueError):
        return []
    merchant = str(transaction.get("merchant") or "").casefold()
    available = regional_trips(transaction, authoritative.values(), booking_agnostic=True)
    preferred, preparation = period_or_preparation(available, day.isoformat())
    if preferred:
        available = preferred
    ranked = []
    for trip in available:
        identity = str(trip["trip_id"])
        start = date.fromisoformat(trip["starts_on"])
        end = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else day
        distance = max((start - day).days, (day - end).days, 0)
        named = bool(trip.get("destination") and str(trip["destination"]).casefold() in merchant)
        # A place name does not make a purchase months later part of that trip.
        rank = (distance, not named, -(nets or {}).get(identity, 0))
        ranked.append((rank, identity, distance, named))
    order = {rank: index for index, rank in enumerate(sorted({entry[0] for entry in ranked}, reverse=True))}
    return [{"trip_id": identity, "score": order[rank], "confidence": "낮음",
             "basis": ("다음 여행 준비기간 · " if preparation else "") + ("가맹점 지역명 일치 · " if named else "") + f"카드 이용일과 여행 기간 거리 {distance}일"}
            for rank, identity, distance, named in ranked]


def propose_correction_pattern(corrections):
    """Build an inactive proposal from the latest distinct owner corrections."""
    latest = {}
    for raw in corrections:
        row = dict(raw)
        identity = str(row.get("transaction_id") or "")
        try:
            revision = int(row.get("revision"))
        except (TypeError, ValueError):
            continue
        if not identity:
            continue
        if identity not in latest or revision > latest[identity]["revision"]:
            latest[identity] = {**row, "revision": revision}
    rows = [r for r in latest.values() if r.get("owner_approved") is True
            and not r.get("duplicate_of") and not r.get("conflict_reason")
            and not r.get("financial_hold") and not r.get("excluded")
            and re.fullmatch(r"[0-9a-f]{64}", str(r.get("source_hash") or ""))
            and r.get("merchant_normalized") and r.get("trip_id") and r.get("item")]
    if len({r["source_hash"] for r in rows}) != len(rows):
        return {"status": "NO_PROPOSAL", "correction_count": 0}
    signatures = {(r["merchant_normalized"], r["trip_id"], r["item"], r["confidence"], r["basis"])
                  for r in rows if r.get("confidence") in ("낮음", "중간", "높음") and r.get("basis")}
    if len(rows) < 2 or len(signatures) != 1:
        return {"status": "NO_PROPOSAL", "correction_count": len(rows)}
    merchant, trip_id, item, confidence, basis = next(iter(signatures))
    correction_refs = [{"transaction_id": r["transaction_id"], "revision": r["revision"],
                        "source_hash": r["source_hash"]} for r in sorted(rows, key=lambda x: x["transaction_id"])]
    scope = {"merchant_normalized": merchant, "trip_id": trip_id,
             "item": item, "confidence": confidence, "basis": basis}
    proposal_id = _correction_proposal_id(scope, correction_refs)
    return {"id": proposal_id, "status": "PENDING_OWNER_APPROVAL", "active": False,
            "scope": scope,
            "corrections": correction_refs}


def approve_correction_pattern(store, proposal, *, approved_by, trips):
    """Serialize proposal validation and persistence in one transaction."""
    with store.lock:
        nested = store.conn.in_transaction
        store.conn.execute("SAVEPOINT approve_trip_corrections" if nested else "BEGIN IMMEDIATE")
        try:
            result = _approve_correction_pattern(store, proposal, approved_by=approved_by, trips=trips)
            if nested:
                store.conn.execute("RELEASE SAVEPOINT approve_trip_corrections")
            else:
                store.conn.commit()
            return result
        except BaseException:
            if nested:
                store.conn.execute("ROLLBACK TO SAVEPOINT approve_trip_corrections")
                store.conn.execute("RELEASE SAVEPOINT approve_trip_corrections")
            else:
                store.conn.rollback()
            raise


def _approve_correction_pattern(store, proposal, *, approved_by, trips):
    """Explicitly persist exact-source inferred rules through the existing rule/audit core."""
    if (not approved_by or not isinstance(proposal, dict)
            or proposal.get("status") != "PENDING_OWNER_APPROVAL"
            or proposal.get("active") is not False
            or not re.fullmatch(r"trip-correction-proposal-[0-9a-f]{24}", str(proposal.get("id") or ""))):
        raise ValueError("OWNER_APPROVAL_REQUIRED")
    scope = proposal.get("scope") or {}
    expected_id = _correction_proposal_id(scope, proposal.get("corrections") or ())
    if proposal.get("id") != expected_id:
        raise ValueError("PROPOSAL_CONTENT_CHANGED")
    if store.conn.execute("SELECT 1 FROM change_log WHERE kind=? AND subject=? LIMIT 1",
                          ("trip_correction_rules.approved", proposal["id"])).fetchone():
        return {"status": "ALREADY_APPROVED", "active": True, "proposal_id": proposal["id"]}
    corrections = proposal.get("corrections")
    if not isinstance(corrections, list) or len(corrections) < 2:
        raise ValueError("INSUFFICIENT_DISTINCT_CORRECTIONS")
    txids = [str(row.get("transaction_id") or "") for row in corrections
             if isinstance(row, dict)]
    hashes = [str(row.get("source_hash") or "") for row in corrections
              if isinstance(row, dict)]
    if (len(txids) != len(corrections) or len(set(txids)) != len(txids)
            or len(set(hashes)) != len(hashes)):
        raise ValueError("INSUFFICIENT_DISTINCT_CORRECTIONS")
    trip = canonical_trip_periods(trips).get(str(scope.get("trip_id") or ""))
    if not trip or not re.fullmatch(r"[^*]{1,160}", str(scope.get("merchant_normalized") or "")):
        raise ValueError("TRIP_NOT_AUTHORITATIVE")
    from .rules import normalize_rule, save_rule
    prepared = []
    from .review import correction_protection_reason
    for correction in corrections:
        txid, digest = str(correction.get("transaction_id") or ""), str(correction.get("source_hash") or "")
        if not txid or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("INVALID_CORRECTION_SCOPE")
        protected = correction_protection_reason(store, txid, digest)
        if protected:
            raise ValueError("CORRECTION_PROTECTED:" + protected)
        row = store.conn.execute(
            "SELECT merchant_normalized,source_hash,revision,trip_id,item,classification_source,"
            "duplicate_of,conflict_reason FROM transactions WHERE transaction_id=?", (txid,)).fetchone()
        if (row is None or row[1] != digest or int(row[2]) != int(correction.get("revision", -1))
                or row[3] != scope["trip_id"] or row[4] != scope["item"]
                or row[0] != scope["merchant_normalized"] or row[5] != "user_decision"
                or row[6] or row[7]):
            raise ValueError("CORRECTION_STALE_OR_PROTECTED")
        draft = {"conditions": {"merchant_normalized": row[0]},
                 "optional": {"source_hash": digest,
                              "inferred_assignment": {"trip_id": scope["trip_id"],
                                  "basis": scope["basis"], "confidence": scope["confidence"]}},
                 "effects": {"item": scope["item"]},
                 "origin": "owner-approved-trip-correction",
                 "rule_id": "trip-correction-" + digest[:24],
                 "note": "Owner-approved transaction-exact trip correction"}
        prepared.append(normalize_rule(draft))
    if len(prepared) < 2:
        raise ValueError("INSUFFICIENT_DISTINCT_CORRECTIONS")
    store.conn.execute("SAVEPOINT provisional_trip_rules")
    try:
        saved = [save_rule(store, rule) for rule in prepared]
        store.log_change("trip_correction_rules.approved", proposal["id"],
                         {"approved_by": str(approved_by), "scope": scope, "rules": saved})
        store.conn.execute("RELEASE SAVEPOINT provisional_trip_rules")
    except BaseException:
        store.conn.execute("ROLLBACK TO SAVEPOINT provisional_trip_rules")
        store.conn.execute("RELEASE SAVEPOINT provisional_trip_rules")
        raise
    return {"status": "APPROVED", "active": True, "approved_by": str(approved_by),
            "proposal_id": proposal["id"], "rules": saved, "scope": dict(scope)}


def rank_trip_candidates(candidates, *, trips=(), manual_trip_id=None, manual_status=None,
                         financial_hold=False):
    """Validate, deduplicate by trip, then rank candidates without mutating input."""
    if manual_status in MANUAL_STATES:
        if manual_status == "USER_CONFIRMED":
            return _decision("CLASSIFIED" if manual_trip_id else "MANUAL_UNASSIGNED",
                             manual_trip_id or "", "사용자 결정 보호", (), source="manual")
        return _decision(manual_status, manual_trip_id or "", "사용자 결정 보호", (), source="manual")
    if manual_trip_id is not None:
        return _decision("CLASSIFIED" if manual_trip_id else "MANUAL_UNASSIGNED",
                         str(manual_trip_id or ""), "사용자 여행 결정 보호", (), source="manual")
    by_id = canonical_trip_periods(trips)
    grouped = {}
    for raw in candidates:
        candidate = dict(raw)
        trip_id = str(candidate.get("trip_id") or "")
        trip = by_id.get(trip_id)
        if not trip or not _valid_period(trip, candidate.get("service_period")):
            continue
        try:
            score = int(candidate.get("score", 0))
        except (TypeError, ValueError):
            continue
        group = grouped.setdefault(trip_id, {"trip_id": trip_id, "score": score,
            "basis": set(), "confidence": candidate.get("confidence", "낮음"),
            "service_period": candidate.get("service_period")})
        group["score"] = max(group["score"], score)
        basis = str(candidate.get("basis") or "근거 부족")
        group["basis"].add(basis)
    valid = [{**group, "evidence_count": len(group["basis"]),
              "basis": " · ".join(sorted(group["basis"])[:3])} for group in grouped.values()]
    if not valid:
        status = "FINANCIAL_HOLD" if financial_hold else "UNASSIGNED_NO_VALID_TRIP"
        return _decision(status, "", "금융 보류" if financial_hold else "유효한 여행 후보 없음", ())
    valid.sort(key=lambda c: (-c["score"], c["trip_id"]))
    alternatives = valid[:3]
    if financial_hold:
        return _decision("FINANCIAL_HOLD", "", "금융 보류: 여행 후보는 참고 정보", alternatives)
    if len(valid) > 1 and valid[0]["score"] == valid[1]["score"]:
        return _decision("CONFLICT_REVIEW", "", "최상위 여행 후보 동률", alternatives)
    top = valid[0]
    return _decision("CLASSIFIED", top["trip_id"], top["basis"], alternatives,
                     confidence=top["confidence"])


def ota_service_period_candidate(event, trips, *, score=0):
    """Return candidates where verified OTA service dates overlap canonical trip periods."""
    period = event.get("service_period") or {}
    try:
        start, end = date.fromisoformat(period["starts_on"]), date.fromisoformat(period["ends_on"])
    except (KeyError, TypeError, ValueError):
        return []
    if end < start or event.get("service_period_conflict") or event.get("period_conflict"):
        return []
    result = []
    for trip in canonical_trip_periods(trips).values():
        try:
            trip_start = date.fromisoformat(trip["starts_on"])
            trip_end = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= end and (trip_end is None or start <= trip_end):
            result.append({"trip_id": str(trip["trip_id"]), "score": score,
                           "confidence": "낮음", "basis": "OTA 확인 이용기간과 여행 기간 일치",
                           "service_period": dict(period)})
    return result


def _valid_period(trip, service_period):
    try:
        starts = date.fromisoformat(trip["starts_on"])
        ends = date.fromisoformat(trip["ends_on"]) if trip.get("ends_on") else None
        if ends and ends < starts:
            return False
        if service_period:
            service_start = date.fromisoformat(service_period["starts_on"])
            service_end = date.fromisoformat(service_period["ends_on"])
            return service_end >= service_start and starts <= service_end and (ends is None or service_start <= ends)
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _decision(status, trip_id, reason, candidates, confidence="낮음", *, source="automatic"):
    return {"status": status, "trip_id": trip_id, "reason": reason,
            "assignment_source": source,
            "confidence": confidence, "candidates": list(candidates),
            "policy_version": POLICY_VERSION}


def _correction_proposal_id(scope, corrections):
    payload = json.dumps([scope, list(corrections)], ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return "trip-correction-proposal-" + hashlib.sha256(payload).hexdigest()[:24]
