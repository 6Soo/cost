import json
from urllib.parse import urlparse

import pytest

from webapp import google_demo_page as page


def trip(key, net, **over):
    base = {"key": key, "closure": "closed", "closure_current": True, "canonical_source": "archive",
            "income_total": net + 100, "expense_total": 100, "net": net, "verified": True, "review": []}
    base.update(over)
    return base


def snap(trips, *, synthetic=True, status="ok"):
    doc = {"synced_at": "2026-10-11T10:00:00+09:00", "sources": {"main": {"status": status}},
           "trips": trips}
    if synthetic:
        doc["synthetic"] = True
    return doc


class FakeHandler:
    def __init__(self):
        self.sent = []

    def _send_json(self, value, code=200, extra_headers=None):
        self.sent.append(("json", code, value))

    def _send(self, text, code=200):
        self.sent.append(("html", code, text))


@pytest.fixture
def demo_file(tmp_path, monkeypatch):
    path = tmp_path / "demo-snapshot.json"
    path.write_text(json.dumps(snap([trip("SYN-A", 900), trip("SYN-B", 700), trip("SYN-C", 500),
                                     trip("SYN-D", 100)])), encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_DEMO_SNAPSHOT", str(path))
    return path


def get(path):
    handler = FakeHandler()
    assert page.dispatch(handler, urlparse(path)) is True
    return handler.sent[0]


def test_off_without_setting(monkeypatch):
    monkeypatch.delenv("WEBLEDGER_DEMO_SNAPSHOT", raising=False)
    assert page.dispatch(FakeHandler(), urlparse("/api/demo/top3")) is False


def test_real_snapshot_without_synthetic_flag_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "real.json"
    path.write_text(json.dumps(snap([trip("REAL", 1)], synthetic=False)), encoding="utf-8")
    monkeypatch.setenv("WEBLEDGER_DEMO_SNAPSHOT", str(path))
    kind, code, body = get("/api/demo/top3")
    assert code == 503 and body["code"] == "DEMO_NOT_SYNTHETIC"


def test_json_carries_rank_and_amounts_but_no_titles_or_keys(demo_file):
    _, code, body = get("/api/demo/top3")
    assert code == 200 and [e["net"] for e in body["entries"]] == [900, 700, 500]
    text = json.dumps(body, ensure_ascii=False)
    assert "SYN-" not in text and "key" not in body["entries"][0] and "sheet" not in text


def test_html_has_no_titles(demo_file):
    _, code, html_text = get("/demo")
    assert code == 200 and "SYN-" not in html_text and "900원" in html_text


def test_failed_sync_shows_the_last_safe_ranking_marked_stale(demo_file):
    get("/api/demo/top3")  # stores the safe payload
    demo_file.write_text(json.dumps(snap([trip("SYN-A", 1)], status="error")), encoding="utf-8")
    _, code, body = get("/api/demo/top3")
    assert body["stale"] is True and [e["net"] for e in body["entries"]] == [900, 700, 500]


def test_write_methods_are_refused(demo_file):
    handler = FakeHandler()
    page.dispatch(handler, urlparse("/api/demo/top3"), raw=b"{}")
    assert handler.sent[0][:2] == ("json", 405)


def test_other_paths_are_not_ours(demo_file):
    assert page.dispatch(FakeHandler(), urlparse("/import")) is False
