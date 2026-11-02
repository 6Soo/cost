import os
import subprocess
import pytest
"""No network or real Muse call: exercise pinned-model CLI and untrusted JSON."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import opencode_receipt_vision as vision


@pytest.fixture
def ready(monkeypatch, tmp_path):
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setattr(vision.shutil, "which", lambda name: "opencode.cmd")
    page = tmp_path / "page.jpg"
    page.write_bytes(b"\xff\xd8\xff" + b"x" * 30 + b"\xff\xd9")
    return page


def event(slips):
    data = json.dumps({"receipts": slips}, ensure_ascii=False)
    return SimpleNamespace(returncode=0, stdout=(json.dumps({
        "type": "text", "part": {"type": "text", "text": data}
    }, ensure_ascii=False) + "\n").encode(), stderr=b"")


def receipt(amount=820):
    return {"merchant": "豊島フェリー", "date": "2026-09-20",
            "amount": amount, "currency": "JPY", "payment": None,
            "category_hint": "교통비", "note": None}


def test_model_pinned_tools_need_approval_and_tickets_not_deduplicated(ready):
    calls = []
    def invoke(command, **kwargs):
        calls.append(command)
        settings = json.loads((Path(kwargs["cwd"]) / "opencode.json").read_text())
        assert settings["permission"] == {"*": "ask"}
        assert settings["agent"]["receipt-readonly"]["permission"] == {"*": "ask"}
        assert "XDG_CONFIG_HOME" in kwargs["env"]
        assert "--auto" not in command
        assert command[command.index("--model")+1] == vision.MODEL
        assert any(arg.startswith("--file=") and arg.endswith(".jpg") for arg in command)
        assert command[command.index("--")+1] == vision.PROMPT
        assert "--pure" in command
        return event([receipt(), receipt()])
    result = vision.recognize(ready, runner=invoke)
    assert len(calls) == 1
    assert len(result["receipts"]) == 2
    assert result["receipts"][0]["id"] != result["receipts"][1]["id"]
    assert result["confirmed"] is False and result["trip_inferred"] is False


def test_missing_fields_are_not_guessed(ready):
    slip = receipt(amount=None)
    response = vision.recognize(ready, runner=lambda *a,**k: event([slip]))
    assert response["receipts"][0]["payment"] is None
    assert response["receipts"][0]["amount"] is None
    assert response["receipts"][0]["requires_review"] is True


def test_non_json_fails_closed(ready):
    proc = SimpleNamespace(returncode=0,
            stdout=b'{"type":"text","part":{"type":"text","text":"Hello"}}\n',
            stderr=b"")
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(ready, runner=lambda *a,**k: proc)
    assert error.value.code == "VISION_RESPONSE_INVALID"


def test_disabled_does_not_run(monkeypatch, tmp_path):
    monkeypatch.setattr(vision, "enabled", lambda: False)
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(tmp_path/"missing.jpg", runner=lambda *a,**k: pytest.fail("called"))
    assert error.value.code == "VISION_DISABLED"


def test_a_command_past_the_time_limit_is_stopped_with_its_children(monkeypatch):
    """A shim that keeps a child process alive must not hold the worker forever."""
    import time
    monkeypatch.setattr(vision, "TIMEOUT_SECONDS", 2)
    started = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        vision._run_bounded(["cmd", "/c", "ping -n 120 127.0.0.1 >nul"], cwd=".", env=dict(os.environ))
    assert time.time() - started < 30



def test_dates_currency_payment_are_normalized_and_unclear_fields_become_null():
    raw = {"receipts": [{"merchant": "A", "date": "2026/10/01 12:30", "amount": 820, "currency": "jpy",
                         "payment": "CASH", "category_hint": None, "note": None},
                        {"merchant": "B", "date": "2026/13/40", "amount": "abc", "currency": "USD",
                         "payment": "credit card", "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h")["receipts"]
    assert [r["merchant"] for r in rows] == ["A", "B"]
    assert rows[0]["date"] == "2026-10-01" and rows[0]["currency"] == "JPY" and rows[0]["payment"] == "cash"
    assert rows[1]["date"] is None and rows[1]["amount"] is None
    assert rows[1]["currency"] is None and rows[1]["payment"] is None
    assert all(r["box"] is None for r in rows)


def test_an_entry_with_no_merchant_date_or_amount_is_not_a_candidate():
    raw = {"receipts": [{"merchant": None, "date": None, "amount": None,
                         "currency": None, "payment": None, "category_hint": None, "note": None},
                        {"merchant": "A", "date": "2026-10-01", "amount": 820,
                         "currency": "JPY", "payment": None, "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h")["receipts"]
    assert len(rows) == 1 and rows[0]["merchant"] == "A"


def test_identical_tickets_stay_separate_whatever_the_order():
    ticket = {"merchant": "A", "date": "2026-10-01", "amount": 820, "currency": "JPY",
              "payment": None, "category_hint": None, "note": None}
    rows = vision.validate_response({"receipts": [ticket, ticket]}, image_hash="h")["receipts"]
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    reordered = vision.validate_response({"receipts": [ticket, ticket]}, image_hash="h")["receipts"]
    assert [r["id"] for r in rows] == [r["id"] for r in reordered]


def test_numeric_text_amounts_are_read_and_model_boxes_are_ignored():
    raw = {"receipts": [{"box": [5, 9, 100, 200], "merchant": "A", "date": "2026-10-01", "amount": "1,200",
                         "currency": "JPY", "payment": None, "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h")["receipts"]
    assert rows[0]["amount"] == 1200 and rows[0]["box"] is None


def test_normalized_boxes_are_requested_and_strictly_preserved_or_cleared():
    valid = {"box": [0.1, 0.2, 0.8, 0.9], "merchant": "A", "date": "2026-10-01",
             "amount": 820, "currency": "JPY", "payment": None}
    invalid = {"box": [0.8, 0.2, 0.1, 0.9], "merchant": "B", "date": None,
               "amount": 1, "currency": "JPY", "payment": None}
    nonfinite = {"box": [0, 0, float("inf"), 1], "merchant": "C", "date": None,
                 "amount": 2, "currency": "JPY", "payment": None}
    rows = vision.validate_response({"receipts": [valid, invalid, nonfinite]}, image_hash="h")["receipts"]
    assert rows[0]["box"] == [0.1, 0.2, 0.8, 0.9]
    assert rows[1]["box"] is None and rows[2]["box"] is None
    assert all(row["requires_review"] for row in rows)

    without_box = {key: value for key, value in valid.items() if key != "box"}
    assert vision.validate_response({"receipts": [without_box]}, image_hash="h")["receipts"][0]["id"] == \
        vision.validate_response({"receipts": [{**without_box, "box": None}]}, image_hash="h")["receipts"][0]["id"]


def test_extremely_large_box_coordinate_becomes_unknown():
    raw = {"receipts": [{"box": [0, 0, 10**400, 1], "merchant": "A", "amount": 820}]}
    assert vision.validate_response(raw, image_hash="h")["receipts"][0]["box"] is None
