"""Synthetic HTTP tests for tools/serve_review.py.

All inputs are synthetic fixtures written to pytest tmp paths. Tests run
a real stdlib server on 127.0.0.1 with an ephemeral port in a background
thread, drive it with raw same-origin HTTP calls, and verify exact Host,
Origin and CSRF checks, input drift conflicts and in-memory exports. No
original data, no database, no external network and no writes outside the
per-test temporary directory and the three synthetic input files it owns.
"""

from __future__ import annotations

import csv
import http.client
import io
import json
import os
import sys
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools import serve_review
from webapp.contracts import sha256_bytes, sha256_text
from webapp.review_context import MASTER_HEADERS

try:
    from openpyxl import Workbook
except Exception:
    Workbook = None


LABELS7 = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액"]
DATE_TXT = "2026-03-04"
SHEET = "비용"

REVIEW_FIELDS = (
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
    "review_schema_version",
    "review_snapshot_sha256",
)


def _need_workbook():
    if Workbook is None:
        pytest.skip("openpyxl is not available")


def _ref(date_col, data_row, amount_col):
    cols = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return SHEET + "!" + cols[date_col - 1] + str(data_row) + "|" + cols[amount_col - 1] + str(data_row) + " (row " + str(data_row) + ")"


def _snapshot_bytes():
    _need_workbook()
    book = Workbook()
    page = book.active
    page.title = SHEET
    for offset, label in enumerate(LABELS7):
        page.cell(row=4, column=2 + offset, value=label)
    first = [DATE_TXT, "회의비", "팀 회의", "2026-03", "RSV-1", "카드전표", 12345]
    for offset, value in enumerate(first):
        page.cell(row=5, column=2 + offset, value=value)
    second = [DATE_TXT, "택시비", "이동", "2026-03", "RSV-2", "카드전표", 777]
    for offset, value in enumerate(second):
        page.cell(row=5, column=10 + offset, value=value)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _master_row(key, merchant, amount, approval_no):
    row = {name: "" for name in MASTER_HEADERS}
    row.update({
        "거래키": key,
        "카드사": "신한",
        "카드4": "1234",
        "구분": "일시불",
        "승인일": "2026-03-03",
        "매입일": DATE_TXT,
        "가맹점": merchant,
        "원화금액": amount,
        "현지금액": amount,
        "통화": "KRW",
        "승인번호": approval_no,
        "취소여부": "N",
        "출처": "master",
        "적재일": "2026-03-05",
        "기록여부": "Y",
        "워크북참조": "w1",
        "비고": "memo",
    })
    return row


