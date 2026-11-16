"""Synthetic tests for the managed Paseo receipt runtime boundary."""
from __future__ import annotations

import base64
import hashlib
import json

import pytest

from app import receipt_paseo

JPEG = b"\xff\xd8\xff" + b"x" * 30 + b"\xff\xd9"


def model_catalog(provider=None):
    return {
        "connected": True,
        "host_label": "synthetic-local-host",
        "checked_at": "2026-11-16T00:00:00Z",
        "providers": [{"id": "claude", "label": "Synthetic subscription", "available": True}],
        "models": [{
            "provider": "claude", "id": "synthetic-photo", "label": "Synthetic photo model",
            "selectable": True, "reason": "", "thinking_options": ["low", "medium"],
            "default_thinking": "medium",
        }],
    }


def test_managed_prompt_and_metadata_are_fixed_hashes():
    prompt = receipt_paseo.managed_prompt()
    metadata = receipt_paseo.prompt_metadata()

    assert prompt == receipt_paseo.SYSTEM_PROMPT + "\n\n" + receipt_paseo.managed_user_prompt()
    assert "정해진 JSON 스키마를 따르는 JSON 객체 하나만 낸다." in prompt
    assert "StructuredOutput" not in prompt
    assert '"header_text"' in prompt and '"receipts"' in prompt
    assert metadata == {
        "prompt_version": receipt_paseo.PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "schema_version": receipt_paseo.SCHEMA_VERSION,
        "schema_sha256": hashlib.sha256(receipt_paseo._schema_bytes()).hexdigest(),
    }


