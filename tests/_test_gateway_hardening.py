"""Offline regressions for protocol completion, isolation and SQL aggregates."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.TemporaryDirectory(prefix="fhub-hardening-")
os.environ["ACCOUNTS_DIR"] = TMP.name
os.environ["WB_PROXY_USAGE_DIR"] = TMP.name

import wb_database
import wb_protocol
import wb_proxy as P
import wb_security
import wb_settings
import wb_validation
import wb_accounts
import wb_background
import wb_dashboard
import wb_events
import wb_usage_views
import wb_usage_store


def frame(value):
    return ("data: " + json.dumps(value) + "\n\n").encode()


def text(value="hello", finish=None, usage=None):
    result = {"choices": [{"delta": {"content": value}, "finish_reason": finish}]}
    if usage is not None:
        result["usage"] = usage
    return frame(result)


class ProtocolTests(unittest.TestCase):
    def test_premature_eof_fails_all_adapters(self):
        for adapter in (lambda rows: P.aggregate_stream(rows, "m", None),
                        lambda rows: list(P.stream_messages_events(rows, "m", {})),
                        lambda rows: list(P.stream_responses_events(rows, "m", {}))):
            with self.assertRaises(wb_protocol.UpstreamStreamError):
                adapter([text()])

    def test_json_error_is_not_a_successful_completion(self):
        usage = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
        for adapter in (lambda rows: P.aggregate_stream(rows, "m", None),
                        lambda rows: list(P.stream_responses_events(rows, "m", {}))):
            with self.assertRaises(wb_protocol.UpstreamStreamError) as result:
                adapter([text(usage=usage), frame({"error": {"message": "failed"}})])
            self.assertEqual(result.exception.usage, usage)

    def test_finish_without_done_is_valid(self):
        result = P.aggregate_stream([text(finish="stop")], "m", None)
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")
        self.assertNotIn("usage", result)

    def test_missing_usage_is_never_fabricated(self):
        result = P.aggregate_stream([text(), b"data: [DONE]\n\n"], "m", None)
        self.assertNotIn("usage", result)
        holder = {}
        frames = list(P.stream_responses_events([text(finish="stop")], "m", holder))
        self.assertIsNone(holder.get("usage"))
        self.assertIn(b"response.completed", frames[-1])

    def test_length_uses_incomplete_event(self):
        frames = list(P.stream_responses_events([text(finish="length")], "m", {}))
        self.assertIn(b"response.incomplete", frames[-1])

    def test_metadata_and_session_validation(self):
        for extra in ({"metadata": ["x"]}, {"metadata": "x"}, {"session_id": []}, {"conversation_id": 1}):
            with self.assertRaises(wb_validation.RequestValidationError):
                wb_validation.validate_request(dict(model="m", input="x", **extra), "responses")

    def test_affinity_namespaces(self):
        keys = {wb_protocol.affinity_key("default", realm, key)
                for realm in ("cn", "intl") for key in ("one", "two")}
        self.assertEqual(len(keys), 4)
        self.assertEqual(wb_protocol.affinity_key("default", "cn", "one"),
                         wb_protocol.affinity_key("default", "cn", "one"))

    def test_default_prompt_retry_is_disabled(self):
        self.assertFalse(wb_settings.prompt_config(TMP.name)["retry_on_content_rejection"])
        self.assertTrue(P.wb_prompt.is_content_rejection('{"error":{"code":11140}}'))
        self.assertFalse(P.wb_prompt.is_content_rejection('{"error":{"code":403}}'))


class LoginTests(unittest.TestCase):
    def test_untrusted_forwarded_ip_is_ignored(self):
        trusted = wb_security.TrustedProxies("127.0.0.1/32")
        self.assertEqual(trusted.client_ip("203.0.113.4", {"X-Real-IP": "198.51.100.2"}), "203.0.113.4")
        self.assertEqual(trusted.client_ip("127.0.0.1", {"X-Real-IP": "198.51.100.2"}), "198.51.100.2")

    def test_attempts_are_reserved_atomically(self):
        limiter = wb_security.LoginLimiter(limit=5, concurrent=32)
        barrier = threading.Barrier(12)
        results = []
        def call():
            barrier.wait()
            results.append(limiter.begin("client"))
        workers = [threading.Thread(target=call) for _ in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sum(ticket is not None for ticket, _ in results), 5)
        for ticket, _ in results:
            if ticket:
                limiter.finish("client", ticket)


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="fhub-sql-")
        self.database = wb_database.Database(os.path.join(self.directory.name, "data.sqlite"), self.directory.name, self.directory.name)

    def tearDown(self):
        self.database.close_thread()
        self.directory.cleanup()

    def append(self, at, realm="cn", key="one", outcome="completed"):
        self.database.append_usage({"at": at, "realm": realm, "key": key, "account": "a", "model": "m",
            "outcome": outcome, "prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})

    def test_hourly_totals_match_exact_boundaries_and_isolate_keys(self):
        for at in (0, 1800, 3600, 5400, 7200, 10800):
            self.append(at)
        self.append(5400, realm="intl")
        self.append(5400, key="two")
        for lo, hi in ((None, None), (1800, 7200), (3600, 7200), (None, 7200), (5400, None), (0, 0)):
            expected = self.database._raw_usage_totals(realm="cn", api_key="one", since=lo, until=hi)
            actual = self.database.usage_totals(realm="cn", api_key="one", since=lo, until=hi)
            self.assertEqual(actual, expected, (lo, hi))

    def test_duplicates_and_deletes_do_not_corrupt_rollups(self):
        row = {"event_id": "same", "at": 3600, "realm": "cn", "total_tokens": 7}
        self.database.append_usage(dict(row))
        self.database.append_usage(dict(row))
        self.assertEqual(self.database.usage_totals()[0]["total_tokens"], 7)
        self.database.connection().execute("DELETE FROM usage_records")
        self.assertEqual(self.database.usage_totals()[0]["total_tokens"], 0)
        self.assertEqual(self.database.pending_exports(), [])

    def test_outbox_is_durable_and_query_limit_runs_in_sql(self):
        for n in range(4):
            self.append(3600+n)
        self.assertEqual(len(self.database.pending_exports()), 4)
        self.assertEqual([row["at"] for row in self.database.usage_rows(limit=2, offset=1)], [3602,3601])
        self.database.confirm_exports([self.database.pending_exports()[0][0]])
        self.assertEqual(len(self.database.pending_exports()), 3)

    def test_incremental_snapshot_reads_only_new_sequences(self):
        self.append(3600)
        cache = wb_usage_views.SnapshotViews()
        calls = []
        def fold(state, row):
            calls.append(row["at"])
            state["total"] += row["total_tokens"]
        self.assertEqual(cache.get(self.database, "cn", None, None, fold, lambda: {"total":0}), {"total":7})
        self.assertEqual(cache.get(self.database, "cn", None, None, fold, lambda: {"total":0}), {"total":7})
        self.assertEqual(calls, [3600])
        self.append(3601)
        self.assertEqual(cache.get(self.database, "cn", None, None, fold, lambda: {"total":0}), {"total":14})
        self.assertEqual(calls, [3600,3601])

    def test_jsonl_export_is_replayable_from_durable_outbox(self):
        self.append(3600)
        path = os.path.join(self.directory.name, "usage.jsonl")
        wb_usage_store.schedule_export(self.database, path)
        self.assertTrue(wb_usage_store.EXPORTS.drain(3))
        self.assertEqual(self.database.pending_exports(), [])
        self.assertEqual(json.loads(Path(path).read_text())["total_tokens"], 7)
        wb_usage_store.schedule_export(self.database, path)
        self.assertTrue(wb_usage_store.EXPORTS.drain(3))
        self.assertEqual(len(Path(path).read_text().splitlines()), 1)


class BackgroundTests(unittest.TestCase):
    def test_queue_is_bounded_and_coalesces_last_write(self):
        queue = wb_background.WorkQueue("test-work", max_pending=1)
        began, finish = threading.Event(), threading.Event()
        values = []
        def wait():
            began.set()
            finish.wait(2)
        self.assertTrue(queue.submit("active", wait))
        self.assertTrue(began.wait(1))
        self.assertTrue(queue.submit("key", lambda: values.append("old")))
        self.assertTrue(queue.submit("key", lambda: values.append("new")))
        self.assertFalse(queue.submit("overflow", lambda: values.append("overflow")))
        finish.set()
        self.assertTrue(queue.close(2))
        self.assertEqual(values, ["new"])

    def test_activity_deltas_coalesce_and_keep_full_invalidations(self):
        broker = wb_events.Broker()
        client = wb_events.Subscription(broker, "cn")
        broker.clients.add(client)
        broker.publish("accounts", realm="cn")
        broker.publish("usage", realm="cn", changes={"accounts":{"a":{"inFlight":1}},"usage":{"a":{"total_tokens":4}}})
        broker.publish(realm="cn", changes={"accounts":{"a":{"inFlight":0}},"usage":{"a":{"total_tokens":3}}})
        broker.publish("settings", realm="intl")
        event = client.next(0)
        self.assertEqual(event["topics"], ["accounts","usage"])
        self.assertEqual(event["changes"]["accounts"]["a"]["inFlight"], 0)
        self.assertEqual(event["changes"]["usage"]["a"]["total_tokens"], 7)
        self.assertIsNone(client.next(0))

    def test_background_affinity_does_not_call_slow_mirror_in_picker(self):
        began, finish = threading.Event(), threading.Event()
        class Mirror:
            def set(self, *args):
                began.set(); finish.wait(2)
            def delete(self, *args): pass
        affinity = wb_accounts.SessionAffinity(mirror=Mirror(), background=True)
        with mock.patch.object(wb_database, "DATABASE", None):
            affinity.bind("session", "a")
            self.assertTrue(began.wait(1))
            self.assertEqual(affinity.get("session"), "a")
            affinity.unbind("session")
            self.assertIsNone(affinity.get("session"))
            finish.set()
            self.assertTrue(wb_background.AFFINITY_WRITES.drain(2))

    def test_dashboard_sources_bundle_and_gzip_negotiation(self):
        assets = wb_dashboard.DashboardAssets()
        page = assets.html(str(ROOT / "dashboard.html"), "test", "nonce")
        self.assertNotIn(b"dashboard_static/", page)
        self.assertIn(b'<script nonce="nonce" src="/assets/', page)
        self.assertTrue(wb_dashboard.accepts_gzip("br, gzip;q=1"))
        self.assertFalse(wb_dashboard.accepts_gzip("gzip;q=0"))
        self.assertFalse(wb_dashboard.accepts_gzip("gzip;q=0..5"))


if __name__ == "__main__":
    unittest.main()
