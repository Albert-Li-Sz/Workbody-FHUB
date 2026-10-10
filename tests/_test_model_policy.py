"""Channel policies, public listings, generation and quotas over real HTTP."""
import http.client
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_model_policy as M
import wb_proxy as P
import wb_settings as S
import _test_platform_http as fixture


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.directory = self.work.name

    def test_defaults_scopes_conflicts_and_restart(self):
        ids = {"one", "two"}
        self.assertEqual(M.resolve(self.directory, "workbuddy-cn", "one"), "one")
        M.update(self.directory, "workbuddy-cn", "one", {"alias": "fast", "enabled": False}, ids)
        M.update(self.directory, "workbuddy-intl", "two", {"alias": "fast"}, ids)
        with self.assertRaises(M.PolicyError):
            M.resolve(self.directory, "workbuddy-cn", "fast")
        self.assertEqual(M.resolve(self.directory, "workbuddy-intl", "fast"), "two")
        for patch in ({"alias": "two"}, {"alias": "cline/no"}, {"alias": "bad name"}, {"enabled": "false"}):
            with self.assertRaises(M.PolicyError):
                M.update(self.directory, "workbuddy-cn", "one", patch, ids)
        with self.assertRaises(M.PolicyError):
            M.update(self.directory, "workbuddy-cn", "two", {"alias": "fast"}, ids)
        S._settings_cache.clear()
        self.assertFalse(M.policies(self.directory, "workbuddy-cn")["one"]["enabled"])

    def test_alias_cannot_shadow_a_new_real_model(self):
        M.update(self.directory, "cline", "cline/one", {"alias": "fast"}, {"cline/one"})
        rows = M.expand([{"id": "cline/one"}, {"id": "cline/fast"}], M.policies(self.directory, "cline"), "cline")
        self.assertEqual([row["id"] for row in rows], ["cline/one", "cline/fast"])
        self.assertEqual(M.resolve(self.directory, "cline", "cline/fast", {"cline/one", "cline/fast"}), "cline/fast")
        # Native IDs still own their names when no eligible account can call
        # them and they are absent from the public list.
        rows = M.expand([{"id": "cline/one"}], M.policies(self.directory, "cline"), "cline",
                        real_ids={"cline/one", "cline/fast"})
        self.assertEqual([row["id"] for row in rows], ["cline/one"])


