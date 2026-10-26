"""CPU-heavy catalog source parsing with an independent read-only board snapshot."""
import pickle
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace


def run(board_path, request_path, result_path):
    from . import ota_catalog
    try:
        sources = pickle.loads(Path(request_path).read_bytes())
        conn = sqlite3.connect(Path(board_path).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            board = SimpleNamespace(conn=conn, _lock=threading.RLock())
            warnings = []
            rows = ota_catalog._rows_from_sources(board, sources, warnings)
            payload = ('ok', rows, warnings)
        finally:
            conn.close()
    except Exception as exc:
        # No source content, paths or customer data in error messages.
        payload = ('error', type(exc).__name__)
    Path(result_path).write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
