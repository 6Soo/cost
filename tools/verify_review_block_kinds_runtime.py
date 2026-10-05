"""Read-only local verification of the active review source and rendered UI.

Customer fields are checked in memory, never included in the evidence output.
Every browser request is intercepted locally. No session or database is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.checkout.resolve()))
    from webapp.contracts import sha256_bytes, sha256_text
    from webapp.review_context import build_review_context
    from webapp.real_review_ui import render_real_review_ui
    from playwright.sync_api import sync_playwright

    snapshot = (args.source_root / "snapshot.xlsx").read_bytes()
    review = (args.source_root / "review.csv").read_text(encoding="utf-8-sig")
    master = (args.source_root / "master.csv").read_text(encoding="utf-8-sig")
    model = build_review_context(snapshot, review, master, sha256_bytes(snapshot),
                                 sha256_text(review), sha256_text(master))
    rows = model["rows"]
    raw = {r["source_ref_snapshot_only"]: r for r in csv.DictReader(io.StringIO(review))}
    assert len(rows) == len(raw) == 1768
    assert {r["ref"] for r in rows} == set(raw)
    assert all(sorted(c["key"] for c in row["candidates"]) ==
               sorted(json.loads(raw[row["ref"]]["candidate_transaction_keys"]))
               for row in rows)
    counts = Counter(row["source"]["block_kind"] for row in rows)
    assert set(counts) == {"income", "expense", "unknown"}
    assert all(row.get("pipeline_recommendation") is None for row in rows
               if row["source"]["block_kind"] != "expense")
    target = next(r for r in rows if r["ref"].startswith("0302_") and
                  r["ref"].endswith("!B8|H8 (row 8)"))
    source = target["source"]
    assert source["block_kind"] == "income"
    assert source["customer_name"]
    assert source["income_components"]["예약금"] == "370000"
    assert [c["label"] for c in source["fieldcells"]] == [
        "거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
    binding = "|".join(model[key] for key in ("snapshotsha", "reviewsha", "mastersha"))
    state = {"binding": binding, "revision": 0, "choices": {}, "updated_at": "",
             "counts": {"total": len(rows), "held": len(rows), "selected": 0, "rejected": 0}}
    payload = {**model, "state": state}
    kind_by_ref = {r["ref"]: r["source"]["block_kind"] for r in rows}
    result = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "source_rows": len(rows), "block_counts": dict(counts),
              "all_refs_preserved": True, "all_candidate_keys_preserved": True,
              "income_and_unknown_recommendations": 0,
              "reported_income_fields_confirmed": True,
              "database_writes": 0, "browser_network": "fully_intercepted_local",
              "viewports": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (375, 1280):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                def route_request(route):
                    url = route.request.url
                    if "/api/review/model" in url:
                        body = state if "state_only" in url else payload
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
                    elif "/api/" in url:
                        route.fulfill(status=400, content_type="application/json", body='{"code":"READ_ONLY_CHECK"}')
                    else:
                        route.fulfill(status=200, content_type="text/html", body=render_real_review_ui())
                page.route("**/*", route_request)
                for kind in ("expense", "income", "unknown", "all"):
                    suffix = "" if kind == "expense" else "?kind=" + kind
                    page.goto("http://review.local.invalid/review" + suffix)
                    page.wait_for_function("window.__realReview && !window.__realReview.loading() && window.__realReview.rows() > 0")
                    cards = page.locator("#rows .card")
                    assert cards.count() == min(50, len(rows) if kind == "all" else counts[kind])
                    refs = cards.evaluate_all("cards => cards.map(card => card.getAttribute('data-ref'))")
                    assert kind == "all" or all(kind_by_ref[ref] == kind for ref in refs)
                    geometry = page.evaluate("({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})")
                    assert geometry["client"] == width and geometry["scroll"] == width
                    if kind == "income":
                        assert cards.locator("input[type=radio], .cand, fieldset").count() == 0
                page.select_option("#kind", "income")
                assert page.evaluate("window.__realReview.visibleRows()") == counts["income"]
                assert "kind=income" in page.url
                page.select_option("#kind", "unknown")
                assert page.evaluate("window.__realReview.visibleRows()") == counts["unknown"]
                page.select_option("#kind", "expense")
                assert page.evaluate("window.__realReview.visibleRows()") == counts["expense"]
                assert not page.evaluate("window.__realReview.isDirty()")
                assert "카드 지출 보류 " + str(counts["expense"]) + "건" in page.locator("#counts").inner_text()
                compact = page.locator("#rows .card").first
                compact_text = compact.inner_text()
                assert compact.get_attribute("data-ref") not in compact_text
                assert compact.locator(".review-evidence[open], .guidance-rule[open]").count() == 0
                assert compact.locator("textarea").count() == 1
                compact_height = compact.bounding_box()["height"]
                compact.locator(".guidance-rule > summary").click()
                assert page.evaluate("document.documentElement.scrollWidth") == width
                compact.locator(".guidance-rule > summary").click()
                page.goto("http://review.local.invalid/review?kind=income&q=" + quote(target["ref"]))
                page.wait_for_function("window.__realReview && !window.__realReview.loading() && window.__realReview.rows() > 0")
                card = page.locator("#rows .card")
                assert card.count() == 1
                assert source["customer_name"] in card.inner_text()
                assert "370,000원" in card.inner_text()
                assert "가맹점" not in card.inner_text()
                assert "<a href" not in card.inner_text()
                card.locator(".review-evidence > summary").click()
                table = card.locator("table.fields")
                assert table.locator("thead > tr").count() == 1
                assert table.locator("thead > tr > th").count() == 2
                assert table.locator("tr > tr").count() == 0
                assert table.locator("tbody > tr").count() == 7
                aligned = table.evaluate("table => {const h=[...table.tHead.rows[0].cells].map(c=>c.getBoundingClientRect()); const b=[...table.tBodies[0].rows[0].cells].map(c=>c.getBoundingClientRect()); return h.length===2 && b.length===2 && h.every((x,i)=>Math.abs(x.x-b[i].x)<1 && Math.abs(x.width-b[i].width)<1);}")
                assert aligned
                assert not errors
                result["viewports"].append({"width": width, "all_kind_filters_passed": True,
                    "income_has_no_card_choices": True, "kind_selector_changes_rows_and_url": True,
                    "card_decision_counts_exclude_income_and_unknown": True, "two_header_columns_aligned": True,
                    "compact_expense_height_px": compact_height, "source_details_collapsed_by_default": True,
                    "answer_and_rule_controls_present": True, "expanded_rule_controls_fit": True,
                    "horizontal_overflow": False, "page_errors": 0})
                page.close()
        finally:
            browser.close()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
