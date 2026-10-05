"""REAL-REVIEW-001: the authenticated actual-source comparison, served in-app.

The user chose to see the actual source data and its differences against the
card candidates, and to make each decision in the public web app. The reading
side of that is not new: :func:`webapp.review_context.build_review_context` and
:func:`webapp.review_context.build_review_export` already own every rule about
what a row is, what evidence it has, which candidate keys are real and what an
approved plan looks like. This module supplies only what that pure core cannot:
where the three sealed inputs come from, that they are still byte-identical, and
where the user's own choices are kept.

What is deliberately not here
-----------------------------
* No automatic approval. Nothing in this module chooses anything.
* No ledger import. Decisions and exports are the existing core's output; the
  operational board rows are never touched.
* No raw source download. The model is the review context, not the workbook and
  not the card master.
* No demo fallback. A missing or broken configuration makes the feature
  unavailable, so the page says so instead of showing something that looks like
  real data and is not.
* No log line and no refusal code ever carries a value, a path, a key or a file
  content. Every refusal is a fixed code.

Fail-closed contract
--------------------
A configured input that is not byte-identical to its configured digest stops the
feature rather than being read. The three digests bind the decisions as well:
stored choices are looked up per binding, so a different snapshot starts from
revision 0 with no choices rather than inheriting another dataset's.
"""

from __future__ import annotations

import json
import os
import re
import contextlib
import sqlite3
import threading
import time
from pathlib import Path

from .contracts import sha256_bytes, sha256_text
from .review_context import (ReviewContextError, build_review_context,
                             build_review_export)

# ------------------------------------------------- fixed refusal vocabulary

CODE_UNAVAILABLE = "REVIEW_UNAVAILABLE"
CODE_CONFIG_INVALID = "REVIEW_CONFIG_INVALID"
CODE_SOURCE_DRIFT = "REVIEW_SOURCE_DRIFT"
CODE_REVISION_CONFLICT = "REVIEW_REVISION_CONFLICT"
CODE_BINDING_CONFLICT = "REVIEW_SOURCE_BINDING_CONFLICT"
CODE_DECISIONS_UNAVAILABLE = "REVIEW_DECISIONS_UNAVAILABLE"
#: A save arrived while an apply was committing, and was refused.
#:
#: The same shape as the collector's busy code, and for the same reason. An apply
#: reads the saved choices, writes ledger rows, and commits; a save that lands in
#: the middle of that is either lost or lands against a bundle the apply never
#: looked at. Refusing with a fixed code is honest and recoverable — the client
#: retries once the apply has finished. Letting it interleave is not.
CODE_DECISIONS_BUSY = "REVIEW_DECISIONS_BUSY"
CODE_DECISIONS_REPLACED = "REVIEW_DECISIONS_REPLACED"
CODE_INTERNAL = "REVIEW_INTERNAL_ERROR"
#: The web app's own view of a refresh it was not told about directly.
CODE_REFRESH_STATUS_UNKNOWN = "REVIEW_REFRESH_STATUS_UNKNOWN"
CODE_REFRESH_STATUS_INVALID = "REVIEW_REFRESH_STATUS_INVALID"

CONFIG_ENV = "WEBLEDGER_REVIEW_CONFIG"

#: Exactly the keys a manifest may carry. An extra key is refused rather than
#: ignored, so a typo in a locally written manifest cannot look like a setting
#: that was applied.
MANIFEST_KEYS = (
    "snapshot_path", "snapshot_sha256",
    "review_path", "review_sha256",
    "master_path", "master_sha256",
    "decisions_db_path",
)

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

#: A manifest value must be a non-empty path or digest. No length cap is applied
#: beyond the filesystem's own, because these are locally configured values and
#: the fixed codes already refuse anything unreadable.
_MAX_PATH_CHARS = 1024


