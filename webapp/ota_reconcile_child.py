"""One full OTA reconciliation in a child process, started only by ota_payment_review.reconcile_in_child.

A reconciliation is long CPU work in Python. Run as a thread of the server it
holds the interpreter lock in bursts, and each request that talks to SQLite waits
for every burst. In this process the request threads keep the lock to themselves.
"""
import pickle
from pathlib import Path


def run(root, board_path, request_path, result_path):
    import sys

    sys.path.insert(0, root)
    from webapp import ota_payment_review
    from webapp.ledger_store import LedgerStore

    request = pickle.loads(Path(request_path).read_bytes())
    store = LedgerStore(Path(board_path), seed_demo=False)
    try:
        store._reservation_authority = request.get("authority")
        payload = ("ok", ota_payment_review.reconcile(store))
    except Exception as exc:
        payload = ("error", type(exc).__name__, str(exc)[:200])
    finally:
        store.close()
    Path(result_path).write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
