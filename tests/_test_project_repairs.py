"""HTTP, rotation, auth and thread lifecycle regressions from the project audit."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_STARTUP = tempfile.TemporaryDirectory(prefix="wb-project-regressions-")
os.environ["ACCOUNTS_DIR"] = _STARTUP.name
os.environ["WB_PROXY_USAGE_DIR"] = _STARTUP.name
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import audit_project


class ProjectRepairTests(unittest.TestCase):
    def test_original_audit_scenarios(self):
        result = audit_project.probe()
        self.assertEqual(result["findings"], [])
        observed = result["observations"]
        self.assertEqual(observed["corrupt_settings"]["after"],
                         observed["corrupt_settings"]["before"])
        self.assertEqual(observed["retired_password_change"]["status"], 400)
        self.assertEqual(observed["wrong_current_password"]["status"], 400)
        self.assertTrue(observed["wrong_current_password"]["panel_session_still_valid"])
        for name in ("chat_message_null", "chat_model_list", "responses_tools_integer",
                     "responses_model_integer", "messages_messages_null", "chat_function_name_list",
                     "chat_tool_calls_integer", "responses_input_type_list", "chat_temperature_overflow"):
            self.assertEqual(observed["invalid_requests"][name]["status"], 400, name)
        self.assertEqual(observed["handler_exceptions"], [])
        self.assertTrue(observed["daily_usage_after_rotation"]["all_counters_preserved"])
        self.assertTrue(observed["daily_usage_after_rotation"]["restart_counters_preserved"])
        self.assertTrue(observed["daily_usage_after_rotation"]["incremental_append_preserved"])

    def test_unreadable_settings_without_a_snapshot_fail_closed(self):
        import tempfile
        import wb_settings
        with tempfile.TemporaryDirectory() as directory:
            Path(wb_settings.settings_path(directory)).write_text('{broken', encoding='utf-8')
            with self.assertRaises(wb_settings.SettingsError):
                wb_settings.load(directory)

    def test_deleting_the_final_panel_key_does_not_revive_launcher_key(self):
        import tempfile
        from unittest import mock
        import wb_settings as S
        import wb_proxy as P
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.multiple(P, ACCOUNTS_DIR=directory, API_KEY='AUDIT_RETIRED_ONLY'):
            S.set_api_keys(directory, [{'key':'AUDIT_CURRENT_ONLY', 'enabled':True}])
            S.set_api_keys(directory, [])
            self.assertTrue(P.auth_required())
            self.assertIsNone(P.identify_key('AUDIT_RETIRED_ONLY'))

    def test_invalid_key_list_keeps_the_trusted_auth_snapshot(self):
        import tempfile
        import wb_settings as S
        with tempfile.TemporaryDirectory() as directory:
            S.set_api_keys(directory, [{'key':'AUDIT_CURRENT_ONLY', 'enabled':True}])
            Path(S.settings_path(directory)).write_text('{"api_keys":42}', encoding='utf-8')
            self.assertIsNotNone(S.match_api_key(directory, 'AUDIT_CURRENT_ONLY'))


if __name__ == "__main__":
    unittest.main()
