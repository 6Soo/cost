"""Group non-final rows into rule-admission requests.

The output of this module is a policy-request surface, not an approval or a
promotion mechanism. A user authorizes one structural failure family and
classification-path scope at a time; the implementation of that rule remains
a separate, fail-closed change.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from collections.abc import Iterable, Mapping


STRUCTURAL_RULE_REQUEST_CONTRACT = "structural-rule-admission-v1"
ITEM_LEVEL_APPROVAL_MODE = "forbidden"
RULE_AUTO_AUTHORIZATION = False


_VETO_FAMILY_BY_CODE = {
    "review_or_provisional_target_path": "review_or_provisional_target",
    "target_not_finally_allocable": "target_not_allocable",
    "manual_target_authority_missing": "manual_target_authority_missing",
    "manual_target_reference_missing": "manual_target_reference_missing",
    "ota_service_period_evidence_missing": "service_period_evidence_missing",
    "ota_lifecycle_not_closed": "lifecycle_not_closed",
    "ota_evidence_record_invalid": "external_evidence_invalid",
    "ota_amount_source_binding_missing": "external_amount_binding_missing",
    "ota_lifecycle_source_binding_missing": "external_lifecycle_binding_missing",
    "ota_amount_match_policy_missing": "amount_policy_missing",
    "ota_amount_tolerance_method_mismatch": "amount_policy_missing",
    "ota_amount_tolerance_path_missing": "amount_policy_missing",
    "ota_amount_difference_ratio_invalid": "amount_policy_missing",
    "ota_exact_card_mail_cardinality_invalid": "card_mail_cardinality_invalid",
    "ota_mn_card_mail_cardinality_invalid": "card_mail_cardinality_invalid",
    "reversal_inheritance_not_exact": "reversal_inheritance_not_exact",
    "canonical_trip_registry_missing": "canonical_trip_registry_missing",
}

_FAMILY_DESCRIPTION = {
    "review_or_provisional_target": "review/provisional 대상 경로 자체가 최종화를 차단",
    "target_not_allocable": "대상이 세 축 최종 배정 계약을 충족하지 않음",
    "manual_target_authority_missing": "수기 대상의 현재 권한 또는 승인 근거가 없음",
    "manual_target_reference_missing": "수기 대상 참조가 현재 거래에 결속되지 않음",
    "service_period_evidence_missing": "독립 서비스 기간 증거가 없음",
    "lifecycle_not_closed": "예약·변경·취소 lifecycle이 종료 상태가 아님",
    "external_evidence_invalid": "외부 증거 레코드가 계약 형식·무결성을 충족하지 않음",
    "external_amount_binding_missing": "외부 금액 증거가 현재 카드에 결속되지 않음",
    "external_lifecycle_binding_missing": "lifecycle 증거가 현재 카드·원천에 결속되지 않음",
    "amount_policy_missing": "정확 금액 또는 명시적 조정식 계약이 없음",
    "card_mail_cardinality_invalid": "카드·메일 대응 cardinality가 유일/허용 M:N 계약이 아님",
    "reversal_inheritance_not_exact": "환불·취소가 확정 원거래에 정확히 연결되지 않음",
    "canonical_trip_registry_missing": "최종 대상에 필요한 정식 여행 레지스트리가 없음",
    "classifier_prediction_missing": "비최종 행에 현재 분류 예측이 없음",
    "unclassified_nonfinal": "비최종이지만 구조적 veto를 판독할 수 없음",
}

_RULE_SHAPE_BY_FAMILY = {
    "review_or_provisional_target": "review/provisional path를 예외 허용할 explicit target·period·authority rule",
    "target_not_allocable": "세 축 미완성을 예외 허용할 보완증거·상한·rollback rule",
    "manual_target_authority_missing": "현재 owner authority와 current-card binding을 함께 검증하는 rule",
    "manual_target_reference_missing": "현재 event/fact/evidence hash의 1:1 또는 명시된 M:N 결속 rule",
    "service_period_evidence_missing": "독립 원천의 서비스 기간과 현재 카드의 exact binding rule",
    "lifecycle_not_closed": "unknown lifecycle을 예외 허용하되 exact binding·no-conflict·최신 원천 hash를 요구하는 rule",
    "external_evidence_invalid": "외부 레코드 schema·content hash·source provenance를 검증하는 rule",
    "external_amount_binding_missing": "현재 카드 foreign/currency/amount와 외부 금액의 exact binding rule",
    "external_lifecycle_binding_missing": "현재 카드와 최신 lifecycle source의 exact binding rule",
    "amount_policy_missing": "exact amount 또는 사용자 명시 조정식을 허용하는 rule",
    "card_mail_cardinality_invalid": "허용 cardinality·중복 방지·cross-card 금지 조건을 명시한 rule",
    "reversal_inheritance_not_exact": "확정 원거래와 reversal relation의 단일 상속 rule",
    "canonical_trip_registry_missing": "독립 일정·현재 거래·대상 registry의 hash 결속 rule",
    "classifier_prediction_missing": "현재 거래 전체를 덮는 fail-closed prediction coverage rule",
    "unclassified_nonfinal": "먼저 미분류 원인을 구조화하는 진단 rule; 즉시 finalization 금지",
}

_WEAK_EVIDENCE_SOURCE_KINDS = frozenset({
    "classifier_training",
    "manual_ledger",
    "geographic_trip_context",
    "trip_cluster_registry",
})
_INDEPENDENT_EVIDENCE_SOURCE_KINDS = frozenset({
    "ota_mail",
    "ota_mail_live",
    "ota_lodging_fact",
    "authenticated_booking_portal",
})


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _membership_sha256(payment_ids: Iterable[int]) -> str:
    return sha256(
        _canonical_json_bytes(sorted({int(payment_id) for payment_id in payment_ids}))
    ).hexdigest()


def _axis_payload(row: Mapping[str, object]) -> Mapping[str, object] | None:
    raw = row.get("axis_evidence_json")
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _veto_codes(row: Mapping[str, object]) -> tuple[str, ...] | None:
    payload = _axis_payload(row)
    if payload is None:
        return None
    finality = payload.get("row_finality")
    if not isinstance(finality, Mapping):
        return None
    vetoes = finality.get("vetoes")
    if not isinstance(vetoes, list) or any(
        not isinstance(veto, str) or not veto for veto in vetoes
    ):
        return None
    return tuple(sorted(set(vetoes)))


def _classification_path(row: Mapping[str, object]) -> str:
    raw = str(row.get("rule_path") or "").strip()
    if not raw:
        return "<missing>"
    parts = raw.split("|")
    return parts[1] if len(parts) > 1 and parts[1] else raw


def _request_slug(value: str) -> str:
    slug = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in value
    ).strip("_")
    return slug or "unknown"


def _family_for_veto(veto: str) -> str:
    return _VETO_FAMILY_BY_CODE.get(veto, "unclassified_nonfinal")


def _evidence_summary(
    row: Mapping[str, object],
) -> tuple[str, tuple[str, ...], Counter[str], Counter[str]]:
    payload = _axis_payload(row)
    refs = payload.get("target_evidence_refs", []) if payload else []
    source_kinds: set[str] = set()
    roles: set[str] = set()
    source_counts: Counter[str] = Counter()
    if isinstance(refs, list):
        for ref in refs:
            if not isinstance(ref, Mapping):
                continue
            source_kind = str(ref.get("source_kind") or "<missing>")
            role = str(ref.get("evidence_role") or "<missing>")
            source_kinds.add(source_kind)
            roles.add(role)
            source_counts[source_kind] += 1
    if source_kinds & _WEAK_EVIDENCE_SOURCE_KINDS:
        composition = (
            "independent_plus_weak"
            if source_kinds & _INDEPENDENT_EVIDENCE_SOURCE_KINDS
            else "weak_only"
        )
    elif source_kinds & _INDEPENDENT_EVIDENCE_SOURCE_KINDS:
        composition = "independent_only"
    elif "gmail_payment_snapshot" in source_kinds:
        composition = "gmail_only"
    else:
        composition = "current_or_other_only"
    strict_roles = tuple(sorted({
        role_name
        for role, role_name in {
            "ota_service_period": "service_period_role",
            "ota_amount_fact": "amount_role",
            "ota_lifecycle_latest": "lifecycle_role",
        }.items()
        if role in roles
    }))
    return composition, strict_roles, source_counts, Counter(roles)


def _empty_report(nonfinal_count: int = 0) -> dict[str, object]:
    return {
        "contract": STRUCTURAL_RULE_REQUEST_CONTRACT,
        "decision_unit": "structural_failure_group",
        "item_level_approval": ITEM_LEVEL_APPROVAL_MODE,
        "rule_auto_authorization": RULE_AUTO_AUTHORIZATION,
        "side_effects_before_authorization": {
            "confirmed_decision": False,
            "allocation_plan": False,
            "cost_allocation": False,
            "journal_or_posting": False,
            "reversal_inheritance": False,
        },
        "nonfinal_payment_count": int(nonfinal_count),
        "rule_request_group_count": 0,
        "affected_payment_count": 0,
        "overlap_payment_count": 0,
        "coverage_invariant": int(nonfinal_count) == 0,
        "groups": [],
    }


def build_structural_rule_request_report(
    predictions: Iterable[Mapping[str, object]],
    nonfinal_payment_ids: Iterable[int],
) -> dict[str, object]:
    """Build aggregate rule requests for the supplied non-final payments.

    The report intentionally contains no payment IDs, event keys, merchants,
    amounts, dates, or target names.  A payment can belong to several groups
    when it has multiple independent blockers; ``affected_payment_count`` is
    therefore a unique union count, not a sum of group counts.
    """
    nonfinal = {int(payment_id) for payment_id in nonfinal_payment_ids}
    if not nonfinal:
        return _empty_report()

    by_payment: dict[int, Mapping[str, object]] = {}
    for row in predictions:
        try:
            payment_id = int(row.get("payment_id"))
        except (TypeError, ValueError):
            continue
        if payment_id in nonfinal and payment_id not in by_payment:
            by_payment[payment_id] = row

    members_by_scope: dict[tuple[str, str], set[int]] = defaultdict(set)
    vetoes_by_scope: dict[tuple[str, str], set[str]] = defaultdict(set)
    evidence_composition_by_scope: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    strict_roles_by_scope: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    source_kinds_by_scope: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    families_by_payment: dict[int, set[str]] = {}
    for payment_id in sorted(nonfinal):
        row = by_payment.get(payment_id)
        if row is None:
            families = {"classifier_prediction_missing"}
            raw_vetoes: tuple[str, ...] = ()
            path = "<missing>"
        else:
            raw_vetoes = _veto_codes(row) or ()
            families = {
                _family_for_veto(veto)
                for veto in raw_vetoes
            } or {"unclassified_nonfinal"}
            path = _classification_path(row)
        families_by_payment[payment_id] = set(families)
        composition, strict_roles, source_counts, _ = (
            _evidence_summary(row) if row is not None
            else ("current_or_other_only", (), Counter(), Counter())
        )
        for family in families:
            scope = (family, path)
            members_by_scope[scope].add(payment_id)
            vetoes_by_scope[scope].update(raw_vetoes)
            evidence_composition_by_scope[scope][composition] += 1
            strict_roles_by_scope[scope][
                "+".join(strict_roles) if strict_roles else "none"
            ] += 1
            source_kinds_by_scope[scope].update(source_counts)

    union_members = set().union(*members_by_scope.values())
    overlap_members = set()
    scope_items = sorted(members_by_scope.items())
    for index, (_, members) in enumerate(scope_items):
        for _, other in scope_items[index + 1:]:
            overlap_members.update(members & other)

    groups: list[dict[str, object]] = []
    for index, ((family, path), members) in enumerate(scope_items, start=1):
        other_blockers = Counter(
            other_family
            for payment_id in members
            for other_family in families_by_payment[payment_id]
            if other_family != family
        )
        veto_only_release_candidates = sum(
            1
            for payment_id in members
            if families_by_payment[payment_id] == {family}
        )
        groups.append({
            "request_id": (
                f"structural-rule-{index:03d}-{_request_slug(family)}-"
                f"{_request_slug(path)}"
            ),
            "status": "awaiting_user_rule_authorization",
            "structural_failure_family": family,
            "classification_path": path,
            "description": _FAMILY_DESCRIPTION.get(family, family),
            "affected_payment_count": len(members),
            "veto_only_release_candidate_count": veto_only_release_candidates,
            "other_blocker_family_counts": dict(sorted(other_blockers.items())),
            "membership_sha256": _membership_sha256(members),
            "source_veto_codes": sorted(vetoes_by_scope[(family, path)]),
            "classification_path_counts": {path: len(members)},
            "evidence_composition_counts": dict(
                sorted(evidence_composition_by_scope[(family, path)].items())
            ),
            "strict_evidence_role_counts": dict(
                sorted(strict_roles_by_scope[(family, path)].items())
            ),
            "evidence_source_kind_counts": dict(
                sorted(source_kinds_by_scope[(family, path)].items())
            ),
            "evidence_source_kind_count_unit": "references",
            "rule_shape": _RULE_SHAPE_BY_FAMILY.get(family, "명시적 포함·제외 predicate를 갖춘 bounded rule"),
            "user_decision": {
                "allowed_values": ["allow_rule", "keep_blocked"],
                "item_level_approval": "not_requested",
                "required_rule_contract": [
                    "inclusion_predicate",
                    "exclusion_predicate",
                    "evidence_binding",
                    "side_effect_invariants",
                    "rollback_identity",
                ],
            },
        })

    report = _empty_report(len(nonfinal))
    report.update({
        "rule_request_group_count": len(groups),
        "affected_payment_count": len(union_members),
        "overlap_payment_count": len(overlap_members),
        "coverage_invariant": union_members == nonfinal,
        "groups": groups,
    })
    return report


def simulate_structural_rule_admission(
    predictions: Iterable[Mapping[str, object]],
    nonfinal_payment_ids: Iterable[int],
    ordered_request_ids: Iterable[str],
) -> dict[str, object]:
    """Return a side-effect-free what-if reduction for approved rule scopes.

    This function deliberately does not mutate predictions or create any
    decision/allocation/posting rows.  It answers only: if the named
    structural scopes were later implemented and each affected row passed its
    separate rule contract, how many rows would remain in the non-final lane?
    """
    prediction_rows = list(predictions)
    nonfinal = {int(payment_id) for payment_id in nonfinal_payment_ids}
    request_report = build_structural_rule_request_report(
        prediction_rows, nonfinal,
    )
    groups_by_id = {
        str(group["request_id"]): group
        for group in request_report["groups"]
        if isinstance(group, Mapping)
    }
    remaining = set(nonfinal)
    stages: list[dict[str, object]] = []
    for request_id in ordered_request_ids:
        request_key = str(request_id)
        group = groups_by_id.get(request_key)
        if group is None:
            raise ValueError("structural_rule_simulation_request_unknown")
        # Membership hashes are intentionally not reversed here: simulation
        # receives the candidate membership through its aggregate report and
        # only uses the reported count.  Actual implementation must re-run the
        # rule predicate against current facts before promotion.
        path = str(group.get("classification_path") or "")
        family = str(group.get("structural_failure_family") or "")
        affected = int(group.get("affected_payment_count") or 0)
        # Reconstruct the scope from the immutable input rather than trusting
        # a count supplied by a caller.
        scope_members: set[int] = set()
        for row in prediction_rows:
            try:
                payment_id = int(row.get("payment_id"))
            except (TypeError, ValueError):
                continue
            if payment_id not in remaining:
                continue
            if _classification_path(row) != path:
                continue
            vetoes = _veto_codes(row) or ()
            if family not in {_family_for_veto(veto) for veto in vetoes}:
                continue
            scope_members.add(payment_id)
        newly_reduced = remaining & scope_members
        remaining -= newly_reduced
        stages.append({
            "request_id": request_key,
            "classification_path": path,
            "structural_failure_family": family,
            "reported_affected_payment_count": affected,
            "newly_reduced_candidate_count": len(newly_reduced),
            "remaining_nonfinal_candidate_count": len(remaining),
            "simulation_only": True,
            "side_effects_created": False,
        })
    return {
        "contract": STRUCTURAL_RULE_REQUEST_CONTRACT,
        "simulation_only": True,
        "nonfinal_payment_count": len(nonfinal),
        "candidate_reduced_count": len(nonfinal) - len(remaining),
        "candidate_remaining_nonfinal_count": len(remaining),
        "side_effects_created": False,
        "stages": stages,
    }
