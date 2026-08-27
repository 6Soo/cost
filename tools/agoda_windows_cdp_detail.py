"""Headless Windows CDP Agoda list/detail capture.

The browser is one isolated headless Edge target.  The ten requested workers
are deterministic logical shards: U01 owns all Upcoming cards and C01..C09
own HMAC partitions of Completed cards.  Work is serialized at the browser
boundary so two workers can never navigate the same authenticated target at
the same time.  Cancelled is intentionally excluded.

This command only creates private evidence staging JSON.  It never writes a
ledger, OTA database, or browser profile.  Raw detail text is consumed in
memory and is not included in the output; only normalized parser results and
stable failure codes are written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

try:
    from tools.agoda_portal_detail_capture import (
        SourceBooking,
        _canonical_json,
        _parse_detail_tree,
        _sha256_text,
    )
    from tools.agoda_windows_cdp_capture import (
        ALLOWED_TABS,
        SHARDS,
        CaptureError,
        census,
        census_from_selected,
        load_hmac_key,
        run_bridge,
        shard_for,
        write_private_json,
    )
except ModuleNotFoundError as _retired_err:
    raise ImportError(
        'tools/agoda_portal_detail_capture was retired in commit 92288ba; '
        'use tools/agoda_paseo_batch_import.py instead.'
    ) from _retired_err


class DetailRunError(RuntimeError):
    pass


def _stable_failure(exc: BaseException) -> str:
    text = str(exc).strip().casefold()
    known = (
        "auth_required",
        "booking_page_error",
        "bookings_route_not_attested",
        "selected_bookings_route_not_attested",
        "selected_tab_not_attested",
        "selected_page_not_attested",
        "list_identity_not_attested",
        "list_cards_missing",
        "cdp_bridge_failed",
        "navigation_state_unknown",
        "cdp_bridge_response_invalid",
        "card_missing",
        "card_click_failed",
        "cdp_dom_ready_timeout",
        "cdp_dom_summary_missing",
        "cdp_detail_summary_missing",
        "detail_scope_not_attested",
        "detail_booking_id_mismatch",
        "detail_booking_id_label_ambiguous",
        "detail_service_period_mismatch",
        "detail_error_or_authentication_page",
        "detail_visible_values_missing",
        "payment_information_missing",
        "gross_total_missing",
        "partial_price_evidence_without_gross",
        "payment_state_ambiguous",
    )
    for item in known:
        if item in text:
            return item
    if isinstance(exc, CaptureError):
        return text or "capture_failed"
    return "detail_capture_failed"


def _agoda_host(value: object) -> bool:
    try:
        host = (urlsplit(str(value)).hostname or "").casefold()
    except ValueError:
        return False
    return host == "agoda.com" or host.endswith(".agoda.com")


def _synthetic_detail_tree(values: Iterable[object]) -> str:
    lines: list[str] = []
    for index, value in enumerate(values):
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        if clean:
            lines.append(f"{index} 텍스트 {clean}")
    return "\n".join(lines)


def _source_booking(card: dict[str, Any]) -> SourceBooking:
    booking_id = str(card.get("booking_id") or "")
    if not booking_id.isdigit():
        raise DetailRunError("source_booking_id_invalid")
    return SourceBooking(
        tab_name=str(card["tab_name"]),
        page_no=int(card["page_no"]),
        card_position=int(card["card_position"]),
        booking_id=booking_id,
        booking_id_sha256=_sha256_text(booking_id),
        booking_pseudonym_hmac=str(card["booking_pseudonym_hmac"]),
        service_start_on=card.get("service_start_on"),
        service_end_on=card.get("service_end_on"),
        source_scope_status=str(card.get("scope_status") or "year_unknown"),
        reservation_status=str(card["reservation_status"]),
        list_card_sha256=str(card["booking_semantic_sha256"]),
    )


def _worker_plan(cards: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    plan = {
        label: {
            "label": label,
            "tab_name": "Upcoming" if label == "U01" else "Completed",
            "assignment_count": 0,
            "booking_pseudonym_hmacs": [],
        }
        for label in SHARDS
    }
    for card in cards:
        label = str(card.get("shard_label") or "")
        if label not in plan:
            raise DetailRunError("logical_worker_assignment_invalid")
        plan[label]["assignment_count"] += 1
        plan[label]["booking_pseudonym_hmacs"].append(
            str(card["booking_pseudonym_hmac"])
        )
    for item in plan.values():
        item["booking_pseudonym_hmacs"].sort()
    return plan


def _collect_tab_pages(
    *,
    port: int,
    endpoint_manifest: Path,
    key: bytes,
    list_url: str,
    tab_name: str,
    max_pages: int,
) -> list[dict[str, Any]]:
    if tab_name not in ALLOWED_TABS:
        raise DetailRunError("cancelled_tab_excluded")
    first = census(
        port=port,
        tab_name=tab_name,
        key=key,
        list_url=list_url,
        page_no=1,
        endpoint_manifest=endpoint_manifest,
    )
    page_values = [int(item) for item in first.get("page_values") or []]
    last_page = max(page_values or [1])
    if last_page > max_pages:
        raise DetailRunError("page_limit_exceeded")
    pages = [first]
    if last_page > 1:
        for page_no in range(2, last_page + 1):
            pages.append(
                census(
                    port=port,
                    tab_name=tab_name,
                    key=key,
                    list_url=list_url,
                    page_no=page_no,
                    endpoint_manifest=endpoint_manifest,
                )
            )
    elif first.get("has_next_page"):
        page_no = 1
        current = first
        while current.get("has_next_page"):
            page_no += 1
            if page_no > max_pages:
                raise DetailRunError("page_limit_exceeded")
            selected = run_bridge(
                port=port,
                operation="select-next-page",
                endpoint_manifest=endpoint_manifest,
                summary_only=False,
            )
            current = census_from_selected(
                tab_name=tab_name,
                page_no=page_no,
                key=key,
                selected=selected,
            )
            pages.append(current)
    return pages


def _verify_return_to_list(
    result: dict[str, Any], source: dict[str, Any]
) -> None:
    if result.get("login_required") or result.get("error_marker"):
        raise DetailRunError("list_restore_page_error")
    if result.get("customer_service_panel_visible"):
        raise DetailRunError("customer_service_panel_open")
    if result.get("selected_tab") != source["tab_name"]:
        raise DetailRunError("list_restore_tab_mismatch")
    if result.get("selected_page") != source["page_no"] or not result.get(
        "page_attested"
    ):
        raise DetailRunError("list_restore_page_mismatch")
    if not result.get("identity_attested"):
        raise DetailRunError("list_restore_identity_not_attested")
    cards = result.get("cards")
    if not isinstance(cards, list):
        raise DetailRunError("list_restore_cards_missing")
    matches = [
        item
        for item in cards
        if str(item.get("booking_id") or "") == str(source["booking_id"])
    ]
    if len(matches) != 1:
        raise DetailRunError("list_restore_target_missing_or_ambiguous")


def _capture_one(
    *,
    port: int,
    endpoint_manifest: Path,
    source: dict[str, Any],
) -> dict[str, Any]:
    source_booking = _source_booking(source)
    clicked = False
    try:
        clicked_result = run_bridge(
            port=port,
            operation="click-card",
            booking_id=source_booking.booking_id,
            card_index=int(source["browser_card_index"]),
            endpoint_manifest=endpoint_manifest,
            summary_only=False,
        )
        if clicked_result.get("customer_service_panel_visible"):
            raise DetailRunError("customer_service_panel_open")
        clicked = True
        detail = run_bridge(
            port=port,
            operation="detail-inspect",
            endpoint_manifest=endpoint_manifest,
            summary_only=False,
        )
        if detail.get("login_required") or detail.get("error_marker"):
            raise DetailRunError("detail_error_or_authentication_page")
        if detail.get("customer_service_panel_visible"):
            raise DetailRunError("customer_service_panel_open")
        if (
            not detail.get("detail_marker")
            or not detail.get("detail_scope_attested")
            or not _agoda_host(detail.get("url"))
        ):
            if not detail.get("detail_scope_attested"):
                raise DetailRunError("detail_scope_not_attested")
            raise DetailRunError("detail_page_not_attested")
        values = detail.get("values")
        if not isinstance(values, list):
            raise DetailRunError("detail_visible_values_missing")
        parsed = _parse_detail_tree(_synthetic_detail_tree(values), source_booking)
        return {
            "capture_status": "success",
            "booking_id": source_booking.booking_id,
            "booking_id_sha256": source_booking.booking_id_sha256,
            "booking_pseudonym_hmac": source_booking.booking_pseudonym_hmac,
            "tab_name": source_booking.tab_name,
            "page_no": source_booking.page_no,
            "card_position": source_booking.card_position,
            "shard_label": source["shard_label"],
            "detail_url_host": urlsplit(str(detail["url"])).hostname,
            "detail": parsed,
            "_clicked": True,
        }
    except Exception as exc:
        failure = _stable_failure(exc)
        # A bridge failure during click-card leaves browser location
        # unknown.  Do not continue the page loop on an unverified detail
        # page; the caller cannot safely decide whether history.back() is
        # required.  The run must be resumed from a fresh attested census.
        if not clicked and failure == "cdp_bridge_failed":
            raise DetailRunError("navigation_state_unknown") from exc
        return {
            "capture_status": "unresolved",
            "failure_code": failure,
            "booking_id": source_booking.booking_id,
            "booking_id_sha256": source_booking.booking_id_sha256,
            "booking_pseudonym_hmac": source_booking.booking_pseudonym_hmac,
            "tab_name": source_booking.tab_name,
            "page_no": source_booking.page_no,
            "card_position": source_booking.card_position,
            "shard_label": source["shard_label"],
            "_clicked": clicked,
        }


def capture(
    *,
    port: int,
    endpoint_manifest: Path,
    hmac_key_file: Path,
    list_url: str,
    max_pages: int,
) -> dict[str, Any]:
    key = load_hmac_key(hmac_key_file)
    all_cards: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    for tab_name in ALLOWED_TABS:
        for page in _collect_tab_pages(
            port=port,
            endpoint_manifest=endpoint_manifest,
            key=key,
            list_url=list_url,
            tab_name=tab_name,
            max_pages=max_pages,
        ):
            page_cards = list(page["cards"])
            pages.append(
                {
                    "tab_name": page["tab_name"],
                    "page_no": page["page_no"],
                    "card_count": len(page_cards),
                    "source_url": page["source_url"],
                }
            )
            all_cards.extend(page_cards)
    booking_ids = [str(item["booking_id"]) for item in all_cards]
    if len(booking_ids) != len(set(booking_ids)):
        raise DetailRunError("cross_tab_booking_id_duplicate")
    plan = _worker_plan(all_cards)
    observations: list[dict[str, Any]] = []
    for page in pages:
        current = census(
            port=port,
            tab_name=page["tab_name"],
            key=key,
            list_url=list_url,
            page_no=int(page["page_no"]),
            endpoint_manifest=endpoint_manifest,
        )
        page_cards = [
            item
            for item in all_cards
            if item["tab_name"] == page["tab_name"]
            and int(item["page_no"]) == int(page["page_no"])
        ]
        current_ids = [str(item.get("booking_id") or "") for item in current["cards"]]
        expected_ids = [str(item["booking_id"]) for item in page_cards]
        if current_ids != expected_ids:
            raise DetailRunError("list_page_membership_drift")
        for source in page_cards:
            observation = _capture_one(
                port=port,
                endpoint_manifest=endpoint_manifest,
                source=source,
            )
            clicked = bool(observation.pop("_clicked", False))
            observations.append(observation)
            # Once click-card has acknowledged navigation, always attempt a
            # history-back.  If detail parsing failed, this prevents the next
            # card from being attempted on the detail page; a click failure
            # remains on the attested list and is recorded as unresolved.
            if clicked:
                restored = run_bridge(
                    port=port,
                    operation="back",
                    endpoint_manifest=endpoint_manifest,
                    summary_only=False,
                )
                _verify_return_to_list(restored, source)
    resolved = sum(item["capture_status"] == "success" for item in observations)
    return {
        "schema": 1,
        "capture_kind": "windows_headless_cdp_detail",
        "raw_browser_data": False,
        "worker_mode": "logical_serialized_single_browser",
        "tabs": list(ALLOWED_TABS),
        "pages": pages,
        "card_count": len(all_cards),
        "resolved_count": resolved,
        "unresolved_count": len(observations) - resolved,
        "worker_plan": plan,
        "observations": observations,
        "membership_sha256": hashlib.sha256(
            _canonical_json(
                sorted(
                    (
                        item["tab_name"],
                        item["booking_pseudonym_hmac"],
                        item["shard_label"],
                    )
                    for item in all_cards
                )
            ).encode("utf-8")
        ).hexdigest(),
    }


def main() -> int:
    try:
        from tools.agoda_browser_policy import legacy_browser_block
    except ImportError:  # pragma: no cover - direct script execution
        from agoda_browser_policy import legacy_browser_block

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--endpoint-manifest", type=Path, required=True)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument(
        "--list-url",
        default="https://www.agoda.com/ko-kr/account/bookings.html",
    )
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return legacy_browser_block("agoda_windows_cdp_detail")

    try:
        if args.max_pages < 1:
            raise DetailRunError("max_pages_invalid")
        result = capture(
            port=args.port,
            endpoint_manifest=args.endpoint_manifest,
            hmac_key_file=args.hmac_key_file,
            list_url=args.list_url,
            max_pages=args.max_pages,
        )
        write_private_json(args.output, result)
        print(
            json.dumps(
                {
                    "status": "DETAIL_STAGED",
                    "card_count": result["card_count"],
                    "resolved_count": result["resolved_count"],
                    "unresolved_count": result["unresolved_count"],
                    "worker_counts": {
                        label: item["assignment_count"]
                        for label, item in result["worker_plan"].items()
                    },
                    "output": str(args.output.resolve()),
                    "raw_browser_data": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "failure_code": _stable_failure(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
