"""Regression pins for the 2026-10-11 audit fixes.

Security and usage regressions from that review are pinned here:

  F1  runtime_settings_view() carried the `models` key twice. Python keeps the
      last literal and drops the first, so the "live" line was dead code: an
      edit to it would look applied while changing nothing.
  F2  the LAN/Docker startup banner printed the gateway API key verbatim.
      `docker compose logs` captures stdout, so the key became a persisted
      secret. It is now masked unless stdout is an interactive terminal.
  F3  public diagnostics answered deployment details to anonymous callers.
  F4  platform exports included credentials without an explicit opt-in.
  F5  _scan_usage_log() defined two closures for every row of the log.

Run with: python tests/_test_audit_2026_10_11.py
Temp dirs, a mocked pricing/metrics layer; no network and no real credentials.
"""
import contextlib
import http.client
import inspect
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

_startup_dir = tempfile.TemporaryDirectory(prefix="audit-2026-10-11-")
os.environ["ACCOUNTS_DIR"] = _startup_dir.name
os.environ["WB_PROXY_USAGE_DIR"] = _startup_dir.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_proxy as proxy


class _FakePool(object):
    def __init__(self, accounts=()):
        self.accounts = list(accounts)

    def count_ready(self, allow_refresh=True):
        return len(self.accounts)


class _FakeRequest(object):
    """Minimal handler surface used by _get_health / runtime_settings_view."""

    def __init__(self, key_ok=False):
        self._key_ok_result = key_ok

    def _key_ok(self, require_credentials=False):
        return self._key_ok_result

    def _json(self, status, payload):
        return status, payload


class DuplicateKeyTests(unittest.TestCase):
    def test_runtime_settings_view_declares_models_once(self):
        source = inspect.getsource(proxy.runtime_settings_view)
        self.assertEqual(source.count('"models":'), 1,
                         "the `models` key must be written once; a duplicate "
                         "literal silently discards the earlier line")

    def test_non_list_models_stored_value_becomes_an_empty_list(self):
        entry = {"id": "k1", "name": "k", "key": "wb-secret", "enabled": True,
                 "models": "not-a-list", "allowed_upstreams": ["workbuddy"]}
        with mock.patch.object(proxy, "configured_keys", return_value=[entry]), \
                mock.patch.object(proxy, "API_KEY", ""), \
                mock.patch.object(proxy.wb_settings, "api_keys", return_value=[]):
            view = proxy.runtime_settings_view()
        self.assertEqual(view["api_keys"][0]["models"], [],
                         "a hand-edited string must not reach the panel as a list-shaped value")


class StartupBannerTests(unittest.TestCase):
    KEY = "wb-abcdefghijklmnopqrstuvwx"

    def _summary(self, isatty):
        class _Stream(io.StringIO):
            def isatty(self):
                return isatty

        out, err = _Stream(), _Stream()
        args = SimpleNamespace(host="0.0.0.0", port=8788)
        with mock.patch.object(proxy, "API_KEY", self.KEY), \
                mock.patch.object(proxy, "POOL", _FakePool()), \
                mock.patch.object(proxy, "current_account", return_value=None), \
                mock.patch.object(proxy, "local_ip_addresses", return_value=["192.168.1.5"]), \
                mock.patch.object(proxy, "IS_WINDOWS", False), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            proxy._log_startup_summary(args, api_key_generated=False)
        return out.getvalue() + err.getvalue()

    def test_captured_output_masks_the_gateway_key(self):
        text = self._summary(isatty=False)
        self.assertNotIn(self.KEY, text, "a captured log must never carry the live key")
        self.assertIn(proxy._masked_secret(self.KEY), text)
        self.assertIn("设置 -> API Key", text)
        self.assertNotIn("?key=", text, "the key-bearing dashboard URL is terminal-only")

    def test_interactive_terminal_still_shows_the_key(self):
        text = self._summary(isatty=True)
        self.assertIn(self.KEY, text)
        self.assertIn("?key=", text)

    def test_masked_secret_keeps_ends_and_hides_the_middle(self):
        masked = proxy._masked_secret("wb-1234567890abcdef")
        self.assertTrue(masked.startswith("wb-1"))
        self.assertTrue(masked.endswith("cdef"))
        self.assertNotIn("567890ab", masked)
        self.assertEqual(proxy._masked_secret("short"), "*****")


