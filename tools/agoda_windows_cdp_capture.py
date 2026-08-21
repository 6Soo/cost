"""Windows-native CDP capture coordinator for Agoda.

This is intentionally separate from the historical ORCA/UIA implementation.
It attaches only to a loopback CDP endpoint owned by a separately launched
headless Edge process.  It never connects to the user's visible Edge process,
never reads cookies or storage, and never writes a ledger or OTA database.

The first usable stage is a private list census.  The census can then be
partitioned into the user-requested logical workers:

    U01                 all Upcoming cards
    C01 ... C09         HMAC partitions of Completed cards

Cancelled is not collected or assigned.  Detail parsing is deliberately kept
behind the same authenticated-session and list-census gates; a direct run on a
logged-out or error page fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
BRIDGE = Path(__file__).resolve().with_name("agoda_cdp_bridge.mjs")
NODE = os.environ.get("AGODA_NODE", "node")
ALLOWED_TABS = ("Upcoming", "Completed")
SHARDS = ("U01",) + tuple(f"C{index:02d}" for index in range(1, 10))
BRIDGE_ERROR_CODES = frozenset(
    {
        "card_missing",
        "card_click_failed",
        "tab_control_missing",
        "tab_click_failed",
        "page_control_missing",
        "page_click_failed",
        "next_page_control_missing",
        "next_page_control_disabled",
        "next_page_click_failed",
        "cdp_dom_ready_timeout",
        "cdp_dom_summary_missing",
        "cdp_detail_summary_missing",
        "cdp_target_list_failed",
        "cdp_page_target_missing",
        "cdp_socket_error",
    }
)


class CaptureError(RuntimeError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_hmac_key(path: Path) -> bytes:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise CaptureError("hmac_key_missing")
    key = resolved.read_bytes()
    if len(key) < 32:
        raise CaptureError("hmac_key_too_short")
    return key


def pseudonym(key: bytes, booking_id: str) -> str:
    return hmac.new(key, booking_id.encode("utf-8"), hashlib.sha256).hexdigest()


def shard_for(tab_name: str, booking_id: str, key: bytes) -> str | None:
    if tab_name == "Upcoming":
        return "U01"
    if tab_name != "Completed":
        return None
    bucket = int.from_bytes(
        hmac.new(key, booking_id.encode("utf-8"), hashlib.sha256).digest()[:8],
        "big",
    ) % 9
    return f"C{bucket + 1:02d}"


def load_endpoint_manifest(path: Path, port: int) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise CaptureError("headless_endpoint_manifest_missing")
    try:
        manifest = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError("headless_endpoint_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise CaptureError("headless_endpoint_manifest_invalid")
    if int(manifest.get("schema", 0)) != 1:
        raise CaptureError("headless_endpoint_manifest_schema_invalid")
    if int(manifest.get("port", -1)) != port:
        raise CaptureError("headless_endpoint_manifest_port_mismatch")
    if not manifest.get("command_line_attested") or not manifest.get("endpoint_attested", True):
        raise CaptureError("headless_endpoint_not_attested")
    pid = manifest.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise CaptureError("headless_endpoint_pid_invalid")
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise CaptureError("headless_endpoint_process_missing")
        kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
        except OSError as exc:
            raise CaptureError("headless_endpoint_process_missing") from exc
    target_id = str(manifest.get("target_id") or "")
    if not target_id:
        raise CaptureError("headless_endpoint_target_missing")
    browser = str(manifest.get("browser") or "")
    if "Edg/" not in browser and "Edge/" not in browser:
        raise CaptureError("headless_endpoint_browser_not_attested")
    return manifest


def run_bridge(
    *,
    port: int,
    operation: str,
    url: str | None = None,
    tab: str | None = None,
    booking_id: str | None = None,
    card_index: int | None = None,
    page_no: int | None = None,
    endpoint_manifest: Path | None = None,
    summary_only: bool = False,
    wait_ms: int = 2500,
) -> dict[str, Any]:
    command = [
        NODE,
        str(BRIDGE),
        "--port",
        str(port),
        "--operation",
        operation,
        "--wait-ms",
        str(wait_ms),
    ]
    manifest = None
    if endpoint_manifest is not None:
        manifest = load_endpoint_manifest(endpoint_manifest, port)
        command.extend(["--target-id", str(manifest["target_id"])])
    if url:
        command.extend(["--url", url])
    if tab:
        command.extend(["--tab", tab])
    if booking_id:
        command.extend(["--booking-id", booking_id])
    if card_index is not None:
        command.extend(["--card-index", str(card_index)])
    if page_no is not None:
        command.extend(["--page-no", str(page_no)])
    if summary_only:
        command.append("--summary-only")
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        safe_code = next(
            (
                code
                for code in BRIDGE_ERROR_CODES
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(code)}(?![A-Za-z0-9_])", completed.stderr)
            ),
            None,
        )
        # Do not surface stderr: browser diagnostics can contain URLs or
        # profile details.  Preserve only a stable, caller-safe error class.
        raise CaptureError(safe_code or "cdp_bridge_failed")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CaptureError("cdp_bridge_response_invalid") from exc
    if not isinstance(result, dict):
        raise CaptureError("cdp_bridge_response_invalid")
    return result


def _synthetic_tree(tab_name: str, page_no: int, cards: Iterable[dict[str, Any]]) -> str:
    """Build only the small tree dialect consumed by the existing card parser."""

    lines = [f"0 기본 {tab_name}"]
    for position, card in enumerate(cards, start=1):
        booking_id = str(card.get("booking_id") or "")
        if not booking_id.isdigit() or not 6 <= len(booking_id) <= 20:
            raise CaptureError("booking_id_missing_or_ambiguous")
        lines.append(f"mmb-booking-card--{booking_id}")
        lines.append(f"  0 단추 Manage booking {booking_id}")
        for value_index, value in enumerate(card.get("values") or [], start=1):
            lines.append(f"  {value_index} 텍스트 {value}")
    lines.append(f"0 기본 {page_no}")
    return "\n".join(lines)


def normalize_cards(tab_name: str, page_no: int, raw_cards: list[dict[str, Any]], key: bytes) -> list[dict[str, Any]]:
    if tab_name not in ALLOWED_TABS:
        raise CaptureError("tab_not_allowed")
    if not raw_cards:
        return []
    try:
        from tools.agoda_portal_full_survey import _survey_cards
    except ModuleNotFoundError:
        from agoda_portal_full_survey import _survey_cards
    tree = _synthetic_tree(tab_name, page_no, raw_cards)
    try:
        parsed = _survey_cards(tree, tab_name, page_no, key)
    except Exception as exc:  # parser errors must be reported as a stable gate
        raise CaptureError("list_card_parse_failed") from exc
    if len(parsed) != len(raw_cards):
        raise CaptureError("list_card_count_mismatch")
    expected_statuses = {
        "Upcoming": {"confirmed", "pending"},
        "Completed": {"completed", "refunded", "failed"},
    }[tab_name]
    seen_ids: set[str] = set()
    for source, raw in zip(parsed, raw_cards):
        raw_id = str(raw.get("booking_id") or "")
        if str(source["booking_id"]) != raw_id:
            raise CaptureError("list_booking_id_binding_mismatch")
        if raw_id in seen_ids:
            raise CaptureError("duplicate_booking_within_page")
        seen_ids.add(raw_id)
        raw_status = str(raw.get("status") or "").strip().casefold()
        if raw_status not in expected_statuses:
            raise CaptureError("list_tab_status_attestation_failed")
        if str(source.get("tab_name")) != tab_name:
            raise CaptureError("list_tab_binding_mismatch")
    return parsed


def _is_agoda_bookings_url(value: object) -> bool:
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    return (host == "agoda.com" or host.endswith(".agoda.com")) and "/account/bookings" in parsed.path.casefold()


def auth_check(
    port: int,
    home_url: str,
    bookings_url: str,
    endpoint_manifest: Path | None = None,
) -> dict[str, Any]:
    if endpoint_manifest is None:
        raise CaptureError("headless_endpoint_manifest_required")
    home = run_bridge(
        port=port,
        operation="navigate-inspect",
        url=home_url,
        endpoint_manifest=endpoint_manifest,
        summary_only=True,
    )
    bookings = run_bridge(
        port=port,
        operation="navigate-inspect",
        url=bookings_url,
        endpoint_manifest=endpoint_manifest,
        summary_only=True,
    )
    # The public Agoda homepage can contain a sign-in CTA even for a valid
    # session.  The bookings surface is the authority for this gate; do not
    # turn a homepage CTA or a direct-route 502 into a false auth diagnosis.
    if bookings.get("error_marker"):
        status = "PAGE_ERROR"
    elif bookings.get("login_required") or not bookings.get("authenticated_page_marker"):
        status = "AUTH_NOT_ATTESTED"
    else:
        status = "AUTHENTICATED"
    return {
        "status": status,
        "home": home,
        "bookings": bookings,
        "raw_browser_data": False,
    }


def census(
    *,
    port: int,
    tab_name: str,
    key: bytes,
    list_url: str,
    page_no: int,
    endpoint_manifest: Path | None = None,
) -> dict[str, Any]:
    if tab_name not in ALLOWED_TABS:
        raise CaptureError("cancelled_tab_excluded")
    if endpoint_manifest is None:
        raise CaptureError("headless_endpoint_manifest_required")
    result = run_bridge(
        port=port,
        operation="navigate-inspect",
        url=list_url,
        endpoint_manifest=endpoint_manifest,
        summary_only=False,
    )
    if result.get("login_required"):
        raise CaptureError("auth_required")
    if result.get("error_marker"):
        raise CaptureError("booking_page_error")
    if not result.get("authenticated_page_marker"):
        raise CaptureError("authenticated_page_marker_missing")
    if not _is_agoda_bookings_url(result.get("url")):
        raise CaptureError("bookings_route_not_attested")

    selected = run_bridge(
        port=port,
        operation="select-tab",
        tab=tab_name,
        endpoint_manifest=endpoint_manifest,
        summary_only=False,
    )
    if selected.get("login_required") or selected.get("error_marker"):
        raise CaptureError("tab_selection_page_error")
    if not selected.get("authenticated_page_marker"):
        raise CaptureError("authenticated_page_marker_missing_after_selection")
    if not _is_agoda_bookings_url(selected.get("url")):
        raise CaptureError("selected_bookings_route_not_attested")
    if selected.get("selected_tab") != tab_name:
        raise CaptureError("selected_tab_not_attested")
    if not selected.get("page_attested") or not isinstance(
        selected.get("selected_page"), int
    ):
        raise CaptureError("selected_page_not_attested")

    if page_no == 1 and selected.get("selected_page") != 1:
        selected = run_bridge(
            port=port,
            operation="select-page",
            page_no=1,
            endpoint_manifest=endpoint_manifest,
            summary_only=False,
        )
        if selected.get("selected_tab") != tab_name:
            raise CaptureError("selected_tab_not_attested_after_page")
        if not selected.get("authenticated_page_marker"):
            raise CaptureError("authenticated_page_marker_missing_after_page")
        if not selected.get("page_attested") or selected.get("selected_page") != 1:
            raise CaptureError("selected_page_not_attested_after_page")
    elif page_no > 1:
        selected = run_bridge(
            port=port,
            operation="select-page",
            page_no=page_no,
            endpoint_manifest=endpoint_manifest,
            summary_only=False,
        )
        if selected.get("selected_tab") != tab_name:
            raise CaptureError("selected_tab_not_attested_after_page")
        if not selected.get("authenticated_page_marker"):
            raise CaptureError("authenticated_page_marker_missing_after_page")
        if not selected.get("page_attested") or selected.get("selected_page") != page_no:
            raise CaptureError("selected_page_not_attested_after_page")

    if not selected.get("identity_attested"):
        raise CaptureError("list_identity_not_attested")
    raw_cards = selected.get("cards")
    if not isinstance(raw_cards, list):
        raise CaptureError("list_cards_missing")
    cards = normalize_cards(tab_name, page_no, raw_cards, key)
    assigned = []
    for card in cards:
        booking_id = str(card["booking_id"])
        assigned.append(
            {
                **card,
                "browser_card_index": int(
                    raw_cards[len(assigned)].get("card_index", card["card_position"] - 1)
                ),
                "shard_label": shard_for(tab_name, booking_id, key),
            }
        )
    if any(item["shard_label"] is None for item in assigned):
        raise CaptureError("cancelled_assignment_forbidden")
    pseudonyms = [item["booking_pseudonym_hmac"] for item in assigned]
    if len(pseudonyms) != len(set(pseudonyms)):
        raise CaptureError("duplicate_booking_within_page")
    return {
        "tab_name": tab_name,
        "page_no": page_no,
        "source_url": result.get("url"),
        "page_values": selected.get("page_values") or [],
        "page_attested": bool(selected.get("page_attested")),
        "has_next_page": bool(selected.get("has_next_page")),
        "next_page_control_present": bool(
            selected.get("next_page_control_present")
        ),
        "card_count": len(assigned),
        "shard_counts": {
            label: sum(item["shard_label"] == label for item in assigned)
            for label in SHARDS
        },
        "cards": assigned,
    }


def census_from_selected(
    *,
    tab_name: str,
    page_no: int,
    key: bytes,
    selected: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a page returned by a tab/page action without navigation."""

    if selected.get("login_required") or selected.get("error_marker"):
        raise CaptureError("selected_page_error")
    if not selected.get("authenticated_page_marker"):
        raise CaptureError("authenticated_page_marker_missing_after_selection")
    if not _is_agoda_bookings_url(selected.get("url")):
        raise CaptureError("selected_bookings_route_not_attested")
    if selected.get("selected_tab") != tab_name:
        raise CaptureError("selected_tab_not_attested")
    if not selected.get("page_attested") or selected.get("selected_page") != page_no:
        raise CaptureError("selected_page_not_attested")
    if not selected.get("identity_attested"):
        raise CaptureError("list_identity_not_attested")
    raw_cards = selected.get("cards")
    if not isinstance(raw_cards, list):
        raise CaptureError("list_cards_missing")
    cards = normalize_cards(tab_name, page_no, raw_cards, key)
    assigned: list[dict[str, Any]] = []
    for position, (card, raw) in enumerate(zip(cards, raw_cards), start=1):
        booking_id = str(card["booking_id"])
        assigned.append(
            {
                **card,
                "browser_card_index": int(raw.get("card_index", position - 1)),
                "shard_label": shard_for(tab_name, booking_id, key),
            }
        )
    if any(item["shard_label"] is None for item in assigned):
        raise CaptureError("cancelled_assignment_forbidden")
    pseudonyms = [item["booking_pseudonym_hmac"] for item in assigned]
    if len(pseudonyms) != len(set(pseudonyms)):
        raise CaptureError("duplicate_booking_within_page")
    return {
        "tab_name": tab_name,
        "page_no": page_no,
        "source_url": selected.get("url"),
        "page_values": selected.get("page_values") or [],
        "page_attested": bool(selected.get("page_attested")),
        "has_next_page": bool(selected.get("has_next_page")),
        "next_page_control_present": bool(
            selected.get("next_page_control_present")
        ),
        "card_count": len(assigned),
        "shard_counts": {
            label: sum(item["shard_label"] == label for item in assigned)
            for label in SHARDS
        },
        "cards": assigned,
    }


