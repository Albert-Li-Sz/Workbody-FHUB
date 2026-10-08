"""Prompt modes (B3): passthrough / custom / append and the degrade window.

Run with: python _test_prompt_modes.py
No upstream credentials or outbound network are used.
"""
import datetime
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

_startup_dir = tempfile.TemporaryDirectory(prefix="prompt-modes-")
os.environ["ACCOUNTS_DIR"] = _startup_dir.name
os.environ["WB_PROXY_USAGE_DIR"] = _startup_dir.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wb_accounts
import wb_prompt
import wb_proxy
import wb_settings

CST = datetime.timezone(datetime.timedelta(hours=8))


class PromptTextTests(unittest.TestCase):
    def test_rewrite_replaces_every_system_and_developer(self):
        messages = [{"role": "system", "content": "client-a"},
                    {"role": "user", "content": "hi"},
                    {"role": "developer", "content": "client-b"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "tool", "tool_call_id": "c1", "content": "r"}]
        out = wb_prompt.rewrite(messages, "GATEWAY")
        self.assertEqual(out[0], {"role": "system", "content": "GATEWAY"})
        self.assertEqual([m["role"] for m in out[1:]],
                         ["user", "assistant", "tool"])

    def test_append_keeps_client_messages_and_inserts_after_the_leading_block(self):
        messages = [{"role": "system", "content": "client-a"},
                    {"role": "developer", "content": "client-b"},
                    {"role": "user", "content": "hi"}]
        out = wb_prompt.append(messages, "GATEWAY")
        self.assertEqual([m["content"] for m in out[:3]],
                         ["client-a", "client-b", "GATEWAY"])
        self.assertEqual(out[3], {"role": "user", "content": "hi"})

    def test_append_without_a_leading_block_inserts_first(self):
        out = wb_prompt.append([{"role": "user", "content": "hi"}], "GATEWAY")
        self.assertEqual(out[0], {"role": "system", "content": "GATEWAY"})
        self.assertEqual(out[1], {"role": "user", "content": "hi"})

    def test_apply_mode_routing(self):
        messages = [{"role": "system", "content": "client"},
                    {"role": "user", "content": "hi"}]
        self.assertIs(wb_prompt.apply_mode(messages, "passthrough", "GW"), messages)
        custom = wb_prompt.apply_mode(messages, "custom", "GW")
        self.assertEqual(custom[0]["content"], "GW")
        self.assertNotIn("client", [m.get("content") for m in custom])
        appended = wb_prompt.apply_mode(messages, "append", "GW")
        self.assertEqual([m["content"] for m in appended[:2]], ["client", "GW"])

    def test_degraded_routing_only_touches_passthrough_and_append(self):
        messages = [{"role": "system", "content": "client"},
                    {"role": "user", "content": "hi"}]
        passthrough = wb_prompt.apply_mode(messages, "passthrough", "", degraded=True)
        self.assertEqual(passthrough[0]["content"], wb_prompt.DEGRADED_PROMPT)
        appended = wb_prompt.apply_mode(messages, "append", "GW", degraded=True)
        self.assertEqual(appended[0]["content"], wb_prompt.DEGRADED_PROMPT)
        custom = wb_prompt.apply_mode(messages, "custom", "GW", degraded=True)
        self.assertEqual(custom[0]["content"], "GW")


