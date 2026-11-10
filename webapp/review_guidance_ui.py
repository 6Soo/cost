"""Inline review guidance controls; values are always rendered as text."""

SCRIPT = r'''
var guidanceDrafts = {};
function guidanceApi(path, body, method) {
  var opts = {method: method || "POST", credentials: "same-origin", cache: "no-store",
              headers: {"Accept": "application/json"}};
  if (opts.method === "POST") {
    body.csrf = csrfToken();
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return fetch(path, opts).then(function(response) {
    return response.json().then(function(data) {
      if (!response.ok) {
        var err = new Error(data.message || data.code || "저장하지 못했습니다.");
        err.code = data.code; throw err;
      }
      return data;
    });
  });
}
function sourceLabel(source, label) {
  var cells = source.fieldcells || [];
  for (var i = 0; i < cells.length; i++) {
    if (cells[i].label === label) { return text(cells[i].value); }
  }
  return "";
}
function renderRecommendation(card, row) {
  var candidates = row.candidates || [], source = row.source || {};
  var recommendation = row.pipeline_recommendation || {};
  var recommended = null;
  for (var i = 0; i < candidates.length; i++) {
    if (candidateKeyOf(candidates[i]) === recommendation.candidate_key) { recommended = candidates[i]; }
  }
  var box = add(card, "div", "recommendation");
  if (recommended) {
    add(box, "p", null, "대사 권고: " + text(recommended.merchant) + " 거래를 확인하세요.");
    add(box, "p", "muted", "기존 대사 기록이 있고, 해당 카드 거래를 가리키는 원본이 한 건입니다.");
  } else if (candidates.length === 1) {
    var only = candidates[0], reasons = [];
    if (text(source.amount).replace(/[,원\s]/g, "") === text(only.amount).replace(/[,원\s]/g, "")) { reasons.push("금액 일치"); }
    if (source.date === (only.datefields || {}).approval_date) { reasons.push("승인일 일치"); }
    add(box, "p", null, "대사 후보: " + text(only.merchant));
    add(box, "p", "muted", reasons.length ? reasons.join(" · ") + " · 같은 거래인지 확인하세요." : "원본과 카드사 사용 내역을 비교해 같은 거래인지 확인하세요.");
  } else {
    add(box, "p", null, candidates.length ? "카드사 사용 내역이 여러 건입니다. 같은 거래를 선택하세요." : "비교할 카드사 사용 내역이 없습니다. 아래에 확인 내용이나 수정 방향을 남겨 주세요.");
  }
}
function renderGuidance(card, row) {
  var ref = row.ref, binding = savedBinding;
  var cacheKey = binding + "|" + ref;
  var draft = guidanceDrafts[cacheKey];
  if (!draft) {
    draft = {revision: 0, note: "", item: "", description: "", loaded: false, dirty: false, editVersion: 0};
    guidanceDrafts[cacheKey] = draft;
  }
  var section = add(card, "div", "guidance");
  var noteId = "answer-" + Object.keys(guidanceDrafts).indexOf(cacheKey);
  var label = add(section, "label", null, "검토 메모·요청 내용"); label.htmlFor = noteId;
  var answer = add(section, "textarea"); answer.id = noteId; answer.rows = 2;
  answer.maxLength = 2000; answer.value = draft.note;
  answer.placeholder = "확인한 사실이나 원하는 수정 내용을 적어 주세요.";
  var actions = add(section, "div", "bar");
  var save = add(actions, "button", null, "답변 저장"); save.type = "button";
  var reload = add(actions, "button", null, "저장된 답변 보기"); reload.type = "button";
  var message = add(section, "p", "guidance-message"); message.setAttribute("role", "status");
  var resultBox = add(section, "p", "guidance-result"); resultBox.setAttribute("role", "status");
  function showReviewResult(saved) {
    var result = saved.review_result;
    resultBox.textContent = result ? "검토 결과 · 추가 자료 확인: " + result.summary : "";
  }
  var rule = null, item = null, description = null, candidate = null, existing = null, future = null, previewButton = null, applyButton = null, previewBox = null;
  if (blockKindOf(row) === "expense") {
    rule = add(section, "details", "guidance-rule");
    add(rule, "summary", null, "분류 규칙 수정");
    var itemLabel = add(rule, "label", null, "바꿀 항목");
    item = add(itemLabel, "input"); item.type = "text"; item.maxLength = 60; item.value = draft.item;
    item.placeholder = "예: 숙박비";
    var descriptionLabel = add(rule, "label", null, "바꿀 내용");
    description = add(descriptionLabel, "input"); description.type = "text"; description.maxLength = 200; description.value = draft.description;
    var conditionLabel = add(rule, "label", null, "규칙 기준 카드 거래");
    candidate = add(conditionLabel, "select");
    add(candidate, "option", null, "카드 거래를 선택하세요").value = "";
    var entries = row.candidates || [];
    for (var c = 0; c < entries.length; c++) {
      var opt = add(candidate, "option", null, text(entries[c].merchant) + " · " + wonText(entries[c].amount));
      opt.value = candidateKeyOf(entries[c]);
    }
    var selected = chosenOf(ref);
    candidate.value = selected.indexOf("APPROVE:") === 0 ? selected.slice(8) : (entries.length === 1 ? candidateKeyOf(entries[0]) : "");
    function scope(textLabel) {
      var l = add(rule, "label", "scope-option");
      var input = add(l, "input"); input.type = "checkbox";
      add(l, "span", null, textLabel); return input;
    }
    existing = scope("같은 조건의 기존 장부 행에 적용");
    future = scope("앞으로 가져오는 카드 내역에 적용");
    var controls = add(rule, "div", "bar");
    previewButton = add(controls, "button", null, "영향 미리보기"); previewButton.type = "button";
    applyButton = add(controls, "button", null, "확인한 규칙 적용"); applyButton.type = "button"; applyButton.disabled = true;
    previewBox = add(rule, "div", "rule-preview");
  }
  function edited() {
    draft.note = answer.value;
    if (item) { draft.item = item.value; draft.description = description.value; }
    draft.dirty = true; draft.saveRequest = null;
    draft.editVersion += 1;
    draft.preview = null;
    if (applyButton) { applyButton.disabled = true; }
  }
  answer.addEventListener("input", edited);
  if (item) {
    item.addEventListener("input", edited); description.addEventListener("input", edited);
    candidate.addEventListener("change", edited); existing.addEventListener("change", edited); future.addEventListener("change", edited);
  }
  function fields() {
    return {ref: ref, binding: binding, note: answer.value, item: item ? item.value : "", description: description ? description.value : ""};
  }
  function showError(error) {
    message.textContent = error.code && error.code.indexOf("CONFLICT") >= 0
        ? "다른 기기에서 답변이나 원천 자료가 바뀌었습니다. 다시 불러와 확인해 주세요."
        : error.message;
  }
  function loadAnswer(force) {
    var version = draft.editVersion;
    return guidanceApi("/api/review/guidance?ref=" + encodeURIComponent(ref) + "&binding=" + encodeURIComponent(binding), null, "GET").then(function(data) {
      var saved = data.guidance || data;
      showReviewResult(saved);
      draft.revision = saved.revision || 0; draft.loaded = true;
      if (version === draft.editVersion && (force || !draft.dirty)) {
        draft.note = saved.note || ""; draft.item = saved.item || ""; draft.description = saved.description || "";
        answer.value = draft.note;
        if (item) { item.value = draft.item; description.value = draft.description; }
        draft.dirty = false;
      }
      return saved;
    });
  }
  answer.addEventListener("focus", function() { if (!draft.loaded) { loadAnswer(false).catch(showError); } });
  reload.addEventListener("click", function() {
    var preserve = draft.dirty;
    loadAnswer(!preserve).then(function(saved) {
      if (preserve) {
        draft.saveRequest = null;
        message.textContent = "현재 저장된 답변: " + (saved.note || "없음") +
            ". 입력 중인 답변은 유지했습니다. 답변 저장을 누르면 내 입력으로 바꿉니다.";
      } else { message.textContent = "저장된 답변을 불러왔습니다."; }
    }).catch(showError);
  });
  save.addEventListener("click", function() {
    save.disabled = true;
    var submittedVersion;
    (draft.loaded ? Promise.resolve() : loadAnswer(false)).then(function() {
      var payload = fields(); payload.expected_revision = draft.revision;
      submittedVersion = draft.editVersion;
      if (!draft.saveRequest) { draft.saveRequest = newRequestId(); }
      payload.request_id = draft.saveRequest;
      return guidanceApi("/api/review/guidance/save", payload);
    }).then(function(data) {
      var saved = data.guidance || data;
      resultBox.textContent = "";
      draft.revision = saved.revision; draft.note = answer.value;
      draft.item = item ? item.value : ""; draft.description = description ? description.value : "";
      if (submittedVersion === draft.editVersion) { draft.dirty = false; draft.saveRequest = null; }
      message.textContent = "검토 내용을 저장했습니다.";
    }).catch(showError).finally(function() { save.disabled = false; });
  });
  if (previewButton) {
    previewButton.addEventListener("click", function() {
      if (!candidate.value || (!item.value.trim() && !description.value.trim()) || (!existing.checked && !future.checked)) {
        message.textContent = "카드 거래, 바꿀 항목이나 내용, 적용 범위를 선택해 주세요."; return;
      }
      var payload = fields(); payload.condition_candidate_key = candidate.value;
      payload.apply_existing = existing.checked; payload.apply_future = future.checked; payload.request_id = newRequestId();
      var previewVersion = draft.editVersion;
      previewButton.disabled = true; applyButton.disabled = true;
      guidanceApi("/api/review/guidance/rule-preview", payload).then(function(data) {
        if (previewVersion !== draft.editVersion) {
          message.textContent = "입력을 바꿨으므로 영향을 다시 확인해 주세요."; return;
        }
        var preview = data.preview || data;
        preview.apply_existing = payload.apply_existing; preview.apply_future = payload.apply_future;
        preview.apply_request_id = newRequestId();
        draft.preview = preview;
        clear(previewBox);
        var basis = preview.condition_basis || {};
        var kind = basis.card_kind;
        if (kind && typeof kind === "object") { kind = kind.value; }
        add(previewBox, "p", null, "조건: 가맹점 " + text(basis.merchant_normalized) + (kind ? " · 카드 " + text(kind) : " · 모든 카드 종류"));
        add(previewBox, "p", null, "변경: " + (payload.item ? "항목 → " + payload.item : "") + (payload.description ? " · 내용 → " + payload.description : ""));
        add(previewBox, "p", null, "기존 장부 " + text((preview.candidates || []).length) + "건 변경 · 향후 카드 가져오기 " + (future.checked ? "적용" : "적용 안 함"));
        add(previewBox, "p", "muted", "아직 장부에 반영하지 않은 검토 원천은 이 기존 장부 건수에 포함되지 않습니다.");
        var changed = preview.candidates || [];
        var changeList = previewBox;
        if (changed.length > 10) {
          changeList = add(previewBox, "details");
          add(changeList, "summary", null, "변경할 " + changed.length + "건 모두 보기");
        }
        for (var k = 0; k < changed.length; k++) {
          add(changeList, "p", null, wonText(changed[k].amount_krw) + " · " + Object.keys(changed[k].changes || {}).map(function(key) { return (key === "item" ? "항목" : "내용") + " → " + text(changed[k].changes[key]); }).join(" · "));
        }
        var excluded = preview.excluded || [];
        if (excluded.length) {
          var excludedRows = {};
          for (var e = 0; e < excluded.length; e++) { excludedRows[excluded[e].row_id] = true; }
          add(previewBox, "p", "muted", "변경할 필요가 없거나 일부 변경을 제외한 행: " + Object.keys(excludedRows).length + "건");
        }
        applyButton.disabled = false;
      }).catch(showError).finally(function() { previewButton.disabled = false; });
    });
    applyButton.addEventListener("click", function() {
      var preview = draft.preview;
      if (!preview) { return; }
      applyButton.disabled = true;
      var payload = {ref: ref, binding: binding, preview_id: preview.preview_id,
                     apply_existing: preview.apply_existing, apply_future: preview.apply_future, request_id: preview.apply_request_id};
      guidanceApi("/api/review/guidance/rule-apply", payload).then(function() {
        message.textContent = "확인한 적용 범위로 규칙을 저장했습니다."; draft.preview = null;
      }).catch(function(error) { showError(error); if (draft.preview === preview) { applyButton.disabled = false; } });
    });
  }
}
'''
