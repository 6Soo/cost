"""예약 원천 행사 식별자와 실제 장부 행사를 연결하는 소유자 화면.

세 가지 상태를 구분해서 보여 준다. 설정 없음, 원천은 읽히는데 대상 행사가 아직
없음, 그리고 연결할 수 있는 상태. 보류된 입력은 예시 데이터로 채우지 않는다.
가짜 행이 실제 행과 구분되지 않기 때문이다.

원천의 `reservation:` 식별자는 건드리지 않는다. 접두사를 벗겨 COST 코드를 얻는
일도, 이름을 비슷한 행에 붙이는 일도 없다. 화면이 고른 대상만 연결된다.
"""

from __future__ import annotations

import html
import json

__all__ = ["render_reserve_link_ui"]

_DOCUMENT = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>예약 명단·여행 연결</title>
<style>
@import url('/static/css/tokens.css');
:root { --bg:var(--c-bg); --surface:var(--c-surface); --text:var(--c-text); --muted:var(--c-text-secondary); --border:var(--c-border-control); --soft:var(--c-surface-sunken); --accent:var(--c-accent-solid); --accent-soft:var(--c-accent-subtle); --focus:var(--c-focus,Highlight); }

body { margin: 1.5rem; background:var(--bg); color:var(--text); }
h1 { font-size: var(--t-h1); }
table { border-collapse: collapse; margin: 0.5rem 0; background:var(--surface); }
th, td { border: 1px solid var(--border); padding: 0.5rem 0.65rem; text-align: left; }
th { background:var(--soft); }
.linktable select, input, textarea { max-width:100%; min-height:44px; border:1px solid var(--border); border-radius:var(--r-md);
  background:var(--surface); color:var(--text); padding:8px 10px; font:inherit; }
:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
.bar { margin: 0.75rem 0; display: flex; gap: 8px; flex-wrap: wrap; }
.bar button { display: inline-flex; align-items: center; gap: 6px; min-height: 44px;
  padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--r-md); background: var(--surface); color:var(--text);
  font: inherit; font-weight: 600; cursor: pointer; }
@media (hover:hover) { .bar button:not(:disabled):hover { background:var(--accent-soft); border-color:var(--accent); } }
.bar button:disabled { opacity:.62; cursor:not-allowed; }
.bar button .ic { width: 16px; height: 16px; flex: 0 0 auto; pointer-events: none; }
.backbar a.back { display: inline-flex; align-items: center; gap: 6px; }
.backbar a.back .ic { width: 16px; height: 16px; flex: 0 0 auto; pointer-events: none; }
@media (prefers-reduced-motion: reduce) { .bar button { transition: none; } }
.note { color: var(--muted); }
.err { color: var(--shell-danger, var(--c-danger-text)); }
.warntext { color: var(--shell-warn, var(--c-warn-text)); }
.link-help { margin:.35rem 0 .75rem; color:var(--muted); }
.link-tools { display:flex; align-items:end; gap:.75rem; flex-wrap:wrap; margin:.75rem 0; }
.link-tools label { display:flex; flex-direction:column; gap:.25rem; color:var(--muted); font-size:var(--t-meta); }
.link-tools input, .link-tools select { min-width:15rem; min-height:40px; }
.link-tools .page { display:flex; align-items:center; gap:.5rem; margin-left:auto; }
.link-tools button { min-height:40px; padding:6px 10px; border:1px solid var(--border); border-radius:var(--r-md);
  background:var(--surface); color:var(--text); font:inherit; cursor:pointer; }
.link-tools button:disabled { opacity:.5; cursor:not-allowed; }
.page-count { min-width:5rem; text-align:center; color:var(--muted); }
.linktable tbody tr.is-hidden { display:none; }
.linktable .picker select { min-height:88px; }
.linktable .source-name { font-weight:700; display:block; }
.linktable .source-code { display:block; margin-top:.25rem; color:var(--muted); font-size:var(--t-meta); }
.linktable .chosen { min-width:13rem; }
.linktable .chosen.empty { color:var(--muted); }
.linktable .clear-link { margin-top:.5rem; min-height:36px; padding:5px 9px; border:1px solid var(--border);
  border-radius:var(--r-sm); background:var(--surface); color:var(--text); font:inherit; cursor:pointer; }
