"""Replay WorkBuddy code 14003 through real selection and concurrent callers."""
import atexit
import contextlib
import datetime
import email.utils
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

_directory = tempfile.TemporaryDirectory(prefix="soft-rate-recovery-")
atexit.register(_directory.cleanup)
os.environ["ACCOUNTS_DIR"] = _directory.name
os.environ["WB_PROXY_USAGE_DIR"] = _directory.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_accounts
import wb_pool
import wb_proxy

DETAIL = json.dumps({"code": 14003, "msg": "too many requests",
                     "retry_policy": {"retry": True}})
PAYLOAD = {"model": "deepseek-v4.1-flash",
           "messages": [{"role": "user", "content": "hello"}]}


def limited(headers=None, detail=DETAIL):
    return urllib.error.HTTPError("https://upstream.invalid", 429, "limited",
                                  headers or {}, io.BytesIO(detail.encode()))


class SoftRateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791900000.0
        self.account = wb_accounts.Account({
            "uid": "synthetic-international", "realm": "intl", "accessToken": "token",
            "expiresAt": self.now + 3600})
        self.pool = wb_accounts.AccountPool(_directory.name)
        self.pool.accounts = [self.account]
        self.pool.apply_pool_config(wb_pool.normalize(None))
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for patch in [mock.patch.object(wb_proxy, "POOL", self.pool),
                      mock.patch.object(wb_proxy, "apply_scheduling_limits"),
                      mock.patch.object(wb_proxy, "auto_switch_product_enabled", return_value=False),
                      mock.patch.object(wb_proxy, "log"),
                      mock.patch.object(time, "time", side_effect=lambda: self.now)]:
            self.stack.enter_context(patch)

    def open(self):
        return wb_proxy.open_upstream(PAYLOAD, target_realm="intl")

    def test_retry_after_controls_account_cooldown(self):
        with mock.patch.object(wb_accounts, "urlopen", side_effect=limited({"Retry-After": "7"})):
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
        self.assertEqual(caught.exception.wait, 7)
        self.assertEqual(self.account.cooldown_until, self.now + 7)
        self.assertFalse(self.account.ready(model="kimi-k3"))

    def test_parked_pool_stays_429_and_does_not_call_upstream(self):
        with mock.patch.object(wb_accounts, "urlopen", side_effect=limited()) as outbound:
            with self.assertRaises(wb_proxy.RateLimited):
                self.open()
            outbound.reset_mock()
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
            outbound.assert_not_called()
        self.assertGreater(caught.exception.wait, 0)
        self.assertEqual(self.account.in_flight, 0)

    def test_frequency_backoff_grows_only_after_recovery_attempts(self):
        waits = []
        for expected in [30, 60, 120, 240, 300, 300]:
            with mock.patch.object(wb_accounts, "urlopen", side_effect=limited()):
                with self.assertRaises(wb_proxy.RateLimited) as caught:
                    self.open()
            waits.append(caught.exception.wait)
            self.assertEqual(caught.exception.wait, expected)
            self.now += expected
        self.assertEqual(waits, [30, 60, 120, 240, 300, 300])
        with mock.patch.object(wb_accounts, "urlopen", return_value=io.BytesIO()):
            response, _, _ = self.open()
            response.close()
        self.assertEqual(self.account.soft_streak, 0)
        self.assertTrue(self.account.ready())

    def test_unknown_rate_limit_keeps_conservative_backoff(self):
        with mock.patch.object(wb_accounts, "urlopen", side_effect=limited(detail="slow down")):
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
        self.assertEqual(caught.exception.wait, 600)

    def test_concurrent_limits_share_window_and_keep_longest_hint(self):
        self.account.note_soft_rate("HTTP 429 (account soft rate)", request_rate=True)
        self.now += 1
        self.account.note_soft_rate("HTTP 429 (account soft rate)", request_rate=True)
        self.assertEqual(self.account.soft_streak, 1)
        self.assertEqual(self.account.cooldown_until, self.now + 29)
        self.account.note_soft_rate("HTTP 429 (account soft rate)", retry_after=120)
        self.account.note_soft_rate("HTTP 429 (account soft rate)", retry_after=3)
        self.assertEqual(self.account.soft_streak, 1)
        self.assertEqual(self.account.cooldown_until, self.now + 120)

    def test_restored_soft_rate_is_still_reported_as_429(self):
        self.account.note_soft_rate("HTTP 429 (account soft rate, code 14003)", request_rate=True)
        self.account.note_error("connection error", cooldown=3)
        self.pool.accounts = [wb_accounts.Account(self.account.to_dict())]
        with mock.patch.object(wb_accounts, "urlopen") as outbound:
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
            outbound.assert_not_called()
        self.assertEqual(caught.exception.wait, 30)

    def test_credential_refresh_cannot_clear_a_new_soft_rate(self):
        self.account.note_soft_rate("HTTP 429 (account soft rate)", request_rate=True)
        self.account.refresh_token = "synthetic-refresh"
        with mock.patch.object(wb_accounts, "http_json",
                               return_value={"data": {"accessToken": "new-token"}}):
            self.assertTrue(self.account.refresh())
        self.assertFalse(self.account.ready())
        self.assertEqual(self.account.soft_rate_until, self.now + 30)

    def test_generic_failure_cooldown_is_not_reported_as_rate_limit(self):
        self.account.note_error("connection error", cooldown=60)
        with mock.patch.object(wb_accounts, "urlopen") as outbound:
            with self.assertRaisesRegex(RuntimeError, "no usable account"):
                self.open()
            outbound.assert_not_called()

    def test_explicit_model_quota_without_reset_does_not_park_sibling_models(self):
        detail = json.dumps({"code": 6004, "msg": "usage exceeds frequency limit"})
        with mock.patch.object(wb_accounts, "urlopen", side_effect=limited(detail=detail)):
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
        self.assertEqual(caught.exception.wait, 60)
        self.assertTrue(self.account.ready(model="kimi-k3"))
        self.assertFalse(self.account.ready(model=PAYLOAD["model"]))

    def test_long_model_error_keeps_reset_beyond_old_body_limit(self):
        reset = datetime.datetime.fromtimestamp(self.now + 120, datetime.timezone.utc)
        detail = json.dumps({"padding": "x" * 1000, "code": 6004,
                             "msg": "usage will reset at " + reset.strftime("%Y-%m-%d %H:%M:%S UTC+0")})
        with mock.patch.object(wb_accounts, "urlopen",
                               side_effect=limited({"Retry-After": "7"}, detail=detail)):
            with self.assertRaises(wb_proxy.RateLimited) as caught:
                self.open()
        self.assertEqual(caught.exception.wait, 120)
        self.assertTrue(self.account.ready(model="kimi-k3"))

    def test_other_account_and_realm_are_not_parked(self):
        other = wb_accounts.Account({"uid": "healthy-international", "realm": "intl",
                                     "accessToken": "token", "expiresAt": self.now + 3600})
        domestic = wb_accounts.Account({"uid": "healthy-domestic", "realm": "cn",
                                        "accessToken": "token", "expiresAt": self.now + 3600})
        self.pool.accounts += [other, domestic]
        self.pool.apply_pool_config()
        self.account.note_soft_rate("HTTP 429 (account soft rate)", request_rate=True)
        with mock.patch.object(wb_accounts, "urlopen", return_value=io.BytesIO()):
            response, account, _ = self.open()
            response.close()
        self.assertIs(account, other)
        self.assertTrue(domestic.ready())

    def test_older_success_cannot_clear_a_new_soft_rate(self):
        started, complete = threading.Event(), threading.Event()
        results, errors = [], []

        def upstream(*args, **kwargs):
            if threading.current_thread().name == "older-request":
                started.set()
                if not complete.wait(3):
                    raise AssertionError("older request was not released")
                return io.BytesIO()
            raise limited()

        def older_request():
            try:
                results.append(self.open()[0])
            except Exception as exc:
                errors.append(exc)

        with mock.patch.object(wb_accounts, "urlopen", side_effect=upstream):
            thread = threading.Thread(target=older_request, name="older-request")
            thread.start()
            try:
                self.assertTrue(started.wait(3))
                with self.assertRaises(wb_proxy.RateLimited):
                    self.open()
                deadline = self.account.cooldown_until
            finally:
                complete.set()
                thread.join(3)
                for response in results:
                    response.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.account.cooldown_until, deadline)
        self.assertEqual(self.account.soft_streak, 1)
        self.assertFalse(self.account.ready(model=PAYLOAD["model"]))
        self.assertEqual(self.account.in_flight, 0)


