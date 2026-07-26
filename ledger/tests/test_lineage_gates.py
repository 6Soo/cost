from __future__ import annotations

import unittest

from ledger.domain.lineage_gates import (
    lineage_semantic_counts,
    require_protected_uids_preserved,
    require_raw_cancellation_signs,
    require_valid_nonposting_aliases,
    require_zero_non_agoda_unresolved,
)


class LineageGateTest(unittest.TestCase):
    def test_non_agoda_unresolved_is_a_hard_regression_gate(self) -> None:
        agoda_only = [
            {
                "uid": "KBO-AGODA-1",
                "source_event_id": "legacy:KBO-AGODA-1",
                "source_event_disposition": "raw_card_unresolved",
                "merchant": "AGODA.COM",
            }
        ]
        require_zero_non_agoda_unresolved(agoda_only)
        self.assertEqual(
            lineage_semantic_counts(agoda_only),
            {
                "projection_rows": 1,
                "source_event_ids": 1,
                "unresolved_total": 1,
                "unresolved_agoda": 1,
                "unresolved_non_agoda": 0,
                "nonposting_rows": 0,
                "dispositions": {"raw_card_unresolved": 1},
            },
        )

        non_agoda = agoda_only + [
            {
                "uid": "KBO-RECUR-1",
                "source_event_id": "legacy:KBO-RECUR-1",
                "source_event_disposition": "raw_card_unresolved",
                "merchant": "HERTZ",
            }
        ]
        with self.assertRaisesRegex(RuntimeError, "non-Agoda card lineage"):
            require_zero_non_agoda_unresolved(non_agoda)
        self.assertEqual(lineage_semantic_counts(non_agoda)["unresolved_non_agoda"], 1)

    def test_kbo_9002_cannot_be_deleted_between_projections(self) -> None:
        before = [{"uid": "KBO-9002"}, {"uid": "KBO-OTHER"}]
        require_protected_uids_preserved(before, before, {"KBO-9002"})
        with self.assertRaisesRegex(RuntimeError, "KBO-9002"):
            require_protected_uids_preserved(before, [{"uid": "KBO-OTHER"}], {"KBO-9002"})

    def test_all_nonposting_dispositions_are_explicit_audit_aliases(self) -> None:
        rows = [
            {
                "uid": "KBO-2771",
                "source_event_id": "projection-alias:KBO-2771",
                "source_event_members": "projection-alias:KBO-2771",
                "source_event_disposition": "superseded_duplicate_projection",
                "source_event_alias_of": "KBO-2769",
            },
            {
                "uid": "HAN-0495",
                "source_event_id": "manual-claimed-card-no-raw:HAN-0495",
                "source_event_members": "manual-claimed-card-no-raw:HAN-0495",
                "source_event_disposition": "manual_claimed_card_no_raw",
                "source_event_alias_of": "manual:0408_교토:136",
            },
            {
                "uid": "HAN-3460",
                "source_event_id": "rejected-legacy-projection:HAN-3460",
                "source_event_members": "rejected-legacy-projection:HAN-3460",
                "source_event_disposition": "rejected_legacy_projection",
                "source_event_alias_of": "card:HAN:H:116:refund",
            },
        ]
        require_valid_nonposting_aliases(rows)
        self.assertEqual(lineage_semantic_counts(rows)["nonposting_rows"], 3)

        invalid = rows.copy()
        invalid[2] = invalid[2] | {"source_event_members": "card:HAN:H:116:refund"}
        with self.assertRaisesRegex(RuntimeError, "invalid non-posting"):
            require_valid_nonposting_aliases(invalid)

    def test_raw_cancellation_must_remain_negative(self) -> None:
        valid = [
            {
                "uid": "CORP-2006",
                "source_event_id": "card:CORP:A_20260720:62",
                "krw": "-356158",
                "cancel": "True",
            }
        ]
        require_raw_cancellation_signs(valid)
        with self.assertRaisesRegex(RuntimeError, "raw cancellation sign mismatch"):
            require_raw_cancellation_signs(
                [
                    valid[0]
                    | {"uid": "CORP-2006-REGRESSION", "krw": "356158"}
                ]
            )

    def test_legacy_card_manual_conflict_needs_an_explicit_rejected_alias(self) -> None:
        # A copied Hana approval/amount that conflicts with the manual-trip
        # facts is not card evidence.  It must stay visible as a rejected
        # non-posting alias, not be silently merged into another source row.
        legacy = {
            "uid": "TRIP-0233",
            "source_event_id": "legacy:TRIP-0233",
            "source_event_members": "",
            "source_event_disposition": "raw_card_unresolved",
            "merchant": "PARK HOTEL GOLDEN",
        }
        with self.assertRaisesRegex(RuntimeError, "non-Agoda card lineage"):
            require_zero_non_agoda_unresolved([legacy])

        rejected = legacy | {
            "source_event_id": "rejected-legacy-projection:TRIP-0233",
            "source_event_members": "rejected-legacy-projection:TRIP-0233",
            "source_event_disposition": "rejected_legacy_projection",
            "source_event_alias_of": "review:card-manual-source-conflict",
        }
        require_valid_nonposting_aliases([rejected])
        self.assertEqual(lineage_semantic_counts([rejected])["unresolved_total"], 0)


if __name__ == "__main__":
    unittest.main()
