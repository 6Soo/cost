from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agoda_portal_full_survey import (
    SurveyError,
    _booking_pseudonym,
    _build_state,
    _canonical_bookings,
    _click_tab,
    _click_visible_numeric_page,
    _convergence_manifest,
    _ensure_tab_selected,
    _force_first_numeric_page,
    _go_to_numeric_page,
    _infer_last_page,
    _is_page_step_control,
    _insert_canonical_bookings,
    _insert_pass,
    _load_or_create_hmac_key,
    _navigate_bookings_url,
    _pagination_buttons,
    _pagination_controls,
    _pass_manifest,
    _publish_memory_database,
    _schema,
    _scope_status,
    _select_tab_at_first_page,
    _selected_page,
    _selected_tab,
    _stable_pair_canonical,
    _survey_cards,
    _tab_buttons,
    _validate_occurrences,
    _wait_tab_state,
)


KEY = b"k" * 32


def card_block(
    booking_id: str = "1701189825",
    *,
    root: str = "dom-token",
    start_line: str = "3 텍스트 Thu, Aug 13, 2026",
    end_line: str = "5 텍스트 Fri, Aug 14, 2026",
) -> str:
    return f"""
0 그룹 mmb-booking-card--{root}
  1 텍스트 Completed
  2 텍스트 Check in
  {start_line}
  4 텍스트 Check out
  {end_line}
  6 단추 Manage booking {booking_id}
"""


def tab_tree(
    *,
    tab: str = "Completed",
    body: str | None = None,
    pagination: str = "14 단추 1\n15 단추 2\n16 단추 3\n20 단추 Next",
    selected_page: int | None = 1,
) -> str:
    return f"""
10 탭 항목 Upcoming, Secondary Actions: Select
11 탭 항목 Completed, Secondary Actions: Select
12 탭 항목 Cancelled, Secondary Actions: Select
13 기본 {tab}
{body if body is not None else card_block()}
{pagination}
{f"17 기본 {selected_page}" if selected_page is not None else ""}
"""


