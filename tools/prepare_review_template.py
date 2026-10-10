"""Build a blank review template bound to one sealed snapshot.

This CLI is the thin shell for the pure template core
(``webapp.review_template``). It owns no review semantics of its own:
every header rule, every refusal and every ``TemplateError.code`` belongs
to the core, while this shell owns only arguments, input verification,
atomic publication and the two output shapes.

Inputs
------
Exactly two files are opened, both named explicitly on the command line:

* ``--snapshot`` / ``--snapshot-sha256`` -- the sealed snapshot file. It is
  read only to verify that its bytes really hash to the declared digest.
  Its content is never decoded and never reaches the core; the core only
  ever sees the digest, as the snapshot binding it writes into every row.
* ``--manifest`` / ``--manifest-sha256`` -- the legacy review manifest. It
  is decoded as UTF-8 with an optional BOM and handed to the core as the
  legacy CSV text.

Both digests are matched as an exact 64-hex string against the recomputed
lowercase digest. There is no trimming, no case folding and no
normalization: a digest declared in uppercase bytes is simply a mismatch.

TOCTOU closure
--------------
Each input is ``stat``-ed (dev, ino, size, mtime_ns), read, and ``stat``-ed
again. A fingerprint change across the read is ``INPUT_CHANGED_DURING_READ``;
a digest mismatch is ``INPUT_HASH_MISMATCH``. Both inputs are verified a
second time immediately before publication and a third time immediately
after it. If the post-publication check fails, the destination is removed
only when it is still the very inode this process just linked, so a
replacement written by another process in the meantime is never deleted.

Publication
-----------
With ``--output PATH`` the parent directory must already exist (nothing is
created implicitly), the destination must not exist (a symlink counts as
existing) and must not be the same file as either input
(``OUTPUT_EQUALS_INPUT``, checked by path and by file identity). The
template bytes are written to a temporary file in the same directory,
flushed and ``fsync``-ed, then published with ``os.link(temp, destination)``
so the no-overwrite guarantee is atomic. A hardlink refusal is
``ATOMIC_PUBLISH_UNAVAILABLE``: there is deliberately no rename, copy or
truncate fallback. The temporary file is always removed, and its content is
never echoed.

Output shapes
-------------
Default (no ``--output``): exit 0 and nothing but the complete CSV text on
stdout. No file is written and no diagnostic is mixed into stdout.

With ``--output``: exit 0 and exactly one JSON object on stdout::

    {"counts": {...}, "manifest_sha256": "...", "row_count": N,
     "snapshot_sha256": "...", "template_sha256": "..."}

Failure is exit 2 with exactly one JSON object on stdout::

    {"error": {"code": "INPUT_HASH_MISMATCH"}}

Privacy
-------
The template CSV is the contract payload and is written verbatim, so source
refs, candidate keys, dates, amounts and review notes inside it are
expected output. Everything outside that payload stays inside: the input
and output paths, raw file bytes, the legacy manifest text, exception
messages, exception reprs and tracebacks are never written to stdout or
stderr, for expected and unexpected failures alike. Diagnostics are a
short code on stderr only, and an unexpected internal failure is reported
as the stable ``INTERNAL_ERROR`` code.

Side effects
------------
The only writes are the same-directory temporary file and the linked
destination, and only in ``--output`` mode. No database, network, manifest
table or project state is touched, and no implicit path is resolved.

Usage::

    python -m tools.prepare_review_template \\
        --snapshot PATH --snapshot-sha256 SHA256HEX \\
        --manifest PATH --manifest-sha256 SHA256HEX [--output PATH]
    python tools/prepare_review_template.py ... (same arguments)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat as stat_module
import sys
import tempfile

# Independent of the current working directory: the file is invoked either
# as a direct script (where sys.path[0] is the tools/ directory) or as
# ``python -m tools.prepare_review_template`` from the project root, so the
# project root is put on sys.path before the package import below is
# resolved.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

EXIT_OK = 0
EXIT_ERROR = 2

# Shell-owned codes. They cover the arguments and the file access that
# never reach the core at all.
CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_INVALID_SNAPSHOT_SHA256 = "INVALID_SNAPSHOT_SHA256"
CODE_INVALID_MANIFEST_SHA256 = "INVALID_MANIFEST_SHA256"
CODE_IO_ERROR = "IO_ERROR"
CODE_INPUT_HASH_MISMATCH = "INPUT_HASH_MISMATCH"
CODE_INPUT_CHANGED_DURING_READ = "INPUT_CHANGED_DURING_READ"
CODE_OUTPUT_EQUALS_INPUT = "OUTPUT_EQUALS_INPUT"
CODE_OUTPUT_EXISTS = "OUTPUT_EXISTS"
CODE_ATOMIC_PUBLISH_UNAVAILABLE = "ATOMIC_PUBLISH_UNAVAILABLE"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

# Core codes are passed through only when they are on this allowlist, so an
# unexpected string in ``TemplateError.code`` can never widen what the CLI
# is willing to print. The set is the core's fixed vocabulary from the
# REVIEW-PREPARE-001 contract, unchanged.
_CORE_CODES = frozenset({
    "LEGACY_SCHEMA_MISMATCH",
    "LEGACY_CSV_INVALID",
    "LEGACY_APPROVAL_PRESENT",
    "INVALID_DISPOSITION",
    "INVALID_CANDIDATE_KEYS",
    "DUPLICATE_REVIEW_REF",
    "INVALID_SNAPSHOT_SHA256",
    "INPUT_HASH_MISMATCH",
    "INPUT_CHANGED_DURING_READ",
    "OUTPUT_EQUALS_INPUT",
    "OUTPUT_EXISTS",
    "ATOMIC_PUBLISH_UNAVAILABLE",
    "IO_ERROR",
})

_COUNT_FIELDS = ("approved", "rejected", "incomplete")

_SHA256_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")

_TEMP_PREFIX = ".prepare-review-template-"
_TEMP_SUFFIX = ".tmp"

_PROG = "prepare_review_template"

# Test seams. Each is the single place the module reaches for the
# corresponding os facility, so a test can substitute one call without
# patching the os module process-wide.
_stat = os.stat
_lexists = os.path.lexists
_link = os.link
_unlink = os.unlink
_abspath = os.path.abspath
_realpath = os.path.realpath


class _CliError(Exception):
    """A refusal already reduced to a stable, printable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _ParserError(Exception):
    """Raised instead of argparse's usage-and-exit behaviour."""


