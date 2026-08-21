import unittest

from ledger.domain.direct_structural_rule_admission import (
    PACKAGE_B_CORE_PATHS,
    PACKAGE_B_PATHS,
    PACKAGE_C_PATHS,
    admission_manifest,
    normalize_admitted_rule_paths,
    paths_for_package,
)


class StructuralRuleAdmissionTest(unittest.TestCase):
    def test_default_package_is_fail_closed(self) -> None:
        self.assertEqual(paths_for_package("none"), frozenset())
        self.assertEqual(normalize_admitted_rule_paths(None), frozenset())

    def test_package_b_contains_only_the_four_ordered_scopes(self) -> None:
        self.assertEqual(paths_for_package("package-b"), frozenset(PACKAGE_B_PATHS))
        manifest = admission_manifest(paths_for_package("package-b"))
        self.assertEqual(manifest["contract"], "structural-rule-admission-v1")
        self.assertEqual(manifest["admitted_paths"], list(PACKAGE_B_PATHS))
        self.assertEqual(manifest["application_order"], list(PACKAGE_B_PATHS))
        self.assertEqual(manifest["item_level_approval"], "forbidden")
        self.assertFalse(manifest["auto_authorization"])
        self.assertFalse(manifest["finalization_permission"])
        self.assertFalse(manifest["posting_permission"])

    def test_package_b_core_excludes_inferred_external_scope(self) -> None:
        self.assertEqual(
            paths_for_package("package-b-core"),
            frozenset(PACKAGE_B_CORE_PATHS),
        )
        manifest = admission_manifest(paths_for_package("package-b-core"))
        self.assertEqual(manifest["package"], "package-b-core")
        self.assertEqual(manifest["admitted_paths"], list(PACKAGE_B_CORE_PATHS))
        self.assertNotIn(
            "current_card_inferred_external_target",
            manifest["admitted_paths"],
        )
        self.assertFalse(manifest["finalization_permission"])
        self.assertFalse(manifest["posting_permission"])

    def test_package_c_adds_only_three_grouped_paths_and_leaves_five(self) -> None:
        self.assertEqual(
            paths_for_package("package-c"), frozenset(PACKAGE_C_PATHS)
        )
        manifest = admission_manifest(paths_for_package("package-c"))
        self.assertEqual(manifest["package"], "package-c")
        self.assertEqual(manifest["admitted_paths"], list(PACKAGE_C_PATHS))
        self.assertEqual(
            list(PACKAGE_C_PATHS)[len(PACKAGE_B_PATHS):],
            [
                "current_card_geography_context_exact_2026",
                "manual_travel_tab_reversal_exact",
                "manual_travel_tab_reversal_mn_target_invariant",
            ],
        )
        self.assertFalse(manifest["finalization_permission"])
        self.assertFalse(manifest["posting_permission"])

    def test_unknown_path_and_package_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "path_unknown"):
            normalize_admitted_rule_paths(["not-a-real-scope"])
        with self.assertRaisesRegex(ValueError, "package_unknown"):
            paths_for_package("package-z")


if __name__ == "__main__":
    unittest.main()
