"""Adding an API Key must never retire a key the user did not remove.

The panel saves by submitting its whole in-memory key list. Two things made
that lose keys:

  * the save replaced the stored list, so any row the submission did not carry
    was soft-deleted. The panel's list can be stale or incomplete - a second
    browser tab, a save that raced the post-save reload, a reload that failed -
    and then "add a key" silently retired a key nobody removed;
  * a field the submission omitted (realm / enabled / name) was reset instead
    of kept, which wiped a key's exit binding the same way the older `models`
    bug (issue #92) wiped its model limits.

The fix is an explicit-delete upsert: the panel names the ids it removed in
`deleted_api_key_ids`, the server retires exactly those and leaves every other
stored key alone. An older client that sends no such field keeps the old
replace-by-omission contract, so nothing about it changes.

No network access required.

    python tests/_test_api_key_save_merge.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_proxy as proxy
import wb_settings as S


class FakeRequest(object):
    """Just enough of the handler for the pieces under test."""

    _handle_settings_save = proxy.Handler._handle_settings_save
    _validate_settings_save = proxy.Handler._validate_settings_save

    def __init__(self, payload):
        self.payload = payload
        self.answering = []

    def _payload_or_error(self, allow_list=False):
        return self.payload

    def _error(self, status, message, kind=""):
        self.answering.append(("error", status, message))
        return status, message

    def _json(self, status, payload):
        self.answering.append(("json", status, payload))
        return status, payload


class KeySaveMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-keymerge-")
        self.addCleanup(self.temp.cleanup)
        self.dir = self.temp.name
        proxy.ACCOUNTS_DIR = self.dir
        proxy.POOL = None
        proxy.PRICING = None
        proxy.API_KEY = None
        proxy.API_KEY_FILE_SET = False

    def _save(self, payload):
        request = FakeRequest(payload)
        request._handle_settings_save()
        for kind, status, _ in request.answering:
            if kind == "error":
                self.fail("save rejected with %s" % status)
        return proxy.runtime_settings_view()

    def _live(self):
        return {e["id"]: e for e in proxy.runtime_settings_view()["api_keys"]}

    def _all(self):
        return {e["id"]: e for e in S.api_keys(self.dir, include_deleted=True)}

    # --- storage contract -------------------------------------------------

    def test_replace_mode_retires_an_omitted_key(self):
        """No delete list: the old contract still retires by omission."""
        S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111", "realm": "intl"},
            {"id": "k2", "name": "b", "key": "key-bbbb2222", "realm": "cn"},
        ])
        saved = S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111", "realm": "intl"},
        ])
        self.assertEqual([e["id"] for e in saved], ["k1"])
        self.assertEqual(self._all()["k2"]["deleted_at"] != "", True)
        self.assertEqual(self._all()["k2"]["key"], "")

    def test_upsert_mode_keeps_an_omitted_key(self):
        """A delete list turns the save into an upsert: omission is not deletion."""
        S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111", "realm": "intl"},
            {"id": "k2", "name": "b", "key": "key-bbbb2222", "realm": "cn"},
        ])
        saved = S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111", "realm": "intl"},
        ], delete_ids=[])
        self.assertEqual(sorted(e["id"] for e in saved), ["k1", "k2"])
        self.assertEqual(self._all()["k2"]["deleted_at"], "")

    def test_upsert_mode_retires_exactly_the_named_ids(self):
        S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111"},
            {"id": "k2", "name": "b", "key": "key-bbbb2222"},
            {"id": "k3", "name": "c", "key": "key-cccc3333"},
        ])
        saved = S.set_api_keys(self.dir, [
            {"id": "k1", "name": "a", "key": "key-aaaa1111"},
            {"id": "k3", "name": "c", "key": "key-cccc3333"},
        ], delete_ids=["k2"])
        self.assertEqual(sorted(e["id"] for e in saved), ["k1", "k3"])
        self.assertNotEqual(self._all()["k2"]["deleted_at"], "")

    def test_upsert_mode_does_not_duplicate_a_resubmitted_secret(self):
        """The race: the same key resubmitted under a fresh id.

        The panel saved it, then added another key before the post-save reload
        landed, so it submitted the first key again with an empty id. One live
        row with that secret must remain, and no phantom retired duplicate.
        """
        S.set_api_keys(self.dir, [
            {"id": "old1", "name": "第一把", "key": "key-first-1111"},
        ])
        saved = S.set_api_keys(self.dir, [
            {"id": "", "name": "第一把", "key": "key-first-1111"},
            {"id": "", "name": "第二把", "key": "key-second-2222"},
        ], delete_ids=[])
        live = [e for e in saved]
        self.assertEqual(len(live), 2, live)
        self.assertEqual(sorted(e["name"] for e in live), ["第一把", "第二把"])
        secrets = sorted(e["key"] for e in live)
        self.assertEqual(secrets, ["key-first-1111", "key-second-2222"])

    # --- handler contract -------------------------------------------------

    def test_handler_preserves_realm_enabled_and_name_when_omitted(self):
        S.set_api_keys(self.dir, [
            {"id": "k1", "name": "国际", "key": "key-intl-1111",
             "realm": "intl", "models": ["deepseek/*"], "enabled": True},
            {"id": "k2", "name": "国内停用", "key": "key-cn-2222",
             "realm": "cn", "models": [], "enabled": False},
        ])
        # An older client that knows only id/name/key/enabled - and here omits
        # even the name on the first row.
        self._save({"api_keys": [
            {"id": "k1", "key": "", "enabled": True},
            {"id": "k2", "name": "国内停用", "key": "", "enabled": True},
            {"id": "", "name": "新Key", "key": "key-new-3333", "enabled": True},
        ]})
        live = self._live()
        self.assertEqual(live["k1"]["name"], "国际")
        self.assertEqual(live["k1"]["realm"], "intl")
        self.assertEqual(live["k1"]["models"], ["deepseek/*"])
        self.assertEqual(live["k2"]["realm"], "cn")
        # enabled was sent explicitly as true here, so it is honoured.
        self.assertEqual(live["k2"]["enabled"], True)

    def test_handler_keeps_disabled_state_when_enabled_omitted(self):
        S.set_api_keys(self.dir, [
            {"id": "k2", "name": "国内停用", "key": "key-cn-2222",
             "realm": "cn", "enabled": False},
        ])
        self._save({"api_keys": [
            {"id": "k2", "name": "国内停用", "key": ""},
            {"id": "", "name": "新Key", "key": "key-new-3333"},
        ]})
        live = self._live()
        self.assertEqual(live["k2"]["enabled"], False)
        self.assertEqual(live["k2"]["realm"], "cn")

    def test_handler_end_to_end_two_quick_adds_keep_both_keys(self):
        """The reported flow: add a key, save, add another, save."""
        # First save: the panel's only row is the brand-new key.
        self._save({"api_keys": [
            {"id": "", "name": "第一把", "realm": "intl", "models": [],
             "enabled": True, "key": "key-first-1111"},
        ], "deleted_api_key_ids": []})
        # Second save races the reload: the first key is still id-less locally,
        # so it is submitted again alongside the second.
        self._save({"api_keys": [
            {"id": "", "name": "第一把", "realm": "intl", "models": [],
             "enabled": True, "key": "key-first-1111"},
            {"id": "", "name": "第二把", "realm": "cn", "models": [],
             "enabled": True, "key": "key-second-2222"},
        ], "deleted_api_key_ids": []})
        live = self._live()
        self.assertEqual(len(live), 2, live)
        self.assertEqual(sorted(e["name"] for e in live.values()),
                         ["第一把", "第二把"])
        self.assertEqual(sorted(e["realm"] for e in live.values()), ["cn", "intl"])
        retired = [e for e in S.api_keys(self.dir, include_deleted=True)
                   if e["deleted_at"]]
        self.assertEqual(retired, [])

    def test_handler_explicit_delete_still_works(self):
        self._save({"api_keys": [
            {"id": "", "name": "甲", "realm": "", "models": [], "enabled": True,
             "key": "key-aaaa1111"},
            {"id": "", "name": "乙", "realm": "", "models": [], "enabled": True,
             "key": "key-bbbb2222"},
        ], "deleted_api_key_ids": []})
        live = self._live()
        keep = next(e for e in live.values() if e["name"] == "甲")
        drop = next(e for e in live.values() if e["name"] == "乙")
        self._save({
            "api_keys": [{"id": keep["id"], "name": "甲", "realm": "",
                          "models": [], "enabled": True, "key": ""}],
            "deleted_api_key_ids": [drop["id"]],
        })
        live = self._live()
        self.assertEqual(sorted(e["name"] for e in live.values()), ["甲"])
        all_rows = S.api_keys(self.dir, include_deleted=True)
        retired = next(e for e in all_rows if e["id"] == drop["id"])
        self.assertNotEqual(retired["deleted_at"], "")
        self.assertEqual(retired["key"], "")

    def test_invalid_delete_list_has_no_partial_write(self):
        S.set_api_keys(self.dir, [{"id": "k1", "key": "key-first-1111"}])
        original = S.load(self.dir)
        request = FakeRequest({"deleted_api_key_ids": [None], "pricing_enabled": False})
        request._handle_settings_save()
        self.assertEqual(request.answering[0][1], 400)
        self.assertEqual(S.load(self.dir), original)

    def test_stale_tab_cannot_revive_retired_id(self):
        S.set_api_keys(self.dir, [{"id": "k1", "key": "key-first-1111"}])
        self._save({"deleted_api_key_ids": ["k1"]})
        request = FakeRequest({"api_keys": [{"id": "k1", "key": "key-first-1111"}], "deleted_api_key_ids": []})
        request._handle_settings_save()
        self.assertEqual(request.answering[0][1], 400)
        self.assertEqual(self._live(), {})

    def test_repeated_idless_secret_keeps_original_history_id(self):
        S.set_api_keys(self.dir, [{"id": "k1", "key": "key-first-1111", "realm": "cn"}])
        self._save({"api_keys": [{"key": "key-first-1111"}], "deleted_api_key_ids": []})
        self.assertEqual(list(self._live()), ["k1"])
        self.assertEqual(self._live()["k1"]["realm"], "cn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
