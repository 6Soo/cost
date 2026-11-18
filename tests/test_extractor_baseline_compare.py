"""SPEC §11.1 M3-3: extraction-content vs source-identity classification (synthetic inputs only)."""
import hashlib
import json
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tools.core_bridge.cli import handle
from tools.core_bridge.extract_baseline import SOURCE_IDENTITY_FIELDS, compare_events

ROOT = Path(__file__).resolve().parents[1]


def event(ref, amount=10000, identity="a", **extra):
    base = {
        "provider": "synthetic", "booking_ref": ref, "event_type": "charge",
        "paid_on": "2026-01-02", "amount_krw": amount, "currency": "KRW",
        "evidence_status": "paid_verified", "evidence_kind": "authenticated_payment_mail",
        "source_ids": ["mail:" + identity], "identity_source_ids": ["mail:" + identity],
        "source_digest": "d" * 64, "source_digests": ["d" * 64],
        "source_lineage_ids": ["mail_" + "l" * 64], "observation_ids": ["obs_" + identity],
        "ota_event_id": "evt_" + identity, "source_binding_ids": [],
        "source_inventory": {"messages": 1},
    }
    base.update(extra)
    return base


def host(tmp_path):
    root = tmp_path / "host"
    (root / "data" / "backups").mkdir(parents=True, exist_ok=True)
    return root


def write_events(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"events": events}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def compare_request(tmp_path, base_events, new_events, **changes):
    backups = host(tmp_path) / "data" / "backups"
    base = write_events(backups / "base" / "events.json", base_events)
    new = write_events(backups / "new" / "events.json", new_events)
    request = {"base": str(base), "new": str(new), "host_root": str(host(tmp_path)),
               "out": str(backups / "compare" / "report.json")}
    return dict(request, **changes)


def evidence_copy(tmp_path, marker=None):
    from app.ota_store import OtaStore
    path = tmp_path / ("ota-evidence-%s.sqlite" % (marker or "plain"))
    store = OtaStore(path)
    store.conn.close()
    if marker:
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE synthetic_marker(value)")
            conn.execute("INSERT INTO synthetic_marker VALUES (?)", (marker,))
    return path


def capture_request(tmp_path, evidence, name):
    root = host(tmp_path)
    return {"ota_evidence": str(evidence), "host_root": str(root),
            "out": str(root / "data" / "backups" / name / "events.json")}


def canonical_digest(body):
    payload = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_identical_events_have_no_difference():
    events = [event("SYN-1"), event("SYN-2", amount=20000, identity="b")]
    result = compare_events(events, [dict(item) for item in events])
    assert result["identical"] == 2
    assert result["source_identity_only"] == result["content_changed"] == 0
    assert result["only_in_base"] == result["only_in_new"] == 0
    assert result["identity_field_diff_counts"] == result["content_field_diff_counts"] == {}


def test_source_identity_difference_is_not_extraction_content():
    base = [event("SYN-1"), event("SYN-2", identity="b")]
    moved = dict(base[1], observation_ids=["obs_moved"], ota_event_id="evt_moved",
                 source_lineage_ids=["mail_moved"])
    result = compare_events(base, [base[0], moved])
    assert result["identical"] == 1
    assert result["source_identity_only"] == 1
    assert result["content_changed"] == 0
    assert result["only_in_base"] == result["only_in_new"] == 0
    assert result["identity_field_diff_counts"] == {
        "observation_ids": 1, "ota_event_id": 1, "source_lineage_ids": 1}
    assert result["content_field_diff_counts"] == {}


def test_extraction_content_difference_pairs_by_business_key():
    result = compare_events([event("SYN-1")], [event("SYN-1", amount=12000)])
    assert result["content_changed"] == 1
    assert result["source_identity_only"] == result["identical"] == 0
    assert result["only_in_base"] == result["only_in_new"] == 0
    assert result["content_field_diff_counts"] == {"amount_krw": 1}


