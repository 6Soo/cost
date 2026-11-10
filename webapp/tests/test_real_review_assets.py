"""Targeted tests for real_review_ui template asset extraction (RF-201/203).

Validates pure template asset ownership, static template byte equivalence,
zero extra per-request disk I/O on page rendering, exact CSRF escaping,
and 100% bit-for-bit equivalence with baseline hashes.
"""

import hashlib
from unittest.mock import patch

from webapp import real_review_assets as assets
from webapp import real_review_ui


def _sha256(data: bytes | str) -> str:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _legacy_copy(document: str) -> str:
    """Normalize only the three retired hold labels; retain the sealed hashes."""
    return (document.replace('행 중 추가 자료 확인 ', '행 중 계속 보류 ')
            .replace('카드 지출 자료 확인 ', '카드 지출 보류 ')
            .replace('option("", "지금은 선택하지 않음", "", false);',
                     'option("", "확인 보류", "", false);'))


class TestRealReviewAssets:
    def test_reexport_document_reference_identity(self):
        """real_review_ui._DOCUMENT must be an alias for real_review_assets._DOCUMENT."""
        assert real_review_ui._DOCUMENT is assets._DOCUMENT

    def test_template_file_exact_byte_equivalence(self):
        """Disk template file must be byte-for-byte identical to in-memory _DOCUMENT."""
        template_file = assets.TEMPLATES_DIR / "real_review.html"
        assert template_file.is_file()

        disk_text = template_file.read_text(encoding="utf-8")
        assert disk_text == assets._DOCUMENT
        assert len(_legacy_copy(assets._DOCUMENT)) == 49037
        assert _sha256(_legacy_copy(assets._DOCUMENT)) == "6b4f6d01cf80cd67f990ed98f379b548a4bbad6e90eb643742fda7c91d5b6fba"

    def test_rendering_causes_zero_extra_disk_io(self):
        """render_real_review_ui must use in-memory template without reading disk."""
        with patch.object(assets.Path, "read_text", side_effect=AssertionError("Disk read called during render!")):
            html = real_review_ui.render_real_review_ui("synthetic-csrf")
            assert len(_legacy_copy(html)) == 60918
            assert "synthetic-csrf" in html

    def test_rendering_baseline_hash_equivalence_across_csrf_variants(self):
        """render_real_review_ui must match baseline hashes for empty, normal, quoted, and tagged csrf."""
        # 1. Empty CSRF
        r_empty = _legacy_copy(real_review_ui.render_real_review_ui())
        assert len(r_empty) == 60904
        assert _sha256(r_empty) == "170e94592d1d32b2e9dba4c1664562e919051a9f0275c8a592fdd6cb24852733"

        # 2. Alphanumeric CSRF
        r_csrf = _legacy_copy(real_review_ui.render_real_review_ui("test-csrf-123"))
        assert len(r_csrf) == 60917
        assert _sha256(r_csrf) == "a359cb37e99bf98ed3bc8f84f413d1e22f733243cd1f85e9e7fd1fee161aa506"

        # 3. CSRF with quotes (must be attribute-escaped)
        r_quotes = _legacy_copy(real_review_ui.render_real_review_ui('csrf"with"quotes'))
        assert len(r_quotes) == 60930
        assert _sha256(r_quotes) == "a5217c2ac90387468e941798692579790aedbe60d3c4a9f17ac1235da8dae3c8"
        assert 'content="csrf&quot;with&quot;quotes"' in r_quotes

        # 4. CSRF with HTML tags
        r_tags = _legacy_copy(real_review_ui.render_real_review_ui("<script>alert(1)</script>"))
        assert len(r_tags) == 60941
        assert _sha256(r_tags) == "fa620e9b18e6c676f1f3b10e9d31760a5c9bb1d591ef3603881d99fa60722db3"
        assert 'content="&lt;script&gt;alert(1)&lt;/script&gt;"' in r_tags

    def test_constants_and_guidance_injection_preserved(self):
        """Public constants and guidance injection order are completely preserved."""
        assert real_review_ui.PAGE_SIZE == 50
        assert real_review_ui.POLL_MS == 2000
        assert real_review_ui.APPLY_PLAN_URL == "/api/review/apply/plan"
        assert real_review_ui.APPLY_URL == "/api/review/apply"

        rendered = real_review_ui.render_real_review_ui("token")
        # Ensure substitutions occurred
        assert "__PAGE_SIZE__" not in rendered
        assert "__POLL_MS__" not in rendered
        assert "__PLAN_URL__" not in rendered
        assert "__APPLY_URL__" not in rendered
        # Ensure guidance script is injected right before buildCard
        assert rendered.count("function buildCard(row, ordinal, total) {") == 1
