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

        # Intentional asset snapshot: catches accidental drift, not a performance cap.
        assert len(assets.CATALOG_STYLE) == 8804
        assert _sha256(assets.CATALOG_STYLE) == "c80aa151e12f1849002c7a65a0d5a646021f85219f9f7ac7d90e163822ffe8bf"
        assert len(assets.CATALOG_SCRIPT) == 1077
        assert _sha256(assets.CATALOG_SCRIPT) == "f9a0039ada5025608f80e59d005240fe58f854c7df63adcabb255cfda814970a"

    def test_retired_rendering_uses_no_disk_io_and_has_canonical_data_link(self):
        data={'rows':[],'total':0,'all_count':0,'cards':[],'months':[],'page':1,'pages':1}
        with patch.object(assets.Path,'read_text',side_effect=AssertionError('per-request disk read')):
            markup=card_catalog.render_html(data,{})
        assert "<h1>카드 내역</h1>" in markup
        assert "href='/cards/all'" in markup
        assert '/my-actions' not in markup and '<form' not in markup

    def test_legacy_catalog_filters_do_not_resurrect_retired_workflow(self):
        markup=card_catalog.render_html({'rows':[]},{'q':['합성상점'],'card':['1234'],
            'month':['2026-10'],'state':['needs_review'],'unassigned':['1']})
        from html import unescape
        from urllib.parse import urlparse,parse_qs
        import re
        target=unescape(re.search(r"href='([^']+)'",markup)[1])
        query=parse_qs(urlparse(target).query)
        assert urlparse(target).path == '/cards/all'
        assert query == {'q':['합성상점'],'card':['1234'],'month':['2026-10']}
        assert '미배정' not in markup and '처리 필요' not in markup
