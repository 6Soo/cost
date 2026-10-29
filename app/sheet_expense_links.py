"""Durable COST-to-sheet linkage metadata; never reads or writes Google sheets."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time


class LinkStoreError(Exception):
    """A safe, machine-readable linkage persistence error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_ALLOWED_STATUSES = frozenset(("MATCHED_MANUAL", "MATCHED_EXISTING"))


def _path_key(path) -> str:
    return str(Path(path).expanduser().resolve())


def _thread_lock(path_key: str) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path_key, threading.RLock())


@contextmanager
def _locked(path: Path):
    key = _path_key(path)
    with _thread_lock(key):
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                            raise
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _empty() -> dict:
    return {"revision": 0, "links": [], "history": []}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError):
        raise LinkStoreError("LINKS_UNAVAILABLE") from None
    if (not isinstance(data, dict) or type(data.get("revision")) is not int
            or data["revision"] < 0 or not isinstance(data.get("links"), list)
            or not isinstance(data.get("history"), list)
            or any(not isinstance(entry, dict) for entry in data["history"])):
        raise LinkStoreError("LINKS_UNAVAILABLE")
    transactions, sheet_keys = set(), set()
    for link in data["links"]:
        if not isinstance(link, dict):
            raise LinkStoreError("LINKS_UNAVAILABLE")
        tx = link.get("transaction_id")
        key = (link.get("trip_id"), link.get("sheet_id"), link.get("source"), link.get("stable_key"))
        if (not all(isinstance(value, str) and value for value in (tx, *key))
                or link.get("status") not in _ALLOWED_STATUSES or tx in transactions or key in sheet_keys):
            raise LinkStoreError("LINKS_UNAVAILABLE")
        transactions.add(tx)
        sheet_keys.add(key)
    return data


def load_links(path) -> dict:
    """Read canonical linkage metadata, returning an empty shape if not initialized."""
    return _read(Path(path))


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_results(results, now: str) -> list[dict]:
    if not isinstance(results, (list, tuple)) or not results:
        raise LinkStoreError("LINK_RESULTS_INVALID")
    normalized = []
    seen_transactions = set()
    seen_sheet_keys = set()
    for result in results:
        if not isinstance(result, dict) or result.get("status") not in _ALLOWED_STATUSES:
            raise LinkStoreError("LINK_STATUS_INVALID")
        transaction_id = result.get("transaction_id")
        trip_id, sheet_id, source = (result.get("trip_id"), result.get("sheet_id"), result.get("source"))
        stable_key = result.get("stable_key") or result.get("sheet_row_key")
        fingerprint = result.get("sheet_fingerprint")
        basis = result.get("basis")
        if not all(isinstance(value, str) and value.strip() for value in
                   (transaction_id, trip_id, sheet_id, source, stable_key, fingerprint)):
            raise LinkStoreError("LINK_IDENTITY_REQUIRED")
        if (not isinstance(basis, (list, tuple)) or not basis
                or any(not isinstance(item, str) or not item.strip() for item in basis)):
            raise LinkStoreError("LINK_BASIS_REQUIRED")
        row_number = result.get("row_number")
        user_override = result.get("user_override", False)
        link_method = result.get("link_method", "automatic_match")
        if row_number is not None and (type(row_number) is not int or row_number < 1):
            raise LinkStoreError("LINK_ROW_NUMBER_INVALID")
        if type(user_override) is not bool or not isinstance(link_method, str) or not link_method.strip():
            raise LinkStoreError("LINK_PROVENANCE_INVALID")
        if row_number is not None and stable_key == str(row_number):
            raise LinkStoreError("ROW_NUMBER_NOT_STABLE_KEY")
        sheet_key = (trip_id, sheet_id, source, stable_key)
        if transaction_id in seen_transactions or sheet_key in seen_sheet_keys:
            raise LinkStoreError("LINK_DUPLICATE_IN_REQUEST")
        seen_transactions.add(transaction_id)
        seen_sheet_keys.add(sheet_key)
        normalized.append({
            "transaction_id": transaction_id,
            "trip_id": trip_id,
            "sheet_id": sheet_id,
            "source": source,
            "row_number": row_number,
            "stable_key": stable_key,
            "sheet_fingerprint": fingerprint,
            "basis": list(basis),
            "user_override": user_override,
            "link_method": link_method,
            "timestamp": now,
            "last_verified": now,
            "status": result["status"],
        })
    return normalized


