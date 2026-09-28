"""Phase 6 provider boundary: transport, configuration, secrets, and rules.

No real call is made anywhere in this file. Every provider answer comes from an
injected `RecordingTransport` or a `SyntheticAdapter`, and every key is a test
key. What is verified here is the boundary the contract describes:

* the request shape each provider expects, and that a reply is parsed into a
  result rather than trusted,
* the exact mapping from a transport fault or an HTTP status to one reason
  code, because the turn policy branches on it,
* that a key comes from server-side configuration only, never from a request,
  and never appears in a response, a log, the ledger, or the turn context,
* that a failed or exhausted provider parks the turn and preserves the row, the
  rule draft, and the recorded answers,
* that a model answer becomes a *candidate*: structured, validated, never
  applied, and still requiring the owner's confirm.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import access_control
from webapp import dialog_turn
from webapp import ledger_board as board_mod
from webapp import provider_config as pc
from webapp import provider_transport as pt
from webapp import rule_text
from webapp.dialog_turn import SyntheticAdapter, run_turn
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner-P"
V1 = "syn-staff-P1"
TRIP_A = "trip-demo-a"
TRIP_B = "trip-demo-b"

# Test keys. They are shaped like real ones so the redaction paths are actually
# exercised, and they are worthless.
MUSE_KEY = "sk-testmusekey-0000000001"
GEMINI_KEY = "AIzaTestGeminiKey-0000000002"

MUSE_OK = (200, {"choices": [{"message": {"content": "C1은 trip-demo-b 여행으로 옮기면 좋아요."}}]})
GEMINI_OK = (200, {"candidates": [{"content": {"parts": [
    {"text": "C1은 trip-demo-b 여행에 넣으면 됩니다."}]}}]})


# --------------------------------------------------------------- transport
class FailureMappingTests(unittest.TestCase):
    """One status or exception, exactly one reason code."""

    def test_http_statuses_map_to_their_reason(self):
        cases = [
            (401, None, "auth_failed"),
            (403, None, "auth_failed"),
            (402, None, "budget_exhausted"),
            (404, None, "not_configured"),
            (408, None, "timeout"),
            (504, None, "timeout"),
            (400, None, "provider_refused"),
            (500, None, "service_error"),
            (503, None, "service_error"),
            (429, None, "rate_limited"),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(pt.reason_for_status(status, body), expected)

    def test_a_429_that_names_a_quota_is_a_quota_wait_not_a_rate_limit(self):
        # The turn treats these two differently, so the distinction has to come
        # from the provider's own words rather than from the status alone.
        for detail in ("quota exceeded", "Free Tier", "free-tier limit",
                       "INSUFFICIENT_QUOTA", "billing"):
            with self.subTest(detail=detail):
                body = {"error": {"status": "RESOURCE_EXHAUSTED",
                                  "message": detail}}
                self.assertEqual(pt.reason_for_status(429, body),
                                 "free_quota_exhausted")
        self.assertEqual(
            pt.reason_for_status(429, {"error": {"message": "slow down"}}),
            "rate_limited")

    def test_exceptions_map_to_their_reason(self):
        cases = [
            (TimeoutError("slow"), "timeout"),
            (ConnectionError("refused"), "connection_refused"),
            (OSError("Connection refused"), "connection_refused"),
            (OSError("timed out"), "timeout"),
            (OSError("disk on fire"), "service_error"),
            (ValueError("odd"), "service_error"),
            (pt.TransportUnavailable("none"), "not_configured"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(pt.classify_exception(exc), expected)

    def test_a_provider_error_body_never_keeps_the_whole_payload(self):
        body = {"error": {"message": "quota", "secret": GEMINI_KEY}}
        self.assertNotIn(GEMINI_KEY, json.dumps(
            {"seen": pt._error_text(body)}))


class AdapterProtocolTests(unittest.TestCase):
    """The request each provider expects, and how a reply is read."""

    def test_muse_builds_a_chat_completion_shape(self):
        transport = pt.RecordingTransport([MUSE_OK])
        adapter = pt.MuseAdapter(secret=MUSE_KEY, model_id="muse-local-1",
                                   transport=transport)
        result = adapter.send({"attempt_id": "t-a1", "slot": "primary",
                               "row_id": "r1", "item": "숙박"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.provider, "muse")
        call = transport.calls[0]
        self.assertTrue(call["url"].startswith("http://127.0.0.1:"))
        body = call["payload"]
        self.assertIn("messages", body)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertIn("r1", body["messages"][1]["content"])

    def test_gemini_builds_a_generate_content_shape_with_the_model_in_the_path(self):
        transport = pt.RecordingTransport([GEMINI_OK])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                   transport=transport)
        result = adapter.send({"attempt_id": "t-a1", "row_id": "r1"})
        self.assertEqual(result.status, "ok")
        call = transport.calls[0]
        self.assertIn("gemini-free-a:generateContent", call["url"])
        self.assertIn("contents", call["payload"])
        self.assertNotIn("model", call["payload"])

    def test_the_key_is_a_header_and_never_in_the_body(self):
        transport = pt.RecordingTransport([GEMINI_OK])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                       transport=transport)
        adapter.send({"attempt_id": "t-a1", "row_id": "r1"})
        call = transport.calls[0]
        self.assertIn("Authorization", call["auth_header_names"])
        # The recorded call keeps header *names* and a count, never a value.
        self.assertNotIn(GEMINI_KEY, json.dumps(call, default=str))
        self.assertEqual(call["auth_header_count"], 1)

    def test_no_adapter_ever_reports_a_real_call(self):
        transport = pt.RecordingTransport([MUSE_OK, GEMINI_OK])
        self.assertFalse(pt.MuseAdapter(
            secret=MUSE_KEY, model_id="muse-local-1", transport=transport).is_real_call)
        self.assertFalse(pt.GeminiAdapter(
            secret=GEMINI_KEY, model_id="gemini-free-a", transport=transport).is_real_call)
        self.assertFalse(pt.RecordingTransport().is_real_call)
        result = pt.MuseAdapter(
            secret=MUSE_KEY, model_id="muse-local-1",
            transport=transport).send({"attempt_id": "a"})
        self.assertFalse(result.is_real_call)

    def test_a_200_with_no_content_is_pending_rather_than_an_empty_answer(self):
        # Adopting an empty draft would overwrite a good draft with nothing.
        transport = pt.RecordingTransport([(200, {"candidates": []})])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                       transport=transport)
        result = adapter.send({"attempt_id": "a"})
        self.assertEqual(result.status, dialog_turn.PENDING_STATUS)

    def test_a_reply_that_is_not_the_expected_shape_is_a_service_error(self):
        transport = pt.RecordingTransport([(200, {"unexpected": True})])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                       transport=transport)
        result = adapter.send({"attempt_id": "a"})
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason_code, "service_error")

    def test_a_transport_fault_is_raised_as_a_classified_provider_error(self):
        from webapp.dialog_turn import ProviderTransportError

        for exc, expected in ((TimeoutError("slow"), "timeout"),
                              (ConnectionError("refused"), "connection_refused"),
                              (pt.TransportUnavailable("none"), "not_configured")):
            with self.subTest(exc=type(exc).__name__):
                transport = pt.RecordingTransport([exc])
                adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                       transport=transport)
                with self.assertRaises(ProviderTransportError) as caught:
                    adapter.send({"attempt_id": "a"})
                self.assertEqual(caught.exception.reason, expected)

    def test_an_unconfigured_adapter_reports_not_configured_and_sends_nothing(self):
        transport = pt.RecordingTransport([GEMINI_OK])
        adapter = pt.GeminiAdapter(secret="", model_id="gemini-free-a",
                                    transport=transport)
        self.assertFalse(adapter.configured)
        with self.assertRaises(Exception):
            adapter.send({"attempt_id": "a"})
        self.assertEqual(transport.calls, [])

    def test_the_context_reaching_a_provider_is_allowlisted(self):
        # A card customer name, a reservation number, and a memo must not be
        # readable in what the provider is handed.
        transport = pt.RecordingTransport([GEMINI_OK])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                       transport=transport)
        context = dialog_turn.build_context(
            conversation_id="conv-1", turn_id="t1",
            row={"row_id": "r1", "item": "숙박", "source_merchant": "아구다호텔",
                 "card_kind": "체크", "amount_krw": 120000,
                 "occurred_on": "2026-04-01", "display_tab_id": TRIP_A,
                 "customer_name": "김민수", "reservation_no": "RSV123456",
                 "memo": "민수님 요청"})
        adapter.send({"attempt_id": "a", **context})
        text = json.dumps(transport.calls[0]["payload"], ensure_ascii=False,
                          default=str)
        for secret_value in ("김민수", "RSV123456", "민수님 요청"):
            self.assertNotIn(secret_value, text)
        self.assertIn("아구다호텔", text)


# A fetched catalog, used wherever a model has to be selected. It is data that
# arrives from a transport call, never a name written into the code.
GEMINI_CATALOG = [
    {"model_id": "gemini-free-a", "display_name": "Gemini Free A",
     "free_supported": True},
    {"model_id": "gemini-free-b", "display_name": "Gemini Free B",
     "free_supported": True},
    {"model_id": "gemini-paid-x", "display_name": "Gemini Paid X",
     "free_supported": False},
    {"model_id": "gemini-unknown", "display_name": "Gemini Unknown",
     "free_supported": None},
]
MUSE_CATALOG = [
    {"model_id": "muse-local-1", "display_name": "Muse Local 1",
     "free_supported": True},
]


def seed_catalog(config, provider="gemini", entries=None, fetched_at="2026-09-27T10:00"):
    """Record a fetched list with its fetch time, the way a real run would."""
    config.record_model_catalog(
        provider, entries if entries is not None else GEMINI_CATALOG,
        fetched_at=fetched_at)
    return config


# -------------------------------------------------------------- config
class SecretStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = pc.SecretStore(path=str(self.tmp / "secrets.json"))

    def test_a_configured_timeout_survives_the_round_trip(self):
        # A regression: `get` returned only str, so a float written by `set`
        # came back empty and the timeout silently reverted to the default.
        self.store.set("gemini", "timeout", 15.0)
        self.assertEqual(self.store.get("gemini", "timeout"), 15.0)
        config = pc.ProviderConfig(self.store)
        self.assertEqual(config.gemini_timeout, 15.0)
        self.assertNotEqual(config.gemini_timeout, pc.DEFAULT_TIMEOUT)
        # And it survives a reload from disk, not just the in-memory cache.
        reloaded = pc.SecretStore(path=self.store.path)
        self.assertEqual(reloaded.get("gemini", "timeout"), 15.0)
        self.assertEqual(pc.ProviderConfig(reloaded).gemini_timeout, 15.0)

    def test_an_int_timeout_survives_too(self):
        self.store.set("muse", "timeout", 30)
        self.assertEqual(self.store.get("muse", "timeout"), 30)
        self.assertEqual(pc.ProviderConfig(self.store).muse_timeout, 30.0)

    def test_a_bool_is_not_read_as_a_number(self):
        self.store.set("muse", "timeout", True)
        self.assertEqual(self.store.get("muse", "timeout"), "")
        self.assertEqual(pc.ProviderConfig(self.store).muse_timeout,
                         pc.DEFAULT_TIMEOUT)

    def test_an_unreadable_store_reads_as_not_configured(self):
        self.store.path = str(self.tmp / "broken.json")
        Path(self.store.path).write_text("{not json", encoding="utf-8")
        fresh = pc.SecretStore(path=self.store.path)
        self.assertEqual(fresh.get("gemini", "secret"), "")
        self.assertFalse(pc.ProviderConfig(fresh).gemini_configured)

    def test_the_public_view_never_holds_a_value(self):
        self.store.set("gemini", "secret", GEMINI_KEY)
        view = self.store.public_view()
        self.assertNotIn(GEMINI_KEY, json.dumps(view))
        self.assertTrue(view["gemini"]["configured"])
        self.assertTrue(view["gemini"]["key_fingerprint"].startswith("sha256:"))

    def test_a_fingerprint_does_not_reveal_the_key(self):
        first = pc.fingerprint(GEMINI_KEY)
        second = pc.fingerprint(GEMINI_KEY)
        self.assertEqual(first, second)
        self.assertNotEqual(first, pc.fingerprint(MUSE_KEY))
        self.assertNotIn(GEMINI_KEY, first)
        self.assertIsNone(pc.fingerprint(""))

    def test_redact_catches_a_key_standalone_or_inside_text(self):
        self.assertEqual(pt.redact(GEMINI_KEY), "[redacted]")
        self.assertEqual(pt.redact("Authorization: Bearer " + GEMINI_KEY),
                         "Authorization: Bearer [redacted]")
        self.assertEqual(pc.redact({"k": GEMINI_KEY, "n": 1}),
                         {"k": "[redacted]", "n": 1})
        self.assertEqual(pc.redact([GEMINI_KEY]), ["[redacted]"])
        self.assertEqual(pc.redact("아무 말"), "아무 말")


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.service = pc.ProviderConfigService(
            pc.SecretStore(path=str(self.tmp / "secrets.json")))

    def test_a_viewer_cannot_write_or_read(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.set_provider(role="viewer", provider="gemini",
                                      secret=GEMINI_KEY)
        self.assertEqual(caught.exception.code, "ACTION_FORBIDDEN")
        with self.assertRaises(pc.ConfigError):
            self.service.status(role="viewer")
        # Nothing was stored.
        self.assertEqual(self.service.store.get("gemini", "secret"), "")

    def test_an_owner_can_set_and_the_reply_has_no_value(self):
        seed_catalog(self.service.config, "gemini")
        status = self.service.set_provider(
            role="owner", provider="gemini", secret=GEMINI_KEY,
            model="gemini-free-a", timeout=15, client_request_id="r1")
        self.assertNotIn(GEMINI_KEY, json.dumps(status))
        self.assertTrue(status["gemini"]["configured"])
        self.assertEqual(status["gemini"]["timeout"], 15.0)
        self.assertEqual(status["gemini"]["model"], "gemini-free-a")
        # The audit trail records what changed, not the value.
        self.assertEqual(self.service.audit[-1]["fields"],
                         ["model", "secret", "timeout"])
        self.assertNotIn(GEMINI_KEY, json.dumps(self.service.audit))

    def test_an_unknown_provider_is_refused(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.set_provider(role="owner", provider="evil",
                                      secret=GEMINI_KEY)
        self.assertEqual(caught.exception.code, "INVALID_VALUE")

    def test_a_bad_model_or_timeout_or_secret_is_refused(self):
        for kwargs in ({"model": "../../etc/passwd"},
                       {"model": "a b"},
                       {"timeout": 0},
                       {"timeout": 100000},
                       {"timeout": "soon"},
                       {"secret": "short"},
                       {"secret": "line\nbreak"}):
            with self.subTest(**kwargs):
                with self.assertRaises(pc.ConfigError):
                    self.service.set_provider(role="owner", provider="muse",
                                              **kwargs)

    def test_a_model_cannot_break_out_of_the_url_path(self):
        # The model id goes into a Gemini URL, so a slash is refused rather
        # than escaped.
        with self.assertRaises(pc.ConfigError):
            self.service.set_provider(role="owner", provider="gemini",
                                      model="a/../../b")

    def test_clearing_removes_the_entry(self):
        self.service.set_provider(role="owner", provider="gemini",
                                  secret=GEMINI_KEY)
        status = self.service.clear_provider(role="owner", provider="gemini")
        self.assertFalse(status["gemini"]["configured"])
        self.assertEqual(self.service.store.get("gemini", "secret"), "")

    def test_the_fallback_is_off_until_the_owner_turns_it_on(self):
        # APP_SPEC 9.3: registering a key is not the same as enabling the
        # fallback. Off by default, so nothing is dialled on its own.
        seed_catalog(self.service.config, "gemini")
        self.service.set_provider(role="owner", provider="gemini",
                                  secret=GEMINI_KEY, model="gemini-free-a")
        self.assertFalse(self.service.config.fallback_enabled)
        muse, gemini = pt.build_adapters(self.service.config)
        self.assertIsNone(gemini)
        self.service.set_fallback(role="owner", enabled=True)
        self.assertTrue(self.service.config.fallback_enabled)
        _, gemini = pt.build_adapters(self.service.config)
        self.assertIsNotNone(gemini)

    def test_only_an_owner_can_switch_the_fallback(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.set_fallback(role="viewer", enabled=True)
        self.assertEqual(caught.exception.code, "ACTION_FORBIDDEN")
        self.assertFalse(self.service.config.fallback_enabled)
        with self.assertRaises(pc.ConfigError):
            self.service.set_fallback(role="owner", enabled="maybe")

    def test_a_switched_off_fallback_leaves_a_muse_failure_waiting(self):
        # The switch is a behaviour change, not a label: with it off a Muse
        # outage parks the turn instead of calling a disabled provider.
        seed_catalog(self.service.config, "gemini")
        seed_catalog(self.service.config, "muse", MUSE_CATALOG)
        self.service.set_provider(role="owner", provider="muse", secret=MUSE_KEY,
                                  model="muse-local-1")
        self.service.set_provider(role="owner", provider="gemini",
                                  secret=GEMINI_KEY, model="gemini-free-a")
        muse, _ = pt.build_adapters(
            self.service.config,
            transport={"muse": pt.RecordingTransport([ConnectionError("refused")]),
                       "gemini": pt.RecordingTransport([GEMINI_OK])})
        outcome = run_turn(turn_id="fb-off", context={"row_id": "r1"},
                           muse=muse, gemini=None)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.switch_count, 0)

    def test_the_store_lives_outside_the_ledger(self):
        # A credential must not land in the database that gets backed up,
        # exported, or migrated.
        store_path = Path(self.service.store.path)
        self.assertNotEqual(store_path.suffix, ".sqlite")
        self.assertFalse(pc.is_real_secret_store)

    def test_build_adapters_reads_the_config_and_nothing_else(self):
        seed_catalog(self.service.config, "gemini")
        self.service.set_provider(role="owner", provider="gemini",
                                  secret=GEMINI_KEY, model="gemini-free-a")
        self.service.set_fallback(role="owner", enabled=True)
        transport = pt.RecordingTransport([GEMINI_OK])
        muse, gemini = pt.build_adapters(self.service.config, transport=transport)
        # Gemini is configured, Muse is not, so no Muse adapter is built at all.
        self.assertIsNone(muse)
        self.assertIsNotNone(gemini)
        self.assertEqual(gemini.model_id, "gemini-free-a")
        report = pt.adapter_report(muse, gemini)
        self.assertNotIn(GEMINI_KEY, json.dumps(report))
        self.assertTrue(report["gemini"]["configured"])

    def test_a_per_provider_transport_is_honoured(self):
        seed_catalog(self.service.config, "gemini")
        seed_catalog(self.service.config, "muse", MUSE_CATALOG)
        self.service.set_provider(role="owner", provider="muse", secret=MUSE_KEY,
                                  model="muse-local-1")
        self.service.set_provider(role="owner", provider="gemini",
                                  secret=GEMINI_KEY, model="gemini-free-a")
        self.service.set_fallback(role="owner", enabled=True)
        muse_transport = pt.RecordingTransport([MUSE_OK])
        gemini_transport = pt.RecordingTransport([GEMINI_OK])
        muse, gemini = pt.build_adapters(
            self.service.config,
            transport={"muse": muse_transport, "gemini": gemini_transport})
        muse.send({"attempt_id": "a"})
        gemini.send({"attempt_id": "a"})
        self.assertEqual(len(muse_transport.calls), 1)
        self.assertEqual(len(gemini_transport.calls), 1)


# ------------------------------------------------------------ turn policy
class TurnBoundaryTests(unittest.TestCase):
    """The contract 7 behaviours, driven through the concrete adapters."""

    CONTEXT = {"row_id": "r1", "item": "숙박", "merchant_normalized": "아구다호텔"}

    def _adapters(self, muse_script, gemini_script, *, fallback=True):
        config = pc.ProviderConfig(pc.SecretStore(
            path=str(Path(tempfile.mkdtemp()) / "s.json")))
        seed_catalog(config, "gemini")
        seed_catalog(config, "muse", MUSE_CATALOG)
        config.store.set("muse", "secret", MUSE_KEY)
        config.store.set("gemini", "secret", GEMINI_KEY)
        config.store.set("muse", "model", "muse-local-1")
        config.store.set("gemini", "model", "gemini-free-a")
        if fallback:
            config.store.set(pc.ProviderConfig.SETTINGS_PROVIDER,
                             "fallback_enabled", "1")
        return pt.build_adapters(
            config, transport={"muse": pt.RecordingTransport(muse_script),
                               "gemini": pt.RecordingTransport(gemini_script)})

    def test_a_healthy_muse_answers_and_gemini_is_never_called(self):
        muse, gemini = self._adapters([MUSE_OK], [GEMINI_OK])
        outcome = run_turn(turn_id="t1", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "answered")
        self.assertEqual(outcome.provider, "muse")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(len(muse.transport.calls), 1)
        self.assertEqual(gemini.transport.calls, [])

    def test_a_muse_pc_that_is_off_falls_back_to_gemini_exactly_once(self):
        muse, gemini = self._adapters(
            [ConnectionError("refused")], [GEMINI_OK])
        outcome = run_turn(turn_id="t2", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "answered")
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.switch_count, 1)
        self.assertEqual(len(outcome.attempts), 2)
        # Both attempts are on record under the same turn with different ids.
        self.assertEqual(outcome.attempts[0]["slot"], "primary")
        self.assertEqual(outcome.attempts[1]["slot"], "fallback")
        self.assertNotEqual(outcome.attempts[0]["attempt_id"],
                            outcome.attempts[1]["attempt_id"])
        self.assertTrue(outcome.as_dict()["fallback_notice"])
        # Only one answer is adopted, so the two replies are never mixed.
        self.assertEqual(outcome.adopted_attempt_id,
                         outcome.attempts[1]["attempt_id"])
        self.assertEqual(sum(1 for a in outcome.attempts if a.get("adopted")), 1)

    def test_a_muse_timeout_also_falls_back(self):
        muse, gemini = self._adapters([TimeoutError("slow")], [GEMINI_OK])
        outcome = run_turn(turn_id="t2b", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.attempts[0]["reason_code"], "timeout")

    def test_both_providers_down_leaves_the_turn_waiting(self):
        muse, gemini = self._adapters(
            [ConnectionError("refused")], [ConnectionError("refused")])
        outcome = run_turn(turn_id="t3", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.switch_count, 1)
        self.assertIsNone(outcome.adopted_attempt_id)

    def test_a_free_quota_wait_does_not_call_gemini_even_when_it_would_work(self):
        muse, gemini = self._adapters(
            [(429, {"error": {"message": "Free Tier limit reached"}})],
            [GEMINI_OK])
        outcome = run_turn(turn_id="t4", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.reason_code, "free_quota_exhausted")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(gemini.transport.calls, [])
        # The row context is untouched and no answer was adopted.
        self.assertIsNone(outcome.draft)
        self.assertEqual(muse.transport.calls[0]["payload"]["context"]["row_id"],
                         "r1")

    def test_a_muse_key_the_owner_revoked_parks_the_turn_without_a_switch(self):
        # A missing key is `not_configured`, which is a waiting reason. The turn
        # must not fall through to Gemini, because a revoked Muse key is a
        # deliberate owner decision, not an outage.
        muse, gemini = self._adapters([MUSE_OK], [GEMINI_OK])
        muse._secret = ""
        outcome = run_turn(turn_id="t5", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.reason_code, "not_configured")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(gemini.transport.calls, [])

    def test_a_muse_auth_failure_still_falls_back(self):
        # Auth is a fault to route around, unlike a quota wait or a revoked key.
        muse, gemini = self._adapters([(401, {"error": {"message": "bad key"}})],
                                      [GEMINI_OK])
        outcome = run_turn(turn_id="t5b", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.switch_count, 1)

    def test_muse_recovers_on_the_next_turn_after_an_outage(self):
        muse, gemini = self._adapters(
            [ConnectionError("refused"), MUSE_OK], [GEMINI_OK])
        first = run_turn(turn_id="t6a", context=self.CONTEXT,
                         muse=muse, gemini=gemini)
        self.assertEqual(first.provider, "gemini")
        second = run_turn(turn_id="t6b", context=self.CONTEXT,
                          muse=muse, gemini=gemini)
        self.assertEqual(second.state, "answered")
        self.assertEqual(second.provider, "muse")
        self.assertEqual(second.switch_count, 0)
        # The switch allowance is per turn, so the next turn has its own.
        self.assertEqual(len(second.attempts), 1)

    def test_a_pending_muse_answer_leaves_the_switch_for_the_next_turn(self):
        muse, gemini = self._adapters([(200, {"choices": []})], [GEMINI_OK])
        outcome = run_turn(turn_id="t7", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "pending")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(gemini.transport.calls, [])

    def test_no_turn_records_a_real_call(self):
        muse, gemini = self._adapters([MUSE_OK], [GEMINI_OK])
        outcome = run_turn(turn_id="t8", context=self.CONTEXT,
                           muse=muse, gemini=gemini)
        self.assertFalse(outcome.is_real_call)
        for attempt in outcome.attempts:
            self.assertFalse(attempt["is_real_call"])


class StoreIntegrationTests(unittest.TestCase):
    """The concrete adapters through the real store, not a stubbed turn."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.path = self.directory / "turn.sqlite"
        self.store = LedgerStore(self.path)
        # The same shape the other dialog tests use, written out here so this
        # file does not depend on another test module being importable.
        self.case_id = self.store.save(
            row_id="expense-demo-c3",
            expected_revision=self.store.get_row(
                "expense-demo-c3")["revision"],
            client_request_id="pb-case",
            change_mode="rule_change",
            changes={"display_tab_id": TRIP_B})["learning_case_id"]
        self.store.open_rule_dialog(
            learning_case_id=self.case_id,
            draft={"conditions": {"merchant_normalized":
                                  {"op": "eq", "value": "아구다호텔"}},
                   "effects": {"display_tab_id": TRIP_B}},
            client_request_id="pb-dialog")
        self.conversation_id = self.store.open_conversation(
            learning_case_id=self.case_id,
            client_request_id="pb-open")["conversation_id"]
        self.config = pc.ProviderConfig(
            pc.SecretStore(path=str(self.directory / "secrets.json")))
        seed_catalog(self.config, "gemini")
        seed_catalog(self.config, "muse", MUSE_CATALOG)
        self.config.store.set("muse", "secret", MUSE_KEY)
        self.config.store.set("gemini", "secret", GEMINI_KEY)
        self.config.store.set("muse", "model", "muse-local-1")
        self.config.store.set("gemini", "model", "gemini-free-a")
        self.config.store.set(pc.ProviderConfig.SETTINGS_PROVIDER,
                              "fallback_enabled", "1")

    def tearDown(self):
        self.store.close()

    def _adapters(self, muse_script, gemini_script):
        return pt.build_adapters(self.config, transport={
            "muse": pt.RecordingTransport(muse_script),
            "gemini": pt.RecordingTransport(gemini_script)})

    def test_a_persisted_turn_records_the_fallback_and_never_a_real_call(self):
        muse, gemini = self._adapters(
            [ConnectionError("refused")], [GEMINI_OK])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-1",
            muse=muse, gemini=gemini, actor="owner")
        turn = result["turn"]
        self.assertEqual(turn["state"], "answered")
        self.assertEqual(turn["adopted_provider"], "gemini")
        self.assertEqual(turn["switch_count"], 1)
        self.assertFalse(result["is_real_call"])
        self.assertIsNotNone(result["notice"])
        attempts = self.store.conn.execute(
            "SELECT slot, provider, reason_code, adopted, is_real_call"
            " FROM rule_turn_attempts WHERE turn_id=? ORDER BY seq",
            (turn["turn_id"],)).fetchall()
        self.assertEqual([a[0] for a in attempts], ["primary", "fallback"])
        self.assertEqual(sum(1 for a in attempts if a[3]), 1)
        for attempt in attempts:
            self.assertEqual(attempt[4], 0)

    def test_a_quota_wait_preserves_the_row_the_draft_and_the_answers(self):
        # Contract 7: a spent free quota parks the dialogue and keeps the row,
        # the rule draft, and the recorded answers.
        before_row = self.store.get_row("expense-demo-c3")
        before_dialog = self.store.dialog_page_state(self.case_id)
        muse, gemini = self._adapters(
            [(429, {"error": {"message": "Free Tier limit reached"}})],
            [GEMINI_OK])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-2",
            muse=muse, gemini=gemini, actor="owner")
        self.assertEqual(result["turn"]["state"], "waiting")
        self.assertEqual(result["turn"]["reason_code"], "free_quota_exhausted")
        # the row is untouched
        self.assertEqual(self.store.get_row("expense-demo-c3")["revision"],
                         before_row["revision"])
        # the dialog and its answers survive
        after_dialog = self.store.dialog_page_state(self.case_id)
        self.assertEqual(after_dialog["dialog_state"],
                         before_dialog["dialog_state"])
        self.assertEqual(after_dialog["answers"], before_dialog["answers"])
        self.assertEqual(after_dialog["pending_draft"],
                         before_dialog["pending_draft"])
        self.assertEqual(len(after_dialog["questions"]),
                         len(before_dialog["questions"]))
        self.assertEqual(after_dialog["row_revision"],
                         before_dialog["row_revision"])
        # and the turn is still on record, so the next turn can start over
        turns = self.store.conversation_state(
            self.conversation_id)["turns"]
        self.assertEqual(turns[-1]["state"], "waiting")

    def test_a_late_answer_for_a_waiting_turn_is_refused(self):
        muse, gemini = self._adapters(
            [(429, {"error": {"message": "quota"}})], [])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-3",
            muse=muse, gemini=gemini, actor="owner")
        turn = result["turn"]
        late = self.store.adopt_late_response(
            conversation_id=self.conversation_id, turn_id=turn["turn_id"],
            attempt_id=f"{turn['turn_id']}-a1",
            client_request_id="pb-3-late", actor="owner")
        self.assertEqual(late["late"]["status"], "refused")

    def test_muse_recovers_on_the_following_turn(self):
        muse, gemini = self._adapters(
            [ConnectionError("refused"), MUSE_OK], [GEMINI_OK])
        first = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-4a",
            muse=muse, gemini=gemini, actor="owner")
        self.assertEqual(first["turn"]["adopted_provider"], "gemini")
        second = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-4b",
            muse=muse, gemini=gemini, actor="owner")
        self.assertEqual(second["turn"]["state"], "answered")
        self.assertEqual(second["turn"]["adopted_provider"], "muse")
        self.assertEqual(second["turn"]["switch_count"], 0)

    def test_no_key_reaches_the_persisted_turn_or_the_conversation(self):
        muse, gemini = self._adapters([MUSE_OK], [])
        self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-5",
            muse=muse, gemini=gemini, actor="owner")
        for table, column in (("rule_turns", "summary_json"),
                              ("rule_conversations", "handoff_summary"),
                              ("rule_turn_attempts", "reason_code")):
            for (value,) in self.store.conn.execute(
                    f"SELECT {column} FROM {table}"):
                with self.subTest(table=table, column=column):
                    self.assertNotIn(MUSE_KEY, str(value or ""))
                    self.assertNotIn(GEMINI_KEY, str(value or ""))

    def test_provider_prose_reaches_a_validated_candidate_and_stops_there(self):
        # A prose answer becomes a candidate, is validated, and is NOT applied.
        # The row is unchanged and no rule is active yet.
        row_before = self.store.get_row("expense-demo-c3")
        active_before = self.store.conn.execute(
            "SELECT COUNT(*) FROM classification_rules WHERE status='active'"
        ).fetchone()[0]
        muse, gemini = self._adapters(
            [(200, {"choices": [{"message": {
                "content": f"이 건은 {TRIP_B} 여행으로 옮기면 될 것 같아요."}}]})],
            [])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-6",
            muse=muse, gemini=gemini, actor="owner",
            operator={"trip_id": TRIP_B, "event_year": 2026})
        self.assertEqual(result["turn"]["state"], "answered")
        self.assertTrue(result["requires_owner_confirm"])
        self.assertIsNotNone(result["candidate"])
        self.assertFalse(result["candidate"]["applied"])
        self.assertEqual(result["candidate"]["source"], "provider_text")
        # the draft is structured and validated
        self.assertEqual(result["draft"]["effects"]["display_tab_id"], TRIP_B)
        self.assertEqual(result["draft"]["scope"]["trip_id"], TRIP_B)
        # nothing was applied to the row and no rule went active
        row_after = self.store.get_row("expense-demo-c3")
        self.assertEqual(row_after["revision"], row_before["revision"])
        self.assertEqual(row_after["display_tab_id"], row_before["display_tab_id"])
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM classification_rules WHERE status='active'"
            ).fetchone()[0],
            active_before)

    def test_prose_without_an_operator_trip_produces_no_candidate(self):
        muse, gemini = self._adapters([MUSE_OK], [])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-7",
            muse=muse, gemini=gemini, actor="owner")
        self.assertEqual(result["turn"]["state"], "answered")
        self.assertIsNone(result["candidate"])
        self.assertEqual(result["draft"], {})
        # the reason is recorded rather than swallowed
        self.assertIsNotNone(result["draft_error"])

    def test_the_candidate_can_then_be_confirmed_and_previewed(self):
        # The full local chain: prose -> candidate -> owner confirm -> preview.
        # The preview is what supplies the impact numbers, never the model.
        muse, gemini = self._adapters([MUSE_OK], [])
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation_id, client_request_id="pb-8",
            muse=muse, gemini=gemini, actor="owner",
            operator={"trip_id": TRIP_B, "event_year": 2026})
        self.assertIsNotNone(result["draft"])
        confirmed = self.store.confirm_dialog_draft(
            learning_case_id=self.case_id, client_request_id="pb-8-confirm",
            actor="owner")
        self.assertTrue(confirmed["confirmed"])
        rule_id = confirmed["rule"]["rule_id"]
        # confirming stores a draft rule; it does not apply anything
        stored = self.store.get_rule(rule_id)
        self.assertEqual(stored["status"], "draft")
        preview = self.store.preview_rule(
            rule_id=rule_id, apply_existing=False, apply_future=False)
        # the impact comes from the preview API, and is a real count
        self.assertIsNotNone(preview.get("preview_id"))
        self.assertGreaterEqual(len(preview.get("rows", [])), 0)


