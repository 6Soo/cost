"""선택한 검토 결과를 실제 장부에 반영하기 위한 계획과 반영.

이 모듈은 두 가지 일을 한다. 하나는 화면에 보여 줄 계획을 세우는 것이고, 다른
하나는 소유자가 그 계획을 명시적으로 실행했을 때 그것을 쓰는 것이다.

두 가지가 같은 함수에 들어 있지 않은 것이 중요합니다. 계획을 세우는 일은 읽기만
합니다. 반영은 소유자가 볼 버튼을 눌러야 비로소 일어납니다. 자동으로 승인되는
선택도, 자동으로 실행되는 계획도 없습니다. 선택하지 않은 자료, 근거가 부족한
자료, 거절한 자료, 후보가 없는 자료는 계획부터 들어가지 않고 계속 보류됩니다.

입력은 하나뿐입니다. 현재 활성 묶음의 세 해시와, 그 묶음에 대해 **저장된** 선택
버전과 저장된 선택, 그리고 카드 원장입니다. 화면에 쓰지 않은 값은 이관의 근거가
되지 않습니다. 화면의 값은 저장이 끝난 뒤에만 비로소 저장된 값이기 때문입니다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import pathlib

from . import review_context
from . import review_refresh
from .real_review import CODE_REVISION_CONFLICT, CODE_BINDING_CONFLICT
from .real_review import RealReviewError

__all__ = [
    "CODE_PLAN_INPUT_INVALID",
    "CODE_PLAN_NO_DECISIONS_DB",
    "CODE_PLAN_REVISION_CONFLICT",
    "CODE_PLAN_BINDING_CONFLICT",
    "CODE_APPLY_NOTHING_TO_DO",
    "CODE_APPLY_ONLY_CONFLICTS",
    "CODE_APPLY_REQUEST_CONFLICT",
    "ApplyPlanError",
    "build_apply_plan",
    "apply_apply_plan",
]

#: The plan could not be built from the stored inputs at all.
CODE_PLAN_INPUT_INVALID = "REVIEW_APPLY_INPUT_INVALID"
#: There is no decision database, so there is no stored choice to plan from.
CODE_PLAN_NO_DECISIONS_DB = "REVIEW_APPLY_NO_DECISIONS"
#: The stored choice version is not the one the plan was made against.
CODE_PLAN_REVISION_CONFLICT = "REVIEW_APPLY_REVISION_CONFLICT"
#: The bundle is not the one the plan was made against.
CODE_PLAN_BINDING_CONFLICT = CODE_BINDING_CONFLICT
#: There was nothing to do. Not an error, but not a silent success either.
CODE_APPLY_NOTHING_TO_DO = "REVIEW_APPLY_NOTHING_TO_DO"
#: Every transaction the request named is a conflict, so there is nothing it may
#: write. Its own code, because "nothing to do" would hide a changed source.
CODE_APPLY_ONLY_CONFLICTS = "REVIEW_APPLY_ONLY_CONFLICTS"
#: The same request id was used with different inputs. Two different decisions
#: cannot both be what that request meant.
CODE_APPLY_REQUEST_CONFLICT = "APPLY_REQUEST_INPUT_CONFLICT"

#: The fields a request may send to name one transaction.
#:
#: The first is what the plan route publishes, and therefore what a page holds and
#: sends back. The second is the same two fields without the label, for a caller
#: that names transactions directly. Both are accepted, and nothing else is: these
#: are exact key sets, not a prefix match, because an extra field would be a
#: second channel for a value the plan never showed.
#:
#: Neither shape can widen what is written. The transaction and its facts are
#: taken from the plan rebuilt here from stored inputs, so a request can only name
#: transactions that plan already offers — it cannot add one, alter one, or invent
#: a transaction key.
_PRESENTED_KEYS = (frozenset({"ref", "source_event_key", "fact_digest"}),
                   frozenset({"source_event_key", "fact_digest"}))


class ApplyPlanError(Exception):
    """A refusal, in a fixed code. The owner is told the code, never a guess."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- inputs


