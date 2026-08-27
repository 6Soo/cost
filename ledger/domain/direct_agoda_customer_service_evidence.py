"""R49 authenticated Agoda customer-service mapping for one residual payment.

The raw RFC822 message is a restricted external input.  Public output contains only
high-entropy content commitments and never emits the booking reference, card suffix,
amount, date, merchant, message id, recipient, or source locator.
"""
from __future__ import annotations

import csv
import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import date
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ledger.domain import direct_kb_confirmation_evidence as r45
from ledger.domain import direct_manual_group_taxonomy_evidence as r36
from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT
from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity, path_from_fd

ARTIFACT_TYPE = "r49-provider-customer-service-evidence-v1"
RULE_VERSION = "r49-signed-row-singleton-manual-ref-v1"
FILES = ("manifest.json", "mappings.csv", "proposals.csv", "exclusions.csv")
RAW_MIME_SHA256 = "840a71d24c005a074d9dcfb792084c4e42d1c06954763105b3de0c2656538b74"
RAW_MIME_BYTES = 34920
BINDING_SHA256 = "11242adc9ba5566a70e3d3ceaf34ff445ba55467b29c60626d575f5d4906190a"
PINNED_DKIM_KEY = ("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwbAhBEssB/ghzgb53lnV"
                   "kthiK/i3U4hQ9CplKrXqfWOo/na90cQHs+VCIp4k3Nj7WDctzHhMEbx8wNO3XMJW"
                   "cy66ArsVEswbjzyFeG2eYV1QqVlARHZmkxMJtaD6lTsp4VzXubYU+XMwEoQ2gE1y"
                   "LkkbCO+0JNxEBSqfLkuQN6Zr3h5K72b8jA0gtBrQOKgwtt6Vh78o9Ger+rOW5Fzw"
                   "nTj1ttEr2N3aEIHcXFQElLHY/ygwgrqDTFWWuutlLAlSKHbm+9zsYImuaVaJsOEH"
                   "WN1QZHbmWZcnuSUvL4e4sHABnV1GIjD4HJjtow59PT+Da6hIsL5c0he9Dkqa+LrI"
                   "gwIDAQAB")
MANUAL_SHA256 = r36.MANUAL_SHA256
TARGET_EVENT = "card:ac20d5a1d65733e6d49f0d8320295404f4b9262a0d15079d929a793914231f33#single"
TARGET_CONTENT_SHA256 = "855e4e2b3a74356fed1033b81cac5b510dc9edbcfddcaa811e00d9fc507910bc"
TARGET_EVENT_SET_SHA256 = "b211c98a25b7bca25e13fec7504a6de74deb14226721353ba33d85038ceeac99"
PRE_ACCEPTED_SHA256 = r45.POST_ACCEPTED_SET
PRE_RESIDUAL_SHA256 = r45.POST_RESIDUAL_SET
POST_ACCEPTED_SHA256 = "d476520330e91f9a463f004b6bad6ac2a4ef17fb6ef2bbbd10e3a0646e7d0147"
POST_RESIDUAL_SHA256 = "bb0f837d775a08b14475574da7ad1c88f7230386355628b954f9d37fc3e3778d"
TRIP_TARGET = "0620_묘코"
ACCOUNT, COST_TYPE, VAT_TAG = "숙박비", "여행원가", "불공제_해외"
DKIM_KEY_SHA256 = "eda7468dcbe00c2d9d07c698116060e9daecae175f195448248c76dddf0c02d0"
MAPPING_FIELDS = ("mapping_id", "event_key_sha256",
                  "current_event_sha256", "current_source_sha256", "current_payload_sha256",
                  "trip_row_sha256", "provider_event_cardinality",
                  "manual_reference_cardinality", "manual_date_role", "disposition",
                  "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")
PROPOSAL_FIELDS = ("proposal_id", "mapping_id", "event_key_sha256", "current_event_sha256",
                   "account", "cost_type", "vat_tag", "trip_target", "atomic_member_count",
                   "disposition", "authority_status", "posting_status", "confirmed_count",
                   "gate5_credit", "applied")
