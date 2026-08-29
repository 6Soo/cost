from __future__ import annotations

import html
import secrets


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def layout(title: str, body: str, gate_banner: str = "") -> str:
    banner = f'<div class="banner">{esc(gate_banner)}</div>' if gate_banner else ""
    nav = (
        '<nav><a href="/">KPI</a> <a href="/queue">큐</a> '
        '<a href="/gates">게이트</a> <a href="/history">원장</a> '
        '<a href="/propose">제안</a></nav>'
    )
    style = (
        "<style>body{font-family:'Malgun Gothic',sans-serif;margin:16px}"
        "nav a{margin-right:12px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px;text-align:left}"
        ".banner{background:#eef;padding:6px 10px;margin-bottom:8px;font-size:13px}"
        ".badge{display:inline-block;padding:1px 6px;border-radius:8px;"
        "background:#dde;font-size:12px}.pass{background:#cfc}.fail{background:#fcc}"
        ".warn{background:#fec}form label{display:block;margin-top:8px}</style>"
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}"
        f"</title>{style}</head><body>{nav}{banner}{body}</body></html>"
    )


def status_badge(value) -> str:
    text = esc("PASS" if value is True else "FAIL" if value is False else value)
    cls = "pass" if value is True else "fail" if value is False else ""
    return f"<span class='badge {cls}'>{text}</span>"


def kpi_page(summary: dict) -> str:
    body = (
        f"<h2>KPI</h2><p>payments: {summary['payments']['count']} / "
        f"sum_krw: {summary['payments']['sum_krw']:,} / "
        f"integrity: {esc(summary['integrity'])} / "
        f"ro_unchanged: {status_badge(summary['ro_unchanged'])}</p>"
    )
    return layout("cost webapp KPI", body)


def queue_page(rows, filters: str = "") -> str:
    trs = "".join(
        f"<tr><td>{esc(r.get('occurred_on'))}</td>"
        f"<td>{esc(r.get('card4'))}</td><td>{esc(r.get('merchant'))}</td>"
        f"<td class='num'>{int(r.get('amount_krw') or 0):,}</td>"
        f"<td><a href='/detail?key={esc(r.get('event_key') or r.get('rowid'))}'"
        f">상세</a></td></tr>"
        for r in rows
    )
    body = (
        f"<h2>잔여 큐 ({len(rows)})</h2><p>{esc(filters)}</p>"
        f"<table><tr><th>결제일</th><th>카드</th><th>가맹점</th>"
        f"<th>금액(KRW)</th><th></th></tr>{trs}</table>"
    )
    return layout("queue", body)


def detail_page(row, decisions) -> str:
    items = "".join(f"<li>{esc(k)}: {esc(v)}</li>" for k, v in row.items())
    dec_rows = "".join(
        f"<tr><td>{esc(d.get('account'))}</td><td>{esc(d.get('cost_type'))}</td>"
        f"<td>{esc(d.get('allocation_target'))}</td>"
        f"<td>{esc(d.get('vat_tag'))}</td></tr>"
        for d in decisions
    )
    body = (
        f"<h2>건별 상세</h2><ul>{items}</ul>"
        f"<h3>현재 분류</h3><table><tr><th>account</th><th>cost_type</th>"
        f"<th>allocation_target</th><th>vat_tag</th></tr>{dec_rows}</table>"
        f"<p><a href='/propose'>이 건에 대한 제안 만들기</a></p>"
    )
    return layout("detail", body)


def gates_page(gates) -> str:
    trs = "".join(
        f"<tr><td>{esc(g['gate'])}</td><td>{status_badge(g.get('status'))}</td>"
        f"<td>{esc(g.get('detail'))}</td></tr>"
        for g in gates
    )
    body = (
        f"<h2>게이트 상태보드</h2>"
        f"<table><tr><th>gate</th><th>판정</th><th>비고</th></tr>{trs}</table>"
    )
    return layout("gates", body)


def propose_form_page(csrf_token: str, streams_hint: str = "") -> str:
    cost_options = "".join(
        f"<option value='{esc(v)}'>{esc(v)}</option>" for v in ("여행원가", "판관비")
    )
    body = (
        "<h2>shadow 제안</h2>"
        "<form method='post' action='/api/propose'>"
        f"<input type='hidden' name='csrftoken' value='{esc(csrf_token)}'/>"
        f"<label>stream_id<input name='stream_id' required placeholder={esc(streams_hint or 'payment event key')} /></label>"
        "<label>target_direct_event_key<input name='target_direct_event_key'/></label>"
        "<label>expected_source_sha256<input name='expected_source_sha256'/></label>"
        f"<label>cost_type<select name='cost_type'>{cost_options}</select></label>"
        "<label>account<input name='account' required/></label>"
        "<label>allocation_target<input name='allocation_target'/></label>"
        "<label>vat_tag<input name='vat_tag'/>(선택 — 제외축)</label>"
        "<label>rationale<textarea name='rationale' required></textarea></label>"
        "<button type='submit'>제안 기록</button></form>"
    )
    return layout("propose", body)


def history_page(events, materialized: dict) -> str:
    trs = "".join(
        f"<tr><td>{esc(e['stream_id'])}</td><td>{e['sequence_no']}</td>"
        f"<td>{esc(e['action'])}</td><td>{esc((e['event_id'] or '')[:12])}</td>"
        f"<td>{esc((e['prev_event_hash'] or '')[:10])}</td>"
        f"<td>{esc(e['rationale'][:40])}</td></tr>"
        for e in events
    )
    active = len(materialized.get("active", {}))
    resolved = len(materialized.get("resolved_out", []))
    body = (
        f"<h2>결정원장 이력</h2><p>streams active={active} resolved_out={resolved}"
        "</p><table><tr><th>stream</th><th>seq</th><th>action</th>"
        f"<th>event_id</th><th>prev</th><th>rationale</th></tr>{trs}</table>"
    )
    return layout("history", body)


def preview_page(diff: dict) -> str:
    trs = "".join(
        f"<tr><td>{esc(c['key'])}</td>"
        f"<td>{esc(c['as_is'].get('axes') if isinstance(c['as_is'], dict) else c['as_is'])}</td>"
        f"<td>{esc(c['to_be'].get('axes') if isinstance(c['to_be'], dict) else c['to_be'])}</td></tr>"
        for c in diff["changes"]
    )
    body = (
        f"<h2>replay preview (shadow)</h2>"
        f"<p>변경 {diff['changed_count']}건 — 운영 DB에는 영향 없음</p>"
        f"<table><tr><th>key</th><th>AS-IS</th><th>TO-BE</th></tr>{trs}</table>"
    )
    return layout("preview", body)


def new_csrf_token() -> str:
    return secrets.token_hex(16)
