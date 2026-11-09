from webapp import ui_components


def test_page_header_and_tabs_escape_text_and_mark_current():
    header = ui_components.page_header("<장부>", meta='A "note"', breadcrumb=[("홈", "/")])
    assert "&lt;장부&gt;" in header
    assert "A &quot;note&quot;" in header
    tabs = ui_components.section_tabs([("거래", "/cards"), ("영수증", "/receipts")], "/cards")
    assert 'aria-current="page"' in tabs
    assert "&lt;" not in tabs


def test_field_binds_label_and_error_to_control():
    rendered = ui_components.field("회사명", '<input name="company">', hint="필수", error="입력하세요")
    assert '<label for="field">' in rendered
    assert 'id="field"' in rendered
    assert 'aria-invalid="true"' in rendered
    assert 'role="alert"' in rendered


def test_status_and_action_helpers_escape_user_text():
    assert ui_components.chip("<위험>", "danger") == '<span class="chip chip-danger">&lt;위험&gt;</span>'
    assert 'role="alert"' in ui_components.notice("<실패>", "danger")
    row = ui_components.list_row("<상호>", "1,000", "메타", "/row?id=1&x=2")
    assert "&lt;상호&gt;" in row
    assert "&amp;" in row


def test_structural_helpers_emit_required_landmarks():
    tabs = ui_components.view_tabs([("지출", "expenses", "내용")])
    assert 'role="tablist"' in tabs and 'role="tabpanel"' in tabs
    assert 'class="drawer"' in ui_components.drawer("detail", "상세", "본문")
    assert 'aria-live="polite"' in ui_components.file_drop("files", ".csv", True, "업로드")
    assert 'class="steps"' in ui_components.steps([("완료", "done", "기록")])
