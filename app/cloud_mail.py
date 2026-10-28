"""Read private Apps Script mail exports without replacing local evidence.

Dry run is the default. Applying only appends new Gmail full originals and invokes
the existing transactional raw-mail importer; it never writes ledger decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from app.mail_collect import stored_ids, sync_unified_store

_ID = re.compile(r"[a-fA-F0-9]+\Z")
_FILE_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_MANIFEST = "cloud-mail-manifest.json"
_MAX_BYTES = 16 * 1024 * 1024
_MAX_TOTAL = 100 * 1024 * 1024


class CloudMailError(ValueError):
    """Finite, original-free error codes safe for scheduled-task logs."""


def _json(content):
    try:
        return json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError, AttributeError):
        raise CloudMailError("CLOUD_MAIL_JSON_INVALID") from None


def _original(content, message_id):
    data = _json(content)
    messages = data.get("responses") if isinstance(data, dict) else None
    if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
        raise CloudMailError("CLOUD_MAIL_ORIGINAL_INVALID")
    message = messages[0]
    payload = message.get("payload")
    if (message.get("id") != message_id or not str(message.get("internalDate") or "").isdigit()
            or not isinstance(payload, dict) or not isinstance(payload.get("headers"), list)
            or not payload["headers"]):
        raise CloudMailError("CLOUD_MAIL_ORIGINAL_INVALID")


def _bounded_content(client, file_id):
    content = client.download(file_id, max_bytes=_MAX_BYTES)
    if not isinstance(content, bytes) or not content or len(content) > _MAX_BYTES:
        raise CloudMailError("CLOUD_MAIL_FILE_SIZE_INVALID")
    return content


def sync(client, directory, *, folder_id, expected_account, apply=False, batch_size=None, batch_offset=0):
    """Validate a private folder's manifest and all new originals before appending.

    `client.list_files` must enumerate every page; metadata must contain id, name,
    parents and MIME type. Existing Gmail IDs retain their original local copy,
    including label/history metadata that may differ on a later cloud retrieval.
    """
    if not isinstance(folder_id, str) or not _FILE_ID.fullmatch(folder_id) or not expected_account:
        raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
    if batch_size is not None:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not (1 <= batch_size <= 100):
            raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
    if not isinstance(batch_offset, int) or isinstance(batch_offset, bool) or batch_offset < 0:
        raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
    if batch_size is None and batch_offset > 0:
        raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
    if apply and batch_offset > 0:
        raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
    folder = client.folder(folder_id)
    if (not isinstance(folder, dict) or folder.get("id") != folder_id
            or folder.get("mimeType") != "application/vnd.google-apps.folder"
            or folder.get("trashed") or folder.get("shared") is not False
            or [owner.get("emailAddress") for owner in folder.get("owners", ())] != [expected_account]):
        raise CloudMailError("CLOUD_MAIL_FOLDER_NOT_PRIVATE")
    files = list(client.list_files(folder_id))
    if any(not isinstance(file, dict) for file in files):
        raise CloudMailError("CLOUD_MAIL_FILES_INVALID")
    manifests = [file for file in files if file.get("name") == _MANIFEST]
    if len(manifests) != 1:
        raise CloudMailError("CLOUD_MAIL_MANIFEST_NOT_UNIQUE")
    by_id = {}
    names = set()
    for file in files:
        file_id, name = file.get("id"), file.get("name")
        if (not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id)
                or not isinstance(name, str) or file_id in by_id or name in names
                or file.get("parents") != [folder_id] or file.get("trashed")
                or file.get("mimeType") != "application/json" or file.get("shared") is not False):
            raise CloudMailError("CLOUD_MAIL_FILES_INVALID")
        by_id[file_id] = file
        names.add(name)
    manifest = _json(_bounded_content(client, manifests[0]["id"]))
    if (not isinstance(manifest, dict) or manifest.get("schema") != "cost-cloud-mail-v1"
            or not isinstance(manifest.get("messages"), dict)):
        raise CloudMailError("CLOUD_MAIL_MANIFEST_INVALID")
    if manifest.get("account") != expected_account:
        raise CloudMailError("CLOUD_MAIL_ACCOUNT_MISMATCH")
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise CloudMailError("CLOUD_MAIL_LOCAL_DIRECTORY_REQUIRED")
    known = stored_ids(directory)
    new_candidates = []
    for message_id, entry in manifest["messages"].items():
        if not isinstance(message_id, str) or not _ID.fullmatch(message_id) or not isinstance(entry, dict):
            raise CloudMailError("CLOUD_MAIL_MANIFEST_INVALID")
        expected_name = f"gmail-{message_id}.json"
        file_id = entry.get("file_id")
        if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
            raise CloudMailError("CLOUD_MAIL_MANIFEST_INVALID")
        file = by_id.get(file_id)
        if file is None or entry.get("name") != expected_name or file["name"] != expected_name:
            raise CloudMailError("CLOUD_MAIL_ORIGINAL_MISSING")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise CloudMailError("CLOUD_MAIL_DIGEST_REQUIRED")
        if message_id in known:
            continue
        target = directory / f"gmail-cloud-{message_id}.json"
        # A file containing some other ID is not permission to replace that file.
        if target.exists():
            raise CloudMailError("CLOUD_MAIL_LOCAL_CONFLICT")
        new_candidates.append((message_id, file, digest, target))

    enumeration_complete = (
        manifest.get("query") is None
        and isinstance(manifest.get("last_complete"), str)
    )
    if apply and batch_size is not None and not enumeration_complete:
        raise CloudMailError("CLOUD_MAIL_ENUMERATION_INCOMPLETE")

    total_new = len(new_candidates)
    if batch_size is None:
        selected_candidates = new_candidates
        selected = total_new
        remaining_new = 0
    else:
        selected_candidates = new_candidates[batch_offset : batch_offset + batch_size]
        selected = len(selected_candidates)
        remaining_new = max(0, total_new - (batch_offset + selected))

    pending, total_bytes = [], 0
    for message_id, file, digest, target in selected_candidates:
        content = _bounded_content(client, file["id"])
        total_bytes += len(content)
        if total_bytes > _MAX_TOTAL:
            raise CloudMailError("CLOUD_MAIL_BATCH_TOO_LARGE")
        if hashlib.sha256(content).hexdigest() != digest:
            raise CloudMailError("CLOUD_MAIL_DIGEST_MISMATCH")
        _original(content, message_id)
        pending.append((target, content))

    appended = 0
    if apply:
        for target, content in pending:
            descriptor, temporary = tempfile.mkstemp(prefix=".cloud-mail-", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Same-volume atomic install, refusing any competing existing file.
                os.link(temporary, target)
                appended += 1
            except FileExistsError:
                raise CloudMailError("CLOUD_MAIL_LOCAL_CONFLICT") from None
            finally:
                os.unlink(temporary)
        # Retry a prior failed transactional import even when files already exist.
        sync_unified_store(directory)

    result = {
        "mode": "APPLY" if apply else "DRY_RUN",
        "indexed": len(manifest["messages"]),
        "existing": len(manifest["messages"].keys() & known),
        "new": total_new,
        "appended": appended,
        "download_bytes": total_bytes,
        "enumeration_complete": enumeration_complete,
    }
    if batch_size is not None:
        result["selected"] = selected
        result["remaining_new"] = remaining_new
        result["batch_offset"] = batch_offset
    return result


class DriveClient:
    """Google ADC with Drive read-only scope, bounded bodies and no redirects."""

    def __init__(self, session=None):
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
            session = AuthorizedSession(credentials)
        self.session = session

    def _get(self, suffix, *, params=None, max_bytes=_MAX_BYTES):
        try:
            response = self.session.get("https://www.googleapis.com/drive/v3/" + suffix,
                                        params=params, timeout=45, stream=True, allow_redirects=False)
        except Exception:
            raise CloudMailError("CLOUD_MAIL_DRIVE_UNREACHABLE") from None
        try:
            if response.status_code in (401, 403):
                raise CloudMailError("CLOUD_MAIL_DRIVE_ACCESS_DENIED")
            if response.status_code != 200:
                raise CloudMailError("CLOUD_MAIL_DRIVE_READ_FAILED")
            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise CloudMailError("CLOUD_MAIL_FILE_SIZE_INVALID")
            return bytes(content)
        finally:
            response.close()

    def folder(self, folder_id):
        if not _FILE_ID.fullmatch(folder_id):
            raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
        return _json(self._get("files/" + folder_id,
                              params={"fields": "id,mimeType,shared,trashed,owners(emailAddress)"}))

    def list_files(self, folder_id):
        if not isinstance(folder_id, str) or not _FILE_ID.fullmatch(folder_id):
            raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
        token, seen = None, set()
        while True:
            params = {"q": f"'{folder_id}' in parents and trashed=false", "pageSize": 1000,
                      "fields": "nextPageToken,files(id,name,parents,mimeType,trashed,shared)"}
            if token:
                params["pageToken"] = token
            result = _json(self._get("files", params=params))
            if not isinstance(result, dict) or not isinstance(result.get("files"), list):
                raise CloudMailError("CLOUD_MAIL_FILES_INVALID")
            yield from result["files"]
            token = result.get("nextPageToken")
            if not token:
                return
            if not isinstance(token, str) or token in seen:
                raise CloudMailError("CLOUD_MAIL_PAGE_TOKEN_INVALID")
            seen.add(token)

    def download(self, file_id, *, max_bytes):
        if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
            raise CloudMailError("CLOUD_MAIL_CONFIG_INVALID")
        return self._get("files/" + file_id, params={"alt": "media"}, max_bytes=max_bytes)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Read private cloud mail evidence; dry run by default")
    parser.add_argument("--directory", required=True)
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--batch-offset", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = sync(DriveClient(), args.directory, folder_id=args.folder_id,
                      expected_account=args.account, apply=args.apply,
                      batch_size=args.batch_size, batch_offset=args.batch_offset)
    except CloudMailError as error:
        print(json.dumps({"status": "ERROR", "code": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"status": "ERROR", "code": "CLOUD_MAIL_RUNTIME_FAILED"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