def _atomic_write(path: Path, data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(data, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise LinkStoreError("LINKS_WRITE_FAILED") from None


def save_links(path, results, *, expected_revision, request_id, source_digest, now=None) -> dict:
    """Atomically save verified links with CAS and idempotent request replay."""
    path = Path(path)
    if type(expected_revision) is not int or expected_revision < 0:
        raise LinkStoreError("LINK_REVISION_INVALID")
    if not isinstance(request_id, str) or not request_id.strip():
        raise LinkStoreError("LINK_REQUEST_ID_REQUIRED")
    if not isinstance(source_digest, str) or not source_digest.strip():
        raise LinkStoreError("LINK_SOURCE_DIGEST_REQUIRED")
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    normalized = _normalize_results(results, timestamp)
    request_results = [{key: value for key, value in item.items()
                        if key not in ("timestamp", "last_verified")} for item in normalized]
    payload_digest = hashlib.sha256(_canonical({
        "results": request_results,
        "source_digest": source_digest,
    }).encode("utf-8")).hexdigest()

    with _locked(path):
        data = _read(path)
        previous_request = next((entry for entry in reversed(data["history"])
                                 if entry.get("kind") == "request" and entry.get("request_id") == request_id), None)
        if previous_request:
            if previous_request.get("payload_digest") != payload_digest:
                raise LinkStoreError("LINK_REQUEST_ID_REUSED")
            return data
        if data["revision"] != expected_revision:
            raise LinkStoreError("LINK_REVISION_CONFLICT")

        links = list(data["links"])
        by_transaction = {link.get("transaction_id"): link for link in links}
        by_sheet_key = {(link.get("trip_id"), link.get("sheet_id"), link.get("source"),
                         link.get("stable_key")): link for link in links}
        for candidate in normalized:
            current_tx = by_transaction.get(candidate["transaction_id"])
            current_sheet = by_sheet_key.get((candidate["trip_id"], candidate["sheet_id"],
                                              candidate["source"], candidate["stable_key"]))
            if current_tx and (current_tx.get("trip_id"), current_tx.get("sheet_id"),
                               current_tx.get("source"), current_tx.get("stable_key")) != (
                                   candidate["trip_id"], candidate["sheet_id"], candidate["source"], candidate["stable_key"]):
                raise LinkStoreError("TRANSACTION_ALREADY_LINKED")
            if current_sheet and current_sheet.get("transaction_id") != candidate["transaction_id"]:
                raise LinkStoreError("SHEET_ROW_ALREADY_LINKED")

        new_revision = data["revision"] + 1
        for candidate in normalized:
            prior = by_transaction.get(candidate["transaction_id"])
            provenance = {"request_id": request_id, "source_digest": source_digest,
                          "link_method": candidate["link_method"],
                          "user_override": candidate["user_override"]}
            record = {**candidate, "revision": new_revision, "provenance": provenance}
            if prior:
                links[links.index(prior)] = record
            else:
                links.append(record)
            data["history"].append({
                "kind": "link_saved", "revision": new_revision,
                "transaction_id": candidate["transaction_id"],
                "trip_id": candidate["trip_id"], "sheet_id": candidate["sheet_id"],
                "source": candidate["source"], "stable_key": candidate["stable_key"],
                "before": prior, "after": record,
                "at": timestamp,
            })
            by_transaction[candidate["transaction_id"]] = record
            by_sheet_key[(candidate["trip_id"], candidate["sheet_id"],
                          candidate["source"], candidate["stable_key"])] = record
        data["revision"] = new_revision
        data["links"] = links
        data["history"].append({"kind": "request", "revision": new_revision,
                               "request_id": request_id, "payload_digest": payload_digest,
                               "source_digest": source_digest, "at": timestamp})
        _atomic_write(path, data)
        return data
