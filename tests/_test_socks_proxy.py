"""Real loopback SOCKS5 handshakes and authenticated outbound requests."""
import json
import base64
import http.client
import os
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.TemporaryDirectory(prefix="wb-socks-")
os.environ["ACCOUNTS_DIR"] = _TMP.name
os.environ["WB_PROXY_USAGE_DIR"] = _TMP.name
import wb_accounts as A
import wb_settings as S
import wb_forward_proxy as F
import wb_webnet as N
import wb_webagent as W


def exact(sock, count):
    result = b""
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise EOFError()
        result += part
    return result


class SocksStub(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(2)
        version, count = exact(sock, 2)
        methods = exact(sock, count)
        required = 2 if self.server.auth else 0
        if version != 5 or required not in methods:
            sock.sendall(b"\x05\xff")
            return
        sock.sendall(bytes([5, required]))
        if required == 2:
            version, length = exact(sock, 2)
            username = exact(sock, length)
            password = exact(sock, exact(sock, 1)[0])
            valid = (version, username, password) == (1, b"synthetic-user", b"synthetic-password")
            sock.sendall(bytes([1, 0 if valid else 1]))
            if not valid:
                return
        version, command, reserved, kind = exact(sock, 4)
        if kind == 3:
            target = exact(sock, exact(sock, 1)[0]).decode()
        elif kind == 1:
            target = ".".join(str(x) for x in exact(sock, 4))
        else:
            target = exact(sock, 16).hex()
        port = int.from_bytes(exact(sock, 2), "big")
        self.server.targets.append((target, port))
        sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        request = b""
        while b"\r\n\r\n" not in request:
            request += exact(sock, 1)
        self.server.requests.append(request)
        body = json.dumps({"via": "socks", "target": target}).encode()
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)


