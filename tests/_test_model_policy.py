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
        M.update(self.directory, "cline", "one", {"alias": "fast"}, {"one"})
        rows = M.expand([{"id": "one"}, {"id": "fast"}], M.policies(self.directory, "cline"), "cline")
        self.assertEqual([row["id"] for row in rows], ["one", "fast"])
        self.assertEqual(M.resolve(self.directory, "cline", "cline/fast", {"one", "fast"}), "fast")
        # Native IDs still own their names when no eligible account can call
        # them and they are absent from the public list.
        rows = M.expand([{"id": "one"}], M.policies(self.directory, "cline"), "cline", real_ids={"one", "fast"})
        self.assertEqual([row["id"] for row in rows], ["one"])

    def test_batch_validation_scopes_deduplication_and_restart(self):
        for channel in M.CHANNELS:
            ids = {"first", "second"} if channel.startswith("workbuddy-") or channel == "cline" else {M.PREFIXES[channel] + name for name in ("first", "second")}
            first, second = sorted(ids)
            M.update(self.directory, channel, first, {"alias": "friendly"}, ids)
            result = M.update_enabled(self.directory, channel, [first, second, first], False, ids)
            self.assertEqual(result["count"], 2)
            for values, enabled in (([first, "missing"], True), ([], True), ([first, None], True), ([first], 1)):
                with self.assertRaises(M.PolicyError):
                    M.update_enabled(self.directory, channel, values, enabled, ids)
            S._settings_cache.clear()
            rules = M.policies(self.directory, channel)
            self.assertEqual({rule["enabled"] for rule in rules.values()}, {False})
            self.assertEqual(rules[first]["alias"], M.alias_id(channel, "friendly"))
            M.update_enabled(self.directory, channel, [first, second], True, ids)
            self.assertTrue(all(rule["enabled"] for rule in M.policies(self.directory, channel).values()))

    def test_legacy_policy_migration_is_unambiguous_and_runs_once(self):
        data = S.load(self.directory)
        data["model_policies"] = {"cline": {"cline/one": {"enabled": False, "alias": "cline/cline/fast"}}}
        S.save(self.directory, data)
        ids = {"one", "cline/one"}
        rules = M.policies(self.directory, "cline")
        self.assertEqual(rules, {"one": {"enabled": False, "alias": "cline/fast"}})
        decorated = M.decorate([{"id": "one"}, {"id": "cline/one"}], rules, "cline")
        self.assertEqual([row["enabled"] for row in decorated], [False, True])
        M.update_enabled(self.directory, "cline", ["one"], True, ids)
        M.update(self.directory, "cline", "cline/one", {"enabled": False}, ids)
        S._settings_cache.clear()
        self.assertEqual(M.policies(self.directory, "cline"), {"one": {"enabled": True, "alias": "cline/fast"}, "cline/one": {"enabled": False}})
        self.assertEqual(M.resolve(self.directory, "cline", "cline/fast", ids), "one")
        self.assertEqual(M.resolve(self.directory, "cline", "cline/cline/fast", ids), "one")


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

    def test_cline_native_ids_and_legacy_calls(self):
        model = "cline-pass/example"
        self.manager.catalogues["cline"]["models"] = {model: {"native_protocol": "chat", "billing_mode": "free"}}
        status, result = self.panel("/settings/models?channel=cline")
        self.assertEqual(status, 200)
        self.assertEqual([row["id"] for row in result["data"]], [model])
        self.assertEqual(self.policy(model=model, alias="friendly")[0], 200)
        rows = json.loads(self.request("/v1/models?upstream=cline")[1])["data"]
        self.assertEqual({row["id"] for row in rows}, {model, "friendly"})
        self.assertEqual({row["canonical_id"] for row in rows}, {model})
        for public in (model, "cline/" + model, "friendly", "cline/friendly"):
            with self.subTest(model=public):
                self.assertEqual(self.request("/v1/models/" + public)[0], 200)
                for protocol in ("chat", "messages", "responses"):
                    path = "/v1/chat/completions" if protocol == "chat" else "/v1/" + protocol
                    status, raw, _ = self.request(path, self.body(protocol, public))
                    self.assertEqual(status, 200, raw.decode())
                    self.assertEqual(json.loads(raw)["model"], model)
                    self.assertEqual(self.upstream.calls[-1][1]["model"], model)

    def test_batch_policy_is_atomic_and_keeps_aliases(self):
        self.manager.catalogues["cline"]["models"]["other/model"] = {"native_protocol": "chat", "billing_mode": "free"}
        self.assertEqual(self.policy(alias="friendly")[0], 200)
        body = {"channel": "cline", "model_ids": ["provider/model", "other/model"], "enabled": False}
        status, result = self.panel("/settings/models", body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["count"], 2)
        self.assertEqual(json.loads(self.request("/v1/models?upstream=cline")[1])["data"], [])
        status, result = self.panel("/settings/models", dict(body, enabled=True, model_ids=["provider/model", "missing"]))
        self.assertEqual(status, 404, result)
        self.assertEqual(json.loads(self.request("/v1/models?upstream=cline")[1])["data"], [])
        self.assertEqual(self.panel("/settings/models", dict(body, enabled=True))[0], 200)
        rows = self.panel("/settings/models?channel=cline")[1]["data"]
        self.assertEqual(next(row for row in rows if row["id"] == "provider/model")["alias"], "friendly")
        self.assertTrue(all(row["enabled"] for row in rows))
        self.assertEqual(self.request("/settings/models", body)[0], 401)

    def test_legacy_cline_policies_keys_and_response_history(self):
        data = S.load(P.ACCOUNTS_DIR)
        data["model_policies"] = {"cline": {"cline/provider/model": {"alias": "cline/friendly", "enabled": False}}}
        data["api_keys"][0]["models"] = ["cline/provider/model"]
        S.save(P.ACCOUNTS_DIR, data)
        self.assertEqual(json.loads(self.request("/v1/models?upstream=cline")[1])["data"], [])
        for model in ("provider/model", "cline/provider/model", "friendly", "cline/friendly"):
            self.assertEqual(self.request("/v1/chat/completions", self.body("chat", model))[0], 403)
        self.assertEqual(self.policy(model="provider/model", enabled=True)[0], 200)
        S._settings_cache.clear()
        rows = self.panel("/settings/models?channel=cline")[1]["data"]
        self.assertEqual((rows[0]["alias"], rows[0]["enabled"]), ("friendly", True))
        _, context = P.RESPONSE_STORE.prepare({"model": "cline/provider/model", "input": "first"}, "owner", list(S.UPSTREAMS), P.MAX_PAYLOAD_BYTES)
        previous = P.RESPONSE_STORE.finish({"status": "completed", "output": []}, context, "cline", "", "cline/provider/model")
        status, raw, _ = self.request("/v1/responses", {"model": "friendly", "previous_response_id": previous["id"], "input": "next"})
        self.assertEqual(status, 200, raw.decode())
        self.assertEqual(json.loads(raw)["model"], "provider/model")
        self.assertEqual(self.upstream.calls[-1][1]["model"], "provider/model")
        data = S.load(P.ACCOUNTS_DIR)
        data["api_keys"][0]["models"] = ["provider/model"]
        S.save(P.ACCOUNTS_DIR, data)
        self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "cline/friendly"))[0], 200)

    def test_cline_and_workbuddy_name_collision_never_changes_platform(self):
        entries = [("provider/model", {})]
        with mock.patch.object(P, "fetch_models", return_value=entries), mock.patch.object(P, "_models_cache", {"cn": {"data": entries}, "intl": {"data": entries}}):
            self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "provider/model"))[0], 400)
            self.assertEqual(self.upstream.calls, [])
            self.assertEqual(self.request("/v1/chat/completions?upstream=cline", self.body("chat", "provider/model"))[0], 200)
            self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "cline/provider/model"))[0], 200)
            captured = []
            def dispatch(handler, path, payload):
                self.assertNotIn("_platform_upstream", payload)
                captured.append(payload["model"])
                return handler._json(200, {"ok": True})
            with mock.patch.object(P.Handler, "_dispatch_chat_post", dispatch):
                self.assertEqual(self.request("/v1/chat/completions?upstream=workbuddy", dict(self.body("chat", "provider/model"), _platform_upstream="cline"))[0], 200)
                self.assertEqual(self.request("/v1/chat/completions", self.body("chat", "provider/model"), key="synthetic-legacy")[0], 200)
            self.assertEqual(captured, ["provider/model", "provider/model"])

    def test_management_auth_and_both_public_ids(self):
        self.assertEqual(self.request("/settings/models?channel=cline")[0], 401)
        self.assertEqual(self.request("/settings/models", {"channel": "cline"})[0], 401)
        self.assertEqual(self.policy(alias="friendly")[0], 200)
        status, raw, _ = self.request("/v1/models?upstream=cline")
        self.assertEqual(status, 200)
        rows = json.loads(raw)["data"]
        self.assertEqual({row["id"] for row in rows}, {"provider/model", "friendly"})
        self.assertTrue(next(row for row in rows if row["is_alias"])["canonical_id"] == "provider/model")
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
        self.assertEqual({row["model"] for row in self.db.usage_totals(group_by=("model",))}, {"provider/model", self.models["responses"], self.models["messages"]})

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
