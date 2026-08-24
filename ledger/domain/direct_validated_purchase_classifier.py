"""Promote only leave-one-out validated purchase classifications.

Historical classifications are imported as a frozen learning snapshot.  They
are never registered as transaction evidence and the target row is removed
from every peer model before a prediction is made.  A current purchase is
promotable only when two account models and two target/cost models each have
at least three distinct peers, are internally unanimous, and agree pairwise.
The held-out target label is consulted only after prediction to score the
model; any validation error fails the whole cohort closed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from typing import Iterable

from ledger.domain.direct_sources import _insert_source
from ledger.domain.direct_verified_ota_lodging import load_trip_schedule


MODEL_CONTRACT = "validated-current-target-four-model-leave-one-out-v3"
RULE_ID = "validated-current-target-four-model-loo-v3"
TRAINING_SOURCE_KIND = "classifier_training"
TRAINING_SOURCE_SHA256 = (
    "8424884622705bb8ebec2efb4ca2d995247993767eac039e5bb2b2959ee3b989"
)
TRAINING_ROLE = "learning_only_not_transaction_evidence"
NORMALIZATION_CONTRACT = "unicode-nfkc-uppercase-strip-nonalnum-v1"
MINIMUM_PEER_COUNT = 3
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
EXPECTED_TRAINING_ROWS = 1833
EXPECTED_CANDIDATES = 4885
EXPECTED_LEARNING_SEEDS = 1154
EXPECTED_PROMOTED = 114
EXPECTED_VALIDATIONS = 99
EXPECTED_SCHEDULE_COUNTS = {
    "ambiguous_match": 76,
    "no_match": 7,
    "unique_agreement": 31,
}
ADVERSE_TOKENS = ("확인", "미정", "검토", "추정")
RATIONALE = (
    "해당 거래의 과거 정답을 제외한 뒤 서로 다른 네 규칙이 같은 세 비용축을 "
    "예측했고, 현재 거래와 분리한 사후 교차검증에서 오분류가 없었음"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    raw = value if isinstance(value, bytes) else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper().strip()
    return re.sub(r"[^0-9A-Z가-힣]+", "", text)


def _digits(value: object) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _compound_key(
    source: object, occurred_on: object, amount: object,
    approval: object, card4: object,
) -> tuple[str, str, int, str, str]:
    return (
        str(source or ""), str(occurred_on or ""), int(amount),
        _digits(approval), _digits(card4)[-4:],
    )


def _is_adverse(value: object) -> bool:
    text = str(value or "").strip()
    return not text or any(token in text for token in ADVERSE_TOKENS)


def _set_sha(values: Iterable[str]) -> str:
    return _sha("".join(value + "\n" for value in sorted(values)).encode())


def _training_rows(raw: bytes) -> list[dict[str, str]]:
    if _sha(raw) != TRAINING_SOURCE_SHA256:
        raise ValueError("classifier_training_snapshot_drift")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        rows = [dict(row) for row in reader]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("classifier_training_parse_invalid") from exc
    required = {
        "uid", "src", "use_date", "post_date", "card4", "merchant", "biz",
        "currency", "krw", "bucket", "account", "cancel", "cost_type",
        "appr",
    }
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("classifier_training_header_invalid")
    uids = [str(row.get("uid") or "").strip() for row in rows]
    if (
        len(rows) != EXPECTED_TRAINING_ROWS
        or any(not uid for uid in uids)
        or len(uids) != len(set(uids))
    ):
        raise ValueError("classifier_training_census_invalid")
    return rows


def materialize_classifier_training(db: object, raw: bytes) -> dict[str, object]:
    """Store the captured learning snapshot outside the evidence tables."""
    rows = _training_rows(raw)
    existing = int(db.execute(
        "SELECT COUNT(*) FROM direct_source_records WHERE source_kind=?",
        (TRAINING_SOURCE_KIND,),
    ).fetchone()[0])
    if existing:
        raise ValueError("classifier_training_already_materialized")
    for row in rows:
        _insert_source(
            db, TRAINING_SOURCE_KIND, str(row["uid"]), row,
            redaction_version="learning-only-no-evidence-v1",
        )
    actual = int(db.execute(
        "SELECT COUNT(*) FROM direct_source_records WHERE source_kind=?",
        (TRAINING_SOURCE_KIND,),
    ).fetchone()[0])
    if actual != EXPECTED_TRAINING_ROWS:
        raise ValueError("classifier_training_materialization_mismatch")
    evidence_leak = int(db.execute(
        """SELECT COUNT(*) FROM direct_promotion_evidence
           WHERE lower(source_kind) LIKE '%classifier%'
              OR lower(source_kind) LIKE '%training%'"""
    ).fetchone()[0])
    if evidence_leak:
        raise ValueError("classifier_training_evidence_leak")
    return {
        "source_kind": TRAINING_SOURCE_KIND,
        "training_role": TRAINING_ROLE,
        "row_count": actual,
        "raw_sha256": TRAINING_SOURCE_SHA256,
        "transaction_evidence_count": 0,
    }


def _load_training(db: object) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records WHERE source_kind=? ORDER BY source_key""",
        (TRAINING_SOURCE_KIND,),
    ).fetchall()
    if len(rows) != EXPECTED_TRAINING_ROWS:
        raise ValueError("classifier_training_database_census_invalid")
    result: list[dict[str, object]] = []
    for uid, row_sha256, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("classifier_training_payload_invalid") from exc
        if not isinstance(payload, dict) or str(payload.get("uid") or "") != str(uid):
            raise ValueError("classifier_training_payload_invalid")
        if _sha(payload) != str(row_sha256):
            raise ValueError("classifier_training_row_hash_mismatch")
        result.append({
            "uid": str(uid), "row_sha256": str(row_sha256), "payload": payload,
        })
    return result