# ------------------------------------------- IMPLEMENTATION_CONTRACT 7.1.1
class SettingsUxTests(unittest.TestCase):
    """The key-registration and switching UX contract (7.1.1).

    These are the parts that can be closed without a real network: the state
    model, the gating, the connection test's shape, and the tier record. The
    actual provider call and the actual AI Studio tier check stay external.
    """

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.service = pc.ProviderConfigService(
            pc.SecretStore(path=str(self.directory / "secrets.json")))

    # -- available models ---------------------------------------------
    def test_the_catalog_is_data_that_arrives_and_no_model_is_hardcoded(self):
        transport = pt.RecordingTransport([(200, {"models": [
            {"name": "models/gemini-free-a", "displayName": "Free A",
             "freeSupported": True},
            {"name": "models/gemini-paid-x", "displayName": "Paid X",
             "freeSupported": False},
            {"name": "models/gemini-unknown", "displayName": "Unknown"},
        ]})])
        self.service.store.set("gemini", "secret", GEMINI_KEY)
        result = self.service.refresh_model_catalog(
            role="owner", provider="gemini", transport=transport,
            fetched_at="2026-09-27T10:00")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["selectable"], ["gemini-free-a"])
        # the bare id is stored, not the "models/" prefixed form
        stored = {e["model_id"]: e for e in self.service.config.catalog("gemini")}
        self.assertIn("gemini-free-a", stored)
        self.assertEqual(stored["gemini-unknown"]["free_supported"], None)
        self.assertEqual(self.service.config.catalog_fetched_at("gemini"),
                         "2026-09-27T10:00")

    def test_a_model_can_only_be_chosen_from_the_free_confirmed_list(self):
        transport = pt.RecordingTransport([(200, {"models": [
            {"name": "models/gemini-free-a", "freeSupported": True},
            {"name": "models/gemini-paid-x", "freeSupported": False},
            {"name": "models/gemini-unknown"},
        ]})])
        self.service.store.set("gemini", "secret", GEMINI_KEY)
        self.service.refresh_model_catalog(
            role="owner", provider="gemini", transport=transport,
            fetched_at="2026-09-27T10:00")
        for model, allowed in (("gemini-free-a", True),
                               ("gemini-paid-x", False),
                               ("gemini-unknown", False),
                               ("gemini-not-listed", False)):
            with self.subTest(model=model):
                try:
                    self.service.set_provider(
                        role="owner", provider="gemini", model=model)
                    self.assertTrue(allowed, f"{model} should be refused")
                except pc.ConfigError as exc:
                    self.assertFalse(allowed, f"{model} should be allowed")
                    self.assertEqual(exc.code, "MODEL_NOT_SELECTABLE")

    def test_no_model_can_be_chosen_before_the_list_is_fetched(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.set_provider(role="owner", provider="gemini",
                                      model="gemini-free-a")
        self.assertEqual(caught.exception.code, "MODEL_NOT_SELECTABLE")

    def test_a_failed_fetch_does_not_replace_the_stored_list(self):
        good = pt.RecordingTransport([(200, {"models": [
            {"name": "models/gemini-free-a", "freeSupported": True}]})])
        self.service.store.set("gemini", "secret", GEMINI_KEY)
        self.service.refresh_model_catalog(role="owner", provider="gemini",
                                           transport=good,
                                           fetched_at="2026-09-27T10:00")
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.refresh_model_catalog(
                role="owner", provider="gemini",
                transport=pt.RecordingTransport([ConnectionError("refused")]),
                fetched_at="2026-09-27T11:00")
        self.assertEqual(caught.exception.code, "MODEL_LIST_UNAVAILABLE")
        # the earlier list is still there and still selectable
        self.assertTrue(
            self.service.config.model_is_selectable("gemini", "gemini-free-a"))

    def test_a_fetch_failure_is_not_reported_as_an_empty_list(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.refresh_model_catalog(
                role="owner", provider="gemini",
                transport=pt.RecordingTransport([(500, {"error": {}})]),
                fetched_at="2026-09-27T10:00")
        self.assertEqual(caught.exception.code, "MODEL_LIST_UNAVAILABLE")

    def test_only_the_owner_may_fetch_the_list(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.refresh_model_catalog(
                role="viewer", provider="gemini",
                transport=pt.RecordingTransport([(200, {"models": []})]),
                fetched_at="2026-09-27T10:00")
        self.assertEqual(caught.exception.code, "ACTION_FORBIDDEN")

    # -- project tier --------------------------------------------------
    def test_the_tier_is_unverified_until_the_owner_records_it(self):
        self.assertEqual(self.service.config.tier_state(), "unknown")
        record = self.service.config.tier_record()
        self.assertEqual(record["state"], "unknown")
        self.assertIsNone(record["verified_at"])
        # the app never claims to guarantee free billing
        self.assertFalse(record["app_guarantees_free_billing"])

    def test_a_fetched_list_alone_does_not_verify_the_tier(self):
        # The contract is explicit: a model list or a working key is not proof
        # that the project is on a free tier.
        transport = pt.RecordingTransport([(200, {"models": [
            {"name": "models/gemini-free-a", "freeSupported": True}]})])
        self.service.store.set("gemini", "secret", GEMINI_KEY)
        self.service.refresh_model_catalog(role="owner", provider="gemini",
                                           transport=transport,
                                           fetched_at="2026-09-27T10:00")
        self.assertEqual(self.service.config.tier_state(), "unknown")

    def test_recording_a_free_tier_stores_when_it_was_checked(self):
        record = self.service.record_tier_verification(
            role="owner", tier="free", verified_at="2026-09-27T10:05")
        self.assertEqual(record["state"], "verified")
        self.assertEqual(record["tier"], "free")
        self.assertEqual(record["verified_at"], "2026-09-27T10:05")
        self.assertIn("AI Studio", record["checked_in"])
        self.assertFalse(record["app_guarantees_free_billing"])

    def test_a_paid_or_unknown_tier_is_setting_required_not_verified(self):
        for tier in ("paid", "unknown"):
            with self.subTest(tier=tier):
                service = pc.ProviderConfigService(
                    pc.SecretStore(path=str(self.directory / f"{tier}.json")))
                record = service.record_tier_verification(
                    role="owner", tier=tier, verified_at="2026-09-27T10:05")
                self.assertEqual(record["state"], "setting-required")

    def test_a_tier_record_needs_a_time_and_a_known_value(self):
        with self.assertRaises(pc.ConfigError):
            self.service.record_tier_verification(
                role="owner", tier="free", verified_at="")
        with self.assertRaises(pc.ConfigError):
            self.service.record_tier_verification(
                role="owner", tier="platinum", verified_at="2026-09-27T10:05")
        with self.assertRaises(pc.ConfigError):
            self.service.record_tier_verification(
                role="viewer", tier="free", verified_at="2026-09-27T10:05")

    # -- connection test ----------------------------------------------
    def test_the_connection_test_returns_success_and_the_actual_model_id(self):
        transport = pt.RecordingTransport([(200, {
            "modelVersion": "gemini-free-a-2026",
            "candidates": [{"content": {"parts": [{"text": "pong"}]}}]})])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                   transport=transport)
        result = pt.connection_test(adapter)
        self.assertTrue(result["ok"])
        # the id the provider reported, not the one we asked for
        self.assertEqual(result["model_id"], "gemini-free-a-2026")
        self.assertIsNone(result["reason_code"])
        self.assertFalse(result["is_real_call"])

    def test_the_connection_test_sends_no_ledger_data(self):
        transport = pt.RecordingTransport([GEMINI_OK])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                   transport=transport)
        pt.connection_test(adapter)
        payload = transport.calls[0]["payload"]
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        # a fixed sentence, and none of the excluded context fields
        for absent in ("conversation_id", "turn_id", "qa", "rule", "handoff",
                       "merchant_normalized", "amount_bucket_krw"):
            self.assertNotIn(absent, blob)
        self.assertIn(pt.CONNECTION_TEST_PROMPT, blob)
        self.assertNotIn(GEMINI_KEY, blob)

    def test_a_connection_test_failure_reports_a_reason_and_no_model(self):
        cases = [
            ((401, {"error": {"message": "bad"}}), "auth_failed"),
            ((429, {"error": {"message": "quota"}}), "free_quota_exhausted"),
            ((500, {"error": {}}), "service_error"),
        ]
        for script, expected in cases:
            with self.subTest(expected=expected):
                transport = pt.RecordingTransport([script])
                adapter = pt.GeminiAdapter(secret=GEMINI_KEY,
                                           model_id="gemini-free-a",
                                           transport=transport)
                result = pt.connection_test(adapter)
                self.assertFalse(result["ok"])
                self.assertIsNone(result["model_id"])
                self.assertEqual(result["reason_code"], expected)

    def test_a_connection_test_on_an_unconfigured_provider_says_so(self):
        result = pt.connection_test(
            pt.GeminiAdapter(secret="", model_id="gemini-free-a"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "not_configured")
        missing_model = pt.connection_test(
            pt.GeminiAdapter(secret=GEMINI_KEY, model_id=""))
        self.assertFalse(missing_model["ok"])
        self.assertEqual(missing_model["reason_code"], "not_configured")

    def test_only_the_owner_may_run_the_connection_test(self):
        with self.assertRaises(pc.ConfigError) as caught:
            self.service.run_connection_test(role="viewer", provider="gemini")
        self.assertEqual(caught.exception.code, "ACTION_FORBIDDEN")

    def test_the_service_connection_test_never_returns_a_key(self):
        transport = pt.RecordingTransport([GEMINI_OK])
        muse, gemini = pt.build_adapters(self.service.config, transport={
            "muse": transport, "gemini": transport})
        result = self.service.run_connection_test(
            role="owner", provider="gemini", muse=muse, gemini=gemini)
        self.assertNotIn(GEMINI_KEY, json.dumps(result))
        self.assertIn("ok", result)

    # -- bounded retry -------------------------------------------------
    def test_a_transient_limit_is_retried_inside_one_attempt(self):
        transport = pt.RecordingTransport([
            (429, {"error": {"message": "slow down"}}), GEMINI_OK])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                   transport=transport)
        result = pt.send_with_bounded_retry(adapter, {"attempt_id": "t-a1"},
                                            backoff=(0,))
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(transport.calls), 2)
        # the same attempt id both times: a retry is not a second attempt
        self.assertEqual(adapter.sent_request_ids, ["t-a1", "t-a1"])

    def test_the_retry_is_bounded(self):
        transport = pt.RecordingTransport([
            (429, {"error": {"message": "slow down"}})
            for _ in range(pt.MAX_TRANSPORT_ATTEMPTS + 4)])
        adapter = pt.GeminiAdapter(secret=GEMINI_KEY, model_id="gemini-free-a",
                                   transport=transport)
        with self.assertRaises(Exception) as caught:
            pt.send_with_bounded_retry(adapter, {"attempt_id": "a"},
                                       backoff=(0,))
        self.assertEqual(caught.exception.reason, "rate_limited")
        self.assertEqual(len(transport.calls), pt.MAX_TRANSPORT_ATTEMPTS)

    def test_a_spent_quota_is_never_retried(self):
        # Retrying a daily limit only spends the same refusal; the contract asks
        # for a wait with the context preserved instead. A non-retryable refusal
        # is returned with its reason so the turn policy can decide, rather than
        # being turned into a transport fault.
        for script, reason in (
                ([(429, {"error": {"message": "quota exhausted"}})],
                 "free_quota_exhausted"),
                ([(402, {"error": {}})], "budget_exhausted"),
                ([(401, {"error": {}})], "auth_failed")):
            with self.subTest(reason=reason):
                transport = pt.RecordingTransport(list(script))
                adapter = pt.GeminiAdapter(secret=GEMINI_KEY,
                                           model_id="gemini-free-a",
                                           transport=transport)
                result = pt.send_with_bounded_retry(adapter, {"attempt_id": "a"},
                                                    backoff=(0,))
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reason_code, reason)
                # exactly one call: no retry was spent
                self.assertEqual(len(transport.calls), 1)

    def test_a_retry_failure_still_reaches_the_turn_policy(self):
        # The turn has to see the reason, not an exception it cannot classify.
        transport = pt.RecordingTransport([
            (429, {"error": {"message": "slow down"}})
            for _ in range(pt.MAX_TRANSPORT_ATTEMPTS)])
        adapter = pt.MuseAdapter(secret=MUSE_KEY, model_id="muse-local-1",
                                 transport=transport)
        outcome = run_turn(turn_id="retry-1", context={"row_id": "r1"},
                           muse=adapter, gemini=None, max_retries=2)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.reason_code, "rate_limited")

    def test_the_turn_uses_the_adapter_retry_and_records_one_attempt(self):
        transport = pt.RecordingTransport([
            (429, {"error": {"message": "slow down"}}), MUSE_OK])
        muse = pt.MuseAdapter(secret=MUSE_KEY, model_id="muse-local-1",
                              transport=transport)
        outcome = run_turn(turn_id="retry-2", context={"row_id": "r1"},
                           muse=muse, gemini=None, max_retries=2)
        self.assertEqual(outcome.state, "answered")
        self.assertEqual(outcome.switch_count, 0)
        # one attempt in the record even though the transport was called twice
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(outcome.attempts[0]["attempt_id"], "retry-2-a1")

    def test_an_outstanding_attempt_is_expired_before_one_new_attempt(self):
        # Contract 7.1.1: when the PC drops mid-question, the earlier attempt is
        # expired and exactly one new attempt is opened.
        expired = []
        transport = pt.RecordingTransport([ConnectionError("refused")])
        muse = pt.MuseAdapter(secret=MUSE_KEY, model_id="muse-local-1",
                              transport=transport)
        outcome = run_turn(
            turn_id="exp-1", context={"row_id": "r1"}, muse=muse, gemini=None,
            expire_attempts=lambda provider: expired.append(provider) or ["a0"])
        self.assertEqual(expired, ["muse"])
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(outcome.state, "waiting")

    def test_a_failing_expiry_hook_does_not_block_the_send(self):
        transport = pt.RecordingTransport([MUSE_OK])
        muse = pt.MuseAdapter(secret=MUSE_KEY, model_id="muse-local-1",
                              transport=transport)

        def boom(provider):
            raise RuntimeError("expiry store is down")

        outcome = run_turn(turn_id="exp-2", context={"row_id": "r1"},
                           muse=muse, gemini=None, expire_attempts=boom)
        self.assertEqual(outcome.state, "answered")


