"""예약 원천 행사 식별자와 실제 장부 행사를 소유자가 명시적으로 연결한다.

두 경계를 지킨다.

첫째, 원천 식별자는 불투명 키다. `reservation:` 앞을 잘라내 COST 코드를 얻지 않고,
제목·이름·금액·날짜가 비슷한 행사를 찾아 붙이지 않는다. 소유자가 대상을 직접
고른 경우에만 연결된다. 원천 코드가 이미 실제 장부 행사 코드와 정확히 같으면
기존 경로를 그대로 쓴다 — 해 prefix도 나도 만들지 않는다.

둘째, 연결 저장은 연결만 저장한다. 명단을 운영에 적용하지도, 직원을 승인하지도
않는다. 적용은 별도 계획이 있고, 그 계획은 원래 명단과 현재 연결 버전에서 만들어
진다. 미연결 식별자가 하나라도 있으면 **전체** 적용을 거절하며 부분 명단으로
내려가지 않는다. 부분 적용은 누구의 권한을 조용히 철회하는 일이기 때문이다.

원천 정체성과 적용 정체성은 두 축으로 분리한다. `source_revision`과
`source_digest`는 원천 그대로 보존하고, `link_version`과 `link_digest`를 따로
기록한다. 그래서 같은 원천에 연결만 고쳐 다시 적용하면 기존 "같은 revision 무변경"
처리에 묻히지 않고, 같은 적용을 재시도하면 중복 권한이나 철회가 생기지 않는다.
현재 시각을 revision으로 만들지 않는다. 가짜 revision은 오래된 입력 차단도
무효화하므로 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib

from . import access_control
from .access_control import AccessError

__all__ = [
    "CODE_CONFIG_REQUIRED",
    "CODE_SOURCE_UNREADABLE",
    "CODE_SOURCE_HASH_MISMATCH",
    "CODE_IDENTIFIER_NOT_IN_SOURCE",
    "CODE_TARGET_NOT_FOUND",
    "CODE_TARGET_DELETED",
    "CODE_DUPLICATE_TARGET",
    "CODE_FIELD_MISSING",
    "CODE_FIELD_INVALID",
    "CODE_LINK_CONFLICT",
    "CODE_APPLY_UNLINKED",
    "CODE_APPLY_BINDING_CONFLICT",
    "CODE_APPLY_INPUT_CONFLICT",
    "CODE_APPLY_TARGET_UNAVAILABLE",
    "ReserveLinkError",
    "CONFIG_ENV",
    "load_source_config",
    "read_source",
    "source_binding",
    "build_plan",
    "save_links",
    "apply_plan",
    "ledger_event_choices",
]

#: The owner has not configured a source file. Nothing is searched for and no
#: collection is started: the screen says this and stops.
CODE_CONFIG_REQUIRED = "RESERVE_LINK_CONFIG_REQUIRED"
CODE_SOURCE_UNREADABLE = "RESERVE_LINK_SOURCE_UNREADABLE"
CODE_SOURCE_HASH_MISMATCH = "RESERVE_LINK_SOURCE_HASH_MISMATCH"
#: The submitted source identifier is not in the configured source at all.
CODE_IDENTIFIER_NOT_IN_SOURCE = "RESERVE_LINK_IDENTIFIER_UNKNOWN"
#: The named target is not a ledger event.
CODE_TARGET_NOT_FOUND = "RESERVE_LINK_TARGET_NOT_FOUND"
#: The named target exists but is deleted or archived, so it cannot be granted.
CODE_TARGET_DELETED = "RESERVE_LINK_TARGET_DELETED"
#: The same target was named twice in one save.
CODE_DUPLICATE_TARGET = "RESERVE_LINK_TARGET_DUPLICATED"
#: A required field was absent. Never interpreted as "all" or "none".
CODE_FIELD_MISSING = "RESERVE_LINK_FIELD_MISSING"
#: A field was present with the wrong type. Distinct from missing, because the
#: caller has to look at what it sent rather than at what it left out.
CODE_FIELD_INVALID = "RESERVE_LINK_FIELD_INVALID"
#: Someone else changed the links, or the source moved under the draft.
CODE_LINK_CONFLICT = "RESERVE_LINK_CONFLICT"
#: At least one source identifier has no explicit link. Refuses the whole roster.
CODE_APPLY_UNLINKED = "RESERVE_APPLY_UNLINKED"
#: The apply does not name the current source binding or link revision.
CODE_APPLY_BINDING_CONFLICT = "RESERVE_APPLY_BINDING_CONFLICT"
#: The same request id with different inputs.
CODE_APPLY_INPUT_CONFLICT = "RESERVE_APPLY_INPUT_CONFLICT"
#: A target the plan resolved to is no longer available: deleted, archived, or
#: gone from the directory entirely. Checked at save time *and* inside the apply's
#: transaction, because a target can be withdrawn in between.
CODE_APPLY_TARGET_UNAVAILABLE = "RESERVE_APPLY_TARGET_UNAVAILABLE"
CODE_APPLY_TARGET_DELETED = "RESERVE_APPLY_TARGET_DELETED"
CODE_APPLY_TARGET_MISSING = "RESERVE_APPLY_TARGET_MISSING"

CONFIG_ENV = "WEBLEDGER_RESERVE_SOURCE"

#: Version string recorded with an apply, so the recorded meaning of an apply is
#: readable later without guessing which code produced it.
SYNC_SCHEMA_VERSION = "reserve-link-v1"


class ReserveLinkError(Exception):
    """A refusal in a fixed code. The owner is told the code, never a guess."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _snapshot_identity(snapshot: dict) -> str:
    """What a parsed roster says about itself.

    The semantic digest, which is the only thing a configuration also states. Used
    to prove that the snapshot a caller holds is the export the configuration names,
    rather than merely something that parses. The file's own hash is checked
    separately, because a file can change without changing what it means and that
    is still a change.
    """
    return str(snapshot["digest"])