EXCLUSION_FIELDS = ("exclusion_id", "reason_code", "disposition",
                    "authority_status", "posting_status", "confirmed_count", "gate5_credit", "applied")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def _csv(fields, rows) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (str(row.get(key, "")).lower()
                              if isinstance(row.get(key), bool) else row.get(key, ""))
                         for key in fields})
    return out.getvalue().encode()


def _read_private(directory: Path) -> tuple[bytes, dict[str, object]]:
    dfd = open_dir(directory)
    try:
        dst = os.fstat(dfd)
        directory_identity = (dst.st_dev, dst.st_ino, dst.st_mode, dst.st_uid, dst.st_nlink, dst.st_ctime_ns)
        expected_names = {"message.eml", "binding.json"}
        if (not stat.S_ISDIR(dst.st_mode) or dst.st_uid != os.getuid() or
                stat.S_IMODE(dst.st_mode) != 0o700 or set(os.listdir(dfd)) != expected_names):
            raise ValueError("r49_private_directory_invalid")
        captured = {}
        identities = {}
        for name in sorted(expected_names):
            fd = open_at(dfd, name)
            try:
                before = os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                        stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
                    raise ValueError("r49_private_file_invalid")
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk: break
                    chunks.append(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                        before.st_ctime_ns, before.st_mode, before.st_uid, before.st_nlink)
            if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                            after.st_ctime_ns, after.st_mode, after.st_uid, after.st_nlink):
                raise ValueError("r49_private_file_changed")
            captured[name] = b"".join(chunks); identities[name] = identity
        data = captured["message.eml"]
        binding_raw = captured["binding.json"]
        if len(data) != RAW_MIME_BYTES or _sha(data) != RAW_MIME_SHA256 or _sha(binding_raw) != BINDING_SHA256:
            raise ValueError("r49_raw_mime_pin_invalid")
        try:
            binding = json.loads(binding_raw, object_pairs_hook=lambda pairs: _unique_pairs(pairs),
                                 parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("r49_binding_invalid") from exc
        final_dst = os.fstat(dfd)
        if ((final_dst.st_dev, final_dst.st_ino, final_dst.st_mode, final_dst.st_uid,
             final_dst.st_nlink, final_dst.st_ctime_ns) != directory_identity or
                set(os.listdir(dfd)) != expected_names):
            raise ValueError("r49_private_directory_changed")
        for name in sorted(expected_names):
            fd = open_at(dfd, name)
            try:
                st = os.fstat(fd)
                now = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                       st.st_mode, st.st_uid, st.st_nlink)
                if now != identities[name]: raise ValueError("r49_private_file_changed")
            finally: os.close(fd)
        return data, binding
    finally:
        os.close(dfd)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("r49_binding_duplicate_key")
        result[key] = value
    return result


def _relaxed_body(body: bytes) -> bytes:
    body = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")
    body = re.sub(br"[ \t]+\r\n", b"\r\n", body)
    body = re.sub(br"[ \t]+", b" ", body)
    while body.endswith(b"\r\n\r\n"): body = body[:-2]
    return b"" if body == b"\r\n" else (body if body.endswith(b"\r\n") else body + b"\r\n")


