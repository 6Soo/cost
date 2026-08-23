#!/usr/bin/env python3
"""Capture a converged census of every Agoda booking-list tab.

The census is deliberately independent of the stale Completed-only r3 DB.
It walks Upcoming, Completed and Cancelled through attested numeric page
controls up to the explicit last-page sentinel, then repeats the complete walk.
Agoda can repeat the same booking on multiple pages and can reshuffle bookings
tied at a page boundary. Publication therefore requires two consecutive full
sweeps with stable per-tab slot totals and the same unique booking ID, period,
status and scope population. Slot totals are an observation count, never an
assumed unique-booking count. Page position and card order are audit evidence,
not booking identity or convergence identity.

The actual Agoda booking ID comes from ``Manage booking <id>``.  It is stored
only inside the private mode-0600 database; report-facing membership uses a
keyed HMAC whose key is held in a separate mode-0600 file and whose key ID,
not key material, is recorded in the DB.  Raw trees, URLs, navigation query
tokens, names, addresses, e-mails, full PANs and screenshots are never stored.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.agoda_portal_detail_capture import (
        MANAGE_BUTTON_RE,
        _canonical_json,
        _file_sha256,
        _require_tmp,
        _sha256_text,
        _utc_now,
    )
    from tools.agoda_portal_page_capture import (
        _card_blocks,
        _element_name,
        _extract_cards,
        _run_orca,
    )
except ModuleNotFoundError:  # direct invocation
    from agoda_portal_detail_capture import (
        MANAGE_BUTTON_RE,
        _canonical_json,
        _file_sha256,
        _require_tmp,
        _sha256_text,
        _utc_now,
    )
    from agoda_portal_page_capture import (
        _card_blocks,
        _element_name,
        _extract_cards,
        _run_orca,
    )


BOOKINGS_ORIGIN = "https://www.agoda.com"
BOOKINGS_ROUTE_KIND = "account_bookings"
BOOKINGS_URL = f"{BOOKINGS_ORIGIN}/account/bookings.html"
TAB_NAMES = ("Upcoming", "Completed", "Cancelled")
MAX_PAGES_PER_TAB = 1000


def _restore_window_args() -> list[str]:
    """Avoid the slow native-provider foreground restore on every read."""
    if os.environ.get("AGODA_UI_BACKEND", "").strip().lower() == "windows_uia":
        return ["--restore-window"]
    return []

TAB_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+탭 항목\s+(Upcoming|Completed|Cancelled)(?:,.*)?$",
    re.IGNORECASE,
)
SELECTED_TAB_RE = re.compile(
    r"^\s*\d+\s+기본\s+(Upcoming|Completed|Cancelled)\s*$",
    re.IGNORECASE,
)
SELECTED_PAGE_RE = re.compile(
    r"^\s*\d+\s+기본\s+(\d+)\s*$",
    re.IGNORECASE,
)
PAGE_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+단추\s+(\d+)(?:,.*)?$",
    re.IGNORECASE,
)
PAGINATION_CONTROL_RE = re.compile(
    r"^\s*(\d+)\s+단추\s+(Back|Previous(?: page)?|Next(?: page)?)(?:,.*)?$",
    re.IGNORECASE,
)
# Windows Edge exposes the Agoda account controls in Korean even when the
# browser chrome is localized differently.  Keep the original English
# patterns above for compatibility, then use these runtime-compatible
# patterns for both locales.
TAB_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+\uD0ED \uD56D\uBAA9\s+(.+?)(?:,.*)?$",
    re.IGNORECASE,
)
SELECTED_TAB_RE = re.compile(
    r"^\s*\d+\s+\uAE30\uBCF8\s+(.+?)\s*$",
    re.IGNORECASE,
)
PAGE_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+\uB2E8\uCD94\s+(\d+)(?:,.*)?$",
    re.IGNORECASE,
)
PAGINATION_CONTROL_RE = re.compile(
    r"^\s*(\d+)\s+\uB2E8\uCD94\s+(.+?)(?:,.*)?$",
    re.IGNORECASE,
)

TAB_LABEL_TO_NAME = {
    "upcoming": "Upcoming",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "\uB2E4\uAC00\uC624\uB294 \uC608\uC57D": "Upcoming",
    "\uC644\uB8CC\uB41C \uC608\uC57D": "Completed",
    "\uCDE8\uC18C\uB41C \uC608\uC57D": "Cancelled",
}


def _canonical_tab_name(label: str) -> str | None:
    normalized = re.sub(r"\s+", " ", label.strip()).casefold()
    return TAB_LABEL_TO_NAME.get(normalized)


def _pagination_direction(label: str) -> str | None:
    normalized = re.sub(r"\s+", " ", label.strip()).casefold()
    if normalized in {
        "next",
        "next page",
        "\uB2E4\uC74C",
        "\uB2E4\uC74C \uD398\uC774\uC9C0",
    }:
        return "next"
    if normalized in {
        "back",
        "previous",
        "previous page",
        "\uC774\uC804",
        "\uC774\uC804 \uD398\uC774\uC9C0",
    }:
        return "previous"
    return None


EMPTY_STATE_PATTERNS = (
    re.compile(r"\bno bookings?\b", re.I),
    re.compile(r"\bno (?:upcoming|completed|cancelled|canceled) bookings?\b", re.I),
    re.compile(r"\byou don't have any bookings?\b", re.I),
)
class SurveyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TabState:
    tree: str
    tab_name: str
    page_no: int
    cards: tuple[dict[str, Any], ...]
    ordered_page_sha256: str
    set_page_sha256: str
    visible_pages: tuple[int, ...]
    last_page: int
    empty: bool


def _progress(event: str, **fields: Any) -> None:
    """Emit only aggregate, non-identifying runtime diagnostics."""
    print(_canonical_json({"survey_progress": {"event": event, **fields}}), flush=True)


def _selected_tab(tree: str) -> str | None:
    matches = []
    for line in tree.splitlines():
        match = SELECTED_TAB_RE.match(line)
        if not match:
            continue
        tab_name = _canonical_tab_name(match.group(1))
        if tab_name is not None:
            matches.append(tab_name)
    return matches[0] if len(matches) == 1 else None


def _selected_page(tree: str) -> int | None:
    matches = [
        int(match.group(1))
        for line in tree.splitlines()
        if (match := SELECTED_PAGE_RE.match(line))
    ]
    return matches[0] if len(matches) == 1 else None


def _tab_buttons(tree: str) -> dict[str, int]:
    buttons: dict[str, int] = {}
    for line in tree.splitlines():
        match = TAB_BUTTON_RE.match(line)
        if match:
            tab_name = _canonical_tab_name(match.group(2))
            if tab_name is not None:
                buttons[tab_name] = int(match.group(1))
    return buttons


def _explicit_empty_state(tree: str) -> bool:
    return any(pattern.search(tree) for pattern in EMPTY_STATE_PATTERNS)


def _pagination_buttons(tree: str) -> dict[int, int]:
    buttons: dict[int, int] = {}
    for line in tree.splitlines():
        match = PAGE_BUTTON_RE.match(line)
        if not match:
            continue
        page_no = int(match.group(2))
        if page_no in buttons:
            raise SurveyError("pagination_numeric_control_ambiguous")
        buttons[page_no] = int(match.group(1))
    return buttons


def _pagination_controls(tree: str) -> dict[str, int]:
    candidates: dict[str, list[tuple[str, int]]] = {
        "next": [],
        "previous": [],
    }
    for line in tree.splitlines():
        match = PAGINATION_CONTROL_RE.match(line)
        if not match:
            continue
        label = match.group(2).strip()
        direction = _pagination_direction(label)
        if direction is None:
            continue
        candidates[direction].append((label, int(match.group(1))))
    controls: dict[str, int] = {}
    for direction, items in candidates.items():
        if not items:
            continue
        page_labeled = [
            item
            for item in items
            if item[0].endswith(" page") or item[0].endswith("페이지")
        ]
        selected = page_labeled if page_labeled else items
        if len(selected) != 1:
            raise SurveyError("pagination_range_control_ambiguous")
        controls[direction] = selected[0][1]
    return controls


def _is_page_step_control(
    tree: str, direction: str, element_index: int
) -> bool:
    """Identify the control that :func:`_pagination_controls` would pick."""
    try:
        controls = _pagination_controls(tree)
    except SurveyError:
        return False
    return controls.get(direction) == element_index


def _infer_last_page(tree: str, *, empty: bool) -> tuple[tuple[int, ...], int]:
    pages = tuple(sorted(_pagination_buttons(tree)))
    if empty or not pages:
        return pages, 1
    if pages[0] != 1:
        raise SurveyError("pagination_first_page_sentinel_missing")
    last_page = pages[-1]
    if last_page > MAX_PAGES_PER_TAB:
        raise SurveyError("tab_page_limit_exceeded")
    return pages, last_page


def _survey_tree(app: str, window_id: int) -> str:
    """Read the accessibility tree without creating a screenshot artifact."""
    result = _run_orca(
        "computer",
        "get-app-state",
        "--app",
        app,
        "--window-id",
        str(window_id),
        *_restore_window_args(),
        "--no-screenshot",
    )
    return str(result["result"]["snapshot"]["treeText"])


def _click_element(
    app: str,
    window_id: int,
    element_index: int,
    *,
    tree: str,
) -> None:
    arguments = [
        "computer",
        "click",
        "--app",
        app,
        "--window-id",
        str(window_id),
        "--element-index",
        str(element_index),
        *_restore_window_args(),
        "--no-screenshot",
    ]
    if os.environ.get("AGODA_UI_BACKEND") == "windows_uia":
        arguments.extend(
            [
                "--expected-name-sha256",
                _sha256_text(_element_name(tree, element_index)),
            ]
        )
    _run_orca(*arguments)


def _load_or_create_hmac_key(path: Path) -> tuple[bytes, str]:
    key_path = _require_tmp(path)
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(key_path.parent, 0o700)
    if key_path.exists():
        if key_path.is_symlink() or (
            os.name != "nt" and (key_path.stat().st_mode & 0o077) != 0
        ):
            raise SurveyError("pseudonym_key_permissions_invalid")
        key = key_path.read_bytes()
    else:
        key = secrets.token_bytes(32)
        try:
            descriptor = os.open(
                key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError as exc:
            raise SurveyError("pseudonym_key_creation_race") from exc
        try:
            os.write(descriptor, key)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(key_path, 0o600)
    if len(key) < 32:
        raise SurveyError("pseudonym_key_too_short")
    key_id = hashlib.sha256(key).hexdigest()[:16]
    return key, f"agoda-hmac-v1:{key_id}"


def _booking_pseudonym(key: bytes, booking_id: str) -> str:
    return hmac.new(key, booking_id.encode("utf-8"), hashlib.sha256).hexdigest()


def _scope_status(start_on: str | None, end_on: str | None) -> str:
    if not start_on or not end_on:
        return "year_unknown"
    try:
        start = date.fromisoformat(start_on)
        end = date.fromisoformat(end_on)
    except ValueError:
        return "year_unknown"
    if end < start:
        return "year_unknown"
    if start <= date(2026, 12, 31) and end >= date(2026, 1, 1):
        return "target_2026_overlap"
    return "outside_2026"


def _survey_cards(
    tree: str,
    tab_name: str,
    page_no: int | None,
    pseudonym_key: bytes,
) -> list[dict[str, Any]]:
    blocks = _card_blocks(tree)
    parsed_cards = _extract_cards(tree, page_no)
    if len(blocks) != len(parsed_cards):
        raise SurveyError("card_block_parser_count_mismatch")
    cards: list[dict[str, Any]] = []
    for position, (block, parsed) in enumerate(zip(blocks, parsed_cards), start=1):
        manage_matches = [
            match
            for line in block.splitlines()
            if (match := MANAGE_BUTTON_RE.match(line))
        ]
        if len(manage_matches) != 1 or not manage_matches[0].group(2):
            raise SurveyError("actual_booking_id_missing_or_ambiguous")
        booking_id = str(manage_matches[0].group(2))
        pseudonym = _booking_pseudonym(pseudonym_key, booking_id)
        scope = _scope_status(parsed["service_start_on"], parsed["service_end_on"])
        booking_normalized = {
            "tab_name": tab_name,
            "booking_pseudonym_hmac": pseudonym,
            "service_start_on": parsed["service_start_on"],
            "service_end_on": parsed["service_end_on"],
            "scope_status": scope,
            "reservation_status": parsed["status"],
            "action_kind": "manage_booking",
        }
        booking_semantic_sha256 = _sha256_text(
            _canonical_json(booking_normalized)
        )
        occurrence_normalized = {
            **booking_normalized,
            "page_no": page_no,
            "card_position": position,
            "booking_semantic_sha256": booking_semantic_sha256,
        }
        cards.append(
            {
                **occurrence_normalized,
                "booking_id": booking_id,
                "service_years_json": parsed["service_years_json"],
                "booking_semantic_sha256": booking_semantic_sha256,
                "semantic_card_sha256": _sha256_text(
                    _canonical_json(occurrence_normalized)
                ),
            }
        )
    return cards


def _build_state(
    tree: str,
    tab_name: str,
    page_no: int | None,
    pseudonym_key: bytes,
) -> TabState:
    if _selected_tab(tree) != tab_name:
        raise SurveyError("selected_tab_attestation_mismatch")
    blocks_present = "mmb-booking-card--" in tree
    empty = _explicit_empty_state(tree)
    if blocks_present == empty:
        raise SurveyError("tab_population_state_ambiguous")
    visible_pages, last_page = _infer_last_page(tree, empty=empty)
    observed_page = _selected_page(tree)
    if visible_pages:
        if observed_page is None:
            # The native Orca provider exposes Agoda's numeric pagination
            # buttons but does not expose a selected/``기본`` state for them.
            # In that provider only, the caller's requested page is the
            # action-derived page identity; the numeric range, card hashes,
            # and previous-page hash still provide the independent guards.
            if (
                os.environ.get("AGODA_UI_BACKEND") == "windows_uia"
                or (page_no is not None and page_no not in visible_pages)
            ):
                raise SurveyError("selected_page_attestation_missing_or_ambiguous")
            effective_page = 1 if page_no is None else page_no
        elif page_no is not None and observed_page != page_no:
            raise SurveyError("selected_page_attestation_mismatch")
        else:
            effective_page = observed_page
    else:
        effective_page = 1
        if page_no not in {None, 1}:
            raise SurveyError("selected_page_attestation_mismatch")
    cards = tuple(
        _survey_cards(tree, tab_name, effective_page, pseudonym_key)
        if blocks_present
        else []
    )
    page_pseudonyms = [card["booking_pseudonym_hmac"] for card in cards]
    if len(page_pseudonyms) != len(set(page_pseudonyms)):
        raise SurveyError("duplicate_booking_within_single_page")
    ordered_hash = _sha256_text(
        _canonical_json([card["semantic_card_sha256"] for card in cards])
    )
    set_hash = _sha256_text(
        _canonical_json(sorted(card["semantic_card_sha256"] for card in cards))
    )
    return TabState(
        tree=tree,
        tab_name=tab_name,
        page_no=effective_page,
        cards=cards,
        ordered_page_sha256=ordered_hash,
        set_page_sha256=set_hash,
        visible_pages=visible_pages,
        last_page=last_page,
        empty=empty,
    )


def _wait_tab_state(
    app: str,
    window_id: int,
    tab_name: str,
    page_no: int,
    pseudonym_key: bytes,
    *,
    initial_tree: str | None = None,
    previous_page_sha256: str | None = None,
    expected_last_page: int | None = None,
    timeout_seconds: float = 120.0,
    refresh_after_seconds: float = 20.0,
    partial_stable_seconds: float = 10.0,
) -> TabState:
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    refresh_at = started_at + refresh_after_seconds
    refresh_used = False
    previous_signature: tuple[Any, ...] | None = None
    signature_first_seen_at: float | None = None
    last_error: SurveyError | None = None
    pending_tree = initial_tree
    while time.monotonic() < deadline:
        if pending_tree is not None:
            tree = pending_tree
            pending_tree = None
        else:
            tree = _survey_tree(app, window_id)
        try:
            state = _build_state(tree, tab_name, page_no, pseudonym_key)
        except SurveyError as exc:
            last_error = exc
            _progress(
                "state_not_ready",
                tab_name=tab_name,
                page_no=page_no,
                reason=str(exc),
                selected_tab=_selected_tab(tree),
            )
            loading = any(
                marker in tree.casefold()
                for marker in ("loading", "skeleton", "spinner")
            )
            if (
                str(exc) == "tab_population_state_ambiguous"
                and loading
                and not refresh_used
                and time.monotonic() >= refresh_at
            ):
                _run_orca(
                    "computer",
                    "hotkey",
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    "--key",
                    "CmdOrCtrl+R",
                    *_restore_window_args(),
                    "--no-screenshot",
                )
                refresh_used = True
                _progress(
                    "stuck_loading_refreshed",
                    tab_name=tab_name,
                    page_no=page_no,
                )
            previous_signature = None
            signature_first_seen_at = None
            time.sleep(0.75)
            continue
        if (
            previous_page_sha256 is not None
            and state.ordered_page_sha256 == previous_page_sha256
        ):
            previous_signature = None
            signature_first_seen_at = None
            time.sleep(0.75)
            continue
        if expected_last_page is not None and state.last_page != expected_last_page:
            last_error = SurveyError("pagination_last_page_drift")
            previous_signature = None
            signature_first_seen_at = None
            time.sleep(0.75)
            continue
        signature = (
            state.ordered_page_sha256,
            state.set_page_sha256,
            state.visible_pages,
            state.last_page,
            state.page_no,
            state.empty,
        )
        observed_at = time.monotonic()
        stable_repeat = signature == previous_signature
        if not stable_repeat:
            signature_first_seen_at = observed_at
        required_stable_seconds = (
            partial_stable_seconds
            if state.page_no == state.last_page or len(state.cards) < 40
            else 0.0
        )
        stable_for_seconds = (
            observed_at - signature_first_seen_at
            if stable_repeat and signature_first_seen_at is not None
            else 0.0
        )
        _progress(
            "state_observed",
            tab_name=tab_name,
            page_no=state.page_no,
            requested_page_no=page_no,
            card_count=len(state.cards),
            ordered_page_sha256=state.ordered_page_sha256[:16],
            visible_pages=list(state.visible_pages),
            last_page=state.last_page,
            stable_repeat=stable_repeat,
            stable_for_seconds=round(stable_for_seconds, 3),
            required_stable_seconds=required_stable_seconds,
        )
        if stable_repeat and stable_for_seconds >= required_stable_seconds:
            if refresh_used:
                raise SurveyError("browser_refresh_requires_fresh_sweep")
            return state
        previous_signature = signature
        time.sleep(0.75)
    raise SurveyError("booking_tab_state_did_not_stabilize") from last_error


def _navigate_bookings_url(app: str, window_id: int) -> None:
    # Ctrl+L can be acknowledged without selecting the omnibox in Chromium.
    # The direct Orca backend exposes the address bar as a settable element;
    # overwrite that element so a malformed value cannot be appended to the
    # existing edge://blank route.
    if os.environ.get("AGODA_UI_BACKEND", "").strip().lower() != "windows_uia":
        for attempt in range(1, 4):
            _progress("route_command_attempt", command="set-value", attempt=attempt)
            try:
                state = _run_orca(
                    "computer",
                    "get-app-state",
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    *_restore_window_args(),
                    "--no-screenshot",
                )
                tree = str(state["result"]["snapshot"]["treeText"])
                address_index = next(
                    int(line.split(maxsplit=1)[0])
                    for line in tree.splitlines()
                    if "주소 표시줄" in line or "address bar" in line.casefold()
                )
                _run_orca(
                    "computer",
                    "set-value",
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    "--element-index",
                    str(address_index),
                    "--value",
                    BOOKINGS_URL,
                    *_restore_window_args(),
                    "--no-screenshot",
                )
                _run_orca(
                    "computer",
                    "press-key",
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    "--key",
                    "Return",
                    *_restore_window_args(),
                    "--no-screenshot",
                )
            except (RuntimeError, StopIteration):
                _progress("route_command_retry", command="set-value", attempt=attempt)
                if attempt == 3:
                    raise SurveyError("route_command_failed:set-value")
                time.sleep(1.0)
                continue
            _progress("route_command_succeeded", command="set-value", attempt=attempt)
            return

    for command, arguments in (
        ("hotkey", ("--key", "CmdOrCtrl+L")),
        ("type-text", ("--text", BOOKINGS_URL)),
        ("press-key", ("--key", "Return")),
    ):
        for attempt in range(1, 4):
            _progress("route_command_attempt", command=command, attempt=attempt)
            try:
                _run_orca(
                    "computer",
                    command,
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    *_restore_window_args(),
                    "--no-screenshot",
                    *arguments,
                )
            except RuntimeError:
                _progress("route_command_retry", command=command, attempt=attempt)
                if attempt == 3:
                    raise SurveyError(f"route_command_failed:{command}")
                time.sleep(1.0)
                continue
            _progress("route_command_succeeded", command=command, attempt=attempt)
            break


def _click_tab(app: str, window_id: int, tree: str, tab_name: str) -> None:
    buttons = _tab_buttons(tree)
    if tab_name not in buttons:
        raise SurveyError("booking_tab_button_missing")
    # Agoda exposes the booking-stage controls as accessibility tabs whose
    # advertised action is ``Select``.  A generic click can return success
    # without changing the selected tab, so use the semantic action and let
    # ``_wait_tab_state`` attest the resulting ``기본 <tab>`` marker.
    arguments = [
        "computer",
        "perform-secondary-action",
        "--app",
        app,
        "--window-id",
        str(window_id),
        "--element-index",
        str(buttons[tab_name]),
        "--action",
        "Select",
        *_restore_window_args(),
        "--no-screenshot",
    ]
    if os.environ.get("AGODA_UI_BACKEND") == "windows_uia":
        arguments.extend(
            [
                "--expected-name-sha256",
                _sha256_text(_element_name(tree, buttons[tab_name])),
            ]
        )
    _run_orca(*arguments)


def _ensure_tab_selected(
    app: str,
    window_id: int,
    tab_name: str,
    *,
    initial_tree: str | None = None,
    attempts: int = 4,
) -> str:
    """Select a tab, retrying accessibility actions that report a false no-op."""
    tree = initial_tree if initial_tree is not None else _survey_tree(app, window_id)
    # After returning from a detail view, Chromium/UIA can expose the list
    # cards before Agoda repaints the selected-tab marker.  Clicking during
    # that interval is a false no-op and can leave the resumable worker in a
    # recovery loop.  Wait for one bounded fresh observation first; this does
    # not infer a tab and still requires the actual selected marker below.
    if _selected_tab(tree) is None:
        marker_deadline = time.monotonic() + 12.0
        while time.monotonic() < marker_deadline:
            time.sleep(0.5)
            candidate = _survey_tree(app, window_id)
            if _selected_tab(candidate) is not None:
                tree = candidate
                break
    for attempt in range(1, attempts + 1):
        if _selected_tab(tree) == tab_name:
            _progress("tab_selected", tab_name=tab_name, attempt=attempt - 1)
            return tree
        _progress(
            "tab_select_attempt",
            tab_name=tab_name,
            attempt=attempt,
            selected_tab=_selected_tab(tree),
        )
        try:
            _click_tab(app, window_id, tree, tab_name)
        except RuntimeError:
            # A transient UIA transport failure is not evidence that the
            # semantic Select action failed or succeeded.  Refresh the same
            # window tree and let the next loop iteration attest before any
            # retry.
            _progress(
                "tab_select_transport_retry",
                tab_name=tab_name,
                attempt=attempt,
            )
            tree = _survey_tree(app, window_id)
            time.sleep(0.5)
            continue
        tree = _survey_tree(app, window_id)
    if _selected_tab(tree) == tab_name:
        return tree
    raise SurveyError("booking_tab_select_noop_after_retries")


def _click_visible_numeric_page(
    app: str,
    window_id: int,
    tab_name: str,
    target_page: int,
    tree: str,
    *,
    attempts: int = 3,
) -> str:
    """Click a visible page by semantic name and attest the disabled target."""
    current_tree = tree
    for attempt in range(1, attempts + 1):
        if _selected_tab(current_tree) != tab_name:
            raise SurveyError("selected_tab_attestation_mismatch")
        if _selected_page(current_tree) == target_page:
            return current_tree
        buttons = _pagination_buttons(current_tree)
        if target_page not in buttons:
            raise SurveyError("visible_page_target_missing")
        _progress(
            "numeric_page_click_attempt",
            tab_name=tab_name,
            target_page=target_page,
            attempt=attempt,
            observed_page=_selected_page(current_tree),
        )
        page_before_click = _selected_page(current_tree)
        try:
            _click_element(
                app,
                window_id,
                buttons[target_page],
                tree=current_tree,
            )
        except RuntimeError:
            # Re-read the same HWND after a transport failure.  The next
            # iteration still requires the expected tab and disabled numeric
            # page attestation, so this cannot manufacture navigation.
            _progress(
                "numeric_page_click_transport_retry",
                tab_name=tab_name,
                target_page=target_page,
                attempt=attempt,
            )
            refreshed_tree = _survey_tree(app, window_id)
            if _selected_tab(refreshed_tree) != tab_name:
                raise SurveyError(
                    "numeric_page_transport_changed_selected_tab"
                )
            observed_after_error = _selected_page(refreshed_tree)
            if observed_after_error not in {page_before_click, target_page}:
                raise SurveyError(
                    "numeric_page_transport_changed_selected_page"
                )
            current_tree = refreshed_tree
            time.sleep(0.5)
            continue
        for _ in range(3):
            candidate = _survey_tree(app, window_id)
            if (
                _selected_tab(candidate) == tab_name
                and _selected_page(candidate) == target_page
            ):
                return candidate
            if (
                os.environ.get("AGODA_UI_BACKEND") != "windows_uia"
                and _selected_tab(candidate) == tab_name
                and _selected_page(candidate) is None
                and target_page in _pagination_buttons(candidate)
            ):
                # Native Orca confirms the semantic click, while Agoda's
                # page button has no exposed selected state.  The subsequent
                # state wait still requires a stable card population and,
                # for detail capture, the sealed source-page hash.
                return candidate
            current_tree = candidate
            time.sleep(0.5)
    raise SurveyError("numeric_page_click_noop_after_retries")


def _force_first_numeric_page(
    app: str,
    window_id: int,
    tab_name: str,
    state: TabState,
    pseudonym_key: bytes,
) -> TabState:
    """Establish page 1 even when Agoda preserves a tab's prior page."""
    if state.empty or state.page_no == 1:
        if (
            not state.empty
            and state.page_no == 1
            and os.environ.get("AGODA_UI_BACKEND") != "windows_uia"
        ):
            # The native provider cannot report which numeric button is
            # selected.  Re-apply page 1 once so the origin is action-derived
            # before any forward page walk begins.
            selected_tree = _click_visible_numeric_page(
                app, window_id, tab_name, 1, state.tree
            )
            return _wait_tab_state(
                app,
                window_id,
                tab_name,
                1,
                pseudonym_key,
                initial_tree=selected_tree,
                expected_last_page=state.last_page,
            )
        return state
    selected_tree = _click_visible_numeric_page(
        app, window_id, tab_name, 1, state.tree
    )
    return _wait_tab_state(
        app,
        window_id,
        tab_name,
        1,
        pseudonym_key,
        initial_tree=selected_tree,
        expected_last_page=state.last_page,
    )