class PromptSettingsTests(unittest.TestCase):
    def test_defaults_are_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(wb_settings.prompt_config(directory),
                             {"mode": "passthrough", "file": "", "retry_on_content_rejection": False})

    def test_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom"})
            self.assertEqual(wb_settings.prompt_config(directory)["mode"], "custom")
            wb_settings.set_prompt_config(directory, {"file": " C:/p.txt "})
            cfg = wb_settings.prompt_config(directory)
            self.assertEqual(cfg["mode"], "custom")
            self.assertEqual(cfg["file"], "C:/p.txt")
        for bad in ({"mode": "weird"}, {"mode": 1}, {"file": 2}, {"nope": 1}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                wb_settings.validate_prompt_patch(bad)

    def test_lenient_load(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(wb_settings.settings_path(directory), "w", encoding="utf-8") as fh:
                json.dump({"prompt": {"mode": "BOGUS", "file": 7}}, fh)
            self.assertEqual(wb_settings.prompt_config(directory),
                             {"mode": "passthrough", "file": "", "retry_on_content_rejection": False})
        with tempfile.TemporaryDirectory() as directory:
            with open(wb_settings.settings_path(directory), "w", encoding="utf-8") as fh:
                json.dump({"prompt": []}, fh)
            self.assertEqual(wb_settings.prompt_config(directory)["mode"], "passthrough")


class BuildBodyPromptTests(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def build(self, directory, messages, **extra):
        payload = {"model": "deepseek-v4.1-flash", "messages": messages}
        payload.update(extra)
        degraded = payload.pop("prompt_degraded", False)
        with mock.patch.object(wb_proxy, "ACCOUNTS_DIR", directory):
            return wb_proxy.build_upstream_body(payload, prompt_degraded=degraded)

    def test_passthrough_keeps_the_client_system_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            body = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], "CLIENT-SYS")

    def test_custom_replaces_the_client_system_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom"})
            body = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], wb_prompt.DEFAULT_PROMPT)
        self.assertNotIn("CLIENT-SYS", json.dumps(body["messages"]))

    def test_append_keeps_both_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "append"})
            body = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}])
        self.assertEqual([m["content"] for m in body["messages"][:2]],
                         ["CLIENT-SYS", wb_prompt.DEFAULT_PROMPT])

    def test_custom_file_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "prompt.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("FILE-PROMPT")
            wb_settings.set_prompt_config(directory, {"mode": "custom", "file": path})
            body = self.build(directory, [{"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], "FILE-PROMPT")

    def test_missing_file_fails_open_to_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {
                "mode": "custom", "file": os.path.join(directory, "nope.txt")})
            body = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], "CLIENT-SYS")

    def test_request_retry_replaces_passthrough_and_append(self):
        with tempfile.TemporaryDirectory() as directory:
            body = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}], prompt_degraded=True)
            self.assertEqual(body["messages"][0]["content"], wb_prompt.DEGRADED_PROMPT)
            wb_settings.set_prompt_config(directory, {"mode": "append"})
            body2 = self.build(directory, [
                {"role": "system", "content": "CLIENT-SYS"},
                {"role": "user", "content": "hi"}], prompt_degraded=True)
            self.assertEqual(body2["messages"][0]["content"], wb_prompt.DEGRADED_PROMPT)
            self.assertNotIn("CLIENT-SYS", json.dumps(body2["messages"]))

    def test_request_retry_leaves_custom_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom"})
            body = self.build(directory, [{"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], wb_prompt.DEFAULT_PROMPT)


class DegradedRetryTests(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def make_pool(self, account):
        class Pool(object):
            accounts = [account]
            affinity = type("Affinity", (), {"unbind": lambda self, key: None})()

            def count_ready(self, realm, model=None):
                return 1

            def pick_for_session(self, realm, session_key=None, exclude=(),
                                 model=None):
                return account

            def list_public(self):
                return []

            def reserve_for_session(self, payload, realm=None, session_key=None, exclude=(), model=None, estimate=None, preferred_uid=None):
                chosen = self.pick_for_session(realm, session_key, exclude, model)
                return (chosen, None) if chosen and chosen.acquire() else (None, None)

            def apply_daily_token_limit(self, value=None, usage=None):
                return value or 0

            def apply_daily_credit_limit(self, value=None, credits=None, free_models=None):
                return value or 0

            def apply_model_daily_token_limit(self, value=None, per_model=None):
                return value or 0

        return Pool()

    def test_opt_in_content_rejection_retries_only_the_current_request(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"retry_on_content_rejection": True})
            account = wb_accounts.Account(
                {"uid": "uid-b3", "accessToken": "t", "realm": "intl"},
                os.path.join(directory, "uid-b3.json"))
            bodies = []

            class Response(object):
                def close(self):
                    pass

            def fake_urlopen(req, timeout=30, proxy=""):
                bodies.append(json.loads(req.data.decode("utf-8")))
                if len(bodies) == 1:
                    raise urllib.error.HTTPError(
                        "https://upstream.invalid", 403, "forbidden", {},
                        io.BytesIO(b'{"error":{"code":11140,"message":"content rejected"}}'))
                return Response()

            old_pool, old_urlopen = wb_proxy.POOL, wb_accounts.urlopen
            wb_proxy.POOL = self.make_pool(account)
            wb_accounts.urlopen = fake_urlopen
            try:
                with mock.patch.object(wb_proxy, "ACCOUNTS_DIR", directory):
                    upstream, _account, _effort = wb_proxy.open_upstream(
                        {"model": "deepseek-v4.1-flash",
                         "messages": [{"role": "system", "content": "CLIENT-SYS"},
                                      {"role": "user", "content": "hi"}]},
                        session_key="conv-b3", target_realm="intl")
                    upstream.close()
                    self.assertIn("CLIENT-SYS", json.dumps(wb_proxy.build_upstream_body({"model":"deepseek-v4.1-flash", "messages":[{"role":"system","content":"CLIENT-SYS"},{"role":"user","content":"next"}]})))
            finally:
                wb_proxy.POOL = old_pool
                wb_accounts.urlopen = old_urlopen

            self.assertEqual(len(bodies), 2)
            self.assertIn("CLIENT-SYS", json.dumps(bodies[0]["messages"]))
            self.assertIn(wb_prompt.DEGRADED_PROMPT, json.dumps(bodies[1]["messages"]))
            self.assertNotIn("CLIENT-SYS", json.dumps(bodies[1]["messages"]))

    def test_custom_mode_does_not_degrade(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom"})
            account = wb_accounts.Account(
                {"uid": "uid-b3c", "accessToken": "t", "realm": "intl"},
                os.path.join(directory, "uid-b3c.json"))
            calls = []

            def fake_urlopen(req, timeout=30, proxy=""):
                calls.append(req)
                raise urllib.error.HTTPError(
                    "https://upstream.invalid", 403, "forbidden", {},
                    io.BytesIO(b'{"error":{"code":11140,"message":"content rejected"}}'))

            old_pool, old_urlopen = wb_proxy.POOL, wb_accounts.urlopen
            wb_proxy.POOL = self.make_pool(account)
            wb_accounts.urlopen = fake_urlopen
            try:
                with mock.patch.object(wb_proxy, "ACCOUNTS_DIR", directory):
                    with self.assertRaises(wb_proxy.ContentRejected):
                        wb_proxy.open_upstream(
                            {"model": "deepseek-v4.1-flash",
                             "messages": [{"role": "user", "content": "hi"}]},
                            session_key="conv-b3c", target_realm="intl")
            finally:
                wb_proxy.POOL = old_pool
                wb_accounts.urlopen = old_urlopen
            self.assertEqual(len(calls), 1)



if __name__ == "__main__":
    unittest.main()
