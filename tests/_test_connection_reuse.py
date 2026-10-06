"""Real-socket regressions for request deadlines and safe connection reuse.

All stores and credentials are synthetic. The server never calls an upstream.
A rejected upload must get its error without sending its body; a complete
request can still reuse its connection, including after an application error.
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WORK = tempfile.TemporaryDirectory(prefix="wb-http-")
os.environ["WB_PROXY_USAGE_DIR"] = os.path.join(WORK.name, "usage")
os.environ["WB_HTTP_READ_TIMEOUT"] = "1"
os.environ["WB_CHAT_SLOT_WAIT"] = "0.05"
os.environ["WB_MAX_CONCURRENT_CHAT"] = "1"
os.environ["WB_MAX_PAYLOAD_BYTES"] = "256"

import wb_proxy as P
import wb_accounts
import wb_settings

P.ACCOUNTS_DIR = os.path.join(WORK.name, "accounts")
P.POOL = wb_accounts.AccountPool(P.ACCOUNTS_DIR)
wb_settings.save(P.ACCOUNTS_DIR, {"api_keys": [
    {"id": "k1", "name": "synthetic", "key": "GOODKEY", "enabled": True}
]})
UPLOAD_STARTED = threading.Event()


class TestHandler(P.Handler):
    def log_message(self, *args):
        pass

    def _read_payload(self, *args, **kwargs):
        UPLOAD_STARTED.set()
        return super()._read_payload(*args, **kwargs)

    def _dispatch_chat_post(self, path, payload):
        if payload.get("model") == "review-no-accounts":
            return super()._dispatch_chat_post(path, payload)
        if payload.get("wait"):
            time.sleep(P.HTTP_READ_TIMEOUT_SECONDS + 0.1)
        return self._json(200, {"ok": True})


class TestServer(P.ThreadingHTTPServer):
    def handle_error(self, request, address):
        self.errors.append(sys.exc_info()[1])


class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = TestServer(("127.0.0.1", 0), TestHandler)
        cls.server.errors = []
        cls.port = cls.server.server_address[1]
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

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.addCleanup(sock.close)
        return sock

    def headers(self, key="GOODKEY", length=2, extra=b"", path="/v1/chat/completions"):
        body_header = (b"Transfer-Encoding: chunked\r\n" if length is None
                       else b"Content-Length: %d\r\n" % length)
        return (b"POST " + path.encode() + b" HTTP/1.1\r\nHost: localhost\r\n"
                b"Authorization: Bearer " + key.encode() + b"\r\n"
                + body_header + extra + b"\r\n")

    def response(self, sock):
        response = http.client.HTTPResponse(sock)
        response.begin()
        payload = response.read()
        return response, json.loads(payload)

    def assert_immediate_rejection(self, request, status):
        sock = self.connect()
        started = time.monotonic()
        sock.sendall(request)
        response, payload = self.response(sock)
        self.assertEqual(response.status, status)
        self.assertEqual(response.getheader("Connection"), "close")
        self.assertEqual(payload["error"]["code"], status)
        self.assertLess(time.monotonic() - started, 0.8)

    def test_invalid_key_without_content_length_body(self):
        self.assert_immediate_rejection(self.headers(key="BADKEY"), 401)

    def test_invalid_key_without_chunked_body(self):
        self.assert_immediate_rejection(self.headers(key="BADKEY", length=None), 401)

    def test_invalid_key_expect_continue_does_not_wait_for_body(self):
        self.assert_immediate_rejection(
            self.headers(key="BADKEY", extra=b"Expect: 100-continue\r\n"), 401)

    def test_panel_rejection_does_not_wait_for_body(self):
        self.assert_immediate_rejection(self.headers(path="/accounts/import"), 401)

    def test_large_rejected_body_closes_and_client_reconnects(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("POST", "/v1/chat/completions", b"A" * 70000,
                     {"Authorization": "Bearer BADKEY"})
        response = conn.getresponse()
        self.assertEqual(response.status, 401)
        self.assertEqual(response.getheader("Connection"), "close")
        self.assertIn("error", json.loads(response.read()))
        conn.request("POST", "/v1/chat/completions", "{}",
                     {"Authorization": "Bearer GOODKEY"})
        self.assertEqual(conn.getresponse().status, 200)

    def test_consumed_invalid_json_keeps_connection_in_sync(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("POST", "/v1/chat/completions", "{",
                     {"Authorization": "Bearer GOODKEY"})
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        original = conn.sock
        self.assertIsNotNone(original)
        conn.request("POST", "/v1/chat/completions", "{}",
                     {"Authorization": "Bearer GOODKEY"})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        self.assertIs(conn.sock, original)

    def test_oversized_fixed_length_does_not_wait_for_body(self):
        self.assert_immediate_rejection(self.headers(length=1000), 413)

    def test_oversized_chunk_does_not_wait_for_chunk_data(self):
        self.assert_immediate_rejection(self.headers(length=None) + b"1000\r\n", 413)

    def test_complete_chunked_body_still_works(self):
        sock = self.connect()
        sock.sendall(self.headers(length=None) + b"2\r\n{}\r\n0\r\n\r\n")
        response, _ = self.response(sock)
        self.assertEqual(response.status, 200)

    def test_stalled_body_times_out_and_releases_slot(self):
        sock = self.connect()
        started = time.monotonic()
        sock.sendall(self.headers())
        response, _ = self.response(sock)
        self.assertEqual(response.status, 408)
        self.assertEqual(response.getheader("Connection"), "close")
        self.assertLess(time.monotonic() - started, 2)
        next_sock = self.connect()
        next_sock.sendall(self.headers() + b"{}")
        self.assertEqual(self.response(next_sock)[0].status, 200)

    def drip(self, sock, initial):
        sock.sendall(initial)
        stop = threading.Event()

        def send():
            while not stop.wait(0.05):
                try:
                    sock.sendall(b"x")
                except OSError:
                    break

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        self.addCleanup(stop.set)
        return stop

    def test_dripping_body_cannot_extend_receive_deadline(self):
        sock = self.connect()
        started = time.monotonic()
        stop = self.drip(sock, self.headers(length=100) + b'{"')
        response, _ = self.response(sock)
        stop.set()
        self.assertEqual(response.status, 408)
        self.assertLess(time.monotonic() - started, 2)

    def test_dripping_headers_and_request_line_are_bounded(self):
        for initial in (b"GET /", b"GET /health HTTP/1.1\r\nHost: x\r\nX-Slow: "):
            with self.subTest(initial=initial):
                sock = self.connect()
                started = time.monotonic()
                stop = self.drip(sock, initial)
                try:
                    self.assertEqual(sock.recv(1024), b"")
                except ConnectionResetError:
                    pass
                stop.set()
                self.assertLess(time.monotonic() - started, 2)

    def test_upload_occupies_chat_slot_before_body_is_sent(self):
        UPLOAD_STARTED.clear()
        first = self.connect()
        first.sendall(self.headers())
        self.assertTrue(UPLOAD_STARTED.wait(1))
        self.assert_immediate_rejection(self.headers(), 503)
        first.sendall(b"{}")
        self.assertEqual(self.response(first)[0].status, 200)
        third = self.connect()
        third.sendall(self.headers() + b"{}")
        self.assertEqual(self.response(third)[0].status, 200)

    def test_receive_deadline_does_not_cut_off_upstream_wait(self):
        sock = self.connect()
        body = b'{"wait":true}'
        sock.sendall(self.headers(length=len(body)) + body)
        self.assertEqual(self.response(sock)[0].status, 200)

    def test_no_accounts_still_returns_clean_json_503(self):
        sock = self.connect()
        body = b'{"model":"review-no-accounts","messages":[{"role":"user","content":"hi"}]}'
        sock.sendall(self.headers(length=len(body)) + body)
        response, payload = self.response(sock)
        self.assertEqual(response.status, 503)
        self.assertIn("no usable account", payload["error"]["message"])

    def test_overlong_request_line_returns_json_414(self):
        sock = self.connect()
        sock.sendall(b"GET /" + b"a" * (2 * 1024 * 1024)
                     + b" HTTP/1.1\r\nHost: x\r\n\r\n")
        response, payload = self.response(sock)
        self.assertEqual(response.status, 414)
        self.assertIn("application/json", response.getheader("Content-Type"))
        self.assertEqual(payload["error"]["code"], 414)


if __name__ == "__main__":
    unittest.main()