def _csv_text(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return buf.getvalue()


def _review_row(ref, snapshot_hex, amount_txt, keys, note):
    return [
        ref, DATE_TXT, amount_txt, str(len(keys)),
        json.dumps(keys, ensure_ascii=False), "2026-03-03/2026-03-04",
        "candidate_review_required", "", note, "review-csv-v1", snapshot_hex,
    ]


def _server_inputs(tmp_path):
    ref_one = _ref(2, 5, 8)
    ref_two = _ref(10, 5, 16)
    snapshot_bytes = _snapshot_bytes()
    snapshot_hex = sha256_bytes(snapshot_bytes)
    master_text = _csv_text(MASTER_HEADERS, [
        [_master_row("TX-1", "식당", "12345", "AP-1")[name] for name in MASTER_HEADERS],
        [_master_row("TX-2", "교통", "777", "AP-2")[name] for name in MASTER_HEADERS],
    ])
    review_text = _csv_text(REVIEW_FIELDS, [
        _review_row(ref_one, snapshot_hex, "12345", ["TX-1"], "n1"),
        _review_row(ref_two, snapshot_hex, "777", ["TX-2"], "n2"),
    ])
    snapshot_path = str(tmp_path / "snapshot.xlsx")
    review_path = str(tmp_path / "review.csv")
    master_path = str(tmp_path / "master.csv")
    with open(snapshot_path, "wb") as handle:
        handle.write(snapshot_bytes)
    with open(review_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(review_text)
    with open(master_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(master_text)
    return {
        "snapshot_path": snapshot_path,
        "review_path": review_path,
        "master_path": master_path,
        "snapshot_hex": snapshot_hex,
        "review_hex": sha256_text(review_text),
        "master_hex": sha256_text(master_text),
        "ref_one": ref_one,
        "ref_two": ref_two,
    }


@pytest.fixture()
def live_server(tmp_path):
    spec = _server_inputs(tmp_path)
    server = serve_review.create_review_server(
        spec["snapshot_path"], spec["review_path"], spec["master_path"],
        spec["snapshot_hex"], spec["review_hex"], spec["master_hex"], 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"server": server, "spec": spec, "port": server.server_address[1]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _raw(port, method, path, headers=None, body=None):
    heads = dict(headers or {})
    if body is not None and "Content-Length" not in heads:
        heads["Content-Length"] = str(len(body))
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest(method, path, skip_host=True)
    for key, value in heads.items():
        conn.putheader(key, value)
    if body is None:
        conn.endheaders()
    else:
        conn.endheaders(body)
    resp = conn.getresponse()
    data = resp.read()
    result = (resp.status, {key.lower(): value for key, value in resp.getheaders()}, data)
    conn.close()
    return result


def _host(port):
    return "127.0.0.1:" + str(port)


def _export_headers(port, nonce, extra=None):
    headers = {
        "Host": _host(port),
        "Origin": "http://" + _host(port),
        "X-Review-CSRF": nonce,
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _model(live):
    status, headers, data = _raw(live["port"], "GET", "/api/model", {"Host": _host(live["port"])})
    assert status == 200
    return json.loads(data.decode("utf-8"))


def test_root_serves_static_screen_with_safety_headers(live_server):
    status, headers, data = _raw(live_server["port"], "GET", "/", {"Host": _host(live_server["port"])})
    assert status == 200
    assert "text/html" in headers["content-type"]
    assert "로컬 검토 화면" in data.decode("utf-8")
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src" in headers["content-security-policy"]
    assert "http" not in headers["content-security-policy"]
    assert "access-control-allow-origin" not in headers


def test_model_returns_rows_and_nonce(live_server):
    payload = _model(live_server)
    assert payload["snapshotsha"] == live_server["spec"]["snapshot_hex"]
    assert payload["reviewsha"] == live_server["spec"]["review_hex"]
    assert payload["mastersha"] == live_server["spec"]["master_hex"]
    assert len(payload["rows"]) == 2
    assert type(payload["csrf_nonce"]) is str and payload["csrf_nonce"] != ""
    refs = [row["ref"] for row in payload["rows"]]
    assert refs == [live_server["spec"]["ref_one"], live_server["spec"]["ref_two"]]


def test_get_never_mutates(live_server):
    first = _raw(live_server["port"], "GET", "/api/model", {"Host": _host(live_server["port"])})
    second = _raw(live_server["port"], "GET", "/api/model", {"Host": _host(live_server["port"])})
    assert first[0] == second[0] == 200
    assert first[2] == second[2]


def test_host_mismatch_rejected_everywhere(live_server):
    port = live_server["port"]
    status, headers, data = _raw(port, "GET", "/", {"Host": "localhost:" + str(port)})
    assert status == 403
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "HOST_MISMATCH"}}
    body = json.dumps({"decisions": []}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", {
        "Host": "localhost:" + str(port),
        "Origin": "http://" + _host(port),
        "Content-Type": "application/json",
    }, body)
    assert status == 403
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "HOST_MISMATCH"}}


def test_unknown_path_and_method_are_safe_errors(live_server):
    port = live_server["port"]
    status, headers, data = _raw(port, "GET", "/api/unknown", {"Host": _host(port)})
    assert status == 404
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "UNKNOWN_PATH"}}
    status, headers, data = _raw(port, "PUT", "/api/export", {"Host": _host(port)})
    assert status == 405
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "METHOD_NOT_ALLOWED"}}


