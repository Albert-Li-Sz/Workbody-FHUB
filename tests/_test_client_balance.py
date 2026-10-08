"""API-key scoped balances and legacy billing over real HTTP connections.

All keys, accounts and refresh responses are synthetic; no upstream is called.
"""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = tempfile.TemporaryDirectory(prefix="wb-client-balance-")
os.environ["WB_PROXY_USAGE_DIR"] = WORK.name
import wb_proxy as P
import wb_settings as S
import wb_balance as B


def account(uid, realm, remain, used=0, enabled=True, fresh=True, error=False):
    a = types.SimpleNamespace(
        uid=uid, realm=realm, nickname="private-nickname-" + uid, enabled=enabled,
        credits={"remain": remain, "used": used, "updated_at": time.time() if fresh else 0},
        access_token="private-upstream-secret")

    def fetch():
        if error:
            raise RuntimeError("private-upstream-secret")
        a.credits = dict(a.credits, updated_at=time.time())
        return {"ok": True}

    a.fetch_credits = mock.Mock(side_effect=fetch)
    return a


class TestHandler(P.Handler):
    def log_message(self, *args):
        pass


class TestServer(P.ThreadingHTTPServer):
    def handle_error(self, request, address):
        self.errors.append(sys.exc_info()[1])


class ClientBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = TestServer(("127.0.0.1", 0), TestHandler)
        cls.server.errors = []
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)
        WORK.cleanup()
        if cls.server.errors:
            raise AssertionError("unexpected server errors: %r" % cls.server.errors)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=WORK.name)
        self.addCleanup(directory.cleanup)
        self.accounts = [account("domestic-a", "cn", 10.1, 3),
                         account("domestic-disabled", "cn", 5.2, 7, enabled=False),
                         account("international-a", "intl", 100, 20)]
        patcher = mock.patch.multiple(
            P, ACCOUNTS_DIR=directory.name, API_KEY="obsolete-launcher",
            CURRENT_REALM="intl", POOL=types.SimpleNamespace(accounts=self.accounts),
            CLIENT_BALANCES=B.ChannelBalances(), PANEL=S.PanelSessions())
        patcher.start()
        self.addCleanup(patcher.stop)
        S.save(directory.name, {"api_keys": [
            {"id": "cn", "key": "client-cn", "realm": "cn", "enabled": True},
            {"id": "intl", "key": "client-intl", "realm": "intl", "enabled": True},
            {"id": "follow", "key": "client-follow", "realm": "", "enabled": True},
            {"id": "disabled", "key": "client-disabled", "realm": "cn", "enabled": False},
            {"id": "deleted", "key": "client-deleted", "realm": "intl",
             "enabled": True, "deleted_at": "2026/10/08 01:00"},
        ]})
        self.conn = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(self.conn.close)

    def request(self, path="/v1/balance", key="client-cn", headers=None, method="GET"):
        headers = dict(headers or {})
        if key is not None:
            headers["Authorization"] = "Bearer " + key
        self.conn.request(method, path, headers=headers)
        response = self.conn.getresponse()
        payload = response.read()
        return response.status, json.loads(payload) if payload else None, dict(response.getheaders())

    def test_bound_keys_return_only_their_channel_on_a_reused_connection(self):
        status, cn, headers = self.request()
        connection = self.conn.sock
        self.assertEqual(status, 200)
        self.assertEqual(cn["total_remain"], 15.3)
        self.assertEqual(cn["account_count"], 2)
        self.assertEqual(cn["channel"], "workbuddy-cn")
        self.assertEqual(cn["currency"], "credits")
        self.assertTrue(cn["complete"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        status, intl, _ = self.request(key="client-intl")
        self.assertEqual(status, 200)
        self.assertEqual(intl["total_remain"], 100)
        self.assertEqual(intl["account_count"], 1)
        self.assertEqual(intl["realm"], "intl")
        self.assertIs(self.conn.sock, connection)
        for result in (cn, intl):
            serialized = json.dumps(result, allow_nan=False)
            for private in ("accounts", "by_realm", "domestic-a", "international-a",
                            "private-nickname", "private-upstream-secret", "client-cn"):
                self.assertNotIn(private, serialized)
        for a in self.accounts:
            a.fetch_credits.assert_not_called()

    def test_query_and_header_cannot_override_the_bound_channel(self):
        status, result, _ = self.request(
            "/balance?realm=intl&channel=workbuddy-intl", headers={"X-Realm": "intl"})
        self.assertEqual(status, 200)
        self.assertEqual(result["realm"], "cn")
        self.assertEqual(result["total_remain"], 15.3)

    def test_unbound_key_follows_the_panel_switch(self):
        self.assertEqual(self.request(key="client-follow")[1]["total_remain"], 100)
        P.CURRENT_REALM = "cn"
        status, result, _ = self.request(key="client-follow", headers={"X-Realm": "intl"})
        self.assertEqual(status, 200)
        self.assertEqual(result["total_remain"], 15.3)

    def test_valid_key_is_required_even_with_panel_session_or_disabled_auth(self):
        S.set_auth_disabled(P.ACCOUNTS_DIR, True)
        with mock.patch.object(P.PANEL, "valid", return_value=True):
            for key in (None, "wrong-key", "client-disabled", "client-deleted", "obsolete-launcher"):
                with self.subTest(key=key):
                    self.assertEqual(self.request(key=key, headers={"X-Panel-Token": "panel"})[0], 401)
            status, result, _ = self.request(headers={"X-Panel-Token": "panel"})
        self.assertEqual(status, 200)
        self.assertEqual(result["realm"], "cn")

    def test_supported_key_headers_and_query_parameters(self):
        for header in ("x-api-key", "api-key", "x-auth-token"):
            with self.subTest(header=header):
                self.assertEqual(self.request(key=None, headers={header: "client-intl"})[1]["realm"], "intl")
        for parameter in ("key", "api_key", "api-key"):
            with self.subTest(parameter=parameter):
                self.assertEqual(self.request("/balance?%s=client-cn" % parameter, key=None)[0], 200)

    def test_query_key_is_redacted_from_access_logs(self):
        request = types.SimpleNamespace(path="/balance", command="GET")
        with mock.patch.object(P, "log") as log:
            P.Handler.log_message(request, '"GET /balance?api-key=client-cn HTTP/1.1" %s %s',
                                  "200", "100")
        message = log.call_args.args[0]
        self.assertNotIn("client-cn", message)
        self.assertIn("api-key=<REDACTED>", message)

    def test_refresh_only_touches_the_keys_channel_including_disabled_accounts(self):
        status, result, _ = self.request("/v1/balance?refresh=1")
        self.assertEqual(status, 200)
        self.assertTrue(result["refreshed"])
        self.assertEqual(result["refresh_failed"], 0)
        for a in self.accounts[:2]:
            a.fetch_credits.assert_called_once()
        self.accounts[2].fetch_credits.assert_not_called()
        self.assertFalse(self.request()[1]["refreshed"])
        for a in self.accounts[:2]:
            a.fetch_credits.assert_called_once()

    def test_unknown_and_failed_balances_are_partial_without_private_errors(self):
        a = self.accounts[1]
        a.credits["remain"] = None
        a.fetch_credits.side_effect = RuntimeError("private-upstream-secret")
        status, result, _ = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["total_remain"], 10.1)
        self.assertEqual(result["unknown_count"], 1)
        self.assertEqual(result["refresh_failed"], 1)
        self.assertFalse(result["complete"])
        status, error, _ = self.request("/dashboard/billing/credit_grants")
        self.assertEqual(status, 503)
        self.assertNotIn("private-upstream-secret", json.dumps(error))
        a.fetch_credits.assert_called_once()

    def test_legacy_billing_aliases_produce_the_same_remaining_credit_total(self):
        for prefix in ("/dashboard/billing/", "/v1/dashboard/billing/"):
            with self.subTest(prefix=prefix):
                status, grants, _ = self.request(prefix + "credit_grants")
                self.assertEqual(status, 200)
                self.assertEqual(grants["object"], "credit_summary")
                self.assertEqual(grants["total_available"], 15.3)
                status, subscription, _ = self.request(prefix + "subscription")
                self.assertEqual(status, 200)
                self.assertEqual(subscription["object"], "billing_subscription")
                status, usage, _ = self.request(prefix + "usage?start_date=2026-10-01&end_date=2026-10-08")
                self.assertEqual(status, 200)
                self.assertEqual(usage["total_usage"], 1000)
                self.assertAlmostEqual(subscription["hard_limit_usd"] - usage["total_usage"] / 100,
                                       grants["total_available"])

    def test_cache_only_does_not_refresh_and_missing_usage_is_not_invented(self):
        a = self.accounts[0]
        a.credits["used"] = None
        status, result, _ = self.request("/v1/balance?refresh=0")
        self.assertEqual(status, 200)
        self.assertTrue(result["complete"])
        self.assertIsNone(result["total_used"])
        self.assertEqual(self.request("/dashboard/billing/subscription?refresh=0")[0], 503)
        a.fetch_credits.assert_not_called()

    def test_invalid_refresh_is_rejected_and_empty_channel_is_zero(self):
        self.assertEqual(self.request("/v1/balance?refresh=unexpected")[0], 400)
        for a in self.accounts:
            a.fetch_credits.assert_not_called()
        self.accounts.clear()
        status, result, _ = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["total_remain"], 0)
        self.assertEqual(result["account_count"], 0)
        self.assertTrue(result["complete"])
        self.assertEqual(self.request("/dashboard/billing/subscription")[1]["hard_limit_usd"], 0)

    def test_cors_preflight_and_management_balance_protection(self):
        for path in ("/balance", "/dashboard/billing/credit_grants", "/v1/dashboard/billing/usage"):
            with self.subTest(path=path):
                status, _, headers = self.request(path, key=None, method="OPTIONS")
                self.assertEqual(status, 204)
                self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        status, _, headers = self.request("/accounts/balance")
        self.assertEqual(status, 401)
        self.assertNotIn("Access-Control-Allow-Origin", headers)


