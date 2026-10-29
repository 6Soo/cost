from pathlib import Path


SOURCE = Path(__file__).parents[1] / 'card_flow.py'


def test_upload_response_summary_contract_is_ui_only():
    source = SOURCE.read_text(encoding='utf-8')
    for token in ('renderUploadSummary', 'upload_summary', 'monthly_reconciliation',
                  'unknown_date_reconciliation', 'financial_warning', 'masked_identity',
                  "['T','total']", "['R','rejected']"):
        assert token in source
    assert 'CREATE TABLE' not in source[source.index('function renderUploadSummary'):source.index('function render(j')]