def _master_rows(master_text: str) -> dict:
    """The card master, read by the review core's own strict reader.

    Not a second parser. Two readers of the same seventeen columns could disagree
    about what a row says, and the disagreement would show up as a source fact
    that changed when nothing changed.
    """
    try:
        return review_context._parse_master(master_text)
    except Exception:
        raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                             "카드 원장을 읽지 못했어요") from None


def _stored_inputs(service):
    """The bundle and the stored choices, and nothing the screen is holding.

    The three inputs are the ones the service itself verified. They come from a
    single digest-checked read through `bound_inputs`, not from a second read of
    the same paths: two reads are two moments, and a source that changes between
    them produces a plan built from facts the running service never saw. If the
    digest no longer matches, that read raises rather than returning something to
    plan from.

    An unsaved choice on the screen is not an input, which is why nothing here
    touches the browser's state.
    """
    manifest = service.manifest
    for key in ("snapshot_path", "review_path", "master_path"):
        if not str(manifest.get(key, "")):
            raise ApplyPlanError(CODE_PLAN_INPUT_INVALID, "묶음이 완전하지 않아요")
    try:
        # One verified set, used for the model, the master facts and the notes.
        inputs = service.bound_inputs()
        state = service.state()
        model = service.model()
    except RealReviewError:
        raise
    saved = state.get("choices") or {}
    revision = state.get("revision")
    if type(revision) is not int or revision < 0:
        raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                             "선택 버전이 올바르지 않아요")
    return {
        "model": model,
        "state": state,
        "binding": inputs.binding,
        "choices_revision": revision,
        "saved_choices": saved,
        "review_text": inputs.review_text,
        "master_text": inputs.master_text,
        "snapshot_sha256": inputs.snapshot_sha256,
    }


# ------------------------------------------------------------------ the plan