def _harden_private_windows_acl(path: Path) -> None:
    if os.name != "nt":
        return
    identity = subprocess.run(
        ["whoami"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    account = identity.stdout.strip()
    if identity.returncode != 0 or not account or "\n" in account:
        raise CaptureError("private_output_identity_unavailable")
    hardened = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if hardened.returncode != 0:
        raise CaptureError("private_output_acl_hardening_failed")


def write_private_json(path: Path, value: Any) -> None:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, resolved)
    try:
        os.chmod(resolved, 0o600)
        _harden_private_windows_acl(resolved)
    except Exception:
        resolved.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auth-check", "census"), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--endpoint-manifest", type=Path, required=True)
    parser.add_argument("--hmac-key-file", type=Path)
    parser.add_argument("--tab", choices=ALLOWED_TABS)
    parser.add_argument("--list-url", default="https://www.agoda.com/ko-kr/account/bookings.html")
    parser.add_argument("--home-url", default="https://www.agoda.com/ko-kr/")
    parser.add_argument("--bookings-url", default="https://www.agoda.com/ko-kr/account/bookings.html")
    parser.add_argument("--page-no", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "auth-check":
            result = auth_check(
                args.port,
                args.home_url,
                args.bookings_url,
                endpoint_manifest=args.endpoint_manifest,
            )
        else:
            if args.tab is None:
                raise CaptureError("tab_required")
            if args.hmac_key_file is None:
                raise CaptureError("hmac_key_required")
            result = census(
                port=args.port,
                tab_name=args.tab,
                key=load_hmac_key(args.hmac_key_file),
                list_url=args.list_url,
                page_no=args.page_no,
                endpoint_manifest=args.endpoint_manifest,
            )
            if args.output is None:
                raise CaptureError("private_output_required")
            write_private_json(args.output, result)
            result = {
                "status": "CENSUS_STAGED",
                "tab_name": result["tab_name"],
                "page_no": result["page_no"],
                "card_count": result["card_count"],
                "shard_counts": result["shard_counts"],
                "output": str(args.output.resolve()),
                "raw_browser_data": False,
            }
        print(canonical_json(result))
        return 0
    except CaptureError as exc:
        print(canonical_json({"status": "BLOCKED", "failure_code": str(exc)}))
        return 2
    except Exception:
        print(canonical_json({"status": "BLOCKED", "failure_code": "capture_internal_error"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
