"""The saved passenger index is used only when its input fingerprint and parser match.

Every name here is synthetic.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import flight_evidence
from webapp import ota_payment_review as ota


class FakeService:
    def __init__(self, key, current=None):
        self._key = key
        self._current = current

    def held(self):
        return (self._current, True) if self._current is not None else (None, False)

    def checked_key(self):
        return self._key


class FakeBoard:
    def __init__(self, service):
        self._ota_snapshot_service = service


class PassengerIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("WEBLEDGER_OTA_REVIEW_DB")
        os.environ["WEBLEDGER_OTA_REVIEW_DB"] = str(Path(self.tmp) / "ota-review.sqlite")
        ota._PASSENGER_CACHE.clear()
        self.path = Path(self.tmp) / ota.PASSENGER_FILE
        self.index = {"R-1": {"names": ["KIM ALPHA"], "conflict": False}}

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("WEBLEDGER_OTA_REVIEW_DB", None)
        else:
            os.environ["WEBLEDGER_OTA_REVIEW_DB"] = self._prev

    def publish(self, key):
        ota._write_passenger_index(self.path, {"key": key, "data": {"passengers": self.index}})

    def test_a_saved_index_is_used_when_its_fingerprint_and_parser_match(self):
        self.publish("k1")
        board = FakeBoard(FakeService("k1"))
        self.assertEqual(ota.passenger_index_for(board), self.index)

    def test_a_changed_input_fingerprint_gives_no_names(self):
        self.publish("k1")
        self.assertEqual(ota.passenger_index_for(FakeBoard(FakeService("k2"))), {})

    def test_a_different_parser_version_gives_no_names(self):
        self.publish("k1")
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["parser"] = "older-parser"
        self.path.write_text(json.dumps(document), encoding="utf-8")
        ota._PASSENGER_CACHE.clear()
        self.assertEqual(ota.passenger_index_for(FakeBoard(FakeService("k1"))), {})

    def test_the_in_memory_index_of_the_current_refresh_wins(self):
        self.publish("k1")
        current = {"key": "k2", "data": {"passengers": {"R-9": {"names": ["LEE BETA"], "conflict": False}}}}
        board = FakeBoard(FakeService("k2", current))
        self.assertEqual(ota.passenger_index_for(board), current["data"]["passengers"])

    def test_nothing_is_saved_without_a_refreshed_index(self):
        ota._write_passenger_index(self.path, {"key": "k1"})
        self.assertFalse(self.path.exists())

    def test_the_saved_file_carries_the_parser_and_fingerprint_only_with_names(self):
        self.publish("k1")
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(document["parser"], flight_evidence.PARSER_VERSION)
        self.assertEqual(document["key"], "k1")
        self.assertEqual(set(document), {"schema", "key", "parser", "passengers"})


if __name__ == "__main__":
    unittest.main()