def build_apply_plan(service, store=None) -> dict:
    """What an apply would do, read from the stored bundle and stored choices.

    Nothing is written. The counts are what the owner is shown before deciding,
    and the same function is called again by `apply_apply_plan`, so the plan the
    owner saw and the plan that runs are built by the same code from the same
    inputs.
    """
    if service is None:
        raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                             "검토 묶음이 연결되어 있지 않아요")
    inputs = _stored_inputs(service)
    # The core's own export, which is where `build_review_export` and
    # `build_reviewed_import_plan` live. Called with the saved choices and no
    # submitted ones, so it plans from what was stored. Re-deciding eligibility
    # here would be a second rule that could disagree with the one the screen
    # used, and eligibility is the thing that decides what reaches the ledger.
    try:
        exported = service.export(presented_binding=inputs["binding"])
        plan_json = json.loads(exported["plan_json"])
    except RealReviewError as exc:
        raise ApplyPlanError(exc.code or CODE_PLAN_INPUT_INVALID,
                             "선택 내용을 계획으로 만들지 못했어요") from None
    except Exception:
        raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                             "선택 내용을 계획으로 만들지 못했어요") from None

    reviewed = plan_json["reviewed_plan"]
    master = _master_rows(inputs["master_text"])
    notes = _notes_by_ref(inputs["review_text"])

    # Two different units live in this plan and are never added together.
    #
    # `approved` is a list of review *references*: one per row a person looked at.
    # `transactions` is a list of card *transactions*: one per distinct 거래키, and
    # fewer than the references whenever two rows named the same transaction. Every
    # count below says which one it is counting.
    approved, held, conflicts, already = [], [], [], []
    # Two review refs can name the same card transaction. That is one expense, not
    # two, so the second one is recorded as held with the ref that won it rather
    # than being applied a second time.
    claimed_by = {}
    for row in reviewed["eligible"]:
        key = row["chosen_candidate_key"]
        record = master.get(key)
        if record is None:
            held.append({"ref": row["source_ref_snapshot_only"],
                         "chosen_candidate_key": key,
                         "code": "APPLY_SOURCE_KEY_UNRESOLVED"})
            continue
        if key in claimed_by:
            held.append({"ref": row["source_ref_snapshot_only"],
                         "chosen_candidate_key": key,
                         "code": "APPLY_DUPLICATE_TRANSACTION",
                         "first_ref": claimed_by[key]})
            continue
        claimed_by[key] = row["source_ref_snapshot_only"]
        approved.append({
            "ref": row["source_ref_snapshot_only"],
            "chosen_candidate_key": key,
            "facts": {name: record[name] for name in review_context.MASTER_HEADERS},
            "fact_digest": _digest({name: record[name]
                                    for name in review_context.MASTER_HEADERS}),
            "workbook_ref": row["source_ref_snapshot_only"],
            "review_note": notes.get(row["source_ref_snapshot_only"], ""),
        })
    for row in reviewed["refused"]:
        held.append({"ref": row["source_ref_snapshot_only"],
                     "code": row.get("reason_code", "APPLY_HELD")})

    already, conflicts = _applied_and_conflicts(store, approved)

    # Only these are ever written. A transaction the ledger already holds is not
    # written again, and a transaction whose facts changed is not overwritten;
    # both are reported and left for a person. Leaving them in the write list is
    # how a count says "applicable" and means something else.
    writeable = [dict(entry, source_event_key=entry["chosen_candidate_key"])
                 for entry in approved
                 if entry["chosen_candidate_key"] not in
                 {item["source_event_key"] for item in already}
                 and entry["chosen_candidate_key"] not in
                 {item["source_event_key"] for item in conflicts}]

    plan = {
        "binding": inputs["binding"],
        "choices_revision": inputs["choices_revision"],
        "snapshot_sha256": inputs["snapshot_sha256"],
        "transactions": writeable,
        "approved_refs": approved,
        "already_applied": already,
        "conflicts": conflicts,
        "held_refs": held,
        "counts": {
            # Transactions, not references: what an apply would write.
            "applicable_transactions": len(writeable),
            "already_applied_transactions": len(already),
            "conflict_transactions": len(conflicts),
            # References: what stays undecided or refused on screen.
            "held_refs": len(held),
            "approved_refs": len(approved),
        },
        "units": {
            "applicable_transactions": "transactions",
            "already_applied_transactions": "transactions",
            "conflict_transactions": "transactions",
            "held_refs": "refs",
            "approved_refs": "refs",
        },
        # The digest of everything the plan was built from. The apply checks it,
        # so a plan cannot be run against inputs it was not built from.
        # The digest binds the bundle, the choice version and every approved
        # transaction's facts.
        #
        # Approved, not writeable, and that distinction matters: a plan stops
        # offering a transaction only because the ledger now holds it, so a digest
        # over the writeable set would change as a result of our own apply and a
        # retry would be refused for having been applied. A digest over what was
        # approved is stable across our own writes and still changes when the
        # source, the bundle or the decisions change — which is exactly when a
        # plan the owner saw must not be run.
        "plan_digest": _digest({
            "binding": inputs["binding"],
            "choices_revision": inputs["choices_revision"],
            "snapshot_sha256": inputs["snapshot_sha256"],
            "approved": [
                {"key": item["chosen_candidate_key"], "facts": item["facts"]}
                for item in approved],
        }),
    }
    return plan


