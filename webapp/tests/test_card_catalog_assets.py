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
        assert len(assets.CATALOG_STYLE) == 6590
        assert _sha256(assets.CATALOG_STYLE) == "935222e47db16b3e86b726e4f6e0c2f6073a34a87d7beae2d984106b08e77d52"
        assert len(assets.CATALOG_SCRIPT) == 1077
        assert _sha256(assets.CATALOG_SCRIPT) == "f9a0039ada5025608f80e59d005240fe58f854c7df63adcabb255cfda814970a"

    def test_rendering_causes_zero_extra_disk_io(self):
        """Rendering catalog HTML must use in-memory assets without disk reads."""
        data = {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        with patch.object(assets.Path, "read_text", side_effect=AssertionError("Disk read called during render!")):
            html = card_catalog.render_html(data, {})
            assert len(html) == 14054
            assert "<style>" + assets.CATALOG_STYLE + "</style>" in html

    def test_baseline_empty_and_synthetic_markup_equivalence(self):
        """render_html must strictly match baseline lengths and hashes for empty and synthetic data."""
        # 1. Empty data
        data_empty = {'rows': [], 'total': 0, 'all_count': 0, 'cards': [], 'months': [], 'page': 1, 'pages': 1}
        html_empty = card_catalog.render_html(data_empty, {}, csrf="test-csrf")
        assert len(html_empty) == 14054
        assert _sha256(html_empty) == "565649e81456fd24a701b6c299ae5bc2d16f17d5842e92e14b81f22a26cd9f1e"

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
                'next_action': {'state_label': '완료', 'reason_label': '분류 완료', 'group': 'done', 'reason': '직접 분류 완료', 'href': '/cards/tx-1001', 'label': '내역 보기'},
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
                'next_action': {'state_label': '확인 필요', 'reason_label': '검토하기', 'group': 'review', 'reason': 'OTA 예약 대사 대기', 'href': '/cards/tx-long', 'label': '검토하기'},
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
        assert len(html_synth) == 15564
        assert _sha256(html_synth) == "117ab605d7a881f0ebea22ccea0c771e6cf73f0388e19a11823124a446a84be0"
