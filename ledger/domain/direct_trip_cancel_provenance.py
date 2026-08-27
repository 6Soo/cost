"""Authenticated, fresh provenance for the nine restricted R44 Trip MIME files."""
from __future__ import annotations

import hashlib
import hmac
import json
import argparse
import os
import re
import stat
import subprocess
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html import unescape
from pathlib import Path

from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity

ARTIFACT_TYPE = "r44-trip-cancel-provenance-v2"
DOMAIN = b"cost:r44:trip-cancel:provenance:v2\0"
IDENTITY_DOMAIN = b"cost:r44:trip-cancel:identity:v2\0"
EXTRACTOR_VERSION = "pypdf-5.9.0-bytesio-v1"
EXTRACT_SCRIPT = (
    "import io,json,sys,pypdf;"
    "b=sys.stdin.buffer.read();r=pypdf.PdfReader(io.BytesIO(b),strict=True);"
    "root=r.trailer.get('/Root',{});"
    "bad=bool(r.is_encrypted or any(k in root for k in ('/OpenAction','/AA')) or "
    "('/Names' in root and any(k in root['/Names'] for k in ('/EmbeddedFiles','/JavaScript'))));"
    "pages=len(r.pages);texts=[p.extract_text() or '' for p in r.pages];text='\\n'.join(texts);"
    "print(json.dumps({'version':pypdf.__version__,'pages':pages,'text':text,'active':bad},"
    "ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False))"
)
EXTRACTOR_CONTRACT_SHA256 = hashlib.sha256((EXTRACTOR_VERSION + "\n" + EXTRACT_SCRIPT).encode()).hexdigest()
RAW_DOCS = {
    "doc-01.eml": "dcc03ba452b12a5041d8419de9d00d76cccbf2847014e6b7c54993f5734fc6a1",
    "doc-02.eml": "8120f55abb128c332946a3ebbcb4856b286a5bf00d41061c3a873307130135a6",
    "doc-03.eml": "bb0a9f113a1067d262afe758807df9f79d1406dcf96b9b1f40371dfd25cf3085",
    "doc-04.eml": "66198d17cc630fdc7c28547dd032c5ad5cbb02eca7faab2da4f23ca798e15312",
    "doc-05.eml": "29e25ddd320fecfa4274d753b0250dd6489df848c49b237e79c111f39aab3ff4",
    "doc-06.eml": "92352cf9433c642d255ee6f994223b6e0006c450781dc120321c03a0c9f2c268",
    "doc-07.eml": "dcba0c445da017f672807ca71220da90e6dad7aebfe0ec4e2f3028c50a905826",
    "doc-08.eml": "b31d6ed41ce9b93f1e67a938ed17b5b113ea4ce4354e694490ad1690eedcf2c5",
    "doc-09.eml": "28bcd36d222800eea0a660587ca910c372e282e6b6c0f33c310ea0f608e54842",
}
RECEIPT_PDFS = {
    "ee8a1e21cdbc134d8570101c0e30a0e87fd51b08b17f4645bfe17fa048a0add6",
    "1d6d1bc2f96219c8e26684e38c3cddfc342b53ec007e9b65494b2f8199a231de",
}
PINNED_RUNTIME = {
    "requested_path": "/tmp/cost-r43-pdf-venv/bin/python",
    "executable_path": "/usr/bin/python3.12",
    "executable_sha256": "1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118",
    "pyvenv_cfg_sha256": "6a7fccbb0970d5204a07fed3eb98d539ec50576e7ef4a8d8dfdc9309c097b546",
    "pypdf_module_sha256": "16f7b97e0c8f56d9c4d05d07157014e27527eb46cd7a1a97af14133f859dd186",
    "pypdf_tree_file_count": 56,
    "pypdf_tree_sha256": "d1e57aad5c9b2720b646fd7c5e2101cb6d1f329bed5e71837b6a368dcadb11f1",
    "pypdf_version": "5.9.0",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _read_regular(directory: Path, name: str) -> bytes:
    dirfd = open_dir(directory)
    try:
        fd = open_at(dirfd, name)
        try:
            before = os.fstat(fd)
            verify_regular_single_link(fd, mode=0o600)
            if before.st_uid != os.getuid():
                raise ValueError("r44_private_file_invalid")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("r44_private_file_changed")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(dirfd)


def _private_dir(directory: Path) -> Path:
    if directory.is_symlink():
        raise ValueError("r44_private_directory_invalid")
    resolved = directory.resolve(strict=True)
    if REPOSITORY_ROOT.resolve() in (resolved, *resolved.parents):
        raise ValueError("r44_private_input_inside_repository")
    st = resolved.stat()
    if (not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700 or
            st.st_uid != os.getuid()):
        raise ValueError("r44_private_directory_invalid")
    return resolved


def _identity(key: bytes, kind: str, value: str) -> str:
    return hmac.new(key, IDENTITY_DOMAIN + kind.encode() + b"\0" + value.encode(), hashlib.sha256).hexdigest()


def _html_text(message) -> tuple[str, str]:
    html_parts = []
    for part in message.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                html_parts.append(payload.decode(part.get_content_charset() or "utf-8", "strict"))
    if len(html_parts) != 1:
        raise ValueError("r44_mime_html_contract_invalid")
    raw = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", html_parts[0])
    text = unescape(re.sub(r"<[^>]+>", "\n", raw))
    return raw, re.sub(r"\s+", " ", text).strip()


def _extract_pdf(pdf: bytes, python: Path) -> dict[str, object]:
    if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-2048:]:
        raise ValueError("r44_pdf_bytes_invalid")
    if len(pdf)>2*1024*1024:raise ValueError("r44_pdf_size_invalid")
    executable=_validate_runtime(python)
    try:
        result = subprocess.run([str(executable), "-I", "-c", EXTRACT_SCRIPT], input=pdf, capture_output=True,
                                env={"PATH":"/usr/bin:/bin","PYTHONHASHSEED":"0"},check=True, timeout=30)
        if result.stderr or len(result.stdout)>2*1024*1024 or result.stdout.count(b"\n")!=1:
            raise ValueError("r44_pdf_extractor_output_invalid")
        parsed = json.loads(result.stdout,object_pairs_hook=_reject_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError("r44_pdf_extraction_failed") from exc
    if (set(parsed)!={"version","pages","text","active"} or parsed.get("version") != "5.9.0" or
            not isinstance(parsed.get("pages"),int) or not 1<=parsed["pages"]<=4 or
            not isinstance(parsed.get("text"),str) or not parsed["text"].strip() or len(parsed["text"].encode())>1024*1024 or
            parsed.get("active") is not False):
        raise ValueError("r44_pdf_extractor_contract_invalid")
    return parsed


def _reject_pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError("r44_json_duplicate_key")
        out[key]=value
    return out


def _validate_runtime(python:Path) -> Path:
    requested=Path(PINNED_RUNTIME["requested_path"])
    if python.absolute()!=requested or not requested.is_symlink():raise ValueError("r44_pdf_runtime_invalid")
    executable=requested.resolve(strict=True);cfg=requested.parent.parent/"pyvenv.cfg"
    module=requested.parent.parent/"lib/python3.12/site-packages/pypdf/__init__.py"
    for path in (executable,cfg,module):
        st=path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid not in {0,os.getuid()}:raise ValueError("r44_pdf_runtime_invalid")
    tree_count,tree_sha=_package_tree_commitment(module.parent)
    if (str(executable),_sha(executable.read_bytes()),_sha(cfg.read_bytes()),_sha(module.read_bytes()),tree_count,tree_sha)!=(
        PINNED_RUNTIME["executable_path"],PINNED_RUNTIME["executable_sha256"],PINNED_RUNTIME["pyvenv_cfg_sha256"],PINNED_RUNTIME["pypdf_module_sha256"],
        PINNED_RUNTIME["pypdf_tree_file_count"],PINNED_RUNTIME["pypdf_tree_sha256"]):
        raise ValueError("r44_pdf_runtime_invalid")
    return requested


def _package_tree_commitment(root:Path) -> tuple[int,str]:
    digest=hashlib.sha256();count=0
    for path in sorted(x for x in root.rglob("*") if x.is_file() and "__pycache__" not in x.parts and not x.is_symlink()):
        rel=path.relative_to(root).as_posix().encode();data=path.read_bytes()
        digest.update(len(rel).to_bytes(4,"big"));digest.update(rel);digest.update(len(data).to_bytes(8,"big"));digest.update(hashlib.sha256(data).digest());count+=1
    return count,digest.hexdigest()


def _trusted_dkim(message) -> None:
    trusted=[]
    for value in message.get_all("Authentication-Results",[]):
        text=str(value);authserv=text.split(";",1)[0].strip().lower()
        if authserv=="mx.google.com":trusted.append(text)
    if len(trusted)!=1:raise ValueError("r44_trusted_authentication_results_invalid")
    clauses=[x.strip() for x in trusted[0].split(";")[1:] if re.match(r"^dkim=",x.strip(),re.I)]
    aligned=[x for x in clauses if re.match(r"^dkim=pass\b",x,re.I) and re.search(r"\bheader\.i=@trip\.com\b",x,re.I)]
    if len(aligned)!=1 or any(re.search(r"\bheader\.i=@trip\.com\b",x,re.I) and x not in aligned for x in clauses):
        raise ValueError("r44_dkim_invalid")
    domain=re.search(r"\bheader\.d=([A-Za-z0-9.-]+)",aligned[0],re.I)
    if domain is not None and domain.group(1).lower()!="trip.com":raise ValueError("r44_dkim_invalid")
    selector=re.search(r"\bheader\.s=([A-Za-z0-9._-]+)",aligned[0],re.I)
    signature_prefix=re.search(r"\bheader\.b=\"?([A-Za-z0-9+/=_-]+)\"?(?=\s|$)",aligned[0],re.I)
    if selector is None or signature_prefix is None:raise ValueError("r44_dkim_selector_invalid")
    signatures=message.get_all("DKIM-Signature",[])
    associated=[]
    for raw in signatures:
        text=str(raw);sig_b=re.search(r"(?:^|;)\s*b=([^;]+)",text,re.I)
        trip_domain=bool(re.search(r"(?:^|;)\s*d=trip\.com\s*(?:;|$)",text,re.I))
        same_selector=bool(re.search(rf"(?:^|;)\s*s={re.escape(selector.group(1))}\s*(?:;|$)",text,re.I))
        same_signature=bool(sig_b is not None and re.sub(r"\s+","",sig_b.group(1)).startswith(signature_prefix.group(1)))
        if trip_domain or same_selector or same_signature:
            associated.append((trip_domain,same_selector,same_signature))
    if associated!=[(True,True,True)]:raise ValueError("r44_dkim_selector_association_invalid")


def _fresh_unsigned(directory: Path, key: bytes, pypdf_python: Path) -> dict[str, object]:
    root = _private_dir(directory)
    if {x.name for x in root.glob("doc-*.eml")} != set(RAW_DOCS):
        raise ValueError("r44_raw_mime_census_invalid")
    if len(key) != 32:
        raise ValueError("r44_provenance_key_invalid")
    documents = []
    lifecycle: dict[str, dict[str, object]] = {}
    receipt_hashes = set()
    message_ids = set()
    for name, expected_sha in sorted(RAW_DOCS.items()):
        raw_bytes = _read_regular(root, name)
        if _sha(raw_bytes) != expected_sha:
            raise ValueError("r44_raw_mime_drift")
        message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        from_address = parseaddr(str(message.get("From", "")))[1].lower()
        if from_address.rsplit("@", 1)[-1] != "trip.com":
            raise ValueError("r44_from_domain_invalid")
        _trusted_dkim(message)
        message_id = str(message.get("Message-ID", "")).strip()
        if not message_id or message_id in message_ids:
            raise ValueError("r44_message_identity_invalid")
        message_ids.add(message_id)
        html, text = _html_text(message)
        refs = set(re.findall(r"(?<!\d)1\d{15}(?!\d)", html))
        if len(refs) != 1:
            raise ValueError("r44_order_reference_invalid")
        ref = refs.pop()
        confirmation = "예약이 확정되었습니다" in text
        cancellation = "취소 완료" in text and "예약이 취소되었습니다" in text
        if confirmation == cancellation:
            raise ValueError("r44_lifecycle_state_invalid")
        stay = "2026년 10월 6일" in text and "2026년 10월 9일" in text
        room = "객실 1개 3박" in text or "객실 1개 × 3박" in text
        amount = bool(re.search(r"JPY\s*92,001", text))
        refund_complete = cancellation and "환불 완료" in text and amount and "수수료가 부과되지 않습니다" in text
        receipts = [];pdfs=[]
        for part in message.walk():
            if part.get_content_type() != "application/pdf":
                continue
            pdf = part.get_payload(decode=True) or b""
            extracted = _extract_pdf(pdf, pypdf_python)
            pdf_sha = _sha(pdf)
            pdf_text = str(extracted["text"])
            pdfs.append({"pdf_sha256":pdf_sha,"text_sha256":_sha(pdf_text.encode()),"pages":extracted["pages"]})
            if ("TRIP.COM TRAVEL SINGAPORE PTE. LTD." in pdf_text and "전자 영수증" in pdf_text
                    and extracted["pages"] == 1 and len(pdf_text) < 700):
                required = ("2026년 3월 21일", "2026년 10월 6일", "2026년 10월 9일",
                            "야쿠시마 그린 호텔", "JPY92,001", "****8835")
                if not all(token in pdf_text for token in required):
                    continue
                if pdf_sha not in RECEIPT_PDFS:
                    raise ValueError("r44_receipt_pdf_drift")
                order = re.findall(r"예약번호:\s*(1\d{15})", pdf_text)
                if order != [ref]:
                    raise ValueError("r44_receipt_order_mismatch")
                receipt_hashes.add(pdf_sha)
                receipts.append({"sha256": pdf_sha, "pages": extracted["pages"], "coverage": "paid|stay|amount|card_suffix"})
        entry = lifecycle.setdefault(ref, {"confirmations": 0, "cancellations": 0, "refund_complete": 0,
                                           "receipts": [], "stay": True, "room": True})
        entry["confirmations"] += int(confirmation)
        entry["cancellations"] += int(cancellation)
        entry["refund_complete"] += int(refund_complete)
        entry["receipts"].extend(receipts)
        entry["stay"] = bool(entry["stay"] and stay)
        entry["room"] = bool(entry["room"] and room)
        documents.append({"file": name, "raw_sha256": expected_sha,
                          "message_id_hmac_sha256": _identity(key, "message", message_id),
                          "order_hmac_sha256": _identity(key, "order", ref),
                          "state": "confirmation" if confirmation else "cancellation",
                          "dkim_pass_header_observed": True,
                          "refund_complete": refund_complete, "receipt_count": len(receipts),
                          "pdfs":pdfs,
                          "receipt_set_sha256": _sha(_json(sorted(x["sha256"] for x in receipts)))})
    if len(lifecycle) != 5 or receipt_hashes != RECEIPT_PDFS:
        raise ValueError("r44_closed_census_invalid")
    relevant = []
    for ref, facts in lifecycle.items():
        if facts["receipts"]:
            if (facts["confirmations"], facts["cancellations"], facts["refund_complete"],
                    len(facts["receipts"]), facts["stay"], facts["room"]) != (1, 1, 1, 1, True, True):
                raise ValueError("r44_relevant_lifecycle_incomplete")
            relevant.append({"order_hmac_sha256": _identity(key, "order", ref),
                             "message_count": 2, "states": ["confirmation", "refund_complete"],
                             "amount_jpy": 92001, "stay_start": "2026-10-06", "stay_end": "2026-10-09",
                             "rooms": 1, "nights": 3,
                             "receipt_sha256": facts["receipts"][0]["sha256"]})
    if len(relevant) != 2 or len({x["order_hmac_sha256"] for x in relevant}) != 2:
        raise ValueError("r44_relevant_lifecycle_census_invalid")
    return {"artifact_type": ARTIFACT_TYPE, "schema_version": 2,
            "extractor_contract_sha256": EXTRACTOR_CONTRACT_SHA256,
            "extractor_runtime":PINNED_RUNTIME,
            "capture_claims": {"closed_query_union_count": 9, "closed_query_pages_exhausted": True,
                               "authenticated": False, "basis": "operator_gmail_session_2026-08-01"},
            "distinct_order_count": 5, "relevant_lifecycle_count": 2,
            "raw_set_sha256": _sha(_json(sorted(RAW_DOCS.values()))),
            "receipt_set_sha256": _sha(_json(sorted(RECEIPT_PDFS))),
            "documents": documents, "lifecycles": sorted(relevant, key=lambda x: x["order_hmac_sha256"]),
            "contains_sensitive_raw_values": False}


def _sealed(unsigned: dict[str, object], key: bytes) -> bytes:
    signature = hmac.new(key, DOMAIN + _json(unsigned), hashlib.sha256).hexdigest()
    return _json({**unsigned, "provenance_hmac_sha256": signature})


def create_provenance(directory: Path, key_path: Path, pypdf_python: Path, output: Path) -> dict[str, object]:
    root = _private_dir(directory)
    if key_path.parent.resolve(strict=True) != root:
        raise ValueError("r44_provenance_key_path_invalid")
    key = _read_regular(key_path.parent.resolve(strict=True), key_path.name)
    unsigned = _fresh_unsigned(root, key, pypdf_python)
    data = _sealed(unsigned, key)
    if output.parent.resolve(strict=True) != root or os.path.lexists(output):
        raise FileExistsError("r44_provenance_output_exists_or_wrong_parent")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = open_dir(root); fsync_dir(dfd); os.close(dfd)
    return {"status": "created", "provenance_sha256": _sha(data), "messages": 9, "lifecycles": 2}


def verify_provenance(directory: Path, provenance_path: Path, key_path: Path, pypdf_python: Path) -> dict[str, object]:
    root = _private_dir(directory)
    if provenance_path.parent.resolve(strict=True) != root or key_path.parent.resolve(strict=True) != root:
        raise ValueError("r44_provenance_path_invalid")
    key = _read_regular(root, key_path.name)
    actual = _read_regular(root, provenance_path.name)
    expected = _sealed(_fresh_unsigned(root, key, pypdf_python), key)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("r44_provenance_fresh_mismatch")
    parsed = json.loads(actual)
    return {"status": "valid", "provenance_sha256": _sha(actual), "provenance": parsed,
            "messages": 9, "lifecycles": 2}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Create or fresh-verify restricted R44 provenance")
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("create","verify"):
        p=sub.add_parser(name);p.add_argument("--documents-dir",type=Path,required=True)
        p.add_argument("--key-path",type=Path,required=True);p.add_argument("--pypdf-python",type=Path,required=True)
        p.add_argument("--provenance",type=Path,required=True)
    args=parser.parse_args(argv)
    result=(create_provenance(args.documents_dir,args.key_path,args.pypdf_python,args.provenance)
            if args.command=="create" else verify_provenance(args.documents_dir,args.provenance,args.key_path,args.pypdf_python))
    if "provenance" in result:result={k:v for k,v in result.items() if k!="provenance"}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())