def test_start_transmits_actual_photo_and_metadata(tmp_path, monkeypatch):
    photo = tmp_path / "synthetic.jpg"
    photo.write_bytes(JPEG)
    calls = []

    def bridge(operation, payload, *, timeout=receipt_paseo.BRIDGE_TIMEOUT_SECONDS):
        calls.append((operation, payload, timeout))
        if operation == "catalog":
            return model_catalog(payload["provider"])
        if operation == "start":
            return {"agent_id": "agent-synthetic-1", "workspace_id": "workspace-synthetic-1"}
        raise AssertionError(operation)

    monkeypatch.setattr(receipt_paseo, "_bridge", bridge)
    metadata = receipt_paseo.prompt_metadata()
    handle = receipt_paseo.start(
        photo, "claude", "synthetic-photo", run_key="synthetic-run-0001",
        expected_prompt_metadata=metadata, thinking="low",
    )

    operation, request, timeout = calls[-1]
    assert operation == "start" and timeout == receipt_paseo.RUN_TIMEOUT_SECONDS
    assert request["prompt"] == receipt_paseo.managed_prompt()
    assert request["prompt_metadata"] == metadata
    assert request["image"]["mimeType"] == "image/jpeg"
    assert base64.b64decode(request["image"]["data"]) == JPEG
    assert request["source_sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert handle["source_sha256"] == request["source_sha256"]
    assert handle["thinking"] == "low"
    assert handle["agent_id"] == "agent-synthetic-1"


def test_start_fails_closed_on_changed_prompt_or_unselectable_model(tmp_path, monkeypatch):
    photo = tmp_path / "synthetic.jpg"
    photo.write_bytes(JPEG)
    calls = []

    def bridge(operation, payload, **kwargs):
        calls.append(operation)
        return model_catalog(payload.get("provider"))

    monkeypatch.setattr(receipt_paseo, "_bridge", bridge)
    metadata = receipt_paseo.prompt_metadata()
    metadata["prompt_sha256"] = "0" * 64
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.start(photo, "claude", "synthetic-photo", run_key="synthetic-run-0002",
                            expected_prompt_metadata=metadata)
    assert error.value.code == "PASEO_PROMPT_CHANGED"
    assert calls == []

    monkeypatch.setattr(receipt_paseo, "_bridge", lambda operation, payload, **kwargs:
                        model_catalog(payload.get("provider")) if operation == "catalog" else
                        pytest.fail("unselectable model must not create an agent"))
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.start(photo, "claude", "unknown-model", run_key="synthetic-run-0003")
    assert error.value.code == "PASEO_MODEL_UNAVAILABLE"


def test_start_rechecks_prompt_and_schema_snapshot_immediately_before_dispatch(tmp_path, monkeypatch):
    photo = tmp_path / "synthetic.jpg"
    photo.write_bytes(JPEG)
    original = receipt_paseo._prompt_snapshot()
    changed = {
        **original,
        "prompt": original["prompt"] + "\nchanged",
        "user_prompt": original["user_prompt"] + "\nchanged",
        "metadata": {**original["metadata"], "prompt_sha256": "f" * 64},
        "schema": original["schema"] + b" ",
    }
    snapshots = [original, changed]
    monkeypatch.setattr(receipt_paseo, "_prompt_snapshot", lambda: snapshots.pop(0))
    calls = []

    def bridge(operation, payload, **kwargs):
        calls.append(operation)
        if operation == "catalog":
            return model_catalog(payload.get("provider"))
        pytest.fail("a changed managed prompt reached agent creation")

    monkeypatch.setattr(receipt_paseo, "_bridge", bridge)
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.start(photo, "claude", "synthetic-photo", run_key="synthetic-run-0008")

    assert error.value.code == "PASEO_PROMPT_CHANGED"
    assert calls == ["catalog"]


def test_inspect_run_validates_json_against_original_hash(monkeypatch):
    handle = {
        "agent_id": "agent-synthetic-2", "workspace_id": "workspace-synthetic-2",
        "run_key": "synthetic-run-0004", "source_sha256": "a" * 64, "model": "synthetic-photo",
    }
    answer = json.dumps({
        "header_text": None, "header_confidence": 0.9,
        "receipts": [{
            "box": [0.1, 0.1, 0.7, 0.8], "merchant": "합성 상점", "date": "2026-10-12",
            "amount": 1200, "currency": "JPY", "payment": "cash", "card_last4": None,
            "confidence": 0.9, "uncertain_fields": [], "note": None,
        }],
        "lesson": None,
    }, ensure_ascii=False)
    monkeypatch.setattr(receipt_paseo, "_bridge",
                        lambda operation, payload: {"status": "done", "raw_result": answer})

    result = receipt_paseo.inspect_run(handle)
    assert result["status"] == "done"
    assert result["result"]["source_sha256"] == "a" * 64
    assert result["result"]["receipts"][0]["merchant"] == "합성 상점"
    assert result["result"]["confirmed"] is False


def test_invalid_model_response_is_private_and_public_result_contains_only_code(
    monkeypatch, tmp_path,
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    private = tmp_path / "Cost" / "receipt-paseo" / "invalid-results"
    handle = {
        "agent_id": "agent-synthetic-3", "workspace_id": "workspace-synthetic-3",
        "run_key": "synthetic-run-0005", "source_sha256": "a" * 64, "model": "synthetic-photo",
    }
    raw = '{"private synthetic response": "only for local retention"'
    monkeypatch.setattr(receipt_paseo, "_bridge",
                        lambda operation, payload: {"status": "done", "raw_result": raw})

    result = receipt_paseo.inspect_run(handle)
    assert result == {"status": "failed", "code": "PASEO_RESPONSE_INVALID"}
    saved = list(private.glob("*.json"))
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == raw
    assert "private synthetic response" not in json.dumps(result)


def test_find_run_distinguishes_absence_from_bridge_failure(monkeypatch):
    monkeypatch.setattr(receipt_paseo, "_bridge", lambda operation, payload: None)
    assert receipt_paseo.find_run("synthetic-run-0006") is None

    def unavailable(*args, **kwargs):
        raise receipt_paseo.PaseoError("PASEO_UNAVAILABLE")

    monkeypatch.setattr(receipt_paseo, "_bridge", unavailable)
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.find_run("synthetic-run-0006")
    assert error.value.code == "PASEO_UNAVAILABLE"


def test_archive_only_receives_the_given_owned_handle(monkeypatch):
    handle = {"agent_id": "agent-synthetic-4", "workspace_id": "workspace-synthetic-4"}
    calls = []
    monkeypatch.setattr(receipt_paseo, "_bridge",
                        lambda operation, payload: calls.append((operation, payload)) or True)

    receipt_paseo.archive_run(handle)

    assert calls == [("archive", {"handle": handle})]


def test_bad_image_and_run_key_do_not_call_daemon(tmp_path, monkeypatch):
    bad = tmp_path / "text.txt"
    bad.write_text("synthetic text", encoding="utf-8")
    monkeypatch.setattr(receipt_paseo, "_bridge",
                        lambda *args, **kwargs: pytest.fail("invalid input reached daemon"))
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.start(bad, "claude", "synthetic-photo", run_key="synthetic-run-0007")
    assert error.value.code == "PASEO_IMAGE_INVALID"
    with pytest.raises(receipt_paseo.PaseoError) as error:
        receipt_paseo.find_run("../bad")
    assert error.value.code == "PASEO_RUN_KEY_INVALID"


def test_bridge_preserves_uncertainty_until_recorded_remote_run_appears(tmp_path):
    import subprocess
    from pathlib import Path
    bridge = Path(receipt_paseo.BRIDGE).as_uri()
    harness = r'''
import {createHash} from 'node:crypto';
const {createBridge}=await import(process.argv[1]);
const hash=x=>createHash('sha256').update(x).digest('hex');
let created=0,visible=false,createdAgent;
const api={
 providers:{snapshot:async()=>({entries:[{provider:'claude',status:'ready'}]}),
 diagnostic:async()=>({diagnostic:'Auth: '+JSON.stringify({loggedIn:true,authMethod:'claude.ai',apiProvider:'firstParty',subscriptionType:'max'})}),
 listModels:async()=>({models:[{id:'claude-fable-5-2'}]})},
 workspaces:{create:async()=>({agents:{create:async request=>{
  created++;
  createdAgent={id:request.agentId,workspaceId:null,cwd:null,provider:'claude',model:'claude-fable-5-2',labels:request.labels};
  throw new Error('synthetic lost acknowledgement');
 }}})},
 agents:{ref:()=>({refresh:async()=>visible?{agent:createdAgent}:null})}
};
// Preserve the workspace identity returned by the actual create request.
const create=api.workspaces.create;
api.workspaces.create=async request=>{
 const w=await create(request);
 const start=w.agents.create;
 w.agents.create=async r=>{try{return await start(r)}finally{createdAgent.workspaceId=request.workspaceId;createdAgent.cwd=request.source.path}};
 return w;
};
const dispatch=await createBridge(api,process.argv[2]);
const run_key='synthetic-lost-ack-20261116';
const noRecord=await dispatch({operation:'find',run_key});
const prompt='synthetic managed instructions',data=Buffer.from('synthetic image');
try{await dispatch({operation:'start',run_key,provider:'claude',model:'claude-fable-5-2',
 prompt,prompt_metadata:{prompt_sha256:hash(prompt)},source_sha256:hash(data),image:{data:data.toString('base64'),mimeType:'image/png'}})}catch{}
const errors=[];
for(let n=0;n<2;n++)try{await dispatch({operation:'find',run_key})}catch(e){errors.push(e.code)}
visible=true;
const found=await dispatch({operation:'find',run_key});
console.log(JSON.stringify({noRecord,errors,created,recovered:found.agent_id===createdAgent.id}));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', harness, bridge, str(tmp_path)],
                            capture_output=True, text=True, check=True, encoding='utf8')
    assert json.loads(result.stdout) == {
        'noRecord': None, 'errors': ['PASEO_START_UNCERTAIN', 'PASEO_START_UNCERTAIN'],
        'created': 1, 'recovered': True,
    }
