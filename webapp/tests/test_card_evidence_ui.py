"""Independent targeted tests for webapp.card_evidence_ui.

Verifies pure HTML presentation:
- Pure inputs only (no database connections, no board objects, no financial judgments)
- Complete coverage of OTA snapshot evidence, catalog blocks, and refund evidence
- Security against XSS via strict HTML escaping
- Behavioral and HTML equivalence between card_flow wrappers and card_evidence_ui
"""
import html
import pytest

from webapp import card_evidence_ui, card_flow
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


def test_refund_merchant_key_distinguishes_taxi_from_other_kakao_services():
    """Kakao taxi aliases group together; pay, proxy, bike, parking remain distinct."""
    assert card_evidence_ui.refund_merchant_key("카카오T_택시") == "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오택시") == "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오T(일반택시)") == "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오모빌리티 일반택시") == "카카오택시"
    assert card_evidence_ui.refund_merchant_key("KakaoT") == "카카오택시"

    # Must NOT group into taxi
    assert card_evidence_ui.refund_merchant_key("카카오페이") != "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오대리") != "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오모빌리티(주차)") != "카카오택시"
    assert card_evidence_ui.refund_merchant_key("카카오모빌리티-바이크") != "카카오택시"


def test_render_ota_snapshot_evidence_all_statuses_and_escaping():
    """All status tones and protected hints render safely with escaping."""
    unsafe_note = "<script>alert('xss')</script>"
    entry = {
        "ota_status": "GROUP_RECONCILED",
        "ota_notes": [unsafe_note, "동일 카드 2건 경합"],
        "snapshot": {"fresh": True, "status": "ready"},
    }
    rendered = card_evidence_ui.render_ota_snapshot_evidence(entry, "TX123")
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in rendered or html.escape(unsafe_note) in rendered
    assert "cleanup-ota-badge-warn" in rendered
    assert "그룹 대응 (개별 미확정)" in rendered
    assert "최신 예약 자료 확인" in rendered
    assert "개별 예약↔카드 연결 미확정 · 장부 기록은 금융 검증 후 허용" in rendered

    # Stale / refreshing statuses
    entry_stale = {
        "ota_status": "RESERVATION_NEEDS_REVIEW",
        "ota_notes": [],
        "snapshot": {"fresh": False, "status": "refreshing"},
    }
    rendered_stale = card_evidence_ui.render_ota_snapshot_evidence(entry_stale)
    assert "예약 근거 갱신 중..." in rendered_stale
    assert "예약 관계만 확인됨 · 결제 검증 별도 · 사용자 재확인 필요" in rendered_stale


def test_render_catalog_block_structure_and_escaping():
    """Catalog block renders booking ref, period, candidate tabs, and cancelled counts."""
    entry = {
        "provider": "Agoda",
        "booking_ref": "AG1234<safe>",
        "status": "CONFIRMED",
        "period": "2026-10-01 ~ 2026-10-05",
        "candidates": [
            {"display_key": "2026_tokyo", "relation": "covers"},
            {"tab_id": "2026_osaka", "relation": "overlaps"},
        ],
        "cancelled_matches": 1,
    }
    rendered = card_evidence_ui.render_catalog_block(entry)
    assert "Agoda 예약 자료" in rendered
    assert "AG1234&lt;safe&gt;" in rendered
    assert "이용 2026-10-01 ~ 2026-10-05" in rendered
    assert "후보 여행: 2026_tokyo(전체 포함), 2026_osaka(일부 겹침)" in rendered
    assert "취소 결제 1건" in rendered


def test_render_no_booking_evidence_conditions():
    """Missing evidence messages depend strictly on fresh flag and source/ota predicate."""
    # When not needed, returns empty
    assert card_evidence_ui.render_no_booking_evidence(fresh=True, source="normal", is_ota=False) == ""

    # When booking evidence needed and fresh
    fresh_msg = card_evidence_ui.render_no_booking_evidence(fresh=True, source="booking_evidence_needed", is_ota=False)
    assert "이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다" in fresh_msg
    assert "카드 결제일만으로는 여행을 정할 수 없습니다." in fresh_msg

    # When not fresh
    stale_msg = card_evidence_ui.render_no_booking_evidence(fresh=False, source="booking_evidence_needed", is_ota=False)
    assert "현재 예약 자료를 확인할 수 없어 예약 부재 여부를 판단하지 않았습니다." in stale_msg


