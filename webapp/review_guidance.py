# -*- coding: utf-8 -*-
"""Reviewed-source guidance: an owner's answer, and a rule learned from it.

A reviewed source row is not a board row. Nothing downstream of the board — no
ledger row, no existing-row classification — can be pointed at it. So this
module answers two separate questions without pretending they are one:

* What did the owner say about this source? That is an answer, bound to the
  source it is about, stored beside the review decisions. It never edits the
  source, a choice, or a ledger row.
* Should future card imports be classified this way? That is a rule, and it is
  built through the existing `LedgerStore` draft/preview/apply path so the same
  classification engine, the same conflict policy and the same server-measured
  impact plan apply to it as to any other rule.

The two are joined by a *proof*: `classification_source_cases` records which
binding and which source ref were verified when the case was registered. The ref
is stored as a hash, and no person, reservation number or note is copied into
it. A rule may therefore say "this was learned from a source row" without
claiming a board row it does not have.

Deterministic only. There is no model call anywhere in this module, and none of
these results may be described as one. Every suggestion here is a reading of a
record that is already on disk.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone

from .classification_rules import RuleError, normalize_draft, normalize_merchant
from .contracts import sha256_text
from .ledger_store import SaveError

# Reuse the review's own refusal vocabulary where it already means the same
# thing, so the UI has one code for one failure rather than a near-synonym.
from .real_review import CODE_BINDING_CONFLICT, CODE_DECISIONS_UNAVAILABLE
from .real_review import CODE_REVISION_CONFLICT

# Guidance-only codes. A source row, a case proof and a preview have no review
# equivalent, so these are new rather than borrowed.
CODE_GUIDANCE_UNAVAILABLE = "GUIDANCE_UNAVAILABLE"
CODE_REF_NOT_FOUND = "GUIDANCE_REF_NOT_FOUND"
CODE_REF_NOT_EXPENSE = "GUIDANCE_REF_NOT_EXPENSE"
CODE_CANDIDATE_NOT_FOUND = "GUIDANCE_CANDIDATE_NOT_FOUND"
CODE_CANDIDATE_REQUIRED = "GUIDANCE_CANDIDATE_REQUIRED"
CODE_REQUEST_ID_REUSED = "GUIDANCE_REQUEST_ID_REUSED"
CODE_TEXT_TOO_LONG = "GUIDANCE_TEXT_TOO_LONG"
CODE_INVALID_VALUE = "GUIDANCE_INVALID_VALUE"
CODE_NOTHING_TO_SAVE = "GUIDANCE_NOTHING_TO_SAVE"
CODE_PREVIEW_NOT_FOUND = "GUIDANCE_PREVIEW_NOT_FOUND"
CODE_PREVIEW_NOT_OWNED = "GUIDANCE_PREVIEW_NOT_OWNED"

# Stable aliases so a caller can import the name it already knows.
CODE_BINDING_STALE = CODE_BINDING_CONFLICT
CODE_DECISIONS_UNAVAILABLE = CODE_DECISIONS_UNAVAILABLE
CODE_REVISION_CONFLICT = CODE_REVISION_CONFLICT

__all__ = [
    "GuidanceError",
    "GuidanceService",
    "CODE_GUIDANCE_UNAVAILABLE",
    "CODE_BINDING_STALE",
    "CODE_BINDING_CONFLICT",
    "CODE_DECISIONS_UNAVAILABLE",
    "CODE_REVISION_CONFLICT",
    "CODE_REF_NOT_FOUND",
    "CODE_REF_NOT_EXPENSE",
    "CODE_CANDIDATE_NOT_FOUND",
    "CODE_CANDIDATE_REQUIRED",
    "CODE_REQUEST_ID_REUSED",
    "CODE_TEXT_TOO_LONG",
    "CODE_INVALID_VALUE",
    "CODE_NOTHING_TO_SAVE",
    "CODE_PREVIEW_NOT_FOUND",
    "CODE_PREVIEW_NOT_OWNED",
    "NOTE_MAX",
    "ITEM_MAX",
    "DESCRIPTION_MAX",
]

# Length limits. A note is prose and gets room; an item is a short label that
# has to fit on a card, and a description is a single line. All three are
# bounded so a paste of a whole spreadsheet cannot end up as one row value.
NOTE_MAX = 2000
ITEM_MAX = 60
DESCRIPTION_MAX = 200
_REQUEST_ID_MAX = 120

_BLOCK_EXPENSE = "expense"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_source_guidance (
    binding TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_ref_sha256 TEXT NOT NULL,
    revision INTEGER NOT NULL,
    note TEXT NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (binding, source_ref)
);
CREATE TABLE IF NOT EXISTS review_guidance_requests (
    binding TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    response_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (binding, source_ref, request_id)
);
CREATE TABLE IF NOT EXISTS review_guidance_previews (
    preview_id TEXT PRIMARY KEY,
    binding TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    apply_existing INTEGER NOT NULL,
    apply_future INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_guidance_results (
    binding TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    answer_revision INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY (binding, source_ref, answer_revision)
);
"""


