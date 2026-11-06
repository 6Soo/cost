"""Read-only layout for expense cleanup and the existing card review tools."""
from pathlib import Path
import re

_STATIC = Path(__file__).parent / 'static'
STYLE = (_STATIC / 'css' / 'expense_workspace.css').read_text(encoding='utf-8').replace('#expense-cleanup', 'main #expense-cleanup')
SCRIPT = (_STATIC / 'js' / 'expense_workspace.js').read_text(encoding='utf-8')


def _required_match(markup: str, pattern: str, name: str):
    matches = list(re.finditer(pattern, markup, re.IGNORECASE | re.DOTALL))
    if len(matches) != 1:
        raise ValueError(f'expense workspace requires exactly one {name}; found {len(matches)}')
    return matches[0]


def _set_attribute(tag: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf'(?P<lead>\s{re.escape(name)}\s*=\s*)'
        r'(?:(?P<quote>["\'])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^\s/>]+))', re.I)
    match = pattern.search(tag)
    if match:
        quote = match.group('quote') or '"'
        return tag[:match.start()] + match.group('lead') + quote + value + quote + tag[match.end():]
    return tag[:-1] + f' {name}="{value}">'


def _tag_with_id_pattern(tag_name: str, element_id: str) -> str:
    value = re.escape(element_id)
    return rf'<{tag_name}\b(?=[^>]*\sid\s*=\s*(?:"{value}"|\'{value}\'|{value}(?=[\s/>])))[^>]*>'


def _panel_tag(markup: str, panel_id: str, view: str) -> str:
    match = _required_match(markup, _tag_with_id_pattern('details', panel_id), f'{panel_id} panel')
    tag = _set_attribute(match.group(), 'role', 'tabpanel')
    tag = _set_attribute(tag, 'aria-labelledby', f'expense-tab-{view}')
    return markup[:match.start()] + tag + markup[match.end():]


def decorate(markup: str, *, page_title: str = '지출 정리') -> str:
    from .ui_icons import icon

    if page_title not in {'지출 정리', '카드 거래 상세'}:
        raise ValueError('unsupported expense workspace page title')
    if '<!--EXPENSE_CLEANUP-->' in markup:
        raise ValueError('expense workspace cleanup marker already exists in source markup')
    title_match = _required_match(
        markup, rf'<h1\b[^>]*>\s*{re.escape(page_title)}\s*</h1\s*>', 'page heading')
    for target in ('saved-materials', 'newupload', 'rules'):
        _required_match(markup, _tag_with_id_pattern('details', target), f'{target} panel')
    status_tag = _tag_with_id_pattern('p', 'status')
    _required_match(markup, status_tag[:-1] + r'>.*?</p\s*>', 'status element')
    _required_match(markup, r'<main\b[^>]*>', 'main element')
    _required_match(markup, r'</main\s*>', 'main closing tag')
    _required_match(
        markup, r'</style\s*>(?P<gap>\s*)(?P<head></head\s*>\s*)?(?P<body><body\b[^>]*>)',
        'style/body boundary')
    _required_match(markup, r'</body\s*>', 'body closing tag')

    task_label = '정리할 지출' if page_title == '지출 정리' else '카드 거래'
    tabs = [
        f'<button type="button" id="expense-tab-{key}" role="tab" '
        f'aria-controls="{panel}" aria-selected="{str(key == "cleanup").lower()}" '
        f'tabindex="{0 if key == "cleanup" else -1}" data-expense-view="{key}">'
        f'{icon(symbol)}<span>{label}</span></button>'
        for key, panel, symbol, label in (
            ('cleanup', 'expense-overview', 'list', task_label),
            ('upload', 'newupload', 'upload', '카드 업로드'),
            ('saved', 'saved-materials', 'list', '저장된 자료'),
            ('rules', 'rules', 'pencil', '분류 규칙'),
        )
    ]
    heading = (
        f'<header class="expense-heading"><div><h1>{page_title}</h1>'
        '</div></header>'
        f'<nav class="expense-tabs" role="tablist" aria-label="{page_title} 도구">' + ''.join(tabs[:2])
        + '<details class="expense-tools"><summary>자료·규칙 관리</summary><div>'
        + ''.join(tabs[2:]) + '</div></details></nav>'
        '<section id="expense-overview" role="tabpanel" aria-labelledby="expense-tab-cleanup">'
        '<!--EXPENSE_CLEANUP--></section>'
        '<details id="card-review-detail"><summary>선택한 카드 자료</summary>'
    )
    source_heading = title_match.group()
    source_opening = re.match(r'<h1\b[^>]*>', source_heading, re.I).group()
    source_closing = re.search(r'</h1\s*>$', source_heading, re.I).group()
    source_contents = source_heading[len(source_opening):-len(source_closing)]
    heading = heading.replace(f'<h1>{page_title}</h1>', source_opening + source_contents + source_closing, 1)
    markup = markup[:title_match.start()] + heading + markup[title_match.end():]
    # Keep original IDs, details.open and event handlers used by upload/review.
    # Only their presentation changes; financial actions stay in card_flow.
    for target, key in (('saved-materials', 'saved'), ('newupload', 'upload'), ('rules', 'rules')):
        markup = _panel_tag(markup, target, key)
    status_match = _required_match(markup, status_tag[:-1] + r'>.*?</p\s*>', 'status element')
    markup = markup[:status_match.end()] + '<section id="expense-transactions" aria-label="선택한 자료의 거래">' + markup[status_match.end():]
    main_close = _required_match(markup, r'</main\s*>', 'main closing tag')
    markup = markup[:main_close.start()] + '</section></details>' + markup[main_close.start():]
    style_body_match = _required_match(
        markup, r'</style\s*>(?P<gap>\s*)(?P<head></head\s*>\s*)?(?P<body><body\b[^>]*>)',
        'style/body boundary')
    style_end = re.match(r'</style\s*>', style_body_match.group()).group()
    gap = style_body_match.group('gap')
    head = style_body_match.group('head') or ''
    body = style_body_match.group('body')
    replacement = style_end + gap + '<style>' + STYLE + '</style>' + head + body
    markup = markup[:style_body_match.start()] + replacement + markup[style_body_match.end():]
    body_close = _required_match(markup, r'</body\s*>', 'body closing tag')
    markup = markup[:body_close.start()] + '<script>' + SCRIPT + '</script>' + markup[body_close.start():]
    if markup.count('<!--EXPENSE_CLEANUP-->') != 1:
        raise ValueError('expense workspace must emit exactly one cleanup marker')
    return markup