class _Parser(argparse.ArgumentParser):
    """argparse parser that never echoes arguments back to the caller.

    The stock parser prints a usage line that embeds the offending option
    and its value, which would put a filesystem path on stdout. Argument
    problems are surfaced as a code instead.
    """

    def error(self, message):  # noqa: D102 - argparse hook
        raise _ParserError()


class _Input:
    """One verified input: its bytes plus the fingerprint they were read at."""

    def __init__(self, path: str, expected_sha256: str, data: bytes,
                 fingerprint: tuple) -> None:
        self.path = path
        self.expected_sha256 = expected_sha256
        self.data = data
        self.fingerprint = fingerprint
        self.digest = hashlib.sha256(data).hexdigest()

    @property
    def identity(self) -> tuple:
        return (self.fingerprint[0], self.fingerprint[1])


def _fingerprint(st) -> tuple:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _read_input(path: str, expected_sha256: str) -> _Input:
    """Stat, read, stat again, then verify the digest. No path is echoed."""
    try:
        before = _stat(path)
    except OSError:
        raise _CliError(CODE_IO_ERROR) from None
    if not stat_module.S_ISREG(before.st_mode):
        raise _CliError(CODE_IO_ERROR)
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        after = _stat(path)
    except OSError:
        raise _CliError(CODE_IO_ERROR) from None
    if _fingerprint(before) != _fingerprint(after):
        raise _CliError(CODE_INPUT_CHANGED_DURING_READ)
    result = _Input(path, expected_sha256, data, _fingerprint(before))
    if result.digest != expected_sha256:
        raise _CliError(CODE_INPUT_HASH_MISMATCH)
    return result


