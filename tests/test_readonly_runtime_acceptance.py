import json

import pytest

from tools import readonly_runtime_acceptance as acceptance


def test_release_report_only_exposes_marker_runner_and_path_booleans(tmp_path):
    runner = tmp_path / "tools" / "start_web_ledger_host.ps1"
    runner.parent.mkdir()
    runner.write_text("synthetic runner", encoding="utf-8")
    (tmp_path / "DEPLOYED_COMMIT").write_text("a" * 40 + "\n", encoding="ascii")
    report = acceptance.release_report(tmp_path, "a" * 40)
    assert report["marker_matches_expected"] is True
    assert report["runner_exists"] is True
    assert report["action_executable_recognized"] is False
    assert "synthetic runner" not in json.dumps(report)


def test_http_probe_limits_targets_and_aggregates_without_body(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size):
            assert size == 65536
            return b"sensitive fixture body"

    monkeypatch.setattr(acceptance.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    report = acceptance.probe_http(("http://127.0.0.1:8751/readyz",), samples=2)
    row = report["results"][0]
    assert row["status_counts"] == {"200": 2}
    assert row["response_body_retained"] is False
    assert "sensitive fixture body" not in json.dumps(report)
    with pytest.raises(ValueError):
        acceptance.probe_http(("http://example.com/ready",), samples=1)
    with pytest.raises(ValueError):
        acceptance.probe_http(("http://user@127.0.0.1:8751/healthz",), samples=1)
    with pytest.raises(ValueError):
        acceptance.probe_http(("http://127.0.0.1:8751/redirect",), samples=1)
    for unsafe in (
        "http://127.0.0.1.evil:8751/healthz",
        "http://127.0.0.1:8751/healthz@evil",
        "http://127.0.0.1:8751/healthz?next=http://evil",
        "http://127.0.0.1:8751/readyz#fragment",
        "https://127.0.0.1:8751/healthz",
    ):
        with pytest.raises(ValueError):
            acceptance.probe_http((unsafe,), samples=1)
    with pytest.raises(ValueError):
        acceptance.probe_http(samples=21)


def test_task_report_never_returns_action_or_principal(monkeypatch):
    from types import SimpleNamespace
    class Principal:
        RunLevel = 1
        LogonType = 3
        UserId = "sensitive-user"
    class Action:
        Path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        WorkingDirectory = r"C:\AX\cost"
        Arguments = '-File "D:\\WebLedgerHost\\releases\\' + "a" * 40 + '\\tools\\start_web_ledger_host.ps1"'
    class Actions:
        Count = 1
        def Item(self, i):
            assert i == 1
            return Action()
    definition = SimpleNamespace(Principal=Principal(), Actions=Actions())
    class Task:
        Enabled = True
        State = 4
        Definition = definition
    class Folder:
        def GetTask(self, name):
            assert name == "WebLedger-Board"
            return Task()
    class Service:
        def Connect(self): pass
        def GetFolder(self, name): return Folder()
    client = SimpleNamespace(Dispatch=lambda _: Service())
    report = acceptance.scheduled_task_report(expected_release=__import__('pathlib').Path('D:/WebLedgerHost/releases/' + 'a' * 40),
                                              expected_sha='a' * 40, client=client)
    assert report["registered"] and report["enabled"]
    assert report["action_executable_recognized"] is True
    assert report["action_executable_resolution"] == "ABSOLUTE_PATH_ONLY"
    assert report["action_runner_sha_reference_matches"] is True
    assert report["working_directory_match"] is False
    assert report["release_acl_protection"] == "UNKNOWN"
    assert report["arguments_emitted"] is False
    assert "sensitive-user" not in json.dumps(report)
    assert "private-argument" not in json.dumps(report)


@pytest.mark.parametrize("argument", [
    '-File "D:\\WebLedgerHost\\releases\\' + "a" * 40 + 'x\\tools\\start_web_ledger_host.ps1"',
    '-File "D:\\WebLedgerHost\\releases\\' + "a" * 40 + '\\tools\\start_web_ledger_host.ps1.backup"',
    '-File "D:\\WebLedgerHost\\releases\\' + "b" * 40 + '\\tools\\start_web_ledger_host.ps1"',
])
def test_task_runner_sha_reference_rejects_path_lookalikes(argument):
    class Action:
        Path = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        WorkingDirectory = r"C:\AX\cost"
        Arguments = argument
    class Actions:
        Count = 1
        def Item(self, index): return Action()
    from types import SimpleNamespace
    task = SimpleNamespace(Definition=SimpleNamespace(
        Principal=SimpleNamespace(RunLevel=1, LogonType=3), Actions=Actions()), Enabled=True, State=4)
    client = SimpleNamespace(Dispatch=lambda _: SimpleNamespace(
        Connect=lambda: None, GetFolder=lambda _: SimpleNamespace(GetTask=lambda __: task)))
    report = acceptance.scheduled_task_report(expected_release=__import__('pathlib').Path('D:/WebLedgerHost/releases/' + 'a' * 40),
                                              expected_sha='a' * 40, client=client)
    assert report["action_runner_sha_reference_matches"] is False


def test_extensionless_powershell_is_recognized_but_unresolved():
    report = acceptance.release_report(__import__('pathlib').Path('D:/release'), 'a' * 40, 'powershell')
    assert report["action_executable_recognized"] is True
    assert report["action_executable_resolution"] == "UNVERIFIED"


def test_redirect_response_is_rejected_without_following(monkeypatch):
    import urllib.error
    calls = []
    def redirect(*args, **kwargs):
        calls.append(True)
        raise urllib.error.HTTPError(args[1].full_url, 302, "redirect", {"Location": "http://example.com/"}, None)
    monkeypatch.setattr(acceptance.urllib.request.OpenerDirector, "open", redirect)
    result = acceptance.probe_http(("http://127.0.0.1:8751/healthz",), samples=1)
    assert calls == [True]
    assert result["results"][0]["failures"] == 1
    assert result["results"][0]["status_counts"] == {"302": 1}


def test_connection_error_does_not_fabricate_http_status(monkeypatch):
    def unavailable(*args, **kwargs):
        raise acceptance.urllib.error.URLError("synthetic connection refused")
    monkeypatch.setattr(acceptance.urllib.request.OpenerDirector, "open", unavailable)
    row = acceptance.probe_http(samples=1)["results"][0]
    assert row["failures"] == 1
    assert row["status_counts"] == {}


@pytest.mark.parametrize("sha", ["", "abc123", "g" * 40])
def test_invalid_expected_sha_cannot_match_missing_marker(tmp_path, sha):
    with pytest.raises(ValueError, match="full Git commit"):
        acceptance.release_report(tmp_path, sha)