class RealReviewError(Exception):
    """A refusal that carries a fixed code and nothing else."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------- the manifest


def load_manifest(config_path: str | None) -> dict | None:
    """Read and check the configured manifest, or None when there is none.

    An unset variable is not a failure: it means the feature was never
    configured, and the board simply has no review link. A set variable that does
    not name a readable manifest *is* a failure, because a silent fallback to the
    board would look like a working review of real data.
    """
    if not config_path:
        return None
    if len(config_path) > _MAX_PATH_CHARS:
        raise RealReviewError(CODE_CONFIG_INVALID)
    try:
        raw = Path(config_path).read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise RealReviewError(CODE_CONFIG_INVALID) from None
    if type(data) is not dict:
        raise RealReviewError(CODE_CONFIG_INVALID)
    if set(data) != set(MANIFEST_KEYS):
        raise RealReviewError(CODE_CONFIG_INVALID)
    for key in MANIFEST_KEYS:
        value = data[key]
        if type(value) is not str or not value or len(value) > _MAX_PATH_CHARS:
            raise RealReviewError(CODE_CONFIG_INVALID)
    for key in ("snapshot_sha256", "review_sha256", "master_sha256"):
        if _HEX64.match(data[key]) is None:
            raise RealReviewError(CODE_CONFIG_INVALID)
    return {key: data[key] for key in MANIFEST_KEYS}


def _read_exact(path: str, expected_sha: str, is_text: bool):
    """Read one configured input, or refuse because it is not what was bound.

    The digest is checked before the content is used, so a source that changed
    under a running service is never parsed and never exported. The file is only
    ever read.
    """
    try:
        raw = Path(path).read_bytes()
    except Exception:
        raise RealReviewError(CODE_SOURCE_DRIFT) from None
    if is_text:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RealReviewError(CODE_SOURCE_DRIFT) from None
        if sha256_text(text) != expected_sha:
            raise RealReviewError(CODE_SOURCE_DRIFT)
        return text
    if sha256_bytes(raw) != expected_sha:
        raise RealReviewError(CODE_SOURCE_DRIFT)
    return raw


class BoundInputs:
    """The three configured inputs, read and digest-checked as a set."""

    def __init__(self, manifest: dict):
        self.snapshot_bytes = _read_exact(manifest["snapshot_path"],
                                          manifest["snapshot_sha256"], False)
        self.review_text = _read_exact(manifest["review_path"],
                                       manifest["review_sha256"], True)
        self.master_text = _read_exact(manifest["master_path"],
                                       manifest["master_sha256"], True)

    @property
    def binding(self) -> str:
        return "|".join((self.snapshot_sha256, self.review_sha256,
                         self.master_sha256))

    snapshot_sha256 = property(lambda self: sha256_bytes(self.snapshot_bytes))
    review_sha256 = property(lambda self: sha256_text(self.review_text))
    master_sha256 = property(lambda self: sha256_text(self.master_text))

    def build_model(self) -> dict:
        try:
            return build_review_context(
                self.snapshot_bytes, self.review_text, self.master_text,
                self.snapshot_sha256, self.review_sha256, self.master_sha256)
        except ReviewContextError:
            raise RealReviewError(CODE_SOURCE_DRIFT) from None
        except Exception:
            raise RealReviewError(CODE_UNAVAILABLE) from None


# ------------------------------------------------------- the decisions store


def _choices_lock_name(db_path: str) -> Path:
    """The lock file for one decision database, beside it."""
    db_path = Path(db_path)
    return db_path.parent / (db_path.name + ".apply.lock")


#: Serializes writers of one decision database inside this process. The OS lock
#: below is what spans processes; this is what stops two threads here from both
#: deciding the machine is free.
_CHOICES_THREAD_LOCK = threading.Lock()


class _ChoicesFileLock:
    """An OS lock on the decision database's lock file, held to the commit.

    An in-process counter is not enough, and saying so is the point of this
    existing. A second `RealReviewService` in the same process, or a second
    process entirely, opens the same database with its own counter and would sail
    straight through a fence that only this object could see. The lock therefore
    lives on the filesystem beside the database, which both see.

    Reused from the source collector rather than written again: one implementation
    of the platform's file locking, so the choices lock and the collector lock
    behave identically and there is no second thing to get wrong.
    """

    def __init__(self, db_path: str):
        from .review_refresh import _FileLock

        self._lock = _FileLock.__new__(_FileLock)
        self._lock._path = _choices_lock_name(db_path)
        self._lock._handle = None
        self._thread = False

    def __enter__(self):
        if not self._lock.acquire():
            _refuse_busy()
        if not _CHOICES_THREAD_LOCK.acquire(blocking=False):
            self._lock.release()
            _refuse_busy()
        self._thread = True
        return self

    def __exit__(self, *exc):
        if self._thread:
            self._thread = False
            _CHOICES_THREAD_LOCK.release()
        self._lock.release()
        return False


def _refuse_busy() -> None:
    raise RealReviewError(CODE_DECISIONS_BUSY)


@contextlib.contextmanager
def choices_write_lock(db_path: str):
    """Exclusive right to write one decision database, held to the commit.

    Every writer of saved choices takes this, including an ordinary save. An
    apply takes it for as long as it is committing, which is what makes a save
    from another process wait rather than land in the middle of a commit.
    """
    with _ChoicesFileLock(db_path):
        yield

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS review_choice_sets ("
    " binding TEXT PRIMARY KEY,"
    " revision INTEGER NOT NULL,"
    " choices_json TEXT NOT NULL,"
    " updated_at TEXT NOT NULL)"
)


class DecisionsStore:
    """The user's own choices, in a database of their own.

    Separate file, separate table, separate table from anything the board uses.
    A review choice is not a ledger row and is never written as one, so a failure
    here cannot leave the operational board half-written.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # `closing`, not the connection's own context manager: sqlite's only
            # commits or rolls back on exit, it does not close the handle. Without
            # the close here every poll's `load` left a file open, which on Windows
            # is a handle the collector's replacement of the database cannot take.
            with contextlib.closing(self._connect()) as conn:
                with conn:
                    conn.execute(_SCHEMA)
        except Exception:
            raise RealReviewError(CODE_DECISIONS_UNAVAILABLE) from None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0, isolation_level=None)

    def write_lock(self):
        """The lock that serializes writers of this database, OS-wide."""
        return choices_write_lock(self.path)

    def load(self, binding: str) -> dict:
        """The saved choices for one binding. Revision 0 and nothing is the default."""
        with self._lock:
            try:
                with contextlib.closing(self._connect()) as conn:
                    row = conn.execute(
                        "SELECT revision, choices_json, updated_at"
                        " FROM review_choice_sets WHERE binding=?",
                        (binding,)).fetchone()
            except Exception:
                raise RealReviewError(CODE_DECISIONS_UNAVAILABLE) from None
        if row is None:
            return {"revision": 0, "choices": {}, "updated_at": ""}
        try:
            choices = json.loads(row[1])
            if type(choices) is not dict:
                raise ValueError
        except Exception:
            raise RealReviewError(CODE_DECISIONS_UNAVAILABLE) from None
        return {"revision": int(row[0]), "choices": choices,
                "updated_at": row[2]}

    def save(self, binding: str, choices: dict, expected_revision: int) -> dict:
        """Save a complete set of choices, or refuse.

        `expected_revision` is what the browser last saw. A save against a
        revision that is no longer current is refused with a conflict and changes
        nothing, which is what stops one device from silently overwriting
        another's choices.

        Re-sending choices that are already saved is accepted and returns the
        current revision. A retry of a request that already went through is not a
        conflict: it is the same choice, and refusing it would make a network
        retry look like a second decision.
        """
        payload = json.dumps(choices, ensure_ascii=False, sort_keys=True)
        # The lock is taken before the write and released after the commit, so a
        # save and an apply can never be inside the database at the same time —
        # in this process or in another one.
        with choices_write_lock(self.path), self._lock:
            try:
                conn = self._connect()
            except Exception:
                raise RealReviewError(CODE_DECISIONS_UNAVAILABLE) from None
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT revision, choices_json FROM review_choice_sets"
                    " WHERE binding=?", (binding,)).fetchone()
                current = int(row[0]) if row is not None else 0
                current_json = row[1] if row is not None else "{}"
                if current != expected_revision:
                    conn.execute("ROLLBACK")
                    raise RealReviewError(CODE_REVISION_CONFLICT)
                if current_json == payload:
                    conn.execute("ROLLBACK")
                    return {"revision": current}
                now = _utc_now()
                conn.execute(
                    "INSERT INTO review_choice_sets(binding, revision,"
                    " choices_json, updated_at) VALUES(?,?,?,?)"
                    " ON CONFLICT(binding) DO UPDATE SET revision=excluded.revision,"
                    " choices_json=excluded.choices_json,"
                    " updated_at=excluded.updated_at",
                    (binding, current + 1, payload, now))
                conn.execute("COMMIT")
                return {"revision": current + 1, "updated_at": now}
            except RealReviewError:
                raise
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise RealReviewError(CODE_DECISIONS_UNAVAILABLE) from None
            finally:
                conn.close()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---------------------------------------------------------------- the service


