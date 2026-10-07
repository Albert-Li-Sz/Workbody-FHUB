"""DuckDuckGo HTML/Lite parsing, request bounds and cache under fake transport."""
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import io
import os
import sys
import threading
import unittest
import urllib.error
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_webtools as W


HTML = """<html><body>
<div class='result result--ad'><div class='result__body'>
  <a href='https://ads.example.com/' class='result__a'>Sponsored</a></div></div>
<div class='result__body'>
  <a href='//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa%252Fb%3Ftag%3Dc%252Bd&amp;rut=x'
     data-extra='>' class='extra result__a'>Python <b>&amp; 中文</b></a>
  <div class='result__snippet'>Read <b>real</b> docs &amp; examples.<script>bad()</script></div>
</div>
<div class='result__body'>
  <a class='result__a' href='https://example.org/'><span>Second</span> result</a>
  <a href='https://example.org/' class='result__snippet'>Another snippet</a>
</div>
<div class='result__body'><a class='result__a' href='https://example.org/'>Duplicate</a></div>
<div class='result__body'><a class='result__a' href='javascript:alert(1)'>Unsafe</a></div>
</body></html>"""
LITE = """<table><tr><td>
<a href='/l/?uddg=https%3A%2F%2Fexample.net%2Flite' class='result-link'>Lite <b>result</b></a>
</td></tr><tr><td class='result-snippet'>Useful &amp; lightweight<br>text.</td></tr>
<tr><td><a class='result-link' href='https://example.net/next'>Next</a></td></tr>
<tr><td class='result-snippet'>Next snippet.</td></tr></table>"""
CHALLENGE = "<form id='challenge-form'><div class='anomaly-modal__title'>Challenge</div></form>"
EMPTY = "<div class='no-results'><h1>No results found</h1></div>"


class Response(io.BytesIO):
    def __init__(self, data, content_type="text/html; charset=utf-8", encoding=""):
        super().__init__(data)
        self.status = 200
        self.reason = "OK"
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if encoding:
            self.headers["Content-Encoding"] = encoding


