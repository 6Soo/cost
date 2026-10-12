from webapp import ui_icons


def test_only_allowlisted_names_render():
    assert ui_icons.icon("search", 16).startswith("<svg")
    assert ui_icons.icon("no-such-icon") == ""
    assert ui_icons.esc_icon(123) == ""
    assert ui_icons.esc_icon("search';alert(1)") == ""


def test_decorative_attributes_and_stroke_contract():
    markup = ui_icons.icon("search")
    assert "aria-hidden='true'" in markup
    assert "focusable='false'" in markup
    assert "viewBox='0 0 24 24'" in markup
    assert "fill='none'" in markup
    assert "stroke='currentColor'" in markup
    assert "stroke-linecap='round'" in markup or 'stroke-linecap="round"' in markup
    assert "<script" not in markup and "onload" not in markup


def test_sizes_stay_within_the_spec():
    assert "width='18'" in ui_icons.icon("house", 18)
    assert "width='14'" in ui_icons.icon("chevron-down", 14)
    # 허용 범위를 벗어나면 기본 16px로 고정한다.
    assert "width='16'" in ui_icons.icon("house", 99)