def test_export_success_returns_in_memory_results(live_server):
    port = live_server["port"]
    spec = live_server["spec"]
    nonce = _model(live_server)["csrf_nonce"]
    body = json.dumps({"decisions": [
        {"ref": spec["ref_one"], "value": "APPROVE:TX-1"},
        {"ref": spec["ref_two"], "value": "REJECT"},
    ]}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", _export_headers(port, nonce), body)
    assert status == 200
    payload = json.loads(data.decode("utf-8"))
    assert set(payload.keys()) == {"decision_csv", "plan_json", "counts", "plan_digest"}
    assert payload["counts"] == {"approved": 1, "rejected": 1, "incomplete": 0}
    assert "APPROVE:TX-1" in payload["decision_csv"]
    plan = json.loads(payload["plan_json"])
    assert set(plan.keys()) == {"counts", "plan_digest", "reviewed_plan", "snapshot_sha256"}
    assert plan["plan_digest"] == payload["plan_digest"]
    assert "snapshot.xlsx" not in payload["decision_csv"]
    assert "review.csv" not in payload["decision_csv"]
    assert "master.csv" not in payload["decision_csv"]


def test_export_rejects_origin_csrf_and_content_type(live_server):
    port = live_server["port"]
    spec = live_server["spec"]
    nonce = _model(live_server)["csrf_nonce"]
    body = json.dumps({"decisions": []}).encode("utf-8")
    headers = _export_headers(port, nonce, {"Origin": "http://localhost:" + str(port)})
    status, headers_out, data = _raw(port, "POST", "/api/export", headers, body)
    assert status == 403
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "ORIGIN_MISMATCH"}}
    headers = _export_headers(port, nonce)
    del headers["Origin"]
    status, headers_out, data = _raw(port, "POST", "/api/export", headers, body)
    assert status == 403
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "ORIGIN_MISMATCH"}}
    status, headers_out, data = _raw(port, "POST", "/api/export", _export_headers(port, "wrong-nonce"), body)
    assert status == 403
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "CSRF_MISMATCH"}}
    headers = _export_headers(port, nonce, {"Content-Type": "text/plain"})
    status, headers_out, data = _raw(port, "POST", "/api/export", headers, body)
    assert status == 415
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "CONTENT_TYPE_MISMATCH"}}


def test_export_rejects_malformed_oversize_and_unknown_decisions(live_server):
    port = live_server["port"]
    nonce = _model(live_server)["csrf_nonce"]
    headers = _export_headers(port, nonce)
    status, headers_out, data = _raw(port, "POST", "/api/export", headers, b"{oops")
    assert status == 400
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "MALFORMED_BODY"}}
    # The server rejects an oversized declared length before reading a body.
    # Sending that discarded body races the early response on Windows sockets.
    oversized_headers = dict(headers, **{"Content-Length": str(2 * 1024 * 1024 + 100)})
    status, headers_out, data = _raw(port, "POST", "/api/export", oversized_headers)
    assert status == 413
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "BODY_TOO_LARGE"}}
    body = json.dumps({"decisions": [{"ref": "없는참조", "value": "REJECT"}]}).encode("utf-8")
    status, headers_out, data = _raw(port, "POST", "/api/export", headers, body)
    assert status == 400
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "DECISION_UNKNOWN_REF"}}


