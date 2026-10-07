"""Legacy account portability before adding another provider.

Exercise the exported document through the real importer and disk reload.
All credentials and proxy addresses are synthetic; no network is used.
"""
import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_accounts as A
import wb_settings as S


def jwt(uid="transfer-user", realm="intl"):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    issuer = "https://www.workbuddy.ai" if realm == "intl" else "https://copilot.tencent.com"
    return encode({"alg": "none"}) + "." + encode(
        {"sub": uid, "iss": issuer, "exp": 4102444800}) + ".synthetic"


def account(realm="intl", product="vscode"):
    return A.Account({
        "uid": "transfer-user", "realm": realm, "nickname": "Synthetic transfer",
        "accessToken": jwt(realm=realm), "refreshToken": "synthetic-refresh",
        "product": product, "proxySlot": "slot-1",
        "proxy": "http://127.0.0.1:18080", "addedAt": 1700000000,
        "platform": "CLI", "enterpriseId": "synthetic-enterprise", "source": "import",
    })


class AccountTransferTests(unittest.TestCase):
    def transfer(self, original, directory):
        document = A.build_export_document([original])
        rows, problem = A._coerce_account_rows(json.loads(json.dumps(document)))
        self.assertEqual(problem, "")
        pool = A.AccountPool(directory)
        report = pool.import_rows(rows)
        self.assertEqual(report["added"], [original.uid])
        self.assertEqual(report["invalid"], [])
        reloaded = A.AccountPool(directory)
        reloaded.load()
        return reloaded.get(original.uid)

    def test_all_identities_and_realms_survive_document_and_disk_round_trip(self):
        for realm in ("intl", "cn"):
            for product in ("workbuddy", "vscode", "cli"):
                with self.subTest(realm=realm, product=product), tempfile.TemporaryDirectory() as directory:
                    original = account(realm, product)
                    restored = self.transfer(original, directory)
                    for name in ("uid", "realm", "domain", "nickname", "product", "platform",
                                 "enterprise_id", "access_token", "refresh_token", "expires_at",
                                 "proxy_slot", "proxy_legacy", "added_at", "source"):
                        self.assertEqual(getattr(restored, name), getattr(original, name), name)
                    self.assertEqual(restored.chat_base_url(), original.chat_base_url())
                    if os.name != "nt":
                        self.assertEqual(os.stat(restored.path).st_mode & 0o777, 0o600)
                        self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)

    def test_target_slot_resolves_locally_without_exporting_resolved_address(self):
        original = account()
        original.proxy = "http://127.0.0.1:19000"  # Resolved only on the source machine.
        self.assertEqual(A.build_export_document([original])["accounts"][0]["proxy"],
                         original.proxy_legacy)
        with tempfile.TemporaryDirectory() as directory:
            S.set_proxy_slots(directory, [{"id": "slot-1", "name": "Target slot",
                                          "url": "http://127.0.0.1:18081", "enabled": True}])
            restored = self.transfer(original, directory)
            restored_pool = A.AccountPool(directory)
            restored_pool.load()
            restored_pool.apply_proxy_slots()
            resolved = restored_pool.get(original.uid)
            self.assertEqual(restored.proxy_slot, "slot-1")
            self.assertEqual(resolved.proxy, "http://127.0.0.1:18081")
            self.assertEqual(resolved.proxy_legacy, "http://127.0.0.1:18080")

    def test_missing_target_slot_keeps_binding_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            original = account()
            restored = self.transfer(original, directory)
            self.assertEqual(restored.proxy_slot, original.proxy_slot)
            self.assertEqual(restored.proxy, original.proxy_legacy)

    def test_flat_list_single_and_nested_desktop_shapes_keep_identity(self):
        row = account().to_dict()
        for document in ([row], row, {"account": {"uid": row["uid"], "nickname": row["nickname"]},
                                     "auth": row}):
            with self.subTest(document_type=type(document).__name__):
                rows, problem = A._coerce_account_rows(document)
                self.assertEqual(problem, "")
                normalized = A.normalise_import_row(rows[0])
                self.assertEqual(normalized["product"], "vscode")
                self.assertEqual(normalized["proxySlot"], "slot-1")
                self.assertEqual(normalized["addedAt"], 1700000000)

    def test_cockpit_alias_translation_keeps_portable_fields(self):
        row = account().to_dict()
        row["access_token"] = row.pop("accessToken")
        row["refresh_token"] = row.pop("refreshToken")
        row["expires_at"] = row.pop("expiresAt") * 1000
        restored = A.Account(A.normalise_import_row(row))
        self.assertEqual(restored.product, "vscode")
        self.assertEqual(restored.proxy_slot, "slot-1")
        self.assertEqual(restored.added_at, 1700000000)
        self.assertEqual(restored.source, "cockpit")

    def test_legacy_missing_identity_and_routing_keep_defaults(self):
        row = {"uid": "transfer-user", "accessToken": jwt()}
        restored = A.Account(A.normalise_import_row(row))
        self.assertEqual(restored.product, "workbuddy")
        self.assertEqual(restored.proxy_slot, "")
        self.assertEqual(restored.proxy_legacy, "")
        self.assertTrue(restored.added_at)

    def test_dry_run_and_duplicate_policy_stay_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = A.AccountPool(directory)
            row = account().to_dict()
            preview = pool.preview_import_rows([row])
            self.assertEqual(preview["added"], [row["uid"]])
            self.assertEqual(pool.accounts, [])
            self.assertEqual(os.listdir(directory), [])
            pool.import_rows([row])
            replacement = dict(row, product="cli", proxySlot="slot-2", addedAt=1800000000)
            self.assertEqual(pool.import_rows([replacement])["skipped"][0]["reason"], "already exists")
            self.assertEqual(pool.get(row["uid"]).product, "vscode")
            report = pool.import_rows([replacement], overwrite=True)
            self.assertEqual(report["updated"], [row["uid"]])
            self.assertEqual(pool.get(row["uid"]).product, "cli")
            self.assertEqual(pool.get(row["uid"]).proxy_slot, "slot-2")
            # Replacing a known credential retains the target's creation time.
            self.assertEqual(pool.get(row["uid"]).added_at, 1700000000)

    def test_legacy_import_resets_transient_state_and_reenables_accounts(self):
        row = dict(account().to_dict(), enabled=False, cooldownUntil=4102444800,
                   lastError="old error", credits={"balance": 1}, lastCheckin={"old": True})
        normalized = A.normalise_import_row(row)
        restored = A.Account(normalized)
        self.assertTrue(restored.enabled)
        self.assertEqual(restored.cooldown_until, 0)
        self.assertEqual(restored.last_error, "")
        self.assertIsNone(restored.credits)
        self.assertIsNone(restored.last_checkin)

    def test_redacted_export_is_inspection_only_and_format_stays_v1(self):
        document = A.build_export_document([account()], include_secrets=False)
        self.assertEqual(document["format"], "workbuddy-accounts")
        self.assertEqual(document["version"], 1)
        self.assertNotIn("accessToken", document["accounts"][0])
        self.assertNotIn("refreshToken", document["accounts"][0])
        with self.assertRaisesRegex(ValueError, "no accessToken"):
            A.normalise_import_row(document["accounts"][0])


if __name__ == "__main__":
    unittest.main()
