"""REVIEW-UI-001 Muse UI tests, Muse writer scope.

Synthetic inputs only. No network, no original data. Tests check the static
HTML wire contract, safe dynamic rendering with textContent, decision
options for blank hold, REJECT, and exact candidate key approval, plus
Korean labels and readable controls.
"""

import json
import shutil
import subprocess

import pytest

from webapp.review_ui import render_review_ui


def _html():
    return render_review_ui()


def _script(html_text):
    start_tag = "<script>"
    end_tag = "</script>"
    assert start_tag in html_text
    parts = html_text.split(start_tag)
    assert len(parts) == 2
    tail = parts[1].split(end_tag)
    assert len(tail) == 2
    return tail[0]


def test_returns_html_doctype():
    html_text = _html()
    assert isinstance(html_text, str)
    assert html_text.startswith("<!DOCTYPE html>")
    assert ("lang=" + chr(34) + "ko" + chr(34)) in html_text
    assert html_text.rstrip().endswith("</html>")


def test_pure_static_deterministic():
    assert render_review_ui() == render_review_ui()


def test_korean_labels_present():
    html_text = _html()
    labels = ["로컬 검토 화면", "보류", "거부", "승인", "내보내기",
        "원본 정보", "후보 목록", "결정 선택", "주의", "다시 불러오기"]
    for label in labels:
        assert label in html_text


def test_no_embedded_external_resources():
    html_text = _html()
    lowered = html_text.lower()
    assert "<script src" not in lowered
    assert "<link" not in lowered
    assert "@import" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered


def test_api_wire_contract():
    html_text = _html()
    tokens = ["/api/model", "/api/export", "X-Review-CSRF",
        "application/json", "decisions", "decision_csv", "plan_json",
        "same-origin", "csrf_nonce", "Blob", "createObjectURL",
        "JSON.stringify"]
    for token in tokens:
        assert token in html_text


def test_safe_dynamic_rendering():
    html_text = _html()
    assert "textContent" in html_text
    banned = ["innerHTML", "outerHTML", "insertAdjacentHTML",
        "document.write", "localStorage", "sessionStorage",
        "err.message", "String(err)"]
    for token in banned:
        assert token not in html_text


def test_no_fetch_outside_localhost():
    html_text = _html()
    assert ("fetch(" + chr(34) + "http") not in html_text
    assert "http://" not in html_text
    assert html_text.count("fetch(") >= 2


def test_decision_options_blank_reject_approve():
    html_text = _html()
    tokens = ["REJECT", "APPROVE:", "보류", "거부", "승인",
        "radio", "checked", "disabled", "insufficient",
        "추가 확인 필요"]
    for token in tokens:
        assert token in html_text


def test_renders_all_rows_with_original_and_candidate_panels():
    html_text = _html()
    tokens = ["renderAll", "renderSourcePanel", "renderCandidatePanel",
        "renderDecisionGroup", "row-card", "data-ref", "rows.length",
        "원본 위치", "증빙 상태", "후보 키", "승인번호"]
    for token in tokens:
        assert token in html_text


def test_insufficient_or_empty_disables_approve_with_confirmation():
    html_text = _html()
    tokens = ["insufficient", "후보가 없습니다", "승인이 비활성화됩니다",
        "추가 확인 필요", "백엔드에서 다시 확인합니다"]
    for token in tokens:
        assert token in html_text


def test_export_posts_all_rows_and_downloads_both_files():
    html_text = _html()
    tokens = ["collectDecisions", "decisions.csv", "plan.json",
        "text/csv", "내보내는 중입니다", "내보내기가 끝났습니다"]
    for token in tokens:
        assert token in html_text


def test_errors_are_korean_without_raw_details():
    html_text = _html()
    tokens = ["모델을 불러오지 못했습니다", "내보내기에 실패했습니다",
        "다시 시도하세요"]
    for token in tokens:
        assert token in html_text
    assert ".stack" not in html_text


def test_buttons_large_and_readable():
    html_text = _html()
    assert "min-height" in html_text
    assert "52px" in html_text
    assert "내보내기 및 다운로드" in html_text


def test_csv_formula_warning_with_json_alternative():
    html_text = _html()
    tokens = ["스프레드시트", "수식", "JSON"]
    for token in tokens:
        assert token in html_text