def _configured_identity(config: dict) -> tuple:
    """What the configuration names: where it is, and what it says.

    The path is part of it, not decoration. Pointing the configuration at a
    different file whose bytes, physical hash and semantic digest all happen to
    match is still a different configuration, and an apply built from the old one
    must not run under the new one — otherwise which file the roster came from
    stops being provable, and "the configured source" becomes "any file that looks
    like it".
    """
    return (_canonical_path(str(config.get("path", ""))),
            str(config["digest"]))


def _canonical_path(value: str) -> str:
    """One spelling of a path, so two names for one file compare equal."""
    try:
        return str(pathlib.Path(value).resolve())
    except (OSError, ValueError):
        return str(value)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    import hashlib as _h

    digest = _h.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------- source config


def load_source_config() -> dict:
    """The owner-configured source file, or the "configuration required" state.

    Three things are required together: a path, the file's own SHA-256, and the
    semantic digest of the parsed roster. The file is not transformed — the
    configured hash is checked against the bytes on disk, and the semantic digest
    against what the strict existing parser read out of them.

    Nothing is discovered here. If this returns the required-config state the
    caller shows that state; it does not go looking for a roster and does not
    begin any collection.
    """
    raw = (os.environ.get(CONFIG_ENV) or "").strip()
    if not raw:
        return {"configured": False, "code": CODE_CONFIG_REQUIRED}
    try:
        described = json.loads(raw)
    except ValueError:
        raise ReserveLinkError(CODE_CONFIG_REQUIRED,
                               "원천 설정 JSON을 읽지 못했어요") from None
    if type(described) is not dict:
        raise ReserveLinkError(CODE_CONFIG_REQUIRED,
                               "원천 설정 형식이 올바르지 않아요")
    path = str(described.get("path") or "").strip()
    file_sha = str(described.get("file_sha256") or "").strip()
    semantic = str(described.get("digest") or "").strip()
    if not path or not file_sha or not semantic:
        # A partial configuration is the required-config state too. Defaulting any
        # of the three would mean trusting an unbound file.
        return {"configured": False, "code": CODE_CONFIG_REQUIRED}
    return {"configured": True, "path": path, "file_sha256": file_sha,
            "digest": semantic}


def _configured_path() -> str:
    """The path the owner configured, exactly as configured.

    Read from the configuration rather than from the snapshot, because a snapshot
    does not know where it came from. The screen shows it so the owner can see
    which file is about to be read, and the apply compares it at commit time.
    """
    raw = (os.environ.get(CONFIG_ENV) or "").strip()
    if not raw:
        return ""
    try:
        described = json.loads(raw)
    except ValueError:
        return ""
    if type(described) is not dict:
        return ""
    return str(described.get("path") or "")


def read_source(config: dict) -> dict:
    """Read and verify the configured roster, through the strict existing parser.

    The file's bytes are checked against the configured file hash and the parsed
    result against the configured semantic digest. Person identifiers, assignment
    identifiers and the export's own revision and digest are carried through
    untouched — this function never rewrites them.
    """
    if not config.get("configured"):
        raise ReserveLinkError(CODE_CONFIG_REQUIRED, "원천 설정이 필요해요")
    path = pathlib.Path(config["path"])
    try:
        raw = path.read_bytes()
    except OSError:
        raise ReserveLinkError(CODE_SOURCE_UNREADABLE,
                               "원천 파일을 읽지 못했어요") from None
    actual_file = hashlib.sha256(raw).hexdigest()
    if actual_file != config["file_sha256"]:
        raise ReserveLinkError(
            CODE_SOURCE_HASH_MISMATCH,
            "원천 파일 해시가 설정과 달라요")
    try:
        from ledger.domain.reservation_access_snapshot import (
            parse_reservation_access_snapshot)
        snapshot = parse_reservation_access_snapshot(raw)
    except Exception:
        raise ReserveLinkError(CODE_SOURCE_UNREADABLE,
                               "예약 명단을 검증하지 못했어요") from None
    if snapshot["digest"] != config["digest"]:
        raise ReserveLinkError(
            CODE_SOURCE_HASH_MISMATCH, "원천 의미 해시가 설정과 달라요")
    return snapshot