class ProxyTests(unittest.TestCase):
    def stub(self, auth=True):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksStub)
        server.daemon_threads = True
        server.auth, server.targets, server.requests = auth, [], []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, "socks5h://127.0.0.1:%d" % server.server_address[1]

    def test_remote_dns_auth_and_http_request_use_the_configured_proxy(self):
        server, url = self.stub()
        proxy = url.replace("://", "://synthetic-user:synthetic-password@")
        result = A.http_json("http://upstream.invalid/credits", proxy=proxy, retries=1, timeout=2)
        self.assertEqual(result, {"via":"socks", "target":"upstream.invalid"})
        self.assertEqual(server.targets, [("upstream.invalid", 80)])
        self.assertNotIn(b"synthetic-password", server.requests[0])

    def test_no_auth_and_bad_password(self):
        server, url = self.stub(auth=False)
        self.assertEqual(A.http_json("http://upstream.invalid/", proxy=url, retries=1, timeout=2)["via"], "socks")
        server, url = self.stub()
        with self.assertRaises(Exception) as error:
            A.http_json("http://upstream.invalid/", proxy=url.replace("://", "://synthetic-user:bad-password@"), retries=1, timeout=2)
        self.assertNotIn("bad-password", str(error.exception))
        self.assertFalse(server.targets)

    def test_separate_slot_credentials_are_preserved_and_applied(self):
        server, url = self.stub()
        slots = S.set_proxy_slots(_TMP.name, [{"url":url, "username":"synthetic-user", "password":"synthetic-password"}])
        self.assertEqual(slots[0]["username"], "synthetic-user")
        self.assertEqual(slots[0]["password"], "synthetic-password")
        pool = A.AccountPool(_TMP.name)
        account = A.Account({"uid":"synthetic", "proxySlot":slots[0]["id"]})
        pool.accounts = [account]
        pool.apply_proxy_slots(slots)
        self.assertEqual(A.http_json("http://upstream.invalid/", proxy=account.proxy, retries=1, timeout=2)["via"], "socks")
        self.assertNotIn("synthetic-password", str(account.public()))

    def test_url_credentials_survive_blank_editor_fields_and_can_be_cleared(self):
        url = "http://test-user:p%3A%40%20%2F%3F@proxy.example:8080"
        slots = S.set_proxy_slots(_TMP.name, [{"url":url, "username":"", "password":""}])
        self.assertEqual(slots[0]["url"], "http://proxy.example:8080")
        self.assertEqual(slots[0]["username"], "test-user")
        self.assertEqual(slots[0]["password"], "p:@ /?")
        self.assertEqual(F.slot_url(slots[0]), url)
        cleared = dict(slots[0], username="", password="")
        slots = S.set_proxy_slots(_TMP.name, [cleared])
        self.assertEqual(F.slot_url(slots[0]), "http://proxy.example:8080")

    def test_http_basic_auth_and_credential_identity(self):
        seen = []
        class Stub(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Proxy-Authorization"))
                body = b'{"via":"http"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:%d" % server.server_address[1]
        slots = S.set_proxy_slots(_TMP.name, [{"url":url, "username":"test-user", "password":"p:@ /?"},
                                            {"url":url, "username":"other-user", "password":"other-password"}])
        self.assertEqual(len(slots), 2, "different credentials on one endpoint are distinct slots")
        result = A.http_json("http://upstream.invalid/", proxy=F.slot_url(slots[0]), retries=1, timeout=2)
        self.assertEqual(result["via"], "http")
        self.assertEqual(seen, ["Basic " + base64.b64encode(b"test-user:p:@ /?").decode()])

    def test_web_fetch_pins_public_ip_even_with_remote_dns_proxy(self):
        server, url = self.stub()
        with mock.patch.dict(os.environ, {"WB_WEB_PROXY":url, "WB_WEB_PROXY_USERNAME":"synthetic-user", "WB_WEB_PROXY_PASSWORD":"synthetic-password"}), \
                mock.patch.object(N, "resolve_public", return_value=["8.8.8.8"]):
            conn, response = N.open_response("http://public.example/path", time.monotonic() + 2, {})
            try:
                self.assertEqual(response.status, 200)
                response.read()
            finally:
                response.close()
                conn.close()
        self.assertEqual(server.targets, [("8.8.8.8", 80)])
        self.assertIn(b"Host: public.example:80", server.requests[0])
        self.assertNotIn(b"synthetic-password", server.requests[0])

    def test_socks_https_preserves_origin_sni_and_tls_verification(self):
        server, url = self.stub()
        proxy = F.parse(url, "synthetic-user", "synthetic-password")
        context = mock.Mock()
        context.wrap_socket.side_effect = lambda sock, **kwargs: sock
        conn = F.socks_connection("upstream.invalid", 443, proxy, secure=True, timeout=2, context=context)
        try:
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
        finally:
            conn.close()
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "upstream.invalid")
        conn = F.socks_connection("upstream.invalid", 443, proxy, secure=True)
        import ssl
        self.assertEqual(conn._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(conn._context.check_hostname)
        conn.close()

    def test_invalid_proxy_is_rejected_without_exposing_credentials(self):
        for url in ("ftp://test-user:secret@host:80", "socks5://test-user:secret@host:0", "http://host:99999", "http://host/path"):
            with self.assertRaises(ValueError) as error:
                F.parse(url)
            self.assertNotIn("secret", str(error.exception))

    def test_socks5_resolves_locally_and_ipv6_connect_uses_binary_address(self):
        server, url = self.stub(auth=False)
        proxy = F.parse(url.replace("socks5h://", "socks5://"))
        lookup = socket.getaddrinfo
        def lookup_target(host, *args):
            if host == "local-dns.invalid":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]
            return lookup(host, *args)
        with mock.patch.object(F.socket, "getaddrinfo", side_effect=lookup_target) as dns:
            conn = F.socks_connection("local-dns.invalid", 80, proxy, timeout=2)
            try:
                conn.request("GET", "/")
                conn.getresponse().read()
            finally:
                conn.close()
        dns.assert_any_call("local-dns.invalid", 80, 0, socket.SOCK_STREAM)
        self.assertEqual(server.targets, [("8.8.8.8", 80)])
        conn = F.socks_connection("2001:4860:4860::8888", 80, proxy, timeout=2)
        try:
            conn.request("GET", "/")
            conn.getresponse().read()
        finally:
            conn.close()
        self.assertEqual(server.targets[-1], ("20014860486000000000000000008888", 80))

    def test_http_connect_auth_stays_on_proxy_and_tls_uses_origin_sni(self):
        seen = []
        class Stub(BaseHTTPRequestHandler):
            def do_CONNECT(self):
                seen.append((self.path, self.headers.get("Proxy-Authorization")))
                self.send_response(200)
                self.end_headers()
                request = self.rfile.readline()
                while True:
                    line = self.rfile.readline()
                    if line in (b"\r\n", b""):
                        break
                    request += line
                seen.append(request)
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://user:password@127.0.0.1:%d" % server.server_address[1]
        channel = W.AcpChannel("https://origin.invalid/acp", "synthetic-token", "test", proxy=url, timeout=2)
        conn = channel._connect()
        context = mock.Mock()
        context.wrap_socket.side_effect = lambda sock, **kwargs: sock
        conn._context = context
        try:
            conn.request("GET", "/acp")
            self.assertEqual(conn.getresponse().read(), b"{}")
        finally:
            conn.close()
        self.assertEqual(seen[0], ("origin.invalid:443", "Basic " + base64.b64encode(b"user:password").decode()))
        self.assertNotIn(b"Proxy-Authorization", seen[1])
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "origin.invalid")

    def test_acp_channel_uses_authenticated_socks_transport(self):
        server, url = self.stub()
        proxy = F.slot_url({"url":url, "username":"synthetic-user", "password":"synthetic-password"})
        channel = W.AcpChannel("http://sandbox.invalid/acp", "synthetic-token", "test", proxy=proxy, timeout=2)
        conn = channel._connect()
        try:
            conn.request("GET", "/acp")
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()
        self.assertEqual(server.targets, [("sandbox.invalid", 80)])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _TMP.cleanup()