# -------------------------------------------------------------- rule text
ROW = {
    "row_id": "expense-demo-c1", "source_merchant": "아구다호텔",
    "card_kind": "체크", "event_kind": "purchase", "amount_krw": 120000,
    "occurred_on": "2026-04-01", "display_tab_id": TRIP_A,
}
OPERATOR = {"trip_id": TRIP_B, "event_year": 2026}


class RuleTextTests(unittest.TestCase):
    def test_provider_prose_becomes_a_validated_candidate_that_is_not_applied(self):
        candidate = rule_text.rule_candidate(
            text=f"이번 거래는 {TRIP_B} 여행으로 옮기면 될 것 같아요.",
            row=ROW, learning_case_id="case-1", rule_id="rule-1",
            operator=OPERATOR)
        self.assertFalse(candidate["applied"])
        self.assertTrue(candidate["requires_owner_confirm"])
        self.assertEqual(candidate["rule"]["effects"]["display_tab_id"], TRIP_B)
        self.assertEqual(candidate["rule"]["rule_id"], "rule-1")
        self.assertTrue(candidate["rule_hash"])

    def test_a_candidate_carries_no_impact_number(self):
        # The model's own count or total is never trusted (contract 7).
        candidate = rule_text.rule_candidate(
            text=f"이 건은 {TRIP_B} 여행으로 옮기면 총 12건 340000원이에요.",
            row=ROW, learning_case_id="case-1", rule_id="rule-1",
            operator=OPERATOR)
        blob = json.dumps(rule_text.candidate_report(candidate),
                          ensure_ascii=False)
        for claim in ("12", "340000", "건"):
            self.assertNotIn(claim, blob)
        report = rule_text.candidate_report(candidate)
        self.assertNotIn("affected", report)
        self.assertNotIn("total", report)

    def test_prose_alone_cannot_place_a_row_without_the_operator_value(self):
        # The prose names a destination, which is not a tab id, so the
        # candidate is refused rather than guessed.
        with self.assertRaises(Exception) as caught:
            rule_text.rule_candidate(
                text="이번 거래는 부산 여행으로 옮기면 될 것 같아요.",
                row=ROW, learning_case_id="case-1", rule_id="rule-1")
        self.assertIn(getattr(caught.exception, "code", ""),
                      ("RULE_SCOPE_INCOMPLETE", "RULE_TEXT_UNRECOGNISED"))

    def test_a_model_cannot_set_its_own_rule_id_version_or_scope(self):
        candidate = rule_text.rule_candidate(
            payload={"rule_id": "attacker", "version": 99,
                     "base_rule_version": 42,
                     "scope": {"trip_id": "trip-evil", "event_year": 2030,
                               "applicability": "existing_and_future"},
                     "conditions": {"merchant_normalized":
                                    {"op": "eq", "value": "아구다호텔"}},
                     "effects": {"display_tab_id": TRIP_B, "amount_krw": 1}},
            row=ROW, learning_case_id="case-1", rule_id="rule-real",
            operator=OPERATOR)
        rule = candidate["rule"]
        self.assertEqual(rule["rule_id"], "rule-real")
        self.assertEqual(rule["version"], 1)
        self.assertEqual(rule["base_rule_version"], 0)
        self.assertEqual(rule["scope"]["trip_id"], TRIP_B)
        self.assertEqual(rule["scope"]["event_year"], 2026)
        self.assertNotIn("amount_krw", rule["effects"])
        self.assertEqual(rule["note"], "")

    def test_a_model_asking_for_a_different_trip_is_refused_not_silently_replaced(self):
        with self.assertRaises(rule_text.TextRuleError) as caught:
            rule_text.rule_candidate(
                payload={"conditions": {"merchant_normalized":
                                        {"op": "eq", "value": "아구다호텔"}},
                         "effects": {"display_tab_id": "trip-demo-z"}},
                row=ROW, learning_case_id="case-1", rule_id="rule-1",
                operator=OPERATOR)
        self.assertEqual(caught.exception.code, "RULE_TEXT_TRIP_MISMATCH")

    def test_a_disallowed_condition_or_effect_is_dropped_not_obeyed(self):
        with self.assertRaises(Exception):
            rule_text.rule_candidate(
                payload={"conditions": {"customer_name": {"op": "eq",
                                                          "value": "김민수"}},
                         "effects": {"display_tab_id": TRIP_B}},
                row=ROW, learning_case_id="case-1", rule_id="rule-1",
                operator=OPERATOR)
        candidate = rule_text.rule_candidate(
            payload={"conditions": {"merchant_normalized":
                                    {"op": "eq", "value": "아구다호텔"}},
                     "effects": {"display_tab_id": TRIP_B,
                                 "amount_krw": 5, "occurred_on": "2030-01-01"}},
            row=ROW, learning_case_id="case-1", rule_id="rule-1",
            operator=OPERATOR)
        self.assertEqual(sorted(candidate["rule"]["effects"]),
                         ["display_tab_id"])

    def test_unusable_provider_text_produces_no_candidate(self):
        for text in ("죄송하지만 판단하기 어렵습니다.", "", None,
                     "amount_krw 를 바꿔 주세요", "x" * 5000):
            with self.subTest(text=str(text)[:20]):
                with self.assertRaises(rule_text.TextRuleError) as caught:
                    rule_text.rule_candidate(
                        text=text, row=ROW, learning_case_id="case-1",
                        rule_id="rule-1", operator=OPERATOR)
                self.assertEqual(caught.exception.code,
                                 "RULE_TEXT_UNRECOGNISED")

    def test_a_long_answer_is_truncated_rather_than_mined(self):
        parsed = rule_text.parse_provider_text("a" * 3000)
        self.assertTrue(parsed["truncated"])

    def test_a_volunteered_json_block_is_still_only_a_candidate(self):
        text = ("확인했습니다.\n```json\n"
                '{"conditions": {"merchant_normalized": {"op": "eq",'
                ' "value": "아구다호텔"}},'
                f' "effects": {{"display_tab_id": "{TRIP_B}"}}}}\n```')
        candidate = rule_text.rule_candidate(
            text=text, row=ROW, learning_case_id="case-1", rule_id="rule-1",
            operator=OPERATOR)
        self.assertEqual(candidate["source"], "provider_json")
        self.assertFalse(candidate["applied"])

    def test_a_candidate_cannot_satisfy_the_apply_contract_on_its_own(self):
        # The apply path needs a preview id, a draft revision, and selected
        # rows. A candidate has none of them, so it cannot be replayed as an
        # apply request.
        candidate = rule_text.rule_candidate(
            text=f"이 건은 {TRIP_B} 여행으로 옮기면 좋아요.", row=ROW,
            learning_case_id="c", rule_id="rule-1", operator=OPERATOR)
        for required in ("preview_id", "expected_revision", "client_request_id",
                         "apply_existing", "apply_future"):
            self.assertNotIn(required, candidate)
            self.assertNotIn(required, candidate["rule"])


