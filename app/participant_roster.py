"""보험가입 명단의 수신·검증·참가 확정 저장.

전달된 구조화 명단은 실제 참가 확정 근거다. 이 모듈은 배치를 검증하고 참가
확정을 별도 저장소(수입·카드 회계와 다른 SQLite 파일)에 기록한다. Google이나
카드 장부에 쓰지 않고, 수입 조회 실패와 무관하게 참가 확정을 보존한다.

전달 자료의 문구는 데이터다. `confirmed` 같은 값은 권한 증명이 아니며, 여기서
권한을 대신하지 않는다.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

SCHEMA_VERSION = 1
ROSTER_SCHEMA = "participant-roster-v1"

#: 이 요청으로 인정된 참가 근거만 이 값을 쓸 수 있다.
AUTHORITIES = ("owner_confirmed_insurance",)
TRANSCRIPTION_STATUSES = ("verified", "unreadable")
COVERAGE_SCOPES = ("partial", "complete")

MANIFEST_FIELDS = {"schema_version", "batch_id", "roster_id", "revision", "authority",
                   "trip_ref", "submitted_by", "submitted_at", "coverage", "sources"}
TRIP_REF_FIELDS = {"cost_trip_id", "google_trip_key"}
COVERAGE_FIELDS = {"scope", "received_pages", "expected_pages", "declared_people"}
SOURCE_FIELDS = {"source_id", "path", "sha256"}
PARTICIPANT_FIELDS = {"schema_version", "items"}
ITEM_FIELDS = {"source_item_id", "source_id", "page", "row_label", "name", "nickname",
                "english_name", "transcription_status"}

#: 수신 필드로 받지 않는다. 이름 대조에 필요하지 않다.
PERSONAL_FIELDS = frozenset({
    "주민등록번호", "주민번호", "생년월일", "전화번호", "휴대전화", "성별", "여권번호",
    "resident_registration_number", "rrn", "national_id", "birth_date", "birthday",
    "phone", "phone_number", "gender", "sex", "passport_number",
})

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

#: 상태값. `held`는 참가 확정을 만들지 못한 상태, `conflict`는 기존 확정을 보존한 상태다.
STATUS_REGISTERED = "registered"
STATUS_HELD = "held"
STATUS_CONFLICT = "conflict"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS roster_batches (
    batch_id TEXT PRIMARY KEY,
    roster_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    authority TEXT NOT NULL,
    trip_id TEXT NOT NULL DEFAULT '',
    google_trip_key TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    received_pages TEXT NOT NULL DEFAULT '[]',
    expected_pages INTEGER,
    declared_people INTEGER,
    submitted_by TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    status_reason TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_sources (
    batch_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, source_id)
);
CREATE TABLE IF NOT EXISTS roster_items (
    roster_id TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL DEFAULT '',
    page INTEGER,
    row_label TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    english_name TEXT NOT NULL DEFAULT '',
    transcription_status TEXT NOT NULL,
    fingerprint TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL,
    PRIMARY KEY (roster_id, source_item_id)
);
CREATE INDEX IF NOT EXISTS roster_items_source ON roster_items(source_sha256, page, row_label);
CREATE TABLE IF NOT EXISTS trip_participants (
    participant_id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    roster_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    nickname TEXT NOT NULL DEFAULT '',
    english_name TEXT NOT NULL DEFAULT '',
    authority TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'confirmed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trip_participants_trip ON trip_participants(trip_id);
CREATE TABLE IF NOT EXISTS participant_item_links (
    participant_id TEXT NOT NULL,
    roster_id TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (participant_id, roster_id, source_item_id),
    UNIQUE (roster_id, source_item_id)
);
CREATE TABLE IF NOT EXISTS roster_corrections (
    correction_id TEXT PRIMARY KEY,
    roster_id TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    participant_id TEXT NOT NULL DEFAULT '',
    field TEXT NOT NULL,
    before_value TEXT NOT NULL DEFAULT '',
    after_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
"""