class HealthDisclosureTests(unittest.TestCase):
    def _health(self, key_ok, accounts=()):
        request = _FakeRequest(key_ok=key_ok)
        with mock.patch.object(proxy, "POOL", _FakePool(accounts)), \
                mock.patch.object(proxy, "current_account", return_value=None):
            return proxy.Handler._get_health(request)

    def test_anonymous_health_hides_pool_size(self):
        status, payload = self._health(False, accounts=["a", "b"])
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("version", payload)
        self.assertIn("api_key_required", payload)
        self.assertNotIn("accounts", payload)
        self.assertNotIn("accounts_ready", payload)

    def test_authenticated_health_still_reports_the_pool(self):
        status, payload = self._health(True, accounts=["a", "b"])
        self.assertEqual(status, 200)
        self.assertEqual(payload["accounts"], 2)
        self.assertEqual(payload["accounts_ready"], 2)


class DiagnosticHTTPTests(unittest.TestCase):
    """Exercise the public routes and the panel-only export over local HTTP."""

    KEY = "gateway-audit-fixture"
    SECRET = "source-audit-fixture"
    PRIVATE_FIELDS = {"accounts", "accounts_ready", "realm", "current", "uid",
                      "domain", "issuer", "credential_file", "expires_at",
                      "api_key_set", "panel_password_is_default"}

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="audit-http-"))
        manager = proxy.wb_platforms.Manager(directory)
        manager.import_accounts({"upstream": "cline", "api_key": self.SECRET})
        self.manager = manager
        panel = proxy.wb_settings.PanelSessions()
        self.panel_token = panel.create()
        stack.enter_context(mock.patch.multiple(
            proxy, ACCOUNTS_DIR=directory, API_KEY=self.KEY, PANEL=panel,
            POOL=_FakePool(["a", "b"]), PLATFORMS=manager))
        stack.enter_context(mock.patch.object(proxy, "current_account", return_value=None))
        stack.enter_context(mock.patch.object(proxy.wb_settings, "panel_password_is_default",
                                             return_value=True))
        class Handler(proxy.Handler):
            def log_message(self, *args):
                pass
        server = proxy.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = server.server_address[1]
        worker = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        stack.callback(server.server_close)
        stack.callback(worker.join, 2)
        stack.callback(server.shutdown)

    def get(self, path, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            client.request("GET", path, headers=headers or {})
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_anonymous_diagnostics_hide_deployment_details(self):
        for headers in ({}, {"Authorization": "Bearer invalid-fixture"}):
            for path in ("/health", "/realm", "/panel/status"):
                with self.subTest(path=path, headers=headers):
                    status, payload = self.get(path, headers)
                    self.assertEqual(status, 200)
                    self.assertFalse(self.PRIVATE_FIELDS.intersection(payload), payload)

    def test_disabled_api_auth_does_not_make_diagnostics_public(self):
        proxy.wb_settings.set_auth_disabled(proxy.ACCOUNTS_DIR, True)
        for path in ("/health", "/realm", "/panel/status"):
            with self.subTest(path=path):
                status, payload = self.get(path)
                self.assertEqual(status, 200)
                self.assertFalse(self.PRIVATE_FIELDS.intersection(payload), payload)

    def test_credentials_retain_diagnostics_and_panel_login_state(self):
        for headers in ({"Authorization": "Bearer " + self.KEY},
                        {"X-Panel-Token": self.panel_token}):
            status, health = self.get("/health", headers)
            self.assertEqual(status, 200)
            self.assertEqual(health["accounts"], 2)
            self.assertEqual(health["accounts_ready"], 2)
            self.assertEqual(health["realm"], proxy.CURRENT_REALM)
            status, realm = self.get("/realm", headers)
            self.assertEqual(status, 200)
            self.assertEqual(realm["current"], proxy.CURRENT_REALM)
        status, panel = self.get("/panel/status", {"X-Panel-Token": self.panel_token})
        self.assertEqual(status, 200)
        self.assertTrue(panel["authenticated"])
        self.assertTrue(panel["panel_password_is_default"])

    def test_anonymous_health_does_not_inspect_account_state(self):
        with mock.patch.object(proxy, "current_account") as current:
            self.get("/health")
        current.assert_not_called()

    def test_export_requires_an_explicit_secret_flag(self):
        for prefix in ("/platforms", "/accounts/upstreams"):
            for flag in ("", "&includeSecrets=0", "&includeSecrets=false",
                         "&includeSecrets=1", "&includeSecrets=true"):
                with self.subTest(prefix=prefix, flag=flag):
                    status, payload = self.get(prefix + "/accounts/export?upstream=cline" + flag,
                                               {"X-Panel-Token": self.panel_token})
                    self.assertEqual(status, 200, payload)
                    self.assertEqual(payload["count"], 1)
                    self.assertEqual(self.SECRET in json.dumps(payload),
                                     flag in ("&includeSecrets=1", "&includeSecrets=true"))
            for flag in ("yes", "2"):
                status, payload = self.get(prefix + "/accounts/export?includeSecrets=" + flag,
                                           {"X-Panel-Token": self.panel_token})
                self.assertEqual(status, 400)
                self.assertNotIn(self.SECRET, json.dumps(payload))
            status, payload = self.get(prefix + "/accounts/export?includeSecrets=1",
                                       {"Authorization": "Bearer " + self.KEY})
            self.assertEqual(status, 401)
            self.assertNotIn(self.SECRET, json.dumps(payload))

    def test_manager_export_is_redacted_by_default(self):
        self.assertNotIn(self.SECRET, json.dumps(self.manager.export_accounts()))
        self.assertIn(self.SECRET, json.dumps(self.manager.export_accounts(secrets=True)))

    def test_startup_recognizes_redacted_health_and_legacy_health(self):
        args = SimpleNamespace(host="127.0.0.1", port=8788)
        for health in ({"ok": True, "service": "workbody-fhub", "version": proxy.VERSION},
                       {"ok": True, "accounts": 0, "version": proxy.VERSION}):
            with self.subTest(health=health), \
                    mock.patch.object(proxy.urllib.request, "urlopen",
                                      return_value=io.BytesIO(json.dumps(health).encode())), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(proxy._probe_running_instance(args))
                self.assertIn("已有一个反代", output.getvalue())


class UsageScanFoldTests(unittest.TestCase):
    ROWS = [
        {"at": 100, "model": "m1", "account": "a1", "outcome": "completed",
         "prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
        {"at": 200, "model": "m1", "account": "a1", "outcome": "client_aborted",
         "total_tokens": 5},
        {"at": 300, "model": "m2", "account": "a2", "outcome": "failed",
         "total_tokens": 7},
    ]

    def test_fold_helpers_are_module_level(self):
        self.assertTrue(callable(proxy._fold_usage_stat))
        self.assertTrue(callable(proxy._bump_model_totals))
        source = inspect.getsource(proxy._scan_usage_log)
        self.assertNotIn("def feed(", source,
                         "the per-row closures must stay hoisted out of the loop")
        self.assertNotIn("def bump_models(", source)

    def test_scan_totals_match_the_previous_semantics(self):
        all_summary, window_summary = proxy._new_analytics_stat(), proxy._new_analytics_stat()
        acct_map, model_map = {}, {}
        with mock.patch.object(proxy.wb_pricing, "cost_for_row",
                               return_value={"known": False, "cny": 0.0}), \
                mock.patch.object(proxy.wb_metrics, "speed_sample", return_value=None):
            proxy._scan_usage_log(all_summary, window_summary, acct_map, model_map,
                                  rows=self.ROWS)
        self.assertEqual(all_summary["requests"], 1)
        self.assertEqual(all_summary["client_aborted"], 1)
        self.assertEqual(all_summary["errors"], 1)
        self.assertEqual(all_summary["total_tokens"], 22)
        # Token totals follow consumption even when the call failed.
        self.assertEqual(acct_map["a2"]["all_time"]["errors"], 1)
        self.assertEqual(acct_map["a2"]["all_time"]["total_tokens"], 7)
        # Only successful requests count as demand for a model.
        self.assertEqual(model_map["m1"]["all_time"]["requests"], 1)
        self.assertEqual(model_map["m2"]["all_time"]["requests"], 0)
        self.assertEqual(window_summary["requests"], 1)

    def test_client_abort_contributes_tokens_but_no_speed_sample(self):
        stat = proxy._new_analytics_stat()
        row = {"total_tokens": 9, "elapsed_ms": 500, "ttft_ms": 100}
        proxy._fold_usage_stat(stat, row, "client_aborted", {"known": False, "cny": 0.0})
        self.assertEqual(stat["client_aborted"], 1)
        self.assertEqual(stat["total_tokens"], 9)
        self.assertEqual(stat["elapsed_n"], 0)
        self.assertEqual(stat["ttft_n"], 0)


if __name__ == "__main__":
    unittest.main()
