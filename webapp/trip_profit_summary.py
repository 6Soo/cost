"""모든 여행의 수입·지출·차액을 한 표로 보고 XLSX 한 시트로 내보낸다. 소유자 전용, 읽기만 한다.

숫자는 여행 화면 KPI와 `GET /api/tabs`가 쓰는 같은 투영에서 가져온다.
`board_read_projection.trip_totals`(= `ledger_board._trip_totals`)가 수입·지출·차액을 주고,
미결 건수는 `row_needs_review`·`row_has_conflict`가 정한다. 이 파일에는 집계식이 없다.

- 수입·지출·차액은 `GET /api/tabs`와 같은 투영 값이다. 이 파일에서 새로 더하거나 빼지 않는다.
  장부에 수입 행이 없으면 0원이 아니라 수입·차액 칸을 비우고 비고에 "수입 확인 필요"만 적는다.
- Google 검증을 통과한 수입(`get_trip_income_summary`의 `show_rows`)은 차액에 섞지 않고
  마지막 "Google 검증 수입(참고)" 열에 따로 보여 준다.
- Google 검증 여부는 동기화된 스냅샷과 여행 연결에서 읽는다. 스냅샷이 없으면 "확인 불가"라 쓴다.
- 내보내는 글자는 모두 `sheets_export.guard_text`를 거쳐 수식으로 읽히지 않게 한다.
- 이 모듈은 쓰지 않는다. 장부·Google·판정에 아무것도 기록하지 않는다.
"""
from __future__ import annotations

import io
from typing import Any, Callable, Iterable

PAGE_PATH = "/trips/profit"
EXPORT_PATH = "/trips/profit/export.xlsx"
ROUTES = (PAGE_PATH, EXPORT_PATH)

SHEET_NAME = "여행별 손익"
HEADER = ("여행", "기간", "수입(원)", "지출(원)", "차액(원)", "Google 검증", "미결 건수", "비고", "Google 검증 수입(참고)")
INCOME_UNKNOWN = "수입 확인 필요"

GOOGLE_VERIFIED = "검증됨"
GOOGLE_UNVERIFIED = "미검증"
GOOGLE_UNLINKED = "Google 연결 없음"
GOOGLE_UNAVAILABLE = "확인 불가"

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_FILENAME = "trip-profit-summary.xlsx"


def owns_route(path: str) -> bool:
    return path in ROUTES


def google_verification_by_tab() -> dict[str, bool] | None:
    """tab_id별 Google 검증 여부. 스냅샷을 읽을 수 없으면 None(판단하지 않는다)."""
    from app import google_authority
    from . import google_ledger_page as google

    if not google.enabled():
        return None
    try:
        path = google.snapshot_path()
        snapshot, _rows = google_authority.load_consistent(path, google.rows_path())
        mapping = google.load_mapping(path)
        payload = google.owner_payload(google.snapshot_for_display(snapshot), google.load_choices(path))
    except (OSError, ValueError, KeyError, TypeError, google_authority.SnapshotError):
        return None
    verified_by_key = {t.get("key"): bool(t.get("verified")) for t in payload.get("trips", [])}
    keys_by_tab: dict[str, list[str]] = {}
    for key, tab_id in (mapping or {}).items():
        if tab_id:
            keys_by_tab.setdefault(str(tab_id), []).append(key)
    # 한 여행이 둘 이상의 Google 탭에 연결돼 있으면 모두 검증돼야 검증됨이다.
    return {tab_id: all(verified_by_key.get(key, False) for key in keys)
            for tab_id, keys in keys_by_tab.items()}


def _google_label(tab_id: str, google: dict[str, bool] | None) -> str:
    if google is None:
        return GOOGLE_UNAVAILABLE
    if tab_id not in google:
        return GOOGLE_UNLINKED
    return GOOGLE_VERIFIED if google[tab_id] else GOOGLE_UNVERIFIED


def period_text(trip: dict) -> str:
    start = str(trip.get("starts_on") or "")
    end = str(trip.get("ends_on") or "")
    return f"{start}~{end}" if end else start


def _no_google_income(_tab_id: str):
    return None


def build_rows(*, store: Any, trips: Iterable[dict], totals_fn: Callable[[str], dict],
               review_fn: Callable[[dict], bool], conflict_fn: Callable[[dict], bool],
               google: dict[str, bool] | None,
               google_income_fn: Callable[[str], dict | None] = _no_google_income) -> list[dict]:
    """여행마다 한 행. 숫자는 totals_fn(투영)이 준 값을 그대로 쓴다."""
    out = []
    selected = [t for t in trips
                if not t.get("deleted") and (t.get("tab_kind") or "trip") == "trip"]
    selected.sort(key=lambda t: (str(t.get("starts_on") or ""), str(t.get("display_key") or "")), reverse=True)
    for trip in selected:
        tab_id = trip["tab_id"]
        totals = totals_fn(tab_id)
        rows = store.list_tab_rows(tab_id) if store is not None else []
        income_rows = sum(1 for r in rows if r.get("row_kind") == "income")
        expense_rows = len(rows) - income_rows
        open_rows = sum(1 for r in rows if review_fn(r) or conflict_fn(r))
        income = totals["income"] if income_rows > 0 else None
        summary = google_income_fn(tab_id)
        google_income = (int(summary.get("amount") or 0)
                         if summary and summary.get("show_rows") else None)
        notes = []
        if income is None:
            notes.append(INCOME_UNKNOWN)
        if trip.get("archived"):
            notes.append("보관됨")
        out.append({
            "tab_id": tab_id,
            "trip": str(trip.get("display_key") or tab_id),
            "period": period_text(trip),
            "income": income,
            "expense": totals["expense"],
            "profit": totals["profit"] if income is not None else None,
            "google_income": google_income,
            "google": _google_label(tab_id, google),
            "open_rows": open_rows,
            "income_rows": income_rows,
            "expense_rows": expense_rows,
            "note": " · ".join(notes),
        })
    return out


