"""Bounded, read-only runtime acceptance diagnostics for the COST host.

Reports only normalized task metadata, SHA match booleans, HTTP status/latency
aggregates and byte counts. It never reads task arguments, process command lines,
environment values, response bodies, configuration contents or database rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.request

DEFAULT_RELEASE = Path(r"D:\WebLedgerHost\releases\dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1")
EXPECTED_SHA = "dbead7d3b46e991f41a8ce6a39ff9bea8ae4c2e1"
DEFAULT_TASK = "WebLedger-Board"
DEFAULT_URLS = ("http://127.0.0.1:8765/health", "http://127.0.0.1:8765/ready")
MAX_SAMPLES = 20
MAX_TIMEOUT = 3.0


def _sha(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def release_report(release: Path, expected_sha: str = EXPECTED_SHA) -> dict:
    marker = release / "DEPLOYED_COMMIT"
    try:
        marker_value = marker.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        marker_value = ""
    launcher = release / "tools" / "launch_web_ledger.py"
    marker_sha = marker_value.lower() == expected_sha.lower()
    return {
        "release_exists": release.is_dir(),
        "marker_matches_expected": marker_sha,
        "launcher_exists": launcher.is_file() and not launcher.is_symlink(),
        "launcher_sha256": _sha(launcher),
    }


def scheduled_task_report(task_name: str = DEFAULT_TASK, *, client=None) -> dict:
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
        return {
            "available": True,
            "registered": True,
            "enabled": bool(task.Enabled),
            "state_code": int(task.State),
            "run_level": int(principal.RunLevel),
            "logon_type": int(principal.LogonType),
            "action_count": int(definition.Actions.Count),
            "arguments_inspected": False,
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
    for url in urls:
        if not url.startswith("http://127.0.0.1:"):
            raise ValueError("only explicit loopback HTTP URLs are allowed")
        elapsed, sizes, statuses = [], [], []
        failures = 0
        for _ in range(samples):
            request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
            start = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    statuses.append(int(response.status))
                    sizes.append(len(response.read(65536)))
            except urllib.error.HTTPError as error:
                statuses.append(int(error.code))
                sizes.append(0)
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
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--expected-sha", default=EXPECTED_SHA)
    parser.add_argument("--task-name", default=DEFAULT_TASK)
    parser.add_argument("--http", action="store_true", help="probe bounded loopback health/ready timing")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=1.5)
    args = parser.parse_args(argv)
    report = {
        "status": "READ_ONLY_DIAGNOSTIC",
        "release": release_report(args.release, args.expected_sha),
        "scheduler": scheduled_task_report(args.task_name),
        "http": probe_http(samples=args.samples, timeout=args.timeout) if args.http else None,
        "sensitive_values_read_or_emitted": False,
        "writes_performed": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
