"""Credential files must stay private during creation, replacement and reload."""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_accounts as A
import wb_settings as S
import wb_storage


@unittest.skipIf(os.name == "nt", "Unix permission bits do not enforce Windows ACLs")
class PrivateStorageTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="wb-private-")
        self.addCleanup(self.work.cleanup)
        self.directory = os.path.join(self.work.name, "accounts")
        self.account = A.Account({"uid": "synthetic", "realm": "intl",
                                  "accessToken": "fake-access", "refreshToken": "fake-refresh"})
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_new_account_and_settings_are_private_before_writing(self):
        original_dump = json.dump
        observed = []

        def inspect_dump(data, fh, **kwargs):
            observed.append((stat.S_IMODE(os.fstat(fh.fileno()).st_mode),
                             self.mode(self.directory)))
            return original_dump(data, fh, **kwargs)

        with patch.object(wb_storage.json, "dump", side_effect=inspect_dump):
            account_path = self.account.save(self.directory)
            settings_path = S.save(self.directory, {"api_keys": [{"key": "fake-key"}]})
        self.assertEqual(observed, [(0o600, 0o700), (0o600, 0o700)])
        self.assertEqual(self.mode(account_path), 0o600)
        self.assertEqual(self.mode(settings_path), 0o600)
        self.assertEqual(self.mode(self.directory), 0o700)
        self.assertEqual(S.load(self.directory)["api_keys"][0]["key"], "fake-key")

    def test_replacement_tightens_a_legacy_account_file(self):
        path = self.account.save(self.directory)
        os.chmod(path, 0o644)
        os.chmod(self.directory, 0o755)
        self.account.refresh_token = "fake-updated"
        self.account.save(self.directory)
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(self.mode(self.directory), 0o700)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["refreshToken"], "fake-updated")
        self.assertEqual(sorted(os.listdir(self.directory)), ["synthetic.json"])

    def test_pool_load_hardens_existing_credentials_without_losing_tokens(self):
        path = self.account.save(self.directory)
        os.chmod(path, 0o644)
        os.chmod(self.directory, 0o755)
        loaded = A.AccountPool(self.directory).load()
        self.assertEqual(loaded[0].refresh_token, "fake-refresh")
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(self.mode(self.directory), 0o700)

    def test_settings_load_hardens_existing_api_keys(self):
        path = S.save(self.directory, {"api_keys": [{"key": "fake-key"}]})
        os.chmod(path, 0o644)
        os.chmod(self.directory, 0o755)
        self.assertEqual(S.load(self.directory)["api_keys"][0]["key"], "fake-key")
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(self.mode(self.directory), 0o700)

    def test_failed_atomic_write_preserves_old_value_and_cleans_up(self):
        path = S.save(self.directory, {"api_keys": [{"key": "fake-original"}]})
        with self.assertRaises(TypeError):
            S.save(self.directory, {"not_json": set()})
        self.assertEqual(S.load(self.directory)["api_keys"][0]["key"], "fake-original")
        self.assertEqual(self.mode(path), 0o600)
        self.assertEqual(os.listdir(self.directory), ["settings.json"])

    def test_permission_failure_cannot_silently_reset_auth_settings(self):
        S.save(self.directory, {"api_keys": [{"key": "fake-key"}]})
        with patch.object(wb_storage, "restrict_file", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                S.load(self.directory)


if __name__ == "__main__":
    unittest.main()