@media (hover:hover) { .linktable .clear-link:hover { background:var(--accent-soft); border-color:var(--accent); } }
.empty-filter { padding:1rem; border:1px dashed var(--border); color:var(--muted); }
fieldset { margin: 0.5rem 0; }
a.back { color: var(--accent); text-decoration: none; }
@media (hover:hover) { a.back:hover { text-decoration: underline; } }
.backbar { margin: 0.25rem 0 0.75rem; display: flex; gap: 1rem; flex-wrap: wrap; }

/* The source key is an opaque identifier that happens to be long, and the target
   list is a multi-select that would otherwise be given its intrinsic width.
   Neither is a reason for the document to scroll sideways, and an identifier
   that no longer fits is an identifier the owner cannot read to compare against
   the roster — so it wraps rather than being clipped, elided or shortened.
   `anywhere` rather than `break-word` because the key has no spaces to break on:
   `break-word` leaves the overflow in place and the line still runs wide. */
.linktable { width: 100%; table-layout: fixed; }
.linktable th, .linktable td { overflow-wrap: anywhere; word-break: break-word; }
.linktable .code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.linktable .picker select { width: 100%; max-width: 100%; }

/* Below this width the three columns cannot each hold an identifier and a
   multi-select, so the table becomes one labelled card per source key. The
   `data-label` each cell carries names it, which is what the column header used
   to do. This is a layout change only: the same DOM, the same select, the same
   change handler, and nothing is hidden. */
