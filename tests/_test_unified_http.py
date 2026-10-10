"""Local HTTP contracts for the fourth provider and unified management paths."""
import http.client
import io
import json
import os
import time
import unittest
from unittest import mock
import _test_platform_http as fixture
import _test_account_transfer as transfer
import wb_accounts as A
import wb_platforms as U
import wb_settings as S
import wb_proxy as P

class Upstream(fixture.Upstream):
    def do_POST(self):
        self.server.client_headers = getattr(self.server, "client_headers", []) + [dict(self.headers)]
        if not self.path.endswith("/alpha/generate"):
            return super().do_POST()
        body=json.loads(self.rfile.read(int(self.headers.get("Content-Length"))))
        self.server.calls.append((self.path,body,self.headers.get("Authorization")))
        if self.headers.get("Authorization")==getattr(self.server,"fail_key",None):
            raw=json.dumps(getattr(self.server,"fail_body",{"error":"INSUFFICIENT_CREDITS"})).encode()
            self.send_response(getattr(self.server,"fail_status",402));self.send_header("Retry-After","1");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw);return
        params=body["params"]
        events=[{"type":"start"},{"type":"reasoning-delta","text":"reasoning"},{"type":"text-delta","text":"remembered"},
          {"type":"finish-step","finishReason":"stop","usage":{"inputTokens":10,"outputTokens":2}}]
        if "abort_stream" not in json.dumps(params):
            events.append({"type":"finish","finishReason":"stop","totalUsage":{"inputTokens":10,"outputTokens":2,"cachedInputTokens":3,"creditsUsed":0.25}})
        raw=b"".join(json.dumps(event).encode()+b"\n" for event in events)
        self.send_response(200);self.send_header("Content-Type","application/x-ndjson");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

