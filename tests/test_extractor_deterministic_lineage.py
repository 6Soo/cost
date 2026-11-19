"""Deterministic extractor lineage: same input content must give the same output bytes.

The baseline capture used to derive ``source_lineage_ids`` from the per-run random
capture directory, so two runs of the same input produced different output bytes
(and the fixed baseline could never be reproduced). These tests pin the contract:
lineage follows input *content*, and the capture directory name is deterministic.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import stat
from pathlib import Path

import pytest

from app.ota_sources import source_lineage_id
from tools.core_bridge.cli import handle
from tools.core_bridge.extract_baseline import sqlite_logical_fingerprint


def _content_lineage(fingerprint):
    return "content_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def portal_store(tmp_path, name):
    """A synthetic unified OTA store holding one verified portal record."""
    from app.ota_store import OtaStore
    from tests.card_pipeline.test_ota_portal import portal_database

    plain = tmp_path / f"{name}-portal.sqlite"
    portal_database(plain, facts=[
        {"price_components": [
            {"kind": "paid_today", "currency": "KRW", "decimal_text": "30000",
             "minor_units": 30000, "scale": 0, "payment_id": "SYN-A"},
            {"kind": "paid_today", "currency": "KRW", "decimal_text": "12000",
             "minor_units": 12000, "scale": 0, "payment_id": "SYN-B"},
            {"kind": "refund_completed", "currency": "KRW", "decimal_text": "5000",
             "minor_units": 5000, "scale": 0, "refunded_on": "2026-08-03",
             "payment_id": "SYN-R"}]}])
    store = OtaStore(tmp_path / f"{name}-store.sqlite")
    store.import_portal(plain)
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.close()
    return tmp_path / f"{name}-store.sqlite"


def copy_store(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(target))
    source_conn.backup(target_conn)
    target_conn.close()
    source_conn.close()
    return target


def capture(evidence, tmp_path, name, host_name=None):
    host = tmp_path / f"host-{host_name or name}"
    (host / "data" / "backups").mkdir(parents=True, exist_ok=True)
    request = {"ota_evidence": str(evidence), "host_root": str(host),
               "out": str(host / "data" / "backups" / f"{name}-out" / "events.json")}
    return handle("extract-baseline", request, sha="")


def capture_named(evidence, tmp_path, host_name, out_name):
    return capture(evidence, tmp_path, out_name, host_name=host_name)


def events_of(response, out):
    return json.loads(open(out, encoding="utf-8").read())["events"]


# ---------------------------------------------------------------- (B) unit level

def test_content_fingerprint_replaces_the_path_fallback(tmp_path):
    path = tmp_path / "ota-evidence.sqlite"
    path.write_bytes(b"synthetic")
    historical = "path_" + hashlib.sha256(
        os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()
    assert source_lineage_id({}, path) == historical
    assert source_lineage_id({}, path, content_fingerprint="abc123") == _content_lineage("abc123")
    assert _content_lineage("abc123") != historical


def test_registered_operator_lineage_still_wins(tmp_path):
    path = tmp_path / "ota-evidence.sqlite"
    path.write_bytes(b"synthetic")
    registry = {str(path.resolve()): "agoda-primary-source"}
    assert source_lineage_id(registry, path, content_fingerprint="abc123") == "agoda-primary-source"


# ------------------------------------------------------- (B) same content, two paths

def test_same_input_at_two_paths_produces_identical_output_bytes(tmp_path):
    store = portal_store(tmp_path, "origin")
    first = copy_store(store, tmp_path / "path-alpha" / "ota-evidence.sqlite")
    second = copy_store(store, tmp_path / "path-beta" / "ota-evidence.sqlite")
    assert first.read_bytes() == second.read_bytes()

    left = capture(first, tmp_path, "left")
    right = capture(second, tmp_path, "right")
    assert left["ok"] and right["ok"], (left, right)
    assert left["result"]["sha256"] == right["result"]["sha256"]
    assert left["result"]["events"] == right["result"]["events"]

    left_events = events_of(left, tmp_path / "host-left" / "data" / "backups" / "left-out" / "events.json")
    right_events = events_of(right, tmp_path / "host-right" / "data" / "backups" / "right-out" / "events.json")
    assert left_events == right_events
    for event in left_events:
        lineage = event["source_lineage_ids"]
        assert len(lineage) == 1 and lineage[0].startswith("content_")
        assert not lineage[0].startswith("path_")


def test_same_path_rerun_is_byte_identical(tmp_path):
    store = portal_store(tmp_path, "rerun")
    first = capture(store, tmp_path, "one")
    assert first["ok"], first
    out_one = tmp_path / "host-one" / "data" / "backups" / "one-out" / "events.json"
    # A rerun over the same bytes reproduces the output exactly, into its own
    # preserved bundle (the pre-existing contract).
    repeat = capture(store, tmp_path, "one-repeat")
    assert repeat["ok"], repeat
    assert repeat["result"]["sha256"] == first["result"]["sha256"]
    assert hashlib.sha256(out_one.read_bytes()).hexdigest() == first["result"]["sha256"]


def test_repeat_capture_names_are_content_derived_with_a_preserved_ordinal(tmp_path):
    store = portal_store(tmp_path, "dupe")
    first = capture_named(store, tmp_path, "dupe-host", "dupe-one")
    assert first["ok"], first
    second = capture_named(store, tmp_path, "dupe-host", "dupe-two")
    assert second["ok"], second
    assert second["result"]["sha256"] == first["result"]["sha256"]
    capture_root = tmp_path / "host-dupe-host" / "data" / "backups" / "extractor-baseline-captures"
    names = sorted(item.name for item in capture_root.iterdir() if item.is_dir())
    fingerprint = sqlite_logical_fingerprint(store)
    assert names == [fingerprint, f"{fingerprint}-2"]


# ------------------------------------------------------------ (A) deterministic dir

def test_capture_directory_name_is_the_input_content_fingerprint(tmp_path):
    store = portal_store(tmp_path, "named")
    response = capture(store, tmp_path, "named")
    assert response["ok"], response
    capture_root = tmp_path / "host-named" / "data" / "backups" / "extractor-baseline-captures"
    capture_dir = Path(response["result"]["manifest_path"]).parent
    assert capture_dir.parent == capture_root
    assert capture_dir.name == sqlite_logical_fingerprint(store)
    manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    assert capture_dir.name == manifest["input"]["sqlite_logical_fingerprint"]

# ------------------------------------------------- (B) imported portal sources too

def test_portal_import_boundary_keeps_original_import_path_in_the_stored_locator(tmp_path):
    """Boundary, not a defect of this change.

    ``OtaStore.import_portal`` persists the *original* portal database path in
    ``ota_sources.locator``, and portal rows carry it as ``_source_locator``. Two
    separate imports of the same logical portal database at different paths
    therefore produce stores whose **content genuinely differs** (the locator
    string is part of the stored content), so their fingerprints differ and the
    lineage differs. Identity for those rows follows the original import path by
    design; only rows without a stored locator follow the input's content.
    """
    from app.ota_store import OtaStore
    from tests.card_pipeline.test_ota_portal import portal_database

    plain = portal_database(tmp_path / "plain-a.sqlite")
    shuffled = copy_store(plain, tmp_path / "plain-b.sqlite")
    assert sqlite_logical_fingerprint(plain) == sqlite_logical_fingerprint(shuffled)

    lineages = []
    for index, source in enumerate((plain, shuffled)):
        store = OtaStore(tmp_path / f"store-{index}.sqlite")
        store.import_portal(source)
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()
        response = capture(tmp_path / f"store-{index}.sqlite", tmp_path, f"import-{index}")
        assert response["ok"], response
        events = events_of(response, tmp_path / f"host-import-{index}" / "data" / "backups"
                           / f"import-{index}-out" / "events.json")
        lineages.append({tuple(event["source_lineage_ids"]) for event in events})
    assert lineages[0] != lineages[1]


def test_a_copy_of_the_same_store_is_still_bit_identical(tmp_path):
    """Two byte-identical copies of one store must still produce identical output."""
    store = portal_store(tmp_path, "copy-origin")
    first = copy_store(store, tmp_path / "copy-a" / "ota-evidence.sqlite")
    second = copy_store(store, tmp_path / "copy-b" / "ota-evidence.sqlite")
    left = capture(first, tmp_path, "copy-left")
    right = capture(second, tmp_path, "copy-right")
    assert left["ok"] and right["ok"]
    assert left["result"]["sha256"] == right["result"]["sha256"]


def test_different_content_still_gets_a_different_lineage(tmp_path):
    from app.ota_store import OtaStore
    from tests.card_pipeline.test_ota_portal import portal_database

    first_plain = portal_database(tmp_path / "diff-a.sqlite")
    second_plain = portal_database(tmp_path / "diff-b.sqlite", facts=[{
        "price_components": [
            {"kind": "paid_today", "currency": "KRW", "decimal_text": "31000",
             "minor_units": 31000, "scale": 0, "payment_id": "SYN-OTHER"}]}])
    assert first_plain.read_bytes() != second_plain.read_bytes()

    lineages = []
    for index, source in enumerate((first_plain, second_plain)):
        store = OtaStore(tmp_path / f"diff-store-{index}.sqlite")
        store.import_portal(source)
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()
        response = capture(tmp_path / f"diff-store-{index}.sqlite", tmp_path, f"diff-{index}")
        assert response["ok"], response
        events = events_of(response, tmp_path / f"host-diff-{index}" / "data" / "backups"
                           / f"diff-{index}-out" / "events.json")
        lineages.append(tuple(event["source_lineage_ids"][0] for event in events))
    assert lineages[0] != lineages[1]


def test_manifest_records_the_content_fingerprint_used_for_lineage(tmp_path):
    store = portal_store(tmp_path, "recorded")
    response = capture(store, tmp_path, "recorded")
    assert response["ok"], response
    manifest = json.loads((Path(response["result"]["manifest_path"])).read_text(encoding="utf-8"))
    assert manifest["sources"] == {"capture_mode": "sqlite-backup", "external_source_files": False}
    assert manifest["input"]["sqlite_logical_fingerprint"]


# ---------------------------------------- per-database fingerprints (the fixed "0" key)

def _captured_mapping(read, monkeypatch):
    """The exact mapping the product code hands to the event builder, without changing it."""
    from app import ota_payments
    captured = {}
    real = ota_payments.build_ota_payment_events

    def recorder(sources):
        captured["portal_content_fingerprints"] = dict(sources.get("portal_content_fingerprints") or {})
        return real(sources)

    monkeypatch.setattr(ota_payments, "build_ota_payment_events", recorder)
    response = read()
    return response, captured.get("portal_content_fingerprints")


def test_single_database_fingerprint_stays_the_historical_literal(tmp_path, monkeypatch):
    """The 1-DB path must stay exactly ``{"0": <logical fingerprint>}``."""
    store = portal_store(tmp_path, "literal")
    expected = sqlite_logical_fingerprint(store)
    response, mapping = _captured_mapping(lambda: capture(store, tmp_path, "literal"), monkeypatch)
    assert response["ok"], response
    assert mapping == {"0": expected}
    assert json.dumps(mapping, ensure_ascii=False, sort_keys=True) == json.dumps(
        {"0": expected}, ensure_ascii=False, sort_keys=True)


def test_one_fingerprint_per_registered_database(tmp_path, monkeypatch):
    """The index-aligned helper is a function of the database count, not of one fixed key."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    fingerprint = "f" * 64
    assert _portal_content_fingerprints(snapshot, fingerprint, [snapshot], BridgeError) == {
        "0": fingerprint}
    # Same content registered under three indexes (the M3 multi-DB shape).
    assert _portal_content_fingerprints(
        snapshot, fingerprint, [snapshot, snapshot, snapshot], BridgeError) == {
        "0": fingerprint, "1": fingerprint, "2": fingerprint}


