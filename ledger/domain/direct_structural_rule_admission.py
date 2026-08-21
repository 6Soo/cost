"""Explicit, run-scoped admission of grouped structural-rule exceptions.

The package is a rule choice, not a row-level approval.  The default package
is ``none``; callers must name a package when they intentionally want the
staged exceptions used by the temporary-under-five goal.
"""
from __future__ import annotations

from collections.abc import Iterable


CONTRACT = "structural-rule-admission-v1"
PACKAGE_NONE = "none"
PACKAGE_B_CORE = "package-b-core"
PACKAGE_B = "package-b"
PACKAGE_C = "package-c"

# Ordered from the strongest structural grouping to the weakest one.  The
# order is also used in aggregate what-if reports and is deliberately kept
# free of payment IDs, merchant names, and source-row identifiers.
PACKAGE_B_PATHS = (
    "current_card_trip_cluster_registry_exact",
    "current_card_travel_activity_placeholder",
    "current_card_reservation_placeholder",
    "current_card_inferred_external_target",
)

# The minimal package keeps the three registry-backed paths and excludes the
# inferred-external path.  It is useful for a shadow comparison when the
# caller wants to meet the coverage target without admitting the weakest
# structural family in package B.
PACKAGE_B_CORE_PATHS = PACKAGE_B_PATHS[:3]

# Package C adds only the three remaining grouped paths needed to reduce the
# current auto-provisional queue from 88 to 5.  The two manual-reversal paths
# remain terminal/no-inheritance paths; they never authorize reversal-axis
# inheritance or financial allocation.
PACKAGE_C_PATHS = PACKAGE_B_PATHS + (
    "current_card_geography_context_exact_2026",
    "manual_travel_tab_reversal_exact",
    "manual_travel_tab_reversal_mn_target_invariant",
)


def normalize_admitted_rule_paths(
    paths: Iterable[str] | None,
) -> frozenset[str]:
    """Validate a concrete path allow-list and return it immutably."""
    if paths is None:
        return frozenset()
    normalized = frozenset(str(path).strip() for path in paths if str(path).strip())
    unknown = normalized - set(PACKAGE_C_PATHS)
    if unknown:
        raise ValueError(
            "structural_rule_admission_path_unknown:" + ",".join(sorted(unknown))
        )
    return normalized


def paths_for_package(package: str | None) -> frozenset[str]:
    """Resolve the named package; absence means the unchanged fail-closed mode."""
    name = PACKAGE_NONE if package is None else str(package).strip().lower()
    if name == PACKAGE_NONE:
        return frozenset()
    if name == PACKAGE_B_CORE:
        return frozenset(PACKAGE_B_CORE_PATHS)
    if name == PACKAGE_B:
        return frozenset(PACKAGE_B_PATHS)
    if name == PACKAGE_C:
        return frozenset(PACKAGE_C_PATHS)
    raise ValueError(f"structural_rule_admission_package_unknown:{name}")


def package_for_paths(paths: Iterable[str] | None) -> str:
    """Return the package label for an allow-list used in an audit payload."""
    normalized = normalize_admitted_rule_paths(paths)
    if not normalized:
        return PACKAGE_NONE
    if normalized == frozenset(PACKAGE_B_CORE_PATHS):
        return PACKAGE_B_CORE
    if normalized == frozenset(PACKAGE_B_PATHS):
        return PACKAGE_B
    if normalized == frozenset(PACKAGE_C_PATHS):
        return PACKAGE_C
    return "custom"


def admission_manifest(paths: Iterable[str] | None) -> dict[str, object]:
    """Build a small, non-row-level audit payload for the selected rule set."""
    normalized = normalize_admitted_rule_paths(paths)
    ordered = [path for path in PACKAGE_C_PATHS if path in normalized]
    return {
        "contract": CONTRACT,
        "package": package_for_paths(normalized),
        "authorized_scope": "classification_path",
        "item_level_approval": "forbidden",
        "auto_authorization": False,
        "admitted_paths": ordered,
        "application_order": ordered,
        "finalization_permission": False,
        "posting_permission": False,
        # The package may close an already grouped relationship-conflict row
        # only as a terminal, no-allocation disposition.  It never authorizes
        # reversal inheritance or an item-level relation claim.
        "relationship_question_overlap": "allowed_without_inheritance",
        "rollback_identity": "run_id+candidate_semantic_sha256+gate_report_sha256",
    }
