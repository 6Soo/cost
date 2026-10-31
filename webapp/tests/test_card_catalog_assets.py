"""Targeted tests for card catalog asset extraction (RF-201).

Validates pure asset ownership of CATALOG_STYLE and CATALOG_SCRIPT,
static file byte equivalence, zero extra per-request disk I/O on rendering,
re-export compatibility, and 100% bit-for-bit equivalence with baseline hashes.
"""

import hashlib
from unittest.mock import patch

from webapp import card_catalog
from webapp import card_catalog_assets as assets
from webapp import ota_catalog


def _sha256(data: bytes | str) -> str:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TestCardCatalogAssets:
    def test_reexport_style_script_reference_identity(self):
        """card_catalog and ota_catalog must export exact same objects from assets module."""
        assert card_catalog.CATALOG_STYLE is assets.CATALOG_STYLE
        assert card_catalog.CATALOG_SCRIPT is assets.CATALOG_SCRIPT
        assert ota_catalog.CATALOG_STYLE is assets.CATALOG_STYLE
        assert ota_catalog.CATALOG_SCRIPT is assets.CATALOG_SCRIPT

    def test_css_and_js_file_exact_byte_equivalence(self):
        """Disk asset files must be byte-for-byte identical to in-memory constants."""
        css_file = assets.CSS_DIR / "card_catalog.css"
        js_file = assets.JS_DIR / "card_catalog.js"
        assert css_file.is_file()
        assert js_file.is_file()

        assert css_file.read_text(encoding="utf-8") == assets.CATALOG_STYLE
        assert js_file.read_text(encoding="utf-8") == assets.CATALOG_SCRIPT

        # Lengths and hashes matching baseline
        assert len(assets.CATALOG_STYLE) == 6313
        assert _sha256(assets.CATALOG_STYLE) == "fb24fe4b2d407d36eab1c8a55c3f874dcb8d0b8f2f62a4fe03dbcf88fb6aa8f2"
        assert len(assets.CATALOG_SCRIPT) == 944
        assert _sha256(assets.CATALOG_SCRIPT) == "05da5414b9b25fc041440078aa16c117ff10e089dd5ab19fdd7142195dc0f3a7"

    def test_rendering_causes_zero_extra_disk_io(self):
        """Rendering catalog HTML must use in-memory assets without disk reads."""
        data = {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        with patch.object(assets.Path, "read_text", side_effect=AssertionError("Disk read called during render!")):
            html = card_catalog.render_html(data, {})
            assert len(html) == 12808
            assert "<style>" + assets.CATALOG_STYLE + "</style>" in html

    def test_baseline_empty_and_synthetic_markup_equivalence(self):
        """render_html must strictly match baseline lengths and hashes for empty and synthetic data."""
        # 1. Empty data
        data_empty = {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        html_empty = card_catalog.render_html(data_empty, {}, csrf="test-csrf")
        assert len(html_empty) == 12808
        assert _sha256(html_empty) == "e8c0ef91fdb09b4e99846332ba97fe1be4a923d6ac68ab53159703a5b0ab60a2"

        # 2. Synthetic list with normal and long booking references
        synthetic_rows = [
            {
                'transaction_id': 'tx-1001',
                'approval_date': '2026-10-15',
                'posting_date': '2026-10-16',
                'issuer': '현대카드',
                'card_tail': '1234',
                'merchant': '스타벅스 강남점',
                'transaction_direction': 'purchase',
                'transaction_kind': '일시불',
                'amount_krw': 12500,
                'item': '식비',
                'trip_name': '제주도 워크샵',
                'decided': True,
                'duplicate_of': None,
                'company_excluded': False,
                'conflict_reason': None,
                'parse_error': None,
                'ota_candidate_notes': [],
                'next_action': {'group': 'done', 'reason': '직접 분류 완료', 'href': '/cards/tx-1001', 'label': '내역 보기'},
            },
            {
                'transaction_id': 'tx-long-ref-999999999999999999999999999999',
                'approval_date': '2026-10-16',
                'posting_date': None,
                'issuer': '신한카드',
                'card_tail': '5678',
                'merchant': 'Agoda Co. Ltd. (BKNG-LONG-REF-999999999999999999999999999999)',
                'transaction_direction': 'cancellation',
                'transaction_kind': '취소',
                'amount_krw': 142000,
                'item': None,
                'trip_name': None,
                'decided': False,
                'duplicate_of': 'tx-1000',
                'company_excluded': True,
                'conflict_reason': '중복 청구 의심',
                'parse_error': None,
                'ota_candidate_notes': ['예약번호 BKNG-LONG-REF-999999999999999999999999999999 추적됨'],
                'next_action': {'group': 'review', 'reason': 'OTA 예약 대사 대기', 'href': '/cards/tx-long', 'label': '검토하기'},
            }
        ]
        data_synth = {
            'rows': synthetic_rows,
            'total': 2,
            'all_count': 150,
            'cards': ['1234', '5678'],
            'months': ['2026-09', '2026-10'],
            'page': 1,
            'pages': 1,
        }
        query_synth = {'q': '스타벅스', 'card': '1234', 'state': 'needs_review', 'sort': 'desc', 'month': '2026-10'}
        html_synth = card_catalog.render_html(data_synth, query_synth, csrf="test-csrf-synth")
        assert len(html_synth) == 14274
        assert _sha256(html_synth) == "877d9cdb0f5548928e78a7c6df48f8d2b9e090b12f6da2384fc02b4e1a201cb7"