def test_export_blocks_insufficient_approve(live_server):
    port = live_server["port"]
    spec = live_server["spec"]
    nonce = _model(live_server)["csrf_nonce"]
    body = json.dumps({"decisions": [{"ref": spec["ref_two"], "value": "APPROVE:TX-2"}]}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", _export_headers(port, nonce), body)
    assert status == 400
    assert json.loads(data.decode("utf-8")) == {"error": {"code": "INSUFFICIENT_EVIDENCE"}}


def test_input_drift_conflicts_without_result(live_server):
    port = live_server["port"]
    spec = live_server["spec"]
    nonce = _model(live_server)["csrf_nonce"]
    with open(spec["review_path"], "ab") as handle:
        handle.write(b"\n# drift")
    body = json.dumps({"decisions": []}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", _export_headers(port, nonce), body)
    assert status == 409
    payload = json.loads(data.decode("utf-8"))
    assert payload == {"error": {"code": "INPUT_DRIFT"}}
    assert "decision_csv" not in payload
    assert "plan_json" not in payload


def test_startup_refuses_bad_inputs(tmp_path):
    spec = _server_inputs(tmp_path)
    with pytest.raises(serve_review.ServerError) as exc:
        serve_review.create_review_server(
            spec["snapshot_path"], spec["review_path"], spec["master_path"],
            "0" * 64, spec["review_hex"], spec["master_hex"], 0)
    assert exc.value.code == "INPUT_HASH_MISMATCH"
    with pytest.raises(serve_review.ServerError) as exc:
        serve_review.create_review_server(
            spec["snapshot_path"], spec["review_path"], spec["master_path"],
            "not-hex", spec["review_hex"], spec["master_hex"], 0)
    assert exc.value.code == "INVALID_SHA256"
    with pytest.raises(serve_review.ServerError) as exc:
        serve_review.create_review_server(
            str(tmp_path / "missing.xlsx"), spec["review_path"], spec["master_path"],
            spec["snapshot_hex"], spec["review_hex"], spec["master_hex"], 0)
    assert exc.value.code == "INPUT_NOT_FOUND"
    with pytest.raises(serve_review.ServerError) as exc:
        serve_review.create_review_server(
            spec["snapshot_path"], spec["review_path"], spec["master_path"],
            spec["snapshot_hex"], spec["review_hex"], spec["master_hex"], -1)
    assert exc.value.code == "INVALID_ARGUMENT"


def test_server_writes_no_files_and_inputs_unchanged(live_server, tmp_path):
    port = live_server["port"]
    spec = live_server["spec"]
    before = set(os.listdir(tmp_path))
    with open(spec["review_path"], "rb") as handle:
        review_before = handle.read()
    nonce = _model(live_server)["csrf_nonce"]
    body = json.dumps({"decisions": []}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", _export_headers(port, nonce), body)
    assert status == 200
    with open(spec["review_path"], "rb") as handle:
        assert handle.read() == review_before
    assert set(os.listdir(tmp_path)) == before


def test_cli_rejects_bad_arguments(tmp_path, capsys):
    assert serve_review.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out == {"error": {"code": "INVALID_ARGUMENT"}}
    spec = _server_inputs(tmp_path)
    assert serve_review.main([
        "--snapshot", str(tmp_path / "missing.xlsx"),
        "--snapshot-sha256", spec["snapshot_hex"],
        "--review", spec["review_path"],
        "--review-sha256", spec["review_hex"],
        "--master", spec["master_path"],
        "--master-sha256", spec["master_hex"],
    ]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out == {"error": {"code": "INPUT_NOT_FOUND"}}


def test_startup_drift_closes_bound_socket_and_refuses(tmp_path, monkeypatch):
    spec = _server_inputs(tmp_path)
    original_build = serve_review.build_review_context
    original_server_cls = serve_review.ReviewServer
    created = {}

    def tracking_server(*args, **kwargs):
        server = original_server_cls(*args, **kwargs)
        created["server"] = server
        return server

    monkeypatch.setattr(serve_review, "ReviewServer", tracking_server)

    def drifting_build(snapshot_bytes, review_text, master_text,
                       snapshot_hex, review_hex, master_hex):
        with open(spec["review_path"], "ab") as handle:
            handle.write(b"\n# drift")
        return original_build(
            snapshot_bytes, review_text, master_text,
            snapshot_hex, review_hex, master_hex)

    monkeypatch.setattr(serve_review, "build_review_context", drifting_build)
    with pytest.raises(serve_review.ServerError) as exc:
        serve_review.create_review_server(
            spec["snapshot_path"], spec["review_path"], spec["master_path"],
            spec["snapshot_hex"], spec["review_hex"], spec["master_hex"], 0)
    assert exc.value.code == "INPUT_DRIFT"
    assert "server" in created
    server = created["server"]
    try:
        fileno = server.socket.fileno()
    except Exception:
        fileno = -1
    assert fileno == -1


def test_payloads_match_static_ui_wire_contract(live_server):
    port = live_server["port"]
    spec = live_server["spec"]
    model = _model(live_server)
    assert type(model["rows"]) is list
    assert type(model["csrf_nonce"]) is str
    nonce = model["csrf_nonce"]
    body = json.dumps({"decisions": [
        {"ref": row["ref"], "value": ""} for row in model["rows"]
    ]}).encode("utf-8")
    status, headers, data = _raw(port, "POST", "/api/export", _export_headers(port, nonce), body)
    assert status == 200
    payload = json.loads(data.decode("utf-8"))
    assert type(payload["decision_csv"]) is str
    assert type(payload["plan_json"]) is str
    assert set(json.loads(payload["plan_json"]).keys()) == {"counts", "plan_digest", "reviewed_plan", "snapshot_sha256"}
