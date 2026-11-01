"""Shared CSV envelope and immutable source-byte verification for imports.

Profiles retain their columns, errors, identities and financial classification.
"""
import csv
import hashlib
import io


def verify_source_bytes(conn, batch_id):
    row = conn.execute('SELECT sha256, content FROM source_blobs WHERE batch_id=?', (batch_id,)).fetchone()
    return row is not None and row[0] == hashlib.sha256(bytes(row[1])).hexdigest()


def parse_csv_rows(content, required_columns, error_type, error_code):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise error_type(error_code, 'CSV를 읽을 수 없어요') from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise error_type(error_code, '머리글 행이 없어요')
    missing = [column for column in required_columns if column not in reader.fieldnames]
    if missing:
        raise error_type(error_code, f"필수 열이 없어요: {','.join(missing)}")
    rows = []
    for index, raw in enumerate(reader):
        if all((value or '').strip() == '' for value in raw.values()):
            continue
        rows.append((index, {key: (value or '').strip() for key, value in raw.items()}))
    return rows
