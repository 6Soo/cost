"""No real model call: the Claude reading runner with fake stream-json answers, its checks and the OCR fallback."""
import base64
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import local_receipt_ocr, receipt_trip_match
from app import receipt_vision as vision

JPEG = b"\xff\xd8\xff" + b"x" * 30 + b"\xff\xd9"


@pytest.fixture
def ready(monkeypatch, tmp_path):
    monkeypatch.setattr(vision, "enabled", lambda: True)
    monkeypatch.setenv("WEBLEDGER_CLAUDE_EXE", sys.executable)
    page = tmp_path / "page.jpg"
    page.write_bytes(JPEG)
    return page


def reading(**changes):
    item = {"box": [0.1, 0.2, 0.6, 0.7], "merchant": "LAWSON 秋田駅前店", "date": "2026-06-26", "amount": 1164,
            "currency": "JPY", "payment": "card", "card_last4": "1234", "confidence": 0.95,
            "uncertain_fields": [], "note": None}
    item.update(changes)
    return item


def stream(output, *, tools=("StructuredOutput",), events=(), result=None, key_source="none"):
    lines = [{"type": "system", "subtype": "init", "tools": list(tools), "mcp_servers": [], "apiKeySource": key_source},
             *events,
             result or {"type": "result", "subtype": "success", "is_error": False, "structured_output": output}]
    return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(line, ensure_ascii=False) for line in lines).encode(),
                           stderr=b"")


def answer(receipts=None, header="0625_아키타", confidence=0.95, lesson=None):
    return {"header_text": header, "header_confidence": confidence,
            "receipts": [reading()] if receipts is None else receipts, "lesson": lesson}


