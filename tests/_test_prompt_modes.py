"""Prompt modes (B3): passthrough / custom / append and the degrade window.

Run with: python _test_prompt_modes.py
No upstream credentials or outbound network are used.
"""
import datetime
import copy
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

    def test_native_responses_replace_all_instruction_sources_without_mutation(self):
        payload = {"instructions": "TOP", "input": [
            {"role": "system", "content": "FIRST"},
            {"role": "user", "content": "hi"},
            {"type": "reasoning", "encrypted_content": "opaque"},
            {"role": "developer", "content": [{"type": "input_text", "text": "LATE"}]}]}
        before = copy.deepcopy(payload)
        out = wb_prompt.apply_payload(payload, "responses", "custom", "GW")
        self.assertEqual(out["instructions"], "GW")
        self.assertEqual(out["input"], before["input"][1:3])
        self.assertEqual(payload, before)

    def test_native_responses_append_preserves_instructions_and_opaque_items(self):
        payload = {"instructions": " TOP \n", "input": [
            {"role": "developer", "content": "FIRST"},
            {"type": "function_call_output", "call_id": "c", "output": "result"}]}
        before = copy.deepcopy(payload)
        out = wb_prompt.apply_payload(payload, "responses", "append", "GW")
        self.assertEqual(out["instructions"], before["instructions"])
        self.assertEqual(out["input"][0], before["input"][0])
        self.assertEqual(out["input"][1]["content"], "GW")
        self.assertEqual(out["input"][2], before["input"][1])
        self.assertEqual(payload, before)
        string = {"instructions": "TOP", "input": " hello \n"}
        out = wb_prompt.apply_payload(string, "responses", "append", "GW")
        self.assertEqual(out["input"][-1]["content"], string["input"])

    def test_native_messages_preserves_cache_and_signed_blocks(self):
        payload = {"system": [{"type": "text", "text": "CLIENT", "cache_control": {"type": "ephemeral"}}],
                   "messages": [{"role": "assistant", "content": [{"type": "thinking", "thinking": "trace", "signature": "opaque"}]},
                                {"role": "user", "content": "hi"}]}
        before = copy.deepcopy(payload)
        self.assertIs(wb_prompt.apply_payload(payload, "messages", "passthrough", "GW"), payload)
        out = wb_prompt.apply_payload(payload, "messages", "append", "GW")
        self.assertEqual(out["system"], before["system"] + [{"type": "text", "text": "GW"}])
        self.assertEqual(out["messages"], before["messages"])
        custom = wb_prompt.apply_payload(payload, "messages", "custom", "GW")
        self.assertEqual(custom["system"], "GW")
        self.assertEqual(custom["messages"], before["messages"])
        self.assertEqual(payload, before)

    def test_append_does_not_remove_later_instruction_messages_or_mutate_history(self):
        payload = {"messages": [{"role": "user", "content": "hi"},
                                {"role": "developer", "content": "LATE"}]}
        before = copy.deepcopy(payload)
        out = wb_prompt.apply_payload(payload, "chat", "append", "GW")
        self.assertEqual(out["messages"][1:], before["messages"])
        self.assertEqual(payload, before)


class PromptSettingsTests(unittest.TestCase):
    def test_defaults_are_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(wb_settings.prompt_config(directory),
                             dict(wb_settings.PROMPT_DEFAULTS))

    def test_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom"})
            self.assertEqual(wb_settings.prompt_config(directory)["mode"], "custom")
            wb_settings.set_prompt_config(directory, {"file": " C:/p.txt "})
            cfg = wb_settings.prompt_config(directory)
            self.assertEqual(cfg["mode"], "custom")
            self.assertEqual(cfg["file"], "C:/p.txt")
        for bad in ({"mode": "weird"}, {"mode": 1}, {"file": 2}, {"nope": 1},
                    {"text": 2}, {"text": " \n"}, {"text": "中" * wb_prompt.MAX_PROMPT_BYTES}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                wb_settings.validate_prompt_patch(bad)

    def test_lenient_load(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(wb_settings.settings_path(directory), "w", encoding="utf-8") as fh:
                json.dump({"prompt": {"mode": "BOGUS", "file": 7}}, fh)
            self.assertEqual(wb_settings.prompt_config(directory),
                             dict(wb_settings.PROMPT_DEFAULTS))
        with tempfile.TemporaryDirectory() as directory:
            with open(wb_settings.settings_path(directory), "w", encoding="utf-8") as fh:
                json.dump({"prompt": []}, fh)
            self.assertEqual(wb_settings.prompt_config(directory)["mode"], "passthrough")

    def test_markdown_text_roundtrip_preserves_whitespace_and_partial_updates(self):
        text = "  # 助手\n\n```python\nprint('OK')\n```\n\n"
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom", "text": text})
            wb_settings.set_prompt_config(directory, {"retry_on_content_rejection": True})
            self.assertEqual(wb_settings.prompt_config(directory)["text"], text)
            self.assertEqual(wb_prompt.load_prompt("custom", text=text), text)
            wb_settings.set_prompt_config(directory, {"text": ""})
            self.assertEqual(wb_prompt.preview(wb_settings.prompt_config(directory))["text"], wb_prompt.DEFAULT_PROMPT)

    def test_file_priority_bom_and_read_errors_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "prompt.md")
            with open(path, "wb") as fh:
                fh.write(b"\xef\xbb\xbf# File\r\n\r\n- rule\r\n")
            cfg = {"mode": "append", "file": path, "text": "INLINE"}
            status = wb_prompt.preview(cfg)
            self.assertEqual(status["text"], "# File\r\n\r\n- rule\r\n")
            self.assertEqual(status["source"], "file")
            self.assertTrue(status["active"])
            for data in (b" \r\n", b"\xff", b"x" * (wb_prompt.MAX_PROMPT_BYTES + 1)):
                with open(path, "wb") as fh:
                    fh.write(data)
                status = wb_prompt.preview(cfg)
                self.assertTrue(status["error"])
                self.assertFalse(status["active"])
                self.assertEqual(status["text"], "")


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

    def test_inline_markdown_goes_upstream_as_source_text(self):
        text = "# 助手\n\n- **验证**\n\n```text\n<rule>\n```\n"
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "custom", "text": text})
            payload = [{"role": "developer", "content": "CLIENT"}, {"role": "user", "content": "hi"}]
            body = self.build(directory, payload)
        self.assertEqual(body["messages"][0]["content"], text)
        self.assertEqual(payload[0]["content"], "CLIENT")

    def test_passthrough_does_not_load_a_configured_file(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"file": "missing.md", "text": "INLINE"})
            with mock.patch.object(wb_prompt, "load_prompt", side_effect=AssertionError("must not load")):
                body = self.build(directory, [{"role": "system", "content": "CLIENT"}, {"role": "user", "content": "hi"}])
        self.assertEqual(body["messages"][0]["content"], "CLIENT")

    def test_retry_is_independent_of_an_unreadable_append_file(self):
        with tempfile.TemporaryDirectory() as directory:
            wb_settings.set_prompt_config(directory, {"mode": "append", "file": os.path.join(directory, "missing.md")})
            body = self.build(directory, [{"role": "system", "content": "CLIENT"}, {"role": "user", "content": "hi"}], prompt_degraded=True)
        self.assertEqual(body["messages"][0]["content"], wb_prompt.DEGRADED_PROMPT)

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