def _select_tab_at_first_page(
    app: str,
    window_id: int,
    tab_name: str,
    pseudonym_key: bytes,
) -> TabState:
    # Normally re-enter the allowlisted route for every tab scan.  When an
    # already-authenticated user tab is supplied by the native Edge/UIA
    # runtime, however, navigation can be blocked by the client even though
    # the existing page is usable.  The opt-in preservation mode lets the
    # caller keep that tab and still applies the same accessibility
    # attestations below; it never fabricates a list state.
    preserve_existing_tab = os.environ.get(
        "AGODA_UI_PRESERVE_BOOKINGS_TAB"
    ) == "1"
    if preserve_existing_tab:
        _progress("route_reset_skipped_existing_tab", target_tab=tab_name)
    else:
        # The static URL contains no booking/query token and is never
        # persisted.
        _progress("route_reset_started", target_tab=tab_name)
        _navigate_bookings_url(app, window_id)
    tree = _survey_tree(app, window_id)
    # Agoda remembers the last selected tab across a route reload.  Establish
    # the known Upcoming origin explicitly before deriving any page identity.
    tree = _ensure_tab_selected(
        app, window_id, "Upcoming", initial_tree=tree
    )
    upcoming = _wait_tab_state(
        app,
        window_id,
        "Upcoming",
        None,
        pseudonym_key,
        initial_tree=tree,
    )
    if tab_name == "Upcoming":
        return _force_first_numeric_page(
            app, window_id, tab_name, upcoming, pseudonym_key
        )
    tree = _ensure_tab_selected(
        app, window_id, tab_name, initial_tree=upcoming.tree
    )
    selected_state = _wait_tab_state(
        app,
        window_id,
        tab_name,
        None,
        pseudonym_key,
        initial_tree=tree,
    )
    return _force_first_numeric_page(
        app, window_id, tab_name, selected_state, pseudonym_key
    )


