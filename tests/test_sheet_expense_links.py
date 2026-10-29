"""Isolated local-JSON linkage store tests; no Google or customer data access."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from app import sheet_expense_links as links


def result(tx="cost-1", key="row-id-1", **overrides):
    value = {
        "transaction_id": tx,
        "trip_id": "trip-2026-01",
        "sheet_id": "sheet-main-42",
        "source": "main",
        "row_number": 12,
        "sheet_row_key": key,
        "sheet_fingerprint": "sha256:synthetic-row-v1",
        "basis": ["same_trip", "amount_currency_sign", "merchant"],
        "status": "MATCHED_MANUAL",
    }
    value.update(overrides)
    return value


def save(path, rows, *, revision=0, request="request-1", digest="source-sha"):
    return links.save_links(path, rows, expected_revision=revision,
                            request_id=request, source_digest=digest,
                            now="2026-10-29T00:00:00Z")


def test_save_load_records_scope_stable_key_audit_and_provenance(tmp_path):
    path = tmp_path / "links.json"
    assert links.load_links(path) == {"revision": 0, "links": [], "history": []}
    saved = save(path, [result(user_override=True, link_method="owner_correction")])
    assert saved["revision"] == 1
    record = saved["links"][0]
    assert (record["transaction_id"], record["trip_id"], record["sheet_id"], record["source"]) == (
        "cost-1", "trip-2026-01", "sheet-main-42", "main")
    assert record["stable_key"] == "row-id-1"
    assert record["row_number"] == 12
    assert record["provenance"]["user_override"] is True
    assert record["provenance"]["link_method"] == "owner_correction"
    assert saved["history"][-1]["kind"] == "request"
    assert links.load_links(path) == saved


def test_same_request_replay_is_noop_even_when_clock_differs(tmp_path):
    path = tmp_path / "links.json"
    original = save(path, [result()])
    replay = links.save_links(path, [result()], expected_revision=0, request_id="request-1",
                              source_digest="source-sha", now="2026-10-30T00:00:00Z")
    assert replay == original
    assert replay["revision"] == 1


def test_request_id_reuse_with_different_payload_and_stale_revision_fail(tmp_path):
    path = tmp_path / "links.json"
    save(path, [result()])
    with pytest.raises(links.LinkStoreError, match="LINK_REQUEST_ID_REUSED"):
        save(path, [result(sheet_fingerprint="other")], request="request-1")
    with pytest.raises(links.LinkStoreError, match="LINK_REVISION_CONFLICT"):
        save(path, [result("cost-2", "row-id-2")], request="request-2")


@pytest.mark.parametrize("bad", [
    result(status="NEW_EXPENSE"),
    result(sheet_row_key="12"),
    {**result(), "sheet_id": ""},
    {key: value for key, value in result().items() if key != "source"},
    [result(), result("cost-2", "row-id-1")],
])
def test_invalid_or_unstable_links_are_rejected_without_write(tmp_path, bad):
    path = tmp_path / "links.json"
    with pytest.raises(links.LinkStoreError):
        save(path, bad if isinstance(bad, list) else [bad])
    assert links.load_links(path) == {"revision": 0, "links": [], "history": []}


def test_neither_transaction_nor_sheet_row_can_be_double_occupied(tmp_path):
    path = tmp_path / "links.json"
    save(path, [result()])
    with pytest.raises(links.LinkStoreError, match="SHEET_ROW_ALREADY_LINKED"):
        save(path, [result("cost-2")], revision=1, request="request-2")
    with pytest.raises(links.LinkStoreError, match="TRANSACTION_ALREADY_LINKED"):
        save(path, [result(key="row-id-2")], revision=1, request="request-3")


def test_update_reverified_fingerprint_preserves_history(tmp_path):
    path = tmp_path / "links.json"
    save(path, [result()])
    updated = save(path, [result(sheet_fingerprint="sha256:synthetic-row-v2")], revision=1,
                   request="request-2")
    assert updated["revision"] == 2
    assert updated["links"][0]["sheet_fingerprint"] == "sha256:synthetic-row-v2"
    saved_events = [event for event in updated["history"] if event["kind"] == "link_saved"]
    assert saved_events[-1]["before"]["sheet_fingerprint"] == "sha256:synthetic-row-v1"
    assert saved_events[-1]["after"]["sheet_fingerprint"] == "sha256:synthetic-row-v2"


def test_failed_atomic_replace_keeps_previous_file_intact(tmp_path, monkeypatch):
    path = tmp_path / "links.json"
    save(path, [result()])
    before = path.read_bytes()
    monkeypatch.setattr(links.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(links.LinkStoreError, match="LINKS_WRITE_FAILED"):
        save(path, [result(fingerprint="sha256:v2")], revision=1, request="request-2")
    assert path.read_bytes() == before
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == 1


def test_concurrent_compare_and_swap_allows_exactly_one_writer(tmp_path):
    path = tmp_path / "links.json"
    barrier = threading.Barrier(2)

    def contender(index):
        barrier.wait()
        try:
            save(path, [result(f"cost-{index}", f"row-{index}")],
                 request=f"request-{index}")
            return "saved"
        except links.LinkStoreError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(contender, (1, 2)))
    assert sorted(outcomes) == ["LINK_REVISION_CONFLICT", "saved"]
    current = links.load_links(path)
    assert current["revision"] == 1
    assert len(current["links"]) == 1


def test_concurrent_same_request_replay_creates_one_audit_event(tmp_path):
    path = tmp_path / "same-request.json"
    barrier = threading.Barrier(2)

    def contender():
        barrier.wait()
        return save(path, [result()])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: contender(), range(2)))
    assert first == second
    assert first["revision"] == 1
    assert sum(event["kind"] == "link_saved" for event in first["history"]) == 1
    assert sum(event["kind"] == "request" for event in first["history"]) == 1


def _process_save(path, index):
    try:
        save(path, [result(f"process-cost-{index}", f"process-row-{index}")],
             request=f"process-request-{index}")
        return "saved"
    except links.LinkStoreError as exc:
        return exc.code


def test_cross_process_lock_and_revision_prevent_double_writer(tmp_path):
    import multiprocessing

    path = str(tmp_path / "process-links.json")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)

    output = context.Queue()
    processes = [context.Process(target=_process_save_with_barrier,
                                 args=(path, index, barrier, output)) for index in (1, 2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    outcomes = [output.get(timeout=5), output.get(timeout=5)]
    assert sorted(outcomes) == ["LINK_REVISION_CONFLICT", "saved"]
    stored = links.load_links(path)
    assert stored["revision"] == 1
    assert len(stored["links"]) == 1


def _process_save_with_barrier(path, index, barrier, output):
    barrier.wait(timeout=20)
    output.put(_process_save(path, index))