def _relaxed_header(name: str, value: str) -> bytes:
    value = re.sub(r"\r?\n", "", value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    return (name.lower().strip() + ":" + value + "\r\n").encode()


def _verify_dkim(raw: bytes, message) -> str:
    key_der = base64.b64decode(PINNED_DKIM_KEY)
    if _sha(key_der) != DKIM_KEY_SHA256: raise ValueError("r49_dkim_key_pin_invalid")
    items = list(message.raw_items())
    raw_dkim = next(value for name, value in items if name.lower() == "dkim-signature")
    tags = {key.lower(): re.sub(r"\s+", "", value) for key, value in
            re.findall(r"(?:^|;)\s*([a-z]+)\s*=\s*([^;]*)", raw_dkim, re.I)}
    if ({key: tags.get(key) for key in ("v", "a", "c", "d", "s")} !=
            {"v": "1", "a": "rsa-sha256", "c": "relaxed/relaxed", "d": "agoda.com", "s": "rsv"} or
            any(not tags.get(key) for key in ("h", "b", "bh")) or "l" in tags):
        raise ValueError("r49_dkim_contract_invalid")
    signed_names=tags["h"].lower().split(":")
    required={"content-transfer-encoding","content-type","date","from","mime-version","subject","to"}
    if not required <= set(signed_names) or signed_names.count("from") < 2 or signed_names.count("subject") < 2:
        raise ValueError("r49_dkim_signed_header_coverage_invalid")
    parts = re.split(br"\r?\n\r?\n", raw, maxsplit=1)
    if len(parts) != 2 or base64.b64encode(hashlib.sha256(_relaxed_body(parts[1])).digest()).decode() != tags["bh"]:
        raise ValueError("r49_dkim_body_invalid")
    used = set(); signed = b""
    for wanted in tags["h"].split(":"):
        for index in range(len(items)-1, -1, -1):
            if index not in used and items[index][0].lower() == wanted.lower():
                used.add(index); signed += _relaxed_header(*items[index]); break
    empty_b = re.sub(r"(?is)((?:^|;)\s*b\s*=)[^;]*", r"\1", raw_dkim)
    signed += _relaxed_header("DKIM-Signature", empty_b).rstrip(b"\r\n")
    try:
        serialization.load_der_public_key(key_der).verify(
            base64.b64decode(tags["b"]), signed, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc: raise ValueError("r49_dkim_signature_invalid") from exc
    return _sha(signed)


def _parse_provider_message(raw: bytes, binding: dict[str, object]) -> dict[str, object]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    for name in ("From", "To", "Date", "Subject", "Message-ID", "Authentication-Results", "DKIM-Signature"):
        if len(message.get_all(name, [])) != 1:
            raise ValueError("r49_mime_header_cardinality_invalid")
    sender = str(message["From"])
    auth = re.sub(r"\s+", " ", str(message["Authentication-Results"]))
    dkim = re.sub(r"\s+", " ", str(message["DKIM-Signature"]))
    if (not re.search(r"<KR-SERVICE@AGODA\.COM>", sender, re.I) or
            not auth.startswith("mx.google.com;") or
            not re.search(r"dkim=pass\s+header\.i=@agoda\.com\s+header\.s=rsv\s+header\.b=kHJupsjV", auth, re.I) or
            not re.search(r"(?:^|;)\s*d=agoda\.com\s*;", dkim, re.I) or
            not re.search(r"(?:^|;)\s*s=rsv\s*;", dkim, re.I) or
            not re.search(r"(?:^|;)\s*bh=x7x4QtecfQogFDstvuQA8g6ztJes772KuuMV54Bbtmg=\s*;", dkim) or
            not re.search(r"(?:^|;)\s*b=kHJupsjV", dkim)):
        raise ValueError("r49_transport_auth_observation_invalid")
    if message.get_content_type() != "text/html" or message.is_multipart():
        raise ValueError("r49_html_body_invalid")
    signed_header_sha = _verify_dkim(raw, message)

    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True); self.rows = []; self.row_tables=[]
            self.row = None; self.cell = None; self.tables=[];self.serial=0;self.row_table=None
        def handle_starttag(self, tag, _attrs):
            if tag.lower()=="table": self.serial+=1;self.tables.append(self.serial)
            elif tag.lower() == "tr": self.row = [];self.row_table=self.tables[-1] if self.tables else None
            elif tag.lower() == "td" and self.row is not None: self.cell = []
        def handle_data(self, data):
            if self.cell is not None: self.cell.append(data)
        def handle_endtag(self, tag):
            if tag.lower() == "td" and self.cell is not None and self.row is not None:
                self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip()); self.cell = None
            elif tag.lower() == "tr" and self.row is not None:
                self.rows.append(tuple(self.row)); self.row_tables.append(self.row_table)
                self.row = None; self.cell = None;self.row_table=None
            elif tag.lower()=="table" and self.tables:self.tables.pop()

    parser = TableParser(); parser.feed(message.get_content())
    table_rows = parser.rows
    if (not isinstance(binding, dict) or set(binding) != {"format_version", "nonce", "provider_date",
            "foreign_amount", "booking_reference", "subject_booking_reference", "manual", "event",
            "supplier_footer"} or binding.get("format_version") != 1 or
            not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("nonce", "")))):
        raise ValueError("r49_binding_invalid")
    date_value = str(binding["provider_date"]); foreign = str(binding["foreign_amount"])
    reference = str(binding["booking_reference"]); subject_reference = str(binding["subject_booking_reference"])
    target_indexes = [index for index in range(len(table_rows) - 1)
                    if parser.row_tables[index] is not None and parser.row_tables[index]==parser.row_tables[index+1] and
                    table_rows[index] == (date_value, "") and
                    table_rows[index + 1] == (foreign, reference)]
    target_pairs=[(table_rows[index],table_rows[index+1]) for index in target_indexes]
    # Row boundaries matter: the subject carries an unrelated booking id.  Only this
    # exact date row followed by its exact value/reference row may bind the event.
    normalized_subject = re.sub(r"\s+", " ", str(message["Subject"])).strip()
    if len(target_pairs) != 1 or f"Booking ID {subject_reference}" not in normalized_subject or reference in normalized_subject:
        raise ValueError("r49_target_provider_row_invalid")
    target_table=parser.row_tables[target_indexes[0]] if len(target_indexes)==1 else None
    scoped=[row for i,row in enumerate(table_rows) if parser.row_tables[i]==target_table]
    date_rows = [row for row in scoped if len(row) == 2 and re.fullmatch(r"\d{1,2}\.\d{1,2}", row[0]) and not row[1]]
    value_rows = [row for row in scoped if len(row) == 2 and re.fullmatch(r"\d+", row[0]) and row[1]]
    if len(date_rows) != 8 or len(value_rows) != 13 or len(scoped)!=30:
        raise ValueError("r49_provider_table_census_invalid")
    normalized_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", message.get_content())).strip()
    footer = binding["supplier_footer"]
    if (not isinstance(footer, dict) or footer.get("company") not in normalized_text or
            footer.get("address") not in normalized_text or "Agoda Customer Experience Group" not in normalized_text):
        raise ValueError("r49_signed_footer_invalid")
    # Bind private low-entropy facts to a random 256-bit nonce before export.
    row_binding = _sha(_json({"nonce": binding["nonce"], "date": date_value,
                             "foreign": foreign, "reference": reference}))
    return {"provider_row_sha256": row_binding,
            "provider_census_sha256": _sha(_json({"nonce": binding["nonce"],
                                                    "date_rows": date_rows, "value_rows": value_rows})),
            "signed_header_sha256": signed_header_sha,
            "transport_sha256": _sha(_json({"auth": auth, "dkim": dkim,
                                              "from": sender, "message": str(message["Message-ID"])}))}


