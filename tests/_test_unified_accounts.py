"""Synthetic OAuth, routing, persistence and provider policy contracts."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_platforms as U
import wb_device_auth as D
import wb_cline_routes as C
import wb_settings as S
import wb_opencode_client as O
import wb_database
import wb_responses


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.manager = U.Manager(self.work.name)
        self.manager.refresh_async = lambda *args, **kwargs: None
        self.calls = []
        self.tokens = 0
        self.cancel_on_token = False
        self.orgs = [{"id": "org-one", "name": "One"}]
        self.manager.transport = self.transport

    def transport(self, request, **options):
        self.calls.append((request, options))
        path = urllib.parse.urlsplit(request.full_url).path
        if path.endswith(("authorize/device", "/device/code")):
            result = {"device_code": "private-device", "user_code": "CODE-FIXTURE", "expires_in": 600, "interval": 1,
                "verification_uri_complete": "https://opencode.ai/console/auth/device?code=CODE-FIXTURE"}
        elif path.endswith(("/authenticate", "/device/token")):
            self.tokens += 1
            if self.cancel_on_token:
                self.manager.cancel_login(self.job["id"])
            result = {"access_token": "private-access", "refresh_token": "private-refresh", "expires_in": 3600}
        elif path.endswith("/auth/register"):
            result = {"data": {"accessToken": "registered-cline", "refreshToken": "private-refresh", "expiresAt": time.time()+3600,
                "userInfo": {"clineUserId": "cline-user", "email": "fixture@example.test"}}}
        elif path.endswith("/api/user"):
            result = {"id": "console-user", "email": "fixture@example.test"}
        elif path.endswith("/api/orgs"):
            result = self.orgs
        elif path.endswith("/api/config"):
            result = {"config": {"provider": {"opencode": {"npm": "@ai-sdk/openai-compatible", "options": {
                "baseURL": "https://opencode.ai/zen/v1", "apiKey": "tenant-api-key"}, "models": {
                "configured-model": {"id": "wire-model", "limit": {"context": 1000000}}}}}}}
        else:
            raise AssertionError(path)
        return io.BytesIO(json.dumps(result).encode())

    def start(self, upstream, **options):
        with mock.patch.object(threading.Thread, "start"):
            view = self.manager.start_login(upstream, options)
        self.job = self.manager.logins.jobs[view["id"]]
        self.job["cancel"].wait = lambda interval: False
        return view

    def finish(self):
        self.manager.logins._poll(self.job, {"device_code": "private-device", "interval": 1})
        return self.manager.poll_login(self.job["id"])

    def test_cline_login_and_metadata_are_private(self):
        view = self.start("cline", priority=7, access_scope="subscription")
        self.assertNotIn("private-device", json.dumps(view))
        result = self.finish()
        self.assertEqual(result["status"], "completed")
        account = self.manager.accounts[result["account"]]
        self.assertEqual(account.token, "workos:registered-cline")
        self.assertEqual(account.priority, 7)
        self.assertFalse(account.allows("paid-model"))
        self.assertTrue(account.allows("cline-pass/model"))
        self.assertNotIn("private-refresh", json.dumps(result))

    def test_opencode_console_login_uses_tenant_config(self):
        self.start("opencode_zen")
        result = self.finish()
        self.assertEqual(result["status"], "completed")
        account = self.manager.accounts[result["account"]]
        self.assertTrue(account.view()["credential_ready"])
        self.assertEqual(self.manager.headers(account)["Authorization"], "Bearer tenant-api-key")
        self.assertTrue(account.allows("configured-model"))
        self.assertFalse(account.allows("unconfigured-model"))
        self.assertEqual(self.manager.model("opencode_zen", "configured-model")["native_protocol"], "chat")
        self.assertNotIn("tenant-api-key", json.dumps(self.manager.snapshot()))
        body=json.loads(self.calls[0][0].data)
        self.assertEqual(body["client_id"], "opencode-cli")

    def test_multiple_orgs_require_explicit_choice(self):
        self.orgs.append({"id": "org-two", "name": "Two"})
        self.start("opencode_zen")
        result = self.finish()
        self.assertEqual(result["status"], "select_org")
        self.assertFalse(self.manager.accounts)
        self.assertNotIn("private-access", json.dumps(result))
        with self.assertRaises(U.PlatformError):
            self.manager.complete_login(result["id"], "unavailable")
        done = self.manager.complete_login(result["id"], "org-two")
        self.assertEqual(self.manager.accounts[done["account"]].document["org_id"], "org-two")
        self.assertEqual(self.calls[-1][0].get_header("X-org-id"), "org-two")

    def test_cancelled_inflight_token_cannot_import(self):
        self.start("cline")
        self.cancel_on_token = True
        self.assertEqual(self.finish()["status"], "cancelled")
        self.assertFalse(self.manager.accounts)

    def test_cancelled_pending_org_drops_tokens(self):
        self.orgs.append({"id": "org-two"})
        self.start("opencode_zen")
        self.finish()
        result=self.manager.cancel_login(self.job["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertNotIn("tokens", self.job)
        with self.assertRaises(U.PlatformError):
            self.manager.complete_login(self.job["id"], "org-one")

    def test_expiry_and_access_denied(self):
        self.start("opencode_zen")
        self.job["expires_at"]=time.time()-1
        self.assertEqual(self.manager.poll_login(self.job["id"])["status"], "expired")
        self.start("cline")
        self.manager.logins._request=lambda *a,**k:{"error":"access_denied"}
        self.assertEqual(self.finish()["status"], "denied")

    def test_pending_and_slowdown_are_not_failures(self):
        self.start("opencode_zen")
        original=self.manager.logins._request
        pending=iter([{"error":"authorization_pending"},{"error":"slow_down"}])
        waits=[]
        self.job["cancel"].wait=lambda interval: waits.append(interval) or False
        def request(url,*args,**kwargs):
            if url.endswith("/device/token"):
                return next(pending, {"access_token":"private-access","refresh_token":"private-refresh","expires_in":3600})
            return original(url,*args,**kwargs)
        self.manager.logins._request=request
        self.assertEqual(self.finish()["status"], "completed")
        self.assertEqual(waits, [1,1,6])

    def test_no_org_is_clear_failure(self):
        self.orgs=[]
        self.start("opencode_zen")
        result = self.finish()
        self.assertEqual(result["status"], "failed")
        self.assertIn("create one in the official console", result["error"])
        self.assertFalse(self.manager.accounts)

    def test_console_rejects_nonofficial_gateway(self):
        self.assertFalse(D.official_url("https://opencode.ai.evil.test/v1"))
        self.assertFalse(D.official_url("https://opencode.ai:bad/v1"))
        self.assertFalse(D.official_url("http://opencode.ai/v1"))
        self.assertIsNone(D.console_gateway({"provider":{"x":{"options":{"baseURL":"https://evil.test"},"models":{"x":{}}}}}))
        for gateway in ("invalid", {"url":"https://evil.test","api_key":"secret","models":{"x":{}}},
                        {"url":"https://opencode.ai/zen/v1","models":{"x":{}}}):
            with self.assertRaises(U.PlatformError):
                self.manager.import_accounts({"upstream":"opencode_zen","auth_type":"oauth","access_token":"console-token","console_gateway":gateway})

    def test_console_keeps_zen_and_go_routes_separate_through_restart_and_import(self):
        config = {"provider": {
            "opencode": {"api": "https://opencode.ai/inference/openai/v1", "npm": "@ai-sdk/openai-compatible",
                "options": {"apiKey": "zen-private", "headers": {"x-opencode-org-id": "zen-org"}},
                "models": {"same-model": {"cost": {"input": 1, "output": 2}}}},
            "opencode-go": {"api": "https://opencode.ai/inference/go/openai/v1", "npm": "@ai-sdk/openai-compatible",
                "options": {"apiKey": "{env:OPENCODE_CONSOLE_TOKEN}", "headers": {"x-opencode-org-id": "go-org"}},
                "models": {"same-model": {"cost": {"input": 1, "output": 2}, "provider": {
                    "npm": "@ai-sdk/anthropic", "api": "https://opencode.ai/inference/go/anthropic/v1"}}}}}}
        gateway = D.console_gateway(config)
        view = self.manager.import_accounts({"upstream": "opencode_zen", "auth_type": "oauth",
            "access_token": "go-current", "console_gateway": gateway})[0]
        account = self.manager.accounts[view["uid"]]
        self.assertTrue(account.allows("same-model"))
        self.assertTrue(account.allows("go/same-model"))
        self.assertEqual(self.manager.headers(account, model="same-model")["Authorization"], "Bearer zen-private")
        self.assertEqual(self.manager.headers(account, model="go/same-model")["Authorization"], "Bearer go-current")
        self.assertEqual(self.manager.headers(account, model="go/same-model")["x-opencode-org-id"], "go-org")
        meta = self.manager.model("opencode_zen", "go/same-model")
        self.assertEqual((meta["native_protocol"], meta["entitlement"], meta["billing_mode"]), ("messages", "subscription", "paid"))
        self.assertNotIn("pricing", meta)
        self.assertEqual(meta["reference_pricing"]["unit"], "USD/1M tokens")
        captured = []
        self.manager.transport = lambda request, **kwargs: captured.append(request) or io.BytesIO(b'{}')
        lease = self.manager.open("opencode_zen", "go/same-model", {"messages": []}, meta)
        lease.close()
        self.assertEqual(captured[-1].full_url, "https://opencode.ai/inference/go/anthropic/v1/messages")
        self.assertEqual(json.loads(captured[-1].data)["model"], "same-model")
        self.assertEqual(captured[-1].get_header("Authorization"), "Bearer go-current")
        self.manager.import_accounts(self.manager.export_accounts())
        reloaded = U.Manager(self.work.name)
        restored = reloaded.accounts[account.uid]
        self.assertTrue(restored.allows("go/same-model"))
        public = json.dumps([reloaded.snapshot(), reloaded.models(["opencode_zen"])])
        for secret in ("zen-private", "go-current", "OPENCODE_CONSOLE_TOKEN"):
            self.assertNotIn(secret, public)
        self.assertEqual(D.console_gateway({"disabled_providers": ["opencode-go"], **config})["models"].keys(), {"same-model"})

    def test_console_prices_are_per_million_and_go_does_not_grant_api_key_accounts(self):
        models = U.parse_catalog("opencode_zen", {"models": {
            "priced": {"cost": {"input": 1.2, "output": 3, "cache_read": 0.1}},
            "free": {"cost": {"input": 0, "output": 0}}}})
        self.assertEqual(models["priced"]["pricing"]["input"], 1.2)
        self.assertEqual(models["priced"]["pricing"]["unit"], "USD/1M tokens")
        self.assertEqual(models["free"]["billing_mode"], "free")
        view = self.manager.import_accounts({"upstream": "opencode_zen", "api_key": "zen-only"})[0]
        self.assertFalse(self.manager.accounts[view["uid"]].allows("go/priced", {"console_provider": "opencode-go"}))

    def test_roundtrip_priority_and_mixed_credential_types(self):
        accounts=self.manager.import_accounts([{ "upstream":"cline","api_key":"sk_fixture","priority":4},
            {"upstream":"cline","access_token":"oauth-fixture","refresh_token":"refresh-fixture"},
            {"upstream":"commandcode","api_key":"user_fixture_key","priority":9}])
        exported=self.manager.export_accounts()
        self.manager.import_accounts(exported)
        for item in accounts:
            self.assertEqual(self.manager.accounts[item["uid"]].view()["auth_type"], item["auth_type"])
        reloaded=U.Manager(self.work.name)
        self.assertEqual(reloaded.accounts[accounts[0]["uid"]].priority,4)
        self.assertNotIn("sk_fixture",json.dumps(reloaded.snapshot()))
        self.assertEqual(reloaded.accounts[accounts[2]["uid"]].token,"user_fixture_key")

    def test_dry_run_does_not_persist(self):
        self.manager.import_accounts({"upstream":"commandcode","api_key":"user_fixture_key"},dry_run=True)
        self.assertFalse(self.manager.accounts)
        self.assertFalse(os.listdir(self.manager.root))

    def test_manual_failover_and_recovery_persist(self):
        views=self.manager.import_accounts([{"upstream":"cline","api_key":"sk_first"},{"upstream":"cline","api_key":"sk_second"}])
        uid=views[0]["uid"]
        self.manager.set_routing("cline","manual",uid)
        meta={"billing_mode":"free"}
        a,ticket=self.manager.reserve("cline","model",meta,"","",1)
        self.assertEqual(a.uid,uid);self.manager.release(ticket)
        a.cooldowns["*"]=time.time()+60
        other,ticket=self.manager.reserve("cline","model",meta,"","",1)
        self.assertNotEqual(other.uid,uid);self.manager.release(ticket)
        a.cooldowns.clear()
        chosen,ticket=self.manager.reserve("cline","model",meta,"","",1)
        self.assertEqual(chosen.uid,uid);self.manager.release(ticket)
        self.assertEqual(U.Manager(self.work.name).routing()["cline"]["uid"],uid)

    def test_roundrobin_and_bound_history(self):
        views=self.manager.import_accounts([{"upstream":"cline","api_key":"sk_first"},{"upstream":"cline","api_key":"sk_second"}])
        self.manager.set_routing("cline","roundrobin")
        chosen=[]
        for _ in range(4):
            account,ticket=self.manager.reserve("cline","model",{"billing_mode":"free"},"same","owner",1)
            chosen.append(account.uid);self.manager.release(ticket)
        self.assertEqual(chosen[0],chosen[2]);self.assertNotEqual(chosen[0],chosen[1])
        self.manager.set_routing("cline","manual",views[0]["uid"])
        account,ticket=self.manager.reserve("cline","model",{"billing_mode":"free"},"","",1,views[1]["uid"])
        self.assertEqual(account.uid,views[1]["uid"]);self.manager.release(ticket)

    def test_cline_routes_both_pipelines_and_observations(self):
        policy={"mode":"preferred","providers":["z-ai"],"excluded":["other"],"known_providers":["z-ai","other"],"sort":"latency"}
        body=C.apply({"model":"pass"},policy)
        self.assertEqual(body["provider"]["order"],["z-ai"])
        self.assertEqual(body["providerOptions"]["gateway"]["only"],["z-ai"])
        self.assertEqual(body["providerOptions"]["gateway"]["sort"],"ttft")
        self.assertEqual(C.observed({"choices":[{"message":{"provider_metadata":{"gateway":{"routing":{"finalProvider":"z-ai"}}}}}]}),
                         {"provider":"z-ai","pipeline":"planner","model":""})
        with self.assertRaises(ValueError): C.validate({"mode":"strict"})
        with self.assertRaises(ValueError): C.validate({"excluded":["other"]})

    def test_command_namespace_and_plan_eligibility(self):
        self.assertEqual(U.route("commandcode/model",{"allowed_upstreams":["commandcode"]})[0],"commandcode")
        with self.assertRaises(U.PlatformError): U.route("commandcode/model",None)
        view=self.manager.import_accounts({"upstream":"commandcode","api_key":"user_fixture_key"})[0]
        account=self.manager.accounts[view["uid"]];account.document["plan"]="individual-go"
        self.assertFalse(account.allows("model",{"min_plan":"goat"}))
        self.assertTrue(account.allows("model",{"min_plan":"go"}))

    def test_opencode_client_identity_and_private_tenant_headers(self):
        first=O.headers("account", "conversation", "owner", {"metadata":{"project_id":"project"}})
        second=O.headers("account", "conversation", "owner", {"metadata":{"project_id":"project"}})
        self.assertEqual(first["x-opencode-session"],second["x-opencode-session"])
        self.assertEqual(first["x-opencode-project"],second["x-opencode-project"])
        self.assertNotEqual(first["x-opencode-request"],second["x-opencode-request"])
        self.assertNotEqual(first["x-opencode-session"],O.headers("other","conversation","owner")["x-opencode-session"])
        self.assertEqual(first["x-opencode-client"],"cli")
        self.assertEqual(first["x-opencode-session-id"],first["x-opencode-session"])
        self.assertEqual(first["x-opencode-request-id"],first["x-opencode-request"])
        self.assertTrue(first["x-opencode-request"].startswith("msg_"))
        view=self.manager.import_accounts({"upstream":"opencode_zen","auth_type":"oauth","access_token":"console-token"})[0]
        headers=self.manager.headers(self.manager.accounts[view["uid"]])
        self.assertNotIn("Authorization",headers)
        self.assertNotIn("x-api-key",headers)
        self.assertIsNone(D.console_gateway({"provider":{"opencode":{"options":{"baseURL":"https://opencode.ai/zen/v1"},"models":{"model":{}}}}}))

    def test_official_console_config_keeps_provider_api_and_org_header(self):
        config = {"provider": {"opencode": {"npm": "@ai-sdk/openai-compatible",
            "api": "https://opencode.ai/inference/openai/v1",
            "options": {"apiKey": "{env:OPENCODE_CONSOLE_TOKEN}", "headers": {"x-opencode-org-id": "org-one"}},
            "models": {"big-pickle": {}, "claude-fixture": {"provider": {
                "npm": "@ai-sdk/anthropic", "api": "https://opencode.ai/inference/anthropic/v1"}},
                "disabled-model": {"disabled": True}, "untrusted-model": {"provider": {"api": "https://evil.test/v1"}}}}}}
        gateway = D.console_gateway(config)
        self.assertIsNotNone(gateway)
        self.assertEqual(gateway["url"], "https://opencode.ai/inference/openai/v1")
        self.assertEqual(gateway["headers"]["x-opencode-org-id"], "org-one")
        self.assertNotIn("disabled-model", gateway["models"])
        self.assertNotIn("untrusted-model", gateway["models"])
        uid = self.manager.import_accounts({"upstream": "opencode_zen", "auth_type": "oauth",
            "access_token": "account-one-access", "org_id": "org-one", "console_gateway": gateway})[0]["uid"]
        self.assertEqual(self.manager.model("opencode_zen", "claude-fixture")["native_protocol"], "messages")
        headers = self.manager.headers(self.manager.accounts[uid])
        self.assertEqual(headers["Authorization"], "Bearer account-one-access")
        self.assertEqual(headers["x-opencode-org-id"], "org-one")
        self.assertNotIn("account-one-access", json.dumps(self.manager.snapshot()))

    def test_console_token_templates_are_account_local_and_follow_refresh(self):
        gateway = {"url": "https://opencode.ai/inference/openai/v1", "provider": "opencode",
            "api_key": "{env:OPENCODE_CONSOLE_TOKEN}", "headers": {}, "models": {"big-pickle": {}}}
        views = self.manager.import_accounts([{"upstream": "opencode_zen", "auth_type": "oauth",
            "access_token": "first-access", "console_gateway": gateway},
            {"upstream": "opencode_zen", "auth_type": "oauth", "access_token": "second-access", "console_gateway": gateway}])
        first, second = [self.manager.accounts[v["uid"]] for v in views]
        with mock.patch.dict(os.environ, {"OPENCODE_CONSOLE_TOKEN": "other-process-secret"}):
            self.assertEqual(self.manager.headers(first)["Authorization"], "Bearer first-access")
            self.assertEqual(self.manager.headers(second)["Authorization"], "Bearer second-access")
            first.document["access_token"] = "refreshed-first-access"
            self.assertEqual(self.manager.headers(first)["x-api-key"], "refreshed-first-access")
            self.assertEqual(self.manager.headers(second)["x-api-key"], "second-access")
        restarted = U.Manager(self.manager.directory, self.manager.database)
        self.assertEqual(restarted.headers(restarted.accounts[first.uid])["Authorization"], "Bearer first-access")

    def test_console_config_rejects_unresolved_environment_and_file_credentials(self):
        for value in ("{env:OTHER_KEY}", "{file:/tmp/private}", "${OTHER_KEY}"):
            with self.subTest(value=value):
                config = {"provider": {"opencode": {"api": "https://opencode.ai/inference/openai/v1",
                    "models": {"big-pickle": {}}, "options": {"baseURL": "https://opencode.ai/inference/openai/v1", "apiKey": value}}}}
                self.assertIsNone(D.console_gateway(config))
                config["provider"]["opencode"]["options"] = {"baseURL": "https://opencode.ai/inference/openai/v1", "headers": {"Authorization": "Bearer " + value}}
                self.assertIsNone(D.console_gateway(config))

    def test_console_config_respects_disabled_providers_and_model_filters(self):
        config={"provider":{"opencode":{"api":"https://opencode.ai/inference/openai/v1",
            "options":{"apiKey":"fixture-key"},"whitelist":["allowed","blocked","retired"],
            "blacklist":["blocked"],"models":{"allowed":{},"blocked":{},
                "retired":{"status":"deprecated"},"unlisted":{}}}}}
        self.assertEqual(set(D.console_gateway(config)["models"]),{"allowed"})
        config["disabled_providers"]=["opencode"]
        self.assertIsNone(D.console_gateway(config))

    def test_model_metadata_cannot_expose_nested_credentials(self):
        self.manager.import_accounts({"upstream":"cline","api_key":"sk_fixture"})
        self.manager.catalogues["cline"]={"models":{"model":{"native_protocol":"chat","api":{"headers":{"Authorization":"secret"}},"pricing":{"input":1},"metadata":{"apiKey":"nested-secret"}}},"updated_at":time.time()}
        public=json.dumps(self.manager.models(["cline"]))
        self.assertNotIn("secret",public)
        self.assertIn('"input": 1',public)

    def test_command_cli_identity_and_balance_recovery(self):
        account=self.manager.accounts[self.manager.import_accounts({"upstream":"commandcode","apiKey":"user_fixture_key","userName":"CLI User","userId":"cli-id"})[0]["uid"]]
        self.assertEqual(account.view()["nickname"],"CLI User")
        self.assertEqual(account.document["user_id"],"cli-id")
        account.document["credit_exhausted"]=True
        account.cooldowns["*"]=time.time()+600
        paths=[]
        def request(upstream,path,*args,**kwargs):
            paths.append(path)
            if "/whoami" in path: return {"orgId":"team","user":{"id":"cli-id"}}
            if "/credits" in path: return {"credits":{"monthlyCredits":10,"purchasedCredits":2},"windowLimits":{"exceeded":False,"fiveHour":{"used":1,"cap":20,"exceeded":False}}}
            return {"data":{"planId":"individual-go"}}
        self.manager.request_json=request
        self.manager.refresh_balance(account)
        self.assertEqual(account.document["balance"]["remain"],12)
        self.assertFalse(account.document.get("credit_exhausted"))
        self.assertNotIn("*",account.cooldowns)
        self.assertTrue(all("orgId=team" in path for path in paths[1:]))
        self.assertEqual(account.document["plan"],"individual-go")

    def database(self):
        database = wb_database.Database(os.path.join(self.work.name, "db.sqlite3"), self.work.name, os.path.join(self.work.name, "usage"))
        self.addCleanup(database.close_thread)
        self.manager.database = database
        return database

    def test_opencode_org_switch_protects_inflight_and_bound_history(self):
        database = self.database()
        self.start("opencode_zen")
        account = self.manager.accounts[self.finish()["account"]]
        self.orgs.append({"id":"org-two", "name":"Two"})
        meta = self.manager.model("opencode_zen", "configured-model")
        _, ticket = self.manager.reserve("opencode_zen", "configured-model", meta, "session", "owner", 1000, account.uid)
        with self.assertRaises(U.PlatformError) as failure:
            self.manager.refresh_console(account, "org-two")
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(account.document["org_id"], "org-one")
        self.manager.release(ticket)
        store = wb_responses.ResponseStore(database, self.work.name)
        _, context = store.prepare({"input":"hello"}, "owner", ["opencode_zen"], 1024*1024)
        context["bound"] = True
        store.finish({"status":"completed", "output":[]}, context, "opencode_zen", "", "opencode/configured-model", account.uid)
        with self.assertRaises(U.PlatformError) as failure:
            self.manager.refresh_console(account, "org-two")
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(account.document["org_id"], "org-one")
        store.delete_conversation(context["conversation"])
        self.manager.refresh_console(account, "org-two")
        self.assertEqual(account.document["org_id"], "org-two")

    def test_paid_session_keeps_large_window_and_counts_inflight(self):
        self.database()
        self.manager.import_accounts([{"upstream":"commandcode", "api_key":"user_first_fixture"},
                                      {"upstream":"commandcode", "api_key":"user_second_fixture"}])
        meta = {"billing_mode":"paid"}
        first, ticket = self.manager.reserve("commandcode", "model", meta, "session", "owner", 4096)
        # Unknown pricing must preserve the ratio between request and window.
        second, pending = self.manager.reserve("commandcode", "model", meta, "session", "owner", 4096)
        self.assertEqual(first.uid, second.uid)
        self.manager.release(pending)
        self.manager.settle(ticket, {"account":first.uid, "billing_mode":"paid", "total_tokens":1000,
            "credit":1, "has_credit":True, "outcome":"completed"})
        self.manager.release(ticket)
        second, ticket = self.manager.reserve("commandcode", "model", meta, "session", "owner", 4096)
        self.assertEqual(first.uid, second.uid)
        self.manager.release(ticket)
        first.cooldowns["*"] = time.time()+60
        following, ticket = self.manager.reserve("commandcode", "model", meta, "session", "owner", 4096)
        self.assertNotEqual(first.uid, following.uid)
        self.manager.release(ticket)

if __name__ == "__main__": unittest.main()
