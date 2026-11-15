"""Targeted tests for ledger design assets extraction (RF-201/202).

Validates pure asset ownership of STYLE and SCRIPT, static file byte equivalence,
zero extra per-request disk I/O on page rendering, and immutable font/icon assets.
"""

import hashlib
from unittest.mock import patch

from webapp import ledger_design
from webapp import ledger_design_assets as assets
from webapp import static_assets


def _sha256(data: bytes | str) -> str:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TestLedgerDesignAssets:
    def test_reexport_style_script_reference_identity(self):
        """ledger_design must re-export STYLE and SCRIPT from assets module without copying."""
        assert ledger_design.STYLE is assets.STYLE
        assert ledger_design.SCRIPT is assets.SCRIPT

    def test_css_and_js_file_exact_byte_equivalence(self):
        """Disk asset files must be byte-for-byte identical to in-memory constants."""
        css_file = assets.CSS_DIR / "ledger_design.css"
        js_file = assets.JS_DIR / "ledger_design.js"
        assert css_file.is_file()
        assert js_file.is_file()

        expected = (
            assets.TOKENS_STYLE + "\n" + assets.COMPONENTS_STYLE + "\n"
            + css_file.read_text(encoding="utf-8")
        )
        assert expected == assets.STYLE
        assert js_file.read_text(encoding="utf-8") == assets.SCRIPT

    def test_rendering_causes_zero_extra_disk_io(self):
        """Rendering a ledger page must use in-memory STYLE and SCRIPT without disk reads."""
        with patch.object(assets.Path, "read_text", side_effect=AssertionError("Disk read called during render!")):
            html = ledger_design.render(ledger_design.page("trip-demo-a"))
            # Requirement change: the bundles are hashed linked assets, not inline.
            assert assets.STYLE not in html
            assert static_assets.link("ledger_design") in html
            assert static_assets.script("ledger_design") in html

    def test_font_and_icon_artifacts_exact_equivalence(self):
        """The unchanged font, license and icons retain their reference bytes."""
        # 3. OFL.txt font license
        ofl_res = ledger_design.static_asset("OFL.txt")
        assert ofl_res is not None
        ofl_bytes, ofl_type = ofl_res
        assert ofl_type == "text/plain; charset=utf-8"
        assert len(ofl_bytes) == 4418
        assert _sha256(ofl_bytes) == "d31ddd9f2bed32fd7e302a205cf2380ba0de6529152d239ef99cfb6f261bfc04"

        # 4. PretendardVariable.woff2 font
        font_res = ledger_design.static_asset("PretendardVariable.woff2")
        assert font_res is not None
        font_bytes, font_type = font_res
        assert font_type == "font/woff2"
        assert len(font_bytes) == 2057688
        assert _sha256(font_bytes) == "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4"

        # 5. Agoda icon
        agoda_res = ledger_design.ota_asset("agoda.png")
        assert agoda_res is not None
        agoda_bytes, agoda_type = agoda_res
        assert agoda_type == "image/png"
        assert len(agoda_bytes) == 1281
        assert _sha256(agoda_bytes) == "512e8c3a492200bf51ec013f94e11fea3eac9f691124543bd3dd57e4bb6f868b"

        # 6. Trip icon
        trip_res = ledger_design.ota_asset("trip.png")
        assert trip_res is not None
        trip_bytes, trip_type = trip_res
        assert trip_type == "image/png"
        assert len(trip_bytes) == 453
        assert _sha256(trip_bytes) == "19f1bca3de687fb4729d5ecf8b8cde15b7ac664ccb8e79907d46b35c485d2e19"

    def test_original_font_and_ota_security_and_missing_checks_preserved(self):
        """Allowlist and missing file semantics on ledger_design are preserved untouched."""
        assert ledger_design.static_asset("../ledger_board.py") is None
        assert ledger_design.static_asset("sub/PretendardVariable.woff2") is None
        assert ledger_design.static_asset("missing.woff2") is None
        assert ledger_design.ota_asset("../agoda.png") is None
        assert ledger_design.ota_asset("missing.png") is None
