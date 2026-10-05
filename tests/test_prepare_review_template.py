"""Tests for tools/prepare_review_template.py.

Two layers:

* Plumbing tests, using a controlled in-memory stand-in for
  ``webapp.review_template`` injected into ``sys.modules``. Nothing is
  written outside each test's own temporary directory, and no source file
  is ever edited or stubbed on disk.
* End-to-end tests against the real ``webapp.review_template`` core over
  synthetic legacy nine-column manifests.

The core is a required product of these end-to-end tests, not an optional
one: they import it directly and fail when it is missing or broken, so the
shell can never be reported green while the real product is absent. Until
the core is delivered those end-to-end tests fail on import and the
plumbing tests still run; nothing is skipped.
"""

from __future__ import annotations

import csv
import errno
import hashlib
import io
import json
import os
import subprocess
import sys
import types
from contextlib import redirect_stderr, redirect_stdout

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
CLI_PATH = os.path.join(TOOLS_DIR, "prepare_review_template.py")

from tools import prepare_review_template as cli  # noqa: E402

SNAPSHOT_SHA = "a" * 64
SNAPSHOT_BYTES = b"synthetic-sealed-snapshot-bytes\n"
MANIFEST_SHA = "b" * 64

SENSITIVE_REF = "src-ref-customer-secret-4242"
SENSITIVE_NOTE = "note-must-not-leak@example.com"
SENSITIVE_DATE = "2026-04-01"
SENSITIVE_AMOUNT = "987654321"

LEGACY_HEADERS = (
    "source_ref_snapshot_only",
    "source_date",
    "source_amount",
    "candidate_count",
    "candidate_transaction_keys",
    "candidate_date_fields",
    "disposition",
    "reviewer_decision",
    "review_note",
)

TEMPLATE_HEADERS = LEGACY_HEADERS + (
    "review_schema_version",
    "review_snapshot_sha256",
)

STUB_CSV_TEXT = (
    "source_ref_snapshot_only,source_date,source_amount,candidate_count,"
    "candidate_transaction_keys,candidate_date_fields,disposition,"
    "reviewer_decision,review_note,review_schema_version,"
    "review_snapshot_sha256\r\n"
    f"src-ref-001,{SENSITIVE_DATE},{SENSITIVE_AMOUNT},2,"
    '["tx-001","tx-002"],["2026-04-01"],candidate_review_required,,,'
    f"review-csv-v1,{SNAPSHOT_SHA}\r\n"
).replace("\r\n", "\n")


# --------------------------------------------------------------- fixtures

class _StubTemplateError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or f"refused: {code}")
        self.code = code


_NO_RAISE = object()


def _make_core(*, csv_text=STUB_CSV_TEXT, counts=None, row_count=1,
               raise_code=_NO_RAISE, raise_message="", result="default",
               hook=None):
    """Build a fake webapp.review_template module for sys.modules injection."""
    module = types.ModuleType("webapp.review_template")
    module.TemplateError = _StubTemplateError
    seen: dict = {}

    def build_blank_review_template(legacy_csv_text, snapshot_sha256):
        seen["text"] = legacy_csv_text
        seen["snapshot_sha256"] = snapshot_sha256
        if hook is not None:
            hook()
        if raise_code is not _NO_RAISE:
            raise _StubTemplateError(raise_code, raise_message) \
                from RuntimeError(raise_message)
        if result == "non_dict":
            return ["not", "a", "mapping"]
        if result == "csv_not_text":
            return {"csv_text": None, "counts": counts or _counts(),
                    "row_count": row_count}
        if result == "row_count_bool":
            return {"csv_text": csv_text, "counts": counts or _counts(),
                    "row_count": True}
        if result == "counts_not_dict":
            return {"csv_text": csv_text, "counts": ["nope"],
                    "row_count": row_count}
        if result == "counts_missing_key":
            return {"csv_text": csv_text, "counts": {"approved": 0},
                    "row_count": row_count}
        return {"csv_text": csv_text, "counts": counts or _counts(),
                "row_count": row_count, "notes": "not part of the contract"}

    module.build_blank_review_template = build_blank_review_template
    module.calls = seen
    return module


def _counts():
    return {"approved": 0, "rejected": 0, "incomplete": 1}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _legacy_row(ref, *, keys=("tx-001",),
                disposition="candidate_review_required",
                decision="", note=""):
    return {
        "source_ref_snapshot_only": ref,
        "source_date": SENSITIVE_DATE,
        "source_amount": SENSITIVE_AMOUNT,
        "candidate_count": str(len(keys)),
        "candidate_transaction_keys": json.dumps(list(keys)),
        "candidate_date_fields": json.dumps([SENSITIVE_DATE]),
        "disposition": disposition,
        "reviewer_decision": decision,
        "review_note": note,
    }


