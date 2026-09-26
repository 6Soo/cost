from __future__ import annotations

import argparse
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

parser = argparse.ArgumentParser(description="Run the web-ledger fixed candidate.")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--db", default=str(HERE / "runtime" / "board.sqlite"))
args = parser.parse_args()

db_path = pathlib.Path(args.db)
db_path.parent.mkdir(parents=True, exist_ok=True)
os.environ["WEBLEDGER_DB"] = str(db_path)
os.environ["WEBLEDGER_EXPORT_DIR"] = str(db_path.parent / "exports")

from webapp import ledger_board as board_mod

# serve() creates + binds its own LedgerStore on db_path (seeding the demo
# board on first run) and binds the card importer, then serves on 127.0.0.1.
server = board_mod.serve(port=args.port, db_path=db_path, with_worker=True)
base = f"http://127.0.0.1:{args.port}"
print(f"serving fixed candidate on {base}")
print(f"db: {db_path}")
print("screens:")
for path in ("/board", "/import", "/export",
             "/income/income-demo-i1/split"):
    print(f"  {base}{path}")
print(f"  {base}/rules?case=<learning_case_id>   "
      "(needs a case; bare /rules answers 404)")
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    worker = getattr(server, "card_worker", None)
    if worker is not None:
        worker.stop(timeout=5)
    server.shutdown()
    server.server_close()
    board_mod.bind_store(None)