class RosterError(Exception):
    """One code per failure. `code` is what a caller switches on."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


# --------------------------------------------------------------- validation

def _mapping(value, code: str) -> dict:
    if not isinstance(value, dict):
        raise RosterError(code, "객체가 필요해요")
    return value


def _text(value, code: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RosterError(code, "문자열이 필요해요")
    text = value.strip()
    if not text and not allow_empty:
        raise RosterError(code, "값이 비어 있어요")
    return text


def _identifier(value, code: str) -> str:
    text = _text(value, code)
    if not IDENTIFIER.fullmatch(text):
        raise RosterError(code, "식별자 형식이 맞지 않아요")
    return text


def _integer(value, code: str, *, minimum: int = 1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RosterError(code, "숫자가 필요해요")
    return value


def _unknown_keys(value: dict, allowed: set, code: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise RosterError(code, f"알 수 없는 필드: {','.join(extra)}")


def _reject_personal_fields(value: dict, code: str) -> None:
    for key in value:
        normalized = unicodedata.normalize("NFC", str(key)).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in PERSONAL_FIELDS:
            raise RosterError(code, "개인정보 필드는 받지 않아요")


def _safe_relative_path(value, code: str) -> str:
    text = _text(value, code)
    if text.startswith("/") or text.startswith("\\") or re.match(r"^[A-Za-z]:", text):
        raise RosterError(code, "상위 경로 밖의 주소는 받지 않아요")
    parts = [part for part in re.split(r"[\\/]+", text) if part]
    if not parts or any(part in (".", "..") for part in parts):
        raise RosterError(code, "상위 경로 밖의 주소는 받지 않아요")
    return "/".join(parts)


def resolve_source_file(batch_dir: Path, relative: str) -> Path:
    """명단 배치 안의 원본 파일 주소. 배치 밖으로 나가거나 심볼릭 링크면 거부한다."""
    root = Path(batch_dir).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise RosterError("SOURCE_PATH_INVALID", "상위 경로 밖의 주소는 받지 않아요") from None
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise RosterError("SOURCE_PATH_INVALID", "심볼릭 링크는 받지 않아요")
    if not target.exists() or not target.is_file():
        raise RosterError("SOURCE_FILE_MISSING", "원본 파일을 찾지 못했어요")
    return target


def file_sha256(path: Path) -> str:
    digest_value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest_value.update(chunk)
    return digest_value.hexdigest()


def validate_manifest(manifest, *, batch_dir: Path | None = None) -> dict:
    """명단 배치 설명서를 검증한다. 실패하면 코드를 담은 RosterError를 낸다."""
    data = _mapping(manifest, "MANIFEST_INVALID")
    _reject_personal_fields(data, "PERSONAL_FIELD_REJECTED")
    _unknown_keys(data, MANIFEST_FIELDS, "MANIFEST_FIELD_UNKNOWN")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RosterError("SCHEMA_VERSION_UNSUPPORTED", "지원하지 않는 명단 형식이에요")
    batch_id = _identifier(data.get("batch_id"), "MANIFEST_BATCH_ID_INVALID")
    roster_id = _identifier(data.get("roster_id"), "MANIFEST_ROSTER_ID_INVALID")
    revision = _integer(data.get("revision"), "MANIFEST_REVISION_INVALID")
    authority = _text(data.get("authority"), "MANIFEST_AUTHORITY_INVALID")
    if authority not in AUTHORITIES:
        raise RosterError("AUTHORITY_UNSUPPORTED", "인정된 참가 근거가 아니에요")
    trip_ref = _mapping(data.get("trip_ref"), "TRIP_REF_INVALID")
    _unknown_keys(trip_ref, TRIP_REF_FIELDS, "TRIP_REF_FIELD_UNKNOWN")
    cost_trip_id = _text(trip_ref.get("cost_trip_id"), "TRIP_REF_INVALID")
    google_trip_key = _text(trip_ref.get("google_trip_key"), "TRIP_REF_INVALID")
    submitted_by = _text(data.get("submitted_by"), "MANIFEST_SUBMITTER_INVALID")
    submitted_at = _text(data.get("submitted_at"), "MANIFEST_SUBMITTED_AT_INVALID")
    try:
        dt.datetime.fromisoformat(submitted_at)
    except ValueError:
        raise RosterError("MANIFEST_SUBMITTED_AT_INVALID", "작성 시각 형식이 맞지 않아요") from None

    coverage = _mapping(data.get("coverage"), "COVERAGE_INVALID")
    _unknown_keys(coverage, COVERAGE_FIELDS, "COVERAGE_FIELD_UNKNOWN")
    scope = _text(coverage.get("scope"), "COVERAGE_INVALID")
    if scope not in COVERAGE_SCOPES:
        raise RosterError("COVERAGE_INVALID", "자료 범위 값이 맞지 않아요")
    pages = coverage.get("received_pages")
    if not isinstance(pages, list) or not pages:
        raise RosterError("COVERAGE_INVALID", "받은 페이지 목록이 필요해요")
    received_pages = []
    for page in pages:
        received_pages.append(_integer(page, "COVERAGE_INVALID"))
    if len(set(received_pages)) != len(received_pages):
        raise RosterError("COVERAGE_INVALID", "같은 페이지를 두 번 받았어요")
    expected_pages = coverage.get("expected_pages")
    if expected_pages is not None:
        expected_pages = _integer(expected_pages, "COVERAGE_INVALID")
    declared_people = coverage.get("declared_people")
    if declared_people is not None:
        declared_people = _integer(declared_people, "COVERAGE_INVALID", minimum=0)
    if scope == "complete":
        if expected_pages is None or declared_people is None:
            raise RosterError("COVERAGE_INCOMPLETE", "전체 명단에는 예상 페이지와 인원이 필요해요")
        if len(received_pages) != expected_pages:
            raise RosterError("COVERAGE_INCOMPLETE", "받은 페이지가 전체 분량과 다릅니다")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RosterError("MANIFEST_SOURCES_INVALID", "원본 목록이 필요해요")
    checked_sources = []
    seen_ids = set()
    for source in sources:
        entry = _mapping(source, "MANIFEST_SOURCES_INVALID")
        _reject_personal_fields(entry, "PERSONAL_FIELD_REJECTED")
        _unknown_keys(entry, SOURCE_FIELDS, "SOURCE_FIELD_UNKNOWN")
        source_id = _identifier(entry.get("source_id"), "SOURCE_ID_INVALID")
        if source_id in seen_ids:
            raise RosterError("SOURCE_ID_INVALID", "같은 원본 id가 두 번 나왔어요")
        seen_ids.add(source_id)
        path = _safe_relative_path(entry.get("path"), "SOURCE_PATH_INVALID")
        sha256 = _text(entry.get("sha256"), "SOURCE_HASH_INVALID")
        if not SHA256.fullmatch(sha256):
            raise RosterError("SOURCE_HASH_INVALID", "해시 형식이 맞지 않아요")
        if batch_dir is not None:
            target = resolve_source_file(batch_dir, path)
            actual = file_sha256(target)
            if actual != sha256:
                raise RosterError("SOURCE_HASH_MISMATCH", "원본 해시가 다릅니다")
        checked_sources.append({"source_id": source_id, "path": path, "sha256": sha256})

    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "roster_id": roster_id,
        "revision": revision,
        "authority": authority,
        "trip_ref": {"cost_trip_id": cost_trip_id, "google_trip_key": google_trip_key},
        "submitted_by": submitted_by,
        "submitted_at": submitted_at,
        "coverage": {"scope": scope, "received_pages": sorted(received_pages),
                     "expected_pages": expected_pages, "declared_people": declared_people},
        "sources": checked_sources,
    }


def validate_participants(participants, manifest: dict) -> dict:
    """명단 항목을 검증한다. 이름은 원문 그대로 보존하고 비교값은 만들지 않는다."""
    data = _mapping(participants, "PARTICIPANTS_INVALID")
    _reject_personal_fields(data, "PERSONAL_FIELD_REJECTED")
    _unknown_keys(data, PARTICIPANT_FIELDS, "PARTICIPANT_FIELD_UNKNOWN")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RosterError("SCHEMA_VERSION_UNSUPPORTED", "지원하지 않는 명단 형식이에요")
    items = data.get("items")
    if not isinstance(items, list):
        raise RosterError("PARTICIPANTS_INVALID", "명단 목록이 필요해요")
    source_ids = {source["source_id"] for source in manifest["sources"]}
    received_pages = set(manifest["coverage"]["received_pages"])
    seen = set()
    checked = []
    for item in items:
        entry = _mapping(item, "PARTICIPANT_INVALID")
        _reject_personal_fields(entry, "PERSONAL_FIELD_REJECTED")
        _unknown_keys(entry, ITEM_FIELDS, "PARTICIPANT_FIELD_UNKNOWN")
        source_item_id = _identifier(entry.get("source_item_id"), "PARTICIPANT_ITEM_ID_INVALID")
        if source_item_id in seen:
            raise RosterError("PARTICIPANT_ITEM_ID_INVALID", "같은 항목 id가 두 번 나왔어요")
        seen.add(source_item_id)
        source_id = _text(entry.get("source_id"), "PARTICIPANT_SOURCE_INVALID")
        if source_id not in source_ids:
            raise RosterError("PARTICIPANT_SOURCE_INVALID", "명단에 없는 원본이에요")
        page = entry.get("page")
        if page is not None:
            page = _integer(page, "PARTICIPANT_PAGE_INVALID")
            if received_pages and page not in received_pages:
                raise RosterError("PARTICIPANT_PAGE_INVALID", "받은 페이지 밖의 항목이에요")
        row_label = entry.get("row_label")
        row_label = "" if row_label is None else _text(row_label, "PARTICIPANT_ROW_INVALID", allow_empty=True)
        name = entry.get("name")
        name = None if name is None else _text(name, "PARTICIPANT_NAME_INVALID", allow_empty=True)
        nickname = entry.get("nickname")
        nickname = None if nickname is None else _text(nickname, "PARTICIPANT_NAME_INVALID", allow_empty=True)
        english_name = entry.get("english_name")
        english_name = None if english_name is None else _text(english_name, "PARTICIPANT_NAME_INVALID", allow_empty=True)
        status = _text(entry.get("transcription_status"), "TRANSCRIPTION_INVALID")
        if status not in TRANSCRIPTION_STATUSES:
            raise RosterError("TRANSCRIPTION_INVALID", "판독 상태 값이 맞지 않아요")
        if status == "verified" and not name:
            raise RosterError("TRANSCRIPTION_INVALID", "확인된 항목에는 이름이 필요해요")
        if name and re.fullmatch(r"[\d\s\-]+", name):
            # 보험 식별 숫자는 이름이 아니다. 날짜나 금액으로 해석하지 않는다.
            raise RosterError("PARTICIPANT_NAME_INVALID", "숫자 식별자는 이름이 아니에요")
        checked.append({
            "source_item_id": source_item_id,
            "source_id": source_id,
            "page": page,
            "row_label": row_label,
            "name": name or "",
            "nickname": nickname or "",
            "english_name": english_name or "",
            "transcription_status": status,
        })
    return {"schema_version": SCHEMA_VERSION, "items": checked}


# ------------------------------------------------------------------- store

class ParticipantStore:
    """참가·명단 저장소. 수입·카드 회계 저장소와 다른 파일을 쓴다."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @classmethod
    def open(cls, path) -> "ParticipantStore":
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=15, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        store = cls(conn)
        store.ensure_schema()
        return store

    @classmethod
    def open_readonly(cls, path) -> "ParticipantStore":
        """Reads a prepared store without creating or changing anything."""
        target = Path(path).resolve()
        if not target.exists():
            raise FileNotFoundError(str(target))
        conn = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=15)
        conn.execute("PRAGMA busy_timeout=10000")
        return cls(conn)

    def ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)

    @contextlib.contextmanager
    def transaction(self):
        """One write transaction. The comparison and the write commit together or not at all."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    # ----------------------------------------------------------- reading

    def batch(self, batch_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT batch_id, roster_id, revision, fingerprint, authority, trip_id, google_trip_key,"
            " scope, received_pages, expected_pages, declared_people, submitted_by, submitted_at,"
            " status, status_reason, result_json, created_at, updated_at FROM roster_batches"
            " WHERE batch_id=?", (batch_id,)).fetchone()
        return _batch_row(row)

    def batches(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT batch_id, roster_id, revision, fingerprint, authority, trip_id, google_trip_key,"
            " scope, received_pages, expected_pages, declared_people, submitted_by, submitted_at,"
            " status, status_reason, result_json, created_at, updated_at FROM roster_batches"
            " ORDER BY created_at, batch_id").fetchall()
        return [_batch_row(row) for row in rows]

    def participants(self, trip_id: str, *, active_only: bool = True) -> list[dict]:
        query = ("SELECT participant_id, trip_id, roster_id, display_name, nickname, english_name,"
                 " authority, role, active, state, created_at, updated_at FROM trip_participants"
                 " WHERE trip_id=?")
        if active_only:
            query += " AND active=1"
        query += " ORDER BY created_at, participant_id"
        rows = self.conn.execute(query, (trip_id,)).fetchall()
        return [{"participant_id": r[0], "trip_id": r[1], "roster_id": r[2], "display_name": r[3],
                 "nickname": r[4], "english_name": r[5], "authority": r[6], "role": r[7],
                 "active": bool(r[8]), "state": r[9], "created_at": r[10], "updated_at": r[11]}
                for r in rows]

    def participant(self, participant_id: str) -> dict | None:
        rows = self.participants_all()
        for item in rows:
            if item["participant_id"] == participant_id:
                return item
        return None

    def participants_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT participant_id, trip_id, roster_id, display_name, nickname, english_name,"
            " authority, role, active, state, created_at, updated_at FROM trip_participants"
            " ORDER BY trip_id, created_at, participant_id").fetchall()
        return [{"participant_id": r[0], "trip_id": r[1], "roster_id": r[2], "display_name": r[3],
                 "nickname": r[4], "english_name": r[5], "authority": r[6], "role": r[7],
                 "active": bool(r[8]), "state": r[9], "created_at": r[10], "updated_at": r[11]}
                for r in rows]

    def items(self, roster_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT roster_id, source_item_id, batch_id, source_id, source_sha256, page, row_label,"
            " name, nickname, english_name, transcription_status, fingerprint, registered_at"
            " FROM roster_items WHERE roster_id=? ORDER BY registered_at, source_item_id",
            (roster_id,)).fetchall()
        return [{"roster_id": r[0], "source_item_id": r[1], "batch_id": r[2], "source_id": r[3],
                 "source_sha256": r[4], "page": r[5], "row_label": r[6], "name": r[7],
                 "nickname": r[8], "english_name": r[9], "transcription_status": r[10],
                 "fingerprint": r[11], "registered_at": r[12]} for r in rows]

    def corrections(self, *, state: str | None = None) -> list[dict]:
        query = ("SELECT correction_id, roster_id, source_item_id, participant_id, field, before_value,"
                 " after_value, reason, state, created_at FROM roster_corrections")
        params: tuple = ()
        if state:
            query += " WHERE state=?"
            params = (state,)
        query += " ORDER BY created_at, correction_id"
        rows = self.conn.execute(query, params).fetchall()
        return [{"correction_id": r[0], "roster_id": r[1], "source_item_id": r[2], "participant_id": r[3],
                 "field": r[4], "before_value": r[5], "after_value": r[6], "reason": r[7],
                 "state": r[8], "created_at": r[9]} for r in rows]

    def events(self, subject: str = "") -> list[dict]:
        if subject:
            rows = self.conn.execute(
                "SELECT event_id, at, kind, subject, detail_json FROM roster_events"
                " WHERE subject=? ORDER BY event_id", (subject,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT event_id, at, kind, subject, detail_json FROM roster_events"
                " ORDER BY event_id").fetchall()
        return [{"event_id": r[0], "at": r[1], "kind": r[2], "subject": r[3],
                 "detail": json.loads(r[4])} for r in rows]

    # ----------------------------------------------------------- writing

    def log_event(self, kind: str, subject: str, detail: dict) -> None:
        self.conn.execute(
            "INSERT INTO roster_events(at, kind, subject, detail_json) VALUES (?,?,?,?)",
            (utc_now(), kind, subject, canonical(detail or {})))


def _batch_row(row) -> dict | None:
    if row is None:
        return None
    return {"batch_id": row[0], "roster_id": row[1], "revision": row[2], "fingerprint": row[3],
            "authority": row[4], "trip_id": row[5], "google_trip_key": row[6], "scope": row[7],
            "received_pages": json.loads(row[8] or "[]"), "expected_pages": row[9],
            "declared_people": row[10], "submitted_by": row[11], "submitted_at": row[12],
            "status": row[13], "status_reason": row[14], "result": json.loads(row[15] or "{}"),
            "created_at": row[16], "updated_at": row[17]}


def _participant_id(trip_id: str, roster_id: str, source_item_id: str) -> str:
    return "pt-" + hashlib.sha256(f"{trip_id}|{roster_id}|{source_item_id}".encode("utf-8")).hexdigest()[:24]


def _item_fingerprint(item: dict) -> str:
    return hashlib.sha256(canonical({
        "name": item["name"], "nickname": item["nickname"], "english_name": item["english_name"],
        "page": item["page"], "row_label": item["row_label"],
        "source_id": item["source_id"],
    }).encode("utf-8")).hexdigest()


def register_roster(store: ParticipantStore, batch_dir, *, trip_resolver=None, now: str | None = None) -> dict:
    """명단 배치를 등록한다. 같은 배치·같은 내용이면 같은 결과를 돌려준다.

    `trip_resolver`는 `trip_ref`를 받아 그 여행을 가리키는 `{"trip_id", "google_trip_key"}`
    를 돌려주거나, 모호하면 None을 돌려준다. None이면 참가 확정을 만들지 않고 보류한다.
    """
    root = Path(batch_dir)
    manifest_raw = _read_json(root / "manifest.json", "BATCH_UNREADABLE")
    participants_raw = _read_json(root / "participants.json", "BATCH_UNREADABLE")
    manifest = validate_manifest(manifest_raw, batch_dir=root)
    participants = validate_participants(participants_raw, manifest)
    fingerprint = digest({"manifest": manifest, "participants": participants})
    stamp = now or utc_now()
    batch_id = manifest["batch_id"]
    roster_id = manifest["roster_id"]

    conn = store.conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = store.batch(batch_id)
        if existing is not None and existing["fingerprint"] != fingerprint:
            conn.execute("ROLLBACK")
            raise RosterError("SOURCE_ID_CONFLICT", "같은 배치 id로 다른 내용이 왔어요")

        trip = None
        if trip_resolver is not None:
            trip = trip_resolver(manifest["trip_ref"])
        if not trip or not trip.get("trip_id"):
            if existing is not None:
                # 이미 보류된 배치다. 내용은 같고 여행 연결만 아직 없다.
                result = dict(existing["result"])
                result["reused"] = True
                conn.execute("COMMIT")
                return result
            result = {
                "batch_id": batch_id, "roster_id": roster_id, "revision": manifest["revision"],
                "status": STATUS_HELD, "status_reason": "TRIP_MAPPING_REQUIRED",
                "reused": False, "trip_id": "", "google_trip_key": "",
                "new_participants": 0, "reused_participants": 0,
                "pending_items": [], "conflict_items": [], "corrections": [],
                "income_reconciliation": "unavailable", "registered_at": stamp,
            }
            _insert_batch(conn, manifest, fingerprint, "", "", STATUS_HELD, "TRIP_MAPPING_REQUIRED",
                          result, stamp)
            store.log_event("roster_held", batch_id, {"reason": "TRIP_MAPPING_REQUIRED"})
            conn.execute("COMMIT")
            return result
        if existing is not None and existing["status"] != STATUS_HELD:
            # 같은 배치·같은 내용이다. 최초 결과를 그대로 돌려주고 항목과 이력을 다시 쓰지 않는다.
            result = dict(existing["result"])
            result["reused"] = True
            conn.execute("COMMIT")
            return result

        trip_id = trip["trip_id"]
        google_trip_key = trip.get("google_trip_key") or manifest["trip_ref"]["google_trip_key"]
        source_hashes = {source["source_id"]: source["sha256"] for source in manifest["sources"]}
        new_participants = 0
        reused_participants = 0
        pending_items = []
        conflict_items = []
        corrections = []
        for item in participants["items"]:
            source_sha = source_hashes.get(item["source_id"], "")
            conn.execute(
                "INSERT INTO roster_items(roster_id, source_item_id, batch_id, source_id, source_sha256,"
                " page, row_label, name, nickname, english_name, transcription_status, fingerprint,"
                " registered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(roster_id, source_item_id) DO UPDATE SET batch_id=excluded.batch_id,"
                " source_sha256=excluded.source_sha256, page=excluded.page, row_label=excluded.row_label,"
                # 등록된 이름은 나중에 온 판독본으로 덮지 않는다. 바뀐 이름은 정정 제안으로 남긴다.
                " name=CASE WHEN roster_items.name='' THEN excluded.name ELSE roster_items.name END,"
                " nickname=CASE WHEN roster_items.name='' THEN excluded.nickname ELSE roster_items.nickname END,"
                " english_name=CASE WHEN roster_items.name='' THEN excluded.english_name"
                "  ELSE roster_items.english_name END,"
                " transcription_status=excluded.transcription_status, fingerprint=excluded.fingerprint",
                (roster_id, item["source_item_id"], batch_id, item["source_id"], source_sha,
                 item["page"], item["row_label"], item["name"], item["nickname"], item["english_name"],
                 item["transcription_status"], _item_fingerprint(item), stamp))
            if item["transcription_status"] != "verified":
                pending_items.append(item["source_item_id"])
                continue
            linked = conn.execute(
                "SELECT participant_id FROM participant_item_links WHERE roster_id=? AND source_item_id=?",
                (roster_id, item["source_item_id"])).fetchone()
            participant_id = linked[0] if linked else None
            evidence = "roster_item"
            if participant_id is None:
                # 명단 id가 바뀌어 같은 원본을 다시 보냈는지 원본 해시와 위치로 찾는다.
                resend = conn.execute(
                    "SELECT l.participant_id FROM roster_items i"
                    " JOIN participant_item_links l ON l.roster_id=i.roster_id"
                    "  AND l.source_item_id=i.source_item_id"
                    " WHERE i.source_sha256=? AND i.page IS ? AND i.row_label=?"
                    " ORDER BY i.registered_at LIMIT 1",
                    (source_sha, item["page"], item["row_label"])).fetchone()
                if resend is not None:
                    participant_id = resend[0]
                    evidence = "resend_source_hash"
            if participant_id is None:
                participant_id = _participant_id(trip_id, roster_id, item["source_item_id"])
            current = conn.execute(
                "SELECT trip_id, display_name, nickname, english_name, state FROM trip_participants"
                " WHERE participant_id=?", (participant_id,)).fetchone()
            if current is None:
                conn.execute(
                    "INSERT INTO trip_participants(participant_id, trip_id, roster_id, display_name,"
                    " nickname, english_name, authority, role, active, state, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (participant_id, trip_id, roster_id, item["name"], item["nickname"],
                     item["english_name"], manifest["authority"], "", 1, "confirmed", stamp, stamp))
                conn.execute(
                    "INSERT INTO participant_item_links(participant_id, roster_id, source_item_id,"
                    " evidence, created_at) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(roster_id, source_item_id) DO UPDATE SET"
                    " participant_id=excluded.participant_id, evidence=excluded.evidence",
                    (participant_id, roster_id, item["source_item_id"], evidence, stamp))
                new_participants += 1
                continue

            if current[0] != trip_id:
                # 다른 여행으로 바뀐 같은 항목. 기존 확정은 보존하고 이 배치를 보류한다.
                conflict_items.append(item["source_item_id"])
                continue
            if current[1] != item["name"] or current[2] != item["nickname"] or current[3] != item["english_name"]:
                correction_id = "rc-" + hashlib.sha256(
                    f"{roster_id}|{item['source_item_id']}|{item['name']}".encode("utf-8")).hexdigest()[:24]
                conn.execute(
                    "INSERT INTO roster_corrections(correction_id, roster_id, source_item_id, participant_id,"
                    " field, before_value, after_value, reason, state, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(correction_id) DO UPDATE SET after_value=excluded.after_value,"
                    " before_value=excluded.before_value, state=excluded.state",
                    (correction_id, roster_id, item["source_item_id"], participant_id, "name",
                     current[1], item["name"], "roster_revision", "proposed", stamp))
                conn.execute(
                    "UPDATE trip_participants SET state='correction_pending', updated_at=?"
                    " WHERE participant_id=?", (stamp, participant_id))
                corrections.append(correction_id)
            conn.execute(
                "INSERT INTO participant_item_links(participant_id, roster_id, source_item_id,"
                " evidence, created_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(roster_id, source_item_id) DO UPDATE SET"
                " participant_id=excluded.participant_id, evidence=excluded.evidence",
                (participant_id, roster_id, item["source_item_id"], evidence, stamp))
            reused_participants += 1

        status = STATUS_CONFLICT if conflict_items else STATUS_REGISTERED
        result = {
            "batch_id": batch_id, "roster_id": roster_id, "revision": manifest["revision"],
            "status": status, "status_reason": "SOURCE_ID_CONFLICT" if conflict_items else "",
            "reused": existing is not None, "trip_id": trip_id, "google_trip_key": google_trip_key,
            "new_participants": new_participants, "reused_participants": reused_participants,
            "pending_items": pending_items, "conflict_items": conflict_items, "corrections": corrections,
            "income_reconciliation": "available", "registered_at": stamp,
        }
        if existing is None:
            _insert_batch(conn, manifest, fingerprint, trip_id, google_trip_key, status,
                          result["status_reason"], result, stamp)
        else:
            _update_batch(conn, manifest, fingerprint, trip_id, google_trip_key, status,
                          result["status_reason"], result, stamp)
        for source in manifest["sources"]:
            conn.execute(
                "INSERT INTO roster_sources(batch_id, source_id, path, sha256, received_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(batch_id, source_id) DO UPDATE SET path=excluded.path,"
                " sha256=excluded.sha256",
                (batch_id, source["source_id"], source["path"], source["sha256"], stamp))
        store.log_event("roster_registered", batch_id,
                        {"new_participants": new_participants, "reused_participants": reused_participants})
        conn.execute("COMMIT")
        return result
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _insert_batch(conn, manifest: dict, fingerprint: str, trip_id: str, google_trip_key: str,
                  status: str, reason: str, result: dict, stamp: str) -> None:
    conn.execute(
        "INSERT INTO roster_batches(batch_id, roster_id, revision, fingerprint, authority, trip_id,"
        " google_trip_key, scope, received_pages, expected_pages, declared_people, submitted_by,"
        " submitted_at, status, status_reason, result_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (manifest["batch_id"], manifest["roster_id"], manifest["revision"], fingerprint,
         manifest["authority"], trip_id, google_trip_key, manifest["coverage"]["scope"],
         canonical(manifest["coverage"]["received_pages"]), manifest["coverage"]["expected_pages"],
         manifest["coverage"]["declared_people"], manifest["submitted_by"], manifest["submitted_at"],
         status, reason, canonical(result), stamp, stamp))


def _update_batch(conn, manifest: dict, fingerprint: str, trip_id: str, google_trip_key: str,
                  status: str, reason: str, result: dict, stamp: str) -> None:
    conn.execute(
        "UPDATE roster_batches SET trip_id=?, google_trip_key=?, status=?, status_reason=?,"
        " result_json=?, updated_at=? WHERE batch_id=?",
        (trip_id, google_trip_key, status, reason, canonical(result), stamp, manifest["batch_id"]))


def _read_json(path: Path, code: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RosterError(code, "명단 파일을 읽을 수 없어요") from error


def default_db_path() -> Path:
    """기본 저장 위치. Git에서 제외된 로컬 경로다."""
    configured = os.environ.get("WEBLEDGER_PARTICIPANT_DB")
    if configured:
        return Path(configured)
    root = Path(__file__).resolve().parents[1]
    return root / ".local-archive" / "participant-rosters" / "participant.sqlite"


def mapping_resolver(mapping: dict):
    """기존 Google 여행 연결표를 쓰는 여행 확인자.

    `trip_ref`의 COST 여행과 Google 여행 키가 같은 여행을 가리켜야 참가 확정이
    저장된다. 다르면, 없으면, 모호하면 None을 돌려 보류한다.
    """
    table = mapping if isinstance(mapping, dict) else {}

    def resolve(trip_ref) -> dict | None:
        key = (trip_ref or {}).get("google_trip_key")
        tab_id = table.get(key)
        if not tab_id or tab_id != (trip_ref or {}).get("cost_trip_id"):
            return None
        return {"trip_id": tab_id, "google_trip_key": key}

    return resolve


# --------------------------------------------------------------- owner decisions

def correct_participant_name(store: ParticipantStore, participant_id: str, new_name: str, *,
                             reason: str = "", decided_by: str = "") -> dict:
    """이름 정정. 원본 명단과 사용자의 정정을 모두 남긴다."""
    name = _text(new_name, "PARTICIPANT_NAME_INVALID")
    if re.fullmatch(r"[\d\s\-]+", name):
        raise RosterError("PARTICIPANT_NAME_INVALID", "숫자 식별자는 이름이 아니에요")
    row = store.conn.execute(
        "SELECT display_name, trip_id FROM trip_participants WHERE participant_id=?",
        (participant_id,)).fetchone()
    if row is None:
        raise RosterError("PARTICIPANT_NOT_FOUND", "참가자를 찾지 못했어요")
    stamp = utc_now()
    store.conn.execute(
        "UPDATE trip_participants SET display_name=?, state='confirmed', updated_at=?"
        " WHERE participant_id=?", (name, stamp, participant_id))
    store.conn.execute(
        "UPDATE roster_corrections SET state='accepted', reason=? WHERE participant_id=?"
        " AND state='proposed'", (reason or decided_by, participant_id))
    store.log_event("participant_name_corrected", participant_id,
                    {"before": row[0], "after": name, "reason": reason, "by": decided_by})
    return {"participant_id": participant_id, "display_name": name, "trip_id": row[1]}


def remap_participant_trip(store: ParticipantStore, participant_id: str, trip_id: str, *,
                           reason: str = "", decided_by: str = "") -> dict:
    """여행 연결 수정. 참가 확정은 유지되고 연결만 바뀐다."""
    if not trip_id:
        raise RosterError("TRIP_REF_INVALID", "여행이 필요해요")
    row = store.conn.execute(
        "SELECT trip_id FROM trip_participants WHERE participant_id=?", (participant_id,)).fetchone()
    if row is None:
        raise RosterError("PARTICIPANT_NOT_FOUND", "참가자를 찾지 못했어요")
    stamp = utc_now()
    store.conn.execute(
        "UPDATE trip_participants SET trip_id=?, updated_at=? WHERE participant_id=?",
        (trip_id, stamp, participant_id))
    store.log_event("participant_trip_remapped", participant_id,
                    {"before": row[0], "after": trip_id, "reason": reason, "by": decided_by})
    return {"participant_id": participant_id, "trip_id": trip_id}


def add_participant_alias(store: ParticipantStore, participant_id: str, alias: str, *,
                           decided_by: str = "") -> dict:
    """확인된 별칭. 원문에 적힌 값만 대조 비교에 쓴다."""
    text = _text(alias, "PARTICIPANT_NAME_INVALID")
    row = store.conn.execute(
        "SELECT nickname FROM trip_participants WHERE participant_id=?", (participant_id,)).fetchone()
    if row is None:
        raise RosterError("PARTICIPANT_NOT_FOUND", "참가자를 찾지 못했어요")
    stamp = utc_now()
    store.conn.execute(
        "UPDATE trip_participants SET nickname=?, updated_at=? WHERE participant_id=?",
        (text, stamp, participant_id))
    store.log_event("participant_alias_confirmed", participant_id,
                    {"before": row[0], "after": text, "by": decided_by})
    return {"participant_id": participant_id, "nickname": text}


def confirm_same_person(store: ParticipantStore, participant_id: str, other_participant_id: str, *,
                        decided_by: str = "") -> dict:
    """같은 사람 확인. 두 명단 항목이 한 참가자다.

    남는 참가자 하나만 활성 상태로 두고 다른 쪽의 항목 연결을 남는 쪽으로 옮긴다.
    인원은 줄어들지 않고 두 항목이 하나의 참가자로 보인다.
    """
    if participant_id == other_participant_id:
        raise RosterError("INVALID_VALUE", "서로 다른 참가자를 골라 주세요")
    rows = store.conn.execute(
        "SELECT participant_id, trip_id, display_name FROM trip_participants"
        " WHERE participant_id IN (?,?)", (participant_id, other_participant_id)).fetchall()
    if len(rows) != 2:
        raise RosterError("PARTICIPANT_NOT_FOUND", "참가자를 찾지 못했어요")
    if rows[0][1] != rows[1][1]:
        raise RosterError("TRIP_MAPPING_REQUIRED", "다른 여행의 참가자는 합치지 않아요")
    stamp = utc_now()
    links = store.conn.execute(
        "SELECT roster_id, source_item_id FROM participant_item_links WHERE participant_id=?",
        (other_participant_id,)).fetchall()
    for roster_id, source_item_id in links:
        store.conn.execute(
            "DELETE FROM participant_item_links WHERE roster_id=? AND source_item_id=?",
            (roster_id, source_item_id))
        store.conn.execute(
            "INSERT INTO participant_item_links(participant_id, roster_id, source_item_id,"
            " evidence, created_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(roster_id, source_item_id) DO UPDATE SET"
            " participant_id=excluded.participant_id, evidence=excluded.evidence",
            (participant_id, roster_id, source_item_id, "same_person_confirmed", stamp))
    store.conn.execute(
        "UPDATE trip_participants SET active=0, state='merged', updated_at=?"
        " WHERE participant_id=?", (stamp, other_participant_id))
    store.log_event("participants_merged", participant_id,
                    {"merged": other_participant_id, "by": decided_by})
    return {"participant_id": participant_id, "merged": other_participant_id,
            "items_moved": len(links)}