def test_lookups_by_a_second_index_resolve_to_a_content_lineage(tmp_path):
    """A database at index 1 must not fall back to the path-based lineage."""
    from app.ota_sources import source_lineage_id

    fingerprint = sqlite_logical_fingerprint(portal_store(tmp_path, "index-one"))
    expected = _content_lineage(fingerprint)
    other = tmp_path / "elsewhere" / "ota-evidence.sqlite"
    assert source_lineage_id({}, other, content_fingerprint=fingerprint) == expected
    assert source_lineage_id({}, other, content_fingerprint=fingerprint) != source_lineage_id({}, other)


def test_a_database_the_capture_did_not_copy_fails_explicitly(tmp_path):
    """A registered database outside the single snapshot is refused, not silently degraded."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    foreign = tmp_path / "other.sqlite"
    foreign.write_bytes(b"synthetic")
    with pytest.raises(BridgeError) as raised:
        _portal_content_fingerprints(snapshot, "f" * 64, [snapshot, foreign], BridgeError)
    assert raised.value.code == "MULTI_DATABASE_FINGERPRINT_UNSUPPORTED"
    # Only an identical path (one real source) is accepted.
    assert _portal_content_fingerprints(snapshot, "f" * 64, [snapshot, snapshot], BridgeError)


def test_a_hard_link_to_the_snapshot_is_the_same_database(tmp_path):
    """A hard link is one file under a second directory entry, not a second source."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    alias = tmp_path / "alias.sqlite"
    os.link(snapshot, alias)
    # samefile proves the aliasing premise; a platform without hard links cannot
    # answer this question, and pytest skips only after that is established.
    assert os.path.samefile(snapshot, alias)
    assert os.path.realpath(alias) != os.path.realpath(snapshot), (
        "a hard link only reaches this test's code path when realpath keeps it distinct")
    assert _portal_content_fingerprints(
        snapshot, "f" * 64, [snapshot, alias], BridgeError) == {
        "0": "f" * 64, "1": "f" * 64}


def test_an_extended_prefix_naming_the_snapshot_is_the_same_database(tmp_path):
    """``\\\\?\\<path>`` names the snapshot itself; the prefix only changes the spelling."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    given = "\\\\?\\" + str(snapshot.resolve())
    assert _portal_content_fingerprints(
        snapshot, "f" * 64, [snapshot, given], BridgeError) == {
        "0": "f" * 64, "1": "f" * 64}


def test_a_registered_path_that_does_not_exist_is_refused_not_raised(tmp_path):
    """A missing path cannot be the snapshot, and the refusal must survive any OSError."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    missing = tmp_path / "gone.sqlite"
    assert not missing.exists()
    with pytest.raises(BridgeError) as raised:
        _portal_content_fingerprints(snapshot, "f" * 64, [snapshot, missing], BridgeError)
    assert raised.value.code == "MULTI_DATABASE_FINGERPRINT_UNSUPPORTED"


def test_a_different_file_with_identical_bytes_is_still_refused(tmp_path):
    """Content equality is not identity: two separate files stay unsupported."""
    from tools.core_bridge.extract_baseline import _portal_content_fingerprints
    from tools.core_bridge.commands import BridgeError

    snapshot = tmp_path / "snapshot.sqlite"
    snapshot.write_bytes(b"synthetic")
    twin = tmp_path / "twin.sqlite"
    twin.write_bytes(b"synthetic")
    assert os.path.samefile(snapshot, twin) is False
    with pytest.raises(BridgeError) as raised:
        _portal_content_fingerprints(snapshot, "f" * 64, [snapshot, twin], BridgeError)
    assert raised.value.code == "MULTI_DATABASE_FINGERPRINT_UNSUPPORTED"
