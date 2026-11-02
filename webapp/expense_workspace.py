"""Read-only layout for expense cleanup and the existing card review tools."""
from pathlib import Path

_STATIC = Path(__file__).parent / 'static'
STYLE = (_STATIC / 'css' / 'expense_workspace.css').read_text(encoding='utf-8').replace('#expense-cleanup', 'main #expense-cleanup')
SCRIPT = (_STATIC / 'js' / 'expense_workspace.js').read_text(encoding='utf-8')


def decorate(markup: str) -> str:
    from .ui_icons import icon

    tabs = ''.join(
        f'<button type="button" id="expense-tab-{key}" role="tab" '
        f'aria-controls="{panel}" aria-selected="{str(key == "cleanup").lower()}" '
        f'tabindex="{0 if key == "cleanup" else -1}" data-expense-view="{key}">'
        f'{icon(symbol)}<span>{label}</span></button>'
        for key, panel, symbol, label in (
            ('cleanup', 'expense-overview', 'list', '정리할 지출'),
            ('saved', 'saved-materials', 'list', '저장된 자료'),
            ('upload', 'newupload', 'upload', '카드 업로드'),
            ('rules', 'rules', 'pencil', '분류 규칙'),
        )
    )
    heading = (
        '<header class="expense-heading"><div><h1>지출 정리</h1>'
        '<p>확인이 필요한 지출을 정리하고, 카드 자료와 분류 규칙을 관리하세요.</p>'
        '</div><a class="expense-all-link" href="/import?scope=all">'
        + icon('credit-card') + '전체 카드 내역' + icon('chevron-right') + '</a></header>'
        '<nav class="expense-tabs" role="tablist" aria-label="지출 정리 작업">' + tabs + '</nav>'
        '<section id="expense-overview" role="tabpanel" aria-labelledby="expense-tab-cleanup">'
        '<!--EXPENSE_CLEANUP--></section>'
        '<details id="card-review-detail"><summary>선택한 카드 자료</summary>'
    )
    markup = markup.replace('<h1>지출 정리</h1>', heading, 1)
    # Keep original IDs, details.open and event handlers used by upload/review.
    # Only their presentation changes; financial actions stay in card_flow.
    for target, key in (('saved-materials', 'saved'), ('newupload', 'upload'), ('rules', 'rules')):
        markup = markup.replace(
            f'<details id="{target}">',
            f'<details id="{target}" role="tabpanel" aria-labelledby="expense-tab-{key}">', 1)
    markup = markup.replace('<p id="status" role="status"></p>', '<p id="status" role="status"></p><section id="expense-transactions" aria-label="선택한 자료의 거래">', 1)
    markup = markup.replace('</main>', '</section></details></main>', 1)
    markup = markup.replace('</style><body>', '</style><style>' + STYLE + '</style><body>', 1)
    return markup.replace('</body>', '<script>' + SCRIPT + '</script></body>', 1)
