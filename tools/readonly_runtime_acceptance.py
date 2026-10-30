"""Bounded, read-only runtime acceptance diagnostics for the COST host.

Reports only normalized task metadata, SHA match booleans, HTTP status/latency
aggregates and byte counts. Task arguments are inspected only in memory to
verify the expected runner path and SHA; their contents are never emitted.
Process command lines, environment values, response bodies, configuration
contents and database rows are not read.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import statistics
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

DEFAULT_TASK = "WebLedger-Board"
DEFAULT_URLS = ("http://127.0.0.1:8751/healthz", "http://127.0.0.1:8751/readyz")
MAX_SAMPLES = 20
MAX_TIMEOUT = 3.0
# Fail-closed: DEPLOYED_COMMIT marker must be small (1 KiB) to prevent memory exhaustion
MAX_MARKER_BYTES = 1024


def release_report(release: Path, expected_sha: str, action_executable: str | None = None,
                   working_directory: str | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_sha):
        raise ValueError("expected SHA must be a full Git commit ID")
    marker = release / "DEPLOYED_COMMIT"
    try:
        with marker.open('rb') as f:
            data = f.read(MAX_MARKER_BYTES + 1)
        if len(data) > MAX_MARKER_BYTES:
            marker_value = ""
        else:
            marker_value = data.decode('ascii').strip()
    except (OSError, UnicodeError):
        marker_value = ""
    marker_sha = marker_value.lower() == expected_sha.lower()
    runner = release / "tools" / "start_web_ledger_host.ps1"
    release_norm = str(release).replace("/", "\\").rstrip("\\").casefold()
    executable_text = str(action_executable or "")
    executable_name = Path(executable_text.replace("\\", "/")).name.casefold()
    executable_known = executable_name in ("powershell", "powershell.exe", "pwsh", "pwsh.exe")
    executable_absolute = Path(executable_text).is_absolute()
    working_norm = str(working_directory or "").replace("/", "\\").rstrip("\\").casefold()
    return {
        "release_exists": release.is_dir(),
        "marker_matches_expected": marker_sha,
        "runner_exists": runner.is_file() and not runner.is_symlink(),
        "action_executable_recognized": executable_known,
        "action_executable_resolution": "ABSOLUTE_PATH_ONLY" if executable_known and executable_absolute else "UNVERIFIED",
        "working_directory_matches_release": working_norm == release_norm,
    }


def scheduled_task_report(task_name: str = DEFAULT_TASK, *, expected_release: Path,
                          expected_sha: str, client=None) -> dict:
    """Return safe Task Scheduler fields; never serialize actions or arguments."""
    try:
        if client is None:
            import win32com.client  # type: ignore[import-not-found]
            client = win32com.client
        service = client.Dispatch("Schedule.Service")
        service.Connect()
        task = service.GetFolder("\\").GetTask(task_name)
        definition = task.Definition
        principal = definition.Principal
        action = definition.Actions.Item(1)
        action_executable = str(action.Path)
        working_directory = str(action.WorkingDirectory)
        arguments = str(action.Arguments)
        release_path = str(expected_release).replace("/", "\\").rstrip("\\")
        runner_reference = release_path + "\\tools\\start_web_ledger_host.ps1"
        argument_tokens = re.findall(r'"([^\"]+)"|([^\s]+)', arguments)
        argument_values = [quoted or bare for quoted, bare in argument_tokens]
        action_sha_reference = any(
            re.search(r"(?<![0-9a-f])" + re.escape(expected_sha) + r"(?![0-9a-f])", value, re.I)
            for value in argument_values
        )
        action_runner_reference = any(value.replace("/", "\\").casefold() == runner_reference.casefold()
                                      for value in argument_values)
        release = release_report(expected_release, expected_sha, action_executable, working_directory)
        return {
            "available": True,
            "registered": True,
            "enabled": bool(task.Enabled),
            "state_code": int(task.State),
            "run_level": int(principal.RunLevel),
            "logon_type": int(principal.LogonType),
            "action_count": int(definition.Actions.Count),
            "action_executable_recognized": release["action_executable_recognized"],
            "action_executable_resolution": release["action_executable_resolution"],
            "action_runner_sha_reference_matches": action_sha_reference and action_runner_reference,
            "working_directory_match": release["working_directory_matches_release"],
            "release_acl_protection": "UNKNOWN",
            "arguments_emitted": False,
            "principal_identity_inspected": False,
        }
    except ImportError:
        return {"available": False, "registered": None, "reason": "scheduler_api_unavailable"}
    except Exception:
        return {"available": True, "registered": False, "reason": "task_query_failed"}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def probe_http(urls=DEFAULT_URLS, samples: int = 5, timeout: float = 1.5) -> dict:
    if not 1 <= samples <= MAX_SAMPLES or not 0.1 <= timeout <= MAX_TIMEOUT:
        raise ValueError("probe limits exceeded")
    results = []
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    for url in urls:
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 8751
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ("/healthz", "/readyz") or parsed.netloc != "127.0.0.1:8751"):
            raise ValueError("URL is outside the exact loopback allowlist")
        elapsed, sizes, statuses = [], [], []
        failures = 0
        for _ in range(samples):
            request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            start = time.perf_counter()
            try:
                with opener.open(request, timeout=timeout) as response:
                    statuses.append(int(response.status))
                    sizes.append(len(response.read(65536)))
            except urllib.error.HTTPError as error:
                statuses.append(int(error.code))
                sizes.append(0)
                failures += 1
            except urllib.error.URLError:
                failures += 1
            except (OSError, TimeoutError):
                failures += 1
            elapsed.append((time.perf_counter() - start) * 1000)
        results.append({
            "endpoint": url.rsplit("/", 1)[-1],
            "samples": samples,
            "failures": failures,
            "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))},
            "latency_ms_p50": _percentile(elapsed, 0.50),
            "latency_ms_p95": _percentile(elapsed, 0.95),
            "response_bytes_mean": round(statistics.mean(sizes), 1) if sizes else None,
            "response_body_retained": False,
        })
    return {"loopback_only": True, "results": results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--task-name", default=DEFAULT_TASK)
    parser.add_argument("--http", action="store_true", help="probe bounded loopback health/ready timing")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=1.5)
    args = parser.parse_args(argv)
    report = {
        "status": "READ_ONLY_DIAGNOSTIC",
        "release": release_report(args.release, args.expected_sha),
        "scheduler": scheduled_task_report(args.task_name, expected_release=args.release,
                                            expected_sha=args.expected_sha),
        "http": probe_http(samples=args.samples, timeout=args.timeout) if args.http else None,
        "sensitive_values_read_or_emitted": False,
        "writes_performed": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
