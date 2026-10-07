"""Exercise fixed OpenCode keys through real local HTTP and a fake upstream.

No real account, key, desktop credential or external inference is used.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_opencode as O
import wb_opencode_catalog as C
import wb_proxy as P
import wb_settings as S

UPSTREAM_KEY = "synthetic-upstream-secret"
CLIENT_KEY = "synthetic-client-opencode"
CHAT_USAGE = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
STREAMS = {
    "/v1/chat/completions": b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: {"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}\n\ndata: [DONE]\n\n',
    "/v1/responses": b'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":7,"output_tokens":3,"total_tokens":10,"output_tokens_details":{"reasoning_tokens":2}}}}\n\n',
    "/v1/messages": b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":4,"cache_read_input_tokens":2,"cache_creation_input_tokens":1,"output_tokens":0}}}\n\nevent: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":3}}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n',
}


class Upstream(BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args):
        pass
    def reply(self, status, body, content_type="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self.requests.append((self.path, dict(self.headers), None))
        self.reply(200, b'{"data":[{"id":"oc-only"}]}')
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.path, dict(self.headers), payload))
        if payload["model"] == "rate-limit":
            return self.reply(429, json.dumps({"error":{"message":UPSTREAM_KEY}}).encode(), extra={"Retry-After":"27"})
        if payload["model"] == "redirect":
            return self.reply(302, b'{"error":"redirect"}', extra={"Location":"/stolen"})
        if payload["model"] == "broken-chunk":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"40\r\npartial")  # Upstream disconnects mid-chunk.
            self.close_connection = True
            return
        if payload.get("stream"):
            body = STREAMS[self.path]
            if payload["model"] == "aborted":
                body = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            return self.reply(200, body, "text/event-stream")
        if self.path.endswith("count_tokens"):
            return self.reply(200, b'{"input_tokens":7}')
        usage = CHAT_USAGE if self.path.endswith("chat/completions") else {"input_tokens":7,"output_tokens":3}
        return self.reply(200, json.dumps({"id":"native","usage":usage,"output":"native reply"}).encode())


class Hub(P.Handler):
    def log_message(self, *args):
        pass


class CheckedServer(ThreadingHTTPServer):
    errors = []
    def handle_error(self, request, client_address):
        self.errors.append(sys.exc_info()[1])


class ExitHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="opencode-exit-")
        cls.old = {key:getattr(P,key) for key in ("ACCOUNTS_DIR","USAGE_DIR","USAGE_LOG","API_KEY","POOL")}
        P.ACCOUNTS_DIR = cls.temp.name
        P.USAGE_DIR = cls.temp.name
        P.USAGE_LOG = os.path.join(cls.temp.name,"usage.jsonl")
        P.API_KEY = None
        P.POOL = None
        cls.upstream = ThreadingHTTPServer(("127.0.0.1",0),Upstream)
        cls.server = CheckedServer(("127.0.0.1",0),Hub)
        for server in (cls.upstream,cls.server):
            threading.Thread(target=server.serve_forever,daemon=True).start()
        cls.url = "http://127.0.0.1:%d" % cls.server.server_port
        cls.config = {"enabled":True,"mode":"custom","base_url":"http://127.0.0.1:%d/v1" % cls.upstream.server_port,"api_key":UPSTREAM_KEY,"timeout_seconds":2}
        cls.wb_patch = mock.patch.object(P,"open_upstream",side_effect=AssertionError("OpenCode must not enter WorkBuddy"))
        cls.wb_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.wb_patch.stop()
        for server in (cls.server,cls.upstream):
            server.shutdown()
            server.server_close()
        for key,value in cls.old.items():
            setattr(P,key,value)
        cls.temp.cleanup()

    def setUp(self):
        self.assertEqual(self.server.errors,[], "previous request raised in the HTTP handler")
        Upstream.requests.clear()
        try:
            os.unlink(P.USAGE_LOG)
        except FileNotFoundError:
            pass
        S.save(self.temp.name,{})
        S.set_opencode_config(self.temp.name,self.config)
        S.set_api_keys(self.temp.name,[
            {"id":"oc-key","name":"OpenCode","key":CLIENT_KEY,"realm":"opencode"},
            {"id":"cn-key","name":"Domestic","key":"synthetic-client-cn","realm":"cn"},
            {"id":"intl-key","name":"Global","key":"synthetic-client-intl","realm":"intl"},
        ])

    def request(self,path,payload=None,key=CLIENT_KEY,headers=None):
        extra = {"Authorization":"Bearer "+key,"Content-Type":"application/json"}
        extra.update(headers or {})
        req = urllib.request.Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=extra)
        try:
            response = urllib.request.urlopen(req,timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status,response.read(),dict(response.headers)

    def rows(self,count=1):
        end = time.monotonic()+2
        while time.monotonic()<end:
            try:
                with open(P.USAGE_LOG) as handle:
                    rows = [json.loads(line) for line in handle if line.strip()]
                if len(rows)>=count:
                    return rows
            except (FileNotFoundError,ValueError):
                pass
            time.sleep(.01)
        self.fail("request was not recorded")

    def test_bound_key_models_use_opencode_and_ignore_workbuddy_default(self):
        status,body,_ = self.request("/v1/models")
        self.assertEqual(status,200)
        catalog = json.loads(body)
        self.assertEqual(catalog["channel"],"opencode")
        self.assertEqual([m["id"] for m in catalog["data"]],["oc-only"])
        self.assertTrue(catalog["inference_ready"])
        self.assertEqual(Upstream.requests[0][0],"/v1/models")

    def test_three_native_protocols_preserve_payload_and_separate_credentials(self):
        for index,path in enumerate(STREAMS):
            payload = {"model":"oc-only","stream":False,"messages":[{"role":"user","content":"hello"}],"tools":[{"type":"function","function":{"name":"user-tool"}}]}
            status,body,_ = self.request(path+"?realm=cn",payload,headers={"X-Realm":"cn","X-Channel":"workbuddy-cn","X-Panel-Token":"never-forward","Cookie":"never-forward","anthropic-version":"2023-06-01"})
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)["output"],"native reply")
            used_path,headers,forwarded = Upstream.requests[-1]
            self.assertEqual(used_path,path)
            self.assertEqual(forwarded,payload)
            lower = {k.lower():v for k,v in headers.items()}
            self.assertNotIn("x-panel-token",lower)
            self.assertNotIn("cookie",lower)
            if path.endswith("messages"):
                self.assertEqual(lower["x-api-key"],UPSTREAM_KEY)
                self.assertNotIn("authorization",lower)
            else:
                self.assertEqual(lower["authorization"],"Bearer "+UPSTREAM_KEY)
            row = self.rows(index+1)[-1]
            self.assertEqual((row["realm"],row["key"],row["total_tokens"]),("opencode","oc-key",10))

    def test_native_sse_bytes_and_protocol_usage_are_preserved(self):
        for index,(path,expected) in enumerate(STREAMS.items()):
            status,body,_ = self.request(path,{"model":"oc-only","stream":True})
            self.assertEqual((status,body),(200,expected))
            row = self.rows(index+1)[-1]
            self.assertEqual(row["outcome"],"completed")
            self.assertEqual((row["prompt_tokens"],row["completion_tokens"],row["total_tokens"]),(7,3,10))
            self.assertEqual(row["realm"],"opencode")

    def test_aborted_stream_is_not_reported_as_completed_or_given_a_fake_done(self):
        _,body,_ = self.request("/v1/chat/completions",{"model":"aborted","stream":True})
        self.assertNotIn(b"[DONE]",body)
        self.assertEqual(self.rows()[0]["outcome"],"upstream_aborted")

    def test_broken_http_chunks_return_an_error_or_mark_an_aborted_stream(self):
        status,_,_ = self.request("/v1/responses",{"model":"broken-chunk"})
        self.assertEqual(status,502)
        status,body,_ = self.request("/v1/chat/completions",{"model":"broken-chunk","stream":True})
        self.assertEqual(status,200)  # Already sent headers cannot be replaced.
        self.assertNotIn(b"[DONE]",body)
        self.assertEqual(self.rows(2)[-1]["outcome"],"upstream_aborted")
        self.assertEqual(self.server.errors,[])

    def test_upstream_status_and_retry_after_survive_without_secret_echo(self):
        status,body,headers = self.request("/v1/responses",{"model":"rate-limit"})
        self.assertEqual(status,429)
        self.assertEqual(headers["Retry-After"],"27")
        self.assertNotIn(UPSTREAM_KEY.encode(),body)
        self.assertEqual(self.rows()[0]["realm"],"opencode")
        self.assertEqual(len(Upstream.requests),1)

    def test_redirect_does_not_forward_upstream_credentials(self):
        status,_,_ = self.request("/v1/responses",{"model":"redirect"})
        self.assertEqual(status,302)
        self.assertEqual(len(Upstream.requests),1)
        self.assertEqual(self.rows()[0]["outcome"],"failed")

    def test_missing_configuration_and_missing_proxy_fail_without_wb_fallback(self):
        S.set_opencode_config(self.temp.name,{"enabled":False})
        self.assertEqual(self.request("/v1/chat/completions",{"model":"oc-only"})[0],503)
        S.set_opencode_config(self.temp.name,{"enabled":True,"proxy_slot":"absent"})
        self.assertEqual(self.request("/v1/messages",{"model":"oc-only"})[0],503)
        self.assertEqual(Upstream.requests,[])
        self.rows(2)

    def test_model_restriction_is_enforced_before_upstream(self):
        keys = S.api_keys(self.temp.name)
        keys[0]["models"] = ["allowed*"]
        S.set_api_keys(self.temp.name,keys)
        self.assertEqual(self.request("/v1/responses",{"model":"denied"})[0],400)
        self.assertEqual(Upstream.requests,[])
        self.assertEqual(self.rows()[0]["realm"],"opencode")

    def test_invalid_key_is_rejected_before_body_arrives(self):
        with socket.create_connection(("127.0.0.1",self.server.server_port),timeout=2) as sock:
            sock.sendall(b"POST /v1/responses HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer invalid\r\nContent-Length: 10000\r\n\r\n{")
            self.assertIn(b"401",sock.recv(4096))
        self.assertEqual(Upstream.requests,[])

    def test_rejected_body_releases_shared_concurrency_slot(self):
        slot = threading.BoundedSemaphore(1)
        with mock.patch.object(P,"_chat_slots",slot), mock.patch.object(P,"CHAT_SLOT_WAIT_SECONDS",.01):
            self.assertEqual(self.request("/v1/responses",{})[0],400)
            self.rows()
            self.assertEqual(self.request("/v1/responses",{"model":"oc-only"})[0],200)
            self.rows(2)
            self.assertTrue(slot.acquire(timeout=1))
            slot.release()

    def test_concurrency_rejection_is_attributed_to_the_bound_channel(self):
        slot = threading.BoundedSemaphore(1)
        slot.acquire()
        try:
            with mock.patch.object(P,"_chat_slots",slot), mock.patch.object(P,"CHAT_SLOT_WAIT_SECONDS",.01):
                self.assertEqual(self.request("/v1/responses",{"model":"oc-only"})[0],503)
                self.assertEqual(self.rows()[0]["realm"],"opencode")
                self.assertEqual(Upstream.requests,[])
        finally:
            slot.release()

    def test_panel_save_keeps_key_and_binding_and_validates_before_writing(self):
        panel = {"X-Panel-Token":P.PANEL.create()}
        keys = [{"id":k["id"],"name":k["name"],"realm":k["realm"],"key":""} for k in S.api_keys(self.temp.name)]
        self.assertEqual(self.request("/settings/save",{"api_keys":keys},headers=panel)[0],200)
        self.assertEqual(S.api_keys(self.temp.name)[0]["key"],CLIENT_KEY)
        before = S.load(self.temp.name)
        status,_,_ = self.request("/settings/save",{"api_keys":keys,"opencode":{"mode":"custom","base_url":"https://key:secret@example.com/v1"}},headers=panel)
        self.assertEqual(status,400)
        self.assertEqual(S.load(self.temp.name),before)
        _,body,_ = self.request("/settings",headers=panel)
        self.assertNotIn(UPSTREAM_KEY.encode(),body)
        self.assertEqual(json.loads(body)["api_keys"][0]["realm"],"opencode")
        self.assertEqual(self.server.errors,[])

    def test_native_count_tokens_uses_opencode_and_does_not_count_as_a_chat(self):
        status,body,_ = self.request("/v1/messages/count_tokens",{"model":"oc-only","messages":[]},headers={"Authorization":"","x-api-key":CLIENT_KEY})
        self.assertEqual((status,json.loads(body)),(200,{"input_tokens":7}))
        self.assertEqual(Upstream.requests[-1][0],"/v1/messages/count_tokens")
        self.assertFalse(os.path.exists(P.USAGE_LOG))


class ConfigAndCacheTests(unittest.TestCase):
    def test_preserve_clear_private_storage_and_legacy_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            S.set_opencode_config(directory,{"enabled":True,"api_key":UPSTREAM_KEY})
            S.set_opencode_config(directory,{"api_key":"","mode":"go"})
            self.assertEqual(S.opencode_config(directory)["api_key"],UPSTREAM_KEY)
            self.assertEqual(S.opencode_config(directory)["base_url"],O.BASE_URLS["go"])
            S.set_opencode_config(directory,{"api_key":"","clear_api_key":True})
            self.assertFalse(O.configured(S.opencode_config(directory)))
            if os.name!="nt":
                self.assertEqual(os.stat(S.settings_path(directory)).st_mode&0o777,0o600)
                self.assertEqual(os.stat(directory).st_mode&0o777,0o700)
        for realm in ("","cn","intl","opencode"):
            self.assertEqual(S._clean_key_entry({"key":"synthetic","realm":realm})["realm"],realm)

    def test_zen_and_go_catalogues_use_independent_provider_metadata_and_cache(self):
        C._cache.clear()
        C._failures.clear()
        index = {"opencode":{"models":{"zen-model":{}}},"opencode-go":{"models":{"go-model":{}}}}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(C,"_get_json",side_effect=[{},index,{},index]) as fetch:
            self.assertEqual(C.opencode_catalog(directory)["data"][0]["id"],"zen-model")
            self.assertEqual(C.opencode_catalog(directory,mode="go")["data"][0]["id"],"go-model")
            C.opencode_catalog(directory)
            C.opencode_catalog(directory,mode="go")
            self.assertEqual(fetch.call_count,4)
            self.assertTrue(os.path.isfile(os.path.join(directory,"catalogs","opencode-go.json")))


if __name__=="__main__":
    unittest.main()
