"""Synthetic Hana/IBK manifests reuse the established import and receive boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from app import Pipeline
from app.db import Store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from card_collection_fixtures import fixture_bytes

SPEC = importlib.util.spec_from_file_location(
    "import_card_download", ROOT / "tools" / "import_kb_card_download.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

FIXTURES = {
    "hana": ("하나 기업카드 이용내역", "hana-card-synthetic.csv"),
    "ibk": ("IBK 기업카드 이용내역", "ibk-card-synthetic.xlsx"),
}


def make_run(tmp_path, provider, *, count=1, duplicate=False):
    source, filename = FIXTURES[provider]
    content = fixture_bytes(provider)
    run = tmp_path / f"{provider}-run"
    run.mkdir()
    target = run / filename
    target.write_bytes(content)
    row = {
        "source": source,
        "query": {"startDate": "2026-10-01", "endDate": "2026-10-31", "postingAxis": "이용일"},
        "summary": {"available": True, "pageTotalCount": count},
        "file": {"savedPath": str(target), "bytes": len(content),
                 "sha256": hashlib.sha256(content).hexdigest()},
        "verification": {"status": "ok"},
        "parserVerification": {"status": "PARSER_VERIFICATION_OK"},
        "countCheck": {"status": "MATCHED"},
    }
    (run / "manifest.json").write_text(json.dumps({
        "schemaVersion": "cost.kb-card-collection-manifest.v1",
        "runId": provider, "rows": [row, *([dict(row)] if duplicate else [])],
    }), encoding="utf-8")
    return run


@pytest.mark.parametrize("provider", ["hana", "ibk"])
def test_provider_manifest_verifies_and_rehearses_through_pipeline_receive(tmp_path, provider):
    run = make_run(tmp_path, provider)
    _manifest, entries, _no_data = tool.load_run(run)
    files = [tool.verify_file(run, entry) for entry in entries]
    assert files[0]["report"]["count_check"] == "MATCHED"
    db = tmp_path / f"{provider}-board.sqlite"
    store = Store.open(str(db))
    store.close()
    first = tool.rehearse(db, files, tmp_path, f"{provider}-preview")
    assert first["safe"] is True
    receipt = first["receipts"][0]
    assert receipt["row_count"] == 1
    assert receipt["inserted"] == 1
    assert first["reupload_idempotent"] is True


@pytest.mark.parametrize("provider", ["hana", "ibk"])
def test_provider_manifest_duplicate_file_is_idempotently_rejected(tmp_path, provider):
    run = make_run(tmp_path, provider, duplicate=True)
    _manifest, entries, _no_data = tool.load_run(run)
    files = [tool.verify_file(run, entry) for entry in entries]
    db = tmp_path / f"{provider}-duplicate-board.sqlite"
    store = Store.open(str(db))
    store.close()
    result = tool.rehearse(db, files, tmp_path, f"{provider}-duplicate-preview")
    assert result["safe"] is True
    assert sum(receipt["inserted"] for receipt in result["receipts"]) == 1
    assert any(receipt["reused"] for receipt in result["receipts"])


@pytest.mark.parametrize("provider", ["hana", "ibk"])
def test_provider_manifest_rejects_screen_count_mismatch(tmp_path, provider):
    run = make_run(tmp_path, provider, count=2)
    _manifest, entries, _no_data = tool.load_run(run)
    with pytest.raises(tool.ImportBoundaryError) as error:
        tool.verify_file(run, entries[0])
    assert error.value.code == "COUNT_MISMATCH"