class AgodaPortalFullSurveyTests(unittest.TestCase):
    def test_extracts_actual_booking_id_and_hmac_not_dom_token(self) -> None:
        cards = _survey_cards(card_block(), "Completed", 1, KEY)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["booking_id"], "1701189825")
        self.assertEqual(
            cards[0]["booking_pseudonym_hmac"],
            _booking_pseudonym(KEY, "1701189825"),
        )
        self.assertNotIn("dom-token", cards[0]["semantic_card_sha256"])
        self.assertEqual(cards[0]["scope_status"], "target_2026_overlap")

    def test_root_suffix_change_does_not_change_semantic_membership(self) -> None:
        first = _survey_cards(card_block(root="first"), "Completed", 1, KEY)[0]
        second = _survey_cards(card_block(root="second"), "Completed", 1, KEY)[0]
        self.assertEqual(first["semantic_card_sha256"], second["semantic_card_sha256"])

    def test_missing_actual_booking_id_fails_closed(self) -> None:
        with self.assertRaisesRegex(SurveyError, "actual_booking_id_missing"):
            _survey_cards(
                card_block().replace("Manage booking 1701189825", "Manage booking"),
                "Completed",
                1,
                KEY,
            )

    def test_scope_includes_cross_year_overlap_and_preserves_unknown(self) -> None:
        self.assertEqual(_scope_status("2025-12-31", "2026-01-02"), "target_2026_overlap")
        self.assertEqual(_scope_status("2026-12-31", "2027-01-02"), "target_2026_overlap")
        self.assertEqual(_scope_status(None, None), "year_unknown")
        self.assertEqual(_scope_status("2025-01-01", "2025-01-02"), "outside_2026")

    def test_tab_and_numeric_pagination_attestation_are_structural(self) -> None:
        tree = tab_tree()
        self.assertEqual(_selected_tab(tree), "Completed")
        self.assertEqual(_selected_page(tree), 1)
        self.assertEqual(_tab_buttons(tree), {"Upcoming": 10, "Completed": 11, "Cancelled": 12})
        self.assertEqual(_pagination_buttons(tree), {1: 14, 2: 15, 3: 16})
        self.assertEqual(_pagination_controls(tree), {"next": 20})
        self.assertEqual(_infer_last_page(tree, empty=False), ((1, 2, 3), 3))

    def test_requested_page_must_match_disabled_numeric_attestation(self) -> None:
        tree = tab_tree(selected_page=2)
        with self.assertRaisesRegex(
            SurveyError, "selected_page_attestation_mismatch"
        ):
            _build_state(tree, "Completed", 1, KEY)
        state = _build_state(tree, "Completed", None, KEY)
        self.assertEqual(state.page_no, 2)

    def test_page_labeled_range_control_wins_over_unrelated_bare_next(self) -> None:
        tree = tab_tree(
            pagination=(
                "14 단추 1\n15 단추 6\n16 단추 7\n17 단추 13\n"
                "18 단추 Previous page\n19 단추 Next page\n20 단추 Next"
            )
        )
        self.assertEqual(
            _pagination_controls(tree), {"next": 19, "previous": 18}
        )
        self.assertTrue(_is_page_step_control(tree, "next", 19))
        self.assertFalse(_is_page_step_control(tree, "next", 20))

    def test_explicit_next_page_may_advance_cards_while_revealing_range(self) -> None:
        current_tree = tab_tree(
            body=card_block("1700000010"),
            pagination=(
                "14 단추 1\n15 단추 6\n16 단추 7\n17 단추 8\n"
                "18 단추 9\n19 단추 10\n20 단추 13\n"
                "21 단추 Previous page\n22 단추 Next page\n23 단추 Next"
            ),
            selected_page=10,
        )
        moved_tree = tab_tree(
            body=card_block("1700000011"),
            pagination=(
                "14 단추 1\n15 단추 8\n16 단추 9\n17 단추 10\n"
                "18 단추 11\n19 단추 12\n20 단추 13\n"
                "21 단추 Previous page\n23 단추 Next"
            ),
            selected_page=11,
        )
        current = _build_state(current_tree, "Completed", 10, KEY)
        moved = _build_state(moved_tree, "Completed", 11, KEY)
        with patch(
            "tools.agoda_portal_full_survey._click_element"
        ) as click, patch(
            "tools.agoda_portal_full_survey._wait_pagination_range",
            return_value=moved_tree,
        ), patch(
            "tools.agoda_portal_full_survey._wait_tab_state",
            return_value=moved,
        ) as wait_state:
            result = _go_to_numeric_page(
                "msedge", 1, "Completed", 11, 10, current, KEY
            )
        self.assertEqual(result, moved)
        click.assert_called_once_with(
            "msedge", 1, 22, tree=current_tree
        )
        self.assertEqual(wait_state.call_args.args[3], 11)

    def test_unmarked_disabled_next_does_not_create_fictional_page_four(self) -> None:
        state = _build_state(
            tab_tree(selected_page=3), "Completed", 3, KEY
        )
        self.assertEqual(state.last_page, 3)
        self.assertEqual(state.visible_pages, (1, 2, 3))

    def test_first_page_reset_clicks_attested_page_one(self) -> None:
        initial = _build_state(
            tab_tree(selected_page=2), "Completed", 2, KEY
        )
        final = _build_state(
            tab_tree(
                body=card_block("1701189827"), selected_page=1
            ),
            "Completed",
            1,
            KEY,
        )
        with (
            patch(
                "tools.agoda_portal_full_survey._wait_tab_state",
                return_value=final,
            ) as wait_state,
            patch(
                "tools.agoda_portal_full_survey._click_visible_numeric_page",
                return_value=final.tree,
            ) as click_page,
        ):
            result = _force_first_numeric_page(
                "msedge", 67514, "Completed", initial, KEY
            )

        self.assertIs(result, final)
        click_page.assert_called_once_with(
            "msedge", 67514, "Completed", 1, initial.tree
        )
        self.assertEqual(wait_state.call_args.args[3], 1)
        self.assertEqual(wait_state.call_args.kwargs["expected_last_page"], 3)

    def test_numeric_page_click_retries_verified_noop(self) -> None:
        pagination = "14 단추 1\n15 단추 12\n16 단추 13"
        page_12 = tab_tree(
            pagination=pagination, selected_page=12
        )
        page_13 = tab_tree(
            pagination=pagination, selected_page=13
        )
        with patch(
            "tools.agoda_portal_full_survey._click_element"
        ) as click_element, patch(
            "tools.agoda_portal_full_survey._survey_tree",
            side_effect=[page_12, page_12, page_12, page_13],
        ), patch("tools.agoda_portal_full_survey.time.sleep"):
            selected = _click_visible_numeric_page(
                "msedge", 67514, "Completed", 13, page_12
            )

        self.assertEqual(_selected_page(selected), 13)
        self.assertEqual(click_element.call_count, 2)

    def test_numeric_page_click_retries_transient_transport_failure(self) -> None:
        pagination = "14 단추 1\n15 단추 12\n16 단추 13"
        page_12 = tab_tree(pagination=pagination, selected_page=12)
        page_13 = tab_tree(pagination=pagination, selected_page=13)
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=[RuntimeError("transient transport"), None],
            ) as click_element,
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                side_effect=[page_12, page_13],
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
        ):
            selected = _click_visible_numeric_page(
                "msedge", 67514, "Completed", 13, page_12
            )

        self.assertEqual(_selected_page(selected), 13)
        self.assertEqual(click_element.call_count, 2)

    def test_numeric_page_transport_retry_does_not_hide_wrong_tab(self) -> None:
        pagination = "14 단추 1\n15 단추 12\n16 단추 13"
        page_12 = tab_tree(pagination=pagination, selected_page=12)
        wrong_tab = tab_tree(
            tab="Upcoming", pagination=pagination, selected_page=12
        )
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=RuntimeError("transient transport"),
            ),
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=wrong_tab,
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
            self.assertRaisesRegex(
                SurveyError, "numeric_page_transport_changed_selected_tab"
            ),
        ):
            _click_visible_numeric_page(
                "msedge", 67514, "Completed", 13, page_12
            )

    def test_numeric_page_transport_retry_rejects_intermediate_page(self) -> None:
        pagination = "14 단추 1\n15 단추 11\n16 단추 12\n17 단추 13"
        page_12 = tab_tree(pagination=pagination, selected_page=12)
        unexpected_page_11 = tab_tree(
            pagination=pagination, selected_page=11
        )
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=RuntimeError("transient transport"),
            ),
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=unexpected_page_11,
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
            self.assertRaisesRegex(
                SurveyError, "numeric_page_transport_changed_selected_page"
            ),
        ):
            _click_visible_numeric_page(
                "msedge", 67514, "Completed", 13, page_12
            )

    def test_tab_select_retries_transient_transport_failure(self) -> None:
        completed = tab_tree(tab="Completed")
        upcoming = tab_tree(tab="Upcoming")
        with (
            patch(
                "tools.agoda_portal_full_survey._click_tab",
                side_effect=[RuntimeError("transient transport"), None],
            ) as click_tab,
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                side_effect=[completed, upcoming],
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
        ):
            selected = _ensure_tab_selected(
                "msedge",
                67514,
                "Upcoming",
                initial_tree=completed,
            )

        self.assertEqual(_selected_tab(selected), "Upcoming")
        self.assertEqual(click_tab.call_count, 2)

    def test_range_control_retries_transient_transport_failure(self) -> None:
        current_tree = tab_tree(
            body=card_block("1700000010"),
            pagination=(
                "14 단추 1\n15 단추 6\n16 단추 7\n17 단추 8\n"
                "18 단추 9\n19 단추 10\n20 단추 13\n"
                "21 단추 Previous page\n22 단추 Next page\n23 단추 Next"
            ),
            selected_page=10,
        )
        moved_tree = tab_tree(
            body=card_block("1700000011"),
            pagination=(
                "14 단추 1\n15 단추 8\n16 단추 9\n17 단추 10\n"
                "18 단추 11\n19 단추 12\n20 단추 13\n"
                "21 단추 Previous page\n23 단추 Next"
            ),
            selected_page=11,
        )
        current = _build_state(current_tree, "Completed", 10, KEY)
        moved = _build_state(moved_tree, "Completed", 11, KEY)
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=[RuntimeError("transient transport"), None],
            ) as click_element,
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=current_tree,
            ),
            patch(
                "tools.agoda_portal_full_survey._wait_pagination_range",
                return_value=moved_tree,
            ),
            patch(
                "tools.agoda_portal_full_survey._wait_tab_state",
                return_value=moved,
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
        ):
            result = _go_to_numeric_page(
                "msedge", 67514, "Completed", 11, 10, current, KEY
            )

        self.assertIs(result, moved)
        self.assertEqual(click_element.call_count, 2)

    def test_range_control_transport_retry_rejects_wrong_tab(self) -> None:
        current_tree = tab_tree(
            body=card_block("1700000010"),
            pagination=(
                "14 단추 1\n15 단추 6\n16 단추 7\n17 단추 8\n"
                "18 단추 9\n19 단추 10\n20 단추 13\n"
                "21 단추 Previous page\n22 단추 Next page"
            ),
            selected_page=10,
        )
        wrong_tab = current_tree.replace(
            "13 기본 Completed", "13 기본 Upcoming"
        )
        current = _build_state(current_tree, "Completed", 10, KEY)
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=RuntimeError("transient transport"),
            ) as click_element,
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=wrong_tab,
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
            self.assertRaisesRegex(
                SurveyError,
                "pagination_range_transport_changed_selected_tab",
            ),
        ):
            _go_to_numeric_page(
                "msedge", 67514, "Completed", 11, 10, current, KEY
            )
        self.assertEqual(click_element.call_count, 1)

    def test_range_control_transport_retry_rejects_wrong_page(self) -> None:
        current_tree = tab_tree(
            body=card_block("1700000010"),
            pagination=(
                "14 단추 1\n15 단추 6\n16 단추 7\n17 단추 8\n"
                "18 단추 9\n19 단추 10\n20 단추 13\n"
                "21 단추 Previous page\n22 단추 Next page"
            ),
            selected_page=10,
        )
        wrong_page = current_tree.replace(
            "17 기본 10", "17 기본 9"
        )
        current = _build_state(current_tree, "Completed", 10, KEY)
        with (
            patch(
                "tools.agoda_portal_full_survey._click_element",
                side_effect=RuntimeError("transient transport"),
            ) as click_element,
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=wrong_page,
            ),
            patch("tools.agoda_portal_full_survey.time.sleep"),
            self.assertRaisesRegex(
                SurveyError,
                "pagination_range_transport_changed_selected_page",
            ),
        ):
            _go_to_numeric_page(
                "msedge", 67514, "Completed", 11, 10, current, KEY
            )
        self.assertEqual(click_element.call_count, 1)

    def test_tab_switch_uses_advertised_select_action(self) -> None:
        with patch("tools.agoda_portal_full_survey._run_orca") as run_orca:
            _click_tab("msedge", 67514, tab_tree(), "Completed")
        arguments = run_orca.call_args.args
        self.assertEqual(arguments[:2], ("computer", "perform-secondary-action"))
        self.assertIn("Select", arguments)
        self.assertIn("11", arguments)

    def test_route_reset_retries_transient_browser_command_failure(self) -> None:
        with (
            patch(
                "tools.agoda_portal_full_survey._run_orca",
                side_effect=[RuntimeError("transient"), {}, {}, {}],
            ) as run_orca,
            patch("tools.agoda_portal_full_survey.time.sleep"),
        ):
            _navigate_bookings_url("msedge", 67514)
        self.assertEqual(run_orca.call_count, 4)

    def test_route_reset_explicitly_reselects_upcoming_origin(self) -> None:
        remembered_completed = tab_tree(tab="Completed")
        upcoming_tree = tab_tree(tab="Upcoming")
        upcoming_state = _build_state(upcoming_tree, "Upcoming", 1, KEY)
        with (
            patch("tools.agoda_portal_full_survey._navigate_bookings_url"),
            patch(
                "tools.agoda_portal_full_survey._survey_tree",
                return_value=remembered_completed,
            ),
            patch(
                "tools.agoda_portal_full_survey._ensure_tab_selected",
                return_value=upcoming_tree,
            ) as ensure_tab,
            patch(
                "tools.agoda_portal_full_survey._wait_tab_state",
                return_value=upcoming_state,
            ),
            patch(
                "tools.agoda_portal_full_survey._force_first_numeric_page",
                return_value=upcoming_state,
            ),
        ):
            result = _select_tab_at_first_page(
                "msedge", 67514, "Upcoming", KEY
            )
        self.assertIs(result, upcoming_state)
        self.assertEqual(ensure_tab.call_args.args[2], "Upcoming")

    def test_explicit_empty_tab_and_exact_full_last_page_are_terminal(self) -> None:
        empty = tab_tree(
            tab="Cancelled",
            body="30 텍스트 You don't have any bookings",
            pagination="",
        )
        state = _build_state(empty, "Cancelled", 1, KEY)
        self.assertTrue(state.empty)
        self.assertEqual(state.last_page, 1)

        forty = "\n".join(
            card_block(str(1700000000 + index), root=f"root-{index}")
            for index in range(40)
        )
        last = _build_state(
            tab_tree(body=forty, selected_page=3),
            "Completed",
            3,
            KEY,
        )
        self.assertEqual(len(last.cards), 40)
        self.assertEqual(last.last_page, 3)

    def test_duplicate_booking_within_one_page_fails_closed(self) -> None:
        body = card_block(root="first") + card_block(root="second")
        with self.assertRaisesRegex(SurveyError, "duplicate_booking_within_single_page"):
            _build_state(tab_tree(body=body), "Completed", 1, KEY)

    def test_duplicate_actual_booking_id_across_tabs_fails_epoch(self) -> None:
        first = _survey_cards(card_block(), "Upcoming", 1, KEY)[0]
        second = _survey_cards(card_block(), "Cancelled", 1, KEY)[0]
        with self.assertRaisesRegex(SurveyError, "semantic_conflict"):
            _validate_occurrences([first, second])

    def test_same_booking_may_move_pages_without_becoming_two_bookings(self) -> None:
        first = dict(
            _survey_cards(card_block(), "Completed", 3, KEY)[0], pass_no=1
        )
        second = dict(
            _survey_cards(card_block(), "Completed", 4, KEY)[0], pass_no=2
        )
        canonical = _canonical_bookings([first, second])
        canonical_reversed = _canonical_bookings([second, first])
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0]["observation_count"], 2)
        self.assertEqual(canonical[0]["booking_pseudonym_hmac"], first["booking_pseudonym_hmac"])
        self.assertEqual(
            _convergence_manifest({"Upcoming": 0, "Completed": 1, "Cancelled": 0}, canonical),
            _convergence_manifest({"Upcoming": 0, "Completed": 1, "Cancelled": 0}, canonical_reversed),
        )
        first_result = ([], [first])
        second_result = ([], [second])
        population_manifest = _convergence_manifest(
            {"Upcoming": 0, "Completed": 1, "Cancelled": 0},
            _canonical_bookings([first]),
        )
        self.assertIsNotNone(
            _stable_pair_canonical(
                [first_result, second_result],
                [population_manifest, population_manifest],
            )
        )

    def test_pass_manifest_ignores_pass_number_but_detects_membership_change(self) -> None:
        card = _survey_cards(card_block(), "Completed", 1, KEY)[0]
        page = {
            "tab_name": "Completed",
            "page_no": 1,
            "card_count": 1,
            "target_2026_count": 1,
            "year_unknown_count": 0,
            "duplicate_occurrence_count": 0,
            "ordered_page_sha256": "o" * 64,
            "set_page_sha256": "s" * 64,
            "next_enabled": 0,
            "terminal_reason": "next_absent",
        }
        first = _pass_manifest([dict(page, pass_no=1)], [dict(card, pass_no=1)])
        second = _pass_manifest([dict(page, pass_no=2)], [dict(card, pass_no=2)])
        changed = _pass_manifest(
            [dict(page, pass_no=2)],
            [dict(card, pass_no=2, card_position=2)],
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_two_identical_sweeps_allow_persistent_cross_page_repeat(self) -> None:
        base = _survey_cards(card_block(), "Cancelled", 1, KEY)[0]
        pass_results = []
        manifests = []
        for pass_no in (1, 2):
            cards = [
                dict(
                    base,
                    pass_no=pass_no,
                    page_no=1,
                    card_position=1,
                    semantic_card_sha256="a" * 64,
                ),
                dict(
                    base,
                    pass_no=pass_no,
                    page_no=2,
                    card_position=1,
                    semantic_card_sha256="b" * 64,
                ),
            ]
            pages = [
                {
                    "pass_no": pass_no,
                    "tab_name": "Cancelled",
                    "page_no": page_no,
                    "card_count": 1,
                    "target_2026_count": 1,
                    "year_unknown_count": 0,
                    "duplicate_occurrence_count": 0,
                    "ordered_page_sha256": str(page_no) * 64,
                    "set_page_sha256": str(page_no + 2) * 64,
                    "next_enabled": int(page_no == 1),
                    "terminal_reason": (
                        None if page_no == 1 else "numeric_last_page"
                    ),
                }
                for page_no in (1, 2)
            ]
            pass_results.append((pages, cards))
            manifests.append(
                _convergence_manifest(
                    {"Upcoming": 0, "Completed": 0, "Cancelled": 2},
                    _canonical_bookings(cards),
                )
            )

        canonical = _stable_pair_canonical(pass_results, manifests)
        self.assertIsNotNone(canonical)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0]["observation_count"], 4)

    def test_changed_second_sweep_does_not_converge(self) -> None:
        base = _survey_cards(card_block(), "Completed", 1, KEY)[0]
        page = {
            "pass_no": 1,
            "tab_name": "Completed",
            "page_no": 1,
            "card_count": 1,
            "target_2026_count": 1,
            "year_unknown_count": 0,
            "duplicate_occurrence_count": 0,
            "ordered_page_sha256": "o" * 64,
            "set_page_sha256": "s" * 64,
            "next_enabled": 0,
            "terminal_reason": "numeric_last_page",
        }
        first = ([page], [dict(base, pass_no=1)])
        changed = _survey_cards(
            card_block("1701189826", root="changed"),
            "Completed",
            1,
            KEY,
        )[0]
        second = (
            [dict(page, pass_no=2)],
            [dict(changed, pass_no=2)],
        )
        expected = {"Upcoming": 0, "Completed": 1, "Cancelled": 0}
        manifests = [
            _convergence_manifest(expected, _canonical_bookings(first[1])),
            _convergence_manifest(expected, _canonical_bookings(second[1])),
        ]
        self.assertIsNone(
            _stable_pair_canonical([first, second], manifests)
        )

    def test_stuck_loading_refresh_requires_fresh_sweep(self) -> None:
        loading = tab_tree(body="1 텍스트 Loading")
        ready = tab_tree(body=card_block())
        with patch(
            "tools.agoda_portal_full_survey._survey_tree",
            side_effect=[ready, ready],
        ), patch(
            "tools.agoda_portal_full_survey._run_orca"
        ) as run_orca, patch(
            "tools.agoda_portal_full_survey.time.sleep"
        ):
            with self.assertRaisesRegex(
                SurveyError, "browser_refresh_requires_fresh_sweep"
            ):
                _wait_tab_state(
                    "msedge",
                    1,
                    "Completed",
                    1,
                    KEY,
                    initial_tree=loading,
                    timeout_seconds=1.0,
                    refresh_after_seconds=0.0,
                    partial_stable_seconds=0.0,
                )

        run_orca.assert_called_once()
        self.assertIn("CmdOrCtrl+R", run_orca.call_args.args)

    def test_partial_page_must_remain_stable_before_acceptance(self) -> None:
        partial = tab_tree(body=card_block())
        full = tab_tree(
            body="\n".join(
                card_block(str(1700000000 + index), root=f"root-{index}")
                for index in range(40)
            )
        )
        with patch(
            "tools.agoda_portal_full_survey._survey_tree",
            side_effect=[partial, full, full],
        ):
            state = _wait_tab_state(
                "msedge",
                1,
                "Completed",
                1,
                KEY,
                initial_tree=partial,
                timeout_seconds=5.0,
                partial_stable_seconds=1.0,
            )

        self.assertEqual(len(state.cards), 40)

    def test_hmac_key_is_separate_private_file(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            key_path = Path(directory) / "key.bin"
            key, key_id = _load_or_create_hmac_key(key_path)
            self.assertGreaterEqual(len(key), 32)
            self.assertTrue(key_id.startswith("agoda-hmac-v1:"))
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            same_key, same_id = _load_or_create_hmac_key(key_path)
            self.assertEqual(key, same_key)
            self.assertEqual(key_id, same_id)

    def test_private_publication_is_0600_and_no_replace(self) -> None:
        connection = sqlite3.connect(":memory:")
        _schema(connection)
        observed_cards = []
        for pass_no in (1, 2):
            for tab in ("Upcoming", "Completed", "Cancelled"):
                booking_id = str(1700000000 + ("Upcoming", "Completed", "Cancelled").index(tab))
                card = dict(
                    _survey_cards(card_block(booking_id), tab, 1, KEY)[0],
                    pass_no=pass_no,
                )
                observed_cards.append(card)
                _insert_pass(
                    connection,
                    [{
                        "pass_no": pass_no,
                        "tab_name": tab,
                        "page_no": 1,
                        "card_count": 1,
                        "target_2026_count": 1,
                        "year_unknown_count": 0,
                        "duplicate_occurrence_count": 0,
                        "ordered_page_sha256": card["semantic_card_sha256"],
                        "set_page_sha256": card["semantic_card_sha256"],
                        "next_enabled": 0,
                        "terminal_reason": "numeric_last_page",
                    }],
                    [card],
                )
        canonical = _canonical_bookings(observed_cards)
        _insert_canonical_bookings(connection, canonical)
        connection.execute(
            "INSERT INTO survey_run_manifest VALUES "
            "('run', 'https://www.agoda.com', 'account_bookings', 'key-id', "
            "3, 2, 6, 6, 3, 3, 0, 0, 0, ?, ?, 'now')",
            ('{"Cancelled":1,"Completed":1,"Upcoming":1}', "f" * 64),
        )
        connection.commit()
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            destination = Path(directory) / "survey.sqlite"
            _publish_memory_database(connection, destination)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(SurveyError, "refusing_to_overwrite"):
                _publish_memory_database(connection, destination)

        descriptor, direct_name = tempfile.mkstemp(
            prefix="agoda-survey-publish-", suffix=".sqlite", dir="/tmp"
        )
        os.close(descriptor)
        direct_destination = Path(direct_name)
        direct_destination.unlink()
        real_chmod = os.chmod

        def reject_tmp_chmod(path: os.PathLike[str] | str, mode: int) -> None:
            if Path(path).resolve() == Path(tempfile.gettempdir()).resolve():
                raise AssertionError("must_not_chmod_shared_tmp")
            real_chmod(path, mode)

        try:
            with patch(
                "tools.agoda_portal_full_survey.os.chmod",
                side_effect=reject_tmp_chmod,
            ):
                _publish_memory_database(connection, direct_destination)
            self.assertEqual(direct_destination.stat().st_mode & 0o777, 0o600)
        finally:
            direct_destination.unlink(missing_ok=True)
        connection.close()


if __name__ == "__main__":
    unittest.main()
