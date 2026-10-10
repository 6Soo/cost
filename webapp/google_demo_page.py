"""Public demo page and JSON. Off by default and served only from a synthetic snapshot.

Real Google data is never served here. The gate is a flag that only a synthetic fixture
carries: a snapshot without `"synthetic": true` is refused with 503. Output comes from
app.google_demo, so it has rank and amounts only: no trip title, no date, no sheet or row.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from app import google_demo

ROUTES = ("/demo", "/api/demo/top3")


def enabled() -> bool:
    return bool(os.environ.get("WEBLEDGER_DEMO_SNAPSHOT"))


def owns_route(path: str) -> bool:
    return path in ROUTES


def _last_safe_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name("demo-last-safe.json")


def _payload() -> dict:
    snapshot_path = Path(os.environ["WEBLEDGER_DEMO_SNAPSHOT"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("synthetic") is not True:
        raise PermissionError("DEMO_NOT_SYNTHETIC")
    last_safe_path = _last_safe_path(snapshot_path)
    previous = json.loads(last_safe_path.read_text(encoding="utf-8")) if last_safe_path.exists() else None
    payload = google_demo.build_demo(snapshot, previous)
    if not payload["stale"]:
        last_safe_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def render_html(payload: dict) -> str:
    if payload["status"] == "preparing":
        body = "<p>데모를 준비하고 있습니다.</p>"
    else:
        rows = "".join(
            f"<tr><td>{e['rank']}위</td><td>{e['income_total']:,}원</td>"
            f"<td>{e['expense_total']:,}원</td><td>{e['net']:,}원</td></tr>"
            for e in payload["entries"])
        note = "<p>마지막 정상 결과입니다.</p>" if payload["stale"] else ""
        body = (f"<h1>실제 수익 상위 여행 데모</h1>{note}"
                "<table><thead><tr><th>순위</th><th>수입</th><th>지출</th><th>순수익</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>")
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>데모</title></head><body>" + body + "</body></html>")


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