def test_the_run_is_tool_free_opus_medium_with_the_playbook_and_no_api_key(ready, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-pass")
    seen = {}

    def runner(command, *, cwd, env, timeout, input_bytes):
        seen.update(command=command, env=env, timeout=timeout, message=json.loads(input_bytes))
        return stream(answer())
    result = vision.recognize(ready, runner=runner)
    command = seen["command"]
    assert command[command.index("--model") + 1] == "opus" and command[command.index("--effort") + 1] == "medium"
    assert command[command.index("--tools") + 1] == "" and command[command.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"} <= set(command)
    schema = json.loads(command[command.index("--json-schema") + 1])
    assert schema == json.loads(vision.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert not any(key.upper().startswith("ANTHROPIC_") for key in seen["env"])
    image, text = seen["message"]["message"]["content"]
    assert base64.b64decode(image["source"]["data"]) == JPEG and image["source"]["media_type"] == "image/jpeg"
    assert text["text"].startswith(vision.playbook_prompt()) and "header_text" in text["text"]
    row, = result["receipts"]
    assert result["header_text"] == "0625_아키타" and result["engine"] == "claude" and result["confirmed"] is False
    assert row["amount"] == 1164 and row["currency"] == "JPY" and row["requires_review"]
    # A receipt cannot say private or corporate card: payment stays open and the last digits go to the note.
    assert row["payment"] is None and row["card_last4"] == "1234" and row["note"] == "카드 끝자리 1234"


@pytest.mark.parametrize("output", [None, {"receipts": "x"}, {"receipts": [1] * 51}, []])
def test_a_schema_violation_is_rejected(ready, output):
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(ready, runner=lambda *a, **k: stream(output))
    assert error.value.code == "VISION_RESPONSE_INVALID"


def test_non_json_output_and_a_missing_init_are_rejected(ready):
    bad = SimpleNamespace(returncode=0, stdout=b"not json", stderr=b"")
    no_init = SimpleNamespace(returncode=0, stdout=json.dumps(
        {"type": "result", "subtype": "success", "structured_output": answer()}).encode(), stderr=b"")
    for proc in (bad, no_init):
        with pytest.raises(vision.VisionUnavailable) as error:
            vision.recognize(ready, runner=lambda *a, proc=proc, **k: proc)
        assert error.value.code == "VISION_RESPONSE_INVALID"


def test_any_tool_besides_structured_output_fails_closed(ready):
    tool_use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}}
    for proc in (stream(answer(), tools=("StructuredOutput", "Bash")), stream(answer(), events=[tool_use])):
        with pytest.raises(vision.VisionUnavailable) as error:
            vision.recognize(ready, runner=lambda *a, proc=proc, **k: proc)
        assert error.value.code == "VISION_TOOL_EXECUTION_DETECTED"


@pytest.mark.parametrize("text,code", [("Claude AI usage limit reached", "VISION_RATE_LIMITED"),
                                       ("Not logged in · Please run /login", "VISION_AUTH_REQUIRED"),
                                       ("API Error: 529 overloaded", "VISION_PROVIDER_UNAVAILABLE")])
def test_error_results_get_a_named_code(ready, text, code):
    failed = {"type": "result", "subtype": "success", "is_error": True, "result": text}
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(ready, runner=lambda *a, **k: stream(None, result=failed))
    assert error.value.code == code


def fake_ocr(calls):
    def ocr(image, language):
        calls.append(language)
        if language == "ko":
            return {"lines": [{"text": "0625_아키타", "top": 0.03}, {"text": "합계", "top": 0.6}]}
        return {"lines": [{"text": "LAWSON", "top": 0.3}], "suggestions": {"date": "2026-06-26", "total_jpy": 1164}}
    return ocr


@pytest.mark.parametrize("failure,code", [
    (subprocess.TimeoutExpired("claude", 180), "VISION_TIMEOUT"),
    (stream(None, events=[{"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}]), "VISION_RATE_LIMITED"),
    (stream({"receipts": "broken"}), "VISION_RESPONSE_INVALID"),
])
def test_a_failed_run_falls_back_to_windows_ocr_with_the_reason(ready, failure, code, caplog):
    def runner(*args, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure
    calls = []
    with caplog.at_level("WARNING", logger="cost.receipt_vision"):
        result = vision.recognize_with_fallback(ready, runner=runner, ocr=fake_ocr(calls))
    assert result["engine"] == "windows_ocr" and result["fallback_reason"] == code
    assert result["attempts"] == [{"model": "opus", "result": code}, {"model": "windows-ocr", "result": "OK"}]
    assert result["header_text"] == "0625_아키타" and calls == ["ja", "ko"]
    row, = result["receipts"]
    assert (row["date"], row["amount"], row["currency"], row["merchant"]) == ("2026-06-26", 1164, "JPY", None)
    assert code in caplog.text and "LAWSON" not in caplog.text


def test_without_windows_ocr_the_original_failure_is_reported(ready, monkeypatch):
    monkeypatch.setattr(local_receipt_ocr, "enabled", lambda: False)

    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired("claude", 180)
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(ready, runner=runner)
    assert error.value.code == "VISION_TIMEOUT"


def test_an_ocr_failure_also_reports_the_claude_failure(ready):
    def ocr(image, language):
        raise local_receipt_ocr.OcrError("OCR_FAILED")
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(ready, runner=lambda *a, **k: stream(None), ocr=ocr)
    assert error.value.code == "VISION_RESPONSE_INVALID"


def test_input_problems_do_not_fall_back(ready, tmp_path):
    text = tmp_path / "note.txt"
    text.write_bytes(b"hello")
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(text, runner=lambda *a, **k: pytest.fail("called"),
                                       ocr=lambda *a: pytest.fail("ocr"))
    assert error.value.code == "VISION_IMAGE_REQUIRED"


def test_disabled_does_not_run(monkeypatch, tmp_path):
    monkeypatch.delenv("WEBLEDGER_RECEIPT_VISION", raising=False)
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize_with_fallback(tmp_path / "missing.jpg", runner=lambda *a, **k: pytest.fail("called"))
    assert error.value.code == "VISION_DISABLED"


def test_the_read_header_finds_one_trip_and_a_doubtful_header_is_dropped(ready):
    trips = [{"id": "akita", "name": "0625_아키타", "starts_on": "2026-06-25"},
             {"id": "sapporo", "name": "0714_삿포로", "starts_on": "2026-07-14"}]
    result = vision.recognize(ready, runner=lambda *a, **k: stream(answer(header="0625 아키타")))
    assert receipt_trip_match.match_header(result["header_text"], trips)["ids"] == ["akita"]
    assert result["trip_inferred"] is False
    doubtful = vision.recognize(ready, runner=lambda *a, **k: stream(answer(header="0625 아키타", confidence=0.3)))
    assert doubtful["header_text"] is None
    # The trip title is not a store: the matcher recognises it when a model still writes it as a merchant.
    assert receipt_trip_match.is_header_text("0625_아키타", result["header_text"], trips)


def test_fields_failing_their_check_become_null_and_the_entry_stays(ready):
    rows = vision.recognize(ready, runner=lambda *a, **k: stream(answer([
        reading(date="2026-13-40", amount=0, currency="USD", payment="other", card_last4="12", box=[0.8, 0.2, 0.1, 0.9]),
        reading(merchant=None, date=None, amount=None),
        reading(payment="cash", card_last4=None, amount=2500, box=None),
    ])))["receipts"]
    first, cash = rows
    assert first["date"] is None and first["amount"] is None and first["box"] is None and first["card_last4"] is None
    assert first["currency"] is None and first["payment"] is None and first["note"] == "통화 USD · 기타 결제"
    assert cash["payment"] == "cash" and cash["note"] is None


def test_identical_tickets_stay_separate_whatever_the_order():
    ticket = reading(box=None, payment="cash", card_last4=None)
    rows = vision.validate_response({"receipts": [ticket, ticket]}, image_hash="h")["receipts"]
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    again = vision.validate_response({"receipts": [ticket, ticket]}, image_hash="h")["receipts"]
    assert [r["id"] for r in rows] == [r["id"] for r in again]


def test_extreme_box_coordinates_become_unknown():
    for box in ([0, 0, 10 ** 400, 1], [0, 0, float("inf"), 1], [5, 9, 100, 200]):
        assert vision.validate_response({"receipts": [reading(box=box)]}, image_hash="h")["receipts"][0]["box"] is None


def test_a_lesson_is_kept_only_on_reanalysis(ready):
    plain = vision.recognize(ready, runner=lambda *a, **k: stream(answer(lesson="작은 표도 따로 볼 것.")))
    assert "lesson" not in plain
    prompts = []

    def runner(command, *, cwd, env, timeout, input_bytes):
        prompts.append(json.loads(input_bytes)["message"]["content"][1]["text"])
        return stream(answer(lesson=" 작은 표도 따로 볼 것. "))
    lessoned = vision.recognize(ready, runner=runner, lesson=True, guidance="메모")
    assert lessoned["lesson"] == "작은 표도 따로 볼 것." and vision.LESSON_INSTRUCTION in prompts[0]
    assert prompts[0].endswith("메모")


def test_the_playbook_prompt_section_is_required(tmp_path):
    assert "header_text" in vision.playbook_prompt() and "StructuredOutput" in vision.playbook_prompt()
    broken = tmp_path / "playbook.md"
    broken.write_text("# no markers", encoding="utf-8")
    for path in (broken, tmp_path / "missing.md"):
        with pytest.raises(vision.VisionUnavailable) as error:
            vision.playbook_prompt(path)
        assert error.value.code == "VISION_PLAYBOOK_MISSING"


@pytest.mark.parametrize("source", ["/login managed key", "ANTHROPIC_API_KEY", "apiKeyHelper", None])
def test_a_billed_login_is_refused_and_falls_back_with_the_reason(ready, source):
    with pytest.raises(vision.VisionUnavailable) as error:
        vision.recognize(ready, runner=lambda *a, **k: stream(answer(), key_source=source))
    assert error.value.code == "VISION_BILLING_PATH_REFUSED"
    result = vision.recognize_with_fallback(ready, runner=lambda *a, **k: stream(answer(), key_source=source),
                                            ocr=fake_ocr([]))
    assert result["engine"] == "windows_ocr" and result["fallback_reason"] == "VISION_BILLING_PATH_REFUSED"


def test_cloud_provider_switches_are_removed_from_the_environment(ready, monkeypatch):
    for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.setenv(name, "1")
    seen = {}

    def runner(command, *, cwd, env, timeout, input_bytes):
        seen.update(env)
        return stream(answer())
    vision.recognize(ready, runner=runner)
    assert not any(key.upper().startswith(("CLAUDE_CODE_USE_", "ANTHROPIC_")) for key in seen)
    assert "PATH" in {key.upper() for key in seen}
