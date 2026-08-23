from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.agoda_portal_detail_capture import (
    CaptureError,
    DetailParseError,
    DetailVerifyError,
    ListDriftError,
    SourceBooking,
    SourceSnapshot,
    _attest_live_page,
    _begin_attempt,
    _canonical_json,
    _close_interrupted_attempts,
    _file_sha256,
    _failure_status,
    _ensure_detail_observation_schema,
    _find_manage_booking_button,
    _finish_failed_attempt,
    _load_source_snapshot,
    _insert_success_snapshot,
    _insert_terminal_observation,
    _ordered_unresolved_targets,
    _parse_detail_tree,
    _parse_money,
    _policy_sha256,
    _return_to_attested_page,
    _recover_after_booking_error,
    _resume_work_db,
    _seal_verification,
    _secure_create_work_db,
    WINDOW_REBIND_REASON,
    _sha256_text,
    _work_schema,
    capture_details,
    main,
)
from tools.agoda_portal_full_survey import (
    _canonical_bookings as _census_canonical_bookings,
    _convergence_manifest as _census_convergence_manifest,
    _insert_canonical_bookings as _insert_census_canonical_bookings,
    _insert_pass as _insert_census_pass,
    _schema as _census_schema,
    _survey_cards as _census_cards,
)


BOOKING_ID = "1700000000"
KEY = b"k" * 32


def source_booking(
    *,
    booking_id: str = BOOKING_ID,
    page_no: int = 1,
    card_position: int = 1,
    tab_name: str = "Completed",
    card_hash: str = "a" * 64,
) -> SourceBooking:
    return SourceBooking(
        page_no=page_no,
        booking_id=booking_id,
        booking_id_sha256=hashlib.sha256(booking_id.encode()).hexdigest(),
        service_start_on="2026-08-15",
        service_end_on="2026-08-16",
        reservation_status="Completed",
        list_card_sha256=card_hash,
        tab_name=tab_name,
        card_position=card_position,
        booking_pseudonym_hmac=hmac.new(
            KEY, booking_id.encode(), hashlib.sha256
        ).hexdigest(),
    )


def paid_tree(*, second_total: bool = False, recommendation_noise: str = "") -> str:
    duplicate = "\n190 텍스트 Total Charge\n191 텍스트 JPY 88,564" if second_total else ""
    return f"""
97 단추 Back to bookings
98 제목 Your booking is paid and confirmed .
100 텍스트 Booking ID
101 텍스트 {BOOKING_ID}
102 텍스트 Date
103 텍스트 Aug 15, 2026 -
104 텍스트 Aug 16, 2026
105 텍스트 Rooms
106 텍스트 4
129 텍스트 Check-in
130 텍스트 Aug 15, 2026
132 텍스트 Check-out
133 텍스트 Aug 16, 2026
175 제목 Payment information
176 텍스트 4 room(s) x 1 night(s)
177 텍스트 JPY 73,196
178 텍스트 Taxes And Fees
179 텍스트 JPY 15,368
180 텍스트 Paid Today
181 텍스트 JPY 88,564
183 텍스트 Total Charge
184 텍스트 JPY 88,564
188 텍스트 City tax information
191 텍스트 Local city tax regulations may add a city accommodation tax based on the room rates. The tax will be collected directly by the property upon check-in.
193 제목 Payment method
194 텍스트 Card type
195 텍스트 MasterCard
196 텍스트 Card number
197 텍스트 •••• •••• •••• 8835
{duplicate}
224 단추 {recommendation_noise}
"""


def korean_paid_tree() -> str:
    return f"""
0 제목 투숙 완료
1 텍스트 예약 번호
2 텍스트 1755317286
3 텍스트 참조 코드
4 텍스트 19308254
5 텍스트 체크인
6 텍스트 2026년 8월 12일 수요일
7 텍스트 체크아웃
8 텍스트 2026년 8월 13일 목요일
9 제목 결제 정보
10 텍스트 객실 1개 x 1박
11 텍스트 JPY 9,066
12 텍스트 세금 및 제반요금
13 텍스트 JPY 1,903
14 텍스트 오늘 결제됨
15 텍스트 JPY 10,969
16 텍스트 총 금액
17 텍스트 JPY 10,969
18 텍스트 현지 세금 안내: 숙소에서 체크인 시 도시세를 직접 지불할 수 있습니다.
19 제목 결제 방법
20 텍스트 카드 종류
21 텍스트 MasterCard
22 텍스트 카드 번호
23 텍스트 •••• •••• •••• 8835
"""


def property_collect_tree() -> str:
    return f"""
10 단추 Back to bookings
11 제목 Your booking is confirmed .
12 텍스트 Booking ID
13 텍스트 {BOOKING_ID}
14 텍스트 Date
15 텍스트 Aug 15, 2026 - Aug 16, 2026
16 텍스트 Rooms
17 텍스트 1
20 제목 Payment information
21 텍스트 1 room(s) x 1 night(s)
22 텍스트 USD 90.00
23 텍스트 Taxes And Fees
24 텍스트 USD 10.00
25 텍스트 Pay at property
26 텍스트 USD 100.00
27 텍스트 Total Charge
28 텍스트 USD 100.00
30 제목 Payment method
31 텍스트 Card type
32 텍스트 Visa
33 텍스트 Card number
34 텍스트 **** **** **** 3820
"""


def cancelled_no_price_tree(*, headline: str = "Your booking is cancelled .") -> str:
    return f"""
10 단추 Back to bookings
11 제목 {headline}
12 텍스트 Booking ID
13 텍스트 {BOOKING_ID}
14 텍스트 Date
15 텍스트 Aug 15, 2026 - Aug 16, 2026
16 텍스트 Check-in
17 텍스트 Aug 15, 2026
18 텍스트 Check-out
19 텍스트 Aug 16, 2026
20 제목 Payment information
21 텍스트 No payment amount is displayed for this cancelled booking
30 제목 Payment method
31 텍스트 Card type
32 텍스트 MasterCard
33 텍스트 Card number
34 텍스트 •••• •••• •••• 8835
"""


def scheduled_charge_tree() -> str:
    return paid_tree().replace(
        "98 제목 Your booking is paid and confirmed .",
        "98 제목 Your booking is confirmed .",
    ).replace(
        "180 텍스트 Paid Today\n181 텍스트 JPY 88,564",
        "180 텍스트 You will be automatically charged on September 1, 2026.\n"
        "181 텍스트 JPY 88,564\n"
        "182 텍스트 Pay nothing until September 1, 2026\n"
        "1821 단추 Change credit card to be charged",
    )


def list_tree(
    booking_id: str = BOOKING_ID,
    *,
    check_in: str = "Sat, Aug 15, 2026",
    check_out: str = "Sun, Aug 16, 2026",
    page_no: int = 1,
) -> str:
    return f"""
10 탭 항목 Upcoming, Secondary Actions: Select
11 탭 항목 Completed, Secondary Actions: Select
12 탭 항목 Cancelled, Secondary Actions: Select
13 기본 Completed
0 그룹 mmb-booking-card--{booking_id}
  1 텍스트 Completed
  2 텍스트 Check in
  3 텍스트 {check_in}
  4 텍스트 Check out
  5 텍스트 {check_out}
  6 단추 Manage booking {booking_id}
14 단추 1
15 단추 2
16 기본 {page_no}
"""


def create_source_db(
    path: Path,
    count: int = 3,
    periods: list[tuple[str, str]] | None = None,
) -> Path:
    key_path = path.with_name(f"{path.stem}.key")
    key_path.write_bytes(KEY)
    os.chmod(key_path, 0o600)
    connection = sqlite3.connect(path)
    _census_schema(connection)
    tabs = ("Upcoming", "Completed", "Cancelled")
    pages: list[dict[str, object]] = []
    cards: list[dict[str, object]] = []
    for index in range(count):
        tab_name = tabs[index % len(tabs)]
        booking_id = str(1800000000 + index)
        check_in, check_out = (
            periods[index]
            if periods is not None
            else ("Sat, Aug 15, 2026", "Sun, Aug 16, 2026")
        )
        parsed = _census_cards(
            list_tree(booking_id, check_in=check_in, check_out=check_out),
            tab_name,
            1,
            KEY,
        )[0]
        cards.append(parsed)
        page_hash = _sha256_text(
            "[\"" + str(parsed["semantic_card_sha256"]) + "\"]"
        )
        pages.append(
            {
                "tab_name": tab_name,
                "page_no": 1,
                "card_count": 1,
                "target_2026_count": int(
                    parsed["scope_status"] == "target_2026_overlap"
                ),
                "year_unknown_count": int(parsed["scope_status"] == "year_unknown"),
                "duplicate_occurrence_count": 0,
                "ordered_page_sha256": page_hash,
                "set_page_sha256": page_hash,
                "next_enabled": 0,
                "terminal_reason": "numeric_last_page",
            }
        )
    pages.sort(key=lambda item: str(item["tab_name"]))
    cards.sort(key=lambda item: str(item["tab_name"]))
    all_observed_cards: list[dict[str, object]] = []
    for pass_no in (1, 2):
        observed = [dict(card, pass_no=pass_no) for card in cards]
        _insert_census_pass(
            connection,
            [dict(page, pass_no=pass_no) for page in pages],
            observed,
        )
        all_observed_cards.extend(observed)
    canonical = _census_canonical_bookings(all_observed_cards)
    _insert_census_canonical_bookings(connection, canonical)
    expected_totals = {
        tab_name: sum(str(card["tab_name"]) == tab_name for card in cards)
        for tab_name in tabs
    }
    manifest_sha = _census_convergence_manifest(expected_totals, canonical)
    scope_counts = {
        scope: sum(str(card["scope_status"]) == scope for card in cards)
        for scope in ("target_2026_overlap", "year_unknown", "outside_2026")
    }
    key_id = "agoda-hmac-v1:" + hashlib.sha256(KEY).hexdigest()[:16]
    connection.execute(
        """INSERT INTO survey_run_manifest(
               run_id,source_origin,source_route_kind,pseudonym_key_id,
               tab_count,verification_pass_count,captured_page_count,
               captured_card_count,canonical_booking_count,target_2026_count,
               year_unknown_count,outside_2026_count,duplicate_occurrence_count,
               expected_tab_totals_json,pass_manifest_sha256,created_at_utc
             ) VALUES (
               'fresh','https://www.agoda.com','account_bookings',?,3,2,
               ?,?,?,?,?,?,0,?,?,'now'
             )""",
        (
            key_id,
            len(pages) * 2,
            len(cards) * 2,
            len(canonical),
            scope_counts["target_2026_overlap"],
            scope_counts["year_unknown"],
            scope_counts["outside_2026"],
            _canonical_json(expected_totals),
            manifest_sha,
        ),
    )
    connection.commit()
    connection.close()
    return key_path


