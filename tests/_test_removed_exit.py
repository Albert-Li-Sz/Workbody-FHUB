"""Retired exits cannot route into WorkBuddy or open anonymous access."""
import http.client
from http.server import ThreadingHTTPServer
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_proxy as P
import wb_settings as S


class ValidationRequest:
    def _error(self, status, message, *args):
        return status, {"error": {"message": message}}


class QuietHandler(P.Handler):
    def log_message(self, *args):
        pass


class RetiredExitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="removed-exit-")
        self.addCleanup(self.temp.cleanup)
        self.patches = mock.patch.multiple(P, ACCOUNTS_DIR=self.temp.name, API_KEY=None, POOL=None)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        S.save(self.temp.name, {
            "opencode": {"enabled": True, "api_key": "synthetic-retired-upstream"},
            "api_keys": [
                {"id": "old", "name": "Retired", "key": "synthetic-retired-key", "realm": "opencode", "enabled": True},
                {"id": "wb", "name": "WorkBuddy", "key": "synthetic-workbuddy-key", "realm": "intl", "enabled": True},
            ],
        })

    def request(self, path, key=""):
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = http.client.HTTPConnection(*server.server_address, timeout=3)
            client.request("GET", path, headers={"Authorization": "Bearer " + key} if key else {})
            response = client.getresponse()
            status, body = response.status, response.read()
            client.close()
            return status, json.loads(body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def validate(self, payload):
        return P.Handler._validate_settings_save(ValidationRequest(), payload)

    def test_old_binding_is_preserved_for_history_but_cannot_authenticate(self):
        old, active = S.api_keys(self.temp.name)
        self.assertEqual(old["realm"], "opencode")
        self.assertFalse(old["enabled"])
        self.assertIsNone(S.match_api_key(self.temp.name, old["key"]))
        self.assertEqual(S.match_api_key(self.temp.name, active["key"])["realm"], "intl")

    def test_retired_key_is_refused_over_http_before_workbuddy_catalogue_fetch(self):
        with mock.patch.object(P, "fetch_models") as fetch:
            status, _ = self.request("/v1/models", "synthetic-retired-key")
            self.assertEqual(status, 401)
            fetch.assert_not_called()

    def test_only_retired_keys_still_require_authentication(self):
        S.set_api_keys(self.temp.name, S.api_keys(self.temp.name)[:1])
        self.assertTrue(P.auth_required())
        self.assertEqual(self.request("/v1/models")[0], 401)

    def test_disabling_the_last_workbuddy_key_still_requires_authentication(self):
        S.set_api_keys(self.temp.name, [dict(S.api_keys(self.temp.name)[1], enabled=False)])
        self.assertTrue(P.auth_required())
        self.assertEqual(self.request("/v1/models")[0], 401)

    def test_explicit_operator_auth_off_switch_still_works(self):
        S.set_auth_disabled(self.temp.name, True)
        self.assertFalse(P.auth_required())

    def test_removed_catalogue_channel_cannot_fetch_any_upstream(self):
        with mock.patch.object(P, "fetch_models") as fetch:
            status, _ = self.request("/v1/models?channel=opencode", "synthetic-workbuddy-key")
            self.assertEqual(status, 400)
            fetch.assert_not_called()

    def test_settings_view_no_longer_contains_retired_configuration(self):
        self.assertNotIn("opencode", P.runtime_settings_view())

    def test_old_settings_payload_is_rejected_explicitly(self):
        plan, response = self.validate({"opencode": {"enabled": True}})
        self.assertIsNone(plan)
        self.assertEqual(response[0], 400)

    def test_new_and_reenabled_retired_bindings_are_rejected(self):
        for entry_id in ("", "old"):
            plan, response = self.validate({"api_keys": [
                {"id": entry_id, "key": "synthetic-retired-key", "realm": "opencode", "enabled": True}]})
            self.assertIsNone(plan)
            self.assertEqual(response[0], 400)

    def test_disabled_old_binding_survives_an_unrelated_key_save(self):
        plan, response = self.validate({"api_keys": [
            {"id": "old", "realm": "opencode", "enabled": False, "key": ""},
            {"id": "wb", "realm": "intl", "enabled": True, "key": ""}]})
        self.assertIsNone(response)
        S.set_api_keys(self.temp.name, plan["api_keys"])
        self.assertFalse(S.api_keys(self.temp.name)[0]["enabled"])
        self.assertEqual(S.api_keys(self.temp.name)[1]["realm"], "intl")

    def test_operator_can_explicitly_rebind_a_retired_key_to_workbuddy(self):
        plan, response = self.validate({"api_keys": [
            {"id": "old", "realm": "cn", "enabled": True, "key": ""},
            {"id": "wb", "realm": "intl", "enabled": True, "key": ""}]})
        self.assertIsNone(response)
        S.set_api_keys(self.temp.name, plan["api_keys"])
        self.assertEqual(S.match_api_key(self.temp.name, "synthetic-retired-key")["realm"], "cn")


if __name__ == "__main__":
    unittest.main()