def table_cells(row: dict) -> list:
    """표의 한 행. 숫자는 숫자로, 비어야 할 칸은 None으로 둔다."""
    return [row["trip"], row["period"], row["income"], row["expense"], row["profit"],
            row["google"], row["open_rows"], row["note"], row["google_income"]]


def build_xlsx(rows: list[dict]) -> bytes:
    """한 시트 XLSX. 글자 칸은 모두 guard_text를 거친다."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from .sheets_export import guard_text

    book = Workbook()
    sheet = book.active
    sheet.title = SHEET_NAME
    sheet.append([guard_text(name) for name in HEADER])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = []
        for value in table_cells(row):
            values.append(guard_text(value) if isinstance(value, str) else value)
        sheet.append(values)
    for letter, width in zip("ABCDEFGHI", (28, 24, 16, 16, 16, 18, 12, 22, 22)):
        sheet.column_dimensions[letter].width = width
    for line in sheet.iter_rows(min_row=2, min_col=3, max_col=5):
        for cell in line:
            cell.number_format = "#,##0"
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _money(value) -> str:
    return "" if value is None else f"{int(value):,}"


def render_body(rows: list[dict]) -> str:
    from .board_render_helpers import esc

    head = "".join(f"<th>{esc(name)}</th>" for name in HEADER)
    lines = []
    for row in rows:
        lines.append(
            "<tr>"
            f"<td><a href='/board?tab={esc(row['tab_id'])}'>{esc(row['trip'])}</a></td>"
            f"<td>{esc(row['period'])}</td>"
            f"<td class='num'>{esc(_money(row['income']))}</td>"
            f"<td class='num'>{esc(_money(row['expense']))}</td>"
            f"<td class='num'>{esc(_money(row['profit']))}</td>"
            f"<td>{esc(row['google'])}</td>"
            f"<td class='num'>{row['open_rows']}</td>"
            f"<td>{esc(row['note'])}</td>"
            f"<td class='num'>{esc(_money(row['google_income']))}</td>"
            "</tr>")
    table = (f"<div class='scrollx'><table><thead><tr>{head}</tr></thead>"
             f"<tbody>{''.join(lines)}</tbody></table></div>"
             if lines else "<p class='muted'>표시할 여행이 없습니다.</p>")
    return (
        "<section class='sect'><h2>여행별 손익</h2>"
        "<p class='muted'>수입·지출·차액은 장부 화면과 같은 값입니다. 장부에 수입 행이 없으면 "
        "0원이 아니라 빈 칸이며 수입 확인 필요로 표시합니다. Google 검증 수입은 차액에 섞지 않고 "
        "마지막 열에 따로 보입니다. 미결 건수는 판정이 끝나지 않았거나 충돌로 기록된 행 수입니다.</p>"
        f"<p><a class='btn primary' href='{EXPORT_PATH}'>XLSX 내보내기</a> "
        "<a href='/trips'>여행 관리</a></p>"
        f"{table}</section>")


def dispatch(handler, parsed, *, is_owner: bool, store: Any = None, trips: Iterable[dict] | None = None,
             totals_fn: Callable[[str], dict] | None = None, google: Any = "default",
             google_income_fn: Callable[[str], dict | None] | None = None) -> bool:
    """GET만 받는다. 소유자가 아니면 아무것도 읽지 않고 거부한다."""
    if not owns_route(parsed.path):
        return False
    if not is_owner:
        handler._send_json({"code": "OWNER_ONLY", "message": "소유자만 볼 수 있습니다"}, 403)
        return True
    if str(getattr(handler, "command", "GET")).upper() != "GET":
        handler._send_json({"code": "METHOD_NOT_ALLOWED", "message": "조회만 할 수 있습니다"}, 405)
        return True
    from . import ledger_board as board

    if google_income_fn is None:
        from .google_ledger_page import get_trip_income_summary as google_income_fn
    store = store if store is not None else board._active_store()
    if store is None:
        handler._send_json({"code": "STORE_UNBOUND", "message": "저장소가 연결되지 않았어요"}, 503)
        return True
    rows = build_rows(
        store=store,
        trips=trips if trips is not None else board.live_trips(include_archived=True),
        totals_fn=totals_fn or board._trip_totals,
        review_fn=board.row_needs_review,
        conflict_fn=board.row_has_conflict,
        google=google_verification_by_tab() if google == "default" else google,
        google_income_fn=google_income_fn)
    if parsed.path == EXPORT_PATH:
        data = build_xlsx(rows)
        handler.send_response(200)
        handler.send_header("Content-Type", XLSX_TYPE)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Content-Disposition", f'attachment; filename="{EXPORT_FILENAME}"')
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    from . import ledger_design

    handler._send(ledger_design.render(ledger_design.shell(
        "여행별 손익", tab_id="", heading="여행별 손익", body=render_body(rows))))
    return True
