import hashlib
import json
import shutil
import stat
from pathlib import Path

import pytest

from tools.core_bridge.cli import handle
from tools.core_bridge.extract_baseline import verify_capture


def evidence_copy(tmp_path):
    from app.ota_store import OtaStore
    path = tmp_path / "ota-evidence.sqlite"
    store = OtaStore(path)
    store.conn.close()
    return path


def request(tmp_path, evidence, name):
    host = tmp_path / "host"
    (host / "data" / "backups").mkdir(parents=True, exist_ok=True)
    return {
        "ota_evidence": str(evidence),
        "host_root": str(host),
        "out": str(host / "data" / "backups" / name / "events.json"),
    }


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_manifest_binds_snapshot_code_and_unchanged_output_and_verifies(tmp_path):
    evidence = evidence_copy(tmp_path)
    original_hash = sha256(evidence)
    req = request(tmp_path, evidence, "capture-one")
    response = handle("extract-baseline", req, sha="")
    assert response["ok"], response
    result = response["result"]
    assert result["events"] == 0 and set(result) >= {"sha256", "manifest_sha256", "manifest_path"}
    assert sha256(evidence) == original_hash

    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    capture_dir = manifest_path.parent
    snapshot = capture_dir / manifest["input"]["path"]
    assert snapshot.is_file()
    assert sha256(snapshot) == manifest["input"]["sha256"]
    assert snapshot.stat().st_size == manifest["input"]["size_bytes"]
    assert manifest["input"]["sqlite_logical_fingerprint"]
    assert manifest["producer"]["python_source_sha256"]
    assert manifest["producer"]["production_python_sha256"]
    module_paths = {item["path"] for item in manifest["producer"]["dependency_modules"]}
    assert "tools/core_bridge/extract_baseline.py" in module_paths
    assert "app/ota_payments.py" in module_paths
    assert manifest["output"]["sha256"] == result["sha256"] == sha256(req["out"])
    assert manifest["output"]["event_count"] == 0
    assert verify_capture(manifest_path, host_root=req["host_root"])["ok"]


def test_same_input_reproduces_output_and_creates_a_new_preserved_snapshot(tmp_path):
    evidence = evidence_copy(tmp_path)
    first = handle("extract-baseline", request(tmp_path, evidence, "first"), sha="")
    second = handle("extract-baseline", request(tmp_path, evidence, "second"), sha="")
    assert first["ok"] and second["ok"]
    assert first["result"]["sha256"] == second["result"]["sha256"]
    assert Path(first["result"]["manifest_path"]).parent != Path(second["result"]["manifest_path"]).parent
    for response in (first, second):
        manifest_path = Path(response["result"]["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert (manifest_path.parent / manifest["input"]["path"]).is_file()


def test_verified_capture_can_be_copied_as_a_complete_preserved_bundle(tmp_path):
    evidence = evidence_copy(tmp_path)
    req = request(tmp_path, evidence, "preserved")
    response = handle("extract-baseline", req, sha="")
    assert response["ok"], response
    original_manifest = Path(response["result"]["manifest_path"])

    copied_host = tmp_path / "host-copy"
    copied_backups = copied_host / "data" / "backups"
    shutil.copytree(Path(req["host_root"]) / "data" / "backups", copied_backups)
    copied_manifest = copied_backups / original_manifest.relative_to(
        Path(req["host_root"]) / "data" / "backups")
    assert verify_capture(copied_manifest, host_root=copied_host)["ok"]


@pytest.mark.parametrize("artifact", ["input", "output"])
def test_artifact_tampering_is_rejected(tmp_path, artifact):
    evidence = evidence_copy(tmp_path)
    req = request(tmp_path, evidence, f"tamper-{artifact}")
    response = handle("extract-baseline", req, sha="")
    assert response["ok"], response
    manifest_path = Path(response["result"]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = (manifest_path.parent / manifest["input"]["path"] if artifact == "input"
              else Path(req["out"]))
    target.chmod(stat.S_IREAD | stat.S_IWRITE)
    with target.open("ab") as file_handle:
        file_handle.write(b"tamper")
    with pytest.raises(ValueError, match="CAPTURE_INVALID"):
        verify_capture(manifest_path, host_root=req["host_root"])


def test_manifest_mutation_is_rejected(tmp_path):
    evidence = evidence_copy(tmp_path)
    req = request(tmp_path, evidence, "tamper")
    response = handle("extract-baseline", req, sha="")
    assert response["ok"], response
    manifest_path = Path(response["result"]["manifest_path"])
    manifest_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output"]["event_count"] = 7
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="CAPTURE_INVALID"):
        verify_capture(manifest_path, host_root=req["host_root"])


def test_interrupted_capture_keeps_snapshot_without_completion_manifest(tmp_path, monkeypatch):
    from app import ota_payments

    evidence = evidence_copy(tmp_path)
    req = request(tmp_path, evidence, "interrupted")

    def stop_after_snapshot(_sources):
        raise RuntimeError("synthetic extraction interruption")

    monkeypatch.setattr(ota_payments, "build_ota_payment_events", stop_after_snapshot)
    response = handle("extract-baseline", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "COMMAND_FAILED"
    assert not Path(req["out"]).exists()
    capture_root = Path(req["host_root"]) / "data" / "backups" / "extractor-baseline-captures"
    capture_dirs = [item for item in capture_root.iterdir() if item.is_dir()]
    assert len(capture_dirs) == 1
    assert (capture_dirs[0] / "inputs" / "ota-evidence.sqlite").is_file()
    assert not (capture_dirs[0] / "manifest.json").exists()


def test_live_source_uses_readonly_snapshot_and_is_left_unchanged(tmp_path):
    evidence = evidence_copy(tmp_path)
    req = request(tmp_path, evidence, "live")
    live = Path(req["host_root"]) / "data" / "ota-evidence.sqlite"
    live.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(evidence, live)
    before = sha256(live)
    response = handle("extract-baseline", dict(req, ota_evidence=str(live)), sha="")
    assert response["ok"], response
    assert sha256(live) == before
    manifest = json.loads(Path(response["result"]["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["sources"] == {"capture_mode": "sqlite-backup", "external_source_files": False}
