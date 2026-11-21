"""Write golden JSONL records for the synthetic parser-vector generators.

Each vector generator under ``tools/core_bridge`` builds a list of synthetic case
records and publishes them as JSONL for the cross-language tests. This module
holds that shared file-writing contract so the next vector family does not
re-implement it.
"""

import json
from pathlib import Path


def write_jsonl(path: Path, records) -> tuple[int, Path]:
    """Write one sorted-key JSON object per line, refusing to overwrite.

    Mirrors the contract the vector generators kept inline: UTF-8 text with
    ``ensure_ascii=False`` and sorted keys, one record per line with a trailing
    newline, no implicit overwrite, and a missing parent directory created.
    Returns ``(record count, path)`` like the inline versions.
    """
    lines = ''.join(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n' for record in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as handle:
            handle.write(lines.encode('utf-8'))
    except FileExistsError:
        # Exclusive creation keeps the "never overwrite" promise without a
        # separate exists/write window; the message matches the inline code.
        raise SystemExit(f'{path} already exists; refusing to overwrite') from None
    return len(records), path
