"""All-account balance queries: exact sums, partial failures and privacy."""
import os
import json
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.TemporaryDirectory(prefix="wb-balance-")
os.environ["ACCOUNTS_DIR"] = os.path.join(_TMP.name, "accounts")
os.environ["WB_PROXY_USAGE_DIR"] = _TMP.name
import wb_proxy as P


class Handler(P.Handler):
    def __init__(self): self.response = None
    def _authorized(self): return True
    def _json(self, status, payload): self.response = (status, payload)


def account(uid, realm, remain, enabled=True, error=False):
    a = types.SimpleNamespace(uid=uid, realm=realm, nickname=uid, enabled=enabled,
                              credits={"remain": remain, "updated_at": 100},
                              access_token="synthetic-secret-never-return")
    def fetch():
        if error:
            raise RuntimeError("synthetic-secret-never-return")
        a.credits = dict(a.credits, updated_at=200)
        return {"ok": True}
    a.fetch_credits = mock.Mock(side_effect=fetch)
    return a


class BalanceTests(unittest.TestCase):
    def test_sum_includes_disabled_accounts_and_both_realms(self):
        accounts = [account("a", "cn", 0.1), account("b", "intl", "0.2", False),
                    account("c", "cn", 0), account("d", "intl", None)]
        with mock.patch.object(P, "POOL", types.SimpleNamespace(accounts=accounts)):
            h = Handler()
            h._get_accounts_balance()
        status, result = h.response
        self.assertEqual(status, 200)
        self.assertEqual(result["total_remain"], 0.3)
        self.assertEqual(result["by_realm"]["cn"]["total_remain"], 0.1)
        self.assertEqual(result["by_realm"]["intl"]["total_remain"], 0.2)
        self.assertEqual(result["account_count"], 4)
        self.assertEqual(result["unknown_count"], 1)
        self.assertFalse(result["complete"])
        self.assertNotIn("synthetic-secret", str(result))
        for a in accounts:
            a.fetch_credits.assert_not_called()

    def test_refresh_failure_preserves_known_balance_and_reports_partial_total(self):
        accounts = [account("a", "cn", 10), account("b", "intl", 20, False, error=True)]
        with mock.patch.object(P, "POOL", types.SimpleNamespace(accounts=accounts)):
            h = Handler()
            h._route_accounts_balance()
        result = h.response[1]
        self.assertEqual(result["total_remain"], 30)
        self.assertEqual(result["refresh_failed"], 1)
        self.assertFalse(result["complete"])
        self.assertTrue(result["refreshed"])
        self.assertNotIn("synthetic-secret", str(result))
        for a in accounts:
            a.fetch_credits.assert_called_once()

    def test_invalid_and_large_cached_balances_do_not_break_json_response(self):
        accounts = [account("a", "cn", "1e30"), account("b", "cn", "-1e30"),
                    account("c", "cn", "0.3"), account("d", "intl", "NaN"),
                    account("e", "intl", True)]
        result = P.wb_balance.summarize(accounts)
        self.assertEqual(result["total_remain"], 0.3)
        self.assertEqual(result["unknown_count"], 2)
        json.dumps(result, allow_nan=False)
        overflow = P.wb_balance.summarize([account("f", "cn", "1e308"), account("g", "cn", "1e308")])
        self.assertIsNone(overflow["total_remain"])
        self.assertFalse(overflow["complete"])
        json.dumps(overflow, allow_nan=False)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _TMP.cleanup()