def _manual_and_trip(binding: dict[str, object]) -> tuple[dict[str, str], str]:
    path = r36.DEFAULT_MANUAL_CSV
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("r49_manual_file_invalid")
    fd = open_nofollow(path)
    try:
        before = os.fstat(fd); chunks=[]
        while True:
            chunk=os.read(fd,1024*1024)
            if not chunk: break
            chunks.append(chunk)
        after=os.fstat(fd)
    finally: os.close(fd)
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != \
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError("r49_manual_file_changed")
    data = b"".join(chunks)
    if _sha(data) != MANUAL_SHA256:
        raise ValueError("r49_manual_pin_invalid")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    reference = str(binding["booking_reference"])
    matches = [row for row in rows if row.get("book") == reference]
    if len(matches) != 1:
        raise ValueError("r49_manual_reference_cardinality_invalid")
    row = matches[0]
    expected = dict(binding["manual"]); expected["book"] = reference
    if row != expected:
        raise ValueError("r49_manual_target_invalid")
    _validate_manual_trip_join(row)
    trips_path = Path(REPOSITORY_ROOT) / "ledger/data/trips.json"
    trips_raw = trips_path.read_bytes()
    if _sha(trips_raw) != r45.TRIPS_SHA256:
        raise ValueError("r49_trips_pin_invalid")
    trips = json.loads(trips_raw)
    target = [item for item in trips if item.get("tab") == TRIP_TARGET]
    if len(target) != 1:
        raise ValueError("r49_trip_cardinality_invalid")
    if set(target[0]) != {"tab","mm","dd","region","window"}:
        raise ValueError("r49_trip_schema_invalid")
    return row, _sha(_json(target[0]))


def _unique_event_map(rows):
    rows=list(rows); mapped={str(row["direct_event_key"]):row for row in rows}
    if len(rows)!=len(mapped): raise ValueError("r49_current_duplicate_event")
    return mapped


