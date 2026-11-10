"""Small HTML helpers for the shared COST UI components.

The helpers escape every value that is text or an attribute.  ``*_html``
arguments are deliberately treated as already-rendered component markup so
callers can compose existing forms and buttons without changing their fields.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from typing import Any


def _text(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _attr(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _items(values: Iterable[Any]) -> list[Any]:
    return list(values or ())


def _pair(item: Any, *, label_key: str = "label", value_key: str = "value") -> tuple[Any, Any]:
    if isinstance(item, Mapping):
        return item.get(label_key, item.get("title", "")), item.get(value_key, item.get("id", ""))
    if isinstance(item, (tuple, list)):
        if len(item) >= 2:
            return item[0], item[1]
        if item:
            return item[0], item[0]
    return item, item


def _slug(value: Any) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "field")).strip("-").lower()
    return raw or "field"


def _control_id(control_html: str, label: str) -> tuple[str, str]:
    match = re.search(r"\bid\s*=\s*(['\"])([^'\"]+)\1", control_html)
    if match:
        return match.group(2), control_html
    control_id = _slug(label)
    injected = re.sub(r"(<(?:input|select|textarea)\b)", rf'\1 id="{_attr(control_id)}"', control_html, count=1, flags=re.I)
    return control_id, injected


def page_header(title: str, meta: str = "", actions: str = "", breadcrumb: Iterable[Any] = ()) -> str:
    crumbs = []
    for item in _items(breadcrumb):
        if isinstance(item, Mapping):
            label = item.get("label", item.get("title", ""))
            href = item.get("href", "")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            label, href = item[0], item[1]
        else:
            label, href = item, ""
        content = f'<a href="{_attr(href)}">{_text(label)}</a>' if href else _text(label)
        crumbs.append(f"<li>{content}</li>")
    nav = f'<nav class="breadcrumb" aria-label="위치"><ol>{"".join(crumbs)}</ol></nav>'
    action_html = f'<div class="ph-actions">{actions}</div>' if actions else ""
    meta_html = f'<p class="ph-meta">{_text(meta)}</p>' if meta else ""
    return f'<header class="page-header">{nav}<div class="ph-row"><h1>{_text(title)}</h1>{action_html}</div>{meta_html}</header>'


def section_tabs(items: Iterable[Any], current: str = "") -> str:
    links = []
    for item in _items(items):
        if isinstance(item, Mapping):
            label = item.get("label", item.get("title", ""))
            href = item.get("href", item.get("value", ""))
            key = item.get("key", href)
        else:
            label, href = _pair(item)
            key = href
        current_attr = ' aria-current="page"' if str(key) == str(current) else ""
        links.append(f'<a href="{_attr(href)}"{current_attr}>{_text(label)}</a>')
    return f'<nav class="section-tabs" aria-label="섹션">{"".join(links)}</nav>'


def view_tabs(items: Iterable[Any]) -> str:
    buttons: list[str] = []
    panels: list[str] = []
    first = True
    for index, item in enumerate(_items(items)):
        if isinstance(item, Mapping):
            label = item.get("label", item.get("title", ""))
            panel_id = item.get("id", f"view-panel-{index + 1}")
            content = item.get("content", "")
            selected = bool(item.get("selected", first))
        elif isinstance(item, (tuple, list)):
            label = item[0] if item else ""
            panel_id = item[1] if len(item) > 1 else f"view-panel-{index + 1}"
            content = item[2] if len(item) > 2 else ""
            selected = first
        else:
            label, panel_id, content, selected = item, f"view-panel-{index + 1}", "", first
        first = False
        selected_attr = "true" if selected else "false"
        hidden = "" if selected else " hidden"
        buttons.append(f'<button type="button" role="tab" aria-selected="{selected_attr}" aria-controls="{_attr(panel_id)}">{_text(label)}</button>')
        panels.append(f'<section id="{_attr(panel_id)}" role="tabpanel"{hidden}>{content}</section>')
    return f'<div class="view-tabs"><div role="tablist">{"".join(buttons)}</div>{"".join(panels)}</div>'


def filter_bar(fields: Iterable[Any], submit_label: str = "조회", reset_href: str = "") -> str:
    rendered = []
    for item in _items(fields):
        if isinstance(item, Mapping):
            label = item.get("label", "")
            control = item.get("control_html", item.get("control", ""))
            hint = item.get("hint", "")
        elif isinstance(item, (tuple, list)):
            values = list(item)
            label = values[0] if values else ""
            control = values[1] if len(values) > 1 else ""
            hint = values[2] if len(values) > 2 else ""
        else:
            label, control, hint = "", item, ""
        rendered.append(field(label, control, hint=hint))
    reset = f'<a class="btn ghost" href="{_attr(reset_href)}">초기화</a>' if reset_href else ""
    return f'<form class="filter-bar" role="search" method="get">{"".join(rendered)}<button class="btn primary" type="submit">{_text(submit_label)}</button>{reset}</form>'


def field(label: str, control_html: str, hint: str = "", error: str = "") -> str:
    control_id, control = _control_id(str(control_html), str(label))
    described: list[str] = []
    hint_html = ""
    if hint:
        hint_id = f"{control_id}-hint"
        described.append(hint_id)
        hint_html = f'<p class="hint" id="{_attr(hint_id)}">{_text(hint)}</p>'
    error_html = ""
    if error:
        error_id = f"{control_id}-error"
        described.append(error_id)
        error_html = f'<p class="error" id="{_attr(error_id)}" role="alert">{_text(error)}</p>'
    if described:
        control = re.sub(r"(<(?:input|select|textarea)\b)", rf'\1 aria-describedby="{_attr(" ".join(described))}"', control, count=1, flags=re.I)
    if error:
        control = re.sub(r"(<(?:input|select|textarea)\b)", r'\1 aria-invalid="true"', control, count=1, flags=re.I)
    return f'<div class="field"><label for="{_attr(control_id)}">{_text(label)}</label>{control}{hint_html}{error_html}</div>'


def chip(text: str, tone: str = "neutral") -> str:
    tone_name = tone if tone in {"neutral", "accent", "warn", "danger"} else "neutral"
    suffix = "" if tone_name == "neutral" else f" chip-{tone_name}"
    return f'<span class="chip{suffix}">{_text(text)}</span>'


def list_row(primary: str, amount: str, secondary: str, href_or_button: Any) -> str:
    if isinstance(href_or_button, Mapping):
        tag = href_or_button.get("tag", "a")
        target = href_or_button.get("href", href_or_button.get("action", ""))
    elif isinstance(href_or_button, (tuple, list)) and len(href_or_button) >= 2:
        tag, target = href_or_button[0], href_or_button[1]
    else:
        tag, target = "a", href_or_button
    if str(tag).lower() == "button":
        hit = f'<button type="button" class="lr-hit">'
        end = "</button>"
    else:
        hit = f'<a class="lr-hit" href="{_attr(target)}">'
        end = "</a>"
    return f'<li class="list-row">{hit}<span class="lr-primary">{_text(primary)}</span><span class="lr-amount">{_text(amount)}</span><span class="lr-secondary">{_text(secondary)}</span>{end}</li>'


def kpi(label: str, value: str, note: str = "") -> str:
    note_html = f'<small>{_text(note)}</small>' if note else ""
    return f'<div class="kpi"><dt>{_text(label)}</dt><dd>{_text(value)}</dd>{note_html}</div>'


def empty_state(title: str, body: str = "", action: str = "") -> str:
    body_html = f"<p>{_text(body)}</p>" if body else ""
    return f'<div class="empty-state"><p class="es-title">{_text(title)}</p>{body_html}{action}</div>'


def notice(text: str, tone: str = "neutral") -> str:
    tone_name = tone if tone in {"neutral", "warn", "danger"} else "neutral"
    role = "alert" if tone_name == "danger" else "status"
    suffix = "" if tone_name == "neutral" else f" notice-{tone_name}"
    return f'<div class="notice{suffix}" role="{role}">{_text(text)}</div>'


def drawer(id: str, title: str, body: str) -> str:
    title_id = f"{_slug(id)}-title"
    return (f'<dialog class="drawer" id="{_attr(id)}" aria-labelledby="{_attr(title_id)}">'
            f'<div class="drawer-header"><h2 id="{_attr(title_id)}">{_text(title)}</h2>'
            f'<button class="icon-btn" type="button" data-drawer-close aria-label="닫기">×</button></div>'
            f'<div class="drawer-body">{body}</div></dialog>')


def file_drop(name: str, accept: str = "", multiple: bool = False, label: str = "파일 선택") -> str:
    multiple_attr = " multiple" if multiple else ""
    accept_attr = f' accept="{_attr(accept)}"' if accept else ""
    return (f'<label class="file-drop">{_text(label)}'
            f'<input class="sr-only-focusable" type="file" name="{_attr(name)}"{accept_attr}{multiple_attr}>'
            '<ul aria-live="polite"></ul></label>')


def steps(items: Iterable[Any]) -> str:
    rows = []
    for item in _items(items):
        if isinstance(item, Mapping):
            label = item.get("label", item.get("title", ""))
            state = item.get("state", "todo")
            note = item.get("note", "")
            href = item.get("href", "")
        elif isinstance(item, (tuple, list)):
            label = item[0] if item else ""
            state = item[1] if len(item) > 1 else "todo"
            note = item[2] if len(item) > 2 else ""
            href = item[3] if len(item) > 3 else ""
        else:
            label, state, note, href = item, "todo", "", ""
        label_html = f'<a href="{_attr(href)}">{_text(label)}</a>' if href else _text(label)
        note_html = f'<span class="step-note">{_text(note)}</span>' if note else ""
        # Completion is stated in words, never by colour alone.
        done_html = '<span class="step-state">완료</span>' if state == "done" else ""
        rows.append(f'<li data-state="{_attr(state)}">{label_html}{done_html}{note_html}</li>')
    return f'<ol class="steps">{"".join(rows)}</ol>'


__all__ = [
    "page_header", "section_tabs", "view_tabs", "filter_bar", "field",
    "chip", "list_row", "kpi", "empty_state", "notice", "drawer",
    "file_drop", "steps",
]