def source_binding(snapshot: dict) -> dict:
    """What the screen shows as the current source binding.

    The export's own `snapshot_revision` and `digest` are reproduced exactly. They
    are not recomputed and not bumped: a link correction is not a new export, and
    a screen that showed a different revision would be claiming the source changed
    when only the owner's link decision did.
    """
    return {
        "source_revision": int(snapshot["snapshot_revision"]),
        "source_digest": str(snapshot["digest"]),
        "source_path": _configured_path(),
        "schema_version": str(snapshot["schema_version"]),
        "exported_at": str(snapshot["exported_at"]),
        "file_sha256": hashlib.sha256(_canonical(snapshot).encode(
            "utf-8")).hexdigest(),
    }


def source_identifiers(snapshot: dict) -> list:
    """Every source event identifier the roster names, in roster order.

    Assignment codes, verbatim. The `reservation:` prefix is part of the key and
    is never stripped, and no code is dropped for looking unrecognised — being
    unlinked is a state the screen shows, not a reason to hide the row.
    """
    seen, out = set(), []
    for person in snapshot["persons"]:
        if not person.get("is_active"):
            continue
        for code in person.get("assignments") or []:
            text = str(code)
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out


def ledger_event_choices(store) -> list:
    """The ledger events an owner may choose from, in a stable order.

    Only events that are live: a deleted or archived event is not a choice, and
    the contract's existing rule for hiding archived events is kept as-is. Travel
    completion is *not* a condition here — a finished trip is still a real trip
    and hiding it would hide the target a link most often needs.

    When the ledger has no event table at all this returns an empty list, which is
    the "no targets yet" state rather than an error.
    """
    try:
        rows = store.conn.execute(
            "SELECT tab_id, display_key, destination FROM trip_tabs"
            " WHERE deleted=0 AND archived=0 ORDER BY tab_id").fetchall()
    except Exception:
        # No ledger here yet. An empty list is the honest answer: there is nothing
        # to connect to, and inventing a placeholder would be a fake target.
        return []
    return [{"tab_id": row[0], "label": row[1], "destination": row[2]}
            for row in rows]


# ------------------------------------------------------------------- planning


def build_plan(store, snapshot: dict, *, link_state=None) -> dict:
    """What an apply would do, from the original roster and the current links.

    A read. Nothing is written, and nothing is applied: this is the screen's
    picture of pending work.

    One unlinked identifier refuses the *plan* as an applyable plan rather than
    producing a smaller one. The result carries `applicable: False` and the list
    of unlinked identifiers, so the screen can show both the counts and the reason
    the plan cannot be run.
    """
    state = link_state if link_state is not None else store.reserve_link_state()
    links = dict(state["links"])
    binding = source_binding(snapshot)
    identifiers = source_identifiers(snapshot)
    resolved, unlinked = [], []
    for code in identifiers:
        # Every target the owner named for this identifier, and nothing else. One
        # source identifier may name several ledger events; each is reported and
        # each is granted, and the set is never widened on its own.
        targets = store.resolve_reserve_codes(code, links)
        if not targets:
            unlinked.append(code)
            continue
        for target, origin in targets:
            resolved.append({"source_event_key": code, "target_tab_id": target,
                             "origin": origin})

    persons = []
    for person in snapshot["persons"]:
        persons.append({
            "reservation_person_id": person["reservation_person_id"],
            "display_name": person["display_name"],
            "is_active": person["is_active"],
            "assignments": [str(code) for code in person["assignments"]],
            "connected": store._active_person_connections(
                person["reservation_person_id"]),
        })

    plan = {
        "binding": binding,
        "link_version": state["link_version"],
        "link_revision": state["revision"],
        "link_digest": state["link_digest"],
        "persons": persons,
        "resolved": resolved,
        "unlinked": unlinked,
        # The set each identifier resolves to, so a many-target link is visible in
        # the plan rather than implied by a row count.
        "per_identifier": {
            code: sorted(target for target, _origin
                         in store.resolve_reserve_codes(code, links))
            for code in identifiers},
        "counts": {
            "source_identifiers": len(identifiers),
            "resolved_transactions": len(resolved),
            "unlinked_identifiers": len(unlinked),
            "persons": len(persons),
        },
        "applicable": not unlinked,
    }
    if unlinked:
        plan["refusal_code"] = CODE_APPLY_UNLINKED
    # The apply identity. Source first, then the links, so a link correction on an
    # unchanged source is a new apply rather than a silent no-op.
    plan["apply_digest"] = _digest({
        "source_revision": binding["source_revision"],
        "source_digest": binding["source_digest"],
        "link_version": state["link_version"],
        "link_digest": state["link_digest"],
        "sync_schema_version": SYNC_SCHEMA_VERSION,
        "resolved": sorted((item["source_event_key"], item["target_tab_id"])
                           for item in resolved),
    })
    return plan


