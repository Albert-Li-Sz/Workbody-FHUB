"""No DNS or redirect path may reach non-public destinations."""
import os
import sys
import unittest
from unittest import mock
from email.message import Message
import io
import socket
import time
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.audit_web_tools import fetch_probe
import wb_webtools as W
import wb_webnet as N


class WebSecurityTests(unittest.TestCase):
    def test_controlled_dns_and_redirect_attacks_cannot_read_loopback(self):
        proof = fetch_probe()
        self.assertFalse(proof["dns_to_loopback_read"])
        self.assertFalse(proof["redirect_to_loopback_read"])
        self.assertTrue(proof["literal_loopback_initial_url_refused"])

    def test_literal_non_public_addresses_and_ambiguous_urls_are_rejected(self):
        for url in ("http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://100.64.0.1/",
                    "http://192.0.2.1/", "http://127.1/", "http://0177.0.0.1/",
                    "http://localhost./", "https://example.com:0/", "https://example.com:99999/",
                    "https://example.com/\r\nX: y"):
            with self.subTest(url=url):
                self.assertTrue(W._guard_url(url)[1], url)

    def test_one_private_address_in_a_mixed_dns_answer_refuses_all_connections(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                   for ip in ("8.8.8.8", "127.0.0.1")]
        with mock.patch.object(N.socket, "getaddrinfo", return_value=records), \
                mock.patch.object(N.http.client, "HTTPSConnection") as connect:
            with self.assertRaisesRegex(ValueError, "non-public"):
                N.open_response("https://public.example/", time.monotonic() + 2, {})
            connect.assert_not_called()

    def test_stalled_dns_workers_do_not_accumulate_queued_requests(self):
        started = threading.Barrier(5)
        release = threading.Event()
        pool = ThreadPoolExecutor(max_workers=4)

        def stalled_dns(*args):
            started.wait(timeout=5)
            release.wait(timeout=5)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

        def resolve():
            try:
                N.resolve_public("public.example", 443, time.monotonic() + 0.1)
            except TimeoutError:
                pass

        with mock.patch.object(N, "_dns_pool", pool), \
                mock.patch.object(N, "_dns_slots", threading.BoundedSemaphore(4), create=True), \
                mock.patch.object(N.socket, "getaddrinfo", side_effect=stalled_dns), \
                mock.patch.object(pool, "submit", wraps=pool.submit) as submit:
            threads = [threading.Thread(target=resolve) for _ in range(4)]
            try:
                for thread in threads:
                    thread.start()
                started.wait(timeout=5)
                for thread in threads:
                    thread.join(timeout=1)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                with self.assertRaises(TimeoutError):
                    N.resolve_public("another.example", 443, time.monotonic() + 0.01)
                self.assertEqual(submit.call_count, 4, "a timed-out lookup must not leave queued DNS work")
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=1)
                pool.shutdown(wait=True)

    def test_direct_connection_pins_ip_but_keeps_hostname_and_host_header(self):
        with mock.patch.object(N, "resolve_public", return_value=["8.8.8.8"]), \
                mock.patch.object(N, "proxy_for", return_value=""), \
                mock.patch.object(N.http.client.HTTPConnection, "request") as request, \
                mock.patch.object(N.http.client.HTTPConnection, "getresponse", return_value=mock.Mock()), \
                mock.patch.object(N.socket, "create_connection", return_value=mock.Mock()) as tcp:
            conn, response = N.open_response("http://public.example/", time.monotonic() + 2, {})
            conn._create_connection(("public.example", 80), 1)
            self.assertEqual(tcp.call_args.args[0], ("8.8.8.8", 80))
            self.assertEqual(conn.host, "public.example")
            self.assertEqual(request.call_args.kwargs["headers"]["Host"], "public.example:80")
            conn.close()

    def test_tls_certificate_and_sni_use_the_original_hostname(self):
        context = mock.Mock()
        conn = N._TunnelHTTPS("proxy.example", 8080, origin_host="public.example", context=context)
        with mock.patch.object(N.http.client.HTTPConnection, "connect", side_effect=lambda *args: setattr(conn, "sock", mock.Mock())):
            conn.connect()
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "public.example")

    def test_redirect_to_private_literal_is_refused_before_a_second_connection(self):
        headers = Message()
        headers["Location"] = "http://127.0.0.1/private"
        response = mock.Mock(status=302, headers=headers)
        conn = mock.Mock()
        conn.getresponse.return_value = response
        with mock.patch.object(N, "resolve_public", return_value=["8.8.8.8"]), \
                mock.patch.object(N, "proxy_for", return_value=""), \
                mock.patch.object(N.http.client, "HTTPConnection", return_value=conn) as factory:
            with self.assertRaisesRegex(ValueError, "Non-public"):
                W._http_get("http://public.example/")
        self.assertEqual(factory.call_count, 1)
        response.close.assert_called_once()

    def test_redirect_dns_is_checked_again_before_connection(self):
        headers = Message()
        headers["Location"] = "http://second.example/private"
        conn = mock.Mock()
        conn.getresponse.return_value = mock.Mock(status=302, headers=headers)
        with mock.patch.object(N, "resolve_public", side_effect=[["8.8.8.8"], ValueError("private DNS")]) as dns, \
                mock.patch.object(N, "proxy_for", return_value=""), \
                mock.patch.object(N.http.client, "HTTPConnection", return_value=conn) as factory:
            with self.assertRaisesRegex(ValueError, "private DNS"):
                W._http_get("http://public.example/")
        self.assertEqual([c.args[0] for c in dns.call_args_list], ["public.example", "second.example"])
        self.assertEqual(factory.call_count, 1)

    def test_proxy_destination_is_a_validated_ip_and_auth_stays_on_tunnel(self):
        conn = mock.Mock()
        with mock.patch.dict(os.environ, {"WB_WEB_PROXY": "http://test-user:test-password@127.0.0.1:8888"}), \
                mock.patch.object(N, "resolve_public", return_value=["8.8.8.8"]), \
                mock.patch.object(N, "_TunnelHTTPS", return_value=conn):
            N.open_response("https://public.example/", time.monotonic() + 2, {})
        self.assertEqual(conn.set_tunnel.call_args.args, ("8.8.8.8", 443))
        self.assertIn("Proxy-Authorization", conn.set_tunnel.call_args.kwargs["headers"])
        self.assertNotIn("Proxy-Authorization", conn.request.call_args.kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