class BalanceCacheTests(unittest.TestCase):
    def test_failed_forced_refresh_stays_incomplete_until_newer_credits_arrive(self):
        a = account("recent", "cn", 10, error=True)
        a.credits["updated_at"] = 99
        balances = B.ChannelBalances()
        with mock.patch.object(B.time, "time", return_value=100):
            failed = balances.query([a], "cn", refresh=True)
            cached = balances.query([a], "cn")
        self.assertFalse(failed["complete"])
        self.assertFalse(cached["complete"])
        self.assertFalse(cached["refreshed"])
        self.assertEqual(cached["refresh_failed"], 1)
        a.credits["updated_at"] = 101
        with mock.patch.object(B.time, "time", return_value=102):
            recovered = balances.query([a], "cn")
        self.assertTrue(recovered["complete"])
        a.fetch_credits.assert_called_once()

    def test_stale_and_failed_queries_retry_after_the_cache_interval(self):
        a = account("cached", "cn", 10, fresh=False, error=True)
        balances = B.ChannelBalances()
        with mock.patch.object(B.time, "time", return_value=100):
            first = balances.query([a], "cn")
            second = balances.query([a], "cn")
        self.assertEqual(first["refresh_failed"], 1)
        self.assertFalse(first["complete"])
        self.assertEqual(first["total_remain"], 10)
        self.assertFalse(second["refreshed"])
        a.fetch_credits.assert_called_once()
        with mock.patch.object(B.time, "time", return_value=161):
            balances.query([a], "cn")
        self.assertEqual(a.fetch_credits.call_count, 2)

    def test_imported_replacement_does_not_inherit_an_old_refresh_failure(self):
        original = account("reused-uid", "cn", 10, fresh=False, error=True)
        replacement = account("reused-uid", "cn", 20, fresh=False)
        balances = B.ChannelBalances()
        balances.query([original], "cn")
        result = balances.query([replacement], "cn")
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_remain"], 20)
        replacement.fetch_credits.assert_called_once()

    def test_concurrent_queries_share_one_channel_refresh(self):
        a = account("concurrent", "intl", 50, fresh=False)
        original_fetch = a.fetch_credits.side_effect
        started, release = threading.Event(), threading.Event()

        def fetch():
            started.set()
            if not release.wait(3):
                raise RuntimeError("refresh was not released")
            return original_fetch()

        a.fetch_credits.side_effect = fetch
        balances = B.ChannelBalances()
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(balances.query, [a], "intl") for _ in range(4)]
            try:
                self.assertTrue(started.wait(1))
            finally:
                release.set()
            results = [future.result(timeout=3) for future in futures]
        self.assertTrue(all(result["complete"] for result in results))
        a.fetch_credits.assert_called_once()

    def test_legacy_usage_overflow_cannot_return_nonfinite_json(self):
        summary = B.summarize_channel([account("huge", "cn", 1, used="1e307")], "cn")
        json.dumps(summary, allow_nan=False)
        self.assertIsNone(B.billing_response(summary, "usage"))


if __name__ == "__main__":
    unittest.main()
