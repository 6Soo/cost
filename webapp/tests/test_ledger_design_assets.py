"""Targeted tests for ledger design assets (RF-201/202).

Validates pure asset ownership, in-memory caching (zero per-request disk reads),
path traversal protections, content-type headers, token preservation,
and 100% bit-for-bit rendering equivalence with baseline.
"""

import hashlib
from unittest.mock import patch
import pytest

from webapp import ledger_design
from webapp import ledger_design_assets as assets


def _sha256(data: bytes | str) -> str:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TestLedgerDesignAssets:
    def test_reexport_constants_and_reference_identity(self):
        """ledger_design must export the exact same objects without copying."""
        assert ledger_design.STYLE is assets.STYLE
        assert ledger_design.SCRIPT is assets.SCRIPT
        assert ledger_design.STATIC_ASSETS is assets.STATIC_ASSETS
        assert ledger_design.OTA_ASSETS is assets.OTA_ASSETS
        assert ledger_design.FONT_FAMILY == "Pretendard Variable"
        assert ledger_design.FONT_DIR == assets.FONT_DIR
        assert ledger_design.OTA_DIR == assets.OTA_DIR

    def test_css_and_js_file_exact_byte_equivalence(self):
        """Disk asset files must be byte-for-byte identical to in-memory constants."""
        css_file = assets.CSS_DIR / "ledger_design.css"
        js_file = assets.JS_DIR / "ledger_design.js"
        assert css_file.is_file()
        assert js_file.is_file()

        assert css_file.read_text(encoding="utf-8") == assets.STYLE
        assert js_file.read_text(encoding="utf-8") == assets.SCRIPT

        # Lengths and hashes matching baseline
        assert len(assets.STYLE) == 32140
        assert _sha256(assets.STYLE) == "b7ce391815ea3c5a35a799be447a996eeff20ad803270fa31a2b9bcc4b44d766"
        assert len(assets.SCRIPT) == 20443
        assert _sha256(assets.SCRIPT) == "05e500361fe498fd00c5102920bf9a689e13422492a1271b215e77dba3023c4c"

    def test_static_asset_font_serving_and_types(self):
        """Font assets must be served with exact MIME types and baseline hashes."""
        ofl_res = assets.static_asset("OFL.txt")
        assert ofl_res is not None
        ofl_bytes, ofl_type = ofl_res
        assert ofl_type == "text/plain; charset=utf-8"
        assert len(ofl_bytes) == 4418
        assert _sha256(ofl_bytes) == "d31ddd9f2bed32fd7e302a205cf2380ba0de6529152d239ef99cfb6f261bfc04"

        font_res = assets.static_asset("PretendardVariable.woff2")
        assert font_res is not None
        font_bytes, font_type = font_res
        assert font_type == "font/woff2"
        assert len(font_bytes) == 2057688
        assert _sha256(font_bytes) == "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4"

    def test_ota_asset_brand_icons_and_types(self):
        """OTA icons must be served with image/png and exact hashes."""
        agoda_res = assets.ota_asset("agoda.png")
        assert agoda_res is not None
        agoda_bytes, agoda_type = agoda_res
        assert agoda_type == "image/png"
        assert len(agoda_bytes) == 1281
        assert _sha256(agoda_bytes) == "512e8c3a492200bf51ec013f94e11fea3eac9f691124543bd3dd57e4bb6f868b"

        trip_res = assets.ota_asset("trip.png")
        assert trip_res is not None
        trip_bytes, trip_type = trip_res
        assert trip_type == "image/png"
        assert len(trip_bytes) == 453
        assert _sha256(trip_bytes) == "19f1bca3de687fb4729d5ecf8b8cde15b7ac664ccb8e79907d46b35c485d2e19"

    def test_path_traversal_and_invalid_asset_refusal(self):
        """Assets outside the allowlist or with traversal sequences must return None."""
        invalid_names = [
            "../ledger_board.py",
            "../../etc/passwd",
            "..\\ledger_board.py",
            "sub/PretendardVariable.woff2",
            "nonexistent.woff2",
            "",
            None,
            123,
        ]
        for name in invalid_names:
            assert assets.static_asset(name) is None
            assert assets.ota_asset(name) is None
            assert ledger_design.static_asset(name) is None
            assert ledger_design.ota_asset(name) is None

    def test_in_memory_caching_avoids_per_request_disk_io(self):
        """Repeated asset requests must be served from cache without disk I/O."""
        # Ensure primed
        assets.static_asset("OFL.txt")
        assets.ota_asset("trip.png")

        # Mock Path.read_bytes to guarantee no disk reads happen on cached calls
        with patch.object(assets.Path, "read_bytes", side_effect=AssertionError("Disk read called!")):
            cached_ofl = assets.static_asset("OFL.txt")
            assert cached_ofl is not None
            assert cached_ofl[1] == "text/plain; charset=utf-8"

            cached_trip = assets.ota_asset("trip.png")
            assert cached_trip is not None
            assert cached_trip[1] == "image/png"

    def test_tokens_css_contains_full_palette_and_dark_media(self):
        """tokens.css must contain the design tokens and dark mode palette."""
        tokens_file = assets.CSS_DIR / "tokens.css"
        assert tokens_file.is_file()
        css = tokens_file.read_text(encoding="utf-8")
        assert "--bg: #F8FAFC" in css
        assert "--paper: #FFFFFF" in css
        assert "--ink: #0F172A" in css
        assert "--line: #E2E8F0" in css
        assert "@media (prefers-color-scheme: dark)" in css
        assert "--bg: #0F172A" in css
        assert "--paper: #1E293B" in css

    def test_rendered_ledger_page_html_equivalence(self):
        """Rendered HTML via ledger_design.render must match baseline hash identically."""
        page_ast = ledger_design.page("trip-demo-a")
        html = ledger_design.render(page_ast)
        assert len(html) == 54752
        assert _sha256(html) == "3ea14a329311bb49fcef3cbe70c07b86c2291a1a4e839d92015381bfd6c082e4"
