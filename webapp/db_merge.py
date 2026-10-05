"""별도 검토 DB의 저장된 결정을 장부 DB로 한 번 보존 이관한다."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

REVIEW_TABLES = ('review_choice_sets', 'review_source_guidance',
                 'review_guidance_requests', 'review_guidance_previews',
                 'review_guidance_results')


def merge_review_database(target_path, source_path):
    target, source = Path(target_path).resolve(), Path(source_path).resolve()
    if target == source or not source.is_file():
        return
    with closing(sqlite3.connect(target, isolation_level=None, timeout=10)) as dest:
        dest.execute('CREATE TABLE IF NOT EXISTS database_migrations '
                     '(source_path TEXT PRIMARY KEY, content_hash TEXT NOT NULL, counts_json TEXT NOT NULL)')
        if dest.execute('SELECT 1 FROM database_migrations WHERE source_path=?',
                        (str(source),)).fetchone():
            return
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
            old.execute('BEGIN')
            rows_by_table = {}
            schemas = {}
            for table in REVIEW_TABLES:
                schema = old.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                                     (table,)).fetchone()
                if schema is None:
                    continue
                columns = old.execute(f'PRAGMA table_info({table})').fetchall()
                rows_by_table[table] = (columns, old.execute(f'SELECT * FROM {table}').fetchall())
                schemas[table] = schema[0]
            if 'review_choice_sets' not in rows_by_table:
                raise ValueError('REVIEW_DATABASE_SCHEMA_MISSING')
            dest.execute('BEGIN IMMEDIATE')
            try:
                counts = {}
                for table, (columns, rows) in rows_by_table.items():
                    if not dest.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                        (table,)).fetchone():
                        dest.execute(schemas[table])
                    names = [column[1] for column in columns]
                    target_names = [column[1] for column in dest.execute(f'PRAGMA table_info({table})')]
                    if names != target_names:
                        raise ValueError('REVIEW_DATABASE_COLUMNS_DIFFER')
                    primary = [column[1] for column in sorted(columns, key=lambda c:c[5]) if column[5]]
                    if not primary:
                        raise ValueError('REVIEW_DATABASE_KEY_MISSING')
                    for row in rows:
                        key_values = tuple(row[names.index(key)] for key in primary)
                        existing = dest.execute(f'SELECT * FROM {table} WHERE '
                                                + ' AND '.join(f'{key}=?' for key in primary),
                                                key_values).fetchone()
                        if existing is not None and tuple(existing) != tuple(row):
                            raise ValueError('REVIEW_DATABASE_CONTENT_CONFLICT')
                        if existing is None:
                            dest.execute(f'INSERT INTO {table} VALUES ('
                                         + ','.join('?' for _ in row) + ')', row)
                    counts[table] = len(rows)
                semantic = json.dumps(rows_by_table, ensure_ascii=False, sort_keys=True, default=str)
                dest.execute('INSERT INTO database_migrations VALUES (?,?,?)',
                             (str(source),hashlib.sha256(semantic.encode()).hexdigest(),json.dumps(counts)))
                dest.commit()
            except Exception:
                dest.rollback()
                raise