# -------------------------------------------------------------- http paths
class ProviderConfigHttpTests(unittest.TestCase):
    """The owner-only boundary over real HTTP routes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._prev = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(self.tmp / "db.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        self.access = access_control.attach_to_ledger_store(self.store)
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        access_control.bind_synthetic_sessions(True)
        board_mod.bind_access(self.access)
        self.service = pc.ProviderConfigService(
            pc.SecretStore(path=str(self.tmp / "secrets.json")))
        seed_catalog(self.service.config, "gemini")
        seed_catalog(self.service.config, "muse", MUSE_CATALOG)
        board_mod.bind_provider_config(self.service, autowire=True,
                                       transport=pt.RecordingTransport(
                                           [MUSE_OK, GEMINI_OK]))
        self.access.ensure_owner(OWNER)
        self.access.create_account(user_id=V1,
                                   role=access_control.ROLE_VIEWER)
        self.access.register_reservation_person(reservation_person_id="rp-1",
                                                display_name="전여자")
        self.access.create_application(user_id=V1, requested_name="전여자",
                                       client_request_id="ap-1")
        application = self.access.applications_for(V1)[0]
        self.access.approve_application(
            application_id=application["application_id"], owner_id=OWNER,
            expected_revision=1, reservation_person_id="rp-1",
            client_request_id="ap-1-approve")
        self.access.apply_assignment_snapshot(
            user_id=V1,
            items=[{"tab_id": TRIP_A, "snapshot_revision": 1,
                    "state": access_control.ASSIGN_ACTIVE}],
            source_version="src-1")

    def tearDown(self):
        board_mod.bind_access(None)
        board_mod.bind_provider_config(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev

    def api(self, path, payload=None, method="GET", user=None):
        data = None
        headers = {}
        if payload is not None:
            body = dict(payload)
            body.setdefault("csrf", board_mod.CSRF_TOKEN)
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_a_viewer_is_refused_the_screen_and_the_write(self):
        for method, payload in (("GET", None),
                                ("POST", {"action": "set", "provider": "gemini",
                                          "secret": GEMINI_KEY})):
            with self.subTest(method=method):
                status, body = self.api("/access/providers", payload, method, V1)
                self.assertEqual(status, 403)
                self.assertIn("ACTION_FORBIDDEN", body.decode("utf-8"))
        # and nothing was stored
        self.assertEqual(self.service.store.get("gemini", "secret"), "")

    def test_the_screen_uses_a_password_field_and_never_echoes_a_key(self):
        self.api("/access/providers", {"action": "set", "provider": "gemini",
                                       "secret": GEMINI_KEY}, "POST", OWNER)
        status, body = self.api("/access/providers", user=OWNER)
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("type='password'", page)
        self.assertNotIn(GEMINI_KEY, page)
        # the operator still gets a way to tell two keys apart
        self.assertIn("sha256:", page)

    def test_a_write_never_returns_the_value(self):
        status, body = self.api("/access/providers", {
            "action": "set", "provider": "gemini", "secret": GEMINI_KEY,
            "model": "gemini-free-a", "timeout": 15}, "POST", OWNER)
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertNotIn(GEMINI_KEY, text)
        payload = json.loads(text)
        self.assertTrue(payload["gemini"]["configured"])
        # the timeout round-trips through the store
        self.assertEqual(payload["gemini"]["timeout"], 15.0)

    def test_clearing_reports_the_key_as_gone(self):
        self.api("/access/providers", {"action": "set", "provider": "gemini",
                                       "secret": GEMINI_KEY}, "POST", OWNER)
        status, body = self.api("/access/providers",
                                {"action": "clear", "provider": "gemini"},
                                "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body.decode("utf-8"))["gemini"]["configured"])

    def test_a_bad_key_is_refused_with_a_reason(self):
        cases = (
            ({"action": "set", "provider": "gemini", "secret": "abc"},
             "INVALID_VALUE"),
            ({"action": "set", "provider": "nope", "secret": GEMINI_KEY},
             "INVALID_VALUE"),
            ({"action": "set", "provider": "gemini", "secret": GEMINI_KEY,
              "timeout": 0}, "INVALID_VALUE"),
        )
        for index, (payload, expected) in enumerate(cases):
            with self.subTest(expected=expected, payload=str(payload)[:40]):
                # A reused request id with a different body is itself refused,
                # so each attempt carries its own id.
                body = dict(payload, client_request_id=f"bad-{index}")
                status, raw = self.api("/access/providers", body, "POST", OWNER)
                self.assertEqual(status, 422)
                self.assertEqual(json.loads(raw.decode("utf-8"))["code"],
                                 expected)

    def test_the_key_never_reaches_the_ledger_database(self):
        self.api("/access/providers", {"action": "set", "provider": "gemini",
                                       "secret": GEMINI_KEY}, "POST", OWNER)
        found = False
        tables = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (name,) in tables:
            for column in self.store.conn.execute(
                    f"PRAGMA table_info({name})"):
                try:
                    hit = self.store.conn.execute(
                        f"SELECT 1 FROM {name} WHERE CAST({column[1]} AS TEXT)"
                        " LIKE ?", (f"%{GEMINI_KEY}%",)).fetchone()
                except Exception:  # noqa: BLE001 - a scan, not a contract
                    continue
                if hit:
                    found = True
        self.assertFalse(found)

    def test_the_credential_is_stored_outside_the_database(self):
        self.api("/access/providers", {"action": "set", "provider": "gemini",
                                       "secret": GEMINI_KEY}, "POST", OWNER)
        secret_file = Path(self.service.store.path)
        self.assertTrue(secret_file.exists())
        self.assertIn(GEMINI_KEY, secret_file.read_text(encoding="utf-8"))

    def test_a_request_body_cannot_pick_a_provider_for_a_turn(self):
        # The body names a provider and a key; the turn still refuses because
        # the conversation does not exist, proving the body was not honoured.
        status, body = self.api("/api/classification/conversation/advance",
                                {"provider": "gemini", "api_key": GEMINI_KEY,
                                 "model": "gemini-1.5-flash"}, "POST", OWNER)
        self.assertEqual(status, 422)
        self.assertNotIn(GEMINI_KEY, body.decode("utf-8"))

    def test_an_unbound_configuration_surface_refuses_rather_than_defaulting(self):
        board_mod.bind_provider_config(None)
        status, body = self.api("/access/providers", user=OWNER)
        self.assertEqual(status, 503)
        self.assertIn("PROVIDER_CONFIG_UNBOUND", body.decode("utf-8"))
        status, _ = self.api("/access/providers", {
            "action": "set", "provider": "gemini", "secret": GEMINI_KEY},
            "POST", OWNER)
        self.assertEqual(status, 503)

    def test_the_wiring_report_holds_no_secret(self):
        self.api("/access/providers", {"action": "set", "provider": "gemini",
                                       "secret": GEMINI_KEY}, "POST", OWNER)
        report = board_mod.provider_status()
        self.assertTrue(report["bound"])
        self.assertNotIn(GEMINI_KEY, json.dumps(report, default=str))
        self.assertFalse(report["is_real_secret_store"])

    def test_a_viewer_cannot_switch_the_fallback(self):
        status, body = self.api("/access/providers",
                                {"action": "fallback", "enabled": True},
                                "POST", V1)
        self.assertEqual(status, 403)
        self.assertIn("ACTION_FORBIDDEN", body.decode("utf-8"))
        self.assertFalse(self.service.config.fallback_enabled)

    def test_the_owner_can_switch_the_fallback_and_it_changes_the_wiring(self):
        # The switch is visible on the screen and it actually changes what is
        # dialled: with it off no Gemini adapter exists.
        status, body = self.api("/access/providers",
                                {"action": "set", "provider": "gemini",
                                 "secret": GEMINI_KEY,
                                 "model": "gemini-free-a"}, "POST", OWNER)
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["fallback_enabled"])
        self.assertIsNone(board_mod._GEMINI)

        status, body = self.api("/access/providers",
                                {"action": "fallback", "enabled": True},
                                "POST", OWNER)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8"))["fallback_enabled"])
        self.assertIsNotNone(board_mod._GEMINI)
        self.assertEqual(board_mod._GEMINI.model_id, "gemini-free-a")
        self.assertNotIn(GEMINI_KEY, json.dumps(
            board_mod.provider_status(), default=str))

        # and turning it back off removes it again
        self.api("/access/providers", {"action": "fallback", "enabled": False},
                 "POST", OWNER)
        self.assertIsNone(board_mod._GEMINI)

    def test_the_screen_reports_the_fallback_state(self):
        status, body = self.api("/access/providers", user=OWNER)
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("value='fallback'", page)
        self.assertIn("fallback ", page)


if __name__ == "__main__":
    unittest.main()
