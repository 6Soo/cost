"""REVIEW-UI-001 Muse review screen, Muse writer scope.

Pure static renderer only. No filesystem, database, or network use here.
render_review_ui returns a standalone HTML document string with inline
CSS and JS. The document embeds no source data and loads no external
scripts, fonts, or styles. At runtime the browser fetches the review model
from same-origin GET /api/model and posts decisions to same-origin
POST /api/export with the X-Review-CSRF nonce taken from the model.

Synthetic data only. This module never reads original checkouts or secrets.
"""

from __future__ import annotations

from .site_assets import SHELL_STYLE, THEME_STYLE, THEME_BOOTSTRAP
from . import site_theme


def render_review_ui() -> str:
    """Return the pure static local review screen HTML document."""
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>로컬 검토 화면</title>
<style>
:root { --ui-bg:var(--shell-bg); --ui-paper:var(--shell-paper); --ui-ink:var(--shell-ink); --ui-muted:var(--shell-muted); --ui-line:var(--shell-line); --ui-accent:var(--shell-accent); --ui-focus:var(--shell-focus); --ui-warn-bg:var(--shell-warn-bg); --ui-warn-ink:var(--shell-warn); --ui-error:var(--shell-danger); --ui-ok:var(--shell-accent); --ui-control:var(--shell-control-min,44px); }
* { box-sizing:border-box; }
body { max-width:1120px; margin:0 auto; padding:clamp(12px,3vw,24px); background:var(--ui-bg); color:var(--ui-ink); font:400 16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; overflow-wrap:anywhere; }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--ui-line); margin-bottom:16px; padding-bottom:12px; }
h1 { font-size:clamp(1.35rem,3vw,1.65rem); margin:0; }
.desc { color:var(--ui-muted); }
#status { min-height:44px; padding:10px 12px; border:1px solid var(--ui-line); border-radius:8px; margin:12px 0; background:var(--ui-paper); }
#status.error { border-color:var(--ui-error); color:var(--ui-error); }
#status.ok { border-color:var(--ui-ok); color:var(--ui-ok); }
#summary { margin:12px 0; font-weight:650; }
.row-card { min-width:0; border:1px solid var(--ui-line); border-radius:12px; padding:clamp(12px,2vw,18px); margin:16px 0; background:var(--ui-paper); }
.row-title { font-size:1.15rem; font-weight:700; margin-bottom:8px; overflow-wrap:anywhere; }
.panels { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.panel { min-width:0; border:1px solid var(--ui-line); border-radius:9px; padding:12px; background:var(--ui-bg); }
.panel h3 { margin:0 0 8px; font-size:1rem; }
.field { margin:6px 0; overflow-wrap:anywhere; }
.field .label { font-weight:650; }
.decision-group { min-width:0; margin-top:12px; padding:12px; border:1px solid var(--ui-line); border-radius:9px; }
.decision-option { display:block; min-height:var(--ui-control); padding:10px 12px; margin:6px 0; border:1px solid var(--ui-line); border-radius:8px; background:var(--ui-paper); cursor:pointer; overflow-wrap:anywhere; }
.decision-option input { width:22px; height:22px; margin:0 10px 0 0; vertical-align:middle; accent-color:var(--ui-accent); }
button { min-height:var(--ui-control); max-width:100%; padding:9px 14px; margin:8px 8px 8px 0; border:1px solid var(--ui-line); border-radius:8px; background:var(--ui-paper); color:var(--ui-ink); font:inherit; cursor:pointer; }
button:disabled { opacity:.55; cursor:not-allowed; }
button.primary { background:var(--ui-accent); color:#fff; border-color:var(--ui-accent); }
:focus-visible { outline:3px solid var(--ui-focus); outline-offset:2px; }
.warn { background:var(--ui-warn-bg); color:var(--ui-warn-ink); border:1px solid currentColor; padding:12px; border-radius:8px; margin:12px 0; }
.confirm-note { color:var(--ui-error); font-weight:700; }
table.field-table { border-collapse:collapse; width:100%; margin-top:8px; table-layout:fixed; }
table.field-table th, table.field-table td { border:1px solid var(--ui-line); padding:7px 8px; font-size:.9rem; text-align:left; overflow-wrap:anywhere; }
.candidate-box { min-width:0; border:1px solid var(--ui-line); border-radius:8px; padding:10px; margin:8px 0; overflow-wrap:anywhere; }
@media (max-width:600px) { .panels { grid-template-columns:minmax(0,1fr); } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto !important; animation-duration:.01ms !important; transition-duration:.01ms !important; } }
</style>
</head>
<body>
<header>
<h1>로컬 검토 화면</h1>
""" + site_theme.BUTTON + """
</header>
<main>
<p class="warn">주의: CSV 파일을 스프레드시트로 열면 수식이 실행될 위험이 있습니다. 안전한 확인용으로는 JSON 파일을 사용하세요.</p>
<div id="status" role="status">불러오는 중입니다...</div>
<div id="summary"></div>
<div id="rows"></div>
<div>
<button id="reloadBtn" type="button">다시 불러오기</button>
<button id="exportBtn" type="button" class="primary">내보내기 및 다운로드</button>
</div>
</main>
<script>
(function() {
"use strict";
var csrfToken = "";
var allRows = [];
function setStatus(message, kind) {
  var el = document.getElementById("status");
  el.textContent = message;
  el.className = kind || "";
}
function safeText(value) {
  if (value === null || value === undefined) { return ""; }
  return String(value);
}
function evidenceLabel(status) {
  if (status === "insufficient") { return "부족"; }
  if (status === "available") { return "충분"; }
  return safeText(status);
}
function rowRef(row, idx) {
  if (row && typeof row.ref === "string" && row.ref !== "") { return row.ref; }
  if (row && typeof row.source_ref_snapshot_only === "string" && row.source_ref_snapshot_only !== "") { return row.source_ref_snapshot_only; }
  return "행 " + String(idx + 1);
}
function candidateKeyOf(entry) {
  if (entry && typeof entry.key === "string") { return entry.key; }
  if (entry && typeof entry.candidate_key === "string") { return entry.candidate_key; }
  return "";
}
async function loadModel() {
  setStatus("모델을 불러오는 중입니다...", "");
  var exportBtn = document.getElementById("exportBtn");
  exportBtn.disabled = true;
  try {
    var resp = await fetch("/api/model", {method: "GET", credentials: "same-origin", headers: {"Accept": "application/json"}});
    if (!resp.ok) {
      setStatus("모델을 불러오지 못했습니다. 입력 파일이 바뀌었는지 확인하고 다시 시도하세요.", "error");
      return;
    }
    var data = await resp.json();
    csrfToken = data.csrf_nonce || data.csrfNonce || data.nonce || "";
    var rows = data.rows || (data.model && data.model.rows) || [];
    allRows = rows;
    renderSummary(rows);
    renderAll(rows);
    exportBtn.disabled = false;
    setStatus("총 " + String(rows.length) + "건을 불러왔습니다. 각 행의 결정을 선택하세요.", "ok");
  } catch (err) {
    setStatus("모델을 불러오지 못했습니다. 다시 시도하세요.", "error");
  }
}
function renderSummary(rows) {
  var el = document.getElementById("summary");
  el.textContent = "전체 " + String(rows.length) + "건이 표시됩니다.";
}
function addField(container, labelText, valueText) {
  var p = document.createElement("p");
  p.className = "field";
  var label = document.createElement("span");
  label.className = "label";
  label.textContent = labelText + ": ";
  var val = document.createElement("span");
  val.textContent = safeText(valueText);
  p.appendChild(label);
  p.appendChild(val);
  container.appendChild(p);
  return p;
}
function renderSourcePanel(panel, source) {
  var h = document.createElement("h3");
  h.textContent = "원본 정보";
  panel.appendChild(h);
  var src = source || {};
  addField(panel, "날짜", src.date);
  addField(panel, "금액", src.amount);
  addField(panel, "가맹점", src.merchant);
  addField(panel, "설명", src.description);
  addField(panel, "원본 위치", src.sourceLocator);
  addField(panel, "증빙 상태", evidenceLabel(src.evidence_status));
  var cells = src.fieldcells || [];
  if (cells && cells.length) {
    var table = document.createElement("table");
    table.className = "field-table";
    var headRow = document.createElement("tr");
    var headers = ["주소", "항목", "값"];
    for (var i = 0; i < headers.length; i++) {
      var th = document.createElement("th");
      th.textContent = headers[i];
      headRow.appendChild(th);
    }
    table.appendChild(headRow);
    for (var r = 0; r < cells.length; r++) {
      var tr = document.createElement("tr");
      var addr = document.createElement("td");
      addr.textContent = safeText(cells[r].address);
      var lab = document.createElement("td");
      lab.textContent = safeText(cells[r].label);
      var val = document.createElement("td");
      val.textContent = safeText(cells[r].value);
      tr.appendChild(addr);
      tr.appendChild(lab);
      tr.appendChild(val);
      table.appendChild(tr);
    }
    panel.appendChild(table);
  }
}
function renderCandidatePanel(panel, candidates) {
  var h = document.createElement("h3");
  h.textContent = "후보 목록 (" + String(candidates.length) + "건)";
  panel.appendChild(h);
  if (!candidates.length) {
    var empty = document.createElement("p");
    empty.textContent = "후보가 없습니다. 승인이 비활성화됩니다.";
    panel.appendChild(empty);
    return;
  }
  for (var i = 0; i < candidates.length; i++) {
    var c = candidates[i] || {};
    var box = document.createElement("div");
    box.className = "candidate-box";
    addField(box, "후보 키", candidateKeyOf(c));
    addField(box, "금액", c.amount);
    addField(box, "가맹점", c.merchant);
    addField(box, "설명", c.description);
    addField(box, "위치", c.sourceLocator);
    var dates = c.datefields || {};
    addField(box, "승인일", dates.approval_date);
    addField(box, "매입일", dates.posting_date);
    if (c.approval_number !== undefined && c.approval_number !== null && c.approval_number !== "") {
      addField(box, "승인번호", c.approval_number);
    }
    panel.appendChild(box);
  }
}
function currentDecision(row) {
  if (row && typeof row.decision === "string" && row.decision !== "") { return row.decision; }
  if (row && typeof row.reviewer_decision === "string" && row.reviewer_decision !== "") { return row.reviewer_decision; }
  return "";
}
function renderDecisionGroup(card, row, idx, candidates, insufficient) {
  var group = document.createElement("fieldset");
  group.className = "decision-group";
  var legend = document.createElement("legend");
  legend.textContent = "결정 선택";
  group.appendChild(legend);
  function makeOption(value, labelText, disabledFlag, checkedFlag) {
    var label = document.createElement("label");
    label.className = "decision-option";
    var input = document.createElement("input");
    input.type = "radio";
    input.name = "decision-" + String(idx);
    input.value = value;
    if (disabledFlag) { input.disabled = true; }
    if (checkedFlag) { input.checked = true; }
    var span = document.createElement("span");
    span.textContent = labelText;
    label.appendChild(input);
    label.appendChild(span);
    group.appendChild(label);
    return input;
  }
  var existing = currentDecision(row);
  var approveKey = "";
  if (existing.indexOf("APPROVE:") === 0) {
    approveKey = existing.slice("APPROVE:".length);
  }
  var blankChecked = true;
  if (existing === "REJECT") { blankChecked = false; }
  if (approveKey !== "") {
    var found = false;
    for (var k = 0; k < candidates.length; k++) {
      if (candidateKeyOf(candidates[k]) === approveKey && !insufficient) { found = true; }
    }
    if (found) { blankChecked = false; }
  }
  makeOption("", "보류 (나중에 결정)", false, blankChecked);
  makeOption("REJECT", "거부", false, existing === "REJECT");
  for (var i = 0; i < candidates.length; i++) {
    var key = candidateKeyOf(candidates[i]);
    var val = "APPROVE:" + key;
    makeOption(val, "승인: " + key, insufficient, (!insufficient && existing === val));
  }
  if (insufficient) {
    var note = document.createElement("p");
    note.className = "confirm-note";
    note.textContent = "추가 확인 필요: 증빙이 부족하거나 후보가 없어 승인이 제한됩니다. 이 상태는 백엔드에서 다시 확인합니다.";
    group.appendChild(note);
  }
  card.appendChild(group);
}
function renderAll(rows) {
  var container = document.getElementById("rows");
  container.textContent = "";
  for (var idx = 0; idx < rows.length; idx++) {
    var row = rows[idx] || {};
    var source = row.source || {};
    var candidates = row.candidates || [];
    var evidence = source.evidence_status || "";
    var insufficient = (evidence === "insufficient") || (candidates.length === 0);
    var ref = rowRef(row, idx);
    var card = document.createElement("section");
    card.className = "row-card";
    card.setAttribute("data-ref", ref);
    card.setAttribute("data-index", String(idx));
    var title = document.createElement("h2");
    title.className = "row-title";
    title.textContent = "검토 " + String(idx + 1) + ": " + ref;
    card.appendChild(title);
    var panels = document.createElement("div");
    panels.className = "panels";
    var left = document.createElement("div");
    left.className = "panel";
    renderSourcePanel(left, source);
    var right = document.createElement("div");
    right.className = "panel";
    renderCandidatePanel(right, candidates);
    panels.appendChild(left);
    panels.appendChild(right);
    card.appendChild(panels);
    renderDecisionGroup(card, row, idx, candidates, insufficient);
    container.appendChild(card);
  }
}
function collectDecisions() {
  var out = [];
  for (var idx = 0; idx < allRows.length; idx++) {
    var ref = rowRef(allRows[idx], idx);
    var selected = document.querySelector("input[name=decision-" + String(idx) + "]:checked");
    var value = selected ? selected.value : "";
    out.push({ref: ref, value: value});
  }
  return out;
}
function downloadBlob(content, filename, mimeType) {
  var blob = new Blob([content], {type: mimeType});
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.textContent = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}
async function exportDecisions() {
  var decisions = collectDecisions();
  setStatus("내보내는 중입니다...", "");
  try {
    var resp = await fetch("/api/export", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-Review-CSRF": csrfToken}, body: JSON.stringify({decisions: decisions})});
    if (!resp.ok) {
      setStatus("내보내기에 실패했습니다. 입력이 변경되었는지 확인하고 다시 시도하세요.", "error");
      return;
    }
    var data = await resp.json();
    var csvText = data.decision_csv || "";
    var planText = data.plan_json || "";
    if (typeof planText !== "string") { planText = JSON.stringify(planText); }
    downloadBlob(csvText, "decisions.csv", "text/csv");
    downloadBlob(planText, "plan.json", "application/json");
    setStatus("내보내기가 끝났습니다. CSV와 JSON 파일을 내려받았습니다.", "ok");
  } catch (err) {
    setStatus("내보내기에 실패했습니다. 다시 시도하세요.", "error");
  }
}
document.getElementById("reloadBtn").addEventListener("click", loadModel);
document.getElementById("exportBtn").addEventListener("click", exportDecisions);
loadModel();
})();
</script>
<style id="site-shell-style">""" + SHELL_STYLE + THEME_STYLE + """</style>
<script>""" + THEME_BOOTSTRAP + """</script>
</body>
</html>"""
