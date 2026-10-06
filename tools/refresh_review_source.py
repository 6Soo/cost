"""SOURCE-REFRESH-001 collector command.

Fetch or read a changed source, build a new review input from it, prove the
bundle with the whole existing review core, and activate it atomically. A
repeated run over an unchanged source does nothing and says so.

Every path is explicit. There is no default config, no default bundle root and no
default source: a collector that guessed where the live review is could activate a
bundle beside the real one, and the operator would have no way to tell.

Nothing is logged but a fixed code. A collector runs unattended and its output
ends up in a task log, and a URL, a path, a cell value, a transaction key or an
exception message in that log is a piece of the customer's data in a place nobody
chose to put it.

    python tools/refresh_review_source.py \\
        --config C:\\review\\review.json \\
        --master C:\\review\\master.csv \\
        --bundle-root C:\\review\\bundles \\
        --snapshot C:\\review\\snapshot.xlsx

    ... --source-url https://host/export.xlsx --timeout 30 --max-bytes 52428800

`--watch --interval` keeps the collector running. It is prepared here and not
exercised by this worker: a network worker against the real source is the
coordinator's to run.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from webapp import real_review
from webapp import review_refresh

#: Bounded on purpose. A collector that hangs holds a fetched snapshot in memory
#: and the config lock between reads, and a lock held by a hung process is a
#: review that cannot be refreshed by anything.
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_ATTEMPTS = 3
#: Watch mode defaults to half a minute. The web app re-reads its config every two
#: seconds, so a longer collection interval means the screen notices a refreshed
#: source up to that much later — and the point of the collector is that a
#: changed source becomes visible without anyone asking for it. An operator who
#: wants it faster passes 15.
DEFAULT_INTERVAL = 30.0
SOURCE_CONFIG_MAX_BYTES = 64 * 1024
GOOGLE_SHEETS_SOURCE_TYPE = "google_sheets"
GOOGLE_SHEETS_EXPORT_FORMAT = "xlsx"
GOOGLE_SHEETS_EXPORT_URL = (
    "https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
)
_SPREADSHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,200}$")

#: Bounds on the operator's own numbers, checked before anything is used. A
#: non-positive or non-finite value is a typo, and a typo that silently meant
#: "no timeout" or "no size limit" would be a collector with no bounds at all.
MAX_ATTEMPTS = 10
MAX_INTERVAL = 86400.0

#: What a workbook download is allowed to say it is. Checked because a URL that
#: answers 200 with an HTML error page would otherwise be parsed as a workbook and
#: refused much later, with a code that says nothing about what came back.
_ALLOWED_TYPES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel", "application/octet-stream", "application/zip",
    "application/x-zip-compressed",
)

CODE_SOURCE_UNREACHABLE = review_refresh.CODE_SOURCE_UNREADABLE
CODE_SOURCE_TOO_LARGE = "REFRESH_SOURCE_TOO_LARGE"
CODE_SOURCE_WRONG_TYPE = "REFRESH_SOURCE_WRONG_TYPE"
CODE_SOURCE_CONFIG_INVALID = "REFRESH_SOURCE_CONFIG_INVALID"
CODE_ARGUMENT = review_refresh.CODE_ARGUMENT


class SourceUnavailable(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def report(code, stream=None) -> None:
    """One fixed code, and nothing else."""
    (stream or sys.stdout).write(json.dumps({"code": code}) + "\n")


def _read_bounded(path, max_bytes):
    try:
        size = pathlib.Path(path).stat().st_size
    except OSError:
        raise SourceUnavailable(CODE_ARGUMENT) from None
    if size > max_bytes:
        # Refused before it is read, so an oversized file is never loaded.
        raise SourceUnavailable(CODE_SOURCE_TOO_LARGE)
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError:
        raise SourceUnavailable(CODE_ARGUMENT) from None
    if len(data) > max_bytes:
        raise SourceUnavailable(CODE_SOURCE_TOO_LARGE)
    return data


def read_text_bounded(path, max_bytes):
    data = _read_bounded(path, max_bytes)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise SourceUnavailable(CODE_ARGUMENT) from None


def load_source_config(path):
    """Read one explicit source descriptor and refuse anything unexpected."""
    try:
        raw = _read_bounded(path, SOURCE_CONFIG_MAX_BYTES)
        config = json.loads(raw.decode("utf-8"))
    except Exception:
        raise SourceUnavailable(CODE_SOURCE_CONFIG_INVALID) from None

    expected = {"source_type", "spreadsheet_id", "export_format"}
    if not isinstance(config, dict) or set(config) != expected:
        raise SourceUnavailable(CODE_SOURCE_CONFIG_INVALID)
    if config["source_type"] != GOOGLE_SHEETS_SOURCE_TYPE:
        raise SourceUnavailable(CODE_SOURCE_CONFIG_INVALID)
    if config["export_format"] != GOOGLE_SHEETS_EXPORT_FORMAT:
        raise SourceUnavailable(CODE_SOURCE_CONFIG_INVALID)
    spreadsheet_id = config["spreadsheet_id"]
    if not isinstance(spreadsheet_id, str) or not _SPREADSHEET_ID.fullmatch(spreadsheet_id):
        raise SourceUnavailable(CODE_SOURCE_CONFIG_INVALID)
    return config


def source_url_from_config(path):
    config = load_source_config(path)
    return GOOGLE_SHEETS_EXPORT_URL.format(
        spreadsheet_id=config["spreadsheet_id"])


def fetch_snapshot(url, *, timeout, max_bytes, attempts, opener=None):
    """A workbook over HTTP, with a time limit, a size limit and a type check.

    `opener` is injected by the tests, so the bounded behaviour is exercised
    without a network. The default one is the only place this file touches a
    socket, and it is a read of a URL the operator named.
    """
    last = CODE_SOURCE_UNREACHABLE
    for attempt in range(max(1, attempts)):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet",
                    # The same agent the working probe used. Some export endpoints
                    # answer a default Python agent with an error page, and an
                    # error page is a refusal here with a code that would say
                    # nothing about what came back.
                    "User-Agent": "Mozilla/5.0",
                })
            open_url = opener or urllib.request.urlopen
            with open_url(request, timeout=timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise SourceUnavailable(CODE_SOURCE_TOO_LARGE)
                    except ValueError:
                        raise SourceUnavailable(CODE_ARGUMENT) from None
                content_type = (response.headers.get("Content-Type") or "")
                content_type = content_type.split(";")[0].strip().lower()
                if content_type and content_type not in _ALLOWED_TYPES:
                    raise SourceUnavailable(CODE_SOURCE_WRONG_TYPE)
                data = response.read(max_bytes + 1)
        except SourceUnavailable:
            raise
        except Exception:
            last = CODE_SOURCE_UNREACHABLE
            # A bounded number of attempts, with a bounded wait between them.
            if attempt + 1 < max(1, attempts):
                time.sleep(min(2.0 * (attempt + 1), 10.0))
            continue
        if len(data) > max_bytes:
            raise SourceUnavailable(CODE_SOURCE_TOO_LARGE)
        if not data:
            last = CODE_SOURCE_UNREACHABLE
            continue
        return data
    raise SourceUnavailable(last)


def _previous_review_text(config_path, max_bytes):
    """The review input the live config names, read as the layout record it is."""
    try:
        with open(config_path, "rb") as handle:
            manifest = json.loads(handle.read().decode("utf-8"))
    except Exception:
        return ""
    try:
        return read_text_bounded(manifest["review_path"], max_bytes)
    except (SourceUnavailable, KeyError, TypeError):
        return ""


def _default_fetcher(args):
    """The fetch a remote source uses when nothing is injected.

    The bounded one, with this run's own timeout, size limit and attempt count.
    Without this the remote path called `None`, which is not callable: a URL was
    accepted by the parser and then failed with a TypeError instead of a code.
    """
    def fetch(url):
        return fetch_snapshot(url, timeout=args.timeout,
                              max_bytes=args.max_bytes,
                              attempts=args.attempts)
    return fetch


def run_once(args, *, fetcher=None) -> str:
    """One collection. Returns a fixed code and nothing else."""
    try:
        if args.snapshot:
            snapshot_bytes = _read_bounded(args.snapshot, args.max_bytes)
        else:
            source_url = (source_url_from_config(args.source_config)
                          if args.source_config else args.source_url)
            snapshot_bytes = (fetcher or _default_fetcher(args))(
                source_url)
        master_text = read_text_bounded(args.master, args.max_bytes)
    except SourceUnavailable as exc:
        _record(args, exc.code, None)
        return exc.code

    previous = _previous_review_text(args.config, args.max_bytes)
    try:
        bundle = review_refresh.collect_and_activate(
            args.config, args.bundle_root, snapshot_bytes, master_text, previous,
            minimum_rows=args.minimum_rows)
    except review_refresh.RefreshError as exc:
        _record(args, exc.code, None)
        return exc.code

    if bundle.get("no_op"):
        # A no-op is a success, and it is the one success that changes nothing
        # else on disk: the bundle, the config and the binding all stay.
        _record(args, "REFRESH_NO_CHANGE", None, collected_at=_now())
        return "REFRESH_NO_CHANGE"

    _record(args, review_refresh.CODE_CONFIG_REPLACED, bundle,
            collected_at=_now())
    return review_refresh.CODE_CONFIG_REPLACED


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _record(args, code, bundle, collected_at=""):
    """The status file, in the one place the web app reads it from.

    The path is the web app's own, taken from `real_review` rather than
    reconstructed here. Two conventions would be two answers to "did the last
    collection work", and the web side is the one that has to answer it for the
    owner while a collection is failing.
    """
    directory = real_review.refresh_status_path(args.config)
    try:
        review_refresh.write_status(args.bundle_root, code, bundle,
                                    collected_at=collected_at, path=directory)
    except Exception:
        # A status that cannot be written must not fail a collection that
        # succeeded, and must not be papered over: the code is still printed.
        pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog="refresh_review_source",
        description="Collect a changed review source and activate it atomically.")
    parser.add_argument("--config", required=True,
                        help="The live review config. Named, never defaulted.")
    parser.add_argument("--master", required=True,
                        help="The card master CSV, exact UTF-8.")
    parser.add_argument("--bundle-root", required=True,
                        help="Where immutable bundles are written.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", help="A local workbook file.")
    source.add_argument("--source-url", help="A workbook URL.")
    source.add_argument(
        "--source-config",
        help="An explicit source descriptor; never searched or defaulted.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="Seconds per fetch attempt.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help="Largest source accepted, in bytes.")
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS,
                        help="Fetch attempts, bounded.")
    parser.add_argument("--minimum-rows", type=int, default=0,
                        help="Operator's own floor. Off unless given.")
    parser.add_argument("--watch", action="store_true",
                        help="Keep collecting.")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="Seconds between collections in watch mode.")
    return parser


def _positive_finite(value) -> bool:
    import math

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # A typo in a bound is refused rather than read as "no bound at all".
    if not _positive_finite(args.timeout) or not _positive_finite(args.max_bytes):
        report(CODE_ARGUMENT)
        return 2
    if not isinstance(args.attempts, int) or not 1 <= args.attempts <= MAX_ATTEMPTS:
        report(CODE_ARGUMENT)
        return 2
    if not _positive_finite(args.interval) or args.interval > MAX_INTERVAL:
        report(CODE_ARGUMENT)
        return 2
    if args.minimum_rows < 0:
        report(CODE_ARGUMENT)
        return 2
    if not args.watch:
        code = run_once(args)
        report(code)
        return 0 if code in (review_refresh.CODE_CONFIG_REPLACED,
                             "REFRESH_NO_CHANGE") else 2
    while True:
        report(run_once(args))
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