def _applied_and_conflicts(store, approved):
    """Split the approved transactions by what the ledger already holds.

    A key already present with the same facts is already applied: writing it again
    would be a second expense. A key present with different facts is a conflict,
    because overwriting would rewrite an approved fact while a new key would make
    one transaction into two. Neither is written.

    Counted once per transaction key, not once per review row, because the ledger
    holds one row per transaction however many rows pointed at it.

    Both lists carry the full entry, not just a report, so that a request naming
    an already-applied transaction can be handed to the store and counted by it.
    """
    if store is None:
        return [], []
    already, conflicts = [], []
    seen = set()
    for entry in approved:
        key = entry["chosen_candidate_key"]
        if key in seen:
            continue
        seen.add(key)
        found = store.applied_source_fact(key)
        if found is None:
            continue
        if found["fact_digest"] == entry["fact_digest"]:
            already.append({
                "ref": entry["ref"], "source_event_key": key,
                "chosen_candidate_key": key, "facts": entry["facts"],
                "fact_digest": entry["fact_digest"], "row_id": found["row_id"],
                "workbook_ref": entry["workbook_ref"],
                "review_note": entry["review_note"], "already": True})
        else:
            conflicts.append({
                "ref": entry["ref"], "source_event_key": key,
                "chosen_candidate_key": key, "facts": entry["facts"],
                "fact_digest": found["fact_digest"], "row_id": found["row_id"],
                "code": "APPLY_SOURCE_FACT_CONFLICT"})
    return already, conflicts


def _notes_by_ref(review_text: str) -> dict:
    """The reviewer's own note per ref, read from the bundle's review CSV."""
    reader = csv.DictReader(io.StringIO(review_text.lstrip("\ufeff")))
    notes = {}
    for record in reader:
        ref = (record.get("source_ref_snapshot_only") or "").strip()
        if ref:
            notes[ref] = (record.get("review_note") or "").strip()
    return notes


# ----------------------------------------------------------------- the apply


#: Sentinel for "the caller named no transaction list at all".
#:
#: Only the in-process helper below may use it, and only to mean "use what the
#: plan offers". A request that arrives over HTTP without a transaction list is a
#: different thing entirely — it is a request to apply whatever happens to be
#: approved — and it is refused. The two are separated by position rather than by
#: a default value on the public function, so there is no default for a request to
#: inherit.
_UNDECLARED = object()


def apply_apply_plan(service, store, *, request_id: str, presented_binding: str,
                     presented_revision, presented_plan_digest: str,
                     presented_transactions=_UNDECLARED) -> dict:
    """Write the plan the owner was shown, once.

    The order of the checks is the whole point of this function. The bundle the
    request names, the stored choice version, and then — after the plan is rebuilt
    from those same stored inputs — every transaction the request claims, compared
    against the rebuilt plan's facts. Only then does the single transaction open,
    and inside it the bundle and the choice version are checked again.

    What gets written is the transactions the request named, never a wider set.
    A choice saved between the plan and here is not applied: the owner has not
    seen it, and a write they did not look at is not one they asked for. It
    appears in the next plan instead.

    The facts written are the rebuilt ones, not the ones in the request. The
    request only says which transactions it means; what they actually are comes
    from the digest-checked read the plan just made.
    """
    if service is None or store is None:
        raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                             "검토 묶음이 연결되어 있지 않아요")

    # The identity of this request is what it was asked to do, not what a fresh
    # plan says now. A retry after a lost response presents the original plan,
    # and once those transactions are applied that plan no longer describes the
    # state — so it is answered from the request record instead of being refused
    # for no longer being true.
    # The identity of the request, and it binds everything the request claims:
    # the bundle, the choice version, the plan digest and the transactions. A
    # digest over the plan and transactions alone would answer "same request" for
    # a request that named a different bundle or an older choice version, and
    # return a success that belonged to a different set of inputs.
    request_digest = _digest({
        "binding": presented_binding,
        "choices_revision": presented_revision,
        "plan_digest": presented_plan_digest,
        # Named rather than raw, because the sentinel is not a value: two
        # different requests must never digest to the same identity by accident.
        "transactions": ("<undeclared>"
                         if presented_transactions is _UNDECLARED
                         else presented_transactions),
    })
    replay = store.source_fact_apply(request_id) if type(request_id) is str \
        else None
    if replay is not None:
        if replay["input_digest"] == request_digest:
            # The answer is cached, but the request is not finished. An audit event
            # left waiting when the audit ledger was refusing still has to go out,
            # and a retry is the moment to send it — through the relay path every
            # other write uses, and for this request's own events only.
            store.resume_audit_relay(request_id)
            return replay["result"]
        raise ApplyPlanError(CODE_APPLY_REQUEST_CONFLICT,
                             "같은 요청 식별자로 다른 입력이에요")

    try:
        service.require_binding(presented_binding)
        service.require_current_binding()
    except RealReviewError as exc:
        raise ApplyPlanError(exc.code or CODE_PLAN_BINDING_CONFLICT,
                             "묶음이 바뀌었어요.") from None
    if type(presented_revision) is not int:
        raise ApplyPlanError(CODE_PLAN_REVISION_CONFLICT,
                             "선택 버전이 올바르지 않아요")

    # The collector's lock, held across the whole apply: re-reading the config,
    # rebuilding the plan, and the commit itself. The source collector takes the
    # same lock around its own collect and activate, so a bundle cannot be
    # replaced underneath a write. This is the collector's lock, not a second
    # one — two locks would be two answers to "is anyone else writing".
    #
    # Lock order, outermost first: this one, then the board store's own lock
    # inside `apply_reviewed_source_facts`. The collector never takes the board
    # lock and the board never took this one before, so there is no cycle.
    #
    # An OS lock on the saved-choices database, held to the commit — the same lock
    # an ordinary decision save takes, in this process or any other. A save that
    # arrives mid-apply cannot take it and is refused with
    # `REVIEW_DECISIONS_BUSY`; it does not queue, and it does not interleave.
    # Reads inside the verify are unaffected: the database is only locked against
    # writers, and the apply reads it while holding the lock itself.
    #
    # Lock order, outermost first: the collector lock, then the choices lock,
    # then the board store's own lock. Nothing takes them in another order, so
    # there is no cycle: a decision save takes only the choices lock, the collector
    # takes only its own, and the board takes only its own.
    with review_refresh.collector_lock(service.config_path), \
            service.decisions_write_lock():
        return _apply_under_lock(
            service, store, request_id=request_id,
            request_digest=request_digest, presented_binding=presented_binding,
            presented_revision=presented_revision,
            presented_plan_digest=presented_plan_digest,
            presented_transactions=presented_transactions)