class RealReviewService:
    """Everything the routes need, and nothing they can reach around.

    The model is built once per set of digests and rebuilt only when the inputs
    change, because building it opens a workbook and 1,734 rows is not something
    to redo on every poll.
    """

    def __init__(self, manifest: dict, store: DecisionsStore | None = None):
        self.manifest = dict(manifest)
        # Where this service was built from. A refresh replaces the config file
        # and nothing else, so the config path is what a later re-read compares
        # and the manifest is what says whether the file actually changed.
        self.config_path = ""
        self.config_bytes = None
        decision_path = manifest['decisions_db_path']
        if store is None and os.environ.get('WEBLEDGER_UNIFIED_DB') == '1':
            board_path = os.environ.get('WEBLEDGER_DB')
            if not board_path:
                raise RealReviewError(CODE_CONFIG_INVALID)
            from .db_merge import merge_review_database
            merge_review_database(board_path, decision_path)
            decision_path = board_path
        self.store = store if store is not None else DecisionsStore(decision_path)
        self._lock = threading.Lock()
        self._model = None
        self._model_binding = ""
        self._inputs: BoundInputs | None = None

    # -- inputs and model ---------------------------------------------------
    def _bound(self) -> BoundInputs:
        """The inputs, with the digests re-checked on every call.

        This is the drift check. A source that changed under a running service
        stops the feature here, before any content is served, exported or saved.
        """
        inputs = BoundInputs(self.manifest)
        with self._lock:
            if self._inputs is not None and self._inputs.binding != inputs.binding:
                self._model = None
                self._model_binding = ""
            self._inputs = inputs
        return inputs

    def bound_inputs(self) -> "BoundInputs":
        """The three inputs, read and digest-checked, for another caller to use.

        Someone planning an apply needs the same bytes the model was built from,
        not a second read of the same paths. Two reads means two moments, and a
        source that changes between them yields a plan built from facts the
        service never saw. This hands back one verified set.
        """
        return self._bound()

    def decisions_write_lock(self):
        """The OS lock on the saved-choices database. See `choices_write_lock`."""
        return choices_write_lock(self.store.path)

    def is_available(self) -> bool:
        """Is the configured source readable and still exactly what was bound?

        Used for the board's owner redirect, so it is the cheap half: the digests,
        not the model. A source that is readable but whose rows cannot be built
        is still not something to send someone to.
        """
        try:
            self._bound()
        except RealReviewError:
            return False
        return True

    def model(self) -> dict:
        inputs = self._bound()
        with self._lock:
            if self._model is not None and self._model_binding == inputs.binding:
                return self._model
        model = inputs.build_model()
        with self._lock:
            self._model = model
            self._model_binding = inputs.binding
        return model

    def binding(self) -> str:
        return self._bound().binding

    def _review_text(self) -> str:
        return self._bound().review_text

    # -- what the screen needs ---------------------------------------------
    def state(self) -> dict:
        """The saved choices, the revision, and the counts the screen shows.

        Counts are counted from the model and the saved choices here rather than
        in the browser, so two devices showing the same revision cannot disagree
        about how many rows are decided.
        """
        model = self.model()
        binding = model["snapshotsha"] + "|" + model["reviewsha"] + "|" + \
            model["mastersha"]
        saved = self.store.load(binding)
        rows = model["rows"]
        counts = {"total": len(rows), "selected": 0, "held": 0, "rejected": 0}
        for row in rows:
            value = saved["choices"].get(row["ref"], "")
            if value == "":
                counts["held"] += 1
            elif value == "REJECT":
                counts["rejected"] += 1
            else:
                counts["selected"] += 1
        return {
            "binding": binding,
            "revision": saved["revision"],
            "updated_at": saved["updated_at"],
            "counts": counts,
            # The saved choices themselves, so a second device renders the state
            # that was actually saved rather than only the totals. The counts
            # alone would let a page agree with the server about how many rows are
            # decided while showing every one of them blank.
            "choices": dict(saved["choices"]),
        }

    def require_binding(self, presented) -> str:
        """The current binding, or a refusal because the page read another one.

        A revision on its own cannot say a page is current. The counter is per
        binding, so a page still holding revision 0 of a dataset that has since
        been replaced is also at revision 0 of the new one, and its choices would
        be written into a different set of rows. The three digests are what say
        which dataset the page actually read, so the page presents them and they
        have to be the current ones.

        The check runs before validation on purpose: a page from another dataset
        should be told that, not that its candidate key is wrong.
        """
        current = self.model_binding()
        if type(presented) is not str or presented != current:
            raise RealReviewError(CODE_BINDING_CONFLICT)
        return current

    def require_current_binding(self) -> str:
        """Refuse a write from a bundle that is no longer the live one.

        A request is handed one service and keeps it for its whole life, which is
        what makes a save and the export beside it agree on one binding. But a
        collector can activate a new bundle while such a request is in flight, and
        the old service's own check would still pass: its binding is internally
        consistent, it is just no longer the one the config names.

        So a write re-reads the config and compares. The service object is not
        replaced and the request's reads are unaffected — only the write is
        refused, because writing a previous bundle's decisions into the new one is
        exactly the thing that must not happen. The decisions store is per binding
        and this path never reaches it.
        """
        path = getattr(self, "config_path", "")
        if not path:
            return self.model_binding()
        try:
            with open(path, "rb") as handle:
                manifest = json.loads(handle.read().decode("utf-8"))
        except Exception:
            raise RealReviewError(CODE_CONFIG_INVALID) from None
        if type(manifest) is not dict:
            raise RealReviewError(CODE_CONFIG_INVALID) from None
        live = "|".join((
            str(manifest.get("snapshot_sha256", "")),
            str(manifest.get("review_sha256", "")),
            str(manifest.get("master_sha256", "")),
        ))
        current = self.model_binding()
        if live != current:
            raise RealReviewError(CODE_BINDING_CONFLICT)
        return current

    def model_binding(self) -> str:
        """The three digests of the model that would be served right now."""
        model = self.model()
        return model["snapshotsha"] + "|" + model["reviewsha"] + "|" + \
            model["mastersha"]

    def save_decisions(self, submitted, expected_revision,
                       presented_binding) -> dict:
        """Validate a complete set of choices and save it, or refuse.

        Validation is the existing core's, run before anything is persisted: the
        refs must be rows of this model, the candidate keys must be that row's
        own candidates, and a row whose evidence is insufficient cannot be
        approved. `build_review_export` is the entry point that does exactly that,
        and it is pure, so running it as the validator writes nothing anywhere.

        `presented_binding` is what the browser says it read. It has to be the
        current one, or nothing is written at all.
        """
        self.require_binding(presented_binding)
        self.require_current_binding()
        model = self.model()
        review_text = self._review_text()
        try:
            build_review_export(model, review_text, submitted)
        except ReviewContextError as exc:
            raise RealReviewError(exc.code) from None
        except Exception:
            raise RealReviewError(CODE_INTERNAL) from None
        if type(expected_revision) is not int or isinstance(expected_revision, bool):
            raise RealReviewError(CODE_INTERNAL)
        binding = model["snapshotsha"] + "|" + model["reviewsha"] + "|" + \
            model["mastersha"]
        choices = {}
        for entry in submitted:
            choices[entry["ref"]] = entry["value"]
        return self.store.save(binding, choices, expected_revision)

    def export(self, submitted=None, presented_binding=None) -> dict:
        """The existing decision CSV and plan, from saved or submitted choices.

        `submitted` is what the browser is holding right now, so an export can be
        made of the screen's own state. When it is None the saved choices are
        used, which is the export of a dataset someone else decided on.

        `presented_binding` is required, as it is on a save. An export carries the
        same decisions into a file that is meant to be applied later, so building
        one from a page that read a different dataset would produce a file whose
        rows are not the ones the user looked at.
        """
        self.require_binding(presented_binding)
        self.require_current_binding()
        model = self.model()
        review_text = self._review_text()
        if submitted is None:
            saved = self.store.load(
                model["snapshotsha"] + "|" + model["reviewsha"] + "|" +
                model["mastersha"])
            submitted = [{"ref": ref, "value": value}
                         for ref, value in saved["choices"].items()]
        try:
            result = build_review_export(model, review_text, submitted)
        except ReviewContextError as exc:
            raise RealReviewError(exc.code) from None
        except Exception:
            raise RealReviewError(CODE_INTERNAL) from None
        # The digests are re-checked after the work, so a source that changed
        # while the plan was being built cannot be exported under the old one.
        self._bound()
        return {
            "decision_csv": result["decision_csv"],
            "plan_json": json.dumps(result["plan_json"], ensure_ascii=False,
                                    sort_keys=True),
            "counts": result["counts"],
            "plan_digest": result["plan_digest"],
            "imports_ledger_rows": False,
        }

    def state_only_payload(self) -> dict:
        """The small answer the two-second poll reads.

        Binding, revision and counts, and nothing else. No source rows and no
        choices: a poll that carried the whole comparison would move 1,734 rows of
        source data every two seconds to discover that nothing changed, and would
        hold that data in every browser on a timer.
        """
        state = self.state()
        return {
            "state_only": True,
            "binding": state["binding"],
            "revision": state["revision"],
            "updated_at": state["updated_at"],
            "counts": state["counts"],
            # Carried here as well as on the page, so the owner learns that a
            # refresh failed without the page having to fetch anything else. A
            # collector that fails leaves the config alone, so this is the only
            # place its failure can be seen from.
            "refresh": refresh_status(),
        }

    def model_payload(self) -> dict:
        """The review context the screen renders, and the saved state with it.

        This is the model the pure core built: source fields and candidates per
        row, plus evidence status. It is not the workbook and not the card master,
        and there is no route that serves either of those.
        """
        model = self.model()
        return {
            "snapshotsha": model["snapshotsha"],
            "reviewsha": model["reviewsha"],
            "mastersha": model["mastersha"],
            "rows": model["rows"],
            "state": self.state(),
            "refresh": refresh_status(),
        }