def test_render_refund_merchant_candidates_pure_view():
    """Pure rendering without database connection or board globals."""
    refund_tuple = ("KB국민", "1234", "카카오T택시", "2026-10-02", -24600, "9999", "1111")
    candidates = [
        ("orig-1", "b1", "카카오택시", "2026-10-02", 24600, "1111", None, "", ""),
        ("orig-2", "b1", "카카오택시", "2026-10-01", 15000, "2222", "dup-id", "", ""),
    ]
    inventory = [
        {"merchant": "카카오택시", "direction": "purchase", "count": 10, "family": "카카오택시"},
        {"merchant": "카카오페이", "direction": "purchase", "count": 5, "family": "카카오페이"},
    ]
    existing = {"orig-1"}

    rendered = card_evidence_ui.render_refund_merchant_candidates(
        refund=refund_tuple,
        candidates=candidates,
        count=2,
        existing_ledger_ids=existing,
        kakao_inventory=inventory,
    )

    assert "카카오T 택시 가맹점 표기 대조" in rendered
    assert "택시 10건 / 기타 5건" in rendered
    assert "원승인번호 일치 · 확정 연결은 별도 검증" in rendered
    assert "장부 기록 있음" in rendered
    assert "중복·원본 오류" in rendered
    assert "장부 미기록" in rendered


def test_render_refund_evidence_pure_view():
    """Pure refund evidence block wrapping title and lines."""
    title = "원결제 추론 연결 · 장부 기록 보류 (환급 완료 아님)"
    lines = ["전액 상쇄", "원승인번호 기준 원결제 확정 연결 · 취소/환불 1건", "원결제 10,000원 · 환불 합계 -10,000원"]
    comparison = "<div class='test-cmp'>대조표</div>"

    rendered = card_evidence_ui.render_refund_evidence(
        title=title,
        lines=lines,
        comparison_html=comparison,
    )

    assert title in rendered
    for line in lines:
        assert f"<li>{html.escape(line)}</li>" in rendered
    assert "<div class='test-cmp'>대조표</div>" in rendered


def test_card_flow_wrappers_identical_to_direct_calls(tmp_path):
    """Calling card_flow wrappers produces identical HTML to direct calls."""
    entry = {
        "ota_status": "EXACT",
        "ota_notes": ["자동 연결 완료"],
        "snapshot": {"fresh": True, "status": "ready"},
    }
    assert card_flow._render_ota_snapshot_evidence(entry, "tx1") == card_evidence_ui.render_ota_snapshot_evidence(entry, "tx1")

    cat_entry = {
        "provider": "Booking.com",
        "booking_ref": "BK888",
        "status": "OK",
        "candidates": [],
    }
    assert card_flow._catalog_block(cat_entry) == card_evidence_ui.render_catalog_block(cat_entry)


def test_render_refund_evidence_contract_preservation_with_store(tmp_path):
    """End-to-end integration test with LedgerStore: 1:N refund pairing display is preserved."""
    from app.partial_refund import refund_links
    board = LedgerStore(tmp_path / "evidence_test.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,원결제가맹점,50000,,,50000,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,취소가맹점,20000,,,20000,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,취소가맹점,30000,,,30000,2026-10-03,2026-10-04,A300,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}
        for approval, amt in [("200", -20000), ("300", -30000)]:
            board.conn.execute(
                "UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,"
                "original_approval_number='100' WHERE transaction_id=?",
                (amt, ids[approval]))
        board.conn.commit()

        linked = refund_links(board.conn, [ids["200"], ids["300"]])
        html_out = card_flow._render_refund_evidence(board, ids["200"], linked[ids["200"]])

        assert "원승인번호 기준 원결제 확정 연결 · 취소/환불 2건" in html_out
        assert "전액 상쇄" in html_out
        assert "원결제 50,000원 · 환불 합계 -50,000원 · 순액 0원" in html_out
    finally:
        board.close()