class GuidanceError(Exception):
    """One code, one meaning. The UI switches on `code`, never on the message."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _raise(code: str, message: str = "") -> None:
    raise GuidanceError(code, message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, limit: int, label: str, code: str) -> str:
    """Accept a string, bound it, and never coerce another type into one."""
    if value is None:
        return ""
    if not isinstance(value, str):
        _raise(code, f"{label} 형식이 달라요")
    cleaned = value.strip()
    if len(cleaned) > limit:
        _raise(code, f"{label}은(는) {limit}자 안이어야 해요")
    return cleaned


class _GuidanceStore:
    """Guidance tables in the review database.

    A separate table in the review's own database, not a separate database: the
    answer is bound to one review bundle and lives beside the choices made in
    that same bundle.

    Answers are keyed by `(binding, source_ref)`, never by row id. So a source
    that is replaced by a newer bundle keeps its old answer and the old
    binding's audit trail: the new bundle writes its own row rather than
    overwriting one, and neither is lost.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        try:
            with closing(self._connect()) as conn:
                # `executescript`, because a single `execute` takes one statement
                # and this schema is several.
                conn.executescript(_SCHEMA)
        except Exception:
            raise GuidanceError(CODE_GUIDANCE_UNAVAILABLE, "답변 저장소를 열 수 없어요") from None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def load(self, binding: str, ref: str) -> dict:
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT source_ref_sha256, revision, note, item, description, updated_at"
                " FROM review_source_guidance WHERE binding=? AND source_ref=?",
                (binding, ref)).fetchone()
        if row is None:
            return {"exists": False, "revision": 0, "note": "", "item": "",
                    "description": "", "source_ref_sha256": "", "updated_at": ""}
        return {"exists": True, "source_ref_sha256": row[0], "revision": int(row[1]),
                "note": row[2], "item": row[3], "description": row[4],
                "updated_at": row[5]}

    def save(self, *, binding: str, ref: str, digest: str, revision: int,
             note: str, item: str, description: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO review_source_guidance(binding, source_ref,"
                    " source_ref_sha256, revision, note, item, description, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(binding, source_ref) DO UPDATE SET"
                    " source_ref_sha256=excluded.source_ref_sha256,"
                    " revision=excluded.revision, note=excluded.note,"
                    " item=excluded.item, description=excluded.description,"
                    " updated_at=excluded.updated_at",
                    (binding, ref, digest, revision, note, item, description,
                     _utc_now()))

    def save_with_request(self, *, binding: str, ref: str, digest: str, revision: int,
                           note: str, item: str, description: str,
                           request_id: str, payload_digest: str,
                           response: dict) -> None:
        """Write the answer and remember the request in one transaction.

        These two must land together. Stored separately they are two autocommit
        writes, and a failure between them leaves an answer saved against a
        request id that was never recorded — so the retry of that same request
        sees a bumped revision and is refused as a conflict, for a save the
        owner believes never happened. One `BEGIN IMMEDIATE` makes the pair
        either both there or neither.

        The service owns the review write lock before calling this method.
        `BEGIN IMMEDIATE` makes the answer and request commit atomic.
        """
        with self._lock, closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO review_source_guidance(binding, source_ref,"
                    " source_ref_sha256, revision, note, item, description,"
                    " updated_at) VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(binding, source_ref) DO UPDATE SET"
                    " source_ref_sha256=excluded.source_ref_sha256,"
                    " revision=excluded.revision, note=excluded.note,"
                    " item=excluded.item, description=excluded.description,"
                    " updated_at=excluded.updated_at",
                    (binding, ref, digest, revision, note, item, description,
                     _utc_now()))
                conn.execute(
                    "INSERT OR REPLACE INTO review_guidance_requests(binding,"
                    " source_ref, request_id, response_json, payload_sha256,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (binding, ref, request_id,
                     json.dumps(response, ensure_ascii=False), payload_digest,
                     _utc_now()))
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def replay(self, binding: str, ref: str, request_id: str, payload_digest: str):
        """A previous answer for this request id, if it was the same request.

        The id is not enough to be sure. Replaying a *different* body under an
        id already used would hand back an answer to a question that was never
        asked, so the stored digest is compared and a mismatch is refused.
        """
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT response_json, payload_sha256 FROM review_guidance_requests"
                " WHERE binding=? AND source_ref=? AND request_id=?",
                (binding, ref, request_id)).fetchone()
        if row is None:
            return None
        if row[1] and row[1] != payload_digest:
            raise GuidanceError(
                CODE_REQUEST_ID_REUSED,
                "같은 요청 ID로 다른 내용을 보냈어요")
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def remember_request(self, binding: str, ref: str, request_id: str,
                         response: dict, payload_digest: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO review_guidance_requests(binding,"
                    " source_ref, request_id, response_json, payload_sha256,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (binding, ref, request_id,
                     json.dumps(response, ensure_ascii=False), payload_digest,
                     _utc_now()))

    def put_preview(self, row: dict) -> None:
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO review_guidance_previews(preview_id,"
                    " binding, source_ref, candidate_key, rule_id, apply_existing,"
                    " apply_future, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (row["preview_id"], row["binding"], row["source_ref"],
                     row["candidate_key"], row["rule_id"], int(row["apply_existing"]),
                     int(row["apply_future"]), _utc_now()))

    def preview(self, preview_id: str):
        with self._lock, closing(self._connect()) as conn:
            return conn.execute(
                "SELECT preview_id, binding, source_ref, candidate_key, rule_id,"
                " apply_existing, apply_future FROM review_guidance_previews"
                " WHERE preview_id=?", (preview_id,)).fetchone()

    def review_result(self, binding: str, ref: str, revision: int):
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT result_json FROM review_guidance_results"
                " WHERE binding=? AND source_ref=? AND answer_revision=?",
                (binding, ref, revision)).fetchone()
        return json.loads(row[0]) if row else None

    def put_result(self, binding: str, ref: str, revision: int, result: dict):
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO review_guidance_results VALUES(?,?,?,?)"
                " ON CONFLICT(binding,source_ref,answer_revision) DO UPDATE SET"
                " result_json=excluded.result_json",
                (binding, ref, revision, json.dumps(result, ensure_ascii=False)))

    def previews_for(self, binding: str, ref: str):
        with self._lock, closing(self._connect()) as conn:
            return conn.execute(
                "SELECT preview_id, candidate_key, rule_id, apply_existing, apply_future"
                " FROM review_guidance_previews WHERE binding=? AND source_ref=?"
                " ORDER BY created_at DESC, preview_id DESC",
                (binding, ref)).fetchall()


