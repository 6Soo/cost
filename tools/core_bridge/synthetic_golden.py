"""Write synthetic parser-vector goldens as JSONL without overwriting."""
import json
from pathlib import Path


def write_jsonl(path: Path, records) -> tuple[int, Path]:
    """Publish synthetic case records as UTF-8 JSONL; refuse to overwrite."""
    data = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as handle:
            handle.write(data.encode('utf-8'))
    except FileExistsError:
        raise SystemExit(f'{path} already exists; refusing to overwrite') from None
    except OSError:
        # A directory never reaches the exclusive create as an error worth
        # showing differently: hold the historical refusal contract.
        if path.is_dir():
            raise SystemExit(f'{path} already exists; refusing to overwrite') from None
        raise
    return len(records), path