def _render_legacy_csv(rows, headers=LEGACY_HEADERS) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers),
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue().encode("utf-8")


class _Inputs:
    """The two verified input files of one test."""

    def __init__(self, snapshot_path, snapshot_sha, manifest_path,
                 manifest_sha):
        self.snapshot_path = snapshot_path
        self.snapshot_sha = snapshot_sha
        self.manifest_path = manifest_path
        self.manifest_sha = manifest_sha

    def argv(self, output=None):
        argv = [
            "--snapshot", self.snapshot_path,
            "--snapshot-sha256", self.snapshot_sha,
            "--manifest", self.manifest_path,
            "--manifest-sha256", self.manifest_sha,
        ]
        if output is not None:
            argv += ["--output", output]
        return argv


def _write_inputs(tmp_path, manifest_bytes=None, snapshot_bytes=SNAPSHOT_BYTES,
                  manifest_sha=None, snapshot_sha=None) -> _Inputs:
    default_rows = [_legacy_row("src-ref-001", note=SENSITIVE_NOTE)]
    manifest_bytes = manifest_bytes if manifest_bytes is not None \
        else _render_legacy_csv(default_rows)
    snapshot_path = tmp_path / "snapshot.bin"
    snapshot_path.write_bytes(snapshot_bytes)
    manifest_path = tmp_path / "legacy_manifest.csv"
    manifest_path.write_bytes(manifest_bytes)
    return _Inputs(
        str(snapshot_path),
        snapshot_sha if snapshot_sha is not None else _sha256(snapshot_bytes),
        str(manifest_path),
        manifest_sha if manifest_sha is not None else _sha256(manifest_bytes),
    )


def _install(monkeypatch, core) -> None:
    monkeypatch.setitem(sys.modules, "webapp.review_template", core)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _listdir(directory):
    return sorted(os.listdir(directory))


def _temp_leftovers(directory):
    return [name for name in os.listdir(directory)
            if name.startswith(cli._TEMP_PREFIX)]


class _FakeStdout:
    """stdout stand-in exposing a real binary buffer, like a console pipe."""

    def __init__(self):
        self.buffer = io.BytesIO()
        self.text = ""

    def write(self, value):
        self.text += value
        return len(value)

    def flush(self):
        pass


# -------------------------------------------------------- default stdout

def test_default_mode_prints_only_the_csv_and_writes_no_file(monkeypatch,
                                                             tmp_path):
    core = _make_core()
    _install(monkeypatch, core)
    inputs = _write_inputs(tmp_path)
    before = _listdir(tmp_path)

    code, out, err = _run(inputs.argv())

    assert code == 0
    assert out == STUB_CSV_TEXT
    assert err == ""
    assert _listdir(tmp_path) == before
    assert _temp_leftovers(tmp_path) == []
    assert core.calls["text"].startswith("source_ref_snapshot_only,")


def test_default_mode_writes_exact_utf8_bytes_for_non_ascii(monkeypatch,
                                                           tmp_path):
    csv_text = "ref,note\n" + f"src-ref-001,{SENSITIVE_NOTE}\n"
    _install(monkeypatch, _make_core(csv_text=csv_text,
                                     counts={"approved": 0, "rejected": 0,
                                             "incomplete": 1}))
    inputs = _write_inputs(tmp_path)
    stream = _FakeStdout()

    with redirect_stdout(stream), redirect_stderr(io.StringIO()):
        code = cli.main(inputs.argv())

    assert code == 0
    assert stream.text == ""
    assert stream.buffer.getvalue() == csv_text.encode("utf-8")
    assert not stream.buffer.getvalue().startswith(b"\xef\xbb\xbf")


def test_default_mode_keeps_core_line_endings_verbatim(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)

    code, out, _ = _run(inputs.argv())

    assert code == 0
    assert "\r\n" not in out
    assert out.endswith("\n")
    assert out == STUB_CSV_TEXT


# ------------------------------------------------------------- file mode

def test_file_mode_publishes_and_reports_exact_metadata(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core(row_count=1))
    inputs = _write_inputs(tmp_path)
    destination = str(tmp_path / "review_template.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert set(payload) == {"counts", "manifest_sha256", "row_count",
                            "snapshot_sha256", "template_sha256"}
    assert payload["counts"] == {"approved": 0, "rejected": 0, "incomplete": 1}
    assert payload["row_count"] == 1
    assert payload["snapshot_sha256"] == inputs.snapshot_sha
    assert payload["manifest_sha256"] == inputs.manifest_sha
    with open(destination, "rb") as handle:
        written = handle.read()
    assert written == STUB_CSV_TEXT.encode("utf-8")
    assert not written.startswith(b"\xef\xbb\xbf")
    assert payload["template_sha256"] == _sha256(written)
    assert out.endswith("\n")
    assert _temp_leftovers(tmp_path) == []
    assert _listdir(tmp_path) == ["legacy_manifest.csv", "review_template.csv",
                                  "snapshot.bin"]


