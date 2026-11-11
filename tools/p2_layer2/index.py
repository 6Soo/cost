"""Build the private offline mail index from a verified backup (never live DB)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib


def build(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    private = Path(__file__).resolve().parents[2] / '.local-archive'
    if not output.is_relative_to(private) or output.exists() or source == output:
        raise ValueError('NEW_PRIVATE_OUTPUT_REQUIRED')
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(output)
    try:
        dst.execute('CREATE TABLE evidence(message_id TEXT PRIMARY KEY, subject TEXT, sender TEXT, sent_date TEXT, body TEXT, digest TEXT)')
        for mid, blob in src.execute('SELECT message_id,payload_json FROM ota_messages'):
            data = json.loads(zlib.decompress(blob))
            payload = data.get('payload', {})
            headers = {h.get('name', '').lower(): h.get('value', '') for h in payload.get('headers', [])}
            def walk(part):
                body = (part.get('body') or {}).get('content')
                values = [body] if isinstance(body, str) else []
                for child in part.get('parts') or []:
                    values.extend(walk(child))
                return values
            values = [headers.get('subject', ''), headers.get('from', ''), headers.get('date', ''), '\n'.join(walk(payload))]
            digest = hashlib.sha256('\n'.join(values).encode()).hexdigest()
            dst.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)', (mid, *values, digest))
            count += 1
        dst.commit()
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()
    return {'messages': count, 'db_bytes': output.stat().st_size}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.backup, args.output)))