# --------------------------------------------------------------- link saving


def _require(payload: dict, field: str):
    if field not in payload:
        # Absent is not "everything". An omitted list is a malformed request, and
        # reading it as select-all would grant every source identifier.
        raise ReserveLinkError(CODE_FIELD_MISSING,
                               "필드가 빠졌어요: " + field)
    return payload[field]


def _validate_targets(store, links: list, unlinks: list) -> dict:
    """Check every submitted link against the source and the ledger.

    Four refusals, each specific: an identifier the source does not contain, a
    target that is not a ledger event, a target that is deleted or archived, and
    the same target named twice.
    """
    # The set of (source, target) pairs. Two identical pairs are a duplicate and
    # are refused; one source naming two *different* targets is the many-target
    # case and is kept.
    planned = {(entry["source_event_key"], entry["target_tab_id"])
               for entry in links}
    if len(planned) != len(links):
        # The same pair twice. One source naming two *different* targets is the
        # many-target case and is kept, so this is only about a real repeat.
        raise ReserveLinkError(CODE_DUPLICATE_TARGET,
                               "같은 연결이 두 번 나왔어요")
    targets = {item["tab_id"] for item in ledger_event_choices(store)}
    all_rows = []
    try:
        all_rows = store.conn.execute(
            "SELECT tab_id, deleted, archived FROM trip_tabs").fetchall()
    except Exception:
        all_rows = []
    known = {row[0]: row for row in all_rows}

    for entry in links:
        code = entry["source_event_key"]
        target = entry["target_tab_id"]
        if type(code) is not str or not code:
            raise ReserveLinkError(CODE_FIELD_MISSING,
                                   "원천 식별자가 필요해요")
        if type(target) is not str or not target:
            raise ReserveLinkError(CODE_FIELD_MISSING,
                                   "대상 행사가 필요해요")
        row = known.get(target)
        if row is None:
            raise ReserveLinkError(CODE_TARGET_NOT_FOUND,
                                   "없는 대상 행사예요: " + target)
        if int(row[1]) or int(row[2]):
            raise ReserveLinkError(CODE_TARGET_DELETED,
                                   "삭제된 대상 행사예요: " + target)
        if target not in targets:
            raise ReserveLinkError(CODE_TARGET_NOT_FOUND,
                                   "없는 대상 행사예요: " + target)
    for code in unlinks:
        if type(code) is not str or not code:
            raise ReserveLinkError(CODE_FIELD_MISSING,
                                   "해제할 원천 식별자가 필요해요")
    return planned


