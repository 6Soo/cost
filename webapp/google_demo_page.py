"""Public demo: disabled by default; real-data publication needs explicit configuration.

Only an allowlisted aggregate projection may leave the server. The real-data gate is
separate from the existing synthetic fixture gate and must remain off until reviewed.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import datetime as dt
import tempfile

from app import google_demo

ROUTES = ("/demo", "/api/demo/top3")


def prepare_real_demo(snapshot: dict, choices: dict, *, previous=None, now=None) -> dict:
    """Prepare an allowlisted preview; this does not enable or publish the demo."""
    from app import google_authority
    from . import google_ledger_page

    if not isinstance(snapshot, dict) or snapshot.get('schema') != google_authority.SCHEMA:
        return google_demo.build_demo(None, previous)
    sources = snapshot.get('sources')
    if not isinstance(sources, dict) or not all(isinstance(sources.get(role), dict) for role in ('main', 'archive')):
        return google_demo.build_demo(None, previous)
    current = now or dt.datetime.now(google_authority.KST)
    try:
        stamp = dt.datetime.fromisoformat(snapshot['synced_at'])
        snapshot_age = (current - stamp).total_seconds()
        synced_at = stamp.isoformat()
    except (KeyError, ValueError, TypeError):
        return google_demo.build_demo(None, previous)
    if not -60 <= snapshot_age <= google_ledger_page.MAX_SNAPSHOT_AGE_SECONDS:
        return google_demo.build_demo(None, previous)
    for role in ('main', 'archive'):
        source = sources[role]
        try:
            age = (current - dt.datetime.fromisoformat(source.get('last_ok_at') or '')).total_seconds()
        except (ValueError, TypeError):
            return google_demo.build_demo(None, previous)
        if source.get('status') != 'ok' or source.get('stale') or not -60 <= age <= google_ledger_page.MAX_SNAPSHOT_AGE_SECONDS:
            return google_demo.build_demo(None, previous)
    try:
        display = google_ledger_page.snapshot_for_display(snapshot, now=current)
        resolved = google_ledger_page.owner_payload(display, choices)
        eligible = []
        for trip in resolved['trips']:
            amounts = [trip.get(field) for field in ('income_total', 'expense_total', 'net')]
            if (trip.get('owner_id', 'aslan') != 'aslan' or trip.get('kind', 'trip') != 'trip'
                    or trip.get('canonical_source') not in ('main', 'archive')
                    or not isinstance(trip.get('copies'), dict) or not trip['copies']
                    or set(trip.get('review', [])) & google_ledger_page.OWNER_CHOICE_BLOCKERS
                    or any(type(value) is not int for value in amounts)
                    or amounts[0] - amounts[1] != amounts[2]):
                continue
            eligible.append(trip)
        return google_demo.build_demo({'synced_at': synced_at,
                                       'sources': {role: resolved['sources'][role] for role in ('main', 'archive')},
                                       'trips': eligible}, previous)
    except (KeyError, TypeError, ValueError):
        return google_demo.build_demo(None, previous)


def enabled() -> bool:
    return bool(os.environ.get("WEBLEDGER_DEMO_SNAPSHOT"))


def owns_route(path: str) -> bool:
    return path in ROUTES


def _last_safe_path(snapshot_path: Path, *, real: bool = False) -> Path:
    return snapshot_path.with_name("demo-real-last-safe.json" if real else "demo-last-safe.json")


def _payload() -> dict:
    snapshot_path = Path(os.environ["WEBLEDGER_DEMO_SNAPSHOT"])
    real_enabled = os.environ.get('WEBLEDGER_DEMO_REAL_PUBLICATION') == '1'
    last_safe_path = _last_safe_path(snapshot_path, real=real_enabled)
    try:
        previous = json.loads(last_safe_path.read_text(encoding="utf-8")) if last_safe_path.exists() else None
    except (OSError, ValueError):
        previous = None
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if real_enabled:
            return google_demo.build_demo(None, previous)
        raise
    if not isinstance(snapshot, dict):
        return google_demo.build_demo(None, previous)
    if snapshot.get("synthetic") is True and real_enabled:
        return google_demo.build_demo(None, previous)
    if snapshot.get("synthetic") is True:
        payload = google_demo.build_demo(snapshot, previous)
    elif real_enabled:
        from app import google_authority
        from . import google_ledger_page
        try:
            choices = google_ledger_page.load_choices(snapshot_path)
        except google_authority.SnapshotError:
            payload = google_demo.build_demo(None, previous)
        else:
            payload = prepare_real_demo(snapshot, choices, previous=previous)
    else:
        raise PermissionError("DEMO_NOT_SYNTHETIC")
    if not payload["stale"] and payload != previous:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=last_safe_path.parent,
                                             prefix='.demo-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, last_safe_path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return payload


def render_html(payload: dict) -> str:
    if payload["status"] == "preparing":
        body = "<p>데모를 준비하고 있습니다.</p>"
    else:
        rows = "".join(
            f"<tr><td>{e['rank']}위</td><td>{e['income_total']:,}원</td>"
            f"<td>{e['expense_total']:,}원</td><td>{e['net']:,}원</td></tr>"
            for e in payload["entries"])
        note = ("<p>마지막 정상 결과입니다. 기준 시각: "
                + html.escape(str(payload.get('as_of') or '미확인')) + "</p>") if payload["stale"] else ""
        body = (f"<h1>실제 수익 상위 여행 데모</h1>{note}"
                "<table><thead><tr><th>순위</th><th>수입</th><th>지출</th><th>순수익</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>데모</title></head><body>" + body + "</body></html>")


def dispatch_preview(handler, parsed, *, is_owner: bool) -> bool:
    """Owner-only, read-only preview; publication and cache settings are untouched."""
    if parsed.path != '/demo/preview':
        return False
    if not is_owner:
        handler._send_json({'code': 'FORBIDDEN'}, 403)
        return True
    from app import google_authority
    from . import google_ledger_page
    try:
        path = google_ledger_page.snapshot_path()
        snapshot = google_authority.load_snapshot(path)
        choices = google_ledger_page.load_choices(path)
        payload = prepare_real_demo(snapshot, choices)
    except (KeyError, OSError, ValueError, google_authority.SnapshotError):
        payload = google_demo.build_demo(None)
    preview = render_html(payload).replace('<body>', '<body><p>공개 전 미리보기</p>', 1)
    handler._send(preview)
    return True


def dispatch(handler, parsed, *, raw=None) -> bool:
    if not owns_route(parsed.path) or not enabled():
        return False
    if raw is not None:
        handler._send_json({"code": "METHOD_NOT_ALLOWED"}, 405)
        return True
    try:
        payload = _payload()
    except PermissionError as error:
        handler._send_json({"code": str(error)}, 503)
        return True
    except (OSError, ValueError):
        handler._send_json({"code": "DEMO_UNAVAILABLE"}, 503)
        return True
    if parsed.path == "/api/demo/top3":
        handler._send_json(payload)
    else:
        handler._send(render_html(payload))
    return True
