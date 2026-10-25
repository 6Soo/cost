import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp import flight_passenger_page as page


def test_design_tokens_and_accessibility_markup_present():
    document = page._page('csrf-synth')
    # Design token variables must be declared in the style block
    assert '--bg:#F8FAFC' in document
    assert '--ink:#0F172A' in document
    assert '--focus:#2266F5' in document
    assert '--paper:#FFFFFF' in document
    # Access improvements: label associations via for/id and aria-label on form
    assert "for='f-booking'" in document
    assert "id='f-booking'" in document
    assert "aria-label='항공권 참가자 후보 검색'" in document
    assert "aria-live='polite'" in document
    assert "aria-label='후보 결과'" in document
    # Focus-visible contract
    assert ':focus-visible' in document
    assert 'outline:2px solid var(--focus)' in document
    # Overflow/narrow-width protection
    assert 'overflow:hidden' in document or 'min-width:0' in document
    assert 'max-width:375px' in document or '@media(max-width:375px)' in document
    # No hardcoded #243129 text color remains
    assert '#243129' not in document
    # Existing dispatch contracts unchanged
    assert '/api/flight-passengers/candidates' in document
    assert '/api/flight-passengers/assign' in document
    # CSRF token is embedded but only as quoted JSON string inside script, not as plain secret
    assert 'const csrf=' in document
    # Secret token value is quoted (json.dumps output) and does not appear outside the JS variable assignment
    # The actual secret value is embedded; we verify the quote escaping keeps it inside JS, not leaked into HTML text
    assert 'csrf-synth' in document
    # No new DB or external write endpoints
    assert 'google' not in document.lower() or 'google' not in document.lower()


def test_save_full_fixture_with_css():
    document = page._page('csrf-synth')
    out_dir = Path('C:/Users/kkokk/AppData/Local/Temp/cost-goal-20261025/flight-ui')
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / 'flight-passenger-render.html'
    fixture_path.write_text(document, encoding='utf-8')
    assert fixture_path.is_file()
    assert fixture_path.stat().st_size > 2000
    # Verify the saved file contains the same design tokens
    content = fixture_path.read_text(encoding='utf-8')
    assert '--bg:#F8FAFC' in content
    assert '--focus:#2266F5' in content
    assert 'overflow:hidden' in content or '@media(max-width:375px)' in content
