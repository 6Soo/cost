"""같은 DB의 장부·감사 원자성과 과거 이력 보존을 검증한다."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webapp.ledger_store import LedgerStore
from webapp.operator_ledger import OperatorLedger, LedgerError
from webapp.real_review import DecisionsStore
from webapp.db_merge import merge_review_database


class UnifiedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'board.sqlite'
        self.environment = patch.dict(os.environ, {'WEBLEDGER_UNIFIED_DB': '1'})
        self.environment.start()
        self.store = LedgerStore(self.path)

    def tearDown(self):
        self.store.close()
        self.environment.stop()
        self.directory.cleanup()

    def test_no_sidecar_and_atomic_rollback(self):
        self.assertIs(self.store.conn, self.store.ledger.conn)
        self.assertFalse(self.path.with_suffix('.operator.sqlite').exists())
        self.assertFalse(Path(str(self.path) + '.checkpoint.json').exists())
        self.store.conn.execute('BEGIN IMMEDIATE')
        self.store._enqueue_ledger(outbox_id='atomic', stream_id='row-x',
                                  action='propose', target='x', rationale='test', actor='owner')
        self.assertEqual(len(self.store.ledger.all_events()), 1)
        self.store.conn.rollback()
        self.assertEqual(len(self.store.ledger.all_events()), 0)
        self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM ledger_outbox').fetchone()[0], 0)

    def test_saved_row_and_audit_replay_together(self):
        request = dict(row_id='expense-demo-c1', expected_revision=1,
                       client_request_id='same-request', change_mode='exception',
                       changes={'item': '교통비'})
        first = self.store.save(**request)
        self.assertEqual(first, self.store.save(**request))
        self.assertEqual(len(self.store.ledger.all_events()), 1)
        self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM ledger_outbox WHERE relayed=0').fetchone()[0], 0)
        self.store.close()
        self.store = LedgerStore(self.path)
        self.assertEqual(len(self.store.ledger.all_events()), 1)
        self.assertEqual(self.store.get_row('expense-demo-c1')['item'], '교통비')
        self.assertTrue(self.store.ledger.verify_chain()['ok'])

    def test_audit_request_content_conflict(self):
        values = dict(stream_id='s', action='propose', rationale='one', client_request_id='r')
        self.store.ledger.append(**values)
        with self.assertRaises(LedgerError):
            self.store.ledger.append(**{**values, 'rationale': 'two'})

    def test_legacy_history_import_preserves_source_and_is_repeatable(self):
        self.store.close()
        legacy_path = self.path.with_suffix('.operator.sqlite')
        legacy = OperatorLedger.create(legacy_path)
        event, _ = legacy.append(stream_id='old', action='propose', rationale='legacy',
                                 client_request_id='legacy-request')
        legacy.conn.close()
        before = legacy_path.read_bytes()
        self.store = LedgerStore(self.path)
        self.assertEqual(self.store.ledger.get_event(event['event_id']), event)
        self.store.close()
        self.store = LedgerStore(self.path)
        self.assertEqual(len(self.store.ledger.all_events()), 1)
        self.assertEqual(legacy_path.read_bytes(), before)

    def test_review_migration_preserves_choices_then_keeps_newer_answer(self):
        source = self.path.parent / 'review.sqlite'
        old = DecisionsStore(str(source))
        old.save('binding', {'row':'APPROVE'}, 0)
        before = source.read_bytes()
        merge_review_database(self.path, source)
        merged = DecisionsStore(str(self.path))
        self.assertEqual(merged.load('binding'), old.load('binding'))
        merged.save('binding', {'row':'REJECT'}, 1)
        merge_review_database(self.path, source)
        self.assertEqual(merged.load('binding')['choices'], {'row':'REJECT'})
        self.assertEqual(source.read_bytes(), before)

    def test_review_conflict_leaves_target_unchanged(self):
        source = self.path.parent / 'review.sqlite'
        old = DecisionsStore(str(source))
        old.save('binding', {'row':'APPROVE'}, 0)
        current = DecisionsStore(str(self.path))
        current.save('binding', {'row':'REJECT'}, 0)
        with self.assertRaisesRegex(ValueError,'CONTENT_CONFLICT'):
            merge_review_database(self.path, source)
        self.assertEqual(current.load('binding')['choices'], {'row':'REJECT'})


if __name__ == '__main__':
    unittest.main()