class SearchTests(unittest.TestCase):
    def setUp(self):
        W._search_cache.clear()
        W._search_pending.clear()
        self.env = mock.patch.dict(os.environ, {"WB_WEB_PROXY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def parse(self, page):
        parser = W._SearchParser()
        parser.feed(page)
        parser.close()
        return parser

    def test_html_attributes_entities_snippets_ads_and_duplicates(self):
        rows = self.parse(HTML).results
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {
            "title": "Python & 中文", "url": "https://example.com/a%2Fb?tag=c%2Bd",
            "snippet": "Read real docs & examples."})
        self.assertEqual(rows[1]["snippet"], "Another snippet")

    def test_lite_table_and_relative_redirects(self):
        rows = self.parse(LITE).results
        self.assertEqual(rows[0], {"title": "Lite result", "url": "https://example.net/lite",
                                  "snippet": "Useful & lightweight text."})
        self.assertEqual(rows[1]["snippet"], "Next snippet.")

    def test_redirects_decode_once_and_match_the_actual_ddg_host(self):
        target = "https://example.com/a%2Fb?q=a%2Bb%26c#part"
        wrapped = "/l/?" + urllib.parse.urlencode({"uddg": target})
        self.assertEqual(W._ddg_target(wrapped), target)
        impostor = "https://duckduckgo.com.example.org/l/?uddg=https%3A%2F%2Felsewhere.org"
        self.assertEqual(W._ddg_target(impostor), impostor)

    def test_invalid_internal_private_and_credential_urls_are_not_sources(self):
        for href in ("", "javascript:alert(1)", "file:///etc/passwd", "/settings",
                     "https://duckduckgo.com/y.js?ad=1", "https://u:p@example.com/",
                     "http://127.0.0.1/", "http://10.0.0.1/"):
            with self.subTest(href=href):
                self.assertEqual(W._ddg_target(href), "")

    def test_result_count_and_text_sizes_are_bounded(self):
        page = "".join("<a class='result__a' href='https://example.com/%d'>%s</a>"
                       "<p class='result__snippet'>%s</p>" % (i, "t" * 500, "s" * 2000)
                       for i in range(20))
        rows = self.parse(page).results
        self.assertEqual(len(rows), W.MAX_RESULTS)
        self.assertEqual(len(rows[0]["title"]), 300)
        self.assertEqual(len(rows[0]["snippet"]), 1200)

    def test_unknown_layout_falls_back_once_to_lite(self):
        with mock.patch.object(W, "_http_get", side_effect=["<h1>Unexpected</h1>", LITE]) as get:
            text = W.search("test query")
        self.assertIn("Lite result", text)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(get.call_args[0][0].startswith(W.LITE_SEARCH_ENDPOINT))

    def test_challenge_on_both_layouts_is_an_error_without_fabricated_sources(self):
        with mock.patch.object(W, "_http_get", return_value=CHALLENGE) as get:
            text = W.search("challenge")
        self.assertIn("CAPTCHA", text)
        self.assertTrue(text.startswith("Error:"))
        self.assertNotIn("No results found", text)
        self.assertEqual(W.sources_from_result(text), [])
        self.assertEqual(get.call_count, 2)

    def test_an_accessible_lite_layout_can_supply_results_after_html_challenge(self):
        with mock.patch.object(W, "_http_get", side_effect=[CHALLENGE, LITE]):
            self.assertIn("Lite result", W.search("fallback"))

    def test_real_no_results_does_not_trigger_a_retry(self):
        with mock.patch.object(W, "_http_get", return_value=EMPTY) as get:
            self.assertTrue(W.search("no matching result").startswith("No results found"))
        get.assert_called_once()

    def test_rate_limit_is_not_retried(self):
        exc = urllib.error.HTTPError(W.SEARCH_ENDPOINT, 429, "limited", {}, io.BytesIO())
        with mock.patch.object(W, "_http_get", side_effect=exc) as get:
            self.assertIn("Rate limited", W.search("rate limit"))
        get.assert_called_once()

    def test_transient_http_error_and_timeout_can_use_lite(self):
        for exc in (urllib.error.HTTPError(W.SEARCH_ENDPOINT, 503, "offline", {}, io.BytesIO()),
                    TimeoutError("timeout")):
            W._search_cache.clear()
            with self.subTest(exc=exc), mock.patch.object(W, "_http_get", side_effect=[exc, LITE]) as get:
                self.assertIn("Lite result", W.search("retry"))
                self.assertEqual(get.call_count, 2)

    def test_unknown_layout_on_both_is_not_reported_as_no_results(self):
        with mock.patch.object(W, "_http_get", return_value="<html></html>") as get:
            text = W.search("unknown layout")
        self.assertTrue(text.startswith("Error:"))
        self.assertNotIn("No results found", text)
        self.assertEqual(get.call_count, 2)

    def test_cache_reuses_rows_across_requested_counts_and_normalizes_whitespace(self):
        with mock.patch.object(W, "_http_get", return_value=HTML) as get:
            one = W.search(" cache   query ", 1)
            two = W.search("cache query", 10)
        self.assertEqual(len(W.sources_from_result(one)), 1)
        self.assertEqual(len(W.sources_from_result(two)), 2)
        get.assert_called_once()

    def test_cache_expires_and_evicts_at_capacity(self):
        with mock.patch.object(W, "SEARCH_CACHE_SIZE", 2), \
                mock.patch.object(W, "_http_get", return_value=HTML) as get:
            W.search("first query")
            W.search("second query")
            W.search("third query")
            self.assertEqual(len(W._search_cache), 2)
            self.assertNotIn(("first query", ""), W._search_cache)
            expiry, rows, error = W._search_cache[("third query", "")]
            W._search_cache[("third query", "")] = (0, rows, error)
            W.search("third query")
            self.assertEqual(get.call_count, 4)

    def test_concurrent_identical_searches_share_one_request(self):
        entered, release = threading.Event(), threading.Event()

        def transport(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return HTML

        with mock.patch.object(W, "_http_get", side_effect=transport) as get, \
                ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(W.search, "same query")
            self.assertTrue(entered.wait(2))
            others = [pool.submit(W.search, "same query") for _ in range(3)]
            release.set()
            texts = [f.result(3) for f in [first] + others]
        self.assertEqual(len(set(texts)), 1)
        get.assert_called_once()
        self.assertFalse(W._search_pending)

    def test_failures_have_a_short_cooldown_and_never_become_results(self):
        with mock.patch.object(W, "_http_get", side_effect=OSError("offline")) as get:
            first = W.search("offline query")
            self.assertEqual(W.search("offline query"), first)
            self.assertEqual(get.call_count, 2)
            key = ("offline query", "")
            expiry, rows, error = W._search_cache[key]
            self.assertLessEqual(expiry - W.time.monotonic(), W.SEARCH_ERROR_TTL)
            self.assertEqual(rows, [])
            W._search_cache[key] = (0, rows, error)
        with mock.patch.object(W, "_http_get", return_value=HTML):
            self.assertFalse(W.search("offline query").startswith("Error:"))

    def test_proxy_change_does_not_reuse_a_different_egress_cache(self):
        with mock.patch.object(W, "_http_get", return_value=HTML) as get:
            W.search("same query")
            with mock.patch.dict(os.environ, {"WB_WEB_PROXY": "http://127.0.0.1:8888"}):
                W.search("same query")
        self.assertEqual(get.call_count, 2)

    def test_invalid_query_and_result_count_never_crash_or_make_invalid_requests(self):
        with mock.patch.object(W, "_http_get", return_value=HTML) as get:
            self.assertIn("at least 2 characters", W.search("x"))
            self.assertIn("exceeds", W.search("x" * (W.MAX_QUERY_CHARS + 1)))
            get.assert_not_called()
            self.assertEqual(len(W.sources_from_result(W.search("numbers", float("inf")))), 2)
            self.assertEqual(len(W.sources_from_result(W.search("numbers", -1))), 1)

    def test_both_attempts_share_one_timeout_budget(self):
        with mock.patch.object(W.time, "monotonic", side_effect=[10, 10, 17]), \
                mock.patch.object(W, "_http_get", side_effect=[TimeoutError(), LITE]) as get:
            rows, error = W._search_backend("budget")
        self.assertTrue(rows)
        self.assertFalse(error)
        self.assertEqual([call.kwargs["timeout"] for call in get.call_args_list], [20, 13])

    def test_http_read_size_and_gzip_expansion_are_bounded(self):
        with mock.patch.object(W, "MAX_HTTP_BYTES", 32), \
                mock.patch.object(W.wb_webnet, "open_response", return_value=(mock.Mock(), Response(b"x" * 33))):
            with self.assertRaises(W.ResponseLimitError):
                W._http_get("https://example.com/")
        zipped = gzip.compress(b"x" * 1000)
        with mock.patch.object(W, "MAX_HTTP_BYTES", 64), \
                mock.patch.object(W.wb_webnet, "open_response", return_value=(mock.Mock(), Response(zipped, encoding="gzip"))):
            with self.assertRaises(W.ResponseLimitError):
                W._http_get("https://example.com/")

    def test_http_decodes_compression_and_refuses_binary(self):
        with mock.patch.object(W.wb_webnet, "open_response", return_value=(mock.Mock(), Response(gzip.compress(HTML.encode()), encoding="gzip"))):
            self.assertEqual(W._http_get("https://example.com/"), HTML)
        with mock.patch.object(W.wb_webnet, "open_response", return_value=(mock.Mock(), Response(b"data", "image/png"))):
            with self.assertRaisesRegex(ValueError, "text responses"):
                W._http_get("https://example.com/")

    def test_real_http_response_can_close_its_socket_after_the_last_bytes(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                data = HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            def local_response(*args):
                connection = W.wb_webnet.http.client.HTTPConnection("127.0.0.1", server.server_port)
                connection.request("GET", "/")
                return connection, connection.getresponse()
            with mock.patch.object(W.wb_webnet, "open_response", side_effect=local_response):
                self.assertEqual(W._http_get("https://example.com/"), HTML)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_explicit_web_proxy_is_independent_of_account_routing(self):
        connection = mock.Mock()
        connection.getresponse.return_value = Response(HTML.encode())
        with mock.patch.dict(os.environ, {"WB_WEB_PROXY": "http://127.0.0.1:8888"}), \
                mock.patch.object(W.wb_webnet, "resolve_public", return_value=["8.8.8.8"]), \
                mock.patch.object(W.wb_webnet, "_TunnelHTTPS", return_value=connection) as factory:
            self.assertEqual(W._http_get("https://example.com/", timeout=3), HTML)
        self.assertEqual(factory.call_args.args, ("127.0.0.1", 8888))
        self.assertEqual(factory.call_args.kwargs["origin_host"], "example.com")
        self.assertLessEqual(factory.call_args.kwargs["timeout"], 3)
        self.assertEqual(connection.set_tunnel.call_args.args, ("8.8.8.8", 443))

    def test_fetch_and_search_sources_preserve_exact_urls(self):
        with mock.patch.object(W, "_http_get", return_value="<p>Fetched page.</p>"):
            result = W.fetch("https://example.com/?q=ends.")
        self.assertEqual(W.sources_from_result(result), [{"title": "https://example.com/?q=ends.",
                                                        "url": "https://example.com/?q=ends."}])
        self.assertEqual(W.sources_from_result("Error: could not fetch https://example.com/"), [])
        result = "Search results for: query\n\n1. Title\n   https://example.com/?q=ends.\n   Snippet"
        self.assertEqual(W.sources_from_result(result)[0]["url"], "https://example.com/?q=ends.")


if __name__ == "__main__":
    unittest.main()
