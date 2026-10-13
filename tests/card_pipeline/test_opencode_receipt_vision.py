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


def test_model_pinned_tools_denied_and_tickets_not_deduplicated(ready):
    calls = []
    def invoke(command, **kwargs):
        calls.append(command)
        settings = json.loads((Path(kwargs["cwd"]) / "opencode.json").read_text())
        assert settings["permission"] == {"*": "deny"}
        assert settings["agent"]["receipt-readonly"]["permission"] == {"*": "deny"}
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