# ------------------------------------------------------------------ binding

_SERVICE = None
_RESOLVED = False
_CONFIG_ERROR = ""


def bind_real_review(service) -> None:
    global _SERVICE, _RESOLVED, _CONFIG_ERROR, _LAST_RECHECK
    _SERVICE = service
    _RESOLVED = True
    _CONFIG_ERROR = ""
    _LAST_RECHECK = 0.0


def clear_real_review() -> None:
    """Forget the bound service and the environment lookup. Tests use this."""
    global _SERVICE, _RESOLVED, _CONFIG_ERROR, _LAST_RECHECK
    _SERVICE = None
    _RESOLVED = False
    _CONFIG_ERROR = ""
    _LAST_RECHECK = 0.0


def config_error() -> str:
    """The fixed code from a manifest that was set but could not be used."""
    return _CONFIG_ERROR


#: How often the config is re-read, in seconds. Bounded on purpose.
#:
#: A refresh replaces the config while the app runs, so the app has to notice, and
#: it has to notice without turning every request into a filesystem read. A change
#: is picked up within this long, and the cost is one read of one small file.
RECHECK_SECONDS = 2.0

_SERVICE_LOCK = threading.Lock()
_LAST_RECHECK = 0.0


def _config_fingerprint(path: str) -> bytes:
    """The config's own bytes.

    The bytes, not the modification time. A collector replaces the file, and a
    filesystem whose timestamp resolution is coarse can produce a replacement that
    looks unchanged, so a time comparison would leave the app on the old source
    for ever after a refresh that did happen.
    """
    if not path:
        return b""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