def _apply_under_lock(service, store, *, request_id, request_digest,
                      presented_binding, presented_revision,
                      presented_plan_digest, presented_transactions):
    """The apply proper. Runs with the collector's lock already held."""
    plan = build_apply_plan(service, store)
    if plan["binding"] != presented_binding:
        raise ApplyPlanError(CODE_PLAN_BINDING_CONFLICT, "묶음이 바뀌었어요.")
    if plan["choices_revision"] != presented_revision:
        raise ApplyPlanError(CODE_PLAN_REVISION_CONFLICT,
                             "다른 기기에서 더 최근 결정을 저장했어요.")
    if presented_plan_digest and plan["plan_digest"] != presented_plan_digest:
        raise ApplyPlanError(CODE_PLAN_BINDING_CONFLICT,
                             "계획이 바뀐 뒤예요. 다시 확인해 주세요.")

    def verify_inside_the_write():
        """Re-check the live bundle and choice version while the write is open.

        Called by the store from inside its transaction, so a refusal here leaves
        no fact, no row, no revision and no queued audit event behind. It only
        reads: this path never writes to the decisions database.
        """
        try:
            service.require_current_binding()
            current = service.state()
        except RealReviewError as exc:
            # The store rolls back and re-raises whatever happens here, so the
            # fixed code reaches the owner with nothing written.
            raise ApplyPlanError(exc.code or CODE_PLAN_BINDING_CONFLICT,
                                 "묶음이 바뀌었어요.") from None
        if current.get("revision") != plan["choices_revision"]:
            raise ApplyPlanError(
                CODE_PLAN_REVISION_CONFLICT,
                "다른 기기에서 더 최근 결정을 저장했어요.")
        if current.get("binding") != plan["binding"]:
            raise ApplyPlanError(CODE_PLAN_BINDING_CONFLICT, "묶음이 바뀌었어요.")

    # What the request claims, checked against the plan just rebuilt from the
    # stored inputs. A transaction the ledger already holds, one whose facts
    # changed, and one the current plan no longer offers all fail here, and each
    # fails before the transaction is opened.
    claimed = []
    if presented_transactions is _UNDECLARED:
        # The convenience path, for a caller inside this process that has already
        # read the plan: it means "apply what this plan offers", nothing wider.
        claimed = list(plan["transactions"])
    else:
        if presented_transactions is None \
                or type(presented_transactions) is not list:
            raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                                 "계획 내용이 올바르지 않아요")
        by_key = {entry["chosen_candidate_key"]: entry
                  for entry in plan["transactions"]}
        applied_already = {entry["source_event_key"]: entry
                           for entry in plan["already_applied"]}
        conflicted = {entry["source_event_key"]: entry
                      for entry in plan["conflicts"]}
        for entry in presented_transactions:
            # The shape the plan route itself publishes, which is therefore the
            # shape the page holds and sends back verbatim.
            #
            # `ref` is accepted because the plan shows it and the page echoes it,
            # and nothing more: it is used to check that the entry is the one the
            # owner was shown, never to decide what is written. The transaction
            # and its facts are taken from the rebuilt plan, so a request cannot
            # add a transaction that plan does not offer, change one, or smuggle a
            # fourth field past a check. Anything else is refused.
            if type(entry) is not dict or set(entry) not in _PRESENTED_KEYS:
                raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                                     "계획 내용이 올바르지 않아요")
            key = entry["source_event_key"]
            digest = entry["fact_digest"]
            if type(key) is not str or type(digest) is not str \
                    or not isinstance(entry.get("ref", ""), str):
                raise ApplyPlanError(CODE_PLAN_INPUT_INVALID,
                                     "계획 내용이 올바르지 않아요")
            if key in conflicted:
                # The facts moved under an approved key. Refused here rather than
                # handed to the store, so the owner is told why instead of getting
                # a count with a conflict in it.
                raise ApplyPlanError(
                    CODE_APPLY_ONLY_CONFLICTS,
                    "같은 거래키의 원천 사실이 바뀌었어요.")
            found = by_key.get(key)
            if found is None:
                done = applied_already.get(key)
                if done is None or done["fact_digest"] != digest:
                    raise ApplyPlanError(CODE_PLAN_BINDING_CONFLICT,
                                         "계획이 바뀐 뒤예요. 다시 확인해 주세요.")
                # Already applied, with these same facts. Passed through on
                # purpose: the store answers a repeat with a no-change success,
                # which is what a repeat is. Refusing here would make applying
                # twice an error rather than an idempotent success.
                claimed.append(dict(done, fact_digest=digest))
                continue
            if found["fact_digest"] != digest:
                raise ApplyPlanError(CODE_PLAN_BINDING_CONFLICT,
                                     "원천 사실이 바뀌었어요. 다시 확인해 주세요.")
            claimed.append(found)

    if not claimed:
        # Reported as itself. A silent success would look the same as an apply
        # that ran, and the owner would think a decision had been carried over.
        raise ApplyPlanError(CODE_APPLY_NOTHING_TO_DO,
                             "반영할 선택이 없어요")
    # Everything claimed goes to the store, including the transactions already in
    # the ledger. That is deliberate: the store decides applied, unchanged and
    # conflict by looking at what it actually holds, so the counts an owner sees
    # after an apply are the store's own rather than a second opinion computed
    # before the write.
    items = [{
        "source_event_key": entry["chosen_candidate_key"],
        "facts": entry["facts"],
        "workbook_ref": entry.get("workbook_ref", ""),
        "review_ref": entry.get("ref", ""),
        "review_snapshot_sha256": plan["snapshot_sha256"],
        "review_note": entry.get("review_note", ""),
    } for entry in claimed]

    return store.apply_reviewed_source_facts(
        request_id=request_id,
        input_digest=request_digest,
        expected_binding=plan["binding"],
        expected_choices_revision=plan["choices_revision"],
        items=items, verify=verify_inside_the_write)
