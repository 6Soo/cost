"""참가자 대조 통합 확인: 수신 → 표시 → 수동 연결 → 재수신 → Google 변경.

합성 자료만 쓴다. 한 번에 한 흐름만 확인하고, Google 원문 행·금액과 사용자의 결정이
전후에 보존되는지 비교한다.
"""
import datetime as dt
import hashlib
import io
import json

import openpyxl

from app import google_authority as ga
from app import participant_income as income
from app import participant_roster as roster
from webapp import google_ledger_page as gl
from webapp import participant_income_page as page

NOW = dt.datetime(2026, 10, 20, 9, 0, tzinfo=ga.KST)
INCOME = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
MATCHED = "가람-합성"
NAME_ONLY = "다온-합성"
OTHER = "이나래-합성"
TAB = "trip-syn-p"
KEY = "0630_오제"


def workbook(*, amount=100000, name_only_name=NAME_ONLY):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(KEY)
    ws["B4"] = "수입 내용"
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    ws["B6"], ws["C6"], ws["H6"] = dt.date(2027, 6, 30), MATCHED, amount
    ws["C7"] = name_only_name
    ws["C9"] = "=sum(H6:H7)"
    ws["B10"] = "지출 내용"
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}11"] = label
    ws["B12"], ws["C12"], ws["H12"] = dt.date(2027, 6, 30), "지출처-합성", 30000
    ws["C13"] = "=SUM(H12:H12)"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def write_roster(root, *, batch_id="batch-syn-p", roster_id="roster-syn-p", revision=1,
                 names=(MATCHED, OTHER)):
    batch = root / "batch"
    (batch / "sources").mkdir(parents=True, exist_ok=True)
    (batch / "sources" / "page-01.png").write_bytes(b"synthetic-roster-source")
    manifest = {
        "schema_version": 1, "batch_id": batch_id, "roster_id": roster_id, "revision": revision,
        "authority": "owner_confirmed_insurance",
        "trip_ref": {"cost_trip_id": TAB, "google_trip_key": KEY},
        "submitted_by": "local-roster-agent", "submitted_at": "2026-10-20T18:00:00+09:00",
        "coverage": {"scope": "partial", "received_pages": [1], "expected_pages": None,
                     "declared_people": None},
        "sources": [{"source_id": "source-syn-p", "path": "sources/page-01.png",
                     "sha256": hashlib.sha256(b"synthetic-roster-source").hexdigest()}],
    }
    participants = {"schema_version": 1, "items": [
        {"source_item_id": f"item-syn-p-{index}", "source_id": "source-syn-p", "page": 1,
         "row_label": str(index + 1), "name": name, "nickname": None, "english_name": None,
         "transcription_status": "verified"} for index, name in enumerate(names)]}
    (batch / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (batch / "participants.json").write_text(json.dumps(participants, ensure_ascii=False), encoding="utf-8")
    return batch


def income_amount_rows(root):
    """비공개 자료에 남은 금액 행. 원문 보존 비교에 쓴다."""
    snapshot = ga.load_snapshot(root / "google-snapshot.json")
    rows = ga.load_rows(root / "google-rows-private.json", snapshot["rows_generation"])
    return rows["main"]["trips"][KEY]["income"]


def income_index_rows(root):
    """이름 인덱스. 금액 없는 이름 행까지 포함한다."""
    snapshot = ga.load_snapshot(root / "google-snapshot.json")
    rows = ga.load_rows(root / "google-rows-private.json", snapshot["rows_generation"])
    return rows["main"]["income_names"][KEY]["income"]


def test_receipt_display_manual_link_resend_and_google_change(tmp_path, monkeypatch):
    root = tmp_path
    # 스냅샷은 두 시간 안에 읽힌 것으로만 현재 확인으로 본다.
    now = dt.datetime.now(ga.KST)
    book = workbook()
    ga.sync(root / "google-snapshot.json", root / "google-rows-private.json",
            fetcher=lambda url: book, now=now)
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(root / "google-snapshot.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(root / "google-rows-private.json"))
    monkeypatch.setenv("WEBLEDGER_PARTICIPANT_DB", str(root / "participant.sqlite"))
    gl.set_mapping(root / "google-snapshot.json", key=KEY, tab_id=TAB, known_keys={KEY})
    gl.record_choice(root / "google-snapshot.json", key=KEY, source="main", at="t")

    # 1. 수신. 명단이 참가 확정이 된다.
    store = roster.ParticipantStore.open(root / "participant.sqlite")
    income.ensure_decision_schema(store.conn)
    try:
        received = roster.register_roster(store, write_roster(root),
                                          trip_resolver=roster.mapping_resolver({KEY: TAB}))
        assert received["status"] == "registered"
        assert received["new_participants"] == 2

        # 2. 표시. 이름이 같은 수입 행은 자동 연결되고, 없는 사람은 이름만 보인다.
        state = page.build_state(TAB, store=store)
        states = {entry["display_name"]: entry["state"] for entry in state["participants"]}
        assert states[MATCHED] == income.STATE_NAME_MATCH
        assert states[OTHER] == income.STATE_NO_INCOME
        assert state["counts"]["participants"] == 2
        assert state["counts"]["linked_income_rows"] == 1

        # 3. 수동 연결. 이름만 있는 원본 행을 다른 참가자에게 연결한다.
        name_only_ref = "main|0630_오제|7"
        target = next(entry for entry in state["participants"] if entry["display_name"] == OTHER)
        saved = income.save_decision(store.conn, participant_id=target["participant_id"],
                                     income_ref=name_only_ref, decision="linked",
                                     link_method="manual", reason="사용자 확인",
                                     income_fingerprint=state["income_rows"][1]["fingerprint"],
                                     decided_by="owner",
                                     presented_fingerprint=state["input_fingerprint"],
                                     current_fingerprint=state["input_fingerprint"])
        assert saved["revision"] == 1
        after = page.build_state(TAB, store=store)
        linked = {entry["display_name"]: entry for entry in after["participants"]}
        assert linked[OTHER]["state"] == income.STATE_MANUAL
        assert linked[OTHER]["links"][0]["row"]["amount"] is None
        assert linked[MATCHED]["state"] == income.STATE_NAME_MATCH
        assert after["counts"]["linked_income_rows"] == 2

        # 4. 재수신. 같은 배치는 같은 결과이고 인원은 늘지 않는다.
        again = roster.register_roster(store, write_roster(root),
                                       trip_resolver=roster.mapping_resolver({KEY: TAB}))
        assert again["reused"] is True
        assert again["new_participants"] == received["new_participants"]
        assert again["registered_at"] == received["registered_at"]
        assert len(store.participants(TAB)) == 2
        assert len(income.decisions_for_trip(store.conn, TAB)) == 1

        # 5. Google 변경. 원본 이름 행이 바뀌면 그 연결만 다시 확인해야 한다.
        before_rows = income_amount_rows(root)
        before_index = income_index_rows(root)
        changed = workbook(name_only_name="바뀐-합성")
        ga.sync(root / "google-snapshot.json", root / "google-rows-private.json",
                fetcher=lambda url: changed, now=now + dt.timedelta(minutes=1))
        after_rows = income_amount_rows(root)
        after_index = income_index_rows(root)
        # 금액 행의 원문과 금액은 그대로다.
        assert after_rows == before_rows
        # 이름 인덱스에서 바뀐 것은 이름이 공란인 그 행뿐이다.
        assert after_index[0] == before_index[0]
        assert after_index[1]["name"] == "바뀐-합성"
        assert before_index[1]["name"] == NAME_ONLY

        moved = page.build_state(TAB, store=store)
        moved_states = {entry["display_name"]: entry["state"] for entry in moved["participants"]}
        # 원문이 바뀐 연결은 확인 대상이 되고, 나머지 연결은 유지된다.
        assert moved_states[OTHER] == income.STATE_NEEDS_CHECK
        assert moved_states[MATCHED] == income.STATE_NAME_MATCH
        assert moved["counts"]["needs_check"] == 1
        assert moved["completion"]["complete"] is False
    finally:
        store.close()