def test_added_and_removed_events_are_content_differences():
    result = compare_events([event("SYN-1")], [event("SYN-2")])
    assert result["only_in_base"] == 1 and result["only_in_new"] == 1
    assert result["content_changed"] == result["identical"] == 0


def test_duplicate_content_is_a_multiset():
    base = [event("SYN-1", identity="a"), event("SYN-1", identity="b")]
    result = compare_events(base, [event("SYN-1", identity="b")])
    assert result["identical"] == 1
    assert result["only_in_base"] == 1
    assert result["source_identity_only"] == 0


def test_classification_is_independent_of_event_order():
    base = [event("SYN-1", identity="a"), event("SYN-2", identity="b")]
    moved = dict(base[1], observation_ids=["obs_moved"])
    forward = compare_events(base, [base[0], moved])
    reverse = compare_events(list(reversed(base)), [moved, base[0]])
    assert forward == reverse


def test_ambiguous_business_key_stays_unmatched():
    base = [event("SYN-1", amount=1), event("SYN-1", amount=2)]
    result = compare_events(base, [event("SYN-1", amount=3)])
    assert result["content_changed"] == 0
    assert result["only_in_base"] == 2 and result["only_in_new"] == 1


def test_extraction_facts_are_not_identity_fields():
    for field in ("provider", "booking_ref", "amount_krw", "paid_on", "evidence_status",
                  "payment_id", "service_period", "reservation_status", "item"):
        assert field not in SOURCE_IDENTITY_FIELDS


def test_observed_490_shape_is_source_identity_only():
    """Regression: the preserved drift summary shows 490 events differing in exactly these four fields."""
    base_event = event(
        "SYN-1", identity="a",
        _portal_reservation_provenance={"provider": "synthetic", "identity": "id-a",
                                        "source_digest": "d" * 64, "source_lineage_id": "lin-a"},
        reservation_identity_attestation={"provider": "synthetic", "identity": "id-a",
                                          "source_lineage_id": "lin-a", "identity_status": "verified",
                                          "evidence_status": "verified", "source_status": "verified",
                                          "evidence_link_ids": ["mail:a"]})
    moved = dict(base_event,
                 _portal_reservation_provenance=dict(base_event["_portal_reservation_provenance"],
                                                     source_digest="e" * 64, source_lineage_id="lin-b"),
                 reservation_identity_attestation=dict(base_event["reservation_identity_attestation"],
                                                       source_lineage_id="lin-b"),
                 observation_ids=["obs_moved"], source_lineage_ids=["mail_moved"])
    result = compare_events([base_event], [moved])
    assert result["identical"] == 0
    assert result["source_identity_only"] == 1
    assert result["content_changed"] == result["only_in_base"] == result["only_in_new"] == 0
    assert result["identity_field_diff_counts"] == {
        "_portal_reservation_provenance": 1, "observation_ids": 1,
        "reservation_identity_attestation": 1, "source_lineage_ids": 1}
    assert result["content_field_diff_counts"] == {}


def test_portal_snapshot_format_flag_is_source_identity():
    base_event = event("SYN-1", verified_portal_snapshot=True)
    result = compare_events([base_event], [dict(base_event, verified_portal_snapshot=False)])
    assert result["source_identity_only"] == 1
    assert result["content_changed"] == 0
    assert result["identity_field_diff_counts"] == {"verified_portal_snapshot": 1}