class HTTPTests(unittest.TestCase):
    setUp = fixture.IntegrationTests.setUp
    body = fixture.IntegrationTests.body
    request = fixture.IntegrationTests.request

    def panel(self, path, body=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            client.request("POST" if body is not None else "GET", path,
                body=json.dumps(body) if body is not None else None,
                headers={"X-Panel-Token": P.PANEL.create(), "Content-Type": "application/json"})
            result = client.getresponse()
            return result.status, json.loads(result.read())
        finally:
            client.close()

    def policy(self, channel="cline", model="cline/provider/model", **patch):
        return self.panel("/settings/models", {"channel": channel, "model_id": model, **patch})

    def test_management_auth_and_both_public_ids(self):
        self.assertEqual(self.request("/settings/models?channel=cline")[0], 401)
        self.assertEqual(self.request("/settings/models", {"channel": "cline"})[0], 401)
        self.assertEqual(self.policy(alias="friendly")[0], 200)
        status, raw, _ = self.request("/v1/models?upstream=cline")
        self.assertEqual(status, 200)
        rows = json.loads(raw)["data"]
        self.assertEqual({row["id"] for row in rows}, {"cline/provider/model", "cline/friendly"})
        self.assertTrue(next(row for row in rows if row["is_alias"])["canonical_id"] == "cline/provider/model")
        self.assertEqual(self.request("/v1/models/cline/friendly")[0], 200)
        self.assertEqual(self.request("/v1/models/friendly", key="synthetic-cline-only")[0], 200)
        self.assertEqual(self.policy(enabled=False)[0], 200)
        self.assertEqual(json.loads(self.request("/v1/models?upstream=cline")[1])["data"], [])
        self.assertEqual(self.panel("/settings/models?channel=cline")[1]["data"][0]["enabled"], False)
        self.assertEqual(self.request("/v1/models/cline/friendly")[0], 404)
        self.assertEqual(self.policy(enabled=True)[0], 200)

    def test_all_protocols_both_ids_streaming_and_canonical_accounting(self):
        for native, model in self.models.items():
            channel = "cline" if native == "chat" else "opencode_zen"
            self.assertEqual(self.policy(channel, model, alias="friendly-" + native)[0], 200)
            alias = M.PREFIXES[channel] + "friendly-" + native
            for public in (model, alias):
                for protocol in ("chat", "messages", "responses"):
                    for stream in (False, True):
                        path = "/v1/chat/completions" if protocol == "chat" else "/v1/" + protocol
                        status, raw, _ = self.request(path, self.body(protocol, public, stream))
                        self.assertEqual(status, 200, raw.decode())
                        self.assertIn(b"remembered", raw)
                        self.assertEqual(self.upstream.calls[-1][1]["model"], model.split("/", 1)[1])
            self.policy(channel, model, enabled=False)
            before = len(self.upstream.calls)
            for public in (model, alias):
                for protocol in ("chat", "messages", "responses"):
                    path = "/v1/chat/completions" if protocol == "chat" else "/v1/" + protocol
                    self.assertEqual(self.request(path, self.body(protocol, public))[0], 403)
            self.assertEqual(len(self.upstream.calls), before)
        self.assertEqual({row["model"] for row in self.db.usage_totals(group_by=("model",))}, set(self.models.values()))

    def test_alias_permissions_account_whitelist_and_response_continuation(self):
        self.policy(alias="friendly")
        self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "cline/friendly"), key="synthetic-legacy")[0], 403)
        data = S.load(P.ACCOUNTS_DIR)
        data["api_keys"][0]["models"] = ["opencode/*"]
        S.save(P.ACCOUNTS_DIR, data)
        self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "cline/friendly"))[0], 403)
        data["api_keys"][0]["models"] = ["cline/provider/model"]
        S.save(P.ACCOUNTS_DIR, data)
        first = self.request("/v1/responses", self.body("responses", "cline/friendly"))
        self.assertEqual(first[0], 200)
        previous = json.loads(first[1])["id"]
        self.assertEqual(self.request("/v1/responses", {"previous_response_id": previous, "input": "next", "model": "cline/provider/model"})[0], 200)
        self.policy(enabled=False)
        self.assertEqual(self.request("/v1/responses", {"previous_response_id": previous, "input": "next"})[0], 403)

    def test_workbuddy_aliases_are_scoped_to_the_key_realm(self):
        entries = [("one", {}), ("two", {})]
        with mock.patch.object(P, "fetch_models", return_value=entries), mock.patch.object(P, "_models_cache", {"cn": {"data": entries}, "intl": {"data": entries}}):
            self.policy("workbuddy-cn", "one", alias="fast")
            self.policy("workbuddy-intl", "two", alias="fast")
            data = S.load(P.ACCOUNTS_DIR)
            data["api_keys"][0]["realm"] = "cn"
            S.save(P.ACCOUNTS_DIR, data)
            captured = []
            def dispatch(handler, path, payload):
                captured.append(payload["model"])
                return handler._json(200, {"ok": True})
            with mock.patch.object(P.Handler, "_dispatch_chat_post", dispatch):
                self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "fast"))[0], 200)
                self.assertEqual(captured, ["one"])
                self.policy("workbuddy-cn", "one", enabled=False)
                self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "fast"))[0], 403)
                self.assertEqual(captured, ["one"])
                self.policy("workbuddy-cn", "one", enabled=True)
                data["api_keys"][0]["realm"] = ""
                S.save(P.ACCOUNTS_DIR, data)
                _, context = P.RESPONSE_STORE.prepare({"model": "one", "input": "first"}, "owner", list(S.UPSTREAMS), P.MAX_PAYLOAD_BYTES)
                stored = P.RESPONSE_STORE.finish({"status": "completed", "output": []}, context, "workbuddy", "cn", "one")
                with mock.patch.object(P, "CURRENT_REALM", "intl"):
                    self.assertEqual(self.request("/v1/responses", {"model": "fast", "previous_response_id": stored["id"], "input": "next"})[0], 200)
                self.assertEqual(captured[-1], "one", "continuation resolves the alias in the stored realm")

    def test_five_hour_api_sums_identities_and_keeps_incomplete_unknown(self):
        first = next(account for account in self.manager.accounts.values() if account.upstream == "cline")
        self.manager.import_accounts({"upstream": "cline", "access_token": "synthetic-extra", "enabled": False})
        second = next(account for account in self.manager.accounts.values() if account.upstream == "cline" and account != first)
        for account, remain, owner in ((first, 80, "person-a"), (second, 60, "person-b")):
            account.document.update(user_id=owner, quota={"fiveHour": {"remaining_percent": remain, "reset_at": "2099-01-01T00:00:00Z"}},
                billing_status={"quota": {"updated_at": time.time(), "stale": False}})
        for path in ("/v1/balance", "/api/billing/balance", "/user/balance", "/dashboard/billing/credit_grants"):
            status, raw, _ = self.request(path + "?upstream=cline")
            self.assertEqual(status, 200, raw.decode())
            result = json.loads(raw)
            self.assertEqual(result["total_remain"], 140)
            self.assertEqual((result["unit"], result["window"]), ("percent", "fiveHour"))
        self.assertEqual(json.loads(self.request("/api/billing/balance?upstream=cline")[1])["balance"], 140)
        second.document["user_id"] = "person-a"
        second.document["billing_status"]["quota"]["updated_at"] = 0
        self.assertEqual(json.loads(self.request("/v1/balance?upstream=cline")[1])["total_remain"], 80)
        second.document["user_id"] = "person-b"
        result = json.loads(self.request("/v1/balance?upstream=cline")[1])
        self.assertEqual((result["total_remain"], result["stale_count"], result["complete"]), (80, 1, False))
        self.assertEqual(self.request("/api/billing/balance?upstream=cline")[0], 503)
        self.assertEqual(self.request("/v1/balance?upstream=cline&refresh=maybe")[0], 400)
        with mock.patch.object(self.manager, "refresh_async") as refresh:
            self.request("/v1/balance?upstream=cline&refresh=0")
            refresh.assert_not_called()
            self.request("/v1/balance?upstream=cline&refresh=1")
            refresh.assert_called_once_with("cline", force=True)


if __name__ == "__main__":
    unittest.main()
