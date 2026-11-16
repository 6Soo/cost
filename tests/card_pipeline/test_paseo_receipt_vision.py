"""No real model call: the Paseo OCR-hybrid reader with fake run/logs answers, its checks and the OCR fallback."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import local_receipt_ocr, receipt_vision
from app import paseo_receipt_vision as paseo

JPEG = b"\xff\xd8\xff" + b"x" * 30 + b"\xff\xd9"


@pytest.fixture
def ready(monkeypatch, tmp_path):
    monkeypatch.setattr(paseo, "enabled", lambda: True)
    monkeypatch.setenv("WEBLEDGER_NODE_EXE", sys.executable)
    cli = tmp_path / "paseo-cli.js"
    cli.write_text("// fake cli entry", encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_PASEO_CLI", str(cli))
    page = tmp_path / "page.jpg"
    page.write_bytes(JPEG)
    return page


def ocr_readings(image):
    return {"ja": "LAWSON 秋田駅前店\n合計 ¥1,164\nVISA ****1234", "ko": "0625_아키타"}


def reading(**changes):
    item = {"box": None, "merchant": "LAWSON 秋田駅前店", "date": "2026-06-26", "amount": 1164,
            "currency": "JPY", "payment": "card", "card_last4": "1234", "confidence": 0.9,
            "uncertain_fields": [], "note": None}
    item.update(changes)
    return item


def answer(receipts=None, header="0625_아키타", confidence=0.9, lesson=None):
    return {"header_text": header, "header_confidence": confidence,
            "receipts": [reading()] if receipts is None else receipts, "lesson": lesson}


def runner_for(answer_text, *, run_proc=None, workspace="wks_test123", calls=None):
    """Fake Paseo CLI: `run --output-schema` returns the schema-shaped JSON as stdout itself."""
    def runner(command, *, cwd, env, timeout, input_bytes=None):
        if calls is not None:
            calls.append(list(command))
        sub = command[3]
        if sub == "run":
            if run_proc is not None:
                return run_proc
            return SimpleNamespace(returncode=0, stdout=answer_text.encode("utf-8"),
                                   stderr=f"Created workspace {workspace}\n".encode())
        if sub == "workspace":
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        raise AssertionError("unexpected subcommand " + sub)
    return runner


def test_the_run_is_isolated_plan_mode_with_ocr_text_and_no_image(ready):
    seen = {}

    def runner(command, *, cwd, env, timeout, input_bytes=None):
        if command[3] == "run":
            seen.update(command=command, cwd=cwd, timeout=timeout, input_bytes=input_bytes)
        return runner_for(json.dumps(answer()))(command, cwd=cwd, env=env, timeout=timeout)
    result = paseo.recognize_with_fallback(ready, runner=runner, ocr=ocr_readings)
    command = seen["command"]
    assert command[command.index("--provider") + 1] == paseo.PROVIDER_MODEL
    assert command[command.index("--mode") + 1] == "plan"
    assert command[command.index("--new-workspace") + 1] == "local"
    assert command[command.index("--output-schema") + 1] == paseo._schema_text()
    prompt = command[-1]
    assert "LAWSON" in prompt and "0625_아키타" in prompt and "Schema:" in prompt
    assert receipt_vision.playbook_prompt(start="ocr-reading-prompt:start", end="ocr-reading-prompt:end") in prompt
    # The photo itself is never handed to the model: only OCR text, no base64 image payload.
    assert JPEG not in prompt.encode("utf-8", errors="ignore") and seen["input_bytes"] is None
    row, = result["receipts"]
    assert result["engine"] == "paseo" and result["label"] == paseo.MODEL_LABEL and result["confirmed"] is False
    assert result["header_text"] == "0625_아키타" and result["trip_inferred"] is False
    assert row["amount"] == 1164 and row["currency"] == "JPY" and row["requires_review"] and row["box"] is None
    # A receipt cannot say private or corporate card: payment stays open and the last digits go to the note.
    assert row["payment"] is None and row["card_last4"] == "1234" and row["note"] == "카드 끝자리 1234"
    assert result["attempts"] == [{"model": paseo.PROVIDER_MODEL, "result": "OK"}]


def test_the_workspace_is_archived_after_reading(ready):
    calls = []
    paseo.recognize(ready, runner=runner_for(json.dumps(answer()), calls=calls), ocr=ocr_readings)
    archives = [c for c in calls if c[3] in ("archive", "workspace")]
    assert archives and "wks_test123" in archives[0]


@pytest.mark.parametrize("bad", ["not json", "", json.dumps({"receipts": "x"}), json.dumps([]),
                                 json.dumps({"no_receipts": True})])
def test_a_bad_answer_is_rejected(ready, bad):
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize(ready, runner=runner_for(bad), ocr=ocr_readings)
    assert error.value.code == "VISION_RESPONSE_INVALID"


def test_a_code_fenced_answer_is_still_parsed(ready):
    fenced = "```json\n" + json.dumps(answer()) + "\n```"
    result = paseo.recognize(ready, runner=runner_for(fenced), ocr=ocr_readings)
    assert result["receipts"][0]["amount"] == 1164


@pytest.mark.parametrize("text,code", [("rate limit exceeded", "VISION_RATE_LIMITED"),
                                       ("401 unauthorized · not logged in", "VISION_AUTH_REQUIRED"),
                                       ("503 service unavailable", "VISION_PROVIDER_UNAVAILABLE")])
def test_a_failed_run_gets_a_named_code(ready, text, code):
    failed = SimpleNamespace(returncode=1, stdout=b"", stderr=text.encode())
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize(ready, runner=runner_for(json.dumps(answer()), run_proc=failed), ocr=ocr_readings)
    assert error.value.code == code


def fake_fallback_ocr(calls):
    def ocr(image, language):
        calls.append(language)
        if language == "ko":
            return {"lines": [{"text": "0625_아키타", "top": 0.03}]}
        return {"lines": [{"text": "LAWSON", "top": 0.3}], "suggestions": {"date": "2026-06-26", "total_jpy": 1164}}
    return ocr


@pytest.mark.parametrize("failure,code", [
    (SimpleNamespace(returncode=1, stdout=b"", stderr=b"rate limit reached"), "VISION_RATE_LIMITED"),
    ("not json", "VISION_RESPONSE_INVALID"),
])
def test_a_failed_model_falls_back_to_windows_ocr_with_the_reason(ready, failure, code, caplog):
    if isinstance(failure, str):
        runner = runner_for(failure)
    else:
        runner = runner_for(json.dumps(answer()), run_proc=failure)
    calls = []
    with caplog.at_level("WARNING", logger="cost.paseo_receipt_vision"):
        result = paseo.recognize_with_fallback(ready, runner=runner, ocr=ocr_readings,
                                               fallback_ocr=fake_fallback_ocr(calls))
    assert result["engine"] == "windows_ocr" and result["fallback_reason"] == code
    assert result["attempts"] == [{"model": paseo.PROVIDER_MODEL, "result": code},
                                  {"model": "windows-ocr", "result": "OK"}]
    assert result["header_text"] == "0625_아키타" and calls == ["ja", "ko"]
    assert code in caplog.text and "LAWSON" not in caplog.text


def test_a_timeout_falls_back_to_windows_ocr(ready):
    def runner(command, *, cwd, env, timeout, input_bytes=None):
        raise subprocess.TimeoutExpired("paseo", timeout)
    result = paseo.recognize_with_fallback(ready, runner=runner, ocr=ocr_readings,
                                           fallback_ocr=fake_fallback_ocr([]))
    assert result["engine"] == "windows_ocr" and result["fallback_reason"] == "VISION_TIMEOUT"


def test_an_ocr_failure_does_not_fall_back(ready):
    def empty_ocr(image):
        raise paseo.VisionUnavailable("VISION_OCR_UNAVAILABLE")
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize_with_fallback(ready, runner=runner_for(json.dumps(answer())), ocr=empty_ocr,
                                      fallback_ocr=lambda *a: pytest.fail("fallback ocr"))
    assert error.value.code == "VISION_OCR_UNAVAILABLE"


def test_input_problems_do_not_fall_back(ready, tmp_path):
    text = tmp_path / "note.txt"
    text.write_bytes(b"hello")
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize_with_fallback(text, runner=lambda *a, **k: pytest.fail("called"),
                                      ocr=lambda *a: pytest.fail("ocr"), fallback_ocr=lambda *a: pytest.fail("ocr"))
    assert error.value.code == "VISION_IMAGE_REQUIRED"


def test_disabled_does_not_run(monkeypatch, tmp_path):
    monkeypatch.delenv("WEBLEDGER_RECEIPT_VISION", raising=False)
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize_with_fallback(tmp_path / "missing.jpg", runner=lambda *a, **k: pytest.fail("called"))
    assert error.value.code == "VISION_DISABLED"


def test_missing_paseo_is_reported(ready, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_NODE_EXE", "")
    monkeypatch.setattr(paseo.shutil, "which", lambda name: None)
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize(ready, runner=lambda *a, **k: pytest.fail("called"), ocr=ocr_readings)
    assert error.value.code == "VISION_PASEO_NOT_FOUND"


def test_a_lesson_is_kept_only_on_reanalysis(ready):
    plain = paseo.recognize(ready, runner=runner_for(json.dumps(answer(lesson="작은 표도 따로 볼 것."))), ocr=ocr_readings)
    assert "lesson" not in plain
    prompts = []

    def runner(command, *, cwd, env, timeout, input_bytes=None):
        if command[3] == "run":
            prompts.append(command[-1])
        return runner_for(json.dumps(answer(lesson=" 작은 표도 따로 볼 것. ")))(command, cwd=cwd, env=env, timeout=timeout)
    lessoned = paseo.recognize(ready, runner=runner, ocr=ocr_readings, lesson=True, guidance="메모")
    assert lessoned["lesson"] == "작은 표도 따로 볼 것." and receipt_vision.LESSON_INSTRUCTION in prompts[0]
    assert "메모" in prompts[0]


def test_the_ocr_playbook_prompt_section_is_required(tmp_path):
    prompt = receipt_vision.playbook_prompt(start="ocr-reading-prompt:start", end="ocr-reading-prompt:end")
    assert "header_text" in prompt and "box는 항상 null" in prompt
    broken = tmp_path / "playbook.md"
    broken.write_text("# no markers", encoding="utf-8")
    for path in (broken, tmp_path / "missing.md"):
        with pytest.raises(receipt_vision.VisionUnavailable) as error:
            receipt_vision.playbook_prompt(path, start="ocr-reading-prompt:start", end="ocr-reading-prompt:end")
        assert error.value.code == "VISION_PLAYBOOK_MISSING"


def test_identical_tickets_stay_separate(ready):
    ticket = reading(payment="cash", card_last4=None)
    result = paseo.recognize(ready, runner=runner_for(json.dumps(answer([ticket, ticket]))), ocr=ocr_readings)
    rows = result["receipts"]
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"] and rows[0]["payment"] == "cash"


def test_the_facade_selects_paseo_and_keeps_claude(monkeypatch, tmp_path):
    from app import paseo_receipt_vision
    page = tmp_path / "page.jpg"
    page.write_bytes(JPEG)
    monkeypatch.setenv("WEBLEDGER_RECEIPT_VISION", "paseo-qwen4-max")
    assert receipt_vision.provider() == "paseo-qwen4-max" and receipt_vision.enabled()
    sentinel = {"receipts": [], "engine": "paseo"}
    monkeypatch.setattr(paseo_receipt_vision, "recognize_with_fallback", lambda *a, **k: sentinel)
    assert receipt_vision.recognize_with_fallback(page) is sentinel
    monkeypatch.setenv("WEBLEDGER_RECEIPT_VISION", "claude-opus")
    assert receipt_vision.provider() == "claude-opus" and receipt_vision.enabled()
    monkeypatch.delenv("WEBLEDGER_RECEIPT_VISION", raising=False)
    assert receipt_vision.provider() is None and not receipt_vision.enabled()


def test_without_windows_ocr_the_model_failure_is_reported(ready, monkeypatch):
    monkeypatch.setattr(local_receipt_ocr, "enabled", lambda: False)
    with pytest.raises(paseo.VisionUnavailable) as error:
        paseo.recognize_with_fallback(ready, runner=runner_for("not json"), ocr=ocr_readings)
    assert error.value.code == "VISION_RESPONSE_INVALID"