def test_cli_compare_writes_protected_report_and_returns_counts_only(tmp_path):
    base = [event("SYN-1"), event("SYN-2", identity="b")]
    moved = dict(base[1], observation_ids=["obs_moved"], ota_event_id="evt_moved")
    req = compare_request(tmp_path, base, [base[0], moved])
    response = handle("extract-baseline-compare", req, sha="")
    assert response["ok"], response
    result = response["result"]
    assert result["identical"] == 1 and result["source_identity_only"] == 1
    assert result["base_events"] == result["new_events"] == 2
    assert result["same_input_fingerprint"] is None and result["same_production_code"] is None
    assert "SYN-1" not in json.dumps(result) and "SYN-2" not in json.dumps(result)
    assert set(result) == {"base_events", "new_events", "identical", "source_identity_only",
                           "content_changed", "only_in_base", "only_in_new",
                           "same_input_fingerprint", "same_production_code", "report_sha256"}
    assert str(tmp_path) not in json.dumps(result)

    report = json.loads(Path(req["out"]).read_text(encoding="utf-8"))
    assert report["schema_version"] == "extractor-baseline-compare-v1"
    assert report["classification"]["source_identity_only"] == 1
    detail = report["classification"]["details"]["source_identity_only"][0]
    assert detail["fields"] == ["observation_ids", "ota_event_id"]
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    assert report["report_sha256"] == canonical_digest(body) == result["report_sha256"]
    assert report["base"]["sha256"] == hashlib.sha256(Path(req["base"]).read_bytes()).hexdigest()
    assert report["new"]["sha256"] == hashlib.sha256(Path(req["new"]).read_bytes()).hexdigest()