def test_js_syntax_with_node_when_available(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = _script(_html())
    target = tmp_path / "review_ui_script.js"
    target.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [node, "--check", str(target)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0


_NODE_EXPORT_HARNESS = r"""
const fs = require("fs");
async function main() {
  const scriptPath = process.argv[2];
  const payloadPath = process.argv[3];
  const csvPath = process.argv[4];
  const outPath = process.argv[5];
  const script = fs.readFileSync(scriptPath, "utf8");
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
  const planValue = payload.value;
  const csvStr = fs.readFileSync(csvPath, "utf8");
  const captured = [];
  const NativeBlob = globalThis.Blob;
  class CapBlob extends NativeBlob {
    constructor(parts, opts) {
      super(parts, opts);
      captured.push({ blob: this, mime: (opts && opts.type) || "" });
    }
  }
  globalThis.Blob = CapBlob;
  globalThis.URL = { createObjectURL: function() { return "blob:mock"; }, revokeObjectURL: function() {} };
  const handlers = {};
  const elements = {};
  function makeElement(tag) {
    return {
      tagName: tag, textContent: "", className: "", disabled: false,
      checked: false, value: "", href: "", download: "", type: "", name: "",
      setAttribute: function() {}, appendChild: function() {},
      remove: function() {}, click: function() {},
      addEventListener: function() {}
    };
  }
  function getEl(id) {
    if (!elements[id]) {
      const el = makeElement("div");
      el._id = id;
      el.addEventListener = function(ev, fn) { handlers[id + "::" + ev] = fn; };
      elements[id] = el;
    }
    return elements[id];
  }
  globalThis.document = {
    getElementById: getEl,
    createElement: makeElement,
    querySelector: function() { return { value: "" }; },
    body: { appendChild: function() {} }
  };
  const modelRows = [
    { ref: "R1", source: { evidence_status: "available" }, candidates: [{ key: "K1" }] },
    { ref: "R2", source: { evidence_status: "available" }, candidates: [{ key: "K2" }] }
  ];
  globalThis.fetch = async function(url, opts) {
    if (url === "/api/model") {
      return { ok: true, json: async function() { return { csrf_nonce: "test-nonce", rows: modelRows }; } };
    }
    if (url === "/api/export") {
      return { ok: true, json: async function() { return { decision_csv: csvStr, plan_json: planValue }; } };
    }
    return { ok: false, json: async function() { return {}; } };
  };
  eval(script);
  await new Promise(function(r) { setTimeout(r, 100); });
  const fn = handlers["exportBtn::click"];
  if (!fn) { fs.writeFileSync(outPath, JSON.stringify({ error: "no-export-handler" })); process.exit(2); }
  await fn();
  await new Promise(function(r) { setTimeout(r, 100); });
  const result = { blobs: [] };
  for (const c of captured) {
    let text = "";
    try { text = await c.blob.text(); } catch (e) { text = "TEXT-ERROR:" + String((e && e.message) || e); }
    result.blobs.push({ mime: c.mime, text: text });
  }
  fs.writeFileSync(outPath, JSON.stringify(result), "utf8");
}
main().catch(function(e) { console.error("HARNESS-FAIL " + ((e && e.stack) || e)); process.exit(1); });
"""


def _run_export_blobs_via_node(tmp_path, plan_value, csv_text):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = _script(_html())
    script_path = tmp_path / "ui.js"
    script_path.write_bytes(script.encode("utf-8"))
    payload_path = tmp_path / "payload.json"
    payload_path.write_bytes(json.dumps({"value": plan_value}).encode("utf-8"))
    csv_path = tmp_path / "input.csv"
    csv_path.write_bytes(csv_text.encode("utf-8"))
    harness_path = tmp_path / "harness.js"
    harness_path.write_bytes(_NODE_EXPORT_HARNESS.encode("utf-8"))
    out_path = tmp_path / "out.json"
    proc = subprocess.run(
        [node, str(harness_path), str(script_path), str(payload_path),
         str(csv_path), str(out_path)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(out_path.read_bytes().decode("utf-8"))
    assert "error" not in out
    assert len(out["blobs"]) == 2
    by_mime = {b["mime"]: b["text"] for b in out["blobs"]}
    return by_mime


def test_plan_json_object_blob_roundtrip_via_node(tmp_path):
    plan_obj = {
        "counts": {"total": 2},
        "plan_digest": "abc123",
        "reviewed_plan": [],
        "snapshot_sha256": "deadbeef",
    }
    csv_text = "ref,reviewer_decision\nR1,\nR2,REJECT\n"
    by_mime = _run_export_blobs_via_node(tmp_path, plan_obj, csv_text)
    plan_text = by_mime.get("application/json", "")
    assert plan_text != "[object Object]"
    parsed = json.loads(plan_text)
    assert parsed == plan_obj
    assert by_mime.get("text/csv", None) == csv_text


def test_plan_json_string_and_csv_preserved_via_node(tmp_path):
    plan_obj = {"counts": {"total": 1}, "plan_digest": "zz", "reviewed_plan": [], "snapshot_sha256": "11"}
    plan_str = json.dumps(plan_obj)
    csv_text = "ref,reviewer_decision\nR1,REJECT\nR2,\n"
    by_mime = _run_export_blobs_via_node(tmp_path, plan_str, csv_text)
    assert by_mime.get("application/json", None) == plan_str
    assert json.loads(by_mime["application/json"]) == plan_obj
    assert by_mime.get("text/csv", None) == csv_text