class HTTPTests(unittest.TestCase):
    request=fixture.IntegrationTests.request
    body=fixture.IntegrationTests.body
    def setUp(self):
        fixture.IntegrationTests.setUp(self)
        self.upstream.RequestHandlerClass=Upstream
        views=self.manager.import_accounts([{"upstream":"commandcode","api_key":"user_first_fixture","priority":0},
          {"upstream":"commandcode","api_key":"user_second_fixture","priority":100}])
        self.command_uids=[row["uid"] for row in views]
        self.manager.catalogues["commandcode"]={"models":{"fixture":{"id":"fixture","native_protocol":"chat","billing_mode":"paid"}},"updated_at":time.time()}
        self.pool=A.AccountPool(self.manager.directory)
        self.addCleanup(self.pool.stop_background)
        patch=mock.patch.object(P,"POOL",self.pool);patch.start();self.addCleanup(patch.stop)
        self.panel=P.PANEL.create()

    def management(self,path,body=None):
        client=http.client.HTTPConnection("127.0.0.1",self.server.server_address[1],timeout=10)
        try:
            client.request("POST" if body is not None else "GET",path,json.dumps(body) if body is not None else None,
                           {"Content-Type":"application/json","X-Panel-Token":self.panel})
            response=client.getresponse();return response.status,json.loads(response.read())
        finally:client.close()

    def assert_reservations_released(self):
        # The client can receive the final bytes before the handler's finally
        # block releases its lease. Check eventual cleanup with a bounded wait.
        deadline = time.monotonic() + 2
        while True:
            with self.manager.lock:
                pending = dict(self.manager.reservations)
            if not pending or time.monotonic() >= deadline:
                self.assertFalse(pending)
                return
            time.sleep(0.005)

    def test_command_protocol_matrix(self):
        for protocol in ("chat","responses","messages"):
            for stream in (False,True):
                with self.subTest(protocol=protocol,stream=stream):
                    path="/v1/chat/completions" if protocol=="chat" else "/v1/"+protocol
                    status,raw,headers=self.request(path,self.body(protocol,"commandcode/fixture",stream))
                    self.assertEqual(status,200,raw.decode())
                    self.assertIn(b"remembered",raw)
                    self.assertNotIn(b"response.failed",raw)
                    if stream:self.assertEqual(headers["X-Accel-Buffering"],"no")
        rows=list(self.db.usage_rows(upstream="commandcode"))
        self.assertEqual(len(rows),6)
        self.assertTrue(all(row["total_tokens"]==12 and row["credit"]==0.25 and row["cost_unit"]=="credits" for row in rows))
        self.assert_reservations_released()

    def test_command_402_fails_over_within_provider(self):
        self.upstream.fail_key="Bearer user_first_fixture"
        status,raw,_=self.request("/v1/chat/completions",self.body("chat","commandcode/fixture"))
        self.assertEqual(status,200,raw.decode())
        self.assertEqual([call[2] for call in self.upstream.calls],["Bearer user_first_fixture","Bearer user_second_fixture"])
        self.assertTrue(all(call[0].endswith("/alpha/generate") for call in self.upstream.calls))
        self.assertGreater(self.manager.accounts[self.command_uids[0]].cooldowns["*"],time.time())
        first = self.manager.accounts[self.command_uids[0]]
        first.cooldowns.clear()
        following, ticket = self.manager.reserve("commandcode", "fixture", {"billing_mode":"paid"}, "", "owner", 4096)
        self.assertNotEqual(first.uid, following.uid, "a timed-out cooldown alone cannot clear credit exhaustion")
        self.manager.release(ticket)
        self.assert_reservations_released()

    def test_command_quota_failure_uses_reset_and_stays_in_provider(self):
        self.upstream.fail_key="Bearer user_first_fixture"
        self.upstream.fail_status=429
        first = self.manager.accounts[self.command_uids[0]]
        for window, scale in (("fiveHour",1),("weekly",1000)):
            reset = time.time()+120
            self.upstream.fail_body={"error":{"code":"USAGE_EXCEEDED","rateLimit":{"window":window,"reset":int(reset*scale)}}}
            first.cooldowns.clear()
            status,raw,_=self.request("/v1/chat/completions",self.body("chat","commandcode/fixture"))
            self.assertEqual(status,200,raw.decode())
            self.assertGreaterEqual(first.cooldowns["*"], reset-1)
            self.assertLess(first.cooldowns["*"], reset+2)
            self.assertTrue(all(call[0].endswith("/alpha/generate") for call in self.upstream.calls))
            self.assert_reservations_released()

    def test_opencode_http_headers_preserve_session_and_selected_credential(self):
        body = self.body("responses", self.models["responses"])
        body["metadata"] = {"project_id":"fixture-project"}
        status, raw, _ = self.request("/v1/responses", body)
        self.assertEqual(status, 200, raw.decode())
        previous = json.loads(raw)["id"]
        status, raw, _ = self.request("/v1/responses", {"previous_response_id":previous,"input":"next", "metadata":body["metadata"]})
        self.assertEqual(status, 200, raw.decode())
        first, second = [{key.lower():value for key,value in headers.items()} for headers in self.upstream.client_headers]
        self.assertEqual(first["authorization"], "Bearer synthetic-zen")
        self.assertEqual(second["authorization"], first["authorization"])
        self.assertEqual(first["x-opencode-client"], "cli")
        self.assertTrue(first["user-agent"].startswith("opencode/"))
        self.assertEqual(first["x-opencode-session"], second["x-opencode-session"])
        self.assertEqual(first["x-opencode-project"], second["x-opencode-project"])
        self.assertNotEqual(first["x-opencode-request"], second["x-opencode-request"])

    def test_upstream_auth_failure_keeps_the_panel_session_and_error_detail(self):
        account = next(a for a in self.manager.accounts.values() if a.upstream == "opencode_zen")
        for upstream_status in (401, 403):
            with self.subTest(upstream_status=upstream_status):
                failure = U.PlatformError("opencode_zen rejected the request (HTTP %d)" % upstream_status,
                                          upstream_status, "upstream_error")
                with mock.patch.object(self.manager, "open", side_effect=failure):
                    status, value = self.management("/accounts/upstreams/accounts/test", {
                        "uid": account.uid, "model": "opencode/native-responses"})
                self.assertEqual(status, 502, value)
                self.assertEqual(value["error"]["code"], "upstream_error")
                self.assertIn("HTTP %d" % upstream_status, value["error"]["message"])
                self.assertEqual(self.management("/accounts/upstreams?models=0")[0], 200)
        self.assertEqual(self.request("/accounts/upstreams/accounts/test", {
            "uid": account.uid, "model": "opencode/native-responses"})[0], 401)

    def test_command_interruption_records_partial_usage(self):
        status,raw,_=self.request("/v1/responses",self.body("responses","commandcode/fixture",True,"abort_stream"))
        self.assertEqual(status,200)
        self.assertIn(b"response.failed",raw)
        self.assertEqual(P.RESPONSE_STORE.snapshot()["count"],0)
        row=list(self.db.usage_rows(upstream="commandcode"))[0]
        self.assertEqual(row["total_tokens"],12)
        self.assertNotEqual(row["outcome"],"completed")
        self.assert_reservations_released()

    def test_command_history_and_stable_session(self):
        status,raw,_=self.request("/v1/responses",self.body("responses","commandcode/fixture"))
        self.assertEqual(status,200)
        response=json.loads(raw)
        first=self.upstream.calls[-1][1]
        status,raw,_=self.request("/v1/responses",{"previous_response_id":response["id"],"input":"NEXT"})
        self.assertEqual(status,200,raw.decode())
        following=self.upstream.calls[-1][1]
        self.assertIn("remembered",json.dumps(following["params"]["messages"]))
        self.assertIn("hello",json.dumps(following["params"]["messages"]))
        self.assertIn("NEXT",json.dumps(following["params"]["messages"]))
        self.assertEqual(first["threadId"],following["threadId"])

    def test_management_aliases_permissions_and_batch(self):
        self.assertEqual(self.request("/accounts/upstreams")[0],401)
        status,value=self.management("/accounts/upstreams?models=0")
        self.assertEqual(status,200)
        self.assertEqual(len(value["accounts"]),4)
        self.assertNotIn("user_first_fixture",json.dumps(value))
        status,value=self.management("/accounts/upstreams/accounts/batch",{"uids":self.command_uids,"enabled":False})
        self.assertEqual(status,200);self.assertTrue(all(not row["enabled"] for row in value["accounts"]))
        self.assertEqual(self.management("/accounts/upstreams/accounts/batch",{"uids":["missing"],"enabled":False})[0],400)
        self.assertEqual(self.management("/settings/responses")[0],200)

    def test_billing_queries_require_panel_auth_and_return_no_credentials(self):
        uid=self.command_uids[0]
        account=self.manager.accounts[uid]
        account.document.update(balance={'remain':12,'unit':'credits'},quota={'monthly':{'percent_used':25,'remaining_percent':75}})
        self.assertEqual(self.request('/accounts/upstreams/billing?uid='+uid)[0],401)
        status,value=self.management('/accounts/upstreams/billing?uid='+uid)
        self.assertEqual(status,200)
        self.assertEqual(value['accounts'][0]['balance']['remain'],12)
        self.assertEqual(value['accounts'][0]['quota']['monthly']['remaining_percent'],75)
        self.assertNotIn('user_first_fixture',json.dumps(value))
        status,raw,_=self.request('/v1/balance?upstream=commandcode')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['quota_windows']['monthly']['remaining_percent_min'],75)
        self.assertEqual(self.management('/accounts/upstreams/billing?uid=missing')[0],404)
        self.assertEqual(self.management('/accounts/upstreams/billing?uid='+uid+'&refresh=invalid')[0],400)

    def test_model_price_details_and_subscription_filter(self):
        self.manager.catalogues['cline']['models']['cline-pass/fixture']={'native_protocol':'chat','billing_mode':'paid',
            'entitlement':'subscription','reference_pricing':{'input':0.3,'output':1.2,'unit':'USD/1M tokens'}}
        status,value=self.management('/accounts/upstreams/models?upstream=cline&group=subscription')
        self.assertEqual(status,200)
        self.assertEqual([model['id'] for model in value['models']],['cline-pass/fixture'])
        status,raw,_=self.request('/v1/models/cline/cline-pass/fixture')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['reference_pricing']['output'],1.2)
        self.assertEqual(self.management('/accounts/upstreams/models?upstream=invalid')[0],400)
        self.assertEqual(self.management('/accounts/upstreams/models?group=invalid')[0],400)

    def test_model_library_scopes_capabilities_and_sync_state(self):
        for upstream, prefix in U.PREFIXES.items():
            with self.subTest(upstream=upstream):
                self.manager.catalogues[upstream] = {"models": {"fixture": {
                    "native_protocol": "chat", "billing_mode": "paid", "reasoning": True,
                    "reasoning_efforts": ["low", "high"], "tool_call": True,
                    "reasoning_options": [{"type": "toggle"}, {"type": "effort", "values": ["low", "high", "max"]}],
                    "modalities": {"input": ["text", "image"]},
                    "limit": {"context": 1000000, "output": 64000},
                    "options": {"apiKey": "private-fixture-secret"}}},
                    "updated_at": time.time() - 700, "metadata_stale": True}
                self.manager.refreshing.add(upstream)
                status, value = self.management('/accounts/upstreams/models?upstream=' + upstream)
                self.assertEqual(status, 200)
                self.assertEqual([m['id'] for m in value['models']], ['fixture' if upstream == 'cline' else prefix + 'fixture'])
                self.assertEqual(set(value['catalogues']), {upstream})
                state = value['catalogues'][upstream]
                self.assertTrue(state['stale'])
                self.assertTrue(state['metadata_stale'])
                self.assertTrue(state['refreshing'])
                model = value['models'][0]
                self.assertEqual(model['context_length'], 1000000)
                self.assertEqual(model['max_output_tokens'], 64000)
                self.assertEqual(model['reasoning_efforts'], ['low', 'high'])
                self.assertEqual(model['reasoning_options'][1]['values'], ['low', 'high', 'max'])
                self.assertEqual(model['modalities']['input'], ['text', 'image'])
                self.assertTrue(model['tool_call'])
                self.assertNotIn('private-fixture-secret', json.dumps(value))
                self.manager.refreshing.discard(upstream)

    def test_model_library_does_not_expose_disabled_account_models(self):
        for account in self.manager.accounts.values():
            if account.upstream == 'cline':
                account.document['enabled'] = False
        status, value = self.management('/accounts/upstreams/models?upstream=cline')
        self.assertEqual(status, 200)
        self.assertEqual(value['models'], [])
        self.assertIn('cline', value['catalogues'])
        # A gateway key cannot grant panel-management access.
        status, _, _ = self.request('/accounts/upstreams/models?upstream=cline')
        self.assertEqual(status, 401)

    def test_source_import_export_leaves_workbuddy_transfer_unchanged(self):
        row={"upstream":"commandcode","api_key":"user_import_fixture","priority":3}
        status,value=self.management("/accounts/upstreams/accounts/import",[row])
        self.assertEqual(status,200,value)
        self.assertEqual(value["accounts"][0]["priority"],3)
        wb={"uid":"workbuddy-import","accessToken":transfer.jwt("workbuddy-import"),"priority":8}
        status,value=self.management("/accounts/import",{"data":[wb],"dryRun":True})
        self.assertEqual(status,200,value)
        self.assertEqual(len(value["result"]["added"]),1)
        self.assertEqual(len(self.pool.accounts),0)
        status,value=self.management("/accounts/import",{"data":[wb]})
        self.assertEqual(status,200,value)
        self.assertEqual(len(self.pool.accounts),1)
        status,document=self.management("/accounts/export")
        self.assertEqual(status,200)
        self.assertEqual(document["count"],1)
        status,document=self.management("/accounts/upstreams/accounts/export?upstream=commandcode")
        self.assertEqual(status,200)
        self.assertEqual(document["count"],3)
        self.assertTrue(all(row["upstream"]=="commandcode" for row in document["accounts"]))
        status,value=self.management("/accounts/upstreams/accounts/import",document)
        self.assertEqual(status,200,value)
        self.assertEqual(len(self.manager.accounts),5)

if __name__=="__main__":unittest.main()