def test_file_mode_bytes_match_default_mode_bytes(monkeypatch, tmp_path):
    inputs = _write_inputs(tmp_path)
    _install(monkeypatch, _make_core())
    printed_code, printed, _ = _run(inputs.argv())
    _install(monkeypatch, _make_core())
    destination = str(tmp_path / "published.csv")
    published_code, _, _ = _run(inputs.argv(output=destination))

    assert printed_code == published_code == 0
    with open(destination, "rb") as handle:
        assert handle.read() == printed.encode("utf-8")


def test_repeat_runs_are_byte_and_metadata_identical(monkeypatch, tmp_path):
    inputs = _write_inputs(tmp_path)
    first = str(tmp_path / "first.csv")
    second = str(tmp_path / "second.csv")

    _install(monkeypatch, _make_core())
    code_one, out_one, _ = _run(inputs.argv(output=first))
    _install(monkeypatch, _make_core())
    code_two, out_two, _ = _run(inputs.argv(output=second))

    assert code_one == code_two == 0
    assert out_one == out_two
    with open(first, "rb") as handle_one, open(second, "rb") as handle_two:
        assert handle_one.read() == handle_two.read()


def test_output_directory_is_never_created(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    missing = str(tmp_path / "no_such_dir" / "template.csv")

    code, out, err = _run(inputs.argv(output=missing))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "IO_ERROR"}}
    assert err.strip() == "IO_ERROR"
    assert not os.path.exists(tmp_path / "no_such_dir")
    assert missing not in out + err


# ------------------------------------------------------- input verification

@pytest.mark.parametrize("which", ["snapshot", "manifest"])
def test_digest_mismatch_is_input_hash_mismatch(monkeypatch, tmp_path, which):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    wrong = "c" * 64
    if which == "snapshot":
        inputs.snapshot_sha = wrong
    else:
        inputs.manifest_sha = wrong
    destination = str(tmp_path / "out.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_HASH_MISMATCH"}}
    assert err.strip() == "INPUT_HASH_MISMATCH"
    assert not os.path.exists(destination)
    assert _temp_leftovers(tmp_path) == []


