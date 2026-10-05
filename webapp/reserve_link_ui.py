"""예약 원천 행사 식별자와 실제 장부 행사를 연결하는 소유자 화면.

세 가지 상태를 구분해서 보여 준다. 설정 없음, 원천은 읽히는데 대상 행사가 아직
없음, 그리고 연결할 수 있는 상태. 보류된 입력은 예시 데이터로 채우지 않는다.
가짜 행이 실제 행과 구분되지 않기 때문이다.

원천의 `reservation:` 식별자는 건드리지 않는다. 접두사를 벗겨 COST 코드를 얻는
일도, 이름을 비슷한 행에 붙이는 일도 없다. 화면이 고른 대상만 연결된다.
"""

from __future__ import annotations

import html

__all__ = ["render_reserve_link_ui"]

_DOCUMENT = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>예약 행사 연결</title>
<style>
body { font-family: system-ui, sans-serif; margin: 1.5rem; }
h1 { font-size: 1.25rem; }
table { border-collapse: collapse; margin: 0.5rem 0; }
th, td { border: 1px solid #ccc; padding: 0.25rem 0.5rem; text-align: left; }
.bar { margin: 0.75rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.note { color: #555; }
.err { color: #a00; }
.warntext { color: #a60; }
fieldset { margin: 0.5rem 0; }
a.back { color: #1a4b8c; text-decoration: none; }
a.back:hover { text-decoration: underline; }
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
  .linktable tr {
    border: 1px solid #ccc;
    border-radius: 4px;
    margin: 0.75rem 0;
    padding: 0.25rem;
  }
  .linktable td { border: 0; padding: 0.25rem; }
  .linktable td::before {
    content: attr(data-label);
    display: block;
    font-size: 0.75rem;
    color: #555;
    margin-bottom: 0.15rem;
  }
}
</style>
</head>
<body>
<h1>예약 행사 연결</h1>
<!-- Two ways back out. This screen has no navigation rail of its own, so
     without these the owner can arrive here and only reach anything else by
     editing the address bar. Both are owner pages and both are behind the same
     server-side role gate as this one, so neither link widens what a viewer can
     reach. The review link is the configured comparison screen, which is where
     an owner checks this linking against the real source. -->
<nav class="backbar" aria-label="돌아가기">
  <a class="back" id="back-board" href="/board">장부로 돌아가기</a>
  <a class="back" id="back-review" href="/review">실제 자료 검토</a>
</nav>
<p id="state" role="status" aria-live="polite">불러오는 중입니다.</p>
<div id="summary"></div>
<div class="bar">
  <button id="reloadBtn" type="button">다시 불러오기</button>
  <button id="saveBtn" type="button" disabled>연결 저장</button>
  <button id="applyBtn" type="button" disabled>명단 적용 실행</button>
</div>
<section id="linkBox"></section>
<section id="planBox"></section>
<div id="rows"></div>
<script>
var stateUrl = "/api/reserve-link/plan";
var linksUrl = "/api/reserve-link/links";
var applyUrl = "/api/reserve-link/apply";
var csrfToken = "__CSRF__";

var draft = null;          // what the owner is looking at
var pendingLinks = null;   // the owner's edited draft, not yet saved
var applied = false;
var appliedDigest = "";

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
  el("applyBtn").disabled = true;
  setState(message, kind || "err");
}

function renderPlan(payload) {
  draft = payload;
  pendingLinks = {};
  var per = payload.per_identifier || {};
  Object.keys(per).forEach(function(code) {
    pendingLinks[code] = per[code].slice();
  });

  var counts = payload.counts || {};
  var summary = el("summary");
  clear(summary);
  add(summary, "p", "counts-line",
      "원천 식별자 " + text(counts.source_identifiers || 0) + "개 중 연결 "
      + text(counts.resolved_transactions || 0) + "개, 미연결 "
      + text(counts.unlinked_identifiers || 0) + "개");
  add(summary, "p", "note",
      "원본 revision " + text(payload.binding.source_revision)
      + " · 원본 digest " + text(payload.binding.source_digest).slice(0, 16)
      + "… · 연결 버전 " + text(payload.link_version)
      + " · 연결 revision " + text(payload.link_revision));

  var box = el("linkBox");
  clear(box);
  var choices = payload.choices || [];
  if (!choices.length) {
    // The honest empty state. Not an example row, not a disabled dropdown full of
    // invented tabs: there is nothing to connect to yet.
    add(box, "p", "warntext",
        "장부에 등록된 대상 행사가 없어요. 대상이 등록되면 여기에 나타납니다.");
    el("saveBtn").disabled = true;
    el("applyBtn").disabled = true;
    setState("대상 행사 대기 중입니다. 연결은 진행할 수 없어요.", "warntext");
    return;
  }
  var table = add(box, "table", "linktable");
  var head = add(add(table, "thead"), "tr");
  ["원천 식별자", "연결된 대상", "대상 선택"].forEach(function(label) {
    var th = add(head, "th", null, label);
    th.setAttribute("scope", "col");
  });
  var body = add(table, "tbody");
  Object.keys(pendingLinks).forEach(function(code) {
    var row = add(body, "tr");
    // `data-label` is what each cell names itself with once the table becomes a
    // stack of cards at a narrow width. Without it a stacked row is three
    // unlabelled fragments and the source key looks like a heading.
    var keyCell = add(row, "td", "code", code);
    keyCell.setAttribute("data-label", "원천 식별자");
    var chosen = add(row, "td", "chosen",
                      pendingLinks[code].join(", ") || "연결 없음");
    chosen.setAttribute("data-label", "연결된 대상");
    chosen.setAttribute("data-source", code);
    var cell = add(row, "td", "picker");
    cell.setAttribute("data-label", "대상 선택");
    var select = document.createElement("select");
    select.multiple = true;
    select.setAttribute("data-source", code);
    // Named on every row rather than only by the column header, because at a
    // narrow width the header is not beside this control any more.
    select.setAttribute("aria-label", "대상 선택 · " + code);
    select.setAttribute("size", String(Math.min(4, Math.max(2, choices.length))));
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
      chosen.textContent = picked.join(", ") || "연결 없음";
      el("saveBtn").disabled = false;
    });
    cell.appendChild(select);
  });
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
           ? "연결할 수 있어요. 저장은 연결만, 적용은 명단이 따로예요."
           : "연결되지 않은 원천 식별자가 있어요. " + text(payload.refusal_code),
           payload.applicable ? "" : "warntext",
           payload.applicable ? "ready" : "unlinked");
}

function renderUnconfigured(payload) {
  clearAll("");
  // The configuration-required state, said plainly. Nothing is searched for and no
  // collection is started from this page.
  add(el("rows"), "p", "warntext",
      "원천 설정이 필요해요. 경로·파일 해시·의미 해시를 함께 지정해야 해요.");
  setState(text(payload.code || "RESERVE_LINK_CONFIG_REQUIRED"), "warntext");
}

function renderUnreadable(payload) {
  clearAll("");
  add(el("rows"), "p", "err",
      "설정된 원천을 검증하지 못했어요. " + text(payload.code));
  setState(text(payload.code), "err");
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
        clearAll("이 화면의 권한이 없어 예약을 다룰 수 없어요.", "err");
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
      clearAll("반영 계획을 세우지 못했습니다.", "err");
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
        clearAll("\uc774 \ud654\uba74\uc758 \uad8c\ud55c\uc774 \uc5c6\uc5b4 \uc608\uc57d\uc744 \ub2e4\ub8ec\uc5b4\uc694.", "err");
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
                + text(result.body.code), "err", "refused");
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
      setState("연결을 저장하지 못했습니다.", "err");
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
        setState("적용하지 못했어요. 코드: " + text(result.body.code), "err");
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
      setState("명단을 적용하지 못했습니다.", "err");
    });
}

el("reloadBtn").addEventListener("click", loadPlan);
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


def render_reserve_link_ui(csrf_token: str = "", payload_json: str = "") -> str:
    """The static document.

    Only the CSRF token is substituted. No source identifier, no person, no
    reservation detail and no target name is placed in the document: the screen
    fetches them over the authenticated route, so a copy of this HTML carries no
    data. The payload argument exists for a caller that already has one and is not
    interpolated, which is the same rule stated twice on purpose.
    """
    del payload_json
    return _DOCUMENT.replace(
        "__CSRF__", html.escape("" if csrf_token is None else str(csrf_token),
                                quote=True))