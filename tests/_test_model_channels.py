"""Channel catalogues are independent from the default exit and key binding."""
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_opencode_catalog as C
import wb_proxy as P


INDEX = {"opencode": {"models": {
    "example": {"name": "Example", "limit": {"context": 100000, "output": 10000},
                "modalities": {"input": ["text", "image"]}, "reasoning": True,
                "tool_call": True, "cost": {"input": 2, "output": 8}},
    "example-free": {"limit": {"context": 32000}, "cost": {"input": 0, "output": 0}},
    "old-model": {"limit": {"context": 20000}},
}}}
LIVE = {"data": [{"id": "example"}, {"id": "example-free"}, {"id": "new-model"}]}


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


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        C._cache.clear()
        C._failures.clear()

    def test_exact_ids_and_free_suffix_survive_and_retired_metadata_is_excluded(self):
        result = C.build_opencode_catalog(INDEX, LIVE)
        self.assertEqual([m["id"] for m in result["data"]], ["example", "example-free", "new-model"])
        self.assertEqual(result["source"], "opencode+models.dev")
        model = result["data"][0]
        self.assertEqual(model["context_length"], 100000)
        self.assertEqual(model["max_output_tokens"], 10000)
        self.assertTrue(model["supports_vision"])
        self.assertEqual(model["pricing"], {"input": 2, "output": 8})
        self.assertNotIn("context_length", result["data"][2])
        self.assertNotIn("credits", model)
        self.assertFalse(result["inference_ready"])

    def test_metadata_fallback_is_labelled_and_does_not_borrow_other_providers(self):
        index = dict(INDEX, unrelated={"models": {"not-opencode": {}}})
        result = C.build_opencode_catalog(index)
        self.assertEqual(result["source"], "models.dev")
        self.assertNotIn("not-opencode", [m["id"] for m in result["data"]])
        with self.assertRaises(ValueError):
            C.build_opencode_catalog({"unrelated": {"models": {"m": {}}}})

    def test_malformed_optional_metadata_does_not_invent_capabilities_or_limits(self):
        result = C.build_opencode_catalog({"opencode": {"models": {
            "one": "bad", "two": {"limit": {"context": True, "output": float("inf")},
                                  "reasoning_options": 42}
        }}}, {"data": [{"id": "one"}, {"id": "two"}]})
        for model in result["data"]:
            self.assertNotIn("context_length", model)
            self.assertNotIn("max_output_tokens", model)
            self.assertNotIn("supports_vision", model)

    def test_compressed_json_is_decoded_and_expansion_is_bounded(self):
        class Response(io.BytesIO):
            headers = {"Content-Encoding": "gzip"}

        body = json.dumps(LIVE).encode()
        with mock.patch.object(C.urllib.request, "urlopen", return_value=Response(gzip.compress(body))) as fetch:
            self.assertEqual(C._get_json(C.OPENCODE_MODELS_URL), LIVE)
            self.assertEqual(fetch.call_args[0][0].get_header("Accept-encoding"), "gzip")
        with mock.patch.object(C, "MAX_BODY", 200), \
                mock.patch.object(C.urllib.request, "urlopen", return_value=Response(gzip.compress(b" " * 1000))):
            with self.assertRaisesRegex(ValueError, "size limit"):
                C._get_json(C.OPENCODE_MODELS_URL)

    def test_cache_persists_separately_and_returns_an_independent_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(C, "_get_json", side_effect=[LIVE, INDEX]) as fetch:
                first = C.opencode_catalog(directory)
                first["data"].clear()
                second = C.opencode_catalog(directory)
                self.assertTrue(second["data"])
                self.assertEqual(fetch.call_count, 2)
            path = os.path.join(directory, "catalogs", "opencode.json")
            self.assertTrue(os.path.exists(path))
            if os.name != "nt":
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            C._cache.clear()
            with mock.patch.object(C, "_get_json") as fetch:
                self.assertTrue(C.opencode_catalog(directory)["data"])
                fetch.assert_not_called()

    def test_old_cache_is_explicitly_stale_on_network_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(C, "_get_json", side_effect=[LIVE, INDEX]):
                C.opencode_catalog(directory)
            C._cache[os.path.abspath(directory)]["at"] = 0
            with mock.patch.object(C, "_get_json", side_effect=OSError("offline")) as fetch:
                result = C.opencode_catalog(directory)
                self.assertTrue(result["stale"])
                self.assertTrue(result["data"])
                C.opencode_catalog(directory)
                self.assertEqual(fetch.call_count, 2)

    def test_failure_without_cache_is_throttled(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(C, "_get_json", side_effect=OSError("offline")) as fetch:
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "temporarily unavailable"):
                        C.opencode_catalog(directory)
                self.assertEqual(fetch.call_count, 2)


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

    def test_opencode_never_uses_workbuddy_catalogue(self):
        with mock.patch.object(C, "opencode_catalog", return_value={"data": [{"id": "oc"}]}) as fetch, \
                mock.patch.object(P, "fetch_models") as workbuddy:
            status, result = P.Handler._get_v1_models(Request("opencode"))
            self.assertEqual(status, 200)
            self.assertEqual(result["data"][0]["id"], "oc")
            fetch.assert_called_once_with(P.ACCOUNTS_DIR)
            workbuddy.assert_not_called()

    def test_unauthorized_and_invalid_channels_never_fetch_catalogues(self):
        with mock.patch.object(C, "opencode_catalog") as fetch, mock.patch.object(P, "fetch_models") as wb:
            self.assertIsNone(P.Handler._get_v1_models(Request("opencode", authorized=False)))
            self.assertEqual(P.Handler._get_v1_models(Request("unexpected"))[0], 400)
            fetch.assert_not_called()
            wb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
