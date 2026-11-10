"""Rule dialog and learning case screen rendering for ledger board.

Extracted under RF-102 to separate rule dialog screen rendering, preview tables,
and learning case HTML forms from the ledger board request handler.
"""
from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional, Tuple

from .classification_rules import (SYNTHETIC_MODE_NOTE, dialog_state_label,
                                   question_view, reason_label)

RULE_MODE_LABEL = SYNTHETIC_MODE_NOTE


def esc(value: Any) -> str:
    """Escape value for safe HTML insertion."""
    return html.escape("" if value is None else str(value), quote=True)


def rule_scope_text(rule: dict) -> str:
    """The rule in one sentence, so the owner can see how wide it is before applying."""
    conditions = rule.get("conditions") or {}
    names = {"merchant_normalized": "가맹점", "card_kind": "카드 구분", "transaction_direction": "거래 방향"}
    parts = []
    for field, entry in conditions.items():
        value = entry.get("value")
        value = ", ".join(map(str, value)) if isinstance(value, list) else value
        parts.append(f"{names.get(field, field)} = {value}")
    optional = rule.get("optional_conditions") or {}
    if optional.get("amount_range"):
        parts.append(f"금액 범위 {optional['amount_range']}")
    if optional.get("date_or_service_period"):
        parts.append(f"기간 {optional['date_or_service_period']}")
    effect_names = {"item": "항목", "display_tab_id": "여행 탭", "description_template": "내용"}
    changes = ", ".join(f"{effect_names.get(k, k)} → {v}" for k, v in (rule.get("effects") or {}).items())
    text = " · ".join(parts) + (f" ⇒ {changes}" if changes else "")
    scope = rule.get("scope") or {}
    if scope.get("trip_id"):
        text += f" (여행 {scope['trip_id']}, {scope.get('event_year')}년)"
    if list(conditions) == ["merchant_normalized"]:
        text += (" — 모든 여행·모든 카드의 같은 가맹점 거래에 해당합니다."
                 " 같은 가맹점의 기존 카드 분류 규칙이 있으면 미래 입력부터 이 규칙이 그 항목을 대체합니다")
    return text


def rule_hidden(case_id: str, request_id: str, *, csrf_token: str, extra: str = "") -> str:
    """Hidden inputs for rule dialog POST forms."""
    return (f"<input type='hidden' name='csrf' value='{csrf_token}'>"
            f"<input type='hidden' name='case' value='{esc(case_id)}'>"
            f"<input type='hidden' name='client_request_id' value='{esc(request_id)}'>"
            f"{extra}")


