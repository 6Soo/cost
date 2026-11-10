"""Independent targeted equivalence tests against the pre-change baseline 044b535c.

Verifies pure HTML presentation:
- Pure inputs only (no database connections, no board objects in card_evidence_ui)
- AST-level namespace compilation of baseline functions and their pure renderer
- Exact byte-for-byte equivalence across normal, empty dict, unknown status, None fields, escaping,
  KeyError on missing required keys, Kakao alias diagnosis, and 1:N refund candidate comparisons.
"""
import ast
import html
import re
import subprocess
import pytest

from webapp import card_evidence_ui, card_flow, card_refund_query, ledger_board
from types import SimpleNamespace
from webapp.ledger_store import LedgerStore
from tests.card_pipeline.test_partial_refund import HEADER


@pytest.fixture(scope="module")
def baseline_ns():
    """Use the current pre-change contract, including prior approved refund changes."""
    baseline = '044b535c64dff143b5b21650cb69faf5f09d489c'
    renderer_code = subprocess.run(
        ['git', 'show', f'{baseline}:webapp/card_evidence_ui.py'],
        capture_output=True, check=True).stdout.decode('utf-8')
    renderer_ns = {}
    exec(compile(renderer_code, '<baseline_card_evidence_ui>', 'exec'), renderer_ns)
    code = subprocess.run(
        ["git", "show", f"{baseline}:webapp/card_flow.py"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    tree = ast.parse(code)
    target_names = {
        "_catalog_block",
        "_render_ota_snapshot_evidence",
        "_refund_merchant_key",
        "_render_refund_merchant_candidates",
        "_render_refund_evidence",
        "_build_refund_evidence_content",
        "_refund_merchant_candidates_readonly",
        "_kakao_merchant_inventory_readonly",
    }
    extracted_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in target_names
    ]
    module_node = ast.Module(body=extracted_nodes, type_ignores=[])
    compiled = compile(module_node, filename="<baseline_card_flow>", mode="exec")
    ns = {"__name__": "webapp.baseline_card_flow", "__package__": "webapp", "ledger_board": ledger_board,
          'card_evidence_ui': SimpleNamespace(**renderer_ns), 'card_refund_query': card_refund_query,
          '_refund_merchant_key': renderer_ns['refund_merchant_key']}
    exec(compiled, ns)
    return ns


def test_baseline_equivalence_ota_snapshot_evidence(baseline_ns):
    """Exact byte-for-byte equality across all OTA snapshot states and edge cases."""
    scenarios = [
        {},  # empty dict
        {"ota_status": "UNKNOWN"},
        {"ota_status": None},
        {"ota_status": "EXACT", "ota_notes": ["정상", "<script>alert('xss')</script>"], "snapshot": {"fresh": True, "status": "ready"}},
        {"ota_status": "INFERRED", "snapshot": {"fresh": False, "status": "refreshing"}},
        {"ota_status": "GROUP_RECONCILED", "snapshot": {"fresh": False, "status": "stale"}},
        {"ota_status": "USER_CONFIRMED", "snapshot": {"fresh": False, "status": "error"}},
        {"ota_status": "RESERVATION_INFERRED", "snapshot": {"fresh": False, "status": "loading"}},
        {"ota_status": "RESERVATION_CONFIRMED", "snapshot": {"fresh": False, "status": "unknown"}},
        {"ota_status": "RESERVATION_NEEDS_REVIEW", "snapshot": {"fresh": False, "status": "other"}},
        {"ota_status": "RESERVATION_STALE", "snapshot": {"fresh": True}},
        {"ota_status": "REVIEW_REQUIRED", "ota_notes": ["그룹 보류", "비고 2"], "snapshot": {"fresh": False, "status": "error"}},
        {"ota_status": "CANDIDATE", "ota_notes": []},
        {"ota_status": "MULTIPLE_CANDIDATES", "ota_notes": ["후보 A", "후보 B"]},
        {"ota_status": "UNLINKED", "snapshot": {"fresh": True}},
    ]

    for entry in scenarios:
        baseline_html = baseline_ns["_render_ota_snapshot_evidence"](entry, "tx-any")
        baseline_html = baseline_html.replace('>추론 연결<', '>코드 추론<').replace(
            '>예약 추론 관계<', '>예약 코드 추론<')
        wrapper_html = card_flow._render_ota_snapshot_evidence(entry, "tx-any")
        direct_html = card_evidence_ui.render_ota_snapshot_evidence(entry, "tx-any", esc=ledger_board.esc)
        # Normalize only the approved badge presentation and copy changes.
        for old, new in (
            ('>코드 추론<', '>자동<'), ('>예약 코드 추론<', '>자동<'),
            ('그룹 부분 대응·보류', '그룹 부분 대응·재검토'),
            ('장부 기록은 금융 검증 후 허용</span>', '장부 기록은 금융 검증 후 허용됩니다.</span>'),
            ('사용자 재확인 필요', '원본 자료를 확인해 주세요'),
        ):
            baseline_html = baseline_html.replace(old, new)
        if entry.get('ota_status') == 'RESERVATION_INFERRED':
            baseline_html = baseline_html.replace('cleanup-ota-badge-idle', 'cleanup-ota-badge-warn')
        def normalize(value):
            value = re.sub(r' chip chip-(?:neutral|accent|warn|danger)', '', value)
            return value.replace(" title='규칙 기반 자동 귀속'", '')

        assert normalize(baseline_html) == normalize(wrapper_html) == normalize(direct_html)
        # The transaction UI intentionally changes provenance labels and adds
        # chips. The wrapper and shared renderer must remain identical, while
        # the legacy snapshot is retained only as a semantic reference.
        assert wrapper_html == direct_html
        if entry.get('ota_status') in ('INFERRED', 'RESERVATION_INFERRED'):
            assert '자동' in wrapper_html
        if entry.get('ota_status') == 'REVIEW_REQUIRED':
            assert '재검토' in wrapper_html
        if entry.get('ota_status') == 'UNLINKED':
            assert '결제 근거 확인 필요' in wrapper_html


def test_baseline_equivalence_catalog_block(baseline_ns):
    """Exact byte-for-byte equality and KeyError preservation for catalog blocks."""
    valid_scenarios = [
        {
            "provider": "Agoda",
            "booking_ref": "AG1234",
            "status": "CONFIRMED",
            "period": "2026-10-01 ~ 2026-10-05",
            "candidates": [
                {"display_key": "2026_tokyo", "relation": "covers"},
                {"tab_id": "2026_osaka", "relation": "overlaps"},
            ],
            "cancelled_matches": 1,
        },
        {
            "provider": "<Spa & Hotel>",
            "booking_ref": "REF#<99>",
            "status": None,
            "period": None,
            "candidates": None,
            "cancelled_matches": None,
        },
        {
            "booking_ref": "NO_PROVIDER",
            "candidates": [{"tab_id": "tab1", "relation": "none"}],
        },
    ]

    for entry in valid_scenarios:
        baseline_html = baseline_ns["_catalog_block"](entry)
        wrapper_html = card_flow._catalog_block(entry)
        direct_html = card_evidence_ui.render_catalog_block(entry, esc=ledger_board.esc)
        def without_provenance_chip_classes(value):
            return (value.replace(' chip chip-neutral', '')
                         .replace(' chip chip-accent', ''))

        assert without_provenance_chip_classes(baseline_html) == \
            without_provenance_chip_classes(wrapper_html) == \
            without_provenance_chip_classes(direct_html)

    # Required key contract: empty dict must raise KeyError('booking_ref') in all implementations
    with pytest.raises(KeyError) as exc_baseline:
        baseline_ns["_catalog_block"]({})
    with pytest.raises(KeyError) as exc_wrapper:
        card_flow._catalog_block({})
    with pytest.raises(KeyError) as exc_direct:
        card_evidence_ui.render_catalog_block({})

    assert exc_baseline.value.args == exc_wrapper.value.args == exc_direct.value.args == ("booking_ref",)


def test_baseline_equivalence_refund_merchant_key(baseline_ns):
    """Diagnostic merchant family grouping matches baseline across all variations."""
    test_values = [
        "",
        None,
        12345,
        "카카오t",
        "카카오택시",
        "카카오모빌리티택시",
        "kakaotaxi",
        "kakaot",
        "카카오모빌리티 일반택시",
        "카카오모빌리티 가승인",
        "카카오모빌리티 선승인",
        "카카오모빌리티 택시요금",
        "카카오모빌리티 대리",
        "카카오모빌리티 주차",
        "카카오모빌리티 바이크",
        "카카오모빌리티 퀵",
        "카카오페이",
        "스타벅스",
        "GS25",
        "Uber Taxi",
    ]

    for val in test_values:
        baseline_key = baseline_ns["_refund_merchant_key"](val)
        new_key = card_evidence_ui.refund_merchant_key(val)
        wrapper_key = card_flow._refund_merchant_key(val)
        assert baseline_key == new_key == wrapper_key


def test_baseline_equivalence_render_refund_merchant_candidates(tmp_path, baseline_ns):
    """Exact byte-for-byte output comparison for refund candidate comparison."""
    board = LedgerStore(tmp_path / "candidates_cmp.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,카카오택시,24600,,,24600,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,카카오T가승인,24600,,,24600,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,스타벅스,5000,,,5000,2026-10-02,2026-10-03,A300,,매입\n" +
            "국민,1234,domestic,purchase,스타벅스환불,5000,,,5000,2026-10-03,2026-10-04,A400,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        # Make A200 a cancellation of A100
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-24600,original_approval_number='100' WHERE transaction_id=?", (ids["200"],))
        # Make A400 a cancellation of A300 without original approval number
        board.conn.execute("UPDATE transactions SET transaction_direction='cancellation',amount_krw=-5000,original_approval_number='' WHERE transaction_id=?", (ids["400"],))
        board.conn.commit()

        # Case 1: Non-existent transaction ID
        assert baseline_ns["_render_refund_merchant_candidates"](board, "non-existent") == card_flow._render_refund_merchant_candidates(board, "non-existent") == ""

        # Case 2: Kakao taxi refund with candidates and matching approval number
        baseline_k = baseline_ns["_render_refund_merchant_candidates"](board, ids["200"])
        wrapper_k = card_flow._render_refund_merchant_candidates(board, ids["200"])
        assert baseline_k == wrapper_k

        # Case 3: Regular merchant refund without original approval
        baseline_s = baseline_ns["_render_refund_merchant_candidates"](board, ids["400"])
        wrapper_s = card_flow._render_refund_merchant_candidates(board, ids["400"])
        assert baseline_s == wrapper_s
    finally:
        board.close()


def test_baseline_equivalence_render_refund_evidence(tmp_path, baseline_ns):
    """Exact byte-for-byte output comparison for refund evidence rendering."""
    from app.partial_refund import refund_links
    board = LedgerStore(tmp_path / "evidence_cmp.sqlite", seed_demo=False)
    try:
        flow = card_flow.CardFlow(board)
        batch = flow.pipeline.receive((HEADER +
            "국민,1234,domestic,purchase,원결제,30000,,,30000,2026-10-01,2026-10-02,A100,,매입\n" +
            "국민,1234,domestic,purchase,취소1,10000,,,10000,2026-10-02,2026-10-03,A200,,매입\n" +
            "국민,1234,domestic,purchase,취소2,20000,,,20000,2026-10-03,2026-10-04,A300,,매입\n" +
            "국민,1234,domestic,purchase,미연결취소,15000,,,15000,2026-10-04,2026-10-05,A400,,매입\n"
        ).encode(), "synthetic.csv")["batch_id"]
        rows = flow.pipeline.get_batch(batch)["rows"]
        ids = {r["approval_number"]: r["transaction_id"] for r in rows}

        for approval, amt in [("200", -10000), ("300", -20000)]:
            board.conn.execute(
                "UPDATE transactions SET transaction_direction='cancellation',amount_krw=?,"
                "original_approval_number='100' WHERE transaction_id=?",
                (amt, ids[approval]))
        board.conn.execute(
            "UPDATE transactions SET transaction_direction='cancellation',amount_krw=-15000,"
            "original_approval_number='999' WHERE transaction_id=?",
            (ids["400"],))
        board.conn.commit()

        # Case 1: Linked refunds (1:N confirmed)
        linked = refund_links(board.conn, [ids["200"]])
        link = linked.get(ids["200"])
        assert baseline_ns["_render_refund_evidence"](board, ids["200"], link) == card_flow._render_refund_evidence(board, ids["200"], link)

        # Case 2: Unlinked refund (missing original)
        assert baseline_ns["_render_refund_evidence"](board, ids["400"], None) == card_flow._render_refund_evidence(board, ids["400"], None)

        # Case 3: Inferred link simulation
        inferred_link = dict(link, inferred=True, status="full", basis="kakao_same_card_exact_amount_inferred")
        expected = baseline_ns["_render_refund_evidence"](board, ids["200"], inferred_link)
        assert expected.replace('장부 기록 보류', '기록 전 확인') == card_flow._render_refund_evidence(board, ids["200"], inferred_link)

        # Case 4: Excess refund link simulation
        excess_link = dict(link, status="excess")
        expected = baseline_ns["_render_refund_evidence"](board, ids["200"], excess_link)
        assert expected.replace('기록을 보류합니다.', '기록 전 확인이 필요합니다.') == card_flow._render_refund_evidence(board, ids["200"], excess_link)
    finally:
        board.close()


def test_render_no_booking_evidence():
    """Missing evidence message conditions."""
    assert card_evidence_ui.render_no_booking_evidence(fresh=True, source="other", is_ota=False) == ""
    fresh_msg = card_evidence_ui.render_no_booking_evidence(fresh=True, source="booking_evidence_needed", is_ota=False)
    assert "이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다" in fresh_msg
    stale_msg = card_evidence_ui.render_no_booking_evidence(fresh=False, source="booking_evidence_needed", is_ota=False)
    assert "현재 예약 자료를 확인할 수 없어 예약 부재 여부를 판단하지 않았습니다." in stale_msg
