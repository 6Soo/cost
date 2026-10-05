"""Read one referenced booking locally and emit only verification metadata."""
import json
from pathlib import Path

BOOKING = "1400821831501966"
ROOT = Path(__file__).resolve().parents[1]


def records(value, path=""):
    if isinstance(value, dict):
        if any(str(v) == BOOKING for v in value.values() if isinstance(v, (str, int))):
            yield path, value
        for key, child in value.items():
            yield from records(child, path + "/" + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from records(child, path + "/" + str(index))


if __name__ == "__main__":
    for name in ("ota_event_links_verified.json", "ota_lodging_facts_v2.json",
                 "ota_reconcile_report.json", "ota_mail_index.json"):
        path = ROOT / "ledger/data" / name
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        for locator, record in records(payload):
            print(json.dumps({"file": name, "record_path": locator,
                              "keys": sorted(record),
                              "metadata": {k: v for k, v in record.items()
                                           if isinstance(v, (str, int, bool, type(None)))
                                           and any(word in k.lower() for word in (
                                               "start", "end", "check", "date", "period",
                                               "target", "trip", "status", "verified",
                                               "sha256", "amount"))}}, ensure_ascii=False))
