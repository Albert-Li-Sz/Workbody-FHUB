"""Three client protocols against all three native upstream protocols over HTTP.

All credentials and upstream messages are synthetic. The upstream server is
local, so these checks prove routing/streaming/storage, not real entitlement.
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_database
import wb_proxy as P
import wb_platforms as U
import wb_responses as R
import wb_settings as S
import wb_protocol_bridge as B

TOKENS = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
TOOLS = [{"id": "call-original", "type": "function", "function": {"name": "lookup", "arguments": '{"q":"test"}'}}]


class Upstream(P.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length"))))
        self.server.calls.append((self.path, body, self.headers.get("Authorization")))
        tool = "call_tool" in json.dumps(body)
        search = "local_search" in json.dumps(body) and not any(m.get("role") == "tool" for m in body.get("messages") or [])
        aborted = "abort_stream" in json.dumps(body)
        if self.path.endswith("/chat/completions"):
            message = {"role": "assistant", "content": "remembered"}
            if tool:
                message["tool_calls"] = TOOLS
            if search:
                message["tool_calls"] = [{"id":"call-search","type":"function","function":{"name":"web_search","arguments":'{"query":"fhub"}'}}]
            obj = {"id": "chat-upstream", "object": "chat.completion", "model": body["model"],
                   "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}], "usage": TOKENS}
            chunks = [B.frame("", {"id": "chat-upstream", "choices": [{"index": 0, "delta": dict(message, tool_calls=[dict(t,index=i) for i,t in enumerate(message.get("tool_calls") or [])]), "finish_reason": None}]}),
                      B.frame("", {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool else "stop"}], "usage": TOKENS}), B.frame("", "[DONE]")]
        elif self.path.endswith("/responses"):
            output = [{"id": "msg-upstream", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "remembered", "annotations": []}]}]
            if tool:
                output.append({"type": "function_call", "id": "fc-original", "call_id": "call-original", "name": "lookup", "arguments": '{"q":"test"}'})
            obj = {"id": "resp-native", "object": "response", "model": body["model"], "status": "completed", "output": output,
                   "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}
            chunks = [B.frame("response.created", {"type": "response.created", "response": dict(obj, status="in_progress", output=[], usage=None)}),
                      B.frame("response.output_text.delta", {"type": "response.output_text.delta", "delta": "remembered", "item_id": "msg-upstream", "output_index": 0})]
            if tool:
                chunks.extend([B.frame("response.output_item.added", {"type": "response.output_item.added", "item": dict(output[-1], arguments=""), "output_index": 1}),
                    B.frame("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": "fc-original", "delta": '{"q":"test"}', "output_index": 1})])
            chunks.append(B.frame("response.completed", {"type": "response.completed", "response": obj}))
        else:
            output = [{"type": "text", "text": "remembered"}]
            if tool:
                output.append({"type": "tool_use", "id": "call-original", "name": "lookup", "input": {"q": "test"}})
            obj = {"id": "msg-native", "type": "message", "role": "assistant", "model": body["model"], "content": output,
                   "stop_reason": "tool_use" if tool else "end_turn", "usage": {"input_tokens": 10, "output_tokens": 2}}
            chunks = [B.frame("message_start", {"type": "message_start", "message": dict(obj, content=[], usage={"input_tokens": 10, "output_tokens": 0})}),
                      B.frame("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                      B.frame("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "remembered"}}),
                      B.frame("content_block_stop", {"type": "content_block_stop", "index": 0})]
            if tool:
                chunks.extend([B.frame("content_block_start", {"type": "content_block_start", "index": 1, "content_block": dict(output[-1], input={})}),
                    B.frame("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"q":"test"}'}}),
                    B.frame("content_block_stop", {"type": "content_block_stop", "index": 1})])
            chunks.extend([B.frame("message_delta", {"type": "message_delta", "delta": {"stop_reason": obj["stop_reason"]}, "usage": {"output_tokens": 2}}),
                           B.frame("message_stop", {"type": "message_stop"})])
        if body.get("stream"):
            raw = b"".join(chunks[:-1] if aborted else chunks)
            content_type = "text/event-stream"
        else:
            raw, content_type = json.dumps(obj).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Handler(P.Handler):
    def log_message(self, *args):
        pass


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        accounts = os.path.join(self.work.name, "accounts")
        usage = os.path.join(self.work.name, "usage")
        self.db = wb_database.Database(os.path.join(accounts, "db.sqlite3"), accounts, usage)
        self.addCleanup(self.db.close_thread)
        self.upstream = P.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.upstream.calls = []
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        base = "http://127.0.0.1:%s" % self.upstream.server_address[1]
        self.manager = U.Manager(accounts, self.db, bases={name: base for name in U.BASES})
        self.manager.refresh_async = lambda *args, **kwargs: None
        self.manager.import_accounts([{"upstream": "cline", "access_token": "synthetic-cline"}, {"upstream": "opencode_zen", "api_key": "synthetic-zen"}])
        self.models = {"chat": "cline/provider/model", "responses": "opencode/native-responses", "messages": "opencode/native-messages"}
        self.manager.catalogues = {"cline": {"models": {"provider/model": {"native_protocol": "chat", "billing_mode": "free"}}, "updated_at": time.time()},
            "opencode_zen": {"models": {"native-responses": {"native_protocol": "responses", "billing_mode": "free"}, "native-messages": {"native_protocol": "messages", "billing_mode": "free"}}, "updated_at": time.time()}}
        S.save(accounts, {"api_keys": [{"id": "owner", "key": "synthetic-client", "allowed_upstreams": list(S.UPSTREAMS)},
            {"id": "other", "key": "synthetic-other", "allowed_upstreams": list(S.UPSTREAMS)},
            {"id": "cline-only", "key": "synthetic-cline-only", "allowed_upstreams": ["cline"]},
            {"id": "legacy", "key": "synthetic-legacy"}], "local_web_tools": False})
        patcher = mock.patch.multiple(P, ACCOUNTS_DIR=accounts, USAGE_DIR=usage, USAGE_LOG=os.path.join(usage, "usage.jsonl"),
            PLATFORMS=self.manager, RESPONSE_STORE=R.ResponseStore(self.db, accounts), POOL=None, API_KEY="", BLOCK_BACKGROUND_REQUESTS=False,
            PANEL=S.PanelSessions())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = mock.patch.object(wb_database, "DATABASE", self.db)
        patcher2.start()
        self.addCleanup(patcher2.stop)
        self.server = P.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, method=None, key="synthetic-client"):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            client.request(method or ("POST" if body is not None else "GET"), path,
                body=json.dumps(body) if body is not None else None,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            response = client.getresponse()
            raw = response.read()
            return response.status, raw, dict(response.getheaders())
        finally:
            client.close()

    def body(self, protocol, model, stream=False, text="hello"):
        if protocol == "responses":
            return {"model": model, "input": text, "stream": stream}
        return {"model": model, "messages": [{"role": "user", "content": text}], "stream": stream, "max_tokens": 64}

    def test_protocol_matrix_stream_and_nonstream(self):
        for native, model in self.models.items():
            for protocol in ("chat", "messages", "responses"):
                for stream in (False, True):
                    with self.subTest(native=native, protocol=protocol, stream=stream):
                        path = "/v1/chat/completions" if protocol == "chat" else "/v1/" + protocol
                        status, raw, headers = self.request(path, self.body(protocol, model, stream))
                        self.assertEqual(status, 200, raw.decode())
                        self.assertIn(b"remembered", raw)
                        self.assertNotIn(b"response.failed", raw)
                        if stream:
                            self.assertEqual(headers["X-Accel-Buffering"], "no")
                        else:
                            obj = json.loads(raw)
                            if protocol == "responses":
                                self.assertTrue(obj["id"].startswith("resp_"))
                                self.assertNotEqual(obj["id"], "resp-native")
        self.assertFalse(self.manager.reservations)
        self.assertEqual(self.db.usage_count(), 18)
        self.assertEqual(sum(r["total_tokens"] for r in self.db.usage_totals()), 18 * 12)
        self.assertEqual(set(r["upstream"] for r in self.db.usage_totals(group_by=("upstream",))), {"cline", "opencode_zen"})

    def test_response_tools_continuation_and_cross_key_access(self):
        for model in self.models.values():
            status, raw, _ = self.request("/v1/responses", self.body("responses", model, False, "call_tool"))
            self.assertEqual(status, 200, raw.decode())
            result = json.loads(raw)
            self.assertIn("call-original", json.dumps(result))
            body = {"previous_response_id": result["id"], "input": [{"type": "function_call_output", "call_id": "call-original", "output": "found"}]}
            status, next_raw, _ = self.request("/v1/responses", body)
            self.assertEqual(status, 200, next_raw.decode())
            self.assertIn("call-original", json.dumps(self.upstream.calls[-1][1]))
            self.assertIn("found", json.dumps(self.upstream.calls[-1][1]))
            self.assertEqual(self.request("/v1/responses/" + result["id"], key="synthetic-other")[0], 404)
            self.assertEqual(self.request("/v1/responses/" + result["id"], method="DELETE")[0], 200)
            self.assertEqual(self.request("/v1/responses/" + result["id"])[0], 404)

    def test_permissions_models_with_slash_and_private_management(self):
        self.assertEqual(self.request("/v1/chat/completions", self.body("chat", self.models["chat"]), key="synthetic-legacy")[0], 403)
        self.assertEqual(self.upstream.calls, [])
        self.assertEqual(self.request("/v1/models/" + self.models["chat"])[0], 200)
        self.assertEqual(self.request("/platforms")[0], 401)
        status, raw, _ = self.request("/api/billing/usage?upstream=cline")
        self.assertEqual(status, 200)
        self.assertNotIn("account", raw.decode())
        self.assertEqual(self.request("/api/billing/usage?upstream=cline", key="synthetic-legacy")[0], 403)

    def test_interrupted_native_stream_counts_confirmed_usage_and_no_history(self):
        before = P.RESPONSE_STORE.snapshot()["count"]
        status, raw, _ = self.request("/v1/responses", self.body("responses", self.models["responses"], True, "abort_stream"))
        self.assertEqual(status, 200)
        self.assertIn(b"response.failed", raw)
        self.assertEqual(P.RESPONSE_STORE.snapshot()["count"], before)
        self.assertFalse(self.manager.reservations)

    def test_converted_history_retains_platform_for_single_platform_key(self):
        for stream in (False, True):
            status, raw, _ = self.request("/v1/responses", self.body("responses", self.models["chat"], stream), key="synthetic-cline-only")
            self.assertEqual(status, 200, raw.decode())
            if stream:
                result = next(data["response"] for event, data in B.sse_events(raw.splitlines(True)) if event == "response.completed")
            else:
                result = json.loads(raw)
            saved = P.RESPONSE_STORE.get(result["id"], "cline-only", ["cline"])
            self.assertEqual(saved["upstream"], "cline")
            status, raw, _ = self.request("/v1/responses", {"previous_response_id": result["id"], "input": "follow up"}, key="synthetic-cline-only")
            self.assertEqual(status, 200, raw.decode())

    def test_storage_write_failure_is_visible_and_counts_once(self):
        self.db.connection().execute("CREATE TRIGGER reject_history BEFORE INSERT ON responses BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        for model in (self.models["chat"], self.models["responses"]):
            before = self.db.usage_count()
            status, raw, _ = self.request("/v1/responses", self.body("responses", model))
            self.assertEqual(status, 503, raw.decode())
            self.assertIn(b"history could not be stored", raw)
            self.assertEqual(self.db.usage_count(), before + 1)
        self.assertEqual(P.RESPONSE_STORE.snapshot()["count"], 0)
        self.assertFalse(self.manager.reservations)

    def test_converted_aborted_messages_keep_confirmed_usage(self):
        status, raw, _ = self.request("/v1/responses", self.body("responses", self.models["messages"], True, "abort_stream"))
        self.assertEqual(status, 200)
        self.assertIn(b'response.failed',raw)
        row=next(self.db.usage_rows(limit=1))
        self.assertEqual(row['total_tokens'],12)
        self.assertNotEqual(row['outcome'],'completed')
        self.assertEqual(P.RESPONSE_STORE.snapshot()['count'],0)

    def test_local_search_results_survive_response_continuation(self):
        with mock.patch.object(P,'local_web_tools_enabled',return_value=True), mock.patch.object(P.wb_webtools,'execute',return_value='Synthetic web result https://example.com/reference'):
            for stream in (False,True):
                body=dict(self.body('responses',self.models['chat'],stream,'local_search'),tools=[{'type':'web_search'}])
                status,raw,_=self.request('/v1/responses',body,key='synthetic-cline-only')
                self.assertEqual(status,200,raw.decode())
                if stream:
                    result=next(d['response'] for event,d in B.sse_events(raw.splitlines(True)) if event=='response.completed')
                else:result=json.loads(raw)
                saved=P.RESPONSE_STORE.get(result['id'],'cline-only',['cline'],True)
                self.assertIn('Synthetic web result',json.dumps(saved['history']))
                self.assertIn('call-search',json.dumps(saved['history']))
                status,raw,_=self.request('/v1/responses',{'previous_response_id':result['id'],'input':'continue'},key='synthetic-cline-only')
                self.assertEqual(status,200,raw.decode())
                self.assertIn('Synthetic web result',json.dumps(self.upstream.calls[-1][1]))


if __name__ == "__main__":
    unittest.main()