def add_terminal_test_attestation(
    connection: sqlite3.Connection, source: SourceBooking
) -> None:
    connection.execute(
        """
        INSERT INTO capture_run_manifest(
            run_id,source_path,source_file_sha256,source_run_id,
            source_capture_set_sha256,membership_ordered_sha256,
            membership_set_sha256,source_population_count,target_count,
            target_2026_count,competitor_count,target_year,
            pseudonym_key_id,app_name,window_id,epoch_status,created_at_utc
        ) VALUES(
            'run','/tmp/source','f','source',?,'o','s',1,1,1,0,2026,
            'key','msedge',1,'capturing','now'
        )
        """,
        ("p" * 64,),
    )
    ordered_hash = _sha256_text(
        _canonical_json([source.booking_pseudonym_hmac])
    )
    connection.execute(
        """
        INSERT INTO page_attestations(
            run_id,tab_name,page_no,phase,expected_selected_page,
            observed_selected_page,ordered_membership_sha256,
            set_membership_sha256,source_page_set_sha256,observed_at_utc
        ) VALUES ('run','Cancelled',1,'before_click',1,1,?,?,?,'now')
        """,
        (ordered_hash, ordered_hash, "p" * 64),
    )
    attestation_id = int(
        connection.execute(
            "SELECT attestation_id FROM page_attestations"
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO page_attestation_members(
            attestation_id,ordinal,booking_pseudonym_hmac,list_card_sha256
        ) VALUES (?,1,?,?)
        """,
        (attestation_id, source.booking_pseudonym_hmac, source.list_card_sha256),
    )
    connection.commit()


class AgodaPortalDetailCaptureTests(unittest.TestCase):
    def test_source_snapshot_keeps_recent_outside_booking_as_competitor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(
                source_path,
                periods=[
                    ("Sat, Aug 15, 2026", "Sun, Aug 16, 2026"),
                    ("Fri, Aug 15, 2025", "Sat, Aug 16, 2025"),
                    ("Tue, Jul 1, 2025", "Wed, Jul 2, 2025"),
                ],
            )
            snapshot = _load_source_snapshot(source_path, key_path)

        self.assertEqual(snapshot.population_count, 3)
        self.assertEqual(len(snapshot.bookings), 2)
        self.assertEqual(snapshot.target_2026_count, 1)
        self.assertEqual(snapshot.competitor_count, 1)
        self.assertEqual(
            {booking.source_scope_status for booking in snapshot.bookings},
            {"target_2026_overlap", "outside_2026"},
        )

    def test_money_parser_uses_minor_units_without_float(self) -> None:
        cases = {
            "JPY 88,564": ("JPY", "88564", 88564, 0),
            "KRW 1,234,567": ("KRW", "1234567", 1234567, 0),
            "USD 1,234.56": ("USD", "1234.56", 123456, 2),
            "1.234,56 EUR": ("EUR", "1234.56", 123456, 2),
            "(USD 12.34)": ("USD", "-12.34", -1234, 2),
            "JPY 1\u00a0234": ("JPY", "1234", 1234, 0),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                money = _parse_money(raw)
                self.assertIsNotNone(money)
                self.assertEqual(
                    (money.currency, money.decimal_text, money.minor_units, money.scale),
                    expected,
                )

    def test_paid_detail_keeps_gross_and_paid_today_separate(self) -> None:
        parsed = _parse_detail_tree(paid_tree(), source_booking())
        by_kind = {item["kind"]: item for item in parsed["price_components"]}
        self.assertEqual(by_kind["gross_total"]["minor_units"], 88564)
        self.assertEqual(by_kind["paid_today"]["minor_units"], 88564)
        self.assertEqual(by_kind["base"]["minor_units"], 73196)
        self.assertEqual(by_kind["taxes_and_fees"]["minor_units"], 15368)
        self.assertEqual(parsed["payment_status"], "paid")
        self.assertEqual(parsed["collection_model"], "agoda_collect")
        self.assertEqual(parsed["card_role"], "payment_or_guarantee_unresolved")
        self.assertEqual(parsed["card_type"], "MasterCard")
        self.assertEqual(parsed["card4"], "8835")
        self.assertEqual(parsed["room_count"], 4)
        self.assertEqual(parsed["nights"], 1)
        self.assertEqual(parsed["has_local_tax"], 1)
        self.assertNotIn(BOOKING_ID, parsed["semantic_detail_sha256"])

    def test_paid_today_with_future_due_is_partial_not_paid_in_full(self) -> None:
        tree = paid_tree().replace(
            "183 텍스트 Total Charge",
            "181 텍스트 Future Payment\n182 텍스트 JPY 1,000\n183 텍스트 Total Charge",
        )
        parsed = _parse_detail_tree(tree, source_booking())
        self.assertEqual(parsed["payment_status"], "partially_paid")
        self.assertEqual(parsed["collection_model"], "agoda_collect")

    def test_korean_detail_normalizes_reference_card_amounts_without_fake_charge_event(self) -> None:
        source = replace(
            source_booking(booking_id="1755317286"),
            service_start_on="2026-08-12",
            service_end_on="2026-08-13",
        )
        parsed = _parse_detail_tree(korean_paid_tree(), source)

        self.assertEqual(parsed["reference_code"], "19308254")
        self.assertEqual(parsed["detail_service_start_on"], "2026-08-12")
        self.assertEqual(parsed["detail_service_end_on"], "2026-08-13")
        self.assertEqual(parsed["reservation_status"], "completed")
        self.assertEqual(parsed["payment_status"], "paid")
        self.assertEqual(parsed["collection_model"], "agoda_collect")
        self.assertEqual(parsed["card_type"], "MasterCard")
        self.assertEqual(parsed["card4"], "8835")
        self.assertEqual(parsed["room_count"], 1)
        self.assertEqual(parsed["nights"], 1)
        self.assertEqual(parsed["has_local_tax"], 1)
        by_kind = {item["kind"]: item for item in parsed["price_components"]}
        self.assertEqual(by_kind["base"]["minor_units"], 9066)
        self.assertEqual(by_kind["taxes_and_fees"]["minor_units"], 1903)
        self.assertEqual(by_kind["paid_today"]["minor_units"], 10969)
        self.assertEqual(by_kind["gross_total"]["minor_units"], 10969)
        self.assertEqual(parsed["payment_events"], [])

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            parsed=parsed,
            attempt_id=attempt_id,
        )
        snapshot = connection.execute(
            "SELECT reference_code, card4 FROM booking_detail_snapshots"
        ).fetchone()
        self.assertEqual(tuple(snapshot), ("19308254", "8835"))
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0],
            0,
        )
        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            parsed=parsed,
            attempt_id=attempt_id,
            replace_existing=True,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_snapshots"
            ).fetchone()[0],
            1,
        )
        connection.close()

    def test_korean_completed_state_wins_over_confirmed_noise(self) -> None:
        tree = korean_paid_tree().replace(
            "0 제목 투숙 완료",
            "0 제목 예약 확정\n1 제목 투숙 완료",
        )
        parsed = _parse_detail_tree(
            tree,
            replace(
                source_booking(booking_id="1755317286"),
                service_start_on="2026-08-12",
                service_end_on="2026-08-13",
            ),
        )
        self.assertEqual(parsed["reservation_status"], "completed")

    def test_multiple_card4_values_fail_closed(self) -> None:
        tree = korean_paid_tree().replace(
            "23 텍스트 •••• •••• •••• 8835",
            "23 텍스트 •••• •••• •••• 8835\n24 텍스트 •••• •••• •••• 1122",
        )
        with self.assertRaisesRegex(DetailParseError, "card4_ambiguous"):
            _parse_detail_tree(
                tree,
                replace(
                    source_booking(booking_id="1755317286"),
                    service_start_on="2026-08-12",
                    service_end_on="2026-08-13",
                ),
            )

    def test_detail_resolves_missing_list_period_and_card_ending_style(self) -> None:
        source = SourceBooking(
            page_no=1,
            booking_id=BOOKING_ID,
            booking_id_sha256=hashlib.sha256(BOOKING_ID.encode()).hexdigest(),
            service_start_on=None,  # type: ignore[arg-type]
            service_end_on=None,  # type: ignore[arg-type]
            reservation_status="Completed",
            list_card_sha256="a" * 64,
        )
        tree = paid_tree().replace(
            "•••• •••• •••• 8835", "Mastercard ending in 3820"
        )
        parsed = _parse_detail_tree(tree, source)
        self.assertEqual(parsed["detail_service_start_on"], "2026-08-15")
        self.assertEqual(parsed["detail_service_end_on"], "2026-08-16")
        self.assertEqual(parsed["detail_scope_status"], "target_2026_overlap")
        self.assertEqual(parsed["card4"], "3820")

    def test_recommendation_noise_does_not_change_semantic_hash(self) -> None:
        first = _parse_detail_tree(paid_tree(recommendation_noise="offer JPY 99"), source_booking())
        second = _parse_detail_tree(paid_tree(recommendation_noise="other offer JPY 100"), source_booking())
        self.assertEqual(first["semantic_detail_sha256"], second["semantic_detail_sha256"])

    def test_page_boundary_move_does_not_change_detail_semantic_hash(self) -> None:
        first = _parse_detail_tree(paid_tree(), source_booking(page_no=3))
        second = _parse_detail_tree(paid_tree(), source_booking(page_no=4))
        self.assertEqual(first["semantic_detail_sha256"], second["semantic_detail_sha256"])

    def test_completed_non_refundable_is_not_a_refund(self) -> None:
        tree = paid_tree().replace(
            "98 제목 Your booking is paid and confirmed .",
            "98 텍스트 Completed\n99 텍스트 Now, cancellation is non-refundable",
        )
        parsed = _parse_detail_tree(tree, source_booking())
        self.assertEqual(parsed["reservation_status"], "completed")
        self.assertEqual(parsed["payment_status"], "paid")
        self.assertEqual(parsed["refund_status"], "none_displayed")

    def test_explicit_refund_requires_payment_section_amount_and_currency(self) -> None:
        tree = paid_tree().replace(
            "183 텍스트 Total Charge",
            "182 텍스트 Refund issued Aug 20, 2026\n"
            "1821 텍스트 JPY 10,000\n"
            "183 텍스트 Total Charge",
        )
        parsed = _parse_detail_tree(tree, source_booking())
        refunds = [
            event for event in parsed["payment_events"]
            if event["event_kind"] == "refund"
        ]
        self.assertEqual(parsed["refund_status"], "full_or_unspecified")
        self.assertEqual(len(refunds), 1)
        self.assertEqual(refunds[0]["event_on"], "2026-08-20")
        self.assertEqual(refunds[0]["minor_units"], 10000)

    def test_property_collect_card_is_only_a_guarantee_card(self) -> None:
        parsed = _parse_detail_tree(property_collect_tree(), source_booking())
        self.assertEqual(parsed["collection_model"], "property_collect")
        self.assertEqual(parsed["payment_status"], "not_collected")
        self.assertEqual(parsed["card_role"], "guarantee_card")
        by_kind = {item["kind"]: item for item in parsed["price_components"]}
        self.assertEqual(by_kind["gross_total"]["minor_units"], 10000)
        self.assertEqual(by_kind["property_due"]["minor_units"], 10000)
        self.assertNotIn("paid_today", by_kind)

    def test_scheduled_agoda_charge_preserves_card_and_is_not_posted_charge(self) -> None:
        parsed = _parse_detail_tree(scheduled_charge_tree(), source_booking())
        self.assertEqual(parsed["payment_status"], "scheduled")
        self.assertEqual(parsed["collection_model"], "agoda_collect")
        self.assertEqual(parsed["card_type"], "MasterCard")
        self.assertEqual(parsed["card4"], "8835")
        by_kind = {item["kind"]: item for item in parsed["price_components"]}
        self.assertEqual(by_kind["future_due"]["minor_units"], 88564)
        self.assertNotIn("paid_today", by_kind)
        self.assertEqual(parsed["payment_events"], [])

    def test_interrupted_attempt_is_closed_before_resume_work(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = source_booking()
        _begin_attempt(connection, "run", source)
        self.assertEqual(_close_interrupted_attempts(connection, "run"), 1)
        row = connection.execute(
            "SELECT capture_status,failure_code FROM capture_attempts"
        ).fetchone()
        self.assertEqual(
            tuple(row),
            ("failed_load", "interrupted_previous_process"),
        )
        connection.close()

    def test_back_click_transport_failure_repositions_and_attests(self) -> None:
        connection = sqlite3.connect(":memory:")
        source = source_booking()
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={},
            target_2026_count=1,
        )
        recovered_tree = list_tree()
        with (
            patch(
                "tools.agoda_portal_detail_capture._click",
                side_effect=RuntimeError("windows UIA browser command failed"),
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page",
                return_value=recovered_tree,
            ) as reposition,
            patch(
                "tools.agoda_portal_detail_capture._stable_current_list_page"
            ) as stable_page,
            patch(
                "tools.agoda_portal_detail_capture._attest_live_page"
            ) as attest,
        ):
            actual = _return_to_attested_page(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        self.assertEqual(actual, recovered_tree)
        reposition.assert_called_once()
        stable_page.assert_not_called()
        attest.assert_called_once()
        connection.close()

    def test_back_click_fallback_does_not_hide_list_drift(self) -> None:
        connection = sqlite3.connect(":memory:")
        source = source_booking()
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={},
            target_2026_count=1,
        )
        drift = ListDriftError("recovery_population_drift")
        with (
            patch(
                "tools.agoda_portal_detail_capture._click",
                side_effect=RuntimeError("windows UIA browser command failed"),
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page",
                side_effect=drift,
            ),
            self.assertRaisesRegex(ListDriftError, "recovery_population_drift"),
        ):
            _return_to_attested_page(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        self.assertEqual(
            _failure_status(drift),
            ("failed_drift", "recovery_population_drift"),
        )
        connection.close()

    def test_successful_back_click_keeps_attested_list_path(self) -> None:
        recovered_tree = list_tree()
        cards = _census_cards(recovered_tree, "Completed", 1, KEY)
        source = source_booking(card_hash=cards[0]["booking_semantic_sha256"])
        page_sha = _sha256_text(
            _canonical_json([cards[0]["semantic_card_sha256"]])
        )
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={
                ("Completed", 1): {
                    "ordered_page_sha256": page_sha,
                    "set_page_sha256": page_sha,
                    "card_count": 1,
                }
            },
            all_booking_semantics=((
                source.booking_pseudonym_hmac,
                cards[0]["booking_semantic_sha256"],
            ),),
            tab_totals=(("Upcoming", 0), ("Completed", 1), ("Cancelled", 0)),
            target_2026_count=1,
        )
        connection = sqlite3.connect(":memory:")
        _work_schema(connection)
        with (
            patch("tools.agoda_portal_detail_capture._click") as click,
            patch(
                "tools.agoda_portal_detail_capture._stable_current_list_page",
                return_value=recovered_tree,
            ) as stable_page,
            patch(
                "tools.agoda_portal_detail_capture._position_list_page"
            ) as reposition,
        ):
            actual = _return_to_attested_page(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        self.assertEqual(actual, recovered_tree)
        click.assert_called_once()
        stable_page.assert_called_once()
        reposition.assert_not_called()
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM page_attestations").fetchone()[0],
            1,
        )
        connection.close()

    def test_outer_recovery_repositions_and_attests_after_transient_failure(self) -> None:
        connection = sqlite3.connect(":memory:")
        _work_schema(connection)
        recovered_tree = list_tree()
        cards = _census_cards(recovered_tree, "Completed", 1, KEY)
        source = source_booking(
            card_hash=cards[0]["booking_semantic_sha256"]
        )
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={},
            target_2026_count=1,
        )
        with (
            patch(
                "tools.agoda_portal_detail_capture._return_to_attested_page",
                side_effect=RuntimeError("transient transport error"),
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page",
                return_value=recovered_tree,
            ) as reposition,
        ):
            actual = _recover_after_booking_error(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        self.assertEqual(actual, recovered_tree)
        reposition.assert_called_once()
        self.assertEqual(
            connection.execute(
                "SELECT phase FROM page_attestations"
            ).fetchone()[0],
            "after_return",
        )
        connection.close()

    def test_outer_recovery_drift_is_terminal_without_reposition(self) -> None:
        connection = sqlite3.connect(":memory:")
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source_booking(),),
            page_manifest={},
            target_2026_count=1,
        )
        drift = ListDriftError("recovery_population_drift")
        with (
            patch(
                "tools.agoda_portal_detail_capture._return_to_attested_page",
                side_effect=drift,
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page"
            ) as reposition,
            patch(
                "tools.agoda_portal_detail_capture._mark_epoch_drift"
            ) as mark_drift,
            self.assertRaisesRegex(ListDriftError, "recovery_population_drift"),
        ):
            _recover_after_booking_error(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        mark_drift.assert_called_once_with(connection, "run")
        reposition.assert_not_called()
        connection.close()

    def test_outer_recovery_fallback_drift_is_terminal(self) -> None:
        connection = sqlite3.connect(":memory:")
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source_booking(),),
            page_manifest={},
            target_2026_count=1,
        )
        drift = ListDriftError("fallback_population_drift")
        with (
            patch(
                "tools.agoda_portal_detail_capture._return_to_attested_page",
                side_effect=RuntimeError("transient transport error"),
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page",
                side_effect=drift,
            ),
            patch(
                "tools.agoda_portal_detail_capture._mark_epoch_drift"
            ) as mark_drift,
            self.assertRaisesRegex(ListDriftError, "fallback_population_drift"),
        ):
            _recover_after_booking_error(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        mark_drift.assert_called_once_with(connection, "run")
        connection.close()

    def test_outer_recovery_double_transient_failure_is_sanitized(self) -> None:
        connection = sqlite3.connect(":memory:")
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source_booking(),),
            page_manifest={},
            target_2026_count=1,
        )
        with (
            patch(
                "tools.agoda_portal_detail_capture._return_to_attested_page",
                side_effect=RuntimeError("contains private browser detail"),
            ),
            patch(
                "tools.agoda_portal_detail_capture._position_list_page",
                side_effect=RuntimeError("contains private route detail"),
            ),
            self.assertRaisesRegex(
                CaptureError,
                "^browser_recovery_failed:unexpected_capture_error$",
            ),
        ):
            _recover_after_booking_error(
                connection,
                app="msedge",
                window_id=67514,
                snapshot=snapshot,
                run_id="run",
                tab_name="Completed",
                page_no=1,
                pseudonym_key=KEY,
                detail_tree=paid_tree(),
            )
        connection.close()

    def test_failed_finish_cannot_relabel_committed_success_attempt(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        attempt_id, _ = _begin_attempt(connection, "run", source_booking())
        connection.execute(
            "UPDATE capture_attempts SET capture_status='success', "
            "finished_at_utc='2026-08-16T00:00:00+00:00' WHERE attempt_id=?",
            (attempt_id,),
        )
        connection.commit()
        _finish_failed_attempt(
            connection,
            attempt_id,
            "failed_load",
            "unexpected_capture_error",
        )
        row = connection.execute(
            "SELECT capture_status,failure_code FROM capture_attempts "
            "WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        self.assertEqual(tuple(row), ("success", None))
        connection.close()

    def test_success_snapshot_stores_issuer_and_masked_card4_privately(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = source_booking()
        attempt_id, _ = _begin_attempt(connection, "run", source)
        parsed = _parse_detail_tree(paid_tree(), source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            parsed=parsed,
            attempt_id=attempt_id,
        )
        row = connection.execute(
            "SELECT card_type, card4, tab_name, detail_scope_status "
            "FROM booking_detail_snapshots"
        ).fetchone()
        self.assertEqual(
            tuple(row),
            ("MasterCard", "8835", "Completed", "target_2026_overlap"),
        )
        connection.close()

    def test_missing_or_duplicate_gross_total_fails_closed(self) -> None:
        with self.assertRaisesRegex(DetailParseError, "ambiguous_gross_total_component"):
            _parse_detail_tree(paid_tree(second_total=True), source_booking())
        missing = paid_tree().replace("Total Charge", "Unlabelled total")
        with self.assertRaisesRegex(
            DetailParseError, "partial_price_evidence_without_gross"
        ):
            _parse_detail_tree(missing, source_booking())

    def test_duplicate_booking_id_labels_require_same_exact_value(self) -> None:
        duplicated = paid_tree().replace(
            f"100 텍스트 Booking ID\n101 텍스트 {BOOKING_ID}",
            f"100 텍스트 Booking ID\n101 텍스트 {BOOKING_ID}"
            f"\n102 텍스트 Booking ID\n103 텍스트 {BOOKING_ID}",
        )
        parsed = _parse_detail_tree(duplicated, source_booking())
        self.assertEqual(parsed["capture_kind"], "price_evidence")

        conflicting = duplicated.replace(
            f"103 텍스트 {BOOKING_ID}",
            f"103 텍스트 9{BOOKING_ID}",
        )
        with self.assertRaisesRegex(
            DetailVerifyError, "detail_booking_id_label_ambiguous"
        ):
            _parse_detail_tree(conflicting, source_booking())

        localized_or_unlabelled = paid_tree().replace(
            "100 텍스트 Booking ID\n", "100 텍스트 예약 번호\n"
        )
        parsed = _parse_detail_tree(localized_or_unlabelled, source_booking())
        self.assertEqual(parsed["capture_kind"], "price_evidence")

        inline = paid_tree().replace(
            f"100 텍스트 Booking ID\n101 텍스트 {BOOKING_ID}",
            f"100 텍스트 Booking ID {BOOKING_ID}",
        )
        parsed = _parse_detail_tree(inline, source_booking())
        self.assertEqual(parsed["capture_kind"], "price_evidence")

    def test_cancelled_no_price_is_terminal_unresolved_observation(self) -> None:
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        tree = cancelled_no_price_tree()
        parsed = _parse_detail_tree(tree, source)
        self.assertEqual(parsed["capture_kind"], "price_evidence_not_displayed")
        self.assertEqual(parsed["reservation_status"], "cancelled")
        self.assertEqual(parsed["gross_total_present"], 0)
        self.assertEqual(parsed["amount_matching_eligible"], 0)
        self.assertEqual(parsed["unresolved_competitor"], 1)

    def test_cancelled_list_status_can_terminal_when_detail_status_is_unshown(self) -> None:
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        tree = cancelled_no_price_tree(headline="Booking details")
        parsed = _parse_detail_tree(tree, source)
        self.assertEqual(parsed["reservation_status"], "cancelled")
        self.assertEqual(parsed["detail_reservation_status"], "unknown")
        self.assertEqual(parsed["capture_kind"], "price_evidence_not_displayed")

        unknown_source = _parse_detail_tree(
            tree,
            replace(source, reservation_status="unknown"),
        )
        self.assertEqual(
            unknown_source["capture_kind"], "price_evidence_not_displayed"
        )
        self.assertEqual(unknown_source["amount_matching_eligible"], 0)
        self.assertEqual(unknown_source["unresolved_competitor"], 1)
        with self.assertRaisesRegex(DetailParseError, "gross_total_missing"):
            _parse_detail_tree(
                tree,
                replace(source, reservation_status="canceled"),
            )

    def test_terminal_rejects_partial_price_id_substring_and_missing_source_period(self) -> None:
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        partial = paid_tree().replace(
            "Your booking is paid and confirmed .", "Your booking is cancelled ."
        ).replace("Total Charge", "Unlabelled total")
        with self.assertRaisesRegex(
            DetailParseError, "partial_price_evidence_without_gross"
        ):
            _parse_detail_tree(partial, source)

        longer_id = cancelled_no_price_tree().replace(
            BOOKING_ID, "9" + BOOKING_ID
        )
        with self.assertRaisesRegex(DetailVerifyError, "detail_booking_id_mismatch"):
            _parse_detail_tree(longer_id, source)

        with self.assertRaisesRegex(
            DetailVerifyError,
            "terminal_observation_requires_exact_source_service_period",
        ):
            _parse_detail_tree(
                cancelled_no_price_tree(),
                replace(source, service_start_on=None),
            )
        conflict = _parse_detail_tree(
            cancelled_no_price_tree(
                headline="Your booking is confirmed ."
            ),
            source,
        )
        self.assertEqual(
            conflict["capture_kind"],
            "cancelled_list_detail_status_conflict_no_price",
        )
        self.assertEqual(conflict["reservation_status"], "cancelled")
        self.assertEqual(conflict["detail_reservation_status"], "confirmed")
        self.assertEqual(conflict["amount_matching_eligible"], 0)

        completed_conflict = _parse_detail_tree(
            cancelled_no_price_tree(headline="Completed"),
            source,
        )
        self.assertEqual(
            completed_conflict["capture_kind"],
            "cancelled_list_detail_status_conflict_no_price",
        )
        self.assertEqual(
            completed_conflict["detail_reservation_status"], "completed"
        )

    def test_terminal_observation_exits_retry_queue_without_price_snapshot(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        tree = cancelled_no_price_tree()
        parsed = _parse_detail_tree(tree, source)
        attempt_id, _ = _begin_attempt(connection, "run", source)
        connection.execute(
            """
            INSERT INTO capture_run_manifest(
                run_id,source_path,source_file_sha256,source_run_id,
                source_capture_set_sha256,membership_ordered_sha256,
                membership_set_sha256,source_population_count,target_count,
                target_2026_count,competitor_count,target_year,
                pseudonym_key_id,app_name,window_id,epoch_status,created_at_utc
            ) VALUES(
                'run','/tmp/source','f','source',?,'o','s',1,1,1,0,2026,
                'key','msedge',1,'capturing','now'
            )
            """,
            ("p" * 64,),
        )
        ordered_hash = _sha256_text(
            _canonical_json([source.booking_pseudonym_hmac])
        )
        connection.execute(
            """
            INSERT INTO page_attestations(
                run_id,tab_name,page_no,phase,expected_selected_page,
                observed_selected_page,ordered_membership_sha256,
                set_membership_sha256,source_page_set_sha256,observed_at_utc
            ) VALUES ('run','Cancelled',1,'before_click',1,1,?,?,?,'now')
            """,
            (ordered_hash, ordered_hash, "p" * 64),
        )
        attestation_id = int(connection.execute(
            "SELECT attestation_id FROM page_attestations"
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO page_attestation_members(
                attestation_id,ordinal,booking_pseudonym_hmac,list_card_sha256
            ) VALUES (?,1,?,?)
            """,
            (
                attestation_id,
                source.booking_pseudonym_hmac,
                source.list_card_sha256,
            ),
        )
        _insert_terminal_observation(
            connection,
            run_id="run",
            source=source,
            parsed=parsed,
            attempt_id=attempt_id,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_snapshots"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM price_components").fetchone()[0],
            0,
        )
        self.assertEqual(_ordered_unresolved_targets(connection, "run", (source,)), ())
        self.assertEqual(
            connection.execute(
                "SELECT capture_status FROM capture_attempts"
            ).fetchone()[0],
            "success",
        )
        source_snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f",
            source_run_id="source",
            source_capture_set_sha256="p" * 64,
            membership_ordered_sha256="o",
            membership_set_sha256="s",
            bookings=(source,),
            page_manifest={},
            population_count=1,
            pseudonym_key_id="key",
            target_2026_count=1,
        )
        connection.execute(
            "UPDATE capture_run_manifest SET final_revalidation_sha256=? "
            "WHERE run_id='run'",
            ("p" * 64,),
        )
        components, _semantic_hash, priced, observed = _seal_verification(
            connection, snapshot=source_snapshot, run_id="run"
        )
        self.assertEqual((components, priced, observed), (0, 0, 1))
        connection.close()

    def test_recapture_can_switch_between_price_and_terminal_lanes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        add_terminal_test_attestation(connection, source)
        terminal = _parse_detail_tree(cancelled_no_price_tree(), source)
        price = _parse_detail_tree(paid_tree(), source)

        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_terminal_observation(
            connection,
            run_id="run",
            source=source,
            parsed=terminal,
            attempt_id=attempt_id,
        )
        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            parsed=price,
            attempt_id=attempt_id,
            replace_existing=True,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_snapshots"
            ).fetchone()[0],
            1,
        )

        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_terminal_observation(
            connection,
            run_id="run",
            source=source,
            parsed=terminal,
            attempt_id=attempt_id,
            replace_existing=True,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_snapshots"
            ).fetchone()[0],
            0,
        )
        old_observation_id = connection.execute(
            "SELECT observation_id FROM booking_detail_observations"
        ).fetchone()[0]
        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_terminal_observation(
            connection,
            run_id="run",
            source=source,
            parsed=terminal,
            attempt_id=attempt_id,
            replace_existing=True,
        )
        new_observation_id = connection.execute(
            "SELECT observation_id FROM booking_detail_observations"
        ).fetchone()[0]
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0],
            1,
        )
        self.assertNotEqual(old_observation_id, new_observation_id)
        connection.close()

    def test_recapture_write_failure_rolls_back_old_price_evidence(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = source_booking()
        original = _parse_detail_tree(paid_tree(), source)
        attempt_id, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            parsed=original,
            attempt_id=attempt_id,
        )

        refund_tree = paid_tree().replace(
            "183 텍스트 Total Charge",
            "182 텍스트 Refund issued Aug 20, 2026\n"
            "1821 텍스트 JPY 10,000\n"
            "183 텍스트 Total Charge",
        )
        replacement = _parse_detail_tree(refund_tree, source)
        replacement = dict(replacement)
        replacement["semantic_detail_sha256"] = "b" * 64
        replacement["payment_events"] = [
            dict(replacement["payment_events"][0], minor_units=None)
        ]
        failed_attempt, _ = _begin_attempt(connection, "run", source)
        with self.assertRaises(sqlite3.IntegrityError):
            _insert_success_snapshot(
                connection,
                run_id="run",
                source=source,
                parsed=replacement,
                attempt_id=failed_attempt,
                replace_existing=True,
            )

        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_snapshots"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM price_components"
            ).fetchone()[0],
            len(original["price_components"]),
        )
        self.assertEqual(
            connection.execute(
                "SELECT capture_status FROM capture_attempts WHERE attempt_id=?",
                (failed_attempt,),
            ).fetchone()[0],
            "started",
        )
        _finish_failed_attempt(
            connection, failed_attempt, "failed_load", "write_failed"
        )
        self.assertEqual(
            connection.execute(
                "SELECT capture_status FROM capture_attempts WHERE attempt_id=?",
                (failed_attempt,),
            ).fetchone()[0],
            "failed_load",
        )
        connection.close()

    def test_old_observation_schema_migrates_required_audit_columns(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        connection.execute("DROP TABLE booking_detail_observations")
        connection.execute(
            """
            CREATE TABLE booking_detail_observations(
                observation_id INTEGER PRIMARY KEY,
                run_id TEXT,
                booking_id_sha256 TEXT,
                booking_pseudonym_hmac TEXT,
                tab_name TEXT,
                page_no INTEGER,
                card_position INTEGER,
                list_card_sha256 TEXT,
                source_service_start_on TEXT,
                source_service_end_on TEXT,
                source_scope_status TEXT,
                source_reservation_status TEXT,
                detail_service_start_on TEXT,
                detail_service_end_on TEXT,
                detail_scope_status TEXT,
                reservation_status TEXT,
                payment_status TEXT,
                collection_model TEXT,
                refund_status TEXT,
                observation_kind TEXT,
                payment_information_present INTEGER,
                gross_total_present INTEGER,
                card_type TEXT,
                card4 TEXT,
                card4_sha256 TEXT,
                card_role TEXT,
                amount_matching_eligible INTEGER,
                unresolved_competitor INTEGER,
                semantic_detail_sha256 TEXT,
                observed_at_utc TEXT
            )
            """
        )
        source = replace(
            source_booking(tab_name="Cancelled"),
            reservation_status="Cancelled",
        )
        connection.execute(
            """
            INSERT INTO booking_detail_observations(
                observation_id, run_id, booking_id_sha256,
                source_reservation_status, observation_kind
            ) VALUES (1, 'run', ?, 'Cancelled', 'price_evidence_not_displayed')
            """,
            (source.booking_id_sha256,),
        )
        _ensure_detail_observation_schema(connection)
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(booking_detail_observations)"
            )
        }
        self.assertTrue(
            {
                "detail_reservation_status",
                "list_attestation_id",
                "visible_money_value_count",
                "attested_ordered_membership_sha256",
                "attested_set_membership_sha256",
                "attested_source_page_set_sha256",
            }
            <= columns
        )
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0],
            0,
        )
        audit = connection.execute(
            "SELECT migration_kind, invalidated_observation_count "
            "FROM observation_schema_migration_audit"
        ).fetchone()
        self.assertEqual(
            tuple(audit),
            ("terminal_attestation_contract_v3", 1),
        )
        self.assertEqual(
            _ordered_unresolved_targets(connection, "run", (source,)),
            (source,),
        )
        connection.close()

    def test_manage_button_is_found_only_inside_matching_card(self) -> None:
        tree = list_tree() + list_tree("1700000001").replace(
            "6 단추 Manage booking 1700000001", "60 단추 Manage booking 1700000001"
        )
        self.assertEqual(_find_manage_booking_button(tree, BOOKING_ID), 6)
        with self.assertRaisesRegex(Exception, "booking_card_subtree_not_unique"):
            _find_manage_booking_button(tree, "does-not-exist")

    def test_source_snapshot_requires_converged_three_tab_census(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            valid = Path(directory) / "source.sqlite"
            key_path = create_source_db(valid)
            snapshot = _load_source_snapshot(valid, key_path)
            self.assertEqual(len(snapshot.bookings), 3)
            self.assertEqual(snapshot.file_sha256, _file_sha256(valid))
            invalid = Path(directory) / "source-invalid.sqlite"
            invalid_key = create_source_db(invalid)
            connection = sqlite3.connect(invalid)
            connection.execute(
                "DELETE FROM survey_booking_cards WHERE pass_no=2 AND row_id=("
                "SELECT MAX(row_id) FROM survey_booking_cards WHERE pass_no=2)"
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(CaptureError, "manifest_count_mismatch"):
                _load_source_snapshot(invalid, invalid_key)

    def test_work_db_is_0600_and_manifest_bound_on_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()
            if os.name != "nt":
                self.assertEqual(work_path.stat().st_mode & 0o777, 0o600)
            resumed = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            resumed.close()
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, snapshot, "other-run", "msedge", 67514
                )
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 67515
                )

    def test_work_db_window_rebind_is_atomic_audited_and_preserves_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            source = snapshot.bookings[0]
            attempt_id, _ = _begin_attempt(connection, "detail-run", source)
            _insert_success_snapshot(
                connection,
                run_id="detail-run",
                source=source,
                parsed=_parse_detail_tree(
                    paid_tree().replace(BOOKING_ID, source.booking_id), source
                ),
                attempt_id=attempt_id,
            )
            connection.commit()
            before = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "capture_attempts",
                    "booking_detail_snapshots",
                    "price_components",
                    "payment_events",
                )
            )
            connection.close()

            resumed = _resume_work_db(
                work_path,
                snapshot,
                "detail-run",
                "msedge",
                67515,
                rebind_window=True,
            )
            self.assertEqual(
                resumed.execute(
                    "SELECT window_id FROM capture_run_manifest"
                ).fetchone()[0],
                67515,
            )
            audit = resumed.execute(
                "SELECT old_window_id,new_window_id,reason_code,rebound_at_utc "
                "FROM window_rebind_audit"
            ).fetchone()
            self.assertEqual(tuple(audit[:3]), (67514, 67515, WINDOW_REBIND_REASON))
            self.assertTrue(audit[3])
            after = tuple(
                resumed.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "capture_attempts",
                    "booking_detail_snapshots",
                    "price_components",
                    "payment_events",
                )
            )
            self.assertEqual(after, before)
            resumed.close()

    def test_window_rebind_rejects_immutable_manifest_mismatch_without_audit(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()
            changed = replace(snapshot, membership_set_sha256="f" * 64)
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path,
                    changed,
                    "detail-run",
                    "msedge",
                    67515,
                    rebind_window=True,
                )
            with closing(sqlite3.connect(work_path)) as check:
                self.assertEqual(
                    check.execute(
                        "SELECT window_id FROM capture_run_manifest"
                    ).fetchone()[0],
                    67514,
                )
                self.assertEqual(
                    check.execute("SELECT COUNT(*) FROM window_rebind_audit").fetchone()[0],
                    0,
                )

    def test_window_rebind_rejects_terminal_epochs(self) -> None:
        for epoch_status, error in (
            ("complete", "work_database_epoch_already_complete"),
            ("failed_drift", "work_database_epoch_failed_drift_start_new_epoch"),
        ):
            with self.subTest(epoch_status=epoch_status), tempfile.TemporaryDirectory(
                dir="/tmp"
            ) as directory:
                source_path = Path(directory) / "source.sqlite"
                key_path = create_source_db(source_path)
                snapshot = _load_source_snapshot(source_path, key_path)
                work_path = Path(directory) / "work.sqlite"
                connection = _secure_create_work_db(
                    work_path, snapshot, "detail-run", "msedge", 67514
                )
                connection.execute(
                    "UPDATE capture_run_manifest SET epoch_status=?",
                    (epoch_status,),
                )
                connection.commit()
                connection.close()
                with self.assertRaisesRegex(CaptureError, error):
                    _resume_work_db(
                        work_path,
                        snapshot,
                        "detail-run",
                        "msedge",
                        67515,
                        rebind_window=True,
                    )
                with closing(sqlite3.connect(work_path)) as check:
                    self.assertEqual(
                        check.execute(
                            "SELECT window_id FROM capture_run_manifest"
                        ).fetchone()[0],
                        67514,
                    )
                    self.assertEqual(
                        check.execute(
                            "SELECT COUNT(*) FROM window_rebind_audit"
                        ).fetchone()[0],
                        0,
                    )

    def test_window_rebind_same_window_is_idempotent_and_invalid_id_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()
            resumed = _resume_work_db(
                work_path,
                snapshot,
                "detail-run",
                "msedge",
                67514,
                rebind_window=True,
            )
            self.assertEqual(
                resumed.execute("SELECT COUNT(*) FROM window_rebind_audit").fetchone()[0],
                0,
            )
            resumed.close()
            with self.assertRaisesRegex(CaptureError, "invalid_rebind_window_id"):
                _resume_work_db(
                    work_path,
                    snapshot,
                    "detail-run",
                    "msedge",
                    0,
                    rebind_window=True,
                )

    def test_work_db_directly_below_tmp_does_not_chmod_shared_tmp(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            descriptor, name = tempfile.mkstemp(
                prefix="agoda-detail-work-", suffix=".sqlite", dir="/tmp"
            )
            os.close(descriptor)
            work_path = Path(name)
            work_path.unlink()
            real_chmod = os.chmod

            def reject_tmp_chmod(path: os.PathLike[str] | str, mode: int) -> None:
                if Path(path).resolve() == Path(tempfile.gettempdir()).resolve():
                    raise AssertionError("must_not_chmod_shared_tmp")
                real_chmod(path, mode)

            try:
                with patch(
                    "tools.agoda_portal_detail_capture.os.chmod",
                    side_effect=reject_tmp_chmod,
                ):
                    connection = _secure_create_work_db(
                        work_path, snapshot, "detail-run", "msedge", 67514
                    )
                connection.close()
                if os.name != "nt":
                    self.assertEqual(work_path.stat().st_mode & 0o777, 0o600)
            finally:
                work_path.unlink(missing_ok=True)

    def test_page_attestation_records_post_census_booking_without_resolving_it(self) -> None:
        tree = list_tree()
        cards = _census_cards(tree, "Completed", 1, KEY)
        source = source_booking(card_hash=cards[0]["booking_semantic_sha256"])
        page_sha = _sha256_text(
            _canonical_json([cards[0]["semantic_card_sha256"]])
        )
        snapshot = SourceSnapshot(
            path=Path("/tmp/source.sqlite"),
            file_sha256="f" * 64,
            source_run_id="r3",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={
                ("Completed", 1): {
                    "ordered_page_sha256": page_sha,
                    "set_page_sha256": page_sha,
                    "card_count": 1,
                }
            },
            all_booking_semantics=((
                source.booking_pseudonym_hmac,
                cards[0]["booking_semantic_sha256"],
            ),),
            tab_totals=(("Upcoming", 0), ("Completed", 1), ("Cancelled", 0)),
        )
        connection = sqlite3.connect(":memory:")
        _work_schema(connection)
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id="run",
            tab_name="Completed",
            page_no=1,
            phase="before_click",
            tree=tree,
            pseudonym_key=KEY,
        )
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id="run",
            tab_name="Completed",
            page_no=2,
            phase="after_return",
            tree=list_tree(page_no=2),
            pseudonym_key=KEY,
        )
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id="run",
            tab_name="Completed",
            page_no=1,
            phase="before_click",
            tree=list_tree("1700000001"),
            pseudonym_key=KEY,
        )
        delta = connection.execute(
            "SELECT delta_kind, COUNT(*) FROM live_census_deltas"
        ).fetchone()
        self.assertEqual(tuple(delta), ("post_census_booking", 1))
        with self.assertRaisesRegex(
            CaptureError, "cannot_seal_with_post_census_booking_delta"
        ):
            _seal_verification(connection, snapshot=snapshot, run_id="run")
        connection.close()

    def test_seal_refuses_incomplete_population(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        connection.execute(
            """
            INSERT INTO capture_run_manifest(
                run_id, source_path, source_file_sha256, source_run_id,
                source_capture_set_sha256, membership_ordered_sha256,
                membership_set_sha256, source_population_count, target_count,
                target_2026_count, competitor_count, target_year,
                pseudonym_key_id, app_name, window_id,
                epoch_status, created_at_utc
            ) VALUES (
                'run', '/tmp/source', ?, 'fresh', ?, ?, ?, 3, 3, 3, 0, 2026,
                'key', 'msedge', 67514, 'capturing',
                '2026-08-15T00:00:00+00:00'
            )
            """,
            ("f" * 64, "c" * 64, "o" * 64, "s" * 64),
        )
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=tuple(source_booking(booking_id=str(index)) for index in range(3)),
            page_manifest={},
            target_2026_count=3,
            competitor_count=0,
        )
        with self.assertRaisesRegex(CaptureError, "complete_fresh_census"):
            _seal_verification(connection, snapshot=snapshot, run_id="run")
        connection.close()

    def test_seal_refuses_multiple_detail_versions_for_one_booking(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)
        source = source_booking()
        first = _parse_detail_tree(paid_tree(), source)
        first_attempt, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            attempt_id=first_attempt,
            parsed=first,
        )
        second = dict(first)
        second["semantic_detail_sha256"] = "b" * 64
        second_attempt, _ = _begin_attempt(connection, "run", source)
        _insert_success_snapshot(
            connection,
            run_id="run",
            source=source,
            attempt_id=second_attempt,
            parsed=second,
        )
        snapshot = SourceSnapshot(
            path=Path("/tmp/source"),
            file_sha256="f" * 64,
            source_run_id="fresh",
            source_capture_set_sha256="c" * 64,
            membership_ordered_sha256="o" * 64,
            membership_set_sha256="s" * 64,
            bookings=(source,),
            page_manifest={},
            target_2026_count=1,
        )
        with self.assertRaisesRegex(CaptureError, "multiple_detail_versions"):
            _seal_verification(connection, snapshot=snapshot, run_id="run")
        connection.close()

    def test_policy_explicitly_forbids_matching_side_effects(self) -> None:
        self.assertEqual(len(_policy_sha256()), 64)

    def test_ordered_unresolved_targets_zero_vs_sixteen_prioritization(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)

        # Empty input returns empty
        self.assertEqual(_ordered_unresolved_targets(connection, "run", ()), ())

        # 16 targets on page 1 with positions 1 to 16
        targets = [
            source_booking(
                booking_id=str(1700000000 + i),
                page_no=1,
                card_position=i + 1,
            )
            for i in range(16)
        ]
        # Position 1 (index 0) has 1 failed attempt
        connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
            ) VALUES ('run', ?, 'Completed', 1, 1, 1, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_load', 'interrupted_previous_process')
            """,
            (targets[0].booking_id_sha256,),
        )
        # Position 2 (index 1) has 2 failed attempts
        for attempt_no in (1, 2):
            connection.execute(
                """
                INSERT INTO capture_attempts(
                    run_id, booking_id_sha256, tab_name, page_no, card_position,
                    attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
                ) VALUES ('run', ?, 'Completed', 1, 2, ?, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_verify', 'verification_failed')
                """,
                (targets[1].booking_id_sha256, attempt_no),
            )
        connection.commit()

        # Unresolved targets ordered: all 0-fail targets first (positions 3..16), then 1-fail (pos 1), then 2-fail (pos 2)
        ordered = _ordered_unresolved_targets(connection, "run", targets)
        self.assertEqual(len(ordered), 16)
        # The 0-failure targets retain their card_position ascending order: pos 3 through 16
        self.assertEqual([b.card_position for b in ordered[:14]], list(range(3, 17)))
        # Target with 1 failure is placed after all 0-failure targets
        self.assertEqual(ordered[14].card_position, 1)
        # Target with 2 failures is placed after the 1-failure target
        self.assertEqual(ordered[15].card_position, 2)
        connection.close()

    def test_ordered_unresolved_targets_deterministic_tie_under_shuffled_input(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)

        # Create bookings with identical and differing positions and failure counts
        b1 = source_booking(booking_id="1700000001", page_no=1, card_position=1)
        b2 = source_booking(booking_id="1700000002", page_no=1, card_position=1)
        b3 = source_booking(booking_id="1700000003", page_no=1, card_position=2)
        b4 = source_booking(booking_id="1700000004", page_no=1, card_position=3)
        b5 = source_booking(booking_id="1700000005", page_no=1, card_position=4)

        # b3 has 1 failure, b5 has 2 failures
        connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
            ) VALUES ('run', ?, 'Completed', 1, 2, 1, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_parse', 'parse_error')
            """,
            (b3.booking_id_sha256,),
        )
        for attempt_no in (1, 2):
            connection.execute(
                """
                INSERT INTO capture_attempts(
                    run_id, booking_id_sha256, tab_name, page_no, card_position,
                    attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
                ) VALUES ('run', ?, 'Completed', 1, 4, ?, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_drift', 'drift_error')
                """,
                (b5.booking_id_sha256, attempt_no),
            )
        connection.commit()

        targets = [b1, b2, b3, b4, b5]
        zero_fail_tied = sorted([b1, b2], key=lambda b: (b.card_position, b.booking_id_sha256))
        expected = tuple([*zero_fail_tied, b4, b3, b5])

        # Test various permutations to ensure deterministic output
        forward = _ordered_unresolved_targets(connection, "run", targets)
        reversed_order = _ordered_unresolved_targets(connection, "run", list(reversed(targets)))
        shuffled = _ordered_unresolved_targets(connection, "run", [b4, b5, b2, b1, b3])
        shuffled_2 = _ordered_unresolved_targets(connection, "run", [b3, b1, b5, b4, b2])

        self.assertEqual(forward, expected)
        self.assertEqual(reversed_order, expected)
        self.assertEqual(shuffled, expected)
        self.assertEqual(shuffled_2, expected)
        connection.close()

    def test_ordered_unresolved_targets_excludes_existing_successes(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)

        b1 = source_booking(booking_id="1700000001", card_position=1)
        b2 = source_booking(booking_id="1700000002", card_position=2)
        b3 = source_booking(booking_id="1700000003", card_position=3)

        # Insert success snapshot for b1 in 'run_target'
        connection.execute(
            """
            INSERT INTO booking_detail_snapshots(
                run_id, booking_id, booking_id_sha256, booking_pseudonym_hmac,
                tab_name, page_no, card_position, list_card_sha256,
                source_scope_status, source_reservation_status,
                detail_service_start_on, detail_service_end_on, detail_scope_status,
                reservation_status, payment_status, collection_model, refund_status,
                payment_schedule_json, has_local_tax, card_role, semantic_detail_sha256,
                snapshot_version, captured_at_utc
            ) VALUES (
                'run_target', ?, ?, ?,
                'Completed', 1, 1, 'card_hash',
                'target_2026_overlap', 'Completed',
                '2026-08-15', '2026-08-16', 'target_2026_overlap',
                'Completed', 'paid', 'agoda_collect', 'non_refundable',
                '[]', 0, 'guarantee', 'detail_sha256',
                1, '2026-08-15T00:00:00+00:00'
            )
            """,
            (b1.booking_id, b1.booking_id_sha256, b1.booking_pseudonym_hmac),
        )

        # Insert success snapshot for b2 in 'run_other'
        connection.execute(
            """
            INSERT INTO booking_detail_snapshots(
                run_id, booking_id, booking_id_sha256, booking_pseudonym_hmac,
                tab_name, page_no, card_position, list_card_sha256,
                source_scope_status, source_reservation_status,
                detail_service_start_on, detail_service_end_on, detail_scope_status,
                reservation_status, payment_status, collection_model, refund_status,
                payment_schedule_json, has_local_tax, card_role, semantic_detail_sha256,
                snapshot_version, captured_at_utc
            ) VALUES (
                'run_other', ?, ?, ?,
                'Completed', 1, 2, 'card_hash',
                'target_2026_overlap', 'Completed',
                '2026-08-15', '2026-08-16', 'target_2026_overlap',
                'Completed', 'paid', 'agoda_collect', 'non_refundable',
                '[]', 0, 'guarantee', 'detail_sha256',
                1, '2026-08-15T00:00:00+00:00'
            )
            """,
            (b2.booking_id, b2.booking_id_sha256, b2.booking_pseudonym_hmac),
        )
        connection.commit()

        # For 'run_target', b1 is excluded, b2 and b3 are included
        unresolved = _ordered_unresolved_targets(
            connection, "run_target", [b1, b2, b3]
        )
        self.assertEqual(unresolved, (b2, b3))

        recapture = _ordered_unresolved_targets(
            connection, "run_target", [b1, b2, b3], recapture_existing=True
        )
        self.assertEqual(recapture, (b1, b2, b3))

        # When all targets have success rows in 'run_target', returns empty
        connection.execute(
            """
            INSERT INTO booking_detail_snapshots(
                run_id, booking_id, booking_id_sha256, booking_pseudonym_hmac,
                tab_name, page_no, card_position, list_card_sha256,
                source_scope_status, source_reservation_status,
                detail_service_start_on, detail_service_end_on, detail_scope_status,
                reservation_status, payment_status, collection_model, refund_status,
                payment_schedule_json, has_local_tax, card_role, semantic_detail_sha256,
                snapshot_version, captured_at_utc
            ) VALUES (
                'run_target', ?, ?, ?,
                'Completed', 1, 2, 'card_hash',
                'target_2026_overlap', 'Completed',
                '2026-08-15', '2026-08-16', 'target_2026_overlap',
                'Completed', 'paid', 'agoda_collect', 'non_refundable',
                '[]', 0, 'guarantee', 'detail_sha256',
                1, '2026-08-15T00:00:00+00:00'
            ), (
                'run_target', ?, ?, ?,
                'Completed', 1, 3, 'card_hash',
                'target_2026_overlap', 'Completed',
                '2026-08-15', '2026-08-16', 'target_2026_overlap',
                'Completed', 'paid', 'agoda_collect', 'non_refundable',
                '[]', 0, 'guarantee', 'detail_sha256',
                1, '2026-08-15T00:00:00+00:00'
            )
            """,
            (
                b2.booking_id, b2.booking_id_sha256, b2.booking_pseudonym_hmac,
                b3.booking_id, b3.booking_id_sha256, b3.booking_pseudonym_hmac,
            ),
        )
        connection.commit()
        self.assertEqual(_ordered_unresolved_targets(connection, "run_target", [b1, b2, b3]), ())
        connection.close()

    def test_ordered_unresolved_targets_started_and_success_statuses_not_counted(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)

        b1 = source_booking(booking_id="1700000001", card_position=1)
        b2 = source_booking(booking_id="1700000002", card_position=2)

        # b1 has 1 'started' and 1 'success' attempt (neither is failed_%)
        connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
            ) VALUES
            ('run', ?, 'Completed', 1, 1, 1, '2026-08-15T00:00:00+00:00', NULL, 'started', NULL),
            ('run', ?, 'Completed', 1, 1, 2, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'success', NULL)
            """,
            (b1.booking_id_sha256, b1.booking_id_sha256),
        )

        # b2 has 1 'failed_verify' attempt
        connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
            ) VALUES
            ('run', ?, 'Completed', 1, 2, 1, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_verify', 'verification_failed')
            """,
            (b2.booking_id_sha256,),
        )
        connection.commit()

        # b1 has failed_count 0, b2 has failed_count 1
        ordered = _ordered_unresolved_targets(connection, "run", [b2, b1])
        self.assertEqual(ordered, (b1, b2))
        connection.close()

    def test_close_interrupted_attempts_is_idempotent(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        _work_schema(connection)

        connection.execute(
            """
            INSERT INTO capture_attempts(
                run_id, booking_id_sha256, tab_name, page_no, card_position,
                attempt_no, started_at_utc, finished_at_utc, capture_status, failure_code
            ) VALUES
            ('run_1', 'hash1', 'Completed', 1, 1, 1, '2026-08-15T00:00:00+00:00', NULL, 'started', NULL),
            ('run_1', 'hash2', 'Completed', 1, 2, 1, '2026-08-15T00:00:00+00:00', NULL, 'started', NULL),
            ('run_1', 'hash3', 'Completed', 1, 3, 1, '2026-08-15T00:00:00+00:00', '2026-08-15T00:00:01+00:00', 'failed_load', 'user_abort'),
            ('run_2', 'hash4', 'Completed', 1, 1, 1, '2026-08-15T00:00:00+00:00', NULL, 'started', NULL)
            """
        )
        connection.commit()

        # First call closes 2 started rows in run_1
        first_call = _close_interrupted_attempts(connection, "run_1")
        self.assertEqual(first_call, 2)

        rows = connection.execute(
            "SELECT booking_id_sha256, capture_status, failure_code FROM capture_attempts WHERE run_id = 'run_1' ORDER BY card_position"
        ).fetchall()
        self.assertEqual(
            [tuple(r) for r in rows],
            [
                ("hash1", "failed_load", "interrupted_previous_process"),
                ("hash2", "failed_load", "interrupted_previous_process"),
                ("hash3", "failed_load", "user_abort"),
            ],
        )

        run2_row = connection.execute(
            "SELECT capture_status, failure_code FROM capture_attempts WHERE run_id = 'run_2'"
        ).fetchone()
        self.assertEqual(tuple(run2_row), ("started", None))

        # Subsequent calls are idempotent
        self.assertEqual(_close_interrupted_attempts(connection, "run_1"), 0)
        self.assertEqual(_close_interrupted_attempts(connection, "run_1"), 0)
        connection.close()

    def test_window_rebind_default_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()

            # Without rebind_window=True, different window_id is rejected fail-closed
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 99999
                )

            # DB manifest remains unchanged
            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 67514)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 0)
            connection.close()

    def test_successful_audited_rebind_preserving_row_counts(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )

            # Insert sample rows across all work tables
            booking = snapshot.bookings[0]
            attempt_id, _ = _begin_attempt(connection, "detail-run", booking)
            parsed = _parse_detail_tree(paid_tree().replace(BOOKING_ID, booking.booking_id), booking)
            _insert_success_snapshot(
                connection,
                run_id="detail-run",
                source=booking,
                parsed=parsed,
                attempt_id=attempt_id,
            )
            connection.execute(
                """
                INSERT INTO page_attestations(
                    run_id, tab_name, page_no, phase, expected_selected_page,
                    observed_selected_page, ordered_membership_sha256,
                    set_membership_sha256, source_page_set_sha256, observed_at_utc
                ) VALUES
                ('detail-run', 'Completed', 1, 'before_click', 1, 1, 'h1', 'h2', 'h3', '2026-08-15T00:00:00+00:00')
                """
            )
            connection.commit()

            # Record baseline row counts before rebind
            count_snapshots_pre = connection.execute("SELECT COUNT(*) FROM booking_detail_snapshots").fetchone()[0]
            count_attempts_pre = connection.execute("SELECT COUNT(*) FROM capture_attempts").fetchone()[0]
            count_components_pre = connection.execute("SELECT COUNT(*) FROM price_components").fetchone()[0]
            count_events_pre = connection.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0]
            count_attestations_pre = connection.execute("SELECT COUNT(*) FROM page_attestations").fetchone()[0]
            connection.close()

            # First rebind: 67514 -> 78901
            resumed1 = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 78901, rebind_window=True
            )
            resumed1.close()

            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 78901)
            rebind_rows = connection.execute(
                "SELECT * FROM window_rebind_audit ORDER BY rebind_id"
            ).fetchall()
            self.assertEqual(len(rebind_rows), 1)
            self.assertEqual(rebind_rows[0]["run_id"], "detail-run")
            self.assertEqual(int(rebind_rows[0]["old_window_id"]), 67514)
            self.assertEqual(int(rebind_rows[0]["new_window_id"]), 78901)
            self.assertEqual(rebind_rows[0]["reason_code"], WINDOW_REBIND_REASON)
            self.assertTrue(bool(rebind_rows[0]["rebound_at_utc"]))

            # Verify row counts are strictly preserved
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM booking_detail_snapshots").fetchone()[0],
                count_snapshots_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_attempts").fetchone()[0],
                count_attempts_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM price_components").fetchone()[0],
                count_components_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0],
                count_events_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM page_attestations").fetchone()[0],
                count_attestations_pre,
            )
            connection.close()

            # Second rebind: 78901 -> 89012
            resumed2 = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 89012, rebind_window=True
            )
            resumed2.close()

            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 89012)
            rebind_rows = connection.execute(
                "SELECT * FROM window_rebind_audit ORDER BY rebind_id"
            ).fetchall()
            self.assertEqual(len(rebind_rows), 2)
            self.assertEqual(int(rebind_rows[1]["old_window_id"]), 78901)
            self.assertEqual(int(rebind_rows[1]["new_window_id"]), 89012)
            self.assertEqual(rebind_rows[1]["reason_code"], WINDOW_REBIND_REASON)

            # Row counts still preserved
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM booking_detail_snapshots").fetchone()[0],
                count_snapshots_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_attempts").fetchone()[0],
                count_attempts_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM price_components").fetchone()[0],
                count_components_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0],
                count_events_pre,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM page_attestations").fetchone()[0],
                count_attestations_pre,
            )
            connection.close()

    def test_window_rebind_immutable_mismatch_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()

            # Mismatched run_id
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, snapshot, "wrong-run", "msedge", 99999, rebind_window=True
                )

            # Mismatched app_name
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "chrome", 99999, rebind_window=True
                )

            # Mismatched snapshot file_sha256
            tampered_snapshot = replace(snapshot, file_sha256="0" * 64)
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, tampered_snapshot, "detail-run", "msedge", 99999, rebind_window=True
                )

            # Mismatched snapshot pseudonym_key_id
            tampered_key_snapshot = replace(snapshot, pseudonym_key_id="agoda-hmac-v1:wrong")
            with self.assertRaisesRegex(CaptureError, "work_database_manifest_mismatch"):
                _resume_work_db(
                    work_path, tampered_key_snapshot, "detail-run", "msedge", 99999, rebind_window=True
                )

            # Manifest window_id remains unchanged and no audit entries created
            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 67514)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 0)
            connection.close()

    def test_window_rebind_terminal_epoch_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            # Set epoch to failed_drift
            connection.execute(
                "UPDATE capture_run_manifest SET epoch_status = 'failed_drift' WHERE run_id = 'detail-run'"
            )
            connection.commit()
            connection.close()

            # Failed drift epoch rejected with and without rebind_window
            with self.assertRaisesRegex(
                CaptureError, "work_database_epoch_failed_drift_start_new_epoch"
            ):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 99999, rebind_window=True
                )
            with self.assertRaisesRegex(
                CaptureError, "work_database_epoch_failed_drift_start_new_epoch"
            ):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 67514, rebind_window=False
                )

            # Set epoch to complete
            connection = sqlite3.connect(work_path)
            connection.execute(
                "UPDATE capture_run_manifest SET epoch_status = 'complete' WHERE run_id = 'detail-run'"
            )
            connection.commit()
            connection.close()

            # Complete epoch rejected with and without rebind_window
            with self.assertRaisesRegex(
                CaptureError, "work_database_epoch_already_complete"
            ):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 99999, rebind_window=True
                )
            with self.assertRaisesRegex(
                CaptureError, "work_database_epoch_already_complete"
            ):
                _resume_work_db(
                    work_path, snapshot, "detail-run", "msedge", 67514, rebind_window=False
                )

            # Manifest window_id remains unchanged and no audit entries created
            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 67514)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 0)
            connection.close()

    def test_window_rebind_idempotent_same_window_resume(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()

            # Same window resume with rebind_window=True is idempotent
            resumed1 = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514, rebind_window=True
            )
            resumed1.close()

            # Same window resume with rebind_window=False is idempotent
            resumed2 = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514, rebind_window=False
            )
            resumed2.close()

            # Manifest window_id is 67514 and no audit rows added
            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 67514)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 0)
            connection.close()

    def test_window_rebind_invalid_window_id_rejection(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            connection.close()

            for invalid_id in (0, -1, -999, True, False, None):
                with self.assertRaisesRegex(CaptureError, "invalid_rebind_window_id"):
                    _resume_work_db(
                        work_path, snapshot, "detail-run", "msedge", invalid_id, rebind_window=True  # type: ignore[arg-type]
                    )

            # Manifest window_id remains unchanged
            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 67514)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 0)
            connection.close()

    def test_window_rebind_backfill_safe_for_existing_dbs(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            source_path = Path(directory) / "source.sqlite"
            key_path = create_source_db(source_path)
            snapshot = _load_source_snapshot(source_path, key_path)
            work_path = Path(directory) / "work.sqlite"
            connection = _secure_create_work_db(
                work_path, snapshot, "detail-run", "msedge", 67514
            )
            # Simulate older DB without window_rebind_audit table
            connection.execute("DROP TABLE window_rebind_audit")
            connection.commit()
            connection.close()

            resumed = _resume_work_db(
                work_path, snapshot, "detail-run", "msedge", 88888, rebind_window=True
            )
            resumed.close()

            connection = sqlite3.connect(work_path)
            connection.row_factory = sqlite3.Row
            manifest = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
            self.assertEqual(int(manifest["window_id"]), 88888)
            rebind_rows = connection.execute("SELECT * FROM window_rebind_audit").fetchall()
            self.assertEqual(len(rebind_rows), 1)
            self.assertEqual(int(rebind_rows[0]["old_window_id"]), 67514)
            self.assertEqual(int(rebind_rows[0]["new_window_id"]), 88888)
            connection.close()

    def test_capture_cli_is_blocked_by_paseo_iab_policy(self) -> None:
        stdout = io.StringIO()
        with patch("sys.argv", [
            "agoda_portal_detail_capture.py",
            "capture",
            "--window-id", "99999",
            "--source-db", "/tmp/source.sqlite",
            "--hmac-key-file", "/tmp/key.key",
            "--work-db", "/tmp/work.sqlite",
            "--run-id", "test-run",
            "--resume",
            "--rebind-window",
        ]), patch("sys.stdout", stdout):
            ret = main()
        self.assertEqual(ret, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["failure_code"], "PASEO_IAB_ONLY")


if __name__ == "__main__":
    unittest.main()