@media (max-width: 640px) {
  body { margin: 0.75rem; }
  .bar button { flex:1 1 100%; justify-content:center; }
  .linktable, .linktable thead, .linktable tbody, .linktable tr, .linktable td {
    display: block;
    width: auto;
  }
  .linktable thead {
    /* Kept in the document rather than hidden outright, so the labels a screen
       reader reads still come from the table's own header. */
    position: absolute;
    width: 1px; height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .linktable thead th {
    display: block;
    width: 1px;
    max-width: 1px;
    padding: 0;
    overflow: hidden;
  }
  .linktable tr {
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    margin: 0.75rem 0;
    padding: 0.25rem;
  }
  .linktable td { border: 0; padding: 0.25rem; }
  .linktable td::before {
    content: attr(data-label);
    display: block;
    font-size: var(--t-caption);
    color: var(--muted);
    margin-bottom: 0.15rem;
  }
}
@media (max-width:700px) { .link-tools .page { margin-left:0; width:100%; justify-content:space-between; } }
@media (max-width:375px) { body { margin:.625rem; } h1 { font-size:var(--t-h3); } .linktable td { padding:.4rem; } .link-tools input, .link-tools select { min-width:0; width:100%; } }
</style>
</head>
<body>
<main>
<h1>예약 명단·여행 연결</h1>
<!-- Two ways back out. This screen has no navigation rail of its own, so
     without these the owner can arrive here and only reach anything else by
     editing the address bar. Both are owner pages and both are behind the same
     server-side role gate as this one, so neither link widens what a viewer can
     reach. The review link is the configured comparison screen, which is where
     an owner checks this linking against the real source. -->
<nav class="backbar" aria-label="돌아가기">
  <a class="back" id="back-board" href="/board">__ICON_CHEVRON_LEFT__여행별 비용으로 돌아가기</a>
</nav>
<p id="state" role="status" aria-live="polite">불러오는 중입니다.</p>
<div id="summary"></div>
<div class="bar">
  <button id="reloadBtn" type="button">__ICON_REFRESH__다시 불러오기</button>
  <button id="saveBtn" type="button" disabled>__ICON_SAVE__여행 연결 저장</button>
  <button id="cancelBtn" type="button" disabled>변경 취소</button>
  <button id="applyBtn" type="button" disabled>__ICON_CHECK__연결된 명단 적용</button>
</div>
<section id="linkBox"></section>
<section id="planBox"></section>
<div id="rows"></div>
</main>
<script>
var stateUrl = "/api/reserve-link/plan";
var linksUrl = "/api/reserve-link/links";
var applyUrl = "/api/reserve-link/apply";
var csrfToken = "__CSRF__";
var currentTrip = __TRIP_ID__;

var draft = null;          // what the owner is looking at
var pendingLinks = null;   // the owner's edited draft, not yet saved
var applied = false;
var appliedDigest = "";
var visiblePage = 0;
var pageSize = 10;
var rowModels = [];

function el(id) { return document.getElementById(id); }
function text(value) {
  if (value === null || value === undefined) { return ""; }
  return String(value);
}
function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
function add(parent, tag, className, value) {
  var node = document.createElement(tag);
  if (className) { node.className = className; }
  if (value !== undefined) { node.textContent = text(value); }
  parent.appendChild(node);
  return node;
}
// A machine-readable outcome beside the sentence, so a caller can wait for "the
// save was answered" without matching prose. The words on screen are written for
// the owner; this is for whatever is driving the screen.
var lastOutcome = "loading";
function setState(message, kind, outcome) {
  var node = el("state");
  node.textContent = message;
  node.className = kind || "";
  if (outcome !== undefined) { lastOutcome = outcome; }
}

// Everything a refusal clears. A screen that has just been told it may not see the
// source must not keep showing the source or the draft built on it.
function clearAll(message, kind) {
  draft = null;
  pendingLinks = null;
  clear(el("summary"));
  clear(el("linkBox"));
  clear(el("planBox"));
  clear(el("rows"));
  el("saveBtn").disabled = true;
  el("cancelBtn").disabled = true;
  el("applyBtn").disabled = true;
  setState(message, kind || "err");
}

function renderPlan(payload) {
  draft = payload;
  el("cancelBtn").disabled = true;
  pendingLinks = {};
  var per = payload.per_identifier || {};
  Object.keys(per).forEach(function(code) {
    pendingLinks[code] = per[code].slice();
  });

  var counts = payload.counts || {};
  var summary = el("summary");
  clear(summary);
  add(summary, "p", "counts-line",
      "연결 " + text(counts.resolved_transactions || 0) + "개 · 미연결 "
      + text(counts.unlinked_identifiers || 0) + "개");

  var box = el("linkBox");
  clear(box);
  var choices = payload.choices || [];
  if (currentTrip) {
    var currentChoice = choices.find(function(choice) { return choice.tab_id === currentTrip; });
    document.querySelector('h1').textContent = (currentChoice ? currentChoice.label : '이 여행') + ' · 예약 연결';
  }
  if (!choices.length) {
    // The honest empty state. Not an example row, not a disabled dropdown full of
    // invented tabs: there is nothing to connect to yet.
    add(box, "p", "warntext",
        "연결할 COST 여행이 없습니다. 장부에서 여행을 먼저 등록한 뒤 다시 불러와 주세요.");
    el("saveBtn").disabled = true;
    el("applyBtn").disabled = true;
    setState("대상 행사 대기 중입니다. 연결은 진행할 수 없어요.", "warntext");
    return;
  }
  var tools = add(box, "div", "link-tools");
  var searchLabel = add(tools, "label", null, "예약 건 검색");
  var search = document.createElement("input");
  search.id = "linkSearch";
  search.type = "search";
  search.placeholder = "예약자 이름 · 예약 정보 · 여행명";
  search.setAttribute("aria-label", "예약 건 검색");
  searchLabel.appendChild(search);
  var filterLabel = add(tools, "label", null, "상태");
  var filter = document.createElement("select");
  filter.id = "linkFilter";
  filter.setAttribute("aria-label", "예약 건 상태 필터");
  (currentTrip ? [["trip", "이 여행에 연결됨"], ["unlinked", "미연결 예약 찾기"], ["all", "전체 예약에서 찾기"]]
               : [["all", "전체"], ["unlinked", "미연결"], ["linked", "연결됨"]]).forEach(function(item) {
    var option = document.createElement("option");
    option.value = item[0]; option.textContent = item[1]; filter.appendChild(option);
  });
  // Keep all rows visible after a save/reload so a just-linked row remains
  // editable. The status filter is available for owners who want to focus on
  // unlinked work; pagination keeps the default view bounded.
  filter.value = currentTrip ? "trip" : "all";
  filterLabel.appendChild(filter);
  var pager = add(tools, "div", "page");
  var previous = add(pager, "button", null, "이전");
  previous.id = "previousPage";
  var pageCount = add(pager, "span", "page-count", "");
  pageCount.id = "pageCount";
  var next = add(pager, "button", null, "다음");
  next.id = "nextPage";
  var table = add(box, "table", "linktable");
  var head = add(add(table, "thead"), "tr");
  ["예약자 / 예약 정보", "현재 연결", "연결할 COST 여행"].forEach(function(label) {
    var th = add(head, "th", null, label);
    th.setAttribute("scope", "col");
  });
  var body = add(table, "tbody");
  rowModels = [];
  var sourceMeta = {};
  (payload.persons || []).forEach(function(person) {
    (person.assignments || []).forEach(function(code) {
      if (!sourceMeta[code]) { sourceMeta[code] = []; }
      sourceMeta[code].push(person.display_name || "예약자 이름 없음");
    });
  });
  Object.keys(pendingLinks).forEach(function(code) {
    var row = add(body, "tr");
    rowModels.push({code: code, row: row, names: sourceMeta[code] || []});
    // `data-label` is what each cell names itself with once the table becomes a
    // stack of cards at a narrow width. Without it a stacked row is three
    // unlabelled fragments and the source key looks like a heading.
    var keyCell = add(row, "td", "code");
    keyCell.setAttribute("data-label", "예약자 / 예약 정보");
    var people = sourceMeta[code] || [];
    add(keyCell, "span", "source-name", people.join(", ") || "예약자 정보 없음");
    add(keyCell, "span", "source-code", code);
    var chosen = add(row, "td", "chosen");
    chosen.setAttribute("data-label", "현재 연결");
    chosen.setAttribute("data-source", code);
    function renderChosen() {
      clear(chosen);
      var values = pendingLinks[code];
      if (clearButton) { clearButton.hidden = !values.length; }
      var changed = JSON.stringify(values.slice().sort()) !== JSON.stringify((per[code] || []).slice().sort());
      chosen.classList.toggle("empty", !values.length);
      add(chosen, "span", null, values.length
          ? values.map(function(target) {
              var match = choices.find(function(choice) { return choice.tab_id === target; });
              return match ? (match.label || match.tab_id) : target;
            }).join(", ")
          : "아직 연결되지 않음");
      if (changed) { add(chosen, "small", "source-code", "저장 전 변경"); }
    }
    renderChosen();
    var cell = add(row, "td", "picker");
    cell.setAttribute("data-label", "연결할 COST 여행");
    var select = document.createElement("select");
    select.multiple = true;
    select.setAttribute("data-source", code);
    // Named on every row rather than only by the column header, because at a
    // narrow width the header is not beside this control any more.
    select.setAttribute("aria-label", "대상 선택 · " + code);
    select.setAttribute("size", String(Math.min(3, Math.max(2, choices.length))));
    choices.forEach(function(choice) {
      var option = document.createElement("option");
      option.value = choice.tab_id;
      option.textContent = choice.label || choice.tab_id;
      if (pendingLinks[code].indexOf(choice.tab_id) !== -1) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    select.addEventListener("change", function() {
      var picked = [];
      for (var i = 0; i < select.options.length; i++) {
        if (select.options[i].selected) { picked.push(select.options[i].value); }
      }
      // Replace, never merge: the selection *is* the target set for this
      // identifier, so a target the owner removed is gone from the draft.
      pendingLinks[code] = picked;
      renderChosen();
      el("saveBtn").disabled = false;
      el("cancelBtn").disabled = false;
      refreshRows();
    });
    cell.appendChild(select);
    var clearButton = add(cell, "button", "clear-link", "이 예약 연결 해제");
    clearButton.type = "button";
    clearButton.hidden = !pendingLinks[code].length;
    clearButton.addEventListener("click", function() {
      for (var i = 0; i < select.options.length; i++) { select.options[i].selected = false; }
      pendingLinks[code] = [];
      renderChosen();
      el("saveBtn").disabled = false;
      el("cancelBtn").disabled = false;
      refreshRows();
    });
  });
  function refreshRows() {
    var query = (search.value || "").toLowerCase().trim();
    var mode = filter.value;
    var matches = rowModels.filter(function(model) {
      var linked = pendingLinks[model.code].length > 0;
      var targets = pendingLinks[model.code].map(function(target) {
        var choice = choices.find(function(item) { return item.tab_id === target; });
        return choice ? (choice.label || target) : target;
      });
      var searchable = [model.code].concat(model.names, targets).join(" ").toLowerCase();
      return (!query || searchable.indexOf(query) !== -1)
        && (mode === "all" || (mode === "trip" ? pendingLinks[model.code].indexOf(currentTrip) !== -1
                                             : (mode === "linked" ? linked : !linked)));
    });
    var pages = Math.max(1, Math.ceil(matches.length / pageSize));
    visiblePage = Math.max(0, Math.min(visiblePage, pages - 1));
    rowModels.forEach(function(model) { model.row.classList.add("is-hidden"); });
    matches.slice(visiblePage * pageSize, (visiblePage + 1) * pageSize)
      .forEach(function(model) { model.row.classList.remove("is-hidden"); });
    pageCount.textContent = matches.length ? (String(visiblePage + 1) + " / " + String(pages)) : "0건";
    previous.disabled = visiblePage === 0;
    next.disabled = visiblePage >= pages - 1;
    var empty = el("emptyFilter");
    if (empty) { empty.remove(); }
    if (!matches.length) {
      var emptyRow = document.createElement("p");
      emptyRow.id = "emptyFilter"; emptyRow.className = "empty-filter";
      emptyRow.textContent = "조건에 맞는 예약 건이 없습니다.";
      table.parentNode.insertBefore(emptyRow, table);
    }
  }
  search.addEventListener("input", function() { visiblePage = 0; refreshRows(); });
  filter.addEventListener("change", function() { visiblePage = 0; refreshRows(); });
  previous.addEventListener("click", function() { visiblePage--; refreshRows(); });
  next.addEventListener("click", function() { visiblePage++; refreshRows(); });
  refreshRows();
  el("saveBtn").disabled = false;
  // Re-enabled only for a plan this screen has not already applied. The plan
  // digest is the identity of the apply, so an unchanged plan stays spent and a
  // changed one — a link correction, or a different roster — becomes available
  // again. Leaving it enabled would offer a button whose only answer is "already
  // done".
  // Two independent reasons the button is inert, and both must hold:
  // the plan cannot be applied at all (an unlinked identifier refuses the whole
  // roster), or this screen already applied exactly this plan. The second is keyed
  // on the digest rather than on a flag, so a *different* plan — a link
  // correction, or a new roster — is applicable again on the same screen.
  el("applyBtn").disabled = !payload.applicable
    || payload.apply_digest === appliedDigest;
  setState(payload.applicable
           ? "연결 내용을 확인하세요. 여행 연결 저장 후 연결된 명단을 적용할 수 있습니다."
           : "연결되지 않은 원천 식별자가 있어요. " + text(payload.refusal_code),
           payload.applicable ? "" : "warntext",
           payload.applicable ? "ready" : "unlinked");
}

function renderUnconfigured(payload) {
  clearAll("");
  // The configuration-required state, said plainly. Nothing is searched for and no
  // collection is started from this page.
  add(el("rows"), "p", "warntext",
      "예약 명단이 아직 연결되지 않았습니다. 연결되기 전에는 여행을 선택할 수 없으니 장부로 돌아가 다른 업무를 진행해 주세요.");
  setState("예약 명단 연결 대기", "warntext");
  el("state").dataset.code = payload.code || "RESERVE_LINK_CONFIG_REQUIRED";
}

function renderUnreadable(payload) {
  clearAll("");
  add(el("rows"), "p", "err",
      "설정된 원천을 검증하지 못했어요. 관리자에게 문의해 주세요. " + text(payload.code));
  setState("원천을 확인하지 못했어요. 관리자에게 문의해 주세요. " + text(payload.code), "err");
}

function loadPlan(options) {
  // `quiet` keeps a result message on screen across the re-read that follows it.
  // Without it the generic "this plan can be applied" line replaces the very
  // sentence that told the owner what happened, and a test — or a person reading
  // quickly — loses the outcome of the press they just made.
  var settings = options || {};
  return fetch(stateUrl, {method: "GET", credentials: "same-origin",
                           cache: "no-store",
                           headers: {"Accept": "application/json"}})
    .then(function(response) {
      if (response.status === 401 || response.status === 403) {
        clearAll("이 화면의 권한이 없어 예약을 다룰 수 없어요. 관리자에게 문의해 주세요.", "err");
        return null;
      }
      if (!response.ok) { throw new Error("status " + response.status); }
      return response.json();
    })
    .then(function(payload) {
      if (!payload) { return; }
      if (settings.quiet) { return; }
      if (!payload.configured) { renderUnconfigured(payload); return; }
      if (!payload.readable) { renderUnreadable(payload); return; }
      renderPlan(payload);
    })
    .catch(function() {
      clearAll("반영 계획을 세우지 못했습니다. 관리자에게 문의해 주세요.", "err");
    });
}

function saveLinks() {
  if (!draft) { return; }
  var links = [];
  Object.keys(pendingLinks).forEach(function(code) {
    pendingLinks[code].forEach(function(target) {
      links.push({source_event_key: code, target_tab_id: target});
    });
  });
  el("saveBtn").disabled = true;
  setState("연결을 저장하는 중입니다...", "");
  return fetch(linksUrl, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: {"Content-Type": "application/json",
              "X-CSRF-Token": csrfToken},
    body: JSON.stringify({
      request_id: "save-" + Date.now().toString(36),
      source_binding: draft.binding,
      link_revision: draft.link_revision,
      links: links,
      unlinks: []
    })
  })
    .then(function(response) {
      if (response.status === 401 || response.status === 403) {
        // Permission was lost. The source and the draft both go: a screen that may
        // no longer be shown must keep neither, and the draft most of all, since it
        // is the owner's work over a roster they may no longer be allowed to see.
        clearAll("이 화면의 권한이 없어 예약을 다룰 수 없어요. 관리자에게 문의해 주세요.", "err");
        return null;
      }
      return response.json().then(function(body) {
        return {status: response.status, body: body};
      });
    })
    .then(function(result) {
      if (!result) { return; }
      if (result.status !== 200) {
        // A conflict keeps the draft and the selections in it. It is the owner's
        // work and they need it in order to decide; a stale link set or a moved
        // source is not a reason to throw it away.
        el("saveBtn").disabled = false;
        setState("\uc810\uc5b0\uc744 \uc800\uc7a5\ud558\uc9c0 \ubabb\ud588\uc5b4\uc694. \ucf54\ub4dc: "
                + text(result.body.code) + " 관리자에게 문의해 주세요.", "err", "refused");
        return;
      }
      // Re-read *first*, then report.
      //
      // The saved links have a new revision and the plan the screen is holding is
      // the old one, so the page has to pick up the current plan before it can
      // offer an apply — and the message has to come after, or the re-read's own
      // line replaces the sentence that said what happened. The draft itself is not
      // discarded: `renderPlan` rebuilds it from the links that were just saved,
      // which is the same set the owner submitted.
      return loadPlan().then(function() {
        setState("연결을 저장했어요. 적용은 따로 실행해야 해요.", "ok", "saved");
      });
    })
    .catch(function() {
      el("saveBtn").disabled = false;
      setState("연결을 저장하지 못했습니다. 관리자에게 문의해 주세요.", "err");
    });
}

function setStatusRefused(message) {
  // The draft is kept deliberately: it is the owner's work, and losing it on a
  // refusal is exactly what the contract rules out.
  setState(message, "err");
}

function runApply() {
  if (!draft || !draft.applicable) { return; }
  // Keyed on the plan digest, not on a flag. A global flag would spend this
  // screen for good, and a link correction afterwards — a different plan, on
  // this same screen — could never be applied without a reload.
  if (appliedDigest && draft && draft.apply_digest === appliedDigest) {
    return;
  }
  el("applyBtn").disabled = true;
  setState("명단을 적용하는 중입니다...", "");
  return fetch(applyUrl, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: {"Content-Type": "application/json",
              "X-CSRF-Token": csrfToken},
    body: JSON.stringify({
      request_id: "apply-" + Date.now().toString(36),
      source_binding: draft.binding,
      link_revision: draft.link_revision,
      apply_digest: draft.apply_digest
    })
  })
    .then(function(response) {
      return response.json().then(function(body) {
        return {status: response.status, body: body};
      });
    })
    .then(function(result) {
      if (result.status !== 200) {
        el("applyBtn").disabled = false;
        setState("적용하지 못했어요. 코드: " + text(result.body.code) + " 관리자에게 문의해 주세요.", "err");
        return;
      }
      applied = true;
      appliedDigest = result.body.apply_digest || draft.apply_digest;
      return loadPlan().then(function() {
        setState("명단을 적용했어요.", "ok", "applied");
      });
    })
    .catch(function() {
      el("applyBtn").disabled = false;
      setState("명단을 적용하지 못했습니다. 관리자에게 문의해 주세요.", "err");
    });
}

el("reloadBtn").addEventListener("click", loadPlan);
el("cancelBtn").addEventListener("click", function() {
  if (draft) { renderPlan(draft); setState("저장 전 변경을 취소했습니다.", ""); }
});
el("saveBtn").addEventListener("click", saveLinks);
el("applyBtn").addEventListener("click", runApply);
// Read once on open. Not on a timer: this is the owner's screen, and re-reading
// it underneath a draft would replace the roster the draft was built on.
loadPlan();
window.__reserveLink = {
  outcome: function() { return lastOutcome; },
  message: function() { return el("state").textContent; },
  state: function() { return draft; },
  appliedDigest: function() { return appliedDigest; },
  draft: function() { return JSON.parse(JSON.stringify(pendingLinks)); },
  applied: function() { return applied; },
  saveDisabled: function() { return el("saveBtn").disabled; },
  applyDisabled: function() { return el("applyBtn").disabled; }
};
</script>
</body>
</html>
"""


def render_reserve_link_ui(csrf_token: str = "", payload_json: str = "", *,
                           trip_id: str = "", embedded: bool = False) -> str:
    """The static document.

    Only the CSRF token is substituted. No source identifier, no person, no
    reservation detail and no target name is placed in the document: the screen
    fetches them over the authenticated route, so a copy of this HTML carries no
    data. The payload argument exists for a caller that already has one and is not
    interpolated, which is the same rule stated twice on purpose.
    """
    from . import ui_icons

    del payload_json
    markup = _DOCUMENT.replace(
        "__CSRF__", html.escape("" if csrf_token is None else str(csrf_token),
                                 quote=True))
    markup = markup.replace('__TRIP_ID__', json.dumps(str(trip_id), ensure_ascii=True).replace('<', '\\u003c'))
    if trip_id:
        from urllib.parse import urlencode
        back = '/board?' + urlencode({'tab': trip_id})
        markup = markup.replace('id="back-board" href="/board"',
                                'id="back-board" href="' + html.escape(back, quote=True) + '"')
        # Applying the roster is a global operation, never disguised as this trip's save.
        button = '<button id="applyBtn" type="button" disabled>__ICON_CHECK__연결된 명단 적용</button>'
        markup = markup.replace(button, '<details class="global-roster"><summary>전체 명단 작업</summary>'
                                '<p>이 작업은 현재 여행뿐 아니라 전체 연결 명단을 적용합니다. 여행 연결 저장과 별개입니다.</p>'
                                + button.replace('연결된 명단 적용', '전체 연결 명단 적용') + '</details>')
    if embedded and trip_id:
        from . import site_theme
        markup = markup.replace('<body>', '<body data-trip-reservation-embed="1">')
        markup = markup.replace('</head>', '<style>'
                                + 'body{margin:0;padding:8px;box-sizing:border-box} .backbar{display:none}'
                                + 'h1{font-size:var(--t-body)}.link-tools input,.link-tools select{min-width:0;max-width:100%}'
                                + '</style><script>' + site_theme.BOOTSTRAP + '</script></head>')
    for token, name in (
            ("__ICON_CHEVRON_LEFT__", "chevron-left"),
            ("__ICON_SEARCH__", "search"),
            ("__ICON_REFRESH__", "refresh-cw"),
            ("__ICON_SAVE__", "save"),
            ("__ICON_CHECK__", "check")):
        markup = markup.replace(token, ui_icons.icon(name))
    return markup