def _reverify(item: _Input) -> None:
    """Re-read an input and require both fingerprint and digest to be stable.

    Used immediately before and immediately after publication. Any drift,
    including a same-byte rewrite that only moves mtime, is a change.
    """
    try:
        with open(item.path, "rb") as handle:
            data = handle.read()
        current = _fingerprint(_stat(item.path))
    except OSError:
        raise _CliError(CODE_INPUT_CHANGED_DURING_READ) from None
    if current != item.fingerprint:
        raise _CliError(CODE_INPUT_CHANGED_DURING_READ)
    if hashlib.sha256(data).hexdigest() != item.digest:
        raise _CliError(CODE_INPUT_CHANGED_DURING_READ)
    if item.digest != item.expected_sha256:
        raise _CliError(CODE_INPUT_CHANGED_DURING_READ)


def _decode_manifest(item: _Input) -> str:
    try:
        return item.data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _CliError(CODE_IO_ERROR) from None


def _load_core():
    """Import the core lazily, so argument errors never depend on it."""
    import importlib

    return importlib.import_module("webapp.review_template")


def _build_template(core, legacy_csv_text: str, snapshot_sha256: str) -> dict:
    try:
        result = core.build_blank_review_template(legacy_csv_text,
                                                 snapshot_sha256)
    except core.TemplateError as exc:
        code = getattr(exc, "code", None)
        if type(code) is not str or code not in _CORE_CODES:
            raise _CliError(CODE_INTERNAL_ERROR) from None
        raise _CliError(code) from None
    if not isinstance(result, dict):
        raise _CliError(CODE_INTERNAL_ERROR)
    csv_text = result.get("csv_text")
    row_count = result.get("row_count")
    counts = result.get("counts")
    if type(csv_text) is not str:
        raise _CliError(CODE_INTERNAL_ERROR)
    if type(row_count) is not int or isinstance(row_count, bool):
        raise _CliError(CODE_INTERNAL_ERROR)
    if not isinstance(counts, dict):
        raise _CliError(CODE_INTERNAL_ERROR)
    view = {}
    for name in _COUNT_FIELDS:
        value = counts.get(name)
        if type(value) is not int or isinstance(value, bool):
            raise _CliError(CODE_INTERNAL_ERROR)
        view[name] = value
    return {"csv_text": csv_text, "row_count": row_count, "counts": view}