def _load_current(db: object, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT d.card_event_id || '#' || d.event_role,p.id,d.amount_krw,
                  p.source_system,p.occurred_on,p.posted_on,p.merchant,
                  p.approval_number,p.transaction_type,pm.last4,s.payload_json,
                  s.source_kind,s.source_key,s.source_sha256,e.evidence_id,
                  e.fact_sha256
           FROM direct_payment_projection_links l
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           LEFT JOIN payment_methods pm ON pm.id=p.payment_method_id
           JOIN direct_promotion_evidence e
             ON e.run_id=l.run_id AND e.evidence_kind='current_card'
            AND e.authority_status='current_raw'
            AND e.direct_event_key=d.card_event_id || '#' || d.event_role
            AND e.source_kind=s.source_kind AND e.source_key=s.source_key
            AND e.source_sha256=s.source_sha256
           WHERE l.run_id=? ORDER BY 1""",
        (run_id,),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        try:
            payload = json.loads(str(row[10]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("classifier_current_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("classifier_current_payload_invalid")
        result.append({
            "direct_event_key": str(row[0]), "payment_id": int(row[1]),
            "amount_krw": int(row[2]), "source": str(row[3]),
            "occurred_on": str(payload.get("use_date") or row[4] or ""),
            "posted_on": str(payload.get("post_date") or row[5] or ""),
            "merchant": str(payload.get("merchant") or row[6] or ""),
            "approval": str(payload.get("appr") or row[7] or ""),
            "transaction_type": str(row[8]),
            "card4": str(payload.get("card4") or row[9] or ""),
            "biz": str(payload.get("biz") or ""),
            "currency": str(payload.get("currency") or ""),
            "source_kind": str(row[11]), "source_key": str(row[12]),
            "source_sha256": str(row[13]), "current_evidence_id": str(row[14]),
            "current_fact_sha256": str(row[15]),
        })
    if len(result) != len({row["direct_event_key"] for row in result}):
        raise ValueError("classifier_current_event_duplicate")
    return result


def _training_amount(payload: dict[str, object]) -> int:
    amount = int(payload.get("krw") or 0)
    if (
        str(payload.get("src") or "") in {"KBO", "CORP"}
        and str(payload.get("cancel") or "").lower() == "true"
    ):
        return -abs(amount)
    return amount


def _historical_associations(
    training: list[dict[str, object]], current: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Associate by identity only; labels never decide current candidacy."""
    historical_groups: dict[
        tuple[str, str, int, str, str], list[dict[str, object]]
    ] = defaultdict(list)
    current_groups: dict[
        tuple[str, str, int, str, str], list[dict[str, object]]
    ] = defaultdict(list)
    for item in training:
        payload = item["payload"]
        assert isinstance(payload, dict)
        try:
            key = _compound_key(
                payload.get("src"), payload.get("use_date"),
                _training_amount(payload), payload.get("appr"),
                payload.get("card4"),
            )
        except (TypeError, ValueError):
            continue
        historical_groups[key].append(item)
    for event in current:
        key = _compound_key(
            event["source"], event["occurred_on"], event["amount_krw"],
            event["approval"], event["card4"],
        )
        current_groups[key].append(event)
    result: dict[str, dict[str, object]] = {}
    for event in current:
        key = _compound_key(
            event["source"], event["occurred_on"], event["amount_krw"],
            event["approval"], event["card4"],
        )
        historical = historical_groups.get(key, [])
        if len(historical) == 1 and len(current_groups[key]) == 1:
            result[str(event["direct_event_key"])] = historical[0]
    return result


def _learning_seeds(
    training: list[dict[str, object]],
    associations: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Build the peer pool from the three active classification axes only."""
    associated_hashes = {
        str(row["row_sha256"]) for row in associations.values()
    }
    seeds: list[dict[str, object]] = []
    for item in training:
        if str(item["row_sha256"]) not in associated_hashes:
            continue
        payload = item["payload"]
        assert isinstance(payload, dict)
        if str(payload.get("src") or "") not in {"KBD", "KBO", "HAN", "CORP"}:
            continue
        account = str(payload.get("account") or "").strip()
        cost_type = str(payload.get("cost_type") or "").strip()
        target = str(payload.get("bucket") or "").strip()
        if any(_is_adverse(value) for value in (account, cost_type, target)):
            continue
        feature = {
            "source": str(payload.get("src") or ""),
            "normalized_merchant": _norm(payload.get("merchant")),
            "occurred_on": str(payload.get("use_date") or ""),
            "posted_on": str(payload.get("post_date") or ""),
        }
        seeds.append({
            "historical_row_sha256": str(item["row_sha256"]),
            "truth_account": account, "truth_cost_type": cost_type,
            "truth_target": target, "feature": feature,
            "account_a_key": (
                feature["source"], feature["normalized_merchant"],
            ),
            "account_b_key": (feature["normalized_merchant"],),
            "target_q_key": (
                feature["occurred_on"], feature["normalized_merchant"],
            ),
            "target_r_key": (
                feature["posted_on"], feature["normalized_merchant"],
            ),
        })
    seeds.sort(key=lambda row: str(row["historical_row_sha256"]))
    return seeds


def _current_candidates(
    current: list[dict[str, object]],
    associations: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for event in current:
        if event["transaction_type"] != "purchase" or int(event["amount_krw"]) <= 0:
            continue
        feature = {
            "source": event["source"],
            "normalized_merchant": _norm(event["merchant"]),
            "exact_biz_category": _norm(event["biz"]),
            "currency": _norm(event["currency"]),
            "occurred_on": event["occurred_on"],
            "posted_on": event["posted_on"],
            "transaction_type": event["transaction_type"],
            "amount_positive": True,
        }
        association = associations.get(str(event["direct_event_key"]))
        excluded_row_sha = (
            "" if association is None else str(association["row_sha256"])
        )
        association_sha = _sha({
            "current_identity": _compound_key(
                event["source"], event["occurred_on"], event["amount_krw"],
                event["approval"], event["card4"],
            ),
            "association_status": "unique" if association is not None else "none",
        })
        candidates.append({
            **event, "feature": feature,
            "excluded_row_sha256": excluded_row_sha,
            "held_out_association_sha256": association_sha,
            "account_a_key": (
                feature["source"], feature["normalized_merchant"],
            ),
            "account_b_key": (feature["normalized_merchant"],),
            "target_q_key": (
                feature["occurred_on"], feature["normalized_merchant"],
            ),
            "target_r_key": (
                feature["posted_on"], feature["normalized_merchant"],
            ),
        })
    candidates.sort(key=lambda row: str(row["direct_event_key"]))
    return candidates


def _peer_model(
    groups: dict[object, list[dict[str, object]]], target: dict[str, object],
    key_name: str, output_names: tuple[str, ...],
) -> dict[str, object]:
    peers = [
        row for row in groups.get(target[key_name], [])
        if row["historical_row_sha256"] != target.get("excluded_row_sha256", "")
    ]
    peer_hashes = sorted({str(row["historical_row_sha256"]) for row in peers})
    excluded = str(target.get("excluded_row_sha256") or "")
    if excluded and excluded in peer_hashes:
        raise ValueError("classifier_target_row_in_peer_set")
    values = {
        tuple(str(row[name]) for name in output_names)
        for row in peers
    }
    output = next(iter(values)) if len(peer_hashes) >= MINIMUM_PEER_COUNT and len(values) == 1 else None
    return {
        "support": len(peer_hashes), "peer_hashes": peer_hashes,
        "peer_set_sha256": _set_sha(peer_hashes), "output": output,
        "unanimous": output is not None,
    }


def _existing_nonclassifier_decisions(db: object, payment_id: int) -> int:
    return int(db.execute(
        """SELECT COUNT(*) FROM current_classification_decisions d
           WHERE d.target_type='payment' AND d.target_id=?
             AND d.dimension IN ('account','cost_type','allocation_target')
             AND NOT EXISTS (
               SELECT 1 FROM direct_validated_classifier_decision_bindings b
               WHERE b.decision_id=d.id
             )""",
        (payment_id,),
    ).fetchone()[0])


def _schedule_status(
    occurred_on: str, target: str, trips: dict[str, dict[str, object]],
) -> tuple[str | None, list[str]]:
    try:
        current_day = date.fromisoformat(occurred_on)
    except ValueError:
        return None, []
    matches = sorted(
        code for code, trip in trips.items()
        if date.fromisoformat(str(trip["starts_on"])) <= current_day
        <= date.fromisoformat(str(trip["ends_on"]))
    )
    if len(matches) == 1:
        return ("unique_agreement" if matches[0] == target else None), matches
    return ("no_match" if not matches else "ambiguous_match"), matches


def _build_expected(db: object, run_id: str) -> dict[str, object]:
    training = _load_training(db)
    current = _load_current(db, run_id)
    associations = _historical_associations(training, current)
    seeds = _learning_seeds(training, associations)
    candidates = _current_candidates(current, associations)
    # This classifier is a candidate generator.  Final allocation/posting is
    # still gated by the strict schedule loader in direct_projection.
    trips = load_trip_schedule(db)
    groups: dict[str, dict[object, list[dict[str, object]]]] = {
        name: defaultdict(list) for name in (
            "account_a_key", "account_b_key", "target_q_key", "target_r_key",
        )
    }
    for row in seeds:
        for name, group in groups.items():
            group[row[name]].append(row)

    algorithm_core = {
        "model_contract": MODEL_CONTRACT,
        "normalization_contract": NORMALIZATION_CONTRACT,
        "minimum_peer_count": MINIMUM_PEER_COUNT,
        "models": {
            "account_a": ["source", "normalized_merchant"],
            "account_b": ["normalized_merchant"],
            "target_q": ["occurred_on", "normalized_merchant"],
            "target_r": ["posted_on", "normalized_merchant"],
        },
        "current_candidate_contract": "positive-current-purchase-only",
        "target_row_excluded_from_every_peer_set": True,
    }
    model_sha256 = _sha(algorithm_core)
    model_id = "validated-classifier-model:" + model_sha256

    predictions: list[dict[str, object]] = []
    withheld: list[dict[str, str]] = []
    validations: list[dict[str, object]] = []
    for target in candidates:
        models = {
            "account_a": _peer_model(
                groups["account_a_key"], target, "account_a_key",
                ("truth_account",),
            ),
            "account_b": _peer_model(
                groups["account_b_key"], target, "account_b_key",
                ("truth_account",),
            ),
            "target_q": _peer_model(
                groups["target_q_key"], target, "target_q_key",
                ("truth_target", "truth_cost_type"),
            ),
            "target_r": _peer_model(
                groups["target_r_key"], target, "target_r_key",
                ("truth_target", "truth_cost_type"),
            ),
        }
        reason = ""
        for name in ("account_a", "account_b", "target_q", "target_r"):
            if not reason and not models[name]["unanimous"]:
                reason = f"{name}_insufficient_or_conflicted"
        account_a = models["account_a"]["output"]
        account_b = models["account_b"]["output"]
        target_q = models["target_q"]["output"]
        target_r = models["target_r"]["output"]
        if not reason and account_a != account_b:
            reason = "account_models_disagree"
        if not reason and target_q != target_r:
            reason = "target_models_disagree"

        predicted_account = str(account_a[0]) if account_a else ""
        predicted_target = str(target_q[0]) if target_q else ""
        predicted_cost_type = str(target_q[1]) if target_q else ""
        if not reason and any(_is_adverse(value) for value in (
            predicted_account, predicted_cost_type, predicted_target,
        )):
            reason = "predicted_axis_adverse"
        if not reason and predicted_target not in trips:
            reason = "unsupported_allocation_target"
        if not reason and predicted_cost_type != "여행원가":
            reason = "trip_cost_type_inconsistent"

        schedule_status: str | None = None
        schedule_matches: list[str] = []
        if not reason:
            schedule_status, schedule_matches = _schedule_status(
                str(target["occurred_on"]), predicted_target, trips,
            )
            if schedule_status is None:
                reason = "unique_schedule_contradiction"
        if not reason and _existing_nonclassifier_decisions(
            db, int(target["payment_id"]),
        ):
            reason = "existing_authority_conflict"

        prediction = (predicted_account, predicted_cost_type, predicted_target)
        if reason:
            detail = {
                "reason": reason, "feature": target["feature"],
                "supports": {name: model["support"] for name, model in models.items()},
                "schedule_matches": schedule_matches,
            }
            withheld.append({
                "direct_event_key": str(target["direct_event_key"]),
                "current_evidence_id": str(target["current_evidence_id"]),
                "reason_code": reason, "detail_sha256": _sha(detail),
            })
            continue

        peer_payload = {
            name: model["peer_hashes"] for name, model in models.items()
        }
        feature_sha256 = _sha(target["feature"])
        loo_model_sha256 = _sha({
            "model_sha256": model_sha256,
            "peer_set_sha256": {
                name: model["peer_set_sha256"]
                for name, model in models.items()
            },
        })
        prediction_core = {
            "model_contract": MODEL_CONTRACT,
            "loo_model_sha256": loo_model_sha256,
            "feature_sha256": feature_sha256,
            "account": predicted_account,
            "cost_type": predicted_cost_type,
            "allocation_target": predicted_target,
            "peer_set_sha256": {
                name: model["peer_set_sha256"] for name, model in models.items()
            },
            "schedule_status": schedule_status,
        }
        prediction_sha256 = _sha(prediction_core)
        prediction_id = "validated-prediction:" + _sha({
            "prediction_sha256": prediction_sha256,
            "direct_event_key": target["direct_event_key"],
            "current_fact_sha256": target["current_fact_sha256"],
        })
        predictions.append({
            "prediction_id": prediction_id,
            "model_id": model_id,
            "direct_event_key": str(target["direct_event_key"]),
            "current_evidence_id": str(target["current_evidence_id"]),
            "payment_id": int(target["payment_id"]),
            "feature_sha256": feature_sha256,
            "loo_model_sha256": loo_model_sha256,
            "held_out_association_sha256": str(
                target["held_out_association_sha256"]
            ),
            "account": predicted_account, "cost_type": predicted_cost_type,
            "allocation_target": predicted_target,
            "account_a_support": int(models["account_a"]["support"]),
            "account_b_support": int(models["account_b"]["support"]),
            "target_q_support": int(models["target_q"]["support"]),
            "target_r_support": int(models["target_r"]["support"]),
            "account_a_peer_set_sha256": str(models["account_a"]["peer_set_sha256"]),
            "account_b_peer_set_sha256": str(models["account_b"]["peer_set_sha256"]),
            "target_q_peer_set_sha256": str(models["target_q"]["peer_set_sha256"]),
            "target_r_peer_set_sha256": str(models["target_r"]["peer_set_sha256"]),
            "schedule_status": str(schedule_status), "conflict_count": 0,
            "prediction_sha256": prediction_sha256,
            "peer_payload_json": _canonical(peer_payload).decode("utf-8"),
        })
        association = associations.get(str(target["direct_event_key"]))
        if association is not None:
            payload = association["payload"]
            assert isinstance(payload, dict)
            truth = (
                str(payload.get("account") or "").strip(),
                str(payload.get("cost_type") or "").strip(),
                str(payload.get("bucket") or "").strip(),
            )
            scorable = not any(_is_adverse(value) for value in truth)
            validations.append({
                "direct_event_key": target["direct_event_key"],
                "prediction_sha256": _sha(prediction),
                "held_out_row_sha256": association["row_sha256"],
                "held_out_truth_sha256": _sha(truth),
                "validation_status": "scored" if scorable else "adverse_truth",
                "agrees": scorable and prediction == truth,
            })

    predictions.sort(key=lambda row: str(row["direct_event_key"]))
    withheld.sort(key=lambda row: (row["direct_event_key"], row["reason_code"]))
    validation_errors = sum(not bool(row["agrees"]) for row in validations)
    schedule_counts = dict(sorted(Counter(
        str(row["schedule_status"]) for row in predictions
    ).items()))
    input_row = db.execute(
        """SELECT raw_sha256,record_count FROM direct_projection_inputs
           WHERE run_id=? AND source_kind=?""",
        (run_id, TRAINING_SOURCE_KIND),
    ).fetchone()
    if input_row is None or str(input_row[0]) != TRAINING_SOURCE_SHA256 or int(input_row[1]) != EXPECTED_TRAINING_ROWS:
        raise ValueError("classifier_training_input_manifest_mismatch")
    candidate_set_sha256 = _sha([
        {
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
            "feature_sha256": _sha(row["feature"]),
        }
        for row in candidates
    ])
    prediction_set_sha256 = _sha([
        {
            key: row[key] for key in (
                "prediction_id", "direct_event_key", "feature_sha256", "account",
                "cost_type", "allocation_target", "loo_model_sha256",
                "prediction_sha256",
            )
        }
        for row in predictions
    ])
    validation_set_sha256 = _sha(validations)
    learning_seed_set_sha256 = _set_sha(
        str(row["historical_row_sha256"]) for row in seeds
    )
    run_state_core = {
        "training_source_sha256": TRAINING_SOURCE_SHA256,
        "candidate_set_sha256": candidate_set_sha256,
        "learning_seed_set_sha256": learning_seed_set_sha256,
        "prediction_set_sha256": prediction_set_sha256,
        "validation_set_sha256": validation_set_sha256,
    }
    run_state_sha256 = _sha(run_state_core)
    reason_counts = dict(sorted(Counter(
        row["reason_code"] for row in withheld
    ).items()))
    payload = {
        **algorithm_core, **run_state_core, "model_id": model_id,
        "model_sha256": model_sha256,
        "run_state_sha256": run_state_sha256,
        "prediction_set_sha256": prediction_set_sha256,
        "validation_set_sha256": validation_set_sha256,
        "training_row_count": len(training), "candidate_count": len(candidates),
        "learning_seed_count": len(seeds),
        "promoted_count": len(predictions), "validation_count": len(validations),
        "validation_error_count": validation_errors,
        "training_role": TRAINING_ROLE,
        "target_historical_label_usage": "post_prediction_validation_only",
        "target_historical_fields_used_for_candidacy": False,
        "current_transaction_evidence": "current_card_only",
        "manual_or_historical_transaction_evidence_used": False,
        "schedule_absence_or_ambiguity_used_as_support": False,
        "schedule_unique_contradiction_blocks": True,
        "schedule_counts": schedule_counts, "withheld_reason_counts": reason_counts,
        "predicted_account_counts": dict(sorted(Counter(
            row["account"] for row in predictions
        ).items())),
        "predicted_target_counts": dict(sorted(Counter(
            row["allocation_target"] for row in predictions
        ).items())),
    }
    return {
        "model": {
            "model_id": model_id, "model_contract": MODEL_CONTRACT,
            "model_sha256": model_sha256,
            "run_state_sha256": run_state_sha256,
            "training_source_sha256": TRAINING_SOURCE_SHA256,
            "candidate_set_sha256": candidate_set_sha256,
            "prediction_set_sha256": prediction_set_sha256,
            "validation_set_sha256": validation_set_sha256,
            "training_row_count": len(training), "candidate_count": len(candidates),
            "promoted_count": len(predictions), "validation_count": len(validations),
            "validation_error_count": validation_errors,
            "minimum_peer_count": MINIMUM_PEER_COUNT,
            "training_role": TRAINING_ROLE,
            "payload_json": _canonical(payload).decode("utf-8"),
        },
        "predictions": predictions, "withheld": withheld,
        "validations": validations,
        "learning_seed_count": len(seeds),
        "schedule_counts": schedule_counts, "withheld_reason_counts": reason_counts,
    }


def _expected_census_issue(expected: dict[str, object]) -> str | None:
    model = expected["model"]
    assert isinstance(model, dict)
    schedule_counts = expected["schedule_counts"]
    if (
        int(expected["learning_seed_count"]) != EXPECTED_LEARNING_SEEDS
        or int(model["candidate_count"]) != EXPECTED_CANDIDATES
        or int(model["promoted_count"]) != EXPECTED_PROMOTED
        or int(model["validation_count"]) != EXPECTED_VALIDATIONS
        or int(model["validation_error_count"]) != 0
        or (
            EXPECTED_SCHEDULE_COUNTS
            and schedule_counts != EXPECTED_SCHEDULE_COUNTS
        )
    ):
        return (
            "classifier_validation_census_drift:"
            f"{expected['learning_seed_count']}:"
            f"{model['candidate_count']}:{model['promoted_count']}:"
            f"{model['validation_count']}:"
            f"{model['validation_error_count']}:{schedule_counts}"
        )
    return None


def project_validated_purchase_classifier(db: object, run_id: str) -> dict[str, object]:
    for table in (
        "direct_validated_classifier_models",
        "direct_validated_classifier_predictions",
        "direct_validated_classifier_axis_derivations",
        "direct_validated_classifier_decision_bindings",
        "direct_validated_classifier_withheld",
    ):
        if int(db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (run_id,),
        ).fetchone()[0]):
            raise ValueError("classifier_projection_already_exists")
    expected = _build_expected(db, run_id)
    census_issue = _expected_census_issue(expected)
    if census_issue is not None:
        raise ValueError(census_issue)
    model = expected["model"]
    db.execute("SAVEPOINT validated_classifier_projection")
    try:
        db.execute(
            """INSERT INTO direct_validated_classifier_models(
                 run_id,model_id,model_contract,model_sha256,
                 run_state_sha256,
                 training_source_sha256,candidate_set_sha256,
                 prediction_set_sha256,validation_set_sha256,
                 training_row_count,candidate_count,promoted_count,
                 validation_count,validation_error_count,minimum_peer_count,
                 training_role,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, model["model_id"], model["model_contract"],
                model["model_sha256"], model["run_state_sha256"],
                model["training_source_sha256"],
                model["candidate_set_sha256"], model["prediction_set_sha256"],
                model["validation_set_sha256"], model["training_row_count"],
                model["candidate_count"], model["promoted_count"],
                model["validation_count"], model["validation_error_count"],
                model["minimum_peer_count"], model["training_role"],
                model["payload_json"],
            ),
        )
        for withheld in expected["withheld"]:
            db.execute(
                """INSERT INTO direct_validated_classifier_withheld(
                     run_id,direct_event_key,current_evidence_id,reason_code,
                     detail_sha256) VALUES (?,?,?,?,?)""",
                (
                    run_id, withheld["direct_event_key"],
                    withheld["current_evidence_id"], withheld["reason_code"],
                    withheld["detail_sha256"],
                ),
            )
        for prediction in expected["predictions"]:
            db.execute(
                """INSERT INTO direct_validated_classifier_predictions(
                     run_id,prediction_id,model_id,direct_event_key,
                     current_evidence_id,payment_id,feature_sha256,
                     loo_model_sha256,held_out_association_sha256,account,cost_type,
                     allocation_target,account_a_support,account_b_support,
                     target_q_support,target_r_support,
                     account_a_peer_set_sha256,account_b_peer_set_sha256,
                     target_q_peer_set_sha256,target_r_peer_set_sha256,
                     schedule_status,conflict_count,prediction_sha256,
                     peer_payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, prediction["prediction_id"], prediction["model_id"],
                    prediction["direct_event_key"],
                    prediction["current_evidence_id"], prediction["payment_id"],
                    prediction["feature_sha256"],
                    prediction["loo_model_sha256"],
                    prediction["held_out_association_sha256"],
                    prediction["account"], prediction["cost_type"],
                    prediction["allocation_target"],
                    prediction["account_a_support"],
                    prediction["account_b_support"],
                    prediction["target_q_support"],
                    prediction["target_r_support"],
                    prediction["account_a_peer_set_sha256"],
                    prediction["account_b_peer_set_sha256"],
                    prediction["target_q_peer_set_sha256"],
                    prediction["target_r_peer_set_sha256"],
                    prediction["schedule_status"], prediction["conflict_count"],
                    prediction["prediction_sha256"],
                    prediction["peer_payload_json"],
                ),
            )
            axes = {
                "account": prediction["account"],
                "cost_type": prediction["cost_type"],
                "allocation_target": prediction["allocation_target"],
            }
            for dimension in ACTIVE_DIMENSIONS:
                value = str(axes[dimension])
                derivation_id = "classifier-derivation:" + _sha({
                    "prediction_id": prediction["prediction_id"],
                    "dimension": dimension, "value": value,
                })
                decision_id = int(db.execute(
                    """INSERT INTO classification_decisions(
                         target_type,target_id,dimension,value,confidence,
                         confidence_label,decision_status,rule_id,rationale)
                       VALUES ('payment',?,?,?,?,?,'confirmed',?,?)""",
                    (
                        prediction["payment_id"], dimension, value, 1.0,
                        "과거정답제외4중교차검증", RULE_ID, RATIONALE,
                    ),
                ).lastrowid)
                db.execute(
                    """INSERT INTO direct_validated_classifier_axis_derivations(
                         derivation_id,run_id,model_id,prediction_id,payment_id,
                         direct_event_key,dimension,value,rule_id,
                         current_evidence_id,derivation_status,conflict_count)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'pass',0)""",
                    (
                        derivation_id, run_id, prediction["model_id"],
                        prediction["prediction_id"], prediction["payment_id"],
                        prediction["direct_event_key"], dimension, value,
                        RULE_ID, prediction["current_evidence_id"],
                    ),
                )
                db.execute(
                    """INSERT INTO direct_validated_classifier_decision_bindings(
                         run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                    (run_id, decision_id, derivation_id),
                )
    except Exception:
        db.execute("ROLLBACK TO validated_classifier_projection")
        db.execute("RELEASE validated_classifier_projection")
        raise
    else:
        db.execute("RELEASE validated_classifier_projection")
    return {
        "model_id": model["model_id"],
        "training_role": TRAINING_ROLE,
        "candidate_count": model["candidate_count"],
        "promoted_payment_count": model["promoted_count"],
        "decision_count": int(model["promoted_count"]) * len(ACTIVE_DIMENSIONS),
        "withheld_payment_count": len(expected["withheld"]),
        "validation_count": model["validation_count"],
        "validation_error_count": model["validation_error_count"],
        "schedule_counts": expected["schedule_counts"],
        "withheld_reason_counts": expected["withheld_reason_counts"],
        "manual_or_historical_transaction_evidence_used": False,
    }


def validate_validated_purchase_classifier(
    db: object, run_id: str, *, require_allocations: bool = False,
) -> dict[str, object]:
    issues: list[str] = []
    try:
        expected = _build_expected(db, run_id)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "passed": False, "issues": [f"expected_rebuild_failed:{exc}"],
            "promoted_payment_count": 0, "decision_count": 0,
        }
    census_issue = _expected_census_issue(expected)
    if census_issue is not None:
        issues.append(census_issue)
    model = expected["model"]
    expected_model = [
        model[name] for name in (
            "model_id", "model_contract", "model_sha256",
            "run_state_sha256",
            "training_source_sha256", "candidate_set_sha256",
            "prediction_set_sha256", "validation_set_sha256",
            "training_row_count", "candidate_count", "promoted_count",
            "validation_count", "validation_error_count", "minimum_peer_count",
            "training_role", "payload_json",
        )
    ]
    actual_model_row = db.execute(
        """SELECT model_id,model_contract,model_sha256,run_state_sha256,
                  training_source_sha256,
                  candidate_set_sha256,prediction_set_sha256,
                  validation_set_sha256,training_row_count,candidate_count,
                  promoted_count,validation_count,validation_error_count,
                  minimum_peer_count,training_role,payload_json
           FROM direct_validated_classifier_models WHERE run_id=?""",
        (run_id,),
    ).fetchone()
    if actual_model_row is None or list(actual_model_row) != expected_model:
        issues.append("classifier_model_mismatch")

    prediction_fields = (
        "prediction_id", "model_id", "direct_event_key", "current_evidence_id",
        "payment_id", "feature_sha256", "loo_model_sha256",
        "held_out_association_sha256",
        "account", "cost_type", "allocation_target", "account_a_support",
        "account_b_support", "target_q_support", "target_r_support",
        "account_a_peer_set_sha256", "account_b_peer_set_sha256",
        "target_q_peer_set_sha256", "target_r_peer_set_sha256",
        "schedule_status", "conflict_count", "prediction_sha256",
        "peer_payload_json",
    )
    expected_predictions = sorted(
        [tuple(row[name] for name in prediction_fields) for row in expected["predictions"]]
    )
    actual_predictions = [tuple(row) for row in db.execute(
        """SELECT prediction_id,model_id,direct_event_key,current_evidence_id,
                  payment_id,feature_sha256,loo_model_sha256,
                  held_out_association_sha256,
                  account,cost_type,allocation_target,account_a_support,
                  account_b_support,target_q_support,target_r_support,
                  account_a_peer_set_sha256,account_b_peer_set_sha256,
                  target_q_peer_set_sha256,target_r_peer_set_sha256,
                  schedule_status,conflict_count,prediction_sha256,
                  peer_payload_json
           FROM direct_validated_classifier_predictions WHERE run_id=?
           ORDER BY prediction_id""",
        (run_id,),
    ).fetchall()]
    if expected_predictions != actual_predictions:
        issues.append("classifier_prediction_set_mismatch")

    expected_withheld = sorted(
        (
            row["direct_event_key"], row["current_evidence_id"],
            row["reason_code"], row["detail_sha256"],
        )
        for row in expected["withheld"]
    )
    actual_withheld = [tuple(row) for row in db.execute(
        """SELECT direct_event_key,current_evidence_id,reason_code,detail_sha256
           FROM direct_validated_classifier_withheld WHERE run_id=?
           ORDER BY direct_event_key,reason_code""",
        (run_id,),
    ).fetchall()]
    if expected_withheld != actual_withheld:
        issues.append("classifier_withheld_set_mismatch")

    expected_decisions = []
    for prediction in expected["predictions"]:
        axes = {
            "account": prediction["account"],
            "cost_type": prediction["cost_type"],
            "allocation_target": prediction["allocation_target"],
        }
        for dimension in ACTIVE_DIMENSIONS:
            value = str(axes[dimension])
            derivation_id = "classifier-derivation:" + _sha({
                "prediction_id": prediction["prediction_id"],
                "dimension": dimension, "value": value,
            })
            expected_decisions.append((
                prediction["prediction_id"], prediction["direct_event_key"],
                dimension, value, RULE_ID, prediction["current_evidence_id"],
                derivation_id, 1.0, "과거정답제외4중교차검증", "confirmed",
                RULE_ID, RATIONALE,
            ))
    expected_decisions.sort()
    actual_decisions = [tuple(row) for row in db.execute(
        """SELECT x.prediction_id,x.direct_event_key,x.dimension,x.value,
                  x.rule_id,x.current_evidence_id,x.derivation_id,d.confidence,
                  d.confidence_label,d.decision_status,d.rule_id,d.rationale
           FROM direct_validated_classifier_axis_derivations x
           JOIN direct_validated_classifier_decision_bindings b
             ON b.run_id=x.run_id AND b.derivation_id=x.derivation_id
           JOIN classification_decisions d ON d.id=b.decision_id
           WHERE x.run_id=? AND d.target_type='payment'
             AND d.target_id=x.payment_id AND d.dimension=x.dimension
             AND d.value=x.value
           ORDER BY x.prediction_id,x.direct_event_key,x.dimension""",
        (run_id,),
    ).fetchall()]
    if expected_decisions != actual_decisions:
        issues.append("classifier_decision_set_mismatch")

    promoted = int(db.execute(
        """SELECT COUNT(DISTINCT d.target_id)
           FROM current_independently_promoted_decisions d
           JOIN direct_validated_classifier_decision_bindings b
             ON b.run_id=d.run_id AND b.decision_id=d.id
           WHERE d.run_id=?""",
        (run_id,),
    ).fetchone()[0])
    if promoted != EXPECTED_PROMOTED:
        issues.append("classifier_promoted_view_mismatch")

    if require_allocations:
        actual_allocations = [tuple(row) for row in db.execute(
            """SELECT p.direct_event_key,t.code,a.amount_krw
               FROM direct_validated_classifier_predictions p
               JOIN current_cost_allocations a ON a.payment_id=p.payment_id
               JOIN allocation_targets t ON t.id=a.target_id
               WHERE p.run_id=? ORDER BY p.direct_event_key""",
            (run_id,),
        ).fetchall()]
        expected_allocations = sorted(
            (
                row["direct_event_key"], row["allocation_target"],
                int(db.execute(
                    "SELECT amount_krw FROM payment_transactions WHERE id=?",
                    (row["payment_id"],),
                ).fetchone()[0]),
            )
            for row in expected["predictions"]
        )
        if actual_allocations != expected_allocations:
            issues.append("classifier_allocation_set_mismatch")
    return {
        "passed": not issues, "issues": issues,
        "model_id": model["model_id"],
        "candidate_count": model["candidate_count"],
        "promoted_payment_count": len(expected["predictions"]),
        "decision_count": len(expected_decisions),
        "withheld_payment_count": len(expected["withheld"]),
        "validation_count": model["validation_count"],
        "validation_error_count": model["validation_error_count"],
        "schedule_counts": expected["schedule_counts"],
    }
