from pathlib import Path
import sys

from app.card_preflight import validate_upload
from tools.site_card_collection import count_check, file_evidence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from card_collection_fixtures import fixture_bytes


def test_count_check_requires_exact_integer_match():
    assert count_check(2, 2)["status"] == "MATCHED"
    assert count_check(2, 3)["status"] == "FAILED"
    assert count_check(0, None)["status"] == "FAILED"
    assert count_check(True, 1)["status"] == "FAILED"


def test_synthetic_hana_format_and_hash_are_validated():
    content = fixture_bytes("hana")
    parsed, _ = validate_upload(content, "hana-card-synthetic.csv")
    evidence = file_evidence(content)
    assert len(parsed.rows) == 1
    assert parsed.rows[0].issuer == "하나"
    assert evidence["bytes"] == len(content)
    assert len(evidence["sha256"]) == 64


def test_count_mismatch_fails_closed():
    parsed, _ = validate_upload(
        fixture_bytes("hana"),
        "hana-card-synthetic.csv",
    )
    assert count_check(len(parsed.rows), 2)["status"] == "FAILED"


def test_synthetic_ibk_format_and_count_match():
    content = fixture_bytes("ibk")
    parsed, _ = validate_upload(content, "ibk-card-synthetic.xlsx")
    assert len(parsed.rows) == 1
    assert parsed.rows[0].issuer == "기업"
    assert count_check(len(parsed.rows), 1)["status"] == "MATCHED"
