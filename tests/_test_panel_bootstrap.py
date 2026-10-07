"""Fresh panels have no guessable default; existing strong passwords survive."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_settings as S


class PanelBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_fresh_install_does_not_accept_admin_before_bootstrap(self):
        self.assertFalse(S.verify_panel_password(self.temp.name, "admin"))

    def test_bootstrap_generates_one_persisted_hash_and_keeps_existing_password(self):
        password = S.ensure_panel_password(self.temp.name)
        self.assertGreaterEqual(len(password), 24)
        self.assertTrue(S.verify_panel_password(self.temp.name, password))
        self.assertFalse(S.verify_panel_password(self.temp.name, "admin"))
        self.assertNotIn(password, str(S.load(self.temp.name)))
        self.assertIsNone(S.ensure_panel_password(self.temp.name))
        self.assertTrue(S.verify_panel_password(self.temp.name, password))

    def test_legacy_default_is_replaced_but_custom_password_is_preserved(self):
        S.save(self.temp.name, {"panel_password_default": True, "panel_password_hash": ""})
        self.assertIsNotNone(S.ensure_panel_password(self.temp.name))
        S.set_panel_password(self.temp.name, "synthetic-strong-existing-password")
        self.assertIsNone(S.ensure_panel_password(self.temp.name))
        self.assertTrue(S.verify_panel_password(self.temp.name, "synthetic-strong-existing-password"))

    def test_admin_cannot_be_set_as_a_new_password(self):
        with self.assertRaises(ValueError):
            S.set_panel_password(self.temp.name, "admin")


if __name__ == "__main__":
    unittest.main()
