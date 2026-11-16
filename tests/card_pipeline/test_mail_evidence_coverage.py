import json
from datetime import datetime

import pytest

from app import mail_collect
from tests.card_pipeline.test_mail_collect import FakeGmail


def test_forwarded_owner_evidence_backfills_before_polling_start_without_auth_rewrite(tmp_path):
    class Forwarded(FakeGmail):
        def list_ids(self, query):
            self.queries.append(query)
            return ['old-forward'] if 'label:' in query and 'before:2026/04/01' in query else []

    client = Forwarded([])
    cursor = b'{"before":"2026-11-15","message_ids":[]}'
    (tmp_path / 'collection.json').write_bytes(cursor)
    # An old successful checkpoint must not conceal an expanded evidence scope.
    (tmp_path / 'history-reconciliation.json').write_text(json.dumps({
        'completed_on':'2026-11-16', 'after':mail_collect.HISTORY_START,
        'supplier_after':mail_collect.SUPPLIER_HISTORY_START}), encoding='utf-8')
    result = mail_collect.reconcile_history(client, tmp_path, datetime(2026, 11, 16))
    assert result['fetched'] == 1 and not result['skipped']
    query = client.queries[-1]
    assert 'label:"결제데이터"' in query
    assert query.endswith(' before:2026/11/17')
    assert 'after:2025/04/01 before:2026/04/01' in query
    assert (tmp_path / 'collection.json').read_bytes() == cursor
    stored = json.loads(next(tmp_path.glob('gmail-window-*.json')).read_text(encoding='utf-8'))
    assert stored['responses'] == [client.get_full('old-forward')]
    assert 'owner_collected' not in stored['responses'][0]
    calls = len(client.queries)
    assert mail_collect.reconcile_history(client, tmp_path, datetime(2026,11,16))['skipped']
    assert len(client.queries) == calls


@pytest.mark.parametrize('scope', [{'suppliers_only':True}, {'forest_only':True}])
def test_owner_history_cannot_expand_an_unrelated_scope(tmp_path, scope):
    with pytest.raises(ValueError, match='MAIL_OWNER_HISTORY_SCOPE_INVALID'):
        mail_collect.collect_window(FakeGmail([]), tmp_path, '2026-04-01', '2026-11-17',
                                    owner_history_after='2025-04-01', **scope)