def test_declared_digest_is_not_normalized(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    inputs.snapshot_sha = _sha256(SNAPSHOT_BYTES).upper()

    code, out, _ = _run(inputs.argv())

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_HASH_MISMATCH"}}


@pytest.mark.parametrize("bad", ["abc", "a" * 63, "a" * 65, " " + "a" * 63,
                                 "a" * 64 + " ", "z" * 64, "A" * 64 + "\n"])
def test_malformed_digests_are_refused(monkeypatch, tmp_path, bad):
    core = _make_core()
    _install(monkeypatch, core)
    inputs = _write_inputs(tmp_path)

    code_a, out_a, err_a = _run(["--snapshot", inputs.snapshot_path,
                                 "--snapshot-sha256", bad,
                                 "--manifest", inputs.manifest_path,
                                 "--manifest-sha256",
                                 inputs.manifest_sha])
    code_b, out_b, err_b = _run(["--snapshot", inputs.snapshot_path,
                                 "--snapshot-sha256", inputs.snapshot_sha,
                                 "--manifest", inputs.manifest_path,
                                 "--manifest-sha256", bad])

    assert (code_a, code_b) == (2, 2)
    assert json.loads(out_a) == {"error": {"code": "INVALID_SNAPSHOT_SHA256"}}
    assert json.loads(out_b) == {"error": {"code": "INVALID_MANIFEST_SHA256"}}
    assert err_a.strip() == "INVALID_SNAPSHOT_SHA256"
    assert err_b.strip() == "INVALID_MANIFEST_SHA256"
    assert core.calls == {}


def test_fingerprint_change_during_read_is_a_change_not_a_hash(monkeypatch,
                                                               tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    real_stat = os.stat
    calls = {"manifest": 0}

    def drifting_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if os.path.abspath(os.fspath(path)) == \
                os.path.abspath(inputs.manifest_path):
            calls["manifest"] += 1
            if calls["manifest"] == 2:
                # Identical bytes, identical digest, moved mtime only.
                return _StatView(info, mtime_ns=info.st_mtime_ns + 1)
        return info

    monkeypatch.setattr(cli, "_stat", drifting_stat)
    destination = str(tmp_path / "out.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    assert err.strip() == "INPUT_CHANGED_DURING_READ"
    assert not os.path.exists(destination)
    assert _temp_leftovers(tmp_path) == []


class _StatView:
    """stat stand-in exposing only what the fingerprint check reads."""

    def __init__(self, info, mtime_ns=None, size=None):
        self.st_dev = info.st_dev
        self.st_ino = info.st_ino
        self.st_size = info.st_size if size is None else size
        self.st_mtime_ns = info.st_mtime_ns if mtime_ns is None else mtime_ns


def test_input_mutated_after_core_before_publish_is_refused(monkeypatch,
                                                            tmp_path):
    manifest_bytes = _render_legacy_csv([_legacy_row("src-ref-001")])
    inputs = _write_inputs(tmp_path, manifest_bytes=manifest_bytes)

    def rewrite_same_bytes():
        # The core has already produced its result, so this is exactly the
        # publish-time revalidation window: the manifest now carries a byte
        # the verified digest never covered.
        with open(inputs.manifest_path, "ab") as handle:
            handle.write(b"\n")

    _install(monkeypatch, _make_core(hook=rewrite_same_bytes))
    destination = str(tmp_path / "out.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    assert err.strip() == "INPUT_CHANGED_DURING_READ"
    assert not os.path.exists(destination)
    assert _temp_leftovers(tmp_path) == []


def test_missing_input_and_directory_input_are_io_errors(monkeypatch,
                                                         tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    missing = str(tmp_path / "absent.csv")

    code, out, err = _run(["--snapshot", missing,
                           "--snapshot-sha256", inputs.snapshot_sha,
                           "--manifest", inputs.manifest_path,
                           "--manifest-sha256", inputs.manifest_sha])
    assert code == 2
    assert json.loads(out) == {"error": {"code": "IO_ERROR"}}

    code, out, _ = _run(["--snapshot", str(tmp_path),
                         "--snapshot-sha256", inputs.snapshot_sha,
                         "--manifest", inputs.manifest_path,
                         "--manifest-sha256", inputs.manifest_sha])
    assert code == 2
    assert json.loads(out) == {"error": {"code": "IO_ERROR"}}
    assert err.strip() == "IO_ERROR"


def test_manifest_that_is_not_utf8_is_an_io_error(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    bad = b"\xff\xfe\x00legacy"
    inputs = _write_inputs(tmp_path, manifest_bytes=bad)

    code, out, err = _run(inputs.argv())

    assert code == 2
    assert json.loads(out) == {"error": {"code": "IO_ERROR"}}
    assert err.strip() == "IO_ERROR"


def test_manifest_bom_is_tolerated_and_snapshot_is_never_decoded(monkeypatch,
                                                                 tmp_path):
    manifest_bytes = _render_legacy_csv([_legacy_row(SENSITIVE_REF)])
    inputs = _write_inputs(tmp_path, manifest_bytes=manifest_bytes)
    bom_path = tmp_path / "legacy_manifest.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + manifest_bytes)
    inputs.manifest_sha = _sha256(b"\xef\xbb\xbf" + manifest_bytes)
    core = _make_core()
    _install(monkeypatch, core)

    code, out, _ = _run(inputs.argv())

    assert code == 0
    assert not core.calls["text"].startswith("\ufeff")
    assert core.calls["text"].startswith("source_ref_snapshot_only,")
    # The sealed snapshot is a digest binding only: its bytes never reach the
    # core and the declared digest is what gets passed on.
    assert core.calls["snapshot_sha256"] == inputs.snapshot_sha
    assert SNAPSHOT_BYTES.decode("utf-8").strip() not in core.calls["text"]


# ------------------------------------------------------------ destinations

def test_existing_destination_file_is_refused(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    destination = tmp_path / "out.csv"
    destination.write_text("sentinel\n", encoding="utf-8")

    code, out, err = _run(inputs.argv(output=str(destination)))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EXISTS"}}
    assert err.strip() == "OUTPUT_EXISTS"
    assert destination.read_text(encoding="utf-8") == "sentinel\n"
    assert _temp_leftovers(tmp_path) == []


def test_existing_destination_directory_is_refused(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    destination = tmp_path / "out.csv"
    destination.mkdir()

    code, out, _ = _run(inputs.argv(output=str(destination)))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EXISTS"}}


def test_existing_destination_symlink_is_refused(monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    target = tmp_path / "target.csv"
    target.write_text("sentinel\n", encoding="utf-8")
    destination = tmp_path / "out.csv"
    try:
        os.symlink(target, destination)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is not permitted here: "
                    f"{exc.__class__.__name__}")

    code, out, _ = _run(inputs.argv(output=str(destination)))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EXISTS"}}
    assert os.path.islink(destination)
    assert target.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.parametrize("which", ["snapshot", "manifest"])
def test_destination_equal_to_an_input_path_is_refused(monkeypatch, tmp_path,
                                                        which):
    core = _make_core()
    _install(monkeypatch, core)
    inputs = _write_inputs(tmp_path)
    before = _sha256(SNAPSHOT_BYTES)
    target = inputs.snapshot_path if which == "snapshot" \
        else inputs.manifest_path

    code, out, err = _run(inputs.argv(output=target))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EQUALS_INPUT"}}
    assert err.strip() == "OUTPUT_EQUALS_INPUT"
    with open(inputs.snapshot_path, "rb") as handle:
        assert _sha256(handle.read()) == before
    with open(inputs.manifest_path, "rb") as handle:
        assert _sha256(handle.read()) == inputs.manifest_sha
    assert _temp_leftovers(tmp_path) == []


def test_destination_aliasing_an_input_by_hardlink_is_refused(monkeypatch,
                                                               tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    alias = str(tmp_path / "snapshot_alias.bin")
    try:
        os.link(inputs.snapshot_path, alias)
    except OSError as exc:
        pytest.skip(f"hardlink creation is not permitted here: {exc.errno}")

    code, out, err = _run(inputs.argv(output=alias))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EQUALS_INPUT"}}
    with open(alias, "rb") as handle:
        assert handle.read() == SNAPSHOT_BYTES


def test_destination_aliasing_an_input_through_a_dot_path_is_refused(
        monkeypatch, tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    manifest_dir = os.path.dirname(inputs.manifest_path)
    indirect = os.path.join(manifest_dir, "..", os.path.basename(tmp_path),
                            "legacy_manifest.csv")

    code, out, _ = _run(inputs.argv(output=indirect))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EQUALS_INPUT"}}


# -------------------------------------------------------- atomic publish

def test_link_race_that_loses_to_another_writer_is_output_exists(monkeypatch,
                                                                 tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    destination = str(tmp_path / "out.csv")
    winner_bytes = b"written by another process\n"

    def racing_link(source, target):
        with open(target, "wb") as handle:
            handle.write(winner_bytes)
        raise FileExistsError(errno.EEXIST, "lost the race", target)

    monkeypatch.setattr(cli, "_link", racing_link)

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "OUTPUT_EXISTS"}}
    assert err.strip() == "OUTPUT_EXISTS"
    with open(destination, "rb") as handle:
        assert handle.read() == winner_bytes
    assert _temp_leftovers(tmp_path) == []


def test_unsupported_hardlink_refuses_without_any_fallback(monkeypatch,
                                                           tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    destination = str(tmp_path / "out.csv")
    attempts = []

    def unsupported_link(source, target):
        attempts.append(target)
        raise OSError(errno.EPERM, "operation not permitted", target)

    monkeypatch.setattr(cli, "_link", unsupported_link)

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "ATOMIC_PUBLISH_UNAVAILABLE"}}
    assert err.strip() == "ATOMIC_PUBLISH_UNAVAILABLE"
    assert len(attempts) == 1
    assert not os.path.exists(destination)
    assert _listdir(tmp_path) == ["legacy_manifest.csv", "snapshot.bin"]
    assert _temp_leftovers(tmp_path) == []


def test_link_that_does_not_create_the_destination_is_refused(monkeypatch,
                                                              tmp_path):
    _install(monkeypatch, _make_core())
    inputs = _write_inputs(tmp_path)
    destination = str(tmp_path / "out.csv")
    monkeypatch.setattr(cli, "_link", lambda source, target: None)

    code, out, _ = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "ATOMIC_PUBLISH_UNAVAILABLE"}}
    assert not os.path.exists(destination)
    assert _temp_leftovers(tmp_path) == []


def test_post_publish_input_change_removes_only_our_own_output(monkeypatch,
                                                                tmp_path):
    manifest_bytes = _render_legacy_csv([_legacy_row("src-ref-001")])
    inputs = _write_inputs(tmp_path, manifest_bytes=manifest_bytes)
    real_link = os.link

    def link_then_drift(source, target):
        real_link(source, target)
        with open(inputs.manifest_path, "ab") as handle:
            handle.write(b"\n")

    _install(monkeypatch, _make_core())
    monkeypatch.setattr(cli, "_link", link_then_drift)
    destination = str(tmp_path / "out.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    assert err.strip() == "INPUT_CHANGED_DURING_READ"
    assert not os.path.exists(destination)
    assert _listdir(tmp_path) == ["legacy_manifest.csv", "snapshot.bin"]


def test_post_publish_change_never_deletes_another_process_replacement(
        monkeypatch, tmp_path):
    manifest_bytes = _render_legacy_csv([_legacy_row("src-ref-001")])
    inputs = _write_inputs(tmp_path, manifest_bytes=manifest_bytes)
    real_link = os.link
    replacement = b"replacement written by another process\n"

    def link_then_replace(source, target):
        real_link(source, target)
        os.unlink(target)
        with open(target, "wb") as handle:
            handle.write(replacement)
        with open(inputs.manifest_path, "ab") as handle:
            handle.write(b"\n")

    _install(monkeypatch, _make_core())
    monkeypatch.setattr(cli, "_link", link_then_replace)
    destination = str(tmp_path / "out.csv")

    code, out, _ = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    with open(destination, "rb") as handle:
        assert handle.read() == replacement
    assert _temp_leftovers(tmp_path) == []


# ----------------------------------------------------------- core refusals

def test_core_error_code_is_passed_through_with_code_only_diagnostics(
        monkeypatch, tmp_path):
    _install(monkeypatch, _make_core(
        raise_code="LEGACY_APPROVAL_PRESENT",
        raise_message=f"{SENSITIVE_REF} {SENSITIVE_NOTE} secret"))
    inputs = _write_inputs(tmp_path)
    destination = str(tmp_path / "out.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "LEGACY_APPROVAL_PRESENT"}}
    assert err == "LEGACY_APPROVAL_PRESENT\n"
    assert not os.path.exists(destination)
    for absent in (SENSITIVE_REF, SENSITIVE_NOTE, str(tmp_path), "Traceback",
                   inputs.manifest_path):
        assert absent not in out + err
    assert _temp_leftovers(tmp_path) == []


@pytest.mark.parametrize("code", ["NOT_A_REAL_CODE", "legacy_schema_mismatch",
                                  "", None, 7])
def test_unknown_core_code_is_internal_error(monkeypatch, tmp_path, code):
    _install(monkeypatch,
             _make_core(raise_code=code, raise_message="leaky row"))
    inputs = _write_inputs(tmp_path)

    exit_code, out, err = _run(inputs.argv())

    assert exit_code == 2
    assert json.loads(out) == {"error": {"code": "INTERNAL_ERROR"}}
    assert err == "INTERNAL_ERROR\n"
    assert "leaky" not in out + err


@pytest.mark.parametrize("result", ["non_dict", "csv_not_text",
                                    "row_count_bool", "counts_not_dict",
                                    "counts_missing_key"])
def test_unusable_core_result_is_internal_error(monkeypatch, tmp_path, result):
    _install(monkeypatch, _make_core(result=result))
    inputs = _write_inputs(tmp_path)

    code, out, err = _run(inputs.argv(output=str(tmp_path / "out.csv")))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INTERNAL_ERROR"}}
    assert err == "INTERNAL_ERROR\n"
    assert not os.path.exists(tmp_path / "out.csv")


def test_missing_core_module_is_internal_error(monkeypatch, tmp_path):
    def blocked_core():
        raise ModuleNotFoundError("webapp.review_template")

    monkeypatch.setattr(cli, "_load_core", blocked_core)
    inputs = _write_inputs(tmp_path)

    code, out, err = _run(inputs.argv())

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INTERNAL_ERROR"}}
    assert err == "INTERNAL_ERROR\n"
    assert "review_template" not in out + err
    assert "Traceback" not in out + err


# ------------------------------------------------------------- arguments

@pytest.mark.parametrize("argv", [
    [],
    ["--snapshot", "s.bin"],
    ["--snapshot", "s.bin", "--snapshot-sha256", "a" * 64],
    ["--snapshot", "s.bin", "--snapshot-sha256", "a" * 64,
     "--manifest", "m.csv"],
    ["--snapshot", "s.bin", "--snapshot-sha256", "a" * 64,
     "--manifest", "m.csv", "--manifest-sha256", "b" * 64, "--unknown", "x"],
])
def test_argument_failures_exit_two_without_usage_echo(monkeypatch, tmp_path,
                                                       argv):
    core = _make_core()
    _install(monkeypatch, core)
    inputs = _write_inputs(tmp_path)
    resolved = []
    for part in argv:
        resolved.append({
            "s.bin": inputs.snapshot_path,
            "m.csv": inputs.manifest_path,
        }.get(part, part))

    code, out, err = _run(resolved)

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INVALID_ARGUMENT"}}
    assert err == "INVALID_ARGUMENT\n"
    assert "usage:" not in (out + err).lower()
    assert inputs.snapshot_path not in out + err
    assert inputs.manifest_path not in out + err
    assert core.calls == {}
    assert _listdir(tmp_path) == ["legacy_manifest.csv", "snapshot.bin"]


def test_empty_output_path_is_an_argument_error(monkeypatch, tmp_path):
    core = _make_core()
    _install(monkeypatch, core)
    inputs = _write_inputs(tmp_path)

    code, out, err = _run(inputs.argv(output=""))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INVALID_ARGUMENT"}}
    assert err == "INVALID_ARGUMENT\n"
    assert core.calls == {}
    assert _listdir(tmp_path) == ["legacy_manifest.csv", "snapshot.bin"]


def test_privacy_of_error_paths_keeps_paths_and_row_text_inside(monkeypatch,
                                                                tmp_path):
    manifest_bytes = _render_legacy_csv(
        [_legacy_row(SENSITIVE_REF, note=SENSITIVE_NOTE)])
    inputs = _write_inputs(tmp_path, manifest_bytes=manifest_bytes)
    inputs.manifest_sha = "d" * 64
    _install(monkeypatch, _make_core())

    code, out, err = _run(inputs.argv(output=str(tmp_path / "out.csv")))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_HASH_MISMATCH"}}
    for absent in (SENSITIVE_REF, SENSITIVE_NOTE, SENSITIVE_DATE,
                   SENSITIVE_AMOUNT, str(tmp_path), inputs.manifest_path,
                   "Traceback", "usage:"):
        assert absent not in out + err
    assert err == "INPUT_HASH_MISMATCH\n"
    assert not os.path.exists(tmp_path / "out.csv")


# ------------------------------------------------- end-to-end with the core

def _real_core():
    """The real core, imported as a required product (no skip, no stub)."""
    from webapp import review_template

    return review_template


def test_blank_template_end_to_end_is_eleven_columns_and_fully_blank(tmp_path):
    rows = [
        _legacy_row("src-ref-002", keys=("tx-002", "tx-003")),
        _legacy_row("src-ref-001", keys=("tx-001",),
                    disposition="unmatched_review_required"),
    ]
    inputs = _write_inputs(tmp_path,
                           manifest_bytes=_render_legacy_csv(rows))
    destination = str(tmp_path / "review_template.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 0, out + err
    assert err == ""
    payload = json.loads(out)
    assert payload["row_count"] == 2
    assert payload["counts"] == {"approved": 0, "rejected": 0, "incomplete": 2}
    assert payload["snapshot_sha256"] == inputs.snapshot_sha

    with open(destination, "rb") as handle:
        written = handle.read()
    assert not written.startswith(b"\xef\xbb\xbf")
    text = written.decode("utf-8")
    assert "\r\n" not in text

    parsed = list(csv.reader(io.StringIO(text, newline="")))
    assert tuple(parsed[0]) == TEMPLATE_HEADERS
    assert [row[0] for row in parsed[1:]] == ["src-ref-001", "src-ref-002"]
    for row in parsed[1:]:
        assert len(row) == len(TEMPLATE_HEADERS)
        record = dict(zip(parsed[0], row))
        assert record["reviewer_decision"] == ""
        assert record["review_note"] == ""
        assert record["review_schema_version"] == "review-csv-v1"
        assert record["review_snapshot_sha256"] == inputs.snapshot_sha
        assert record["disposition"] in ("candidate_review_required",
                                         "unmatched_review_required")
    # Source material is preserved without reinterpretation.
    assert parsed[1][1] == SENSITIVE_DATE
    assert parsed[1][2] == SENSITIVE_AMOUNT
    assert json.loads(parsed[1][4]) == ["tx-001"]
    assert payload["template_sha256"] == _sha256(written)


def test_generated_template_is_accepted_by_the_accepted_adapter(tmp_path):
    from webapp import review_csv_adapter

    _real_core()
    rows = [_legacy_row(f"src-ref-{index:03d}", keys=(f"tx-{index}",))
            for index in range(1, 4)]
    inputs = _write_inputs(tmp_path, manifest_bytes=_render_legacy_csv(rows))
    destination = str(tmp_path / "review_template.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 0, out + err
    with open(destination, "rb") as handle:
        text = handle.read().decode("utf-8")
    adapter = review_csv_adapter.normalize_review_csv(text,
                                                     inputs.snapshot_sha)
    assert adapter["counts"] == {"approved": 0, "rejected": 0, "incomplete": 3}
    refs = [row["source_ref_snapshot_only"] for row in adapter["review_rows"]]
    assert refs == ["src-ref-001", "src-ref-002", "src-ref-003"]


def test_existing_approval_in_the_legacy_manifest_is_refused_end_to_end(
        tmp_path):
    _real_core()
    rows = [
        _legacy_row("src-ref-001"),
        _legacy_row("src-ref-002", keys=("tx-002",), decision="REJECT"),
    ]
    inputs = _write_inputs(tmp_path, manifest_bytes=_render_legacy_csv(rows))
    destination = str(tmp_path / "review_template.csv")

    code, out, err = _run(inputs.argv(output=destination))

    assert code == 2
    assert json.loads(out) == {"error": {"code": "LEGACY_APPROVAL_PRESENT"}}
    assert err == "LEGACY_APPROVAL_PRESENT\n"
    assert not os.path.exists(destination)
    assert _temp_leftovers(tmp_path) == []


def test_default_stdout_refuses_when_the_snapshot_changes_after_the_core(
        monkeypatch, tmp_path):
    _real_core()
    inputs = _write_inputs(tmp_path)
    real_build = cli._build_template

    def build_then_drift(core, legacy_csv_text, snapshot_sha256):
        result = real_build(core, legacy_csv_text, snapshot_sha256)
        with open(inputs.snapshot_path, "ab") as handle:
            handle.write(b"\n")
        return result

    monkeypatch.setattr(cli, "_build_template", build_then_drift)

    code, out, err = _run(inputs.argv())

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    assert err == "INPUT_CHANGED_DURING_READ\n"
    _assert_no_template_or_context_leaked(out, err, inputs)


def test_default_stdout_refuses_when_the_manifest_changes_after_the_core(
        monkeypatch, tmp_path):
    _real_core()
    inputs = _write_inputs(tmp_path)
    real_build = cli._build_template

    def build_then_drift(core, legacy_csv_text, snapshot_sha256):
        result = real_build(core, legacy_csv_text, snapshot_sha256)
        with open(inputs.manifest_path, "ab") as handle:
            handle.write(b"\n")
        return result

    monkeypatch.setattr(cli, "_build_template", build_then_drift)

    code, out, err = _run(inputs.argv())

    assert code == 2
    assert json.loads(out) == {"error": {"code": "INPUT_CHANGED_DURING_READ"}}
    assert err == "INPUT_CHANGED_DURING_READ\n"
    _assert_no_template_or_context_leaked(out, err, inputs)


def _assert_no_template_or_context_leaked(out: str, err: str, inputs) -> None:
    """No CSV, header, customer value or path survives a post-core refusal."""
    assert set(json.loads(out)) == {"error"}
    directory = os.path.dirname(inputs.snapshot_path)
    for absent in ("source_ref_snapshot_only", "review_schema_version",
                   "review_snapshot_sha256", "review-csv-v1",
                   SENSITIVE_REF, SENSITIVE_NOTE, SENSITIVE_DATE,
                   SENSITIVE_AMOUNT, inputs.snapshot_path,
                   inputs.manifest_path, directory,
                   "Traceback", "usage:"):
        assert absent not in out + err, absent


def test_stdout_mode_matches_published_bytes_end_to_end(tmp_path):
    _real_core()
    rows = [_legacy_row("src-ref-001", keys=("tx-001", "tx-002"))]
    inputs = _write_inputs(tmp_path, manifest_bytes=_render_legacy_csv(rows))

    printed_code, printed, printed_err = _run(inputs.argv())
    destination = str(tmp_path / "review_template.csv")
    published_code, _, _ = _run(inputs.argv(output=destination))

    assert printed_code == published_code == 0
    assert printed_err == ""
    with open(destination, "rb") as handle:
        assert handle.read() == printed.encode("utf-8")
    # The header is compared as CSV fields, not as raw text: the core quotes
    # every field, so the first line is not a bare prefix of the payload.
    parsed = list(csv.reader(io.StringIO(printed, newline="")))
    assert tuple(parsed[0]) == TEMPLATE_HEADERS


# ------------------------------------------------------------ entry points

def test_help_is_available_through_both_entry_points(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    cases = (
        ([sys.executable, "-m", "tools.prepare_review_template", "--help"],
         PROJECT_ROOT),
        ([sys.executable, CLI_PATH, "--help"], tmp_path),
    )
    for argv, workdir in cases:
        proc = subprocess.run(argv, cwd=str(workdir), env=env,
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "usage:" in proc.stdout.lower()
        for option in ("--snapshot", "--snapshot-sha256", "--manifest",
                       "--manifest-sha256", "--output"):
            assert option in proc.stdout
