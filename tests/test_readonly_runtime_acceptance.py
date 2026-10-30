import json

import pytest

from tools import readonly_runtime_acceptance as acceptance


def test_release_report_only_exposes_sha_match_and_launcher_digest(tmp_path):
    launcher = tmp_path / "tools" / "launch_web_ledger.py"
    launcher.parent.mkdir()
    launcher.write_bytes(b"synthetic launcher")
    (tmp_path / "DEPLOYED_COMMIT").write_text("abc123\n", encoding="ascii")
    report = acceptance.release_report(tmp_path, "abc123")
    assert report["marker_matches_expected"] is True
    assert report["launcher_exists"] is True
    assert report["launcher_sha256"] == acceptance.hashlib.sha256(b"synthetic launcher").hexdigest()
    assert "abc123" not in json.dumps(report)


def test_http_probe_limits_targets_and_aggregates_without_body(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size):
            assert size == 65536
            return b"sensitive fixture body"

    monkeypatch.setattr(acceptance.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    report = acceptance.probe_http(("http://127.0.0.1:8765/ready",), samples=2)
    row = report["results"][0]
    assert row["status_counts"] == {"200": 2}
    assert row["response_body_retained"] is False
    assert "sensitive fixture body" not in json.dumps(report)
    with pytest.raises(ValueError):
        acceptance.probe_http(("http://example.com/ready",), samples=1)
    with pytest.raises(ValueError):
        acceptance.probe_http(samples=21)


def test_task_report_never_returns_action_or_principal(monkeypatch):
    from types import SimpleNamespace
    class Principal:
        RunLevel = 1
        LogonType = 3
        UserId = "sensitive-user"
    class Actions:
        Count = 1
        Item = lambda self, i: (_ for _ in ()).throw(AssertionError("action inspected"))
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
    report = acceptance.scheduled_task_report(client=client)
    assert report["registered"] and report["enabled"]
    assert report["arguments_inspected"] is False
    assert "sensitive-user" not in json.dumps(report)