def save_links(store, snapshot: dict, payload: dict, *, owner_id: str) -> dict:
    """Save an explicit link change, in one transaction with its own record.

    The caller submits the source binding it was looking at, the link revision it
    was looking at, the links to make and the links to remove. All four are
    required. A field that is absent is a malformed request, not a request to
    change everything.

    Nothing here applies the roster or approves anyone. This saves links and
    bumps the link version, which is what lets a later apply tell "same links"
    from "links corrected".
    """
    if type(owner_id) is not str or not owner_id:
        raise ReserveLinkError(CODE_FIELD_MISSING, "소유자가 필요해요")
    request_id = _require(payload, "request_id")
    if type(request_id) is not str or not request_id:
        raise ReserveLinkError(CODE_FIELD_MISSING, "요청 식별자가 필요해요")
    presented_binding = _require(payload, "source_binding")
    presented_revision = _require(payload, "link_revision")
    submitted_links = _require(payload, "links")
    submitted_unlinks = _require(payload, "unlinks")
    if type(submitted_links) is not list or type(submitted_unlinks) is not list:
        raise ReserveLinkError(CODE_FIELD_MISSING,
                               "연결과 해제 목록이 올바르지 않아요")
    if type(presented_revision) is not int:
        raise ReserveLinkError(CODE_FIELD_MISSING,
                               "연결 버전이 올바르지 않아요")
    for entry in submitted_links:
        if type(entry) is not dict or set(entry) != {
                "source_event_key", "target_tab_id"}:
            raise ReserveLinkError(CODE_FIELD_MISSING,
                                   "연결 항목이 올바르지 않아요")

    binding = source_binding(snapshot)
    identifiers = set(source_identifiers(snapshot))
    for entry in submitted_links:
        if entry["source_event_key"] not in identifiers:
            # Refused against the *current* source, so a stale draft cannot link an
            # identifier this export does not contain.
            raise ReserveLinkError(
                CODE_IDENTIFIER_NOT_IN_SOURCE,
                "원본에 없는 식별자예요: " + str(entry["source_event_key"]))
    for code in submitted_unlinks:
        if code not in identifiers:
            raise ReserveLinkError(CODE_IDENTIFIER_NOT_IN_SOURCE,
                                   "원본에 없는 식별자예요: " + str(code))

    planned = _validate_targets(store, submitted_links, submitted_unlinks)
    input_digest = _digest({
        "request_id": request_id,
        "source_binding": binding,
        "presented_binding": presented_binding,
        "link_revision": presented_revision,
        "links": sorted(planned),
        "unlinks": sorted(submitted_unlinks),
    })

    def work():
        existing = store.conn.execute(
            "SELECT input_digest, result_json FROM reserve_link_saves"
            " WHERE request_id=?", (request_id,)).fetchone()
        if existing is not None:
            if existing[0] != input_digest:
                raise AccessError(
                    CODE_LINK_CONFLICT,
                    "같은 요청 식별자로 다른 입력이에요", status=409)
            return json.loads(existing[1])
        state = store.reserve_link_state()
        if presented_binding != binding:
            # The source moved under the draft. Reported; the draft is the
            # caller's to keep or discard, never thrown away here.
            raise AccessError(CODE_LINK_CONFLICT,
                              "원천이 바뀌었어요. 다시 확인해 주세요",
                              status=409)
        if int(presented_revision) != int(state["revision"]):
            # Another device saved links first. Their links are still here; the
            # owner's draft is reported as stale rather than silently applied over
            # them.
            raise AccessError(
                CODE_LINK_CONFLICT,
                "다른 기기에서 연결을 바꿨어요. 최신 상태를 확인해 주세요",
                status=409)

        now = access_control.iso(access_control.utc_now())
        revision = int(state["revision"]) + 1
        link_version = int(state["link_version"]) + 1
        for code in submitted_unlinks:
            # A removal names the *source*, so it removes every target that source
            # had. `unlinks` is how a source is cleared; the `links` list is how its
            # target set is stated, and the two together cover every case without a
            # third "remove one target" verb to keep in step with them.
            store.conn.execute(
                "DELETE FROM reserve_event_links WHERE source_event_key=?",
                (code,))
        # Replace, not merge: the submitted list *is* the target set for each source
        # it names. Merging would make a correction additive, so dropping a target
        # from the screen's draft would leave the old one in force — and the owner
        # would have corrected a link that nothing actually corrected. Anything the
        # owner did not name for that source this time is gone, and the omission
        # revokes the trip it no longer names at the next apply.
        for code in sorted({source for source, _target in planned}):
            store.conn.execute(
                "DELETE FROM reserve_event_links WHERE source_event_key=?",
                (code,))
        for code, target in sorted(planned):
            digest = _digest({"source": code, "target": target})
            store.conn.execute(
                "INSERT INTO reserve_event_links(source_event_key, target_tab_id,"
                " link_digest, revision, linked_by, linked_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(source_event_key, target_tab_id) DO UPDATE SET"
                " link_digest=excluded.link_digest,"
                " revision=reserve_event_links.revision+1,"
                " linked_by=excluded.linked_by, linked_at=excluded.linked_at",
                (code, target, digest, 1, owner_id, now))
        after = store.reserve_link_state()
        store.conn.execute(
            "INSERT INTO reserve_link_state(id, link_version, link_digest,"
            " revision) VALUES (1,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET link_version=excluded.link_version,"
            " link_digest=excluded.link_digest,"
            " revision=excluded.revision",
            (link_version, after_link_digest := _digest(
                {key: sorted(value) for key, value in sorted(
                    dict(after["links"]).items())}), revision))
        result = {
            "outcome": "saved",
            "request_id": request_id,
            "linked": [{"source_event_key": code, "target_tab_id": target}
                       for code, target in sorted(planned)],
            "unlinked": sorted(submitted_unlinks),
            "link_version": link_version,
            "link_revision": revision,
            "link_digest": after_link_digest,
            "counts": {"links": len(after["links"])},
        }
        store.conn.execute(
            "INSERT INTO reserve_link_saves(request_id, input_digest,"
            " source_binding, link_revision, result_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (request_id, input_digest,
             json.dumps(binding, ensure_ascii=False, sort_keys=True),
             revision,
             json.dumps(result, ensure_ascii=False, sort_keys=True), now))
        return result

    with store.lock:
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            result = work()
            store.conn.execute("COMMIT")
            return result
        except Exception:
            store.conn.execute("ROLLBACK")
            raise


# -------------------------------------------------------------------- applying


def read_apply_record(store, apply_digest: str):
    """What one apply recorded, or None. Read-only."""
    row = store.conn.execute(
        "SELECT result_json FROM reserve_link_applies WHERE apply_digest=?",
        (apply_digest,)).fetchone()
    return json.loads(row[0]) if row is not None else None