def test_manifest_binding_reports_same_input_and_code(tmp_path, monkeypatch):
    from app import ota_payments
    monkeypatch.setattr(ota_payments, "build_ota_payment_events", lambda sources: [event("SYN-1")])
    evidence = evidence_copy(tmp_path)
    first = handle("extract-baseline", capture_request(tmp_path, evidence, "first"), sha="")
    second = handle("extract-baseline", capture_request(tmp_path, evidence, "second"), sha="")
    assert first["ok"] and second["ok"], (first, second)
    backups = host(tmp_path) / "data" / "backups"
    req = {"base": str(backups / "first" / "events.json"), "new": str(backups / "second" / "events.json"),
           "base_manifest": first["result"]["manifest_path"], "new_manifest": second["result"]["manifest_path"],
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert response["ok"], response
    result = response["result"]
    assert result["identical"] == 1
    assert result["same_input_fingerprint"] is True
    assert result["same_production_code"] is True
    report = json.loads(Path(req["out"]).read_text(encoding="utf-8"))
    assert report["base"]["binding"]["input_sha256"] == report["new"]["binding"]["input_sha256"]


def test_different_input_fingerprint_is_reported(tmp_path, monkeypatch):
    from app import ota_payments
    monkeypatch.setattr(ota_payments, "build_ota_payment_events", lambda sources: [event("SYN-1")])
    first = handle("extract-baseline", capture_request(tmp_path, evidence_copy(tmp_path), "first"), sha="")
    second = handle("extract-baseline",
                    capture_request(tmp_path, evidence_copy(tmp_path, marker="drift"), "second"), sha="")
    assert first["ok"] and second["ok"], (first, second)
    backups = host(tmp_path) / "data" / "backups"
    req = {"base": str(backups / "first" / "events.json"), "new": str(backups / "second" / "events.json"),
           "base_manifest": first["result"]["manifest_path"], "new_manifest": second["result"]["manifest_path"],
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert response["ok"], response
    result = response["result"]
    assert result["identical"] == 1
    assert result["same_input_fingerprint"] is False
    assert result["same_production_code"] is True


def test_events_file_not_bound_to_manifest_is_rejected(tmp_path, monkeypatch):
    from app import ota_payments
    monkeypatch.setattr(ota_payments, "build_ota_payment_events", lambda sources: [event("SYN-1")])
    captured = handle("extract-baseline", capture_request(tmp_path, evidence_copy(tmp_path), "first"), sha="")
    assert captured["ok"], captured
    backups = host(tmp_path) / "data" / "backups"
    other = write_events(backups / "other" / "events.json", [event("SYN-2")])
    req = {"base": str(other), "new": str(backups / "first" / "events.json"),
           "base_manifest": captured["result"]["manifest_path"],
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "OUTPUT_MANIFEST_MISMATCH"
    assert not Path(req["out"]).exists()


def test_tampered_manifest_is_rejected(tmp_path):
    captured = handle("extract-baseline", capture_request(tmp_path, evidence_copy(tmp_path), "first"), sha="")
    assert captured["ok"], captured
    manifest_path = Path(captured["result"]["manifest_path"])
    manifest_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output"]["event_count"] = 7
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    backups = host(tmp_path) / "data" / "backups"
    req = {"base": str(backups / "first" / "events.json"), "new": str(backups / "first" / "events.json"),
           "base_manifest": str(manifest_path),
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"


@pytest.mark.parametrize("target", ["base", "new", "out"])
def test_paths_inside_the_repository_are_refused(tmp_path, target):
    req = compare_request(tmp_path, [event("SYN-1")], [event("SYN-1")])
    req[target] = str(ROOT / "outputs" / "compare.json")
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "PATH_INSIDE_REPO"
    assert response["error"]["detail"] == target


def test_output_outside_the_protected_folder_is_refused(tmp_path):
    req = compare_request(tmp_path, [], [])
    req["out"] = str(tmp_path / "elsewhere.json")
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "PATH_NOT_PROTECTED"


def test_missing_input_is_refused(tmp_path):
    req = compare_request(tmp_path, [], [])
    Path(req["base"]).unlink()
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "FILE_NOT_FOUND"
    assert not Path(req["out"]).exists()


def test_existing_report_is_not_overwritten(tmp_path):
    req = compare_request(tmp_path, [], [])
    out = Path(req["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("{}", encoding="utf-8")
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "OUT_EXISTS"
    assert out.read_text(encoding="utf-8") == "{}"


def test_malformed_events_file_is_refused(tmp_path):
    req = compare_request(tmp_path, [], [])
    Path(req["base"]).write_text('{"events": [1]}', encoding="utf-8")
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "FORMAT_INVALID"


def test_cli_accepts_the_compare_command_name():
    proc = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "core_bridge" / "cli.py"),
                           "extract-baseline-compare"],
                          input="{}\n", text=True, capture_output=True, encoding="utf-8")
    assert json.loads(proc.stdout)["error"]["code"] == "BASE_REQUIRED"


def reseal_manifest(path, mutate):
    """Rewrite a manifest body with a matching checksum: the reported attack shape."""
    path = Path(path)
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.pop("manifest_sha256")
    mutate(manifest)
    manifest["manifest_sha256"] = canonical_digest(manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return str(path)


def capture_synthetic(tmp_path, monkeypatch, name, events):
    from app import ota_payments
    monkeypatch.setattr(ota_payments, "build_ota_payment_events", lambda sources: events)
    response = handle("extract-baseline", capture_request(tmp_path, evidence_copy(tmp_path), name), sha="")
    assert response["ok"], response
    return response["result"]


def same_file_request(tmp_path, name, manifest_path):
    backups = host(tmp_path) / "data" / "backups"
    return {"base": str(backups / name / "events.json"), "new": str(backups / name / "events.json"),
            "base_manifest": str(manifest_path), "new_manifest": str(manifest_path),
            "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}


def test_self_consistent_hollow_manifests_are_rejected(tmp_path, monkeypatch):
    """Regression: null fingerprints, no dependency list and a wrong count must not bind.

    Before the fix these checksum-valid manifests returned ok=true with
    same_input_fingerprint/same_production_code=true (None == None).
    """
    result = capture_synthetic(tmp_path, monkeypatch, "empty", [])

    def hollow(manifest):
        manifest["input"]["sqlite_logical_fingerprint"] = None
        manifest["producer"]["production_python_sha256"] = None
        del manifest["producer"]["dependency_modules"]
        manifest["output"]["event_count"] = 999

    forged = reseal_manifest(result["manifest_path"], hollow)
    req = same_file_request(tmp_path, "empty", forged)
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"
    assert not Path(req["out"]).exists()


@pytest.mark.parametrize("field,value", [("event_count", 999), ("size_bytes", 1)])
def test_well_formed_manifest_must_match_actual_output(tmp_path, monkeypatch, field, value):
    result = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    forged = reseal_manifest(result["manifest_path"],
                             lambda manifest: manifest["output"].__setitem__(field, value))
    req = same_file_request(tmp_path, "first", forged)
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "OUTPUT_MANIFEST_MISMATCH"
    assert not Path(req["out"]).exists()


def test_cross_producer_version_compare_stays_allowed(tmp_path, monkeypatch):
    first = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    second = capture_synthetic(tmp_path, monkeypatch, "second", [event("SYN-1")])

    def other_version(manifest):
        producer = manifest["producer"]
        modules = producer["dependency_modules"]
        extractor = next(item for item in modules
                         if item["path"] == "tools/core_bridge/extract_baseline.py")
        extractor["sha256"] = "e" * 64
        producer["python_source_sha256"] = extractor["sha256"]
        producer["production_python_sha256"] = canonical_digest(modules)

    forged = reseal_manifest(second["manifest_path"], other_version)
    backups = host(tmp_path) / "data" / "backups"
    req = {"base": str(backups / "first" / "events.json"), "new": str(backups / "second" / "events.json"),
           "base_manifest": first["manifest_path"], "new_manifest": forged,
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert response["ok"], response
    result = response["result"]
    assert result["identical"] == 1
    assert result["same_input_fingerprint"] is True
    assert result["same_production_code"] is False


@pytest.mark.parametrize("mutate", [
    lambda manifest: manifest["producer"].__setitem__("dependency_modules", []),
    lambda manifest: manifest["producer"]["dependency_modules"][0].pop("path"),
    lambda manifest: manifest["producer"]["dependency_modules"][0].__setitem__("sha256", "short"),
])
def test_invalid_dependency_description_is_rejected(tmp_path, monkeypatch, mutate):
    result = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    forged = reseal_manifest(result["manifest_path"], mutate)
    req = same_file_request(tmp_path, "first", forged)
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"


def test_non_hex_digest_is_rejected(tmp_path, monkeypatch):
    result = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    forged = reseal_manifest(result["manifest_path"],
                             lambda manifest: manifest["input"].__setitem__("sha256", "g" * 64))
    req = same_file_request(tmp_path, "first", forged)
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"


def test_changed_module_hash_with_stale_bundle_is_rejected(tmp_path, monkeypatch):
    """Regression: resealing one dependency hash while keeping the bundle digest
    must not let compare report ok=true / same_production_code=true."""
    first = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    second = capture_synthetic(tmp_path, monkeypatch, "second", [event("SYN-1")])
    forged = reseal_manifest(
        second["manifest_path"],
        lambda manifest: manifest["producer"]["dependency_modules"][0].__setitem__("sha256", "e" * 64))
    backups = host(tmp_path) / "data" / "backups"
    req = {"base": str(backups / "first" / "events.json"), "new": str(backups / "second" / "events.json"),
           "base_manifest": first["manifest_path"], "new_manifest": forged,
           "host_root": str(host(tmp_path)), "out": str(backups / "compare" / "report.json")}
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"
    assert not Path(req["out"]).exists()


@pytest.mark.parametrize("mutate", [
    lambda manifest: manifest["producer"].__setitem__("python_source_sha256", "f" * 64),
    lambda manifest: manifest["producer"].__setitem__("production_python_sha256", "a" * 64),
    lambda manifest: next(item for item in manifest["producer"]["dependency_modules"]
                          if item["path"] == "tools/core_bridge/extract_baseline.py"
                          ).__setitem__("sha256", "e" * 64),
])
def test_manifest_internal_inconsistency_is_rejected(tmp_path, monkeypatch, mutate):
    result = capture_synthetic(tmp_path, monkeypatch, "first", [event("SYN-1")])
    forged = reseal_manifest(result["manifest_path"], mutate)
    req = same_file_request(tmp_path, "first", forged)
    response = handle("extract-baseline-compare", req, sha="")
    assert not response["ok"] and response["error"]["code"] == "MANIFEST_INVALID"
    assert not Path(req["out"]).exists()