def _wait_pagination_range(
    app: str,
    window_id: int,
    tab_name: str,
    previous_pages: tuple[int, ...],
    expected_last_page: int,
    *,
    timeout_seconds: float = 120.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    previous_signature: tuple[int, ...] | None = None
    while time.monotonic() < deadline:
        tree = _survey_tree(app, window_id)
        pages = tuple(sorted(_pagination_buttons(tree)))
        valid = (
            _selected_tab(tree) == tab_name
            and pages
            and pages[0] == 1
            and pages[-1] == expected_last_page
            and pages != previous_pages
        )
        if valid and pages == previous_signature:
            return tree
        previous_signature = pages if valid else None
        time.sleep(0.75)
    raise SurveyError("pagination_numeric_range_did_not_change")


def _go_to_numeric_page(
    app: str,
    window_id: int,
    tab_name: str,
    target_page: int,
    current_page: int,
    current_state: TabState,
    pseudonym_key: bytes,
) -> TabState:
    if target_page <= current_page:
        raise SurveyError("pagination_target_not_forward")
    expected_last_page = current_state.last_page
    tree = current_state.tree
    for _range_attempt in range(20):
        buttons = _pagination_buttons(tree)
        if target_page in buttons:
            selected_tree = _click_visible_numeric_page(
                app,
                window_id,
                tab_name,
                target_page,
                tree,
            )
            return _wait_tab_state(
                app,
                window_id,
                tab_name,
                target_page,
                pseudonym_key,
                initial_tree=selected_tree,
                previous_page_sha256=current_state.ordered_page_sha256,
                expected_last_page=expected_last_page,
            )

        visible = tuple(sorted(buttons))
        if not visible or visible[0] != 1 or visible[-1] != expected_last_page:
            raise SurveyError("pagination_last_page_sentinel_missing")
        middle = [page for page in visible if page not in {1, expected_last_page}]
        middle_min = min(middle) if middle else visible[0]
        middle_max = max(middle) if middle else visible[-1]
        controls = _pagination_controls(tree)
        if target_page > middle_max and "next" in controls:
            direction = "next"
        elif target_page < middle_min and "previous" in controls:
            direction = "previous"
        else:
            raise SurveyError("pagination_target_not_reachable")
        control_index = controls[direction]
        page_step_control = _is_page_step_control(
            tree, direction, control_index
        )
        try:
            _click_element(app, window_id, control_index, tree=tree)
        except RuntimeError:
            # Range controls are also semantic UIA clicks.  Re-read and
            # re-evaluate the visible range instead of terminating the worker
            # or assuming that the range advanced.
            _progress(
                "pagination_range_click_transport_retry",
                tab_name=tab_name,
                target_page=target_page,
                direction=direction,
                range_attempt=_range_attempt + 1,
            )
            refreshed_tree = _survey_tree(app, window_id)
            if _selected_tab(refreshed_tree) != tab_name:
                raise SurveyError(
                    "pagination_range_transport_changed_selected_tab"
                )
            observed_after_error = _selected_page(refreshed_tree)
            allowed_pages = {current_page}
            if (
                page_step_control
                and target_page == current_page + 1
            ):
                allowed_pages.add(target_page)
            if observed_after_error not in allowed_pages:
                raise SurveyError(
                    "pagination_range_transport_changed_selected_page"
                )
            tree = refreshed_tree
            time.sleep(0.5)
            continue
        tree = _wait_pagination_range(
            app,
            window_id,
            tab_name,
            visible,
            expected_last_page,
        )
        observed_page = _selected_page(tree)
        if (
            observed_page is None
            and os.environ.get("AGODA_UI_BACKEND") != "windows_uia"
        ):
            observed_page = current_page
        if observed_page == target_page and (
            direction == "next"
            and page_step_control
            and target_page == current_page + 1
        ):
            # Agoda can make ``Next page`` both advance one booking page and
            # reveal the next numeric range.  The transition starts from an
            # attested current page; require the new population to stabilize.
            return _wait_tab_state(
                app,
                window_id,
                tab_name,
                target_page,
                pseudonym_key,
                initial_tree=tree,
                previous_page_sha256=current_state.ordered_page_sha256,
                expected_last_page=expected_last_page,
            )
        if observed_page != current_page:
            raise SurveyError("pagination_range_shift_changed_selected_page")
        range_state = _build_state(
            tree, tab_name, current_page, pseudonym_key
        )
        if range_state.ordered_page_sha256 != current_state.ordered_page_sha256:
            raise SurveyError("pagination_range_shift_changed_booking_cards")
    raise SurveyError("pagination_range_navigation_exceeded_retry_limit")


def _scan_tab(
    app: str,
    window_id: int,
    tab_name: str,
    pass_no: int,
    pseudonym_key: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state = _select_tab_at_first_page(app, window_id, tab_name, pseudonym_key)
    pages: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    seen_page_hashes: set[str] = set()
    last_page = state.last_page
    if not 1 <= last_page <= MAX_PAGES_PER_TAB:
        raise SurveyError("tab_page_limit_exceeded")
    for page_no in range(1, last_page + 1):
        if page_no > 1:
            state = _go_to_numeric_page(
                app,
                window_id,
                tab_name,
                page_no,
                page_no - 1,
                state,
                pseudonym_key,
            )
        if state.ordered_page_sha256 in seen_page_hashes:
            raise SurveyError("tab_page_sequence_repeated")
        seen_page_hashes.add(state.ordered_page_sha256)
        page_cards = [dict(card, pass_no=pass_no) for card in state.cards]
        page_pseudonyms = [
            card["booking_pseudonym_hmac"] for card in page_cards
        ]
        target_count = sum(
            card["scope_status"] == "target_2026_overlap" for card in page_cards
        )
        unknown_count = sum(
            card["scope_status"] == "year_unknown" for card in page_cards
        )
        page = {
            "pass_no": pass_no,
            "tab_name": tab_name,
            "page_no": page_no,
            "card_count": len(page_cards),
            "target_2026_count": target_count,
            "year_unknown_count": unknown_count,
            "duplicate_occurrence_count": (
                len(page_pseudonyms) - len(set(page_pseudonyms))
            ),
            "ordered_page_sha256": state.ordered_page_sha256,
            "set_page_sha256": state.set_page_sha256,
            "next_enabled": int(page_no < last_page),
            "terminal_reason": (
                "explicit_empty_state"
                if state.empty
                else "numeric_last_page"
                if page_no == last_page
                else None
            ),
        }
        pages.append(page)
        cards.extend(page_cards)
        print(
            _canonical_json(
                {
                    "page": {
                        "pass_no": pass_no,
                        "tab_name": tab_name,
                        "page_no": page_no,
                        "card_count": len(page_cards),
                        "target_2026_count": target_count,
                        "year_unknown_count": unknown_count,
                        "duplicate_occurrence_count": page[
                            "duplicate_occurrence_count"
                        ],
                        "terminal": page["terminal_reason"],
                    }
                }
            ),
            flush=True,
        )
    return pages, cards


def _pass_manifest(
    pages: Sequence[dict[str, Any]], cards: Sequence[dict[str, Any]]
) -> str:
    semantic = {
        "pages": [
            {
                key: page[key]
                for key in (
                    "tab_name",
                    "page_no",
                    "card_count",
                    "target_2026_count",
                    "year_unknown_count",
                    "duplicate_occurrence_count",
                    "ordered_page_sha256",
                    "set_page_sha256",
                    "next_enabled",
                    "terminal_reason",
                )
            }
            for page in pages
        ],
        "cards": [
            {
                key: card[key]
                for key in (
                    "tab_name",
                    "page_no",
                    "card_position",
                    "booking_pseudonym_hmac",
                    "service_start_on",
                    "service_end_on",
                    "scope_status",
                    "reservation_status",
                    "booking_semantic_sha256",
                    "semantic_card_sha256",
                )
            }
            for card in cards
        ],
    }
    return _sha256_text(_canonical_json(semantic))


def _canonical_bookings(
    cards: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    if any(card["scope_status"] not in {
        "target_2026_overlap", "year_unknown", "outside_2026"
    } for card in cards):
        raise SurveyError("invalid_scope_status")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        grouped.setdefault(str(card["booking_pseudonym_hmac"]), []).append(card)
    canonical: list[dict[str, Any]] = []
    for pseudonym, occurrences in grouped.items():
        if len({str(item["booking_id"]) for item in occurrences}) != 1:
            raise SurveyError("booking_pseudonym_collision")
        if len({str(item["booking_semantic_sha256"]) for item in occurrences}) != 1:
            raise SurveyError("booking_semantic_conflict_across_observations")
        first = min(
            occurrences,
            key=lambda item: (
                int(item["pass_no"]),
                TAB_NAMES.index(str(item["tab_name"])),
                int(item["page_no"]),
                int(item["card_position"]),
            ),
        )
        canonical.append(
            {
                **first,
                "booking_pseudonym_hmac": pseudonym,
                "observation_count": len(occurrences),
            }
        )
    return sorted(
        canonical,
        key=lambda item: (
            TAB_NAMES.index(str(item["tab_name"])),
            str(item["booking_pseudonym_hmac"]),
        ),
    )


def _convergence_manifest(
    expected_tab_totals: dict[str, int],
    canonical: Sequence[dict[str, Any]],
) -> str:
    return _sha256_text(
        _canonical_json(
            {
                "expected_tab_totals": expected_tab_totals,
                "canonical_bookings": [
                    {
                        key: card[key]
                        for key in (
                            "tab_name",
                            "booking_pseudonym_hmac",
                            "service_start_on",
                            "service_end_on",
                            "scope_status",
                            "reservation_status",
                            "booking_semantic_sha256",
                        )
                    }
                    for card in canonical
                ],
            }
        )
    )


def _validate_occurrences(cards: Sequence[dict[str, Any]]) -> None:
    _canonical_bookings(cards)


def _stable_pair_canonical(
    pass_results: Sequence[
        tuple[list[dict[str, Any]], list[dict[str, Any]]]
    ],
    population_manifests: Sequence[str],
) -> list[dict[str, Any]] | None:
    """Return the unique population proven by two equivalent full sweeps.

    Agoda can persistently repeat a booking on two different pages. Requiring
    unique bookings to equal the sum of page slots would turn those repeats
    into an impossible completeness target. The evidence we can prove is that
    the unique semantic booking population is identical in two consecutive
    full sweeps; page movement at tied sort boundaries is allowed.
    """
    if len(pass_results) < 2 or len(population_manifests) < 2:
        return None
    if population_manifests[-1] != population_manifests[-2]:
        return None
    stable_cards = [
        card
        for _, cards in pass_results[-2:]
        for card in cards
    ]
    return _canonical_bookings(stable_cards)


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE survey_run_manifest(
            run_id TEXT PRIMARY KEY,
            source_origin TEXT NOT NULL,
            source_route_kind TEXT NOT NULL,
            pseudonym_key_id TEXT NOT NULL,
            tab_count INTEGER NOT NULL CHECK(tab_count = 3),
            verification_pass_count INTEGER NOT NULL CHECK(verification_pass_count >= 2),
            captured_page_count INTEGER NOT NULL,
            captured_card_count INTEGER NOT NULL,
            canonical_booking_count INTEGER NOT NULL,
            target_2026_count INTEGER NOT NULL,
            year_unknown_count INTEGER NOT NULL,
            outside_2026_count INTEGER NOT NULL,
            duplicate_occurrence_count INTEGER NOT NULL CHECK(duplicate_occurrence_count >= 0),
            expected_tab_totals_json TEXT NOT NULL,
            pass_manifest_sha256 TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        CREATE TABLE survey_pages(
            pass_no INTEGER NOT NULL CHECK(pass_no >= 1),
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            card_count INTEGER NOT NULL,
            target_2026_count INTEGER NOT NULL,
            year_unknown_count INTEGER NOT NULL,
            duplicate_occurrence_count INTEGER NOT NULL CHECK(duplicate_occurrence_count >= 0),
            ordered_page_sha256 TEXT NOT NULL,
            set_page_sha256 TEXT NOT NULL,
            next_enabled INTEGER NOT NULL CHECK(next_enabled IN (0,1)),
            terminal_reason TEXT,
            PRIMARY KEY(pass_no, tab_name, page_no)
        );
        CREATE TABLE survey_booking_cards(
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            pass_no INTEGER NOT NULL CHECK(pass_no >= 1),
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            card_position INTEGER NOT NULL,
            booking_id TEXT NOT NULL,
            booking_pseudonym_hmac TEXT NOT NULL,
            service_start_on TEXT,
            service_end_on TEXT,
            service_years_json TEXT NOT NULL,
            scope_status TEXT NOT NULL CHECK(
                scope_status IN ('target_2026_overlap','year_unknown','outside_2026')
            ),
            reservation_status TEXT NOT NULL,
            booking_semantic_sha256 TEXT NOT NULL,
            semantic_card_sha256 TEXT NOT NULL,
            UNIQUE(pass_no, tab_name, page_no, card_position)
        );
        CREATE TABLE survey_canonical_bookings(
            canonical_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tab_name TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            booking_pseudonym_hmac TEXT NOT NULL UNIQUE,
            service_start_on TEXT,
            service_end_on TEXT,
            service_years_json TEXT NOT NULL,
            scope_status TEXT NOT NULL CHECK(
                scope_status IN ('target_2026_overlap','year_unknown','outside_2026')
            ),
            reservation_status TEXT NOT NULL,
            booking_semantic_sha256 TEXT NOT NULL,
            first_pass_no INTEGER NOT NULL,
            first_page_no INTEGER NOT NULL,
            first_card_position INTEGER NOT NULL,
            observation_count INTEGER NOT NULL CHECK(observation_count >= 1)
        );
        CREATE INDEX idx_survey_scope
            ON survey_booking_cards(pass_no, scope_status, booking_pseudonym_hmac);
        """
    )


def _insert_pass(
    connection: sqlite3.Connection,
    pages: Sequence[dict[str, Any]],
    cards: Sequence[dict[str, Any]],
) -> None:
    connection.executemany(
        """
        INSERT INTO survey_pages(
            pass_no, tab_name, page_no, card_count, target_2026_count,
            year_unknown_count, duplicate_occurrence_count,
            ordered_page_sha256, set_page_sha256,
            next_enabled, terminal_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                page["pass_no"], page["tab_name"], page["page_no"],
                page["card_count"], page["target_2026_count"],
                page["year_unknown_count"], page["duplicate_occurrence_count"],
                page["ordered_page_sha256"],
                page["set_page_sha256"], page["next_enabled"],
                page["terminal_reason"],
            )
            for page in pages
        ],
    )
    connection.executemany(
        """
        INSERT INTO survey_booking_cards(
            pass_no, tab_name, page_no, card_position, booking_id,
            booking_pseudonym_hmac, service_start_on, service_end_on,
            service_years_json, scope_status, reservation_status,
            booking_semantic_sha256, semantic_card_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                card["pass_no"], card["tab_name"], card["page_no"],
                card["card_position"], card["booking_id"],
                card["booking_pseudonym_hmac"], card["service_start_on"],
                card["service_end_on"], card["service_years_json"],
                card["scope_status"], card["reservation_status"],
                card["booking_semantic_sha256"],
                card["semantic_card_sha256"],
            )
            for card in cards
        ],
    )


def _insert_canonical_bookings(
    connection: sqlite3.Connection,
    canonical: Sequence[dict[str, Any]],
) -> None:
    connection.executemany(
        """
        INSERT INTO survey_canonical_bookings(
            tab_name, booking_id, booking_pseudonym_hmac,
            service_start_on, service_end_on, service_years_json,
            scope_status, reservation_status, booking_semantic_sha256,
            first_pass_no, first_page_no, first_card_position,
            observation_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                card["tab_name"],
                card["booking_id"],
                card["booking_pseudonym_hmac"],
                card["service_start_on"],
                card["service_end_on"],
                card["service_years_json"],
                card["scope_status"],
                card["reservation_status"],
                card["booking_semantic_sha256"],
                card["pass_no"],
                card["page_no"],
                card["card_position"],
                card["observation_count"],
            )
            for card in canonical
        ],
    )


def _publish_memory_database(connection: sqlite3.Connection, destination: Path) -> None:
    final_path = _require_tmp(destination)
    if final_path.exists() or final_path.is_symlink():
        raise SurveyError("refusing_to_overwrite_survey_database")
    final_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # /tmp itself is a root-owned sticky directory and must never be chmod'ed.
    # A result written directly below it is still private because the lock,
    # temporary database and final database are all created mode 0600.  Any
    # dedicated result subdirectory remains tightened to 0700.
    if final_path.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        os.chmod(final_path.parent, 0o700)
    lock_path = final_path.with_name(f".{final_path.name}.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SurveyError("survey_destination_is_locked") from exc
    os.close(lock_fd)
    temporary_path: Path | None = None
    published_inode: tuple[int, int] | None = None
    try:
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{final_path.name}.", suffix=".tmp", dir=str(final_path.parent)
        )
        os.close(temp_fd)
        temporary_path = Path(temp_name)
        disk = sqlite3.connect(temporary_path)
        try:
            connection.backup(disk)
            disk.commit()
        finally:
            disk.close()
        os.chmod(temporary_path, 0o600)
        with temporary_path.open("r+b") as source:
            os.fsync(source.fileno())
        os.link(temporary_path, final_path)
        stat = final_path.stat()
        published_inode = (stat.st_dev, stat.st_ino)
        temporary_path.unlink()
        temporary_path = None
        os.chmod(final_path, 0o600)
        with closing(sqlite3.connect(
            f"file:{final_path}?mode=ro&immutable=1", uri=True
        )) as verified:
            integrity = verified.execute("PRAGMA integrity_check").fetchone()[0]
            passes = verified.execute(
                "SELECT COUNT(DISTINCT pass_no) FROM survey_pages"
            ).fetchone()[0]
            tabs = verified.execute(
                "SELECT COUNT(DISTINCT tab_name) FROM survey_pages WHERE pass_no=1"
            ).fetchone()[0]
            manifests = verified.execute("SELECT COUNT(*) FROM survey_run_manifest").fetchone()[0]
            canonical = verified.execute(
                "SELECT COUNT(*) FROM survey_canonical_bookings"
            ).fetchone()[0]
            claimed = verified.execute(
                "SELECT canonical_booking_count FROM survey_run_manifest"
            ).fetchone()[0]
        if (
            integrity != "ok" or passes < 2 or tabs != 3 or manifests != 1
            or canonical != claimed
        ):
            raise SurveyError("survey_immutable_verification_failed")
    except Exception:
        if published_inode is not None and final_path.exists():
            current = final_path.stat()
            if (current.st_dev, current.st_ino) == published_inode:
                final_path.unlink()
        raise
    finally:
        lock_path.unlink(missing_ok=True)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def survey_all_tabs(
    *,
    app: str,
    window_id: int,
    db_path: Path,
    run_id: str,
    hmac_key_file: Path,
) -> dict[str, Any]:
    previous_umask = os.umask(0o077)
    pseudonym_key, key_id = _load_or_create_hmac_key(hmac_key_file)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _schema(connection)
    try:
        retryable_drift_codes = {
            "booking_semantic_conflict_across_observations",
            "browser_refresh_requires_fresh_sweep",
            "census_consecutive_sweeps_did_not_converge",
            "census_expected_tab_total_changed",
        }
        for epoch_attempt in range(1, 4):
            pass_results: list[
                tuple[list[dict[str, Any]], list[dict[str, Any]]]
            ] = []
            population_manifests: list[str] = []
            expected_totals: dict[str, int] | None = None
            canonical: list[dict[str, Any]] = []
            try:
                for pass_no in range(1, 5):
                    all_pages: list[dict[str, Any]] = []
                    all_cards: list[dict[str, Any]] = []
                    for tab_name in TAB_NAMES:
                        pages, cards = _scan_tab(
                            app, window_id, tab_name, pass_no, pseudonym_key
                        )
                        all_pages.extend(pages)
                        all_cards.extend(cards)
                    _validate_occurrences(all_cards)
                    current_totals = {
                        tab_name: sum(
                            int(page["card_count"])
                            for page in all_pages
                            if page["tab_name"] == tab_name
                        )
                        for tab_name in TAB_NAMES
                    }
                    if expected_totals is None:
                        expected_totals = current_totals
                    elif current_totals != expected_totals:
                        raise SurveyError("census_expected_tab_total_changed")
                    pass_results.append((all_pages, all_cards))
                    current_canonical = _canonical_bookings(all_cards)
                    population_manifests.append(
                        _convergence_manifest(
                            current_totals, current_canonical
                        )
                    )
                    unique_by_tab = Counter(
                        str(card["tab_name"]) for card in current_canonical
                    )
                    if any(
                        unique_by_tab[tab_name] > expected_totals[tab_name]
                        for tab_name in TAB_NAMES
                    ):
                        raise SurveyError("census_unique_exceeds_page_slots")
                    stable_canonical = _stable_pair_canonical(
                        pass_results, population_manifests
                    )
                    _progress(
                        "census_sweep_progress",
                        pass_no=pass_no,
                        expected_totals=expected_totals,
                        unique_totals={
                            tab_name: unique_by_tab[tab_name]
                            for tab_name in TAB_NAMES
                        },
                        stable_population_with_previous=(
                            stable_canonical is not None
                        ),
                    )
                    if stable_canonical is not None:
                        canonical = stable_canonical
                        break
                else:
                    raise SurveyError(
                        "census_consecutive_sweeps_did_not_converge"
                    )
            except SurveyError as exc:
                reason = str(exc)
                if reason not in retryable_drift_codes or epoch_attempt == 3:
                    raise
                _progress(
                    "fresh_epoch_retry",
                    failed_epoch_attempt=epoch_attempt,
                    reason=reason,
                )
                time.sleep(2.0)
                continue
            break

        for pages, cards in pass_results:
            _insert_pass(connection, pages, cards)
        _insert_canonical_bookings(connection, canonical)
        all_pages = [page for pages, _ in pass_results for page in pages]
        all_cards = [card for _, cards in pass_results for card in cards]
        counts = Counter(card["scope_status"] for card in canonical)
        duplicate_occurrence_count = sum(
            len(cards)
            - len({card["booking_pseudonym_hmac"] for card in cards})
            for _, cards in pass_results
        )
        convergence_manifest_sha256 = _convergence_manifest(
            expected_totals, canonical
        )
        connection.execute(
            """
            INSERT INTO survey_run_manifest VALUES(
                ?, ?, ?, ?, 3, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id,
                BOOKINGS_ORIGIN,
                BOOKINGS_ROUTE_KIND,
                key_id,
                len(pass_results),
                len(all_pages),
                len(all_cards),
                len(canonical),
                counts["target_2026_overlap"],
                counts["year_unknown"],
                counts["outside_2026"],
                duplicate_occurrence_count,
                _canonical_json(expected_totals),
                convergence_manifest_sha256,
                _utc_now(),
            ),
        )
        connection.commit()
        _publish_memory_database(connection, db_path)
        page_summaries = [
            {
                key: page[key]
                for key in (
                    "tab_name",
                    "page_no",
                    "card_count",
                    "target_2026_count",
                    "year_unknown_count",
                    "terminal_reason",
                )
            }
            for page in all_pages
        ]
        return {
            "run_id": run_id,
            "db": str(_require_tmp(db_path)),
            "db_sha256": _file_sha256(_require_tmp(db_path)),
            "pseudonym_key_id": key_id,
            "verification_pass_count": len(pass_results),
            "captured_page_count": len(all_pages),
            "captured_card_count": len(all_cards),
            "canonical_booking_count": len(canonical),
            "target_2026_count": counts["target_2026_overlap"],
            "year_unknown_count": counts["year_unknown"],
            "outside_2026_count": counts["outside_2026"],
            "duplicate_occurrence_count": duplicate_occurrence_count,
            "expected_tab_totals": expected_totals,
            "pass_manifest_sha256": convergence_manifest_sha256,
            "page_summaries": page_summaries,
        }
    finally:
        connection.close()
        os.umask(previous_umask)


def main() -> int:
    try:
        from tools.agoda_browser_policy import legacy_browser_block
    except ImportError:  # pragma: no cover - direct script execution
        from agoda_browser_policy import legacy_browser_block

    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="msedge")
    parser.add_argument("--window-id", type=int, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    args = parser.parse_args()
    return legacy_browser_block("agoda_portal_full_survey")

    result = survey_all_tabs(
        app=args.app,
        window_id=args.window_id,
        db_path=args.db,
        run_id=args.run_id,
        hmac_key_file=args.hmac_key_file,
    )
    print(_canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
