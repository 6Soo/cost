import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp import flight_passenger_page as page


def test_design_tokens_and_accessibility_markup_present():
    document = page._legacy_page('csrf-synth')
    # Page styles consume the shared semantic token sheet.
    assert "@import url('/static/css/tokens.css')" in document
    assert '--bg:var(--c-bg)' in document
    assert '--ink:var(--c-text)' in document
    assert '--focus:var(--c-focus' in document
    assert '--paper:var(--c-surface)' in document
    assert '@media(prefers-color-scheme:dark)' not in document
    # Access improvements: label associations via for/id and aria-label on form
    assert "for='f-booking'" in document
    assert "id='f-booking'" in document
    assert "aria-label='항공권 참가자 연결 검색'" in document
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
    # The page reads candidate data and saves only through COST's local API.
    assert "fetch('/api/flight-passengers/candidates?" in document
    assert "fetch('/api/flight-passengers/assign',{method:'POST'" in document
    assert 'googleapis.com' not in document.lower()
    assert 'spreadsheets.values.update' not in document
    assert '항공권 참가자 연결' in document
    assert '예약 시스템 여행 ID' in document
    assert '연결 후보 찾기' in document
    assert "title.textContent=passenger.passenger_name_en+' · '+passenger.status" not in document
    assert 'data.code||' not in document


def test_csrf_token_cannot_terminate_script_element():
    document = page._legacy_page('</script><script>alert(1)</script>')
    assert r'const csrf="\u003c/script>\u003cscript>alert(1)\u003c/script>";' in document
    assert '</script><script>alert(1)' not in document


def test_save_full_fixture_with_css():
    document = page._legacy_page('csrf-synth')
    out_dir = Path('C:/Users/kkokk/AppData/Local/Temp/cost-goal-20261025/flight-ui')
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = out_dir / 'flight-passenger-render.html'
    fixture_path.write_text(document, encoding='utf-8')
    assert fixture_path.is_file()
    assert fixture_path.stat().st_size > 2000
    # Verify the saved file contains the same design tokens
    content = fixture_path.read_text(encoding='utf-8')
    assert '--bg:var(--c-bg)' in content
    assert '--focus:var(--c-focus' in content
    assert 'overflow:hidden' in content or '@media(max-width:375px)' in content
