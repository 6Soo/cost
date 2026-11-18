"""구형 스키마에서도 두 조회 경로가 같은 행·금액·합계를 보여준다 (테스트 전용·합성 자료).

`m4-ledger-parity-verify-20261118`의 `test_m4_parity_degraded_env.py`에서 구형 스키마
케이스를 이 후보로 옮긴 것이다. 기대값은 그대로다: 예외 없이, 두 경로가 같은 행 ID
집합·부호 있는 금액·탭 합계를 보여줘야 한다. 이 후보가 통과해야 하는 이유는
`ledger_stay_evidence.manual_period_rows`가 `field` 열이 없는 파일을 빈 집합으로
읽기 때문이다(`webapp/tests/test_manual_period_rows_schema.py`가 그 세 경우를 고정한다).

여기서 흉내 내는 환경(SPEC §11.2.1 적용 순서 2, RFND·수동 교정 보호):
  * `board_manual_overrides`가 `row_id`만 있는 구 기록이고 `board_revisions`가 없다.
  * Rust가 판정을 쓰는 상태다(`WEBLEDGER_CLASSIFICATION_WRITER=rust` + core.sqlite).
    그래야 장부 화면이 이용기간을 읽을 때 수동 기록을 함께 읽는다.
  * 저장 기간이 없는 카드 행 두 개(한 건은 현재 거래도 없음)와 수기 지출 한 건.

합성 자료만 사용한다. 운영 원본·운영 DB·운영 포트·Google 쓰기는 하지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from app import core_writer
from webapp import access_control, ledger_board, ledger_design
from webapp.ledger_store import LedgerStore
from webapp.tests.test_plush_api import call

MARKER_DESCRIPTION = "합성 구형 스키마 행"


@pytest.fixture
def rust_writer(tmp_path, monkeypatch):
    """Rust가 판정을 쓰는 상태: 저장 기간은 core.sqlite에서만 읽는다."""
    core = tmp_path / "core.sqlite"
    sqlite3.connect(core).close()
    monkeypatch.setenv("WEBLEDGER_CLASSIFICATION_WRITER", "rust")
    monkeypatch.setenv("WEBLEDGER_CORE_DB", str(core))
    for name in (core_writer.WRITER_ENV, core_writer.BIN_ENV):
        if name == core_writer.WRITER_ENV:
            monkeypatch.setenv(name, "rust")
    core_writer._FALLBACK.clear()
    core_writer._LAST_READ["periods"] = None
    core_writer._PUBLISHED["key"] = None
    yield core


@pytest.fixture
def bound_store(tmp_path):
    store = LedgerStore(tmp_path / "schema-parity.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


@pytest.fixture
def legacy_owner(monkeypatch):
    """요청 컨텍스트 밖에서 레거시 읽기가 소유자 범위로 동작하게 한다."""
    monkeypatch.setattr(ledger_board, "current_role", lambda: "owner")


def _trip(store):
    return store.create_trip(
        starts_on="2026-11-10", ends_on="2026-11-20",
        destination=f"합성-{uuid.uuid4().hex[:6]}", tab_kind="trip",
        client_request_id=f"parity-trip-{uuid.uuid4()}")["tab_id"]


def _card_row(store, row_id, tab, amount, *, source_event_id, description):
    """source_event_id가 카드 거래와 연결되는 합성 장부 행을 직접 시드한다."""
    record = {
        "amount_krw": amount, "occurred_on": "2026-11-12", "item": "숙박",
        "description": description, "source_kind": "카드",
        "source_event_id": source_event_id, "source_merchant": "합성가맹점",
        "operator_note": "", "pay_method": "카드", "evidence_type": "카드",
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        (row_id, "expense", tab, 1, json.dumps(record, ensure_ascii=False)))
    store.conn.commit()
    return row_id


def _downgrade_override_tables(store, row_ids):
    """구 기록 모양으로 바꾼다: row_id만 있는 수동 기록, 이력 테이블 없음."""
    with store._lock:
        store.conn.execute("DROP TABLE IF EXISTS board_manual_overrides")
        store.conn.execute("CREATE TABLE board_manual_overrides(row_id TEXT)")
        store.conn.executemany("INSERT INTO board_manual_overrides VALUES (?)",
                               [(row_id,) for row_id in row_ids])
        store.conn.execute("DROP TABLE IF EXISTS board_revisions")
        store.conn.commit()


def test_row_id_only_override_schema_keeps_both_paths_readable(
        bound_store, legacy_owner, rust_writer):
    """§11.2.1 적용 순서 2·계약 1·4: 구형 수동 기록 스키마에서도 두 경로가 같은 행·금액을 본다.

    Rust 판정 저장소가 설정된 상태에서 장부 화면은 이용기간을 읽기 전에 수동 기록을
    함께 읽는다(`ledger_design._read_period` → `ledger_stay_evidence.manual_period_rows`).
    구 기록에는 `field` 열이 없어 그 조회가 sqlite3.OperationalError로 끝났고, 레거시
    `/board`는 응답 없이 연결이 닫히는 반면 React 공통 조회는 200을 돌려줬다. 이제 두
    경로 모두 같은 행 ID·부호 있는 금액·탭 합계를 보여야 한다.
    """
    store, _access = bound_store
    tab = _trip(store)
    no_evidence = _card_row(store, "card-TX-LEGACY", tab, 45000,
                            source_event_id="TX-LEGACY",
                            description=MARKER_DESCRIPTION)
    no_transaction = _card_row(store, "card-TX-GONE", tab, 70000,
                               source_event_id="TX-GONE",
                               description="합성 현재 거래 부재")
    manual = store.create_manual_expense(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-12",
                "amount_krw": 12000, "item": "식비", "pay_method": "현금",
                "description": "합성 수기"},
        client_request_id=f"parity-row-{uuid.uuid4()}")["row_id"]
    seeded = {no_evidence, no_transaction, manual}
    expected_sum = 45000 + 70000 + 12000
    _downgrade_override_tables(store, [no_evidence])

    def legacy_view():
        incomes, expenses, _whole_in, _whole_ex = ledger_design._selected_rows(tab, "", "")
        return ({r["row_id"]: ledger_board._shown_amount(r) for r in expenses},
                {r["row_id"]: ledger_design._stay_period(r) for r in expenses},
                {r["row_id"]: ledger_design._stay_text(r) for r in expenses})

    legacy = ({}, {}, {})
    try:
        legacy = legacy_view()
    except Exception as exc:  # noqa: BLE001 - 재현 증거로 남긴다
        pytest.fail(
            "구형 row_id-only 수동 기록 스키마에서 레거시 장부 조회가 예외로 끝남: "
            f"{type(exc).__name__}: {exc}")

    status, body = call(f"/api/plush/ledger?tab={tab}&kind=expense&page_size=200",
                        "syn-owner", store)
    assert status == 200, body
    react_rows = {r["id"]: r["amount"] for r in body["rows"]}

    assert set(legacy[0]) == set(react_rows) == seeded, (
        "구형 스키마에서 두 경로의 행 집합이 다름")
    assert {rid: str(amount) for rid, amount in legacy[0].items()} == react_rows
    assert body["trip"]["expense"] == str(expected_sum)
    assert sum(legacy[0].values()) == expected_sum
    assert body["filtered_total"] == str(expected_sum)
    # 저장되지 않은 이용기간은 두 경로 모두 미확인이며 확정값으로 표시되지 않는다.
    assert legacy[1] == {rid: "" for rid in seeded}, legacy[1]
    assert next(r for r in body["rows"] if r["id"] == no_evidence)["period"] == ""


def test_row_id_only_schema_keeps_a_stored_decision_visible(
        bound_store, legacy_owner, rust_writer):
    """구형 스키마에서도 Rust가 저장한 기간은 두 경로에서 확정값으로 읽힌다.

    수동 기록을 '전부 서비스기간 지정'으로 세면 저장 판정이 가려져 '이용일 확인 필요'가
    된다. 구형 기록은 어떤 필드를 지정했는지 말할 수 없으므로 아무 행도 수동으로 세지
    않고, 저장 판정이 그대로 보여야 한다(DATE-109).
    """
    store, _access = bound_store
    tab = _trip(store)
    rid = _card_row(store, "card-TX-DECIDED", tab, 55000,
                    source_event_id="TX-DECIDED",
                    description="합성 저장 판정")
    _downgrade_override_tables(store, [rid])

    stored = {"TX-DECIDED": {"kind": "verified",
                             "starts_on": "2026-11-10", "ends_on": "2026-11-12"}}

    def fake_stored_periods():
        return stored

    original = ledger_design._stored_periods
    ledger_design._stored_periods = fake_stored_periods
    try:
        incomes, expenses, _wi, _we = ledger_design._selected_rows(tab, "", "")
        legacy_row = next(r for r in expenses if r["row_id"] == rid)
        period, source = ledger_design._read_period(legacy_row, verified=False)
    finally:
        ledger_design._stored_periods = original

    assert source == "decision", (period, source)
    assert period == "2026-11-10~2026-11-12", (
        "구형 스키마 때문에 저장된 이용기간이 사라짐")
