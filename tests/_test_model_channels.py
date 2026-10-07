"""WorkBuddy model catalogues do not change default exits or key bindings."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_proxy as P


class Request:
    def __init__(self, channel=None, bound="intl", authorized=True):
        self.path = "/v1/models" + ("?channel=" + channel if channel else "")
        self.bound = bound
        self.authorized = authorized

    def _authorized(self):
        return self.authorized

    def _request_realm(self):
        return self.bound

    def _json(self, status, payload):
        return status, payload

    def _error(self, status, message, *args):
        return status, {"error": {"message": message}}


class ChannelRouteTests(unittest.TestCase):
    def test_both_workbuddy_channels_are_explicit_without_changing_default(self):
        original = P.CURRENT_REALM
        for channel, realm in (("workbuddy-cn", "cn"), ("workbuddy-intl", "intl")):
            with self.subTest(channel=channel), \
                    mock.patch.object(P, "fetch_models", return_value=[("model", {})]) as fetch, \
                    mock.patch.object(P, "model_entry", return_value={"id": "model"}), \
                    mock.patch.object(P.wb_modelsdev, "refresh_async"):
                status, response = P.Handler._get_v1_models(Request(channel))
                self.assertEqual(status, 200)
                self.assertEqual(response["realm"], realm)
                self.assertEqual(response["data"][0]["channel"], channel)
                fetch.assert_called_once_with(realm=realm)
                self.assertEqual(P.CURRENT_REALM, original)

    def test_legacy_model_listing_still_follows_key_realm(self):
        with mock.patch.object(P, "fetch_models", return_value=[]) as fetch, \
                mock.patch.object(P.wb_modelsdev, "refresh_async"):
            P.Handler._get_v1_models(Request(bound="cn"))
            fetch.assert_called_once_with(realm="cn")

    def test_legacy_combined_realm_is_not_mislabelled_as_international(self):
        with mock.patch.object(P, "fetch_models", return_value=[("model", {})]), \
                mock.patch.object(P, "model_entry", return_value={"id": "model"}), \
                mock.patch.object(P.wb_modelsdev, "refresh_async"):
            _, result = P.Handler._get_v1_models(Request(bound="all"))
            self.assertIsNone(result["channel"])
            self.assertNotIn("channel", result["data"][0])

    def test_unauthorized_and_removed_channels_never_fetch_catalogues(self):
        with mock.patch.object(P, "fetch_models") as fetch:
            self.assertIsNone(P.Handler._get_v1_models(Request("workbuddy-cn", authorized=False)))
            for channel in ("opencode", "unexpected"):
                self.assertEqual(P.Handler._get_v1_models(Request(channel))[0], 400)
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