class RetryHeaderTests(unittest.TestCase):
    def test_delay_seconds_case_and_fraction(self):
        self.assertEqual(wb_proxy.parse_retry_after({"retry-after": "1.2"}, now=1000), 2)
        self.assertEqual(wb_proxy.parse_retry_after({"Retry-After": "0"}, now=1000), 1)

    def test_http_date(self):
        self.assertEqual(wb_proxy.parse_retry_after(
            {"Retry-After": email.utils.formatdate(1123, usegmt=True)}, now=1000), 123)

    def test_invalid_headers_fall_back(self):
        for value in ["-1", "nan", "inf", "later", ""]:
            with self.subTest(value=value):
                self.assertIsNone(wb_proxy.parse_retry_after({"Retry-After": value}, now=1000))

    def test_reset_clock_is_independent_of_local_timezone_and_dst(self):
        expected = datetime.datetime(2026, 10, 13, 10, 0, tzinfo=datetime.timezone.utc).timestamp()
        # time.mktime previously applied the host's DST before subtracting a
        # standard offset. It must not participate in parsing an upstream clock.
        with mock.patch.object(time, "mktime", side_effect=AssertionError("local clock used")):
            self.assertEqual(wb_proxy.parse_rate_limit_reset(
                "RESET AT 2026-10-13 18:00:00 UTC+8"), expected)
        self.assertEqual(wb_proxy.parse_rate_limit_reset(
            "reset at 2026-10-13 09:30:00 UTC-00:30"), expected)
        self.assertIsNone(wb_proxy.parse_rate_limit_reset(
            "reset at 2026-10-13 18:00:00 UTC+8:99"))


if __name__ == "__main__":
    unittest.main()
