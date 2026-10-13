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


def receipt(box, amount=820):
    return {"box": box, "merchant": "豊島フェリー", "date": "2026-09-20",
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
        return event([receipt([.1,.1,.3,.3]), receipt([.4,.1,.6,.3])])
    result = vision.recognize(ready, runner=invoke)
    assert len(calls) == 1
    assert len(result["receipts"]) == 2
    assert result["receipts"][0]["id"] != result["receipts"][1]["id"]
    assert result["confirmed"] is False and result["trip_inferred"] is False


def test_missing_fields_are_not_guessed(ready):
    slip = receipt([.1,.1,.3,.3], amount=None)
    response = vision.recognize(ready, runner=lambda *a,**k: event([slip]))
    assert response["receipts"][0]["payment"] is None
    assert response["receipts"][0]["amount"] is None
    assert response["receipts"][0]["requires_review"] is True


@pytest.mark.parametrize("box", [[.3,.3,.1,.1], [0,0,1.01,1]])
def test_invalid_boxes_blocked(ready, box):
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(ready, runner=lambda *a,**k: event([receipt(box)]))
    assert error.value.code == "VISION_BOX_INVALID"


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



def test_pixel_boxes_dates_and_payment_words_are_normalized_not_guessed():
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1240).to_bytes(4, "big") + (1754).to_bytes(4, "big")
    assert vision.image_size(png_header + b"\x00" * 8) == (1240, 1754)
    assert vision.image_size(b"not an image") is None
    raw = {"receipts": [{"box": [124, 175.4, 620, 877], "merchant": "A", "date": "2026/10/01 12:30",
                         "amount": 820, "currency": "jpy", "payment": "CASH", "category_hint": None, "note": None},
                        {"box": [.1, .1, .3, .3], "merchant": "B", "date": "2026/13/40", "amount": 5,
                         "currency": "USD", "payment": "credit card", "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h", size=(1240, 1754))["receipts"]
    assert rows[0]["box"] == [0.1, 0.1, 0.5, 0.5]
    assert rows[0]["date"] == "2026-10-01" and rows[0]["currency"] == "JPY" and rows[0]["payment"] == "cash"
    assert rows[1]["date"] is None and rows[1]["currency"] is None and rows[1]["payment"] is None


def test_an_entry_with_no_merchant_date_or_amount_is_not_a_candidate():
    raw = {"receipts": [{"box": [0, 0, 1000, 1000], "merchant": None, "date": None, "amount": None,
                         "currency": None, "payment": None, "category_hint": None, "note": None},
                        {"box": [0.1, 0.1, 0.4, 0.4], "merchant": "A", "date": "2026-10-01", "amount": 820,
                         "currency": "JPY", "payment": None, "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h", size=None)["receipts"]
    assert len(rows) == 1 and rows[0]["merchant"] == "A"


def test_a_placed_receipt_survives_an_unplaceable_neighbour_and_numeric_text_amounts():
    raw = {"receipts": [{"box": None, "merchant": "A", "date": "2026-10-01", "amount": "1,200",
                         "currency": "JPY", "payment": None, "category_hint": None, "note": None},
                        {"box": None, "merchant": "B", "date": "2026-10-02", "amount": 300,
                         "currency": "KRW", "payment": None, "category_hint": None, "note": None}]}
    rows = vision.validate_response(raw, image_hash="h", size=None)["receipts"]
    assert [r["amount"] for r in rows] == [1200, 300]
    assert rows[0]["box"] is None and rows[1]["box"] is None
    with pytest.raises(vision.VisionUnavailable):
        vision.validate_response({"receipts": [{"box": [5, 9], "merchant": "A", "date": None, "amount": 1, "currency": "JPY", "payment": None, "category_hint": None, "note": None}]}, image_hash="h", size=None)