class GuidanceService:
    """Owner guidance on one reviewed source row.

    Answer saves preserve the source, choices and ledger rows. Explicit rule
    application goes through the existing preview/apply lifecycle. Answer
    writes own the review service's write lock until the atomic commit.
    """

    def __init__(self, review_service, ledger_store):
        self._review = review_service
        self._store = ledger_store
        try:
            self._guidance = _GuidanceStore(review_service.store.path)
        except GuidanceError:
            raise
        except Exception:
            raise GuidanceError(CODE_GUIDANCE_UNAVAILABLE, "답변 저장소를 열 수 없어요") from None

    # ------------------------------------------------------------- identity

    def _require_binding(self, presented) -> str:
        """A stale bundle may not be written to, and neither may a stale ref."""
        binding = presented if isinstance(presented, str) else ""
        if not binding:
            _raise(CODE_INVALID_VALUE, "바인딩이 필요해요")
        try:
            owned = self._review.require_binding(binding)
        except Exception as exc:
            raise GuidanceError(CODE_BINDING_STALE, str(exc)) from None
        try:
            live = self._review.require_current_binding()
        except Exception as exc:
            raise GuidanceError(CODE_BINDING_STALE, str(exc)) from None
        if owned != binding or live != binding:
            _raise(CODE_BINDING_STALE, "검토 묶음이 바뀌었어요. 새로고침해 주세요")
        return binding

    def _row(self, ref: str):
        """The reviewed source row this ref names, or nothing."""
        model = self._review.model()
        for row in model.get("rows") or []:
            if row.get("ref") == ref:
                return row
        return None

    def _require_row(self, ref: str) -> dict:
        """A ref the live model does not name is refused, never answered.

        This is the whole boundary of the service: if the source is not in the
        bundle that was verified, there is nothing to attach an answer to.
        """
        row = self._row(ref)
        if row is None:
            _raise(CODE_REF_NOT_FOUND, "없는 원천이에요")
        return row

    def _require_expense(self, row: dict) -> None:
        """Only a card expense can produce a rule. A deposit has no candidate."""
        source = row.get("source") or {}
        kind = source.get("block_kind") or _BLOCK_EXPENSE
        if kind != _BLOCK_EXPENSE:
            _raise(CODE_REF_NOT_EXPENSE, "입금 건으로는 규칙을 만들 수 없어요")

    def _candidate(self, row: dict, key: str) -> dict:
        for candidate in row.get("candidates") or []:
            if candidate.get("key") == key:
                return candidate
        _raise(CODE_CANDIDATE_NOT_FOUND, "선택한 후보를 찾을 수 없어요")

    # --------------------------------------------------------------- reads

    def get(self, ref: str, binding: str) -> dict:
        """The stored answer for one source, and the previews it produced.

        Read-only, and it does not require the binding to still be live: a
        bundle that has been replaced can still be read, it just cannot be
        written to. An unknown ref is refused rather than answered, so a typo
        cannot look like a source that simply has no answer yet.
        """
        binding = _text(binding, 200, "바인딩", CODE_INVALID_VALUE)
        ref = _text(ref, 200, "원천 참조", CODE_INVALID_VALUE)
        try:
            owned = self._review.require_binding(binding)
        except Exception as exc:
            raise GuidanceError(CODE_BINDING_STALE, str(exc)) from None
        row = self._require_row(ref)
        stored = self._guidance.load(owned, ref)
        previews = [{
            "preview_id": p[0], "candidate_key": p[1], "rule_id": p[2],
            "apply_existing": bool(p[3]), "apply_future": bool(p[4]),
        } for p in self._guidance.previews_for(owned, ref)]
        return {
            "binding": owned,
            "ref": ref,
            "source_ref_sha256": stored["source_ref_sha256"],
            "exists": stored["exists"],
            "revision": stored["revision"],
            "note": stored["note"],
            "item": stored["item"],
            "description": stored["description"],
            "updated_at": stored["updated_at"],
            "review_result": self._guidance.review_result(owned, ref, stored["revision"]),
            "block_kind": ((row or {}).get("source") or {}).get("block_kind") or _BLOCK_EXPENSE,
            "can_make_rule": bool(row) and (
                ((row.get("source") or {}).get("block_kind")
                 or _BLOCK_EXPENSE) == _BLOCK_EXPENSE),
            "previews": previews,
            "deterministic": True,
            "model_generated": False,
        }

    def record_local_review(self, *, ref: str, binding: str,
                            expected_revision: int, summary: str, evidence: list) -> dict:
        """Record an operator's verified response, never a financial decision.

        This has no public write route. A local operator must bind the response
        to the answer revision actually read; editing the answer hides the old
        response while its audit record remains stored.
        """
        summary = _text(summary, NOTE_MAX, "검토 결과", CODE_TEXT_TOO_LONG)
        if not summary or not isinstance(evidence, list) or not evidence:
            _raise(CODE_INVALID_VALUE, "검토 결과와 근거가 필요해요")
        if type(expected_revision) is not int or expected_revision < 1:
            _raise(CODE_INVALID_VALUE, "저장된 요청 버전이 필요해요")
        with self._review.decisions_write_lock():
            self._require_binding(binding)
            self._require_row(ref)
            answer = self._guidance.load(binding, ref)
            if answer["revision"] != expected_revision:
                _raise(CODE_REVISION_CONFLICT, "검토 중 요청이 바뀌었어요")
            result = {"status": "needs_verification", "summary": summary,
                      "checked_at": _utc_now(), "answer_revision": expected_revision,
                      "processor": "manual_local_review", "evidence": evidence,
                      "classification_applied": False}
            self._guidance.put_result(binding, ref, expected_revision, result)
            return result

    # --------------------------------------------------------------- writes

    def save(self, ref: str, binding: str, note: str, item: str, description: str,
             expected_revision, request_id: str) -> dict:
        """Store the owner's answer for this source. Nothing else is written.

        `expected_revision` is the optimistic lock: it is the revision the owner
        was looking at, and a save against a newer one is refused rather than
        merged, because these are three fields of free text and there is no way
        to merge two answers to the same question.
        """
        binding = self._require_binding(binding)
        ref = _text(ref, 200, "원천 참조", CODE_INVALID_VALUE)
        note = _text(note, NOTE_MAX, "답변", CODE_TEXT_TOO_LONG)
        item = _text(item, ITEM_MAX, "항목", CODE_TEXT_TOO_LONG)
        description = _text(description, DESCRIPTION_MAX, "내용", CODE_TEXT_TOO_LONG)
        request_id = _text(request_id, _REQUEST_ID_MAX, "요청 ID", CODE_INVALID_VALUE)
        if expected_revision is None:
            _raise(CODE_INVALID_VALUE, "기대 버전이 필요해요")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            _raise(CODE_INVALID_VALUE, "기대 버전 형식이 달라요")
        if expected_revision < 0:
            _raise(CODE_INVALID_VALUE, "기대 버전 형식이 달라요")
        if not request_id:
            _raise(CODE_INVALID_VALUE, "요청 ID가 필요해요")
        # An answer is a note, a label, a description, or any combination. A note
        # is not required: correcting the item and the description is an answer
        # on its own, and refusing it would force prose nobody needs to write.
        if not (note or item or description):
            _raise(CODE_NOTHING_TO_SAVE, "답변을 하나 이상 입력해 주세요")

        payload_digest = sha256_text(json.dumps(
            [binding, ref, note, item, description, expected_revision],
            ensure_ascii=False, separators=(",", ":")))
        row = self._require_row(ref)

        with self._review.decisions_write_lock():
            replay = self._guidance.replay(binding, ref, request_id, payload_digest)
            if replay is not None:
                return replay
            # Re-confirmed under the lock, and the source re-checked: the bundle
            # or the source can both have moved between the check above and the
            # write below.
            self._require_binding(binding)
            row = self._require_row(ref)
            current = self._guidance.load(binding, ref)
            if int(expected_revision) != current["revision"]:
                _raise(CODE_REVISION_CONFLICT,
                       "다른 곳에서 먼저 고쳤어요. 새로고침해 주세요")
            revision = current["revision"] + 1
            digest = sha256_text(ref)
            result = {
                "binding": binding, "ref": ref, "source_ref_sha256": digest,
                "revision": revision, "note": note, "item": item,
                "description": description, "updated_at": _utc_now(),
            }
            self._guidance.save_with_request(
                binding=binding, ref=ref, digest=digest, revision=revision,
                note=note, item=item, description=description,
                request_id=request_id, payload_digest=payload_digest,
                response=result)
        return result

    # --------------------------------------------------------------- rules

    def _build_draft(self, *, note: str, item: str, description: str,
                     candidate: dict, case_id: str, ref_digest: str,
                     card_kind: str = "") -> dict:
        """The rule draft this source supports, and nothing more.

        Conditions come from the candidate the owner pointed at, read from the
        bound master. `transaction_direction` is deliberately absent: the review
        model does not prove purchase, refund or cancellation, and inferring it
        from the sign of an amount is exactly the kind of guess a rule must not
        be built on. `card_kind` is included only when the store actually
        verified one, otherwise the merchant condition stands alone.

        Effects are only the fields the owner filled in. Nothing is added, and
        in particular no travel placement: this source says nothing about a
        trip, and inferring one would move real money between trips.
        """
        merchant = normalize_merchant(candidate.get("merchant"))
        if not merchant:
            _raise(CODE_CANDIDATE_NOT_FOUND, "가맹점이 없는 후보예요")
        conditions = {"merchant_normalized": merchant}
        if card_kind:
            conditions["card_kind"] = card_kind
        effects = {}
        if item:
            effects["item"] = item
        if description:
            effects["description_template"] = description
        if not effects:
            _raise(CODE_INVALID_VALUE, "항목이나 내용을 입력해 주세요")
        draft = {
            "conditions": conditions,
            "effects": effects,
            # A reference, not a copy. The owner's note stays on the source row.
            "note": f"review-source:{ref_digest}",
            "learning_case_id": case_id,
        }
        try:
            # Validated here so a bad draft is refused with this service's own
            # error type, but `create_rule_draft` gets the *raw* draft: its own
            # `normalize_draft` adds fields such as `evidence_case_ids`, and
            # feeding that output back in would be rejected as an unknown key.
            rule = normalize_draft(draft, learning_case_id=case_id,
                                   rule_id=f"rule-{case_id}")
        except RuleError as exc:
            raise GuidanceError(CODE_INVALID_VALUE, str(exc)) from None
        return draft, rule

    def _verified_card_kind(self, candidate_key: str) -> str:
        """The card kind read from the bound master, or "" when there is none.

        The card kind is not in the review model, so it is read straight from the
        bound master's `카드종류` column, matched on the exact transaction key.
        The key is never split or guessed at: an approximate match would attach
        another transaction's card kind to this one.

        No column, or no row, means no card kind condition. That makes the rule
        *wider* — every card of any kind with that merchant matches — never
        narrower, and `condition_basis.card_kind_present` says so out loud so the
        UI does not present a wide rule as a precise one.
        """
        try:
            master_text = self._review.bound_inputs().master_text
        except Exception:
            return ""
        if not master_text:
            return ""
        try:
            reader = csv.DictReader(io.StringIO(master_text))
            for record in reader:
                if (record.get("거래키") or "").strip() != candidate_key:
                    continue
                return (record.get("카드종류") or "").strip()
        except Exception:
            return ""
        return ""

    def _case_id(self, binding: str, ref: str, candidate_key: str) -> str:
        """A case id bound to the binding, the ref and the chosen candidate.

        Keyed by the ref alone, a second bundle or a re-picked candidate would
        collide with the proof already registered and be refused as a mismatch.
        Keyed by all three, each is its own case, and re-registering the *same*
        three stays idempotent.
        """
        return "review-" + sha256_text(json.dumps(
            [binding, ref, candidate_key], ensure_ascii=False,
            separators=(",", ":")))[:32]

    def rule_preview(self, ref: str, binding: str, note: str, item: str,
                     description: str, condition_candidate_key: str,
                     apply_existing, apply_future, request_id: str) -> dict:
        """Draft and preview a rule learned from this source.

        Existing and future impact come back as the server's own measured plan,
        never as a count assembled on the client. A source row with no board row
        behind it can still produce a future rule, which is the whole point of
        asking here rather than on the board.
        """
        binding = self._require_binding(binding)
        ref = _text(ref, 200, "원천 참조", CODE_INVALID_VALUE)
        note = _text(note, NOTE_MAX, "답변", CODE_TEXT_TOO_LONG)
        item = _text(item, ITEM_MAX, "항목", CODE_TEXT_TOO_LONG)
        description = _text(description, DESCRIPTION_MAX, "내용", CODE_TEXT_TOO_LONG)
        key = _text(condition_candidate_key, 200, "조건 후보", CODE_INVALID_VALUE)
        request_id = _text(request_id, _REQUEST_ID_MAX, "요청 ID", CODE_INVALID_VALUE)
        if not key:
            _raise(CODE_CANDIDATE_REQUIRED, "조건을 걸 후보를 고르세요")
        if not isinstance(apply_existing, bool) or not isinstance(apply_future, bool):
            _raise(CODE_INVALID_VALUE, "적용 범위 값이 달라요")
        if not request_id:
            _raise(CODE_INVALID_VALUE, "요청 ID가 필요해요")

        self._require_expense(self._require_row(ref))
        candidate = self._candidate(self._require_row(ref), key)

        ref_digest = sha256_text(ref)
        card_kind = self._verified_card_kind(key)
        case_id = self._case_id(binding, ref, key)
        with self._review.decisions_write_lock():
            # Verified again inside the lock: the bundle this case is bound to
            # could have been replaced between the check and the registration.
            self._require_binding(binding)
            self._require_expense(self._require_row(ref))
            self._store.register_review_rule_case(
                case_id=case_id, binding=binding, source_ref=ref,
                candidate_key=key,
                # Derived facts only: a hash, a merchant, a card kind. No person,
                # no reservation number, no note.
                context={"source_ref_sha256": ref_digest,
                         "merchant_normalized": normalize_merchant(candidate.get("merchant")),
                         "card_kind": card_kind})

        draft, _rule = self._build_draft(
            note=note, item=item, description=description, candidate=candidate,
            case_id=case_id, ref_digest=ref_digest, card_kind=card_kind)

        try:
            created = self._store.create_rule_draft(
                draft=draft, client_request_id=request_id)
        except SaveError as exc:
            raise GuidanceError(exc.code, str(exc)) from None

        rule_id = created.get("rule_id") or f"rule-{request_id}"
        try:
            plan = self._store.preview_rule(
                rule_id=rule_id, apply_existing=apply_existing,
                apply_future=apply_future)
        except SaveError as exc:
            raise GuidanceError(exc.code, str(exc)) from None

        preview_id = str(plan.get("preview_id") or "")
        self._guidance.put_preview({
            "preview_id": preview_id, "binding": binding, "source_ref": ref,
            "candidate_key": key, "rule_id": rule_id,
            "apply_existing": apply_existing, "apply_future": apply_future})
        return {
            "preview_id": preview_id,
            "rule_id": rule_id,
            "binding": binding,
            "ref": ref,
            "source_ref_sha256": ref_digest,
            "case_id": case_id,
            "candidate_key": key,
            "draft": {
                "conditions": draft.get("conditions"),
                "effects": draft.get("effects"),
                "note": draft.get("note"),
            },
            "condition_basis": {
                "merchant_normalized": normalize_merchant(candidate.get("merchant")),
                "card_kind": draft.get("conditions", {}).get("card_kind", ""),
                # False means the rule matches any card kind for this merchant.
                # Wider, never narrower — and stated, not implied.
                "card_kind_present": bool(draft.get("conditions", {}).get("card_kind")),
                "transaction_direction": None,
                "transaction_direction_reason": "거래 방향을 증명할 근거가 없어 넣지 않았어요",
            },
            "counts": plan.get("counts", {}),
            "candidates": plan.get("candidates", []),
            "excluded": plan.get("excluded", []),
            "amounts": plan.get("amounts", {}),
            "unavailable_conditions": plan.get("unavailable_conditions", []),
            "conflict_policy": plan.get("conflict_policy", {}),
            "future": plan.get("future", {}),
            "apply_existing": bool(apply_existing),
            "apply_future": bool(apply_future),
            "source_case": self._store.review_rule_case(case_id),
            "deterministic": True,
            "model_generated": False,
        }

    def verify_preview(self, ref: str, binding: str, preview_id: str) -> dict:
        """Confirm a preview belongs to this source under this binding.

        Without this, any preview id in hand could be applied. With it, a
        preview is applied only for the source it was measured against.
        """
        binding = self._require_binding(binding)
        ref = _text(ref, 200, "원천 참조", CODE_INVALID_VALUE)
        preview_id = _text(preview_id, 200, "미리보기 ID", CODE_INVALID_VALUE)
        found = self._guidance.preview(preview_id)
        if found is None:
            _raise(CODE_PREVIEW_NOT_FOUND, "없는 미리보기예요")
        if found[1] != binding or found[2] != ref:
            _raise(CODE_PREVIEW_NOT_OWNED, "이 원천에서 만든 미리보기가 아니에요")
        return {"preview_id": preview_id, "binding": binding, "source_ref": ref,
                "candidate_key": found[3], "rule_id": found[4]}

    def apply_rule(self, preview_id: str, apply_existing: bool, apply_future: bool,
                   request_id: str, ref: str = "", binding: str = "") -> dict:
        """Apply a previewed rule, after checking it belongs to this source.

        `ref` and `binding` are optional in the signature only so the call site
        can read naturally; omitting them is refused, because an apply that
        cannot be tied to the source it came from is not something this service
        will do on a preview id alone.
        """
        preview_id = _text(preview_id, 200, "미리보기 ID", CODE_INVALID_VALUE)
        request_id = _text(request_id, _REQUEST_ID_MAX, "요청 ID", CODE_INVALID_VALUE)
        if not isinstance(apply_existing, bool) or not isinstance(apply_future, bool):
            _raise(CODE_INVALID_VALUE, "적용 범위 값이 달라요")
        if not ref or not binding:
            _raise(CODE_PREVIEW_NOT_OWNED, "원천과 바인딩을 함께 보내야 해요")
        owned = self.verify_preview(ref, binding, preview_id)
        try:
            applied = self._store.apply_rule(
                preview_id=preview_id, apply_existing=apply_existing,
                apply_future=apply_future, client_request_id=request_id)
        except SaveError as exc:
            raise GuidanceError(exc.code, str(exc)) from None
        result = dict(applied) if isinstance(applied, dict) else {"applied": applied}
        result.update({
            "preview_id": preview_id,
            "ref": ref,
            "binding": owned["binding"],
            "candidate_key": owned["candidate_key"],
            "rule_id": owned["rule_id"],
            "apply_existing": bool(apply_existing),
            "apply_future": bool(apply_future),
        })
        return result
