"""Free fairness uses a large session window within each realm."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RUNTIME = tempfile.TemporaryDirectory(prefix="wb-free-runtime-")
os.environ["ACCOUNTS_DIR"] = _RUNTIME.name
os.environ["WB_PROXY_USAGE_DIR"] = _RUNTIME.name
import wb_accounts as A
import wb_pool
import wb_proxy as P
import wb_settings


class FairnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wb-fair-")
        self.addCleanup(self.directory.cleanup)
        self.pool = A.AccountPool(self.directory.name)
        for realm in ("cn", "intl"):
            for i in range(3):
                a = A.Account({"uid": realm + str(i), "realm": realm,
                               "accessToken": "synthetic", "expiresAt": time.time() + 86400,
                               "credits": {"remain": [1, 100, 10000][i]}})
                a.free_models = frozenset({"free-model"})
                self.pool.accounts.append(a)

    def test_each_realm_rotates_independently_despite_balance_weights(self):
        with mock.patch.object(wb_pool, "choose", side_effect=lambda candidates, *args, **kwargs: candidates[0]):
            cn, intl = [], []
            for i in range(12):
                cn.append(self.pool.pick(realm="cn", model="free-model").uid)
                intl.append(self.pool.pick(realm="intl", model="free-model").uid)
        self.assertEqual(Counter(cn), {"cn0": 4, "cn1": 4, "cn2": 4})
        self.assertEqual(Counter(intl), {"intl0": 4, "intl1": 4, "intl2": 4})

    def test_token_growth_below_window_keeps_the_session_account(self):
        for realm in ("cn", "intl"):
            key = realm + "-session"
            account = self.pool.pick_for_session(realm=realm, model="free-model", session_key=key)
            for load in (1, 1000, 64000, 262143):
                account.free_tokens_today = load
                self.assertIs(self.pool.pick_for_session(realm=realm, model="free-model", session_key=key), account)
            account.free_tokens_today = 262144
            chosen = self.pool.pick_for_session(realm=realm, model="free-model", session_key=key)
            self.assertIsNot(chosen, account)
            self.assertEqual(chosen.realm, realm)
            self.assertEqual(self.pool.affinity.get(key), chosen.uid)

    def test_window_counts_pending_tokens_and_zero_uses_exact_minimum(self):
        account = self.pool.get("cn0")
        self.pool.affinity.bind("session", account.uid)
        account.free_tokens_today = 262143
        reservation = {"id": "pending", "kind": "free", "tokens": 1, "credit": 0}
        self.assertTrue(account.acquire(reservation))
        try:
            self.assertIsNot(self.pool.pick_for_session(realm="cn", model="free-model", session_key="session"), account)
        finally:
            account.release("pending")
        self.pool.apply_pool_config({"free_switch_window_tokens": 0})
        self.pool.affinity.bind("session", account.uid)
        account.free_tokens_today = 0
        self.assertIs(self.pool.pick_for_session(realm="cn", model="free-model", session_key="session"), account)
        account.free_tokens_today = 1
        self.assertIsNot(self.pool.pick_for_session(realm="cn", model="free-model", session_key="session"), account)

    def test_preferred_continuation_ignores_growth_but_obeys_health_priority_and_realm(self):
        account = self.pool.get("cn0")
        account.free_tokens_today = 1000000
        account.daily_credits_today = 1000000
        for model in ("free-model", "paid-model"):
            self.assertIs(self.pool.pick_for_session(realm="cn", model=model, preferred_uid=account.uid), account)
        self.assertIsNot(self.pool.pick_for_session(realm="intl", model="free-model", preferred_uid=account.uid), account)
        self.assertIsNot(self.pool.pick_for_session(realm="cn", model="free-model", preferred_uid=account.uid,
                                                  exclude={account.uid}), account)
        account.enabled = False
        self.assertIsNot(self.pool.pick_for_session(realm="cn", model="free-model", preferred_uid=account.uid), account)
        account.enabled = True
        self.pool.get("cn1").priority = 0
        self.assertEqual(self.pool.pick_for_session(realm="cn", model="free-model", preferred_uid=account.uid).uid, "cn1")

    def test_window_survives_settings_reload_and_invalid_values_are_rejected(self):
        self.assertEqual(wb_settings.pool_config(self.directory.name)["free_switch_window_tokens"], 262144)
        wb_settings.set_pool_config(self.directory.name, {"free_switch_window_tokens": 524288})
        restored = A.AccountPool(self.directory.name)
        restored.load()
        self.assertEqual(restored.pool_cfg["free_switch_window_tokens"], 524288)
        for invalid in (-1, True, "1024", 1.5):
            with self.assertRaises(ValueError):
                wb_pool.validate_patch({"free_switch_window_tokens": invalid})

    def test_cost_learning_does_not_starve_untried_free_accounts(self):
        picked = []
        for i in range(12):
            account = self.pool.pick_for_session(realm="cn", model="free-model", session_key="new-session-%d" % i)
            picked.append(account.uid)
            self.pool.note_model_cost(account.uid, "free-model", 0)
        self.assertEqual(Counter(picked), {"cn0": 4, "cn1": 4, "cn2": 4})

    def test_concurrent_selection_skips_unavailable_accounts(self):
        self.pool.get("cn1").enabled = False
        self.pool.get("cn2").model_cooldowns["free-model"] = time.time() + 100
        self.assertEqual(self.pool.pick(realm="cn", model="free-model").uid, "cn0")
        self.pool.get("cn1").enabled = True
        self.pool.get("cn2").model_cooldowns.clear()
        with ThreadPoolExecutor(max_workers=8) as executor:
            picked = list(executor.map(lambda _: self.pool.pick(realm="intl", model="free-model").uid, range(120)))
        self.assertEqual(Counter(picked), {"intl0": 40, "intl1": 40, "intl2": 40})

    def test_paid_sessions_keep_existing_affinity(self):
        bound = self.pool.get("cn2")
        self.pool.affinity.bind("paid-session", bound.uid)
        for _ in range(3):
            self.assertIs(self.pool.pick_for_session(realm="cn", model="paid-model", session_key="paid-session"), bound)

    def test_catalogue_is_applied_even_without_a_daily_credit_cap(self):
        with mock.patch.object(P, "POOL", self.pool), \
                mock.patch.object(P.wb_settings, "daily_credit_limit", return_value=0), \
                mock.patch.object(P, "free_models_by_realm", return_value={"cn": {"new-free"}, "intl": set()}):
            P.apply_daily_credit_limit()
        self.assertTrue(self.pool.get("cn0").model_is_free("new-free"))
        self.assertFalse(self.pool.get("intl0").model_is_free("new-free"))

    def test_cached_paid_price_supersedes_a_bundled_free_price(self):
        with mock.patch.object(P.wb_catalog, "STATIC_CN_MODELS", [{"id": "changed-model", "credits": "x0.00"}]), \
                mock.patch.object(P, "_free_models_cache", {}), \
                mock.patch.object(P, "read_cached_remote_catalog", side_effect=lambda realm: (0, {"changed-model": {"credits": "x1.00"}}) if realm == "cn" else None):
            self.assertNotIn("changed-model", P.free_models_by_realm()["cn"])

    def test_fairness_can_be_disabled_and_paid_round_robin_is_preserved(self):
        self.pool.apply_pool_config({"weighted_pick": False, "free_fair_pick": False})
        picked = [self.pool.pick(realm="cn", model="paid-model").uid for _ in range(6)]
        self.assertEqual(Counter(picked), {"cn0": 2, "cn1": 2, "cn2": 2})
        bound = self.pool.get("cn1")
        self.pool.affinity.bind("old-mode", bound.uid)
        self.assertIs(self.pool.pick_for_session(realm="cn", model="free-model", session_key="old-mode"), bound)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _RUNTIME.cleanup()
