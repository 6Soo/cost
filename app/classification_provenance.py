"""Classification execution origin, separate from completion and confidence."""

LABELS = {'automatic': '자동', 'code_inference': '코드 추론',
          'ai_inference': 'AI 추론', 'manual': '직접', 'unknown': '출처 미확인'}
CODE_SOURCES = frozenset(('inference', 'auto_inferred', 'code_inference'))
MANUAL_SOURCES = frozenset(('manual', 'user_decision', 'user_exception', 'previous_decision'))
AUTOMATIC_SOURCES = frozenset(('auto', 'rule', 'pattern', 'card_category', 'owner_booking',
                               'owner_card_residual', 'guide_airfare_evidence', 'refund_original'))


def origin(row):
    source = str(row.get('classification_source') or '').strip()
    # decided is also set by financial recording; only an actual decision counts.
    if row.get('decided_at') or source in MANUAL_SOURCES:
        return 'manual'
    if source == 'ai_inference':
        return 'ai_inference'
    if source in CODE_SOURCES or str(row.get('classification_basis') or '').startswith('AUTO_TRIP_INFERRED'):
        return 'code_inference'
    return 'automatic' if source in AUTOMATIC_SOURCES else 'unknown'


def label(row):
    return LABELS[origin(row)]
