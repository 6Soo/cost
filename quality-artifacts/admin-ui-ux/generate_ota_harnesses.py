"""Render real OTA catalog UI in state and long-content scratch harnesses."""
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from webapp import ota_catalog, site_shell
from webapp.ledger_store import LedgerStore
from webapp.tests.test_ota_catalog import source_database


OUT = Path(__file__).resolve().parent
WORK = OUT / "synthetic"
WORK.mkdir(exist_ok=True)
for generated in ("board.sqlite", "board.sqlite-shm", "board.sqlite-wal",
                 "ota.sqlite", "empty-ota.sqlite"):
    (WORK / generated).unlink(missing_ok=True)
board = LedgerStore(WORK / "board.sqlite", seed_demo=False)
source = WORK / "ota.sqlite"
source_database(source)
sources = {"portal_databases": [source], "mail_directories": [], "missing": []}
rows_data = ota_catalog.catalog(board, {}, sources=sources)
empty_source = WORK / "empty-ota.sqlite"
connection = sqlite3.connect(empty_source)
connection.executescript("""
CREATE TABLE bookings(id INTEGER PRIMARY KEY, provider TEXT, booking_number TEXT,
  product_type TEXT, label TEXT, service_start_on TEXT, service_end_on TEXT, status TEXT);
CREATE TABLE allocation_targets(id INTEGER PRIMARY KEY, target_type TEXT, code TEXT, name TEXT);
CREATE TABLE booking_target_links(booking_id INTEGER, target_id INTEGER, link_status TEXT);
""")
connection.close()
empty_data = ota_catalog.catalog(
    board, {}, sources={"portal_databases": [empty_source], "mail_directories": [], "missing": []})


def full_page(data, query=None):
    document = ota_catalog.render_html(data, query or {})
    return site_shell.wrap_document(document, "/ota").replace(
        "<head>", "<head><base href='http://127.0.0.1:8876/'>", 1)


def state_document(label, data, query=None):
    return full_page(data, query)


states = []
loading = deepcopy(empty_data)
loading["refresh_state"] = "refreshing"
states.append(("불러오는 중", loading, {}))
failed = deepcopy(empty_data)
failed["refresh_state"] = "failed"
states.append(("불러오기 실패", failed, {}))
states.append(("자료 없음", deepcopy(empty_data), {}))
filtered_empty = deepcopy(rows_data)
filtered_empty["rows"] = []
filtered_empty["total"] = 0
states.append(("검색 결과 없음", filtered_empty, {"q": ["no-match-synthetic"]}))
states.append(("예약 목록", deepcopy(rows_data), {}))
stale = deepcopy(rows_data)
stale["refresh_state"] = "refreshing"
states.append(("이전 자료 표시", stale, {}))


def switcher(title, items, *, mode):
    labels = "".join(
        f'<button type="button" data-view="v{i}" aria-pressed="{"true" if i == 0 else "false"}">{escape(label)}</button>'
        for i, (label, _, _) in enumerate(items)
    )
    frames = "".join(
        f'<section data-panel="v{i}"{" hidden" if i else ""}><p>{escape(label)}</p>'
        f'<iframe title="{escape(label)}" srcdoc="{escape(state_document(label, data, query), quote=True)}"></iframe></section>'
        for i, (label, data, query) in enumerate(items)
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>body{{font:14px system-ui;margin:16px}}nav{{display:flex;gap:8px;flex-wrap:wrap}}button{{min-height:40px;padding:8px 12px}}section[hidden]{{display:none}}iframe{{display:block;width:100%;height:720px;border:1px solid #aaa}}.scenarios{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}.scenarios iframe{{height:760px}}</style>
</head><body><h1>{escape(title)}</h1><p>{escape(mode)}</p><nav aria-label="표시할 상태">{labels}</nav>{frames}
<script>document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.view);document.querySelectorAll('[data-view]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));}}));</script></body></html>"""


(OUT / "ota-state-machine.html").write_text(
    switcher("OTA 예약 목록 상태 확인", states,
             mode="OTA 카탈로그 표 · 실제 render_html 출력 · 격리 합성 자료 · 상태: loading, failed, empty, filtered-empty, populated, stale-refresh"),
    encoding="utf-8")

long_data = deepcopy(rows_data)
long_row = deepcopy(rows_data["rows"][0])
long_row["booking_ref"] = "SYNTHETIC-" + "REFERENCE-" * 14
long_row["booking_ref_display"] = long_row["booking_ref"]
long_row["label"] = "합성 장기 예약 설명 " + "가나다라마바사 " * 18
long_row["trips"] = [{"name": "합성 긴 여행 이름 " + "여행 " * 20, "source": "period",
                      "confidence": "낮음", "basis": "합성 일정 근거 " + "확인 " * 16}]
long_data["rows"] = [long_row] * 8
long_data["total"] = 8
long_data["all_count"] = 8
long_data["pages"] = 1
break_widths = (320, 390, 760)
break_scenarios = "".join(
    f'<section><p>{width}px · 합성 긴 예약번호·내용·여행 이름 · 8행</p>'
    f'<iframe title="{width}px 긴 내용" style="width:{width}px;max-width:100%" '
    f'srcdoc="{escape(state_document("긴 예약 내용", long_data), quote=True)}"></iframe></section>'
    for width in break_widths
)
(OUT / "ota-break.html").write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OTA 표 긴 내용 확인</title>
<style>body{{font:14px system-ui;margin:16px}}section{{margin:16px 0}}iframe{{display:block;height:760px;border:1px solid #aaa}}</style>
</head><body><h1>OTA 예약 표 긴 내용 스트레스 확인</h1>
<p>한 컴포넌트: 실제 OTA 카탈로그 예약 표. 실제 OTA 렌더러·CSS를 사용하고 합성 긴 예약번호·설명·여행 이름과 8개 행을 공급합니다.</p>
{break_scenarios}</body></html>""", encoding="utf-8")
board.close()
