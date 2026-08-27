"""Authenticated private-input gate for R43 receipt evidence.

The sidecar and HMAC key are restricted external files.  This module never
publishes message IDs, recipient addresses, or attachment names.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from typing import Mapping

from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity

SCHEMA_VERSION = 2
PURPOSE = "r43_receipt_airfare_evidence"
ACQUISITION_TOOL = "gmail-api-users.messages.get-format-raw-v1"
EXTRACTOR_CONTRACT = "pypdf-5.9.0:extract_text:pages-in-order:utf8-lf-formfeed:v1"
EXTRACTOR_CONTRACT_SHA256 = hashlib.sha256(EXTRACTOR_CONTRACT.encode()).hexdigest()
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("r43_provenance_duplicate_json_key")
        out[key] = value
    return out


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _private_bytes(path: Path) -> bytes:
    path = path.resolve()
    root = REPOSITORY_ROOT.resolve()
    if root in (path, *path.parents):
        raise ValueError("r43_authenticated_input_inside_repository")
    directory = path.parent
    dfd = open_dir(directory)
    try:
        dst = os.fstat(dfd)
        if (dst.st_mode & 0o777) != 0o700 or dst.st_uid != os.getuid():
            raise ValueError("r43_authenticated_directory_invalid")
        fd = open_at(dfd, path.name)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or (before.st_mode & 0o777) != 0o600 or before.st_uid != os.getuid()
                    or before.st_nlink != 1):
                raise ValueError("r43_authenticated_file_invalid")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("r43_authenticated_file_changed")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def _mac(key: bytes, domain: str, value: bytes) -> str:
    return hmac.new(key, domain.encode() + b"\0" + value, hashlib.sha256).hexdigest()


def _manifest_mac(key: bytes, manifest: dict) -> str:
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_hmac_sha256"}
    return _mac(key, "r43-acquisition-manifest-v1", _json(unsigned))


def _mime_facts(raw: bytes):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    mids = message.get_all("Message-ID", [])
    delivered = message.get_all("Delivered-To", [])
    if len(mids) != 1 or len(delivered) != 1:
        raise ValueError("r43_mime_identity_cardinality_invalid")
    message_id = str(mids[0]).strip()
    account = parseaddr(str(delivered[0]))[1].strip().lower()
    if not message_id or not account:
        raise ValueError("r43_mime_identity_invalid")
    sender_domain=parseaddr(str(message.get("From", "")))[1].rsplit("@",1)[-1].lower()
    auth_headers=[str(x) for x in message.get_all("Authentication-Results",[])]
    signature_domains={x.lower().rstrip(".") for header in message.get_all("DKIM-Signature",[]) for x in re.findall(r"(?i)(?:^|;)\s*d\s*=\s*([a-z0-9.-]+)",str(header))}
    passed_domains=set()
    for header in auth_headers:
        for clause in re.split(r";",header):
            if not re.search(r"(?i)\bdkim\s*=\s*pass\b",clause):continue
            match=re.search(r"(?i)\bheader\.(?:d|i)\s*=\s*@?([a-z0-9.-]+)",clause)
            if match:passed_domains.add(match.group(1).lower().rstrip("."))
    aligned={d for d in passed_domains & signature_domains if sender_domain==d or sender_domain.endswith("."+d) or d.endswith("."+sender_domain)}
    if not sender_domain or not aligned:raise ValueError("r43_mime_outer_auth_invalid")
    transport_auth=("provider_outer_dkim_aligned" if sender_domain=="trip.com" and any(d=="trip.com" or d.endswith(".trip.com") for d in aligned) else "forwarded_outer_auth_observed_unverified")
    attachments = []
    for index, part in enumerate(message.walk()):
        payload = part.get_payload(decode=True)
        if payload is None or part.get_content_type() != "application/pdf":
            continue
        filename = part.get_filename()
        if not filename:
            raise ValueError("r43_mime_attachment_name_missing")
        attachments.append((index, filename, payload))
    return message_id, account, transport_auth, attachments


_EXTRACT_SCRIPT = r'''import base64,hashlib,io,json,sys
import pypdf
if pypdf.__version__ != "5.9.0": raise SystemExit("pypdf_version_invalid")
items=json.loads(sys.stdin.buffer.read())
out=[]
for item in items:
    raw=base64.b64decode(item["pdf"],validate=True)
    if len(raw)>2_000_000: raise SystemExit("pdf_size_invalid")
    reader=pypdf.PdfReader(io.BytesIO(raw),strict=True)
    if reader.is_encrypted: raise SystemExit("pdf_encrypted")
    root=reader.trailer.get("/Root",{})
    if any(k in root for k in ("/OpenAction","/AA")): raise SystemExit("pdf_active_content")
    names=root.get("/Names",{})
    if "/EmbeddedFiles" in names or "/JavaScript" in names: raise SystemExit("pdf_active_or_embedded")
    if not 1<=len(reader.pages)<=4: raise SystemExit("pdf_pages_invalid")
    text="\n\f\n".join((page.extract_text() or "") for page in reader.pages).encode()
    if not text.strip() or len(text)>1_000_000: raise SystemExit("pdf_text_invalid")
    out.append({"alias":item["alias"],"pages":len(reader.pages),
                "text":base64.b64encode(text).decode(),
                "text_sha256":hashlib.sha256(text).hexdigest()})
sys.stdout.write(json.dumps(out,sort_keys=True,separators=(",",":")))
'''


def _run_extractor(python_path: Path, pdfs: Mapping[str, bytes]) -> dict[str, tuple[bytes, int]]:
    # Keep the explicit venv entrypoint: resolving its normal ``python``
    # symlink would discard the venv prefix and therefore its locked pypdf.
    executable = python_path.absolute()
    if not executable.is_file():
        raise ValueError("r43_pypdf_python_invalid")
    request = [{"alias": alias, "pdf": base64.b64encode(raw).decode()}
               for alias, raw in sorted(pdfs.items())]
    try:
        result = subprocess.run([str(executable), "-I", "-c", _EXTRACT_SCRIPT],
                                input=json.dumps(request).encode(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=60, check=True,
                                env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"})
        rows = json.loads(result.stdout, object_pairs_hook=_strict_object)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("r43_pypdf_extraction_failed") from exc
    if not isinstance(rows, list) or {x.get("alias") for x in rows} != set(pdfs):
        raise ValueError("r43_pypdf_output_invalid")
    return {x["alias"]: (base64.b64decode(x["text"], validate=True), int(x["pages"]))
            for x in rows}


def build_authenticated_sidecar(documents_dir: Path, key_path: Path,
                                expected_docs: Mapping[str, tuple[str, str, int]],
                                pypdf_python: Path) -> bytes:
    """Build sidecar bytes from actual RFC822 MIME; caller controls private write."""
    key = _private_bytes(key_path)
    if len(key) < 32:
        raise ValueError("r43_hmac_key_invalid")
    pdfs = {alias: _private_bytes(documents_dir / f"{alias}.pdf") for alias in expected_docs}
    texts = {alias: _private_bytes(documents_dir / f"{alias}.txt") for alias in expected_docs}
    mime_files = sorted(documents_dir.glob("raw_*.eml"))
    if len(mime_files) != len(expected_docs):
        raise ValueError("r43_raw_mime_census_invalid")
    matches = {}
    account = None
    message_ids = set()
    for mime_path in mime_files:
        raw = _private_bytes(mime_path)
        mid, recipient, transport_auth, attachments = _mime_facts(raw)
        if mid in message_ids:
            raise ValueError("r43_mime_message_duplicate")
        message_ids.add(mid)
        if account is None:
            account = recipient
        elif account != recipient:
            raise ValueError("r43_mime_account_mismatch")
        for index, filename, attachment in attachments:
            aliases = [a for a, pdf in pdfs.items() if hmac.compare_digest(pdf, attachment)]
            if len(aliases) == 1:
                alias = aliases[0]
                if alias in matches:
                    raise ValueError("r43_mime_attachment_duplicate")
                matches[alias] = (mime_path.name, raw, mid, transport_auth, filename, index, attachment)
    if set(matches) != set(expected_docs):
        raise ValueError("r43_mime_attachment_census_invalid")
    extracted = _run_extractor(pypdf_python, pdfs)
    entries = []
    for alias in sorted(expected_docs):
        pdf_sha, text_sha, pages = expected_docs[alias]
        mime_name, raw, mid, transport_auth, filename, index, attachment = matches[alias]
        fresh, fresh_pages = extracted[alias]
        if (_sha(pdfs[alias]), _sha(texts[alias]), fresh, fresh_pages) != (
                pdf_sha, text_sha, texts[alias], pages):
            raise ValueError("r43_fresh_extraction_mismatch")
        entries.append({"alias": alias, "raw_mime_file": mime_name,
                        "raw_mime_sha256": _sha(raw), "raw_mime_size": len(raw),
                        "message_id_hmac": _mac(key, "message-id", mid.encode()),
                        "transport_auth": transport_auth,
                        "attachment_name_hmac": _mac(key, "attachment-name", filename.encode()),
                        "document_id_hmac": _mac(key, "document-id", attachment),
                        "attachment_part_index": index, "pdf_sha256": _sha(attachment),
                        "pdf_size": len(attachment), "text_sha256": _sha(fresh),
                        "pages": fresh_pages})
    manifest = {"schema_version": SCHEMA_VERSION, "purpose": PURPOSE,
                "acquisition_tool": ACQUISITION_TOOL,
                "extractor_contract_sha256": EXTRACTOR_CONTRACT_SHA256,
                "account_hmac": _mac(key, "delivered-to", account.encode()),
                "documents": entries}
    manifest["manifest_hmac_sha256"] = _manifest_mac(key, manifest)
    return _json(manifest)


def verify_authenticated_inputs(documents_dir: Path, sidecar_path: Path, key_path: Path,
                                expected_docs: Mapping[str, tuple[str, str, int]],
                                pypdf_python: Path) -> dict:
    """Rebuild from live private inputs and require byte-identical signed sidecar."""
    actual = _private_bytes(sidecar_path)
    try:
        parsed = json.loads(actual, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as exc:
        raise ValueError("r43_provenance_json_invalid") from exc
    key = _private_bytes(key_path)
    if not isinstance(parsed, dict) or not _HEX64.fullmatch(str(parsed.get("manifest_hmac_sha256", ""))):
        raise ValueError("r43_provenance_schema_invalid")
    if not hmac.compare_digest(_manifest_mac(key, parsed), parsed["manifest_hmac_sha256"]):
        raise ValueError("r43_provenance_hmac_invalid")
    expected = build_authenticated_sidecar(documents_dir, key_path, expected_docs, pypdf_python)
    expected_parsed = json.loads(expected, object_pairs_hook=_strict_object)
    # Whitespace is not an authenticated fact: the MAC above covers the strict
    # canonical object.  Require semantic identity with a fresh live rebuild.
    if parsed != expected_parsed:
        raise ValueError("r43_authenticated_inputs_mismatch")
    return {"status": "valid", "documents": len(expected_docs),
            "extractor_contract_sha256": EXTRACTOR_CONTRACT_SHA256,
            "sidecar_sha256": _sha(actual), "provenance": parsed}