def _emit(payload: dict) -> None:
    sys.stdout.write(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _write_csv_stdout(csv_text: str) -> None:
    """Write the template and nothing else to stdout, byte for byte."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(csv_text)
        sys.stdout.flush()
        return
    stream.write(csv_text.encode("utf-8"))
    stream.flush()


def _fail(code: str) -> int:
    _emit({"error": {"code": code}})
    sys.stderr.write(code + "\n")
    return EXIT_ERROR


def _build_parser() -> _Parser:
    parser = _Parser(
        prog=_PROG,
        description=("Build a blank review template bound to one sealed "
                     "snapshot and print it as CSV, or publish it atomically "
                     "to a new file."),
        add_help=True,
    )
    parser.add_argument(
        "--snapshot", dest="snapshot_path", required=True, metavar="PATH",
        help="sealed snapshot file to digest-verify (never decoded)")
    parser.add_argument(
        "--snapshot-sha256", dest="snapshot_sha256", required=True,
        metavar="SHA256HEX",
        help="64-hex digest the snapshot bytes must hash to exactly")
    parser.add_argument(
        "--manifest", dest="manifest_path", required=True, metavar="PATH",
        help="legacy review manifest to convert (UTF-8, optional BOM)")
    parser.add_argument(
        "--manifest-sha256", dest="manifest_sha256", required=True,
        metavar="SHA256HEX",
        help="64-hex digest the manifest bytes must hash to exactly")
    parser.add_argument(
        "--output", dest="output_path", required=False, metavar="PATH",
        help="publish the template to this new file; parent directory must "
             "already exist (default: print the CSV on stdout)")
    return parser


def _identity_of(path: str):
    try:
        info = _stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def _same_location(left: str, right: str) -> bool:
    if _abspath(left) == _abspath(right):
        return True
    try:
        if _realpath(left) == _realpath(right):
            return True
    except OSError:
        pass
    return False


def _check_destination(destination: str, inputs) -> None:
    """Refuse aliasing and pre-existing destinations before any write."""
    for item in inputs:
        if _same_location(destination, item.path):
            raise _CliError(CODE_OUTPUT_EQUALS_INPUT)
    if not _lexists(destination):
        return
    destination_identity = _identity_of(destination)
    if destination_identity is not None:
        for item in inputs:
            if destination_identity == item.identity:
                raise _CliError(CODE_OUTPUT_EQUALS_INPUT)
    raise _CliError(CODE_OUTPUT_EXISTS)


def _remove_quietly(path) -> None:
    if not path:
        return
    try:
        _unlink(path)
    except OSError:
        pass


def _publish(destination: str, payload: bytes, inputs) -> None:
    directory = os.path.dirname(destination) or "."
    if not os.path.isdir(directory):
        raise _CliError(CODE_IO_ERROR)
    temp_path = None
    try:
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", dir=directory, prefix=_TEMP_PREFIX,
                    suffix=_TEMP_SUFFIX, delete=False) as handle:
                temp_path = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            raise _CliError(CODE_IO_ERROR) from None
        for item in inputs:
            _reverify(item)
        try:
            _link(temp_path, destination)
        except FileExistsError:
            raise _CliError(CODE_OUTPUT_EXISTS) from None
        except OSError:
            # A refusal here is either an unsupported hardlink or an
            # unusable destination. There is no fallback by design.
            raise _CliError(CODE_ATOMIC_PUBLISH_UNAVAILABLE) from None
        temp_identity = _identity_of(temp_path)
        if temp_identity is None:
            raise _CliError(CODE_ATOMIC_PUBLISH_UNAVAILABLE)
        try:
            for item in inputs:
                _reverify(item)
        except _CliError:
            # The destination is deleted only while it is still the inode
            # this process linked, so a replacement written by another
            # process in the meantime is never destroyed.
            if _identity_of(destination) == temp_identity:
                _remove_quietly(destination)
            raise
        if _identity_of(destination) != temp_identity:
            raise _CliError(CODE_ATOMIC_PUBLISH_UNAVAILABLE)
    finally:
        _remove_quietly(temp_path)


def _run(argv) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except _ParserError:
        raise _CliError(CODE_INVALID_ARGUMENT) from None

    if type(args.snapshot_sha256) is not str or \
            _SHA256_RE.match(args.snapshot_sha256) is None:
        raise _CliError(CODE_INVALID_SNAPSHOT_SHA256)
    if type(args.manifest_sha256) is not str or \
            _SHA256_RE.match(args.manifest_sha256) is None:
        raise _CliError(CODE_INVALID_MANIFEST_SHA256)
    if args.output_path is not None and args.output_path == "":
        raise _CliError(CODE_INVALID_ARGUMENT)

    snapshot = _read_input(args.snapshot_path, args.snapshot_sha256)
    manifest = _read_input(args.manifest_path, args.manifest_sha256)
    inputs = (snapshot, manifest)

    legacy_csv_text = _decode_manifest(manifest)
    core = _load_core()
    template = _build_template(core, legacy_csv_text, args.snapshot_sha256)

    # Both inputs are reverified after the core has run, so the time the
    # template spent outside this process cannot silently widen the binding
    # it is about to carry. In file mode the publish window adds its own
    # immediately-before and immediately-after checks on top of this one.
    for item in inputs:
        _reverify(item)

    csv_text = template["csv_text"]
    destination = args.output_path
    if destination is None:
        _write_csv_stdout(csv_text)
        return EXIT_OK

    _check_destination(destination, inputs)
    payload = csv_text.encode("utf-8")
    _publish(destination, payload, inputs)

    _emit({
        "counts": template["counts"],
        "manifest_sha256": manifest.digest,
        "row_count": template["row_count"],
        "snapshot_sha256": snapshot.digest,
        "template_sha256": hashlib.sha256(payload).hexdigest(),
    })
    return EXIT_OK


def main(argv=None) -> int:
    """Entry point. Returns 0 on success and 2 on any refusal."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        return _run(argv)
    except _CliError as exc:
        return _fail(exc.code)
    except Exception:
        # No traceback, no exception repr, no message: an unexpected internal
        # failure is still just a stable code.
        return _fail(CODE_INTERNAL_ERROR)


if __name__ == "__main__":
    sys.exit(main())