#: Where the collector records its outcome. A sibling of the config, because a
#: collector that fails does not change the config — it keeps the last good
#: bundle — so the web app would otherwise have nothing to notice. One file, read
#: by both sides, and overridable for a deployment that keeps it elsewhere.
REFRESH_STATUS_ENV = "WEBLEDGER_REVIEW_REFRESH_STATUS"


def refresh_status_path(config_path: str = "") -> str:
    configured = os.environ.get(REFRESH_STATUS_ENV, "").strip()
    if configured:
        return configured
    path = config_path or os.environ.get(CONFIG_ENV) or ""
    if not path:
        return ""
    return str(Path(path)) + ".refresh-status.json"


def read_refresh_status() -> dict:
    """The collector's last outcome, as a fixed code and nothing else.

    Read fresh each time, because the point is to notice a collector that has
    failed since the page was served. A collector that cannot write this file has
    not run, and that is a different state from one that has failed, so a missing
    file is reported as unknown rather than as success.
    """
    path = refresh_status_path()
    if not path:
        return {"code": CODE_REFRESH_STATUS_UNKNOWN, "source": "collector"}
    try:
        with open(path, "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
    except OSError:
        return {"code": CODE_REFRESH_STATUS_UNKNOWN, "source": "collector"}
    except Exception:
        return {"code": CODE_REFRESH_STATUS_INVALID, "source": "collector"}
    if type(data) is not dict:
        return {"code": CODE_REFRESH_STATUS_INVALID, "source": "collector"}
    code = data.get("code")
    if type(code) is not str or code == "":
        return {"code": CODE_REFRESH_STATUS_UNKNOWN, "source": "collector"}
    return {"code": code, "source": "collector",
            "collected_at": data.get("collected_at", "")}


def refresh_status() -> dict:
    """What the owner is told about the last refresh, whoever it was by.

    The collector's own record wins when it has one, because a failed collection
    never changes the config and would otherwise be invisible. A service that
    rejected a new config reports that when the collector has said nothing.
    """
    if _CONFIG_ERROR:
        # The service's own failure comes first. The collector's record is the
        # *last* collection, which after a failed config swap is a success that
        # happened before the failure — reporting that would say the source is
        # fine while the app is serving the previous bundle because it cannot read
        # the one it was pointed at. A past success is not the present state.
        return {"code": _CONFIG_ERROR, "source": "service"}
    return read_refresh_status()


def _recheck_service(service):
    """Swap in a newer config, but only for one the core has fully accepted.

    The whole model is built *before* the swap, not after. A new config naming a
    workbook the core refuses must never become the service a request is answered
    from, because the failure would then surface as a broken page rather than as a
    rejected refresh. On any failure the last good service keeps serving and the
    code is recorded, so the owner can be told the source did not move instead of
    assuming an unchanged screen means an unchanged source.
    """
    # `global` matters here. Without it the assignment below creates a local and
    # the failure is written nowhere, so `refresh_status` reports the previous
    # outcome and the owner is told the source refreshed when it did not.
    global _LAST_RECHECK, _CONFIG_ERROR
    path = getattr(service, "config_path", "")
    if not path:
        return service
    _LAST_RECHECK = time.monotonic()
    current = _config_fingerprint(path)
    if current and current == service.config_bytes:
        # The config is back to what this service was built from, so whatever
        # rejected it has been undone. Without clearing the code here the app would
        # keep reporting a failure that no longer exists, and an owner who fixed
        # the problem would still be told it was not fixed.
        _CONFIG_ERROR = ""
        return service
    if not current:
        # The config could not be read. That is a failure to report, not a reason
        # to say nothing: an unreadable config is why a refresh would be invisible.
        _CONFIG_ERROR = CODE_CONFIG_INVALID
        return service
    if current == getattr(service, "config_bytes", None):
        return service
    try:
        manifest = load_manifest(path)
        if manifest is None:
            return service
        # The decision history is not part of the source. A config that names a
        # different one would move every saved choice to a new file, silently:
        # the new bundle would show nothing decided, and re-saving would start a
        # second history beside the first. The collector never does this — a bundle
        # inherits the history from the config it replaces — so a config that does
        # is not a refresh, and it is refused rather than honoured.
        if str(manifest.get("decisions_db_path", "")) != str(
                service.store.path):
            _CONFIG_ERROR = CODE_DECISIONS_REPLACED
            return service
        candidate = RealReviewService(manifest)
        if candidate is None:
            return service
        # This build is the acceptance test, and it happens here on purpose.
        candidate.model()
    except RealReviewError as exc:
        _CONFIG_ERROR = exc.code
        return service
    except Exception:
        _CONFIG_ERROR = CODE_SOURCE_DRIFT
        return service
    candidate.config_path = path
    candidate.config_bytes = current
    _CONFIG_ERROR = ""
    return candidate


def active_service() -> RealReviewService | None:
    """The bound service, resolved from the environment once if none is bound.

    Resolving here rather than in a launcher means the feature turns on wherever
    `WEBLEDGER_REVIEW_CONFIG` is set, whichever entry point started the process,
    and it is still explicitly bindable for a test.

    After the first lookup the config is re-read at a bounded frequency, so a
    refresh is picked up without a restart. A request is handed one service object
    and keeps it for its whole life, so a swap cannot happen between two reads of
    the same request — which is what keeps a save and the export it belongs to
    pinned to one binding.
    """
    global _SERVICE, _RESOLVED, _CONFIG_ERROR, _LAST_RECHECK
    with _SERVICE_LOCK:
        due = time.monotonic() - _LAST_RECHECK >= RECHECK_SECONDS
        if not _RESOLVED:
            _RESOLVED = True
            _LAST_RECHECK = time.monotonic()
            try:
                _SERVICE = load_configured_service()
                if _SERVICE is not None:
                    _SERVICE.config_path = os.environ.get(CONFIG_ENV) or ""
                    _SERVICE.config_bytes = _config_fingerprint(
                        _SERVICE.config_path)
            except RealReviewError as exc:
                _SERVICE = None
                _CONFIG_ERROR = exc.code
        elif _SERVICE is None and due:
            # A first resolve that failed used to latch: the app then never looked
            # at the config again, so a config that became valid a minute later was
            # never seen without a restart. The same bounded re-read that picks up
            # a new bundle picks up a first one.
            #
            # The timestamp is set here as well. Without it this branch is due on
            # every single request for as long as the config stays broken, so a
            # misconfigured app would re-read and re-fail per request instead of at
            # the bounded rate the working path uses.
            _LAST_RECHECK = time.monotonic()
            try:
                _SERVICE = load_configured_service()
                if _SERVICE is not None:
                    _SERVICE.config_path = os.environ.get(CONFIG_ENV) or ""
                    _SERVICE.config_bytes = _config_fingerprint(
                        _SERVICE.config_path)
                    _CONFIG_ERROR = ""
            except RealReviewError as exc:
                _SERVICE = None
                _CONFIG_ERROR = exc.code
        elif _SERVICE is not None and due:
            _SERVICE = _recheck_service(_SERVICE)
        return _SERVICE


def load_configured_service() -> RealReviewService | None:
    """Build the service from the environment, or None when unconfigured.

    A configured-but-broken manifest raises rather than returning None, because
    None means "not configured" and the board would then quietly carry on as if
    the review did not exist.
    """
    manifest = load_manifest(os.environ.get(CONFIG_ENV))
    if manifest is None:
        return None
    return RealReviewService(manifest)