def _validate_manual_trip_join(row: dict[str, object]) -> None:
    if row.get("tab") != TRIP_TARGET:
        raise ValueError("r49_manual_trip_join_invalid")


def _validate_provider_event_date(binding: dict[str, object]) -> None:
    expected = binding["event"]
    date_match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", str(binding["provider_date"]))
    try:
        occurred = date.fromisoformat(str(expected["occurred_on"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("r49_provider_event_date_join_invalid") from exc
    if (date_match is None or int(date_match.group(1)) != occurred.month or
            int(date_match.group(2)) != occurred.day):
        raise ValueError("r49_provider_event_date_join_invalid")


def _live(ledger_dir: Path, binding: dict[str, object]):
    if ledger_dir.resolve() != (Path(REPOSITORY_ROOT) / "ledger").resolve():
        raise ValueError("r49_noncanonical_ledger")
    _, _, upstream_residual = r45._live(ledger_dir)
    with tempfile.TemporaryDirectory(prefix="r49-current-") as td:
        ctx = r36._context(ledger_dir, Path(td))
        db = ctx["db"]
        try:
            physical_events = list(ctx["events"])
            events = _unique_event_map(physical_events)
            if (ctx["current_event_set_sha256"], ctx["decision_scope_sha256"]) != (r45.EXPECTED_CURRENT, r45.EXPECTED_SCOPE):
                raise ValueError("r49_current_context_invalid")
            expected = binding["event"]
            _validate_provider_event_date(binding)
            candidates = [event for event in physical_events
                          if event["source_system"] == expected["source_system"] and
                          event["transaction_type"] == expected["transaction_type"] and
                          event["occurred_on"] == expected["occurred_on"] and
                          event["currency"] == expected["currency"] and
                          str(event["foreign_amount"]) == str(binding["foreign_amount"])]
            if len(candidates) != 1 or candidates[0]["direct_event_key"] != TARGET_EVENT:
                raise ValueError("r49_provider_event_cardinality_invalid")
            event = candidates[0]
            raw_rows = db.execute("SELECT payload_json FROM direct_source_records WHERE source_key=?",
                                  (expected["source_key"],)).fetchall()
            if len(raw_rows) != 1 or event["current_source_key"] != expected["source_key"]:
                raise ValueError("r49_source_record_cardinality_invalid")
            raw = raw_rows[0]
            payload = r36._strict_json(raw[0].encode(), "r49_source_payload") if raw else None
            if (event["current_event_sha256"] != TARGET_CONTENT_SHA256 or
                    int(event["signed_amount_krw"]) != int(expected["krw"]) or event["card4"] != expected["card4"] or
                    event["merchant"] != expected["merchant"] or event["posted_on"] != expected["posted_on"] or
                    event["current_source_kind"] != expected["source_kind"] or
                    event["event_role"] != expected["event_role"] or payload is None or
                    payload.get("raw_record_id") != expected["raw_record_id"] or
                    payload.get("biz") != "해외" or payload.get("cancel") is not False):
                raise ValueError("r49_target_event_contract_invalid")
        finally:
            db.close()
    universe = set(events)
    pre_accepted = (universe - upstream_residual) | set(r45.EVENTS)
    pre_residual = universe - pre_accepted
    if (len(pre_accepted), r36._event_set_sha(pre_accepted), len(pre_residual),
            r36._event_set_sha(pre_residual)) != (1531, PRE_ACCEPTED_SHA256, 3797, PRE_RESIDUAL_SHA256):
        raise ValueError("r49_pre_state_invalid")
    post_accepted = pre_accepted | {TARGET_EVENT}
    post_residual = pre_residual - {TARGET_EVENT}
    if (TARGET_EVENT not in pre_residual or r36._event_set_sha({TARGET_EVENT}) != TARGET_EVENT_SET_SHA256 or
            len(post_accepted) != 1532 or r36._event_set_sha(post_accepted) != POST_ACCEPTED_SHA256 or
            len(post_residual) != 3796 or r36._event_set_sha(post_residual) != POST_RESIDUAL_SHA256):
        raise ValueError("r49_post_state_invalid")
    return event, payload


def _build(private_dir: Path, ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger"):
    raw, binding = _read_private(private_dir)
    provider = _parse_provider_message(raw, binding)
    manual, trip_sha = _manual_and_trip(binding)
    event, payload = _live(ledger_dir, binding)
    manual_sha = _sha(_json({"nonce": binding["nonce"], "row": manual}))
    event_key_sha = _sha(TARGET_EVENT.encode())
    mapping_id = _sha(_json({"provider": provider["provider_row_sha256"], "event": event_key_sha,
                             "manual": manual_sha, "trip": trip_sha}))
    common = {"authority_status": "unattested", "posting_status": "blocked",
              "confirmed_count": 0, "gate5_credit": 0, "applied": False}
    mapping = {"mapping_id": mapping_id, "provider_row_sha256": provider["provider_row_sha256"],
               "event_key_sha256": event_key_sha, "current_event_sha256": TARGET_CONTENT_SHA256,
               "current_source_sha256": event["current_source_sha256"],
               "current_payload_sha256": _sha(_json(payload)), "manual_row_sha256": manual_sha,
               "trip_row_sha256": trip_sha, "provider_event_cardinality": 1,
               "manual_reference_cardinality": 1, "manual_date_role": "legacy_entry_date_non_authoritative",
               "disposition": "provider_row_to_event_to_manual_reference_exact", **common}
    proposal = {"proposal_id": _sha(_json({"mapping": mapping_id, "event": event_key_sha})),
                "mapping_id": mapping_id, "event_key_sha256": event_key_sha,
                "current_event_sha256": TARGET_CONTENT_SHA256, "account": ACCOUNT,
                "cost_type": COST_TYPE, "vat_tag": VAT_TAG, "trip_target": TRIP_TARGET,
                "atomic_member_count": 1, "disposition": "singleton_full_classification_review_proposal",
                **common}
    exclusion = {"provider_census_sha256": provider["provider_census_sha256"],
                 "reason_code": "non_target_rows_require_independent_service_trip_evidence",
                 "disposition": "support_only_no_broadcast", **common}
    exclusion["exclusion_id"] = _sha(_json(exclusion))
    payloads = {"mappings.csv": _csv(MAPPING_FIELDS, [mapping]),
                "proposals.csv": _csv(PROPOSAL_FIELDS, [proposal]),
                "exclusions.csv": _csv(EXCLUSION_FIELDS, [exclusion])}
    base = {"artifact_type": ARTIFACT_TYPE, "rule_version": RULE_VERSION,
            "private_binding_sha256": BINDING_SHA256, "transport_auth_observation_sha256": provider["transport_sha256"],
            "dkim_signed_headers_sha256": provider["signed_header_sha256"],
            "dkim_public_key_sha256": DKIM_KEY_SHA256,
            "transport_authentication": "offline_rsa_sha256_relaxed_verified_with_pinned_key",
            "provider_census_sha256": provider["provider_census_sha256"],
            "selected_event_set_sha256": TARGET_EVENT_SET_SHA256, "full_classification_delta": 1,
            "accepted_union": 1532, "global_residual": 3796,
            "post_admission_accepted_set_sha256": POST_ACCEPTED_SHA256,
            "post_admission_residual_set_sha256": POST_RESIDUAL_SHA256,
            "manual_raw_sha256": MANUAL_SHA256, "manual_date_authority": "not_used",
            "trip_attribution_basis": "authenticated_provider_reference_to_authoritative_manual_tab",
            "service_period_evidence": "none_asserted_or_used",
            "trip_target": TRIP_TARGET, "trip_row_sha256": trip_sha,
            "authority_status": "unattested", "posting_status": "blocked", "confirmed_count": 0,
            "gate5_credit": 0, "applied": False, "database_applied": False,
            "contains_sensitive_raw_values": False,
            "state_semantics": "classification-review delta only; no DB apply or activation authority",
            "files": {name: {"sha256": _sha(data), "rows": len(data.splitlines()) - 1}
                      for name, data in payloads.items()}}
    base["package_set_sha256"] = _sha(_json(base) + b"".join(payloads[name] for name in sorted(payloads)))
    files = {"manifest.json": _json(base), **payloads}
    _privacy_scan(files, binding)
    return base, files


def _privacy_scan(files: dict[str, bytes], binding: dict[str, object]) -> None:
    blob = b"".join(files.values()).decode()
    event = binding["event"]
    manual = binding["manual"]
    private_values = (
        binding["booking_reference"], binding["subject_booking_reference"],
        binding["foreign_amount"], event["krw"], event["card4"], event["merchant"],
        event["source_key"], event["raw_record_id"], manual["item"], manual["amount"],
    )
    forbidden = (r"card:[0-9a-f]{64}#", r"https?://", r"message-id", r"booking", r"approval",
                 r"provider_row_sha256", r"manual_row_sha256", r"raw_mime_sha256",
                 *(re.escape(str(value)) for value in private_values if str(value)))
    if any(re.search(pattern, blob, re.I) for pattern in forbidden):
        raise ValueError("r49_public_privacy_violation")


def _capture_dirfd(dirfd: int) -> dict[str, bytes]:
    dst = os.fstat(dirfd)
    if (not stat.S_ISDIR(dst.st_mode) or stat.S_IMODE(dst.st_mode) != 0o700 or
            dst.st_uid != os.getuid() or set(os.listdir(dirfd)) != set(FILES)):
        raise ValueError("r49_package_shape_invalid")
    result = {}
    for name in FILES:
        fd = open_at(dirfd, name)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
                raise ValueError("r49_package_shape_invalid")
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk: break
                chunks.append(chunk)
            after = os.fstat(fd)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,before.st_ctime_ns,
                 before.st_mode,before.st_uid,before.st_nlink) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,after.st_ctime_ns,
                     after.st_mode,after.st_uid,after.st_nlink)):
                raise ValueError("r49_package_changed_during_read")
            result[name] = b"".join(chunks)
        finally:
            os.close(fd)
    return result


class PublicationDurabilityError(OSError):
    def __init__(self, output, package_sha, parent_identity, target_identity):
        super().__init__("r49_published_durability_unknown"); self.output=output
        self.package_set_sha256=package_sha; self.published=True; self.parent_path=output.parent
        self.target_name=output.name; self.parent_identity=parent_identity; self.target_identity=target_identity


class PublicationIntegrityError(OSError):
    def __init__(self, output, package_sha, parent_identity, target_identity):
        super().__init__("r49_published_integrity_invalid"); self.output=output
        self.package_set_sha256=package_sha; self.published=True; self.parent_path=output.parent
        self.target_name=output.name; self.parent_identity=parent_identity; self.target_identity=target_identity


def build_agoda_customer_service_evidence(private_dir: Path, output: Path | None = None,
                                           ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger"):
    manifest, files = _build(private_dir, ledger_dir)
    if output is None:
        return {"manifest": manifest, "files": files}
    if output.parent.is_symlink():
        raise ValueError("r49_output_parent_symlink")
    out = output.resolve()
    if Path(REPOSITORY_ROOT).resolve() in (out, *out.parents):
        raise ValueError("r49_output_inside_repository")
    if os.path.lexists(out):
        raise FileExistsError(out)
    parentfd = open_dir(output.parent)
    parent_identity = r45._identity(os.fstat(parentfd))
    if r45._identity(os.stat(output.parent, follow_symlinks=False)) != parent_identity:
        os.close(parentfd); raise ValueError("r49_parent_identity_changed")
    stage = None; stagefd=None; targetfd=None; published=False; target_identity=None
    try:
        stage = Path(tempfile.mkdtemp(prefix=".r49-stage-", dir=path_from_fd(parentfd)))
        stage_name = stage.name
        os.chmod(stage, 0o700)
        stagefd = open_at(parentfd, stage_name)
        try:
            for name, data in files.items():
                fd = open_at(stagefd, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                try:
                    view = memoryview(data)
                    while view:
                        written=os.write(fd, view)
                        if written <= 0: raise OSError("r49_short_write_zero")
                        view = view[written:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
            fsync_dir(stagefd)
            if _capture_dirfd(stagefd) != files:
                raise ValueError("r49_stage_verify_failed")
        finally: pass
        if (r45._identity(os.fstat(parentfd)) != parent_identity or
                r45._identity(os.stat(output.parent, follow_symlinks=False)) != parent_identity):
            raise ValueError("r49_parent_identity_changed")
        rename_noreplace_at(parentfd, stage_name, out.name)
        published=True; stage=None; os.close(stagefd);stagefd=None
        targetfd = open_at(parentfd, out.name)
        target_identity=r45._identity(os.fstat(targetfd))
        try:
            if _capture_dirfd(targetfd) != files:
                raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
            checkfd=open_at(parentfd, out.name)
            try:
                if r45._identity(os.fstat(checkfd)) != target_identity or _capture_dirfd(checkfd)!=files:
                    raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
            finally: os.close(checkfd)
            try: fsync_dir(parentfd)
            except OSError as exc: raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_identity,target_identity) from exc
            if (r45._identity(os.stat(output.parent,follow_symlinks=False)) != parent_identity or
                    r45._identity(os.fstat(targetfd)) != target_identity):
                raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
            if _capture_dirfd(targetfd) != files:
                raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
            checkfd=open_at(parentfd, out.name)
            try:
                if r45._identity(os.fstat(checkfd)) != target_identity or _capture_dirfd(checkfd)!=files:
                    raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_identity,target_identity)
            finally: os.close(checkfd)
        finally: os.close(targetfd);targetfd=None
    finally:
        if targetfd is not None: os.close(targetfd)
        if stagefd is not None: os.close(stagefd)
        if not published and stage is not None and stage.exists():
            shutil.rmtree(stage)
        os.close(parentfd)
    return {"manifest": manifest, "output": str(out)}


def verify_agoda_customer_service_evidence(directory: Path, private_dir: Path,
                                            ledger_dir: Path = Path(REPOSITORY_ROOT) / "ledger"):
    manifest, expected = _build(private_dir, ledger_dir)
    expected_identity=r45._identity(os.stat(directory,follow_symlinks=False))
    directoryfd = open_dir(directory)
    try:
        actual = _capture_dirfd(directoryfd)
        if r45._identity(os.fstat(directoryfd)) != expected_identity or r45._identity(os.stat(directory,follow_symlinks=False)) != expected_identity:
            raise ValueError("r49_verify_path_identity_changed")
    finally:
        os.close(directoryfd)
    if actual != expected:
        raise ValueError("r49_package_or_context_mismatch")
    return {"status": "valid", "package_set_sha256": manifest["package_set_sha256"],
            "proposals": 1, "accepted_union": 1532, "global_residual": 3796}


def reconcile_publication(error, private_dir: Path, ledger_dir: Path = Path(REPOSITORY_ROOT)/"ledger"):
    if not isinstance(error,(PublicationDurabilityError,PublicationIntegrityError)):
        raise ValueError("r49_reconcile_state_invalid")
    manifest,expected=_build(private_dir,ledger_dir)
    pfd=open_dir(error.parent_path)
    try:
        if r45._identity(os.fstat(pfd)) != error.parent_identity: raise ValueError("r49_reconcile_parent_identity_mismatch")
        if r45._identity(os.stat(error.parent_path,follow_symlinks=False)) != error.parent_identity:
            raise ValueError("r49_reconcile_parent_identity_mismatch")
        tfd=open_at(pfd, error.target_name)
        try:
            if r45._identity(os.fstat(tfd)) != error.target_identity or _capture_dirfd(tfd)!=expected:
                raise ValueError("r49_reconcile_target_identity_mismatch")
            fsync_dir(pfd)
            if (r45._identity(os.fstat(pfd)) != error.parent_identity or
                    r45._identity(os.stat(error.parent_path,follow_symlinks=False)) != error.parent_identity or
                    r45._identity(os.fstat(tfd)) != error.target_identity or _capture_dirfd(tfd)!=expected):
                raise ValueError("r49_reconcile_identity_changed")
            checkfd=open_at(pfd, error.target_name)
            try:
                if r45._identity(os.fstat(checkfd)) != error.target_identity or _capture_dirfd(checkfd)!=expected:
                    raise ValueError("r49_reconcile_identity_changed")
            finally: os.close(checkfd)
        finally: os.close(tfd)
    finally: os.close(pfd)
    if manifest["package_set_sha256"] != error.package_set_sha256: raise ValueError("r49_reconcile_package_mismatch")
    return {"status":"valid","package_set_sha256":manifest["package_set_sha256"],"published":True,"durable":True}