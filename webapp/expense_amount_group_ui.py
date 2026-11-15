"""Read-only, accessible rendering for COST ↔ Google expense amount groups."""
from __future__ import annotations

import html
import hashlib
from collections.abc import Mapping, Sequence


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _group_dom_id(annotation: Mapping[str, object]) -> str:
    """Create a stable, DOM-safe opaque id without exposing source group keys."""
    group_id = annotation.get("group_id")
    if group_id is None:
        group_id = f"{annotation.get('trip_id', '')}\0{annotation.get('amount_krw', '')}"
    digest = hashlib.sha256(str(group_id).encode("utf-8", "replace")).hexdigest()[:20]
    return f"gemn-group-{digest}"


_STATUS = {
    "matched": ("ok", "✓", "장부 건수 일치"),
    "partial": ("partial", "!", "부분 일치"),
    "unrecorded": ("missing", "—", "미기록"),
    "google_only": ("google-only", "·", "Google에만 있음"),
    "unavailable": ("unavailable", "?", "비교 불가"),
}


def _reason_label(reason):
    return {
        'AMOUNT_UNCERTAIN': '금액 또는 통화를 확인할 수 없습니다.',
        'INVALID_OR_UNCERTAIN_ROW': '일부 원행의 금액·통화·식별 정보가 불확실합니다.',
        'TRIP_MAPPING_UNAVAILABLE': '이 여행과 Google 장부의 연결을 확인해 주세요.',
        'SOURCE_NOT_VERIFIED': 'Google 지출 자료가 검증되지 않았거나 오래됐습니다.',
        'SOURCE_LAYOUT_UNSUPPORTED': '이 여행의 Google 시트는 표준 지출 양식이 아닙니다.',
        'SOURCE_FINGERPRINT_MISMATCH': 'Google 지출 자료가 바뀌어 다시 확인해야 합니다.',
        'SOURCE_NOT_SELECTED': '이 여행의 Google 장부를 찾지 못했습니다. 잠시 뒤 다시 열어 주세요.',
        'GOOGLE_SOURCE_DISABLED': 'Google 지출 자료가 연결되지 않았습니다.',
        'GOOGLE_TRIP_UNAVAILABLE': '이 여행의 Google 장부를 찾을 수 없습니다.',
        'COST_TRIP_UNAVAILABLE': '대조할 실제 여행을 확인할 수 없습니다.',
        'SHEET_ROWS_UNAVAILABLE': 'Google 지출 행을 확인할 수 없습니다.',
        'RECONCILIATION_INVALID': '지출 자료를 안전하게 대조할 수 없습니다.',
        'SOURCE_UNAVAILABLE': 'Google 자료를 확인할 수 없습니다.',
    }.get(str(reason), str(reason or 'Google 자료를 확인할 수 없습니다.'))


def status_cell(annotation: Mapping[str, object] | None) -> str:
    """Return a semantic table cell; counts indicate a group, not row identity."""
    annotation = annotation or {}
    status = str(annotation.get("status") or "unavailable")
    tone, icon, label = _STATUS.get(status, _STATUS["unavailable"])
    cost_count = annotation.get("cost_count", "—")
    google_count = annotation.get("google_count", "—")
    group_dom_id = _group_dom_id(annotation)
    detail = f"{label} · COST {cost_count}건 / Google {google_count}건"
    if status == "partial":
        try:
            detail += f" · 차이 {abs(int(cost_count) - int(google_count))}건"
        except (TypeError, ValueError, OverflowError):
            pass
    if status == 'unavailable':
        detail = label + ' · ' + _reason_label(annotation.get('reason'))
        if annotation.get('last_success_at'):
            detail += ' · 마지막 정상 조회 ' + str(annotation['last_success_at'])
    if not annotation.get('group_id') or status == 'unavailable':
        return (f"<td class='gemn-desktop gemn-status-cell gemn-unavailable' title='{_esc(detail)}'>"
                f"<span aria-hidden='true'>{icon}</span> {_esc(label)}</td>")
    return (f"<td class='gemn-desktop gemn-status-cell gemn-{tone}'>"
            f"<button type='button' class='gemn-status-button' data-gemn-group='{group_dom_id}' "
            f"aria-label='{_esc(detail)}' aria-controls='{group_dom_id}'>"
            f"<span aria-hidden='true'>{icon}</span> {_esc(label)} "
            f"<span class='gemn-count'>{_esc(cost_count)}/{_esc(google_count)}</span></button></td>")


def header_cell() -> str:
    """Return the matching accessible table header."""
    return "<th class='gemn-desktop' scope='col'>Google 장부</th>"


def render_summary(state: Mapping[str, object]) -> str:
    """Render group-level totals and source freshness/failure information."""
    summary = state.get("summary") or {}
    summary = summary if isinstance(summary, Mapping) else {}
    names = (("matched", "일치"), ("partial", "부분 일치"),
             ("unrecorded", "미기록"), ("google_only", "Google 전용"))
    counts = " · ".join(f"{label} {_esc(summary.get(key, 0))}그룹" for key, label in names)
    available = state.get("available") is True
    reason = state.get("reason")
    last_success = state.get("last_success_at")
    if not available:
        counts = '그룹 건수 확인 불가'
        note = f"비교 불가 · {_esc(_reason_label(reason))}"
    else:
        note = "Google 지출 스냅샷 기준"
        if state.get('total_warning'):
            note += ' · 시트 합계 수식을 확인해 주세요 · 개별 지출 행 기준 비교'
        if reason:
            note += f" · {_esc(reason)}"
    if last_success:
        note += f" · 마지막 정상 조회 {_esc(last_success)}"
    return (f"<div class='gemn-desktop gemn-summary' role='status' aria-live='polite'>"
            f"<strong>Google 지출 대조</strong><span>{counts}</span>"
            f"<span class='gemn-note'>{note}</span>"
            "<span class='gemn-disclaimer'>건수 일치는 개별 거래 식별 또는 Google 반영 완료를 뜻하지 않습니다.</span></div>")


def _row_label(row: object, identifier_key: str) -> str:
    if not isinstance(row, Mapping):
        return _esc(row)
    identifier = row.get(identifier_key, "")
    details = ([f"Google 행 {row['row_number']}"] if type(row.get('row_number')) is int else
               [f"ID {identifier}"] if identifier != "" else [])
    for key, label in (("date", "날짜"), ("description", "내용"), ("payee", "가맹점")):
        value = row.get(key)
        if value not in (None, ""):
            details.append(f"{label} {value}")
    return _esc(" · ".join(details) or "식별 정보 없음")


def render_groups(state: Mapping[str, object]) -> str:
    """Render compact native-details groups with both source lists, O(m+n) DOM."""
    groups = state.get("groups") or []
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes)):
        groups = []
    if state.get("available") is not True:
        return ''
    output = ["<dialog class='gemn-dialog' aria-label='금액 그룹 상세'>"
              "<button type='button' class='gemn-close' data-gemn-close autofocus>닫기</button>"
              "<div class='gemn-groups'>"]
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        status = str(group.get("status") or "unavailable")
        _, _, label = _STATUS.get(status, _STATUS["unavailable"])
        costs = group.get("cost_rows") or []
        googles = group.get("google_rows") or []
        if not isinstance(costs, Sequence) or isinstance(costs, (str, bytes)):
            costs = []
        if not isinstance(googles, Sequence) or isinstance(googles, (str, bytes)):
            googles = []
        m = group.get("cost_count", len(costs))
        n = group.get("google_count", len(googles))
        amount = group.get("amount_krw", "")
        title = f"{label} · {m}/{n} · {group.get('candidate_count', len(costs) * len(googles))}개 관계"
        if amount != "":
            try:
                amount_text = f"{int(amount):,}원"
            except (ValueError, TypeError, OverflowError):
                amount_text = str(amount)
            title += f" · {amount_text}"
        dom_id = _group_dom_id(group)
        output.append(f"<details id='{dom_id}' class='gemn-group'><summary>{_esc(title)}</summary>")
        output.append(f"<section aria-label='COST 원행 {m}건'><h4>COST 지출 원행 ({_esc(m)}건)</h4><ul>")
        output.extend(f"<li>{_row_label(row, 'row_id')}</li>" for row in costs)
        output.append("</ul></section>")
        output.append(f"<section aria-label='Google 원행 {n}건'><h4>Google 지출 원행 ({_esc(n)}건)</h4><ul>")
        output.extend(f"<li>{_row_label(row, 'ref')}</li>" for row in googles)
        output.append("</ul></section></details>")
    output.append("</div></dialog>")
    return "".join(output)


def styles() -> str:
    """Scoped styles inherit the application's light/dark color tokens."""
    return ("<style>@import url('/static/css/tokens.css');"
            ".gemn-desktop,th.gemn-desktop,td.gemn-desktop{display:none!important}"
            ".gemn-group summary{display:none!important}"
            ".gemn-status-button{font:inherit;color:inherit;background:transparent;border:0;padding:4px;cursor:pointer}"
            ".gemn-summary,.gemn-groups{color:var(--shell-ink,var(--ink,var(--c-text)));background:var(--shell-paper);"
            "border:1px solid var(--shell-line);border-radius:var(--r-md);padding:10px;margin:8px 0}"
            ".gemn-summary{gap:10px 16px;flex-wrap:wrap;align-items:center;font-size:var(--t-meta)}"
            ".gemn-summary .gemn-note,.gemn-summary .gemn-disclaimer{color:var(--shell-muted)}"
            ".gemn-group{border-top:1px solid var(--shell-line);padding:8px 0}"
            ".gemn-group summary{cursor:pointer;min-height:40px;display:flex;align-items:center;font-weight:700}"
            ".gemn-group ul{margin:4px 0;padding-left:22px}.gemn-group li{overflow-wrap:anywhere;margin:3px 0}"
            ".gemn-status-cell{white-space:nowrap;font-size:var(--t-caption)}.gemn-ok{color:var(--shell-accent,var(--c-accent-text))}"
            ".gemn-partial{color:var(--shell-warn,var(--c-warn-text))}.gemn-missing,.gemn-google-only,.gemn-unavailable{color:var(--shell-muted,var(--c-text-secondary))}"
            ".gemn-count{font-variant-numeric:tabular-nums}"
            ".gemn-dialog{color:var(--shell-ink);background:var(--shell-paper,var(--c-surface));border:1px solid var(--shell-line);"
            "border-radius:var(--r-md);max-width:min(850px,90vw);max-height:80vh;overflow:auto}"
            ".gemn-dialog::backdrop{background:var(--shell-overlay)}.gemn-close{float:right;font:inherit;padding:8px 16px;cursor:pointer}"
            "@media(max-width:899px){.gemn-dialog{display:none!important}}"
            "@media(min-width:900px){th.gemn-desktop.gemn-desktop,td.gemn-desktop.gemn-desktop{display:table-cell!important}"
            "col.gemn-column{display:table-column!important;width:170px}"
            ".gemn-summary.gemn-desktop.gemn-desktop{display:flex!important}"
            "div.gemn-groups.gemn-groups.gemn-desktop{display:block!important}.gemn-group summary{display:flex!important}}"
            "</style>")