def rule_dialog_page(
    case_id: str,
    query: dict,
    *,
    store: Any,
    csrf_token: str,
) -> str:
    """Minimal rule dialog screen on top of the existing functional HTML.

    The screen only orchestrates existing endpoints. It never writes a row
    itself, and a provider answer is shown as a draft the owner must confirm.
    """
    from . import ledger_design

    if store is None:
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body="<div class='sect'><p>저장소가 연결되지 않았습니다.</p></div>"))
    state = store.dialog_page_state(case_id)
    row = store.get_row(state["row_id"]) if state.get("row_id") else None
    if row is None:
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body="<div class='sect'><p>대화에 연결된 행이 없습니다.</p></div>"))
    row_id = esc(row["row_id"])
    dialog = state["dialog_state"]
    conv = state["conversation"] or {}
    pending = state["pending_draft"]
    rule = state["rule"]
    provider = state["provider"] or {}
    real_call = bool(provider.get("is_real_call"))
    mode_label = "AI 연결됨" if real_call else RULE_MODE_LABEL
    notice = query.get("msg", [""])[0]
    parts = []

    parts.append(
        f"<h3>규칙 대화</h3>"
        f"<p class='muted'>{esc(row.get('item', ''))} · {esc(row.get('description', ''))}</p>"
        f"<p><span class='synth'>{esc(mode_label)}</span> "
        f"<span class='muted'>대화 상태: {esc(dialog_state_label(dialog))}"
        + (f" · 공급자: {esc(conv.get('active_provider') or '-')}"
           f" · model: {esc(conv.get('active_model_id') or '-')}"
           f" · 턴 {conv.get('turn_count', 0)}회" if conv else "")
        + "</span></p>")
    if notice:
        parts.append(f"<p class='muted'>{esc(notice)}</p>")
    if "PREVIEW_STALE" in notice:
        parts.append(
            "<p class='muted'>선택한 행이 바뀌었습니다. 아래에서 새 미리보기를 다시 받아 주세요."
            " 일부 행만 적용되지는 않습니다.</p>")
    if dialog == "closed":
        parts.append(
            "<form method='post' action='/api/classification/dialog/resume'>"
            + rule_hidden(case_id, f"ui-resume-{case_id}", csrf_token=csrf_token)
            + "<button class='btn' type='submit'>대화 재개</button></form>")
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id='', heading='규칙 대화',
            body=(f"<div class='sect'>{''.join(parts)}"
                  "<p><a href='/board'>목록으로</a></p></div>")))

    if state["should_not_create_rule"]:
        parts.append(
            "<p class='muted'>이번 거래만 적용하기로 하셨습니다. 규칙 초안·영향 미리보기·"
            "적용은 진행하지 않고, 이미 저장한 행 수정은 그대로 유지합니다.</p>")

    # 근거 자유문: 그대로 저장한다
    parts.append(
        "<form method='post' action='/api/classification/dialog/note'>"
        + rule_hidden(case_id, f"ui-note-{case_id}", csrf_token=csrf_token)
        + "<p><label>근거 설명 (자유문)</label>"
        + f"<input name='note' value='{esc(state['note'])}' size='60'></p>"
        + "<button class='btn' type='submit'>근거 저장</button></form>")

    # 질문
    for question in state["questions"]:
        answered = question["answer"] is not None
        view = question_view(question)
        if question["question_key"] == "trip_move_reason" and not answered and not question["options"]:
            parts.append(
                "<section class='qgroup'><p>" + esc(view["prompt"]) + "</p>"
                "<form method='post' action='/api/classification/conversation/reasons'>"
                + rule_hidden(case_id, f"ui-reasons-{case_id}", csrf_token=csrf_token)
                + "<button class='btn' type='submit'>AI 예상 이유 2개 제안</button></form>"
                "<form method='post' action='/api/classification/dialog/answer'>"
                + rule_hidden(case_id, f"ui-direct-reason-{case_id}", csrf_token=csrf_token,
                              extra=(f"<input type='hidden' name='question_id' value='{esc(question['question_id'])}'>"
                                     f"<input type='hidden' name='expected_row_revision' value='{row.get('revision', 1)}'>"
                                     "<input type='hidden' name='answer' value='__direct__'>"))
                + "<label>직접 입력<textarea name='direct_answer' required maxlength='500'></textarea></label>"
                + "<button class='btn' type='submit'>이유 저장</button></form></section>")
            continue
        options = "".join(
            f"<label class='opt'>"
            f"<input type='radio' name='answer' value='{esc(option['value'])}'"
            f"{' checked' if question['answer'] == option['value'] else ''}>"
            f"<span>{esc(option['label'])}</span></label>"
            for option in view["options"])
        if answered:
            parts.append(f"<p class='muted'>답변 완료: {esc(view['answer_label'])}</p>")
        else:
            parts.append(
                f"<form method='post' action='/api/classification/dialog/answer'>"
                + rule_hidden(case_id, f"ui-answer-{case_id}-{question['question_key']}", csrf_token=csrf_token,
                              extra=(f"<input type='hidden' name='question_id' value='{esc(question['question_id'])}'>"
                                     f"<input type='hidden' name='expected_row_revision' value='{row.get('revision', 1)}'>"))
                + "<div class='qgroup'>"
                + f"<p>{esc(view['prompt'])}</p><p>{options}</p>"
                + ("<label>직접 입력<textarea name='direct_answer' maxlength='500'></textarea></label>"
                   if question["question_key"] == "trip_move_reason" else "")
                + "<button class='btn' type='submit'>답변 저장</button></div></form>")
    if not state["open_questions"]:
        parts.append("<p class='muted'>더 물을 질문이 없습니다.</p>")

    if state["should_not_create_rule"]:
        parts.append(
            "<form method='post' action='/api/classification/dialog/close'>"
            + rule_hidden(case_id, f"ui-close-{case_id}", csrf_token=csrf_token)
            + "<button class='btn' type='submit'>대화 닫기</button></form>")
        return ledger_design.render(ledger_design.shell(
            '규칙 대화', tab_id=row.get('display_tab_id') or '',
            heading='규칙 대화',
            body=(f"<div class='sect'>{''.join(parts)}"
                  f"<p><a href='/row?id={esc(row_id)}'>내용으로 돌아가기</a> · "
                  "<a href='/board'>목록으로</a></p></div>")))

    # 규칙 초안 요청
    turn_no = (conv.get("turn_count") or 0) + 1
    parts.append(
        "<form method='post' action='/api/classification/conversation/advance'>"
        + rule_hidden(case_id, f"ui-turn-{case_id}-{turn_no:02d}", csrf_token=csrf_token)
        + "<button class='btn' type='submit'>규칙 초안 요청</button></form>")
    if conv.get("turns"):
        last = conv["turns"][-1]
        review = last.get("owner_review")
        parts.append(
            f"<p class='muted'>최근 턴 {esc(last['turn_id'])}: "
            f"{esc(last.get('state_label') or last['state'])}"
            + (f" · 채택 {esc(last['adopted_provider'])}" if last["adopted_provider"] else "")
            + (f" · 사유 {esc(reason_label(last['reason_code']))}"
               if last["reason_code"] else "")
            + (f" · 전환 {last['switch_count']}회" if last["switch_count"] else "")
            + (f" · 소유권 확인 대기 ({esc(reason_label(review['reason']))})"
               if review else "")
            + "</p>")
    if pending.get("draft_error"):
        parts.append(f"<p class='muted'>초안 검증 실패: {esc(pending['draft_error']['message'])}</p>")

    if not rule and dialog != "closed":
        parts.append(
            "<p class='muted'>이 거래에서 저장한 수정(항목·여행)을 같은 가맹점 거래에 반복 적용하는 규칙 초안을 만듭니다."
            " 초안은 아직 아무 행도 바꾸지 않으며, 아래에서 영향 미리보기를 확인한 뒤 직접 적용합니다.</p>"
            "<form method='post' action='/api/classification/conversation/owner-draft'>"
            + rule_hidden(case_id, f"ui-owner-draft-{case_id}", csrf_token=csrf_token)
            + "<button class='btn' type='submit'>내 수정 내용으로 규칙 초안 만들기</button></form>")

    if pending.get("rule") and not pending.get("confirmed"):
        parts.append(
            "<p class='muted'>검증을 통과한 초안이에요. 저장하면 규칙 초안이 되고, 적용은 "
            "아래에서 범위를 고른 뒤 따로 합니다.</p>"
            "<form method='post' action='/api/classification/conversation/confirm-draft'>"
            + rule_hidden(case_id, f"ui-confirm-{case_id}-{pending.get('turn_id', '')}", csrf_token=csrf_token)
            + "<button class='btn' type='submit'>초안 저장</button></form>")

    if rule:
        parts.append(
            f"<p class='muted'>저장된 규칙 {esc(rule['rule_id'])} · version {rule['version']}"
            f" · {esc(rule['status'])}</p>"
            f"<p><b>적용 조건</b> {esc(rule_scope_text(rule['rule']))}</p>")
        existing = state.get("last_preview") or {}
        preview = existing.get("plan") or {}
        if preview:
            counts = preview.get("counts", {})
            amounts = preview.get("amounts", {})
            rows_html = "".join(
                f"<tr><td>{esc(c['row_id'])}</td><td>{esc(c['from_tab_id'] or '귀속 없음')}"
                f"</td><td>{esc(c['to_tab_id'] or '귀속 없음')}</td>"
                f"<td style='text-align:right'>{esc(c['amount_krw'])}</td></tr>"
                for c in preview.get("candidates", []))
            excluded_html = "".join(
                f"<li>{esc(e['row_id'])}: {esc(e['reason'])}</li>"
                for e in preview.get("excluded", []))
            parts.append(
                f"<h4>영향 미리보기 (preview {esc(existing['preview_id'])[:12]}…)</h4>"
                f"<p class='muted'>포함 {counts.get('included_rows', 0)}건 · 제외 "
                f"{counts.get('excluded_rows', 0)}건 · 매칭 {counts.get('matched_rows', 0)}건</p>"
                f"<table class='rules-table'><tr><th>행</th><th>이동 전</th><th>이동 후</th>"
                f"<th style='text-align:right'>금액</th></tr>{rows_html}</table>"
                + (f"<ul class='muted'>{excluded_html}</ul>" if excluded_html else "")
                + "<p class='muted'>합계(전): " + ", ".join(
                    f"{esc(tab)} {esc(value.get('before'))} → {esc(value.get('after'))}"
                    for tab, value in amounts.items()) + "</p>")
        parts.append(
            "<form method='post' action='/api/classification/rules/preview'>"
            + rule_hidden(case_id, f"ui-preview-{case_id}-{turn_no:02d}", csrf_token=csrf_token,
                          extra=f"<input type='hidden' name='rule_id' value='{esc(rule['rule_id'])}'>")
            + "<label style='margin-right:12px'><input type='checkbox' name='apply_existing' value='1' checked>"
            " 기존 행 적용</label>"
            + "<label><input type='checkbox' name='apply_future' value='1'> 미래 입력 적용</label>"
            + "<button class='btn' type='submit'>영향 미리보기</button></form>")
        if preview and existing:
            selected = ",".join(c["row_id"] for c in preview.get("candidates", []))
            parts.append(
                "<form method='post' action='/api/classification/rules/apply'>"
                + rule_hidden(case_id, f"ui-apply-{case_id}-{existing['preview_id'][:12]}", csrf_token=csrf_token,
                              extra=(f"<input type='hidden' name='preview_id' value='{esc(existing['preview_id'])}'>"
                                     f"<input type='hidden' name='apply_existing' value='{existing['apply_existing'] and '1' or ''}'>"
                                     f"<input type='hidden' name='apply_future' value='{existing['apply_future'] and '1' or ''}'>"
                                     + (f"<input type='hidden' name='selected_row_ids' value='{esc(selected)}'>" if selected else "")))
                + "<button class='btn' type='submit'>이 범위로 적용</button></form>")
    if dialog != "not_started":
        # Closing a dialog that was never started is refused by the store, so the
        # control is not offered until there is something to close.
        parts.append(
            "<form method='post' action='/api/classification/dialog/close'>"
            + rule_hidden(case_id, f"ui-close-{case_id}", csrf_token=csrf_token)
            + "<button class='btn' type='submit'>대화 닫기</button></form>")
    body = (f"<div class='sect'>{''.join(parts)}"
            f"<p><a href='/row?id={row_id}'>내용으로 돌아가기</a> · "
            "<a href='/board'>목록으로</a></p></div>")
    return ledger_design.render(ledger_design.shell(
        '규칙 대화', tab_id=row.get('display_tab_id') or '',
        heading='규칙 대화', body=body))