def apply_plan(store, snapshot: dict, *, request_id: str, presented_binding: dict,
               presented_link_revision, presented_apply_digest: str,
               owner_id: str, allow_empty: bool = False,
               allow_large_drop: bool = False, link_map=None) -> dict:
    """Apply the roster through the explicit links, once, atomically.

    Four things are required and all four are checked before anything is written:
    the request id, the current source binding, the current link revision, and the
    plan digest. A field that is absent is refused — it is never widened into
    "apply whatever is there now".

    There are two identities here and they answer different questions.

    The *request* identity is every input this request presented. It is answered
    first, before the revision checks, because a client that lost the original
    response resends the original request — and by then the links may have moved.
    Refusing that would leave it unable to learn its first attempt succeeded, and
    answering it with the current links would apply permissions it never saw. So the
    same request id with the same inputs gets the original receipt, and the same
    request id with different inputs is refused.

    The *apply* identity is the plan digest, which covers the source revision and
    digest *and* the link version and digest. So a link correction against an
    unchanged source is a new apply that reaches the assignments rather than being
    answered as the same-revision no-op the existing guard would report, and a
    second request naming that same plan is that apply arriving again.

    This does not connect staff accounts and does not approve applications. It
    synchronises the roster that already exists, through the links the owner saved.
    """
    if type(request_id) is not str or not request_id:
        raise ReserveLinkError(CODE_FIELD_MISSING, "필드가 빠졌어요: request_id")
    if type(presented_binding) is not dict or not presented_binding:
        # The binding is a mapping of the source's own revision and digest, not a
        # token, because the screen has to display what it is applying.
        raise ReserveLinkError(CODE_FIELD_MISSING,
                               "필드가 빠졌어요: presented_binding")
    if type(presented_apply_digest) is not str or not presented_apply_digest:
        raise ReserveLinkError(CODE_FIELD_MISSING,
                               "필드가 빠졌어요: presented_apply_digest")
    if type(presented_link_revision) is not int:
        raise ReserveLinkError(CODE_FIELD_MISSING, "연결 버전이 필요해요")
    # The two roster overrides are inputs like any other, and they are the most
    # dangerous ones: `allow_empty` is how an empty export is read as "everyone
    # left" and `allow_large_drop` is how a truncated one revokes everybody. Exact
    # booleans, so `1`, `"true"` and `None` cannot arrive wearing a truthy value,
    # and they are refused here rather than silently treated as False — an
    # unrecognised value would otherwise be the *safer* setting by accident, on a
    # field whose unsafe setting is the whole point.
    for name, value in (("allow_empty", allow_empty),
                        ("allow_large_drop", allow_large_drop)):
        if type(value) is not bool:
            raise ReserveLinkError(CODE_FIELD_INVALID,
                                   "필드 형식이 올바르지 않아요: " + name)
    if type(owner_id) is not str or not owner_id:
        raise ReserveLinkError(CODE_FIELD_MISSING, "소유자가 필요해요")

    # The live configuration, kept for the commit-time check. Read here and re-read
    # there: the two have to agree, or the file the plan came from is not the file
    # the owner configured.
    config = load_source_config()
    if not config.get("configured"):
        raise ReserveLinkError(CODE_CONFIG_REQUIRED, "원천 설정이 필요해요")
    # The request's receipt, looked up before anything is re-checked.
    # Everything this request presented, and nothing else. Leaving the roster
    # overrides out would let one request id mean two different applies — the same
    # plan applied once under its own guards and once with `allow_large_drop` — and
    # the receipt for the first would answer the second.
    request_input_digest = _digest({
        "source_binding": presented_binding,
        "link_revision": presented_link_revision,
        "apply_digest": presented_apply_digest,
        "owner_id": owner_id,
        "allow_empty": allow_empty,
        "allow_large_drop": allow_large_drop,
    })
    seen_request = store.conn.execute(
        "SELECT input_digest, result_json FROM reserve_link_apply_requests"
        " WHERE request_id=?", (request_id,)).fetchone()
    if seen_request is not None:
        if seen_request[0] != request_input_digest:
            # One request id, two different sets of inputs. Refused: otherwise the
            # receipt for the first would be handed to the second, and the second
            # would apply whatever the links happened to be when it arrived.
            raise ReserveLinkError(
                CODE_APPLY_INPUT_CONFLICT,
                "같은 요청 식별자로 다른 입력이에요")
        receipt = json.loads(seen_request[1])
        receipt["replayed"] = True
        return receipt

    binding = source_binding(snapshot)
    if presented_binding != binding:
        raise ReserveLinkError(CODE_APPLY_BINDING_CONFLICT,
                               "원천 결속이 달라요")
    state = store.reserve_link_state()
    if int(presented_link_revision) != int(state["revision"]):
        raise ReserveLinkError(CODE_APPLY_BINDING_CONFLICT,
                               "연결 버전이 달라요")

    resolved_links = dict(state["links"]) if link_map is None \
        else dict(link_map)
    # Refuse before opening the write, and refuse the *whole* roster.
    #
    # A partial roster would read as "these people lost their trips", which is a
    # revocation nobody asked for. The owner links the identifiers and runs it
    # again; nothing is half-applied in the meantime.
    try:
        known = store._known_trip_ids() or set()
    except Exception:
        known = set()
    unresolved = []
    for code in source_identifiers(snapshot):
        if not store.resolve_reserve_codes(code, resolved_links) \
                and code not in unresolved:
            unresolved.append(code)
    if unresolved:
        raise ReserveLinkError(
            CODE_APPLY_UNLINKED,
            "연결되지 않은 원천 식별자가 있어요: "
            + ", ".join(sorted(unresolved)[:20]))

    plan = build_plan(store, snapshot, link_state=state)
    if presented_apply_digest != plan["apply_digest"]:
        raise ReserveLinkError(CODE_APPLY_BINDING_CONFLICT,
                               "계획이 바뀌었어요. 다시 확인해 주세요")

    # The apply record and the roster write are one transaction.
    #
    # `sync_reservation_access_snapshot` owns its own `BEGIN IMMEDIATE` and its own
    # guards, so it is not wrapped here — a nested BEGIN would fail outright. It
    # takes an `on_commit` callback instead, which runs *inside* that transaction
    # just before the COMMIT. The apply record is written from there, so it cannot
    # exist without the roster write and cannot be missing when the roster moved.
    # The (source, target) pairs this apply resolved to, for the commit-time check.
    resolved_pairs = sorted(
        (item["source_event_key"], item["target_tab_id"]) for item in plan["resolved"])

    def verify_binding(conn) -> None:
        """Prove, inside the write transaction, that this apply is still current.

        Three things, and each has a way to go stale after the checks above ran:

        * the link set — another connection may have saved links in between, and the
          roster rows about to be committed would then describe the previous
          decision;
        * the source file's own bytes — the file can change on disk while this runs,
          and the configured `file_sha256` is the only thing that says whether what
          is now on disk is the export this plan was built from. The semantic digest
          alone would not catch it, because a roster can gain trailing whitespace
          without changing what it means;
        * the configured binding itself — the owner could have pointed the
          configuration at a different file between the read and the commit.

        Any failure raises, and the sync rolls the whole roster back, so a stale
        apply leaves no permission behind and no apply record.
        """
        # Every target this apply names, re-read inside this transaction.
        #
        # Saving a link proves the target was live then. It says nothing about now:
        # the target can be deleted, archived or removed between the plan and the
        # commit, and the roster rows about to be written would grant a trip that no
        # longer exists. Three answers, three codes — deleted, archived, and gone —
        # because "unavailable" that does not say which leaves the owner guessing
        # whether to unlink it or to restore it.
        try:
            rows = conn.execute(
                "SELECT tab_id, deleted, archived FROM trip_tabs").fetchall()
        except Exception:
            raise access_control._BindingRefused(
                CODE_APPLY_TARGET_UNAVAILABLE,
                "대상 행사 목록을 확인할 수 없어요",
                outcome="refused_targets_unknown") from None
        live_targets = {row[0]: row for row in rows}
        for _source_key, tab_id in resolved_pairs:
            row = live_targets.get(tab_id)
            if row is None:
                raise access_control._BindingRefused(
                    CODE_APPLY_TARGET_MISSING,
                    "없는 대상 행사예요: " + str(tab_id),
                    outcome="refused_target_missing")
            if int(row[1]) or int(row[2]):
                raise access_control._BindingRefused(
                    CODE_APPLY_TARGET_DELETED,
                    "삭제된 대상 행사예요: " + str(tab_id),
                    outcome="refused_target_deleted")

        current = store.reserve_link_state()
        if int(current["link_version"]) != int(state["link_version"]) \
                or int(current["revision"]) != int(state["revision"]):
            raise access_control._BindingRefused(
                CODE_APPLY_BINDING_CONFLICT,
                "연결이 바뀌었어요. 다시 확인해 주세요",
                outcome="refused_links_changed")

        live = load_source_config()
        if not live.get("configured") \
                or live["file_sha256"] != config["file_sha256"] \
                or live["digest"] != config["digest"] \
                or _configured_identity(live) != (
                    _canonical_path(str(config["path"])),
                    _snapshot_identity(snapshot)):
            raise access_control._BindingRefused(
                CODE_APPLY_BINDING_CONFLICT,
                "원천 설정이 바뀌었어요. 다시 확인해 주세요",
                outcome="refused_source_reconfigured")
        # The bytes on disk, checked against the configured file hash. Reading them
        # again here is the point: the semantic digest is unchanged by a whitespace
        # edit, and an edit is still an edit.
        try:
            actual = _sha256_file(pathlib.Path(live["path"]))
        except OSError:
            raise access_control._BindingRefused(
                CODE_SOURCE_UNREADABLE, "원천 파일을 읽지 못했어요",
                outcome="refused_source_unreadable") from None
        if actual != live["file_sha256"]:
            raise access_control._BindingRefused(
                CODE_SOURCE_HASH_MISMATCH, "원천 파일이 바뀌었어요",
                outcome="refused_source_changed")

    def write_apply_record(conn, counts: dict) -> None:
        recorded = {
            "outcome": "applied",
            "request_id": request_id,
            "apply_digest": plan["apply_digest"],
            "source_revision": binding["source_revision"],
            "source_digest": binding["source_digest"],
            "link_version": state["link_version"],
            "link_digest": state["link_digest"],
            "sync_schema_version": SYNC_SCHEMA_VERSION,
            "counts": dict(counts or {}),
            # The whole original request, so an audit reader can see what was asked
            # for and not only what came out. `request_input_digest` proves the two
            # match; this shows what they were.
            "inputs": {
                "source_binding": binding,
                "link_revision": plan["link_revision"],
                "apply_digest": plan["apply_digest"],
                "owner_id": owner_id,
                "allow_empty": allow_empty,
                "allow_large_drop": allow_large_drop,
            },
        }
        conn.execute(
            "INSERT INTO reserve_link_apply_requests(request_id, input_digest,"
            " apply_digest, result_json, created_at) VALUES (?,?,?,?,?)",
            (request_id, request_input_digest, plan["apply_digest"],
             json.dumps(recorded, ensure_ascii=False, sort_keys=True),
             access_control.iso(access_control.utc_now())))
        conn.execute(
            "INSERT INTO reserve_link_applies(apply_digest, request_id,"
            " source_revision, source_digest, link_version, link_digest,"
            " sync_schema_version, result_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (plan["apply_digest"], request_id, binding["source_revision"],
             binding["source_digest"], state["link_version"],
             state["link_digest"], SYNC_SCHEMA_VERSION,
             json.dumps(recorded, ensure_ascii=False, sort_keys=True),
             access_control.iso(access_control.utc_now())))

    with store.lock:
        # Answered from the apply record when the same apply is retried, so a retry
        # grants nothing twice and revokes nothing twice. This check is outside the
        # transaction on purpose: it is a read that may return without writing.
        # The apply digest is the identity of *what was applied*, so this row is the
        # record of one apply rather than of one request. A second request naming
        # the same plan is that same apply arriving again — a client retrying after
        # a lost response, or two screens pressing at once — and it is answered from
        # here. Answering it as a conflict would be wrong in both directions: the
        # work is already done, and refusing would leave the caller unable to learn
        # that it succeeded.
        seen = store.conn.execute(
            "SELECT apply_digest, request_id, result_json FROM reserve_link_applies"
            " WHERE apply_digest=?", (plan["apply_digest"],)).fetchone()
        if seen is not None:
            replayed = json.loads(seen[2])
            replayed["replayed"] = True
            replayed["replayed_from_request_id"] = seen[1]
            return replayed

    try:
        result = store.sync_reservation_access_snapshot(
            snapshot=snapshot, link_map=resolved_links,
            allow_empty=allow_empty, allow_large_drop=allow_large_drop,
            link_version=state["link_version"], apply_digest=plan["apply_digest"],
            on_commit=write_apply_record, verify_binding=verify_binding)
    except AccessError as exc:
        # The sync rolls the roster back and re-raises the commit-time refusal as
        # its own error type. This module's callers — the screen, the route, the
        # tests — are written against one exception, so a refusal that happened at
        # the last possible moment arrives the same way as one that happened at the
        # first. Anything else keeps the sync's code, because those refusals are the
        # existing contract and are not restated here.
        if exc.code in (CODE_APPLY_BINDING_CONFLICT, CODE_SOURCE_HASH_MISMATCH,
                        CODE_SOURCE_UNREADABLE, CODE_APPLY_UNLINKED,
                        CODE_APPLY_TARGET_UNAVAILABLE, CODE_APPLY_TARGET_DELETED,
                        CODE_APPLY_TARGET_MISSING):
            raise ReserveLinkError(exc.code, str(exc)) from None
        raise

    return dict(read_apply_record(store, plan["apply_digest"]) or
                {"outcome": "applied", "request_id": request_id,
                 "apply_digest": plan["apply_digest"],
                 "source_revision": binding["source_revision"],
                 "source_digest": binding["source_digest"],
                 "link_version": state["link_version"],
                 "link_digest": state["link_digest"],
                 "sync_schema_version": SYNC_SCHEMA_VERSION,
                 "counts": {
                     "connected_persons_synced": result.get(
                         "connected_persons_synced", 0),
                     "assignments_applied": result.get("assignments_applied", 0),
                     "assignments_ignored_older": result.get(
                         "assignments_ignored_older", 0),
                     "connections_revoked": result.get("connections_revoked", 0),
                 }})