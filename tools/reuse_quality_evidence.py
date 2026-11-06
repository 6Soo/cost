"""Reuse a successful PR quality run only for an identical merged source tree."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile


API = "https://api.github.com"
WORKFLOW_PATH = ".github/workflows/quality.yml"
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
CI_OWNED_PATHS = {
    WORKFLOW_PATH,
    "tools/run_quality_checks.py",
    "tools/reuse_quality_evidence.py",
    "tools/select_targeted_tests.py",
    "tools/check_tracked_data.py",
    "config/test-impact-map.json",
    "requirements-dev.txt",
    "tests/test_quality_checks.py",
}


class GitHubAPI:
    def __init__(self, token: str):
        self.token = token

    def _get(self, url: str) -> tuple[bytes, str]:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cost-quality-evidence-reuse",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(MAX_ARTIFACT_BYTES + 1), response.headers.get("Content-Type", "")

    def json(self, url: str):
        body, _ = self._get(url)
        if len(body) > MAX_ARTIFACT_BYTES:
            raise ValueError("API_RESPONSE_TOO_LARGE")
        return json.loads(body.decode("utf-8"))

    def artifact(self, url: str) -> bytes:
        body, _ = self._get(url)
        if len(body) > MAX_ARTIFACT_BYTES:
            raise ValueError("ARTIFACT_TOO_LARGE")
        return body


def _api_url(repository: str, path: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("INVALID_REPOSITORY")
    return f"{API}/repos/{repository}/{path.lstrip('/')}"


def _valid_summary(archive: bytes) -> tuple[dict, dict]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        entries = {item.filename: item for item in zipped.infolist()}
        total = sum(item.file_size for item in entries.values())
        if total > MAX_ARTIFACT_BYTES:
            raise ValueError("ARTIFACT_UNCOMPRESSED_TOO_LARGE")
        plan_name = "quality-plan.json"
        summary_name = "quality-artifacts/run-summary.json"
        if plan_name not in entries or summary_name not in entries:
            raise ValueError("QUALITY_EVIDENCE_MISSING")
        plan = json.loads(zipped.read(plan_name).decode("utf-8"))
        summary = json.loads(zipped.read(summary_name).decode("utf-8"))

    targets = plan.get("pytest_targets")
    browser_tests = plan.get("browser_tests")
    artifact_head = plan.get("head_sha", "")
    plan_tree = plan.get("head_tree_sha", "")
    base_sha = plan.get("base_sha", "")
    if (plan.get("status") != "SELECTED" or not re.fullmatch(r"[0-9a-fA-F]{40}", artifact_head)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", plan_tree)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha)
            or not isinstance(targets, list) or not targets
            or not all(isinstance(target, str) for target in targets) or len(targets) != len(set(targets))
            or plan.get("unknown_paths") or not isinstance(browser_tests, list)
            or not all(isinstance(target, str) for target in browser_tests)
            or len(browser_tests) != len(set(browser_tests))):
        raise ValueError("QUALITY_PLAN_NOT_REUSABLE")
    if (summary.get("status") != "PASSED"
            or summary.get("head_sha", "").lower() != artifact_head.lower()
            or summary.get("head_tree_sha", "").lower() != plan_tree.lower()
            or summary.get("base_sha") != plan.get("base_sha")
            or summary.get("pytest_targets") != targets
            or summary.get("browser_required") is not bool(browser_tests)
            or type(summary.get("test_case_count")) is not int or summary["test_case_count"] < 1
            or type(summary.get("executed_case_count")) is not int or summary["executed_case_count"] < 1
            or type(summary.get("skip_count")) is not int or summary["skip_count"] != 0
            or summary.get("skipped_test_cases")
            or summary.get("nonbrowser_skipped_test_cases")
            or summary.get("browser_skipped")
            or summary.get("missing_browser_tests")
            or not isinstance(summary.get("browser_executed"), list)
            or not all(isinstance(target, str) for target in summary["browser_executed"])
            or set(summary["browser_executed"]) != set(browser_tests)):
        raise ValueError("QUALITY_RUN_NOT_REUSABLE")
    return plan, summary


def find_reusable_evidence(api, repository: str, commit_sha: str, commit_tree: str) -> dict | None:
    """Return proof metadata only when PR tests cover this exact committed tree."""
    try:
        pulls = api.json(_api_url(repository, f"commits/{commit_sha}/pulls"))
        matching = [pr for pr in pulls if pr.get("merged_at")
                    and pr.get("merge_commit_sha", "").lower() == commit_sha.lower()
                    and pr.get("base", {}).get("ref") == "main"
                    and pr.get("base", {}).get("repo", {}).get("full_name", "").lower() == repository.lower()
                    and pr.get("head", {}).get("repo", {}).get("full_name", "").lower() == repository.lower()]
        if len(matching) != 1:
            return None
        pr = matching[0]
        number = pr["number"]
        head_sha = pr["head"]["sha"]

        changed = api.json(_api_url(repository, f"pulls/{number}/files?per_page=100"))
        if not isinstance(changed, list) or any(file.get("filename") in CI_OWNED_PATHS for file in changed):
            return None
        # GitHub paginates pull file lists at 100. A full page is ambiguous, so
        # refuse reuse instead of risking a hidden CI-owned change.
        if len(changed) >= 100:
            return None

        runs_url = _api_url(repository,
            f"actions/workflows/quality.yml/runs?head_sha={urllib.parse.quote(head_sha)}&event=pull_request&per_page=100")
        runs = api.json(runs_url).get("workflow_runs", [])
        candidates = [run for run in runs if run.get("path") == WORKFLOW_PATH
                      and run.get("head_sha", "").lower() == head_sha.lower()
                      and run.get("event") == "pull_request"
                      and run.get("status") == "completed" and run.get("conclusion") == "success"]
        if not candidates:
            return None
        run = max(candidates, key=lambda item: (item.get("run_attempt", 1), item.get("id", 0)))
        artifacts = api.json(_api_url(repository, f"actions/runs/{run['id']}/artifacts")).get("artifacts", [])
        artifacts = [item for item in artifacts if item.get("name", "").startswith("quality-evidence-")
                     and not item.get("expired") and item.get("archive_download_url")]
        if not artifacts:
            return None
        artifact = max(artifacts, key=lambda item: item.get("created_at", ""))
        plan, summary = _valid_summary(api.artifact(artifact["archive_download_url"]))
        tested_commit = plan["head_sha"]
        tested_tree = plan["head_tree_sha"]
        if tested_tree.lower() != commit_tree.lower():
            return None
        return {
            "status": "REUSED_VERIFIED",
            "reuse": {
                "pull_request": number,
                "pull_request_head_sha": head_sha,
                "pull_request_head_tree_sha": tested_tree,
                "tested_merge_sha": tested_commit,
                "tested_merge_tree_sha": tested_tree,
                "merged_sha": commit_sha,
                "merged_tree_sha": commit_tree,
                "workflow_run_id": run["id"],
                "artifact_name": artifact["name"],
                "base_sha": plan["base_sha"],
                "pytest_target_count": len(plan["pytest_targets"]),
                "executed_test_count": summary["executed_case_count"],
                "browser_test_count": len(plan["browser_tests"]),
                "skipped_test_count": 0,
                "data_guard_and_pytest": "passed_in_source_workflow_run",
            },
            "steps": ["verified-identical-tree", "reuse-successful-pr-quality-evidence"],
            "fallback": None,
        }
    except (AttributeError, KeyError, TypeError, ValueError, OSError, urllib.error.URLError,
            json.JSONDecodeError, zipfile.BadZipFile, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = None
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout.strip()
        result = find_reusable_evidence(GitHubAPI(token), args.repository, args.commit, tree)
    if result is None:
        result = {"status": "REUSE_UNAVAILABLE", "reason": "NO_EXACT_SUCCESSFUL_PR_EVIDENCE",
                  "steps": ["run-normal-impact-checks"], "fallback": "full-impact-check"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
