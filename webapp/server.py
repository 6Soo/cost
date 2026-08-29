from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .comparator import diff_json
from .contracts import validate_axes
from .pages import (
    detail_page,
    gates_page,
    history_page,
    kpi_page,
    new_csrf_token,
    preview_page,
    propose_form_page,
    queue_page,
)
from .snapshot_descriptor import verify_snapshot

MAX_BODY = 1_000_000


class WebApp:
    def __init__(self, snapshot_path, ledger=None, include_writes=False):
        result = verify_snapshot(snapshot_path)
        if not result["ok"]:
            raise RuntimeError(f"snapshot verify failed: {result['problems']}")
        self.descriptor = dict(result["descriptor"])
        self.descriptor["base_dir"] = str(Path(snapshot_path).parent)
        from .candidate_reader import ReadOnlyCandidate

        base_dir = Path(snapshot_path).parent
        db_path = base_dir / self.descriptor["candidate_db"]["path"]
        self.reader = ReadOnlyCandidate(db_path, descriptor=self.descriptor)
        self.ledger = ledger
        self.include_writes = bool(include_writes and ledger is not None)
        self.csrf_tokens: set[str] = set()

    def routes(self):
        gets = [
            ("GET", r"^/$", self.handle_kpi),
            ("GET", r"^/queue$", self.handle_queue),
            ("GET", r"^/detail$", self.handle_detail),
            ("GET", r"^/gates$", self.handle_gates),
            ("GET", r"^/history$", self.handle_history),
            ("GET", r"^/propose$", self.handle_propose_form),
        ]
        posts = [
            ("POST", r"^/api/propose$", self.handle_api_propose),
        ]
        return gets + (posts if self.include_writes else [])

    def handle_kpi(self, query):
        summary = {
            "payments": self.reader.payments_summary(),
            "integrity": self.reader.integrity_check(),
            "ro_unchanged": True,
        }
        return 200, "text/html; charset=utf-8", kpi_page(summary)

    def handle_queue(self, query):
        rows = self.reader.queue_rows()
        return 200, "text/html; charset=utf-8", queue_page(rows)

    def handle_detail(self, query):
        key = (query.get("key") or [""])[0]
        row = next(
            (
                r
                for r in self.reader.queue_rows(limit=100000)
                if str(r.get("event_key") or r.get("rowid")) == key
            ),
            {},
        )
        all_decisions = self.reader.active_decisions()
        keyed = [d for d in all_decisions if "event_key" in d]
        if keyed:
            decisions = [d for d in keyed if str(d.get("event_key")) == key]
        else:
            decisions = []
        return 200, "text/html; charset=utf-8", detail_page(row, decisions)

    def handle_gates(self, query):
        gates = self.reader.gates_from_report()
        banner = "TRIAGE_PASS / shadow_ready / release_ready 는 별개 지표입니다"
        body = gates_page(gates)
        body = body.replace(
            "<body>", f"<body><div class='banner'>{banner}</div>", 1
        )
        return 200, "text/html; charset=utf-8", body

    def handle_propose_form(self, query):
        token = new_csrf_token()
        self.csrf_tokens.add(token)
        return 200, "text/html; charset=utf-8", propose_form_page(token)

    def handle_history(self, query):
        events = self.ledger.all_events() if self.ledger else []
        materialized = self.ledger.materialize() if self.ledger else {
            "active": {},
            "resolved_out": [],
        }
        return 200, "text/html; charset=utf-8", history_page(events, materialized)

    def shadow_preview(self):
        baseline = {
            d["event_key"]: d
            for d in self.reader.active_decisions()
            if "event_key" in d
        }
        shadow = {}
        if self.ledger:
            materialized = self.ledger.materialize()
            for stream_id, item in materialized["active"].items():
                target = item["target"] or stream_id
                shadow[target] = {"axes": item["axes"], "event_id": item["event_id"]}
        return diff_json(baseline, {**baseline, **shadow})

    def handle_preview(self, query):
        return 200, "text/html; charset=utf-8", preview_page(self.shadow_preview())

    def check_csrf(self, headers, form) -> bool:
        token = form.get("csrftoken", [""])[0]
        origin = headers.get("Origin")
        host = headers.get("Host")
        if origin:
            try:
                origin_host = re.sub(r"^[a-zA-Z]+://", "", origin).rstrip("/")
            except Exception:
                return False
            if host and origin_host.split("/")[0] != host:
                return False
        return bool(token) and token in self.csrf_tokens

    @staticmethod
    def _field(form, name) -> str:
        return form.get(name, [""])[0].strip()

    def handle_api_propose(self, query, headers, form):
        if not self.check_csrf(headers, form):
            return 403, "text/plain; charset=utf-8", "csrf rejected"
        try:
            axes = {
                "account": self._field(form, "account"),
                "cost_type": self._field(form, "cost_type"),
                "allocation_target": self._field(form, "allocation_target")
                or None,
                "vat_tag": self._field(form, "vat_tag") or None,
            }
            validate_axes(axes)
            event, created = self.ledger.append(
                stream_id=self._field(form, "stream_id"),
                action="propose",
                target_direct_event_key=self._field(
                    form, "target_direct_event_key"
                )
                or None,
                expected_source_sha256=self._field(
                    form, "expected_source_sha256"
                )
                or None,
                axes=axes,
                rationale=self._field(form, "rationale"),
                client_request_id=None,
            )
        except Exception as exc:
            return 400, "text/plain; charset=utf-8", f"rejected: {exc}"
        body = json.dumps(
            {"created": created, "event_id": event["event_id"]},
            ensure_ascii=False,
        )
        return 200, "application/json; charset=utf-8", body


def make_handler(app: WebApp):
    compiled = [(method, re.compile(pattern), handler)
                for method, pattern, handler in app.routes()]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            for route_method, pattern, handler in compiled:
                if route_method == method and pattern.match(parsed.path):
                    break
            else:
                self._respond(404, "text/plain; charset=utf-8", "not found")
                return
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self._respond(413, "text/plain", "too large")
                    return
                raw = self.rfile.read(length).decode("utf-8")
                form = parse_qs(raw)
                status, ctype, body = handler(query, self.headers, form)
            else:
                result = handler(query)
                if len(result) == 4:
                    status, ctype, body, _ = result
                else:
                    status, ctype, body = result
            self._respond(status, ctype, body)

        def _respond(self, status, ctype, body):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def serve(app: WebApp, host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server
