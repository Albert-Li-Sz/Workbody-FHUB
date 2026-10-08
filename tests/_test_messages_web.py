"""Messages search orchestration, replay and failure accounting without live APIs."""
import copy
from contextlib import closing
from email.message import Message
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_RUNTIME = tempfile.TemporaryDirectory(prefix="wb-messages-web-")
os.environ["ACCOUNTS_DIR"] = _RUNTIME.name
os.environ["WB_PROXY_USAGE_DIR"] = _RUNTIME.name
import wb_database as D
import wb_messages_web as M
import wb_proxy as P
import wb_webtools as W

SOURCE = {"query": "synthetic query", "results": [{
    "url": "https://example.org/article", "title": "Synthetic source", "snippet": "Verified excerpt."}]}


def tool(name="web_search", call_id="server-1", arguments=None):
    return {"id": call_id, "type": "function", "function": {
        "name": name, "arguments": arguments or '{"query":"synthetic query"}'}}


def response(calls=None, text="", finish=None, output=3, usage=True):
    delta = {"content": text, "reasoning_content": "real upstream reasoning"}
    if calls:
        delta["tool_calls"] = [dict(copy.deepcopy(c), index=i) for i, c in enumerate(calls)]
    result = [{"id": "chatcmpl-search", "choices": [{"delta": delta}]},
              {"choices": [{"delta": {}, "finish_reason": finish or ("tool_calls" if calls else "stop")}]}]
    if usage:
        result[-1]["usage"] = {"prompt_tokens": 10, "completion_tokens": output, "total_tokens": 10 + output}
    return result


class Upstream:
    def __init__(self, chunks, done=True, broken=False):
        self.frames = [b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks]
        if done:
            self.frames.append(b"data: [DONE]\n\n")
        self.broken = broken
        self.closed = False

    def __iter__(self):
        yield from self.frames
        if self.broken:
            raise OSError("synthetic upstream disconnect")

    def close(self):
        self.closed = True


def events(raw):
    return [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith("data: {")]


class Handler:
    path = "/v1/messages"

    def __init__(self, sink=None):
        self.wfile = sink if sink is not None else io.BytesIO()

    def _key_id(self):
        return "synthetic-key-id"

    def _json(self, code, body):
        return code, body

    def _anthropic_error(self, code, message, *args):
        return code, {"type": "error", "error": {"message": message}}

    def send_response(self, *args):
        pass

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass


def run(chunks, stream=False, mode="native", max_tokens=100, max_uses=5, sink=None):
    upstreams = [c if isinstance(c, Upstream) else Upstream(c) for c in chunks]
    account = type("Account", (), {"uid": "stable-account"})()
    body = {"model": "deepseek-v4.1-flash", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": "question"}],
            "tools": [W.web_search_tool_def()], "_messages_web_search": {"max_uses": max_uses}}
    handler = Handler(sink)
    opened, logged, failed = [], [], []

    def open_round(payload, **kwargs):
        opened.append((copy.deepcopy(payload), kwargs))
        if len(opened) >= len(upstreams):
            raise AssertionError("unexpected upstream continuation")
        return upstreams[len(opened)], account, "high"

    with mock.patch.object(P, "open_upstream", side_effect=open_round), \
            mock.patch.object(P, "record_usage", side_effect=lambda m, u, **kw: logged.append((u, kw))), \
            mock.patch.object(P, "record_error", side_effect=lambda *a, **kw: failed.append(kw)), \
            mock.patch.object(W, "search_results", return_value=copy.deepcopy(SOURCE)) as search, \
            mock.patch.object(D, "DATABASE", None):
        flow = M.MessagesWebFlow(body, mode, "synthetic-key-id")
        method = P.Handler._messages_stream_response if stream else P.Handler._messages_nonstream_response
        result = method(handler, upstreams[0], body["model"], {}, account, time.time(),
                        base_body=body, session_key="session", realm="intl",
                        session_meta={"conversation_id": "session", "conversation_request_id": "same-turn"},
                        effort="high", web_flow=flow)
    return (events(handler.wfile.getvalue()) if stream else result), opened, logged, failed, search, upstreams


class FlowTests(unittest.TestCase):
    def test_nonstream_search_continuation_retains_reasoning_budget_account_and_usage(self):
        result, opened, logged, failed, search, upstreams = run([response([tool()]), response(text="Answer", output=7)])
        code, message = result
        self.assertEqual(code, 200)
        self.assertEqual([b["type"] for b in message["content"]],
                         ["server_tool_use", "web_search_tool_result", "text", "text"])
        self.assertEqual(message["content"][-1]["text"], "Answer")
        self.assertEqual(message["usage"]["output_tokens"], 10)
        self.assertEqual(message["usage"]["input_tokens"], 20)
        self.assertEqual(message["usage"]["server_tool_use"]["web_search_requests"], 1)
        follow, kwargs = opened[0]
        self.assertEqual(follow["max_tokens"], 97)
        self.assertEqual(follow["messages"][1]["reasoning_content"], "real upstream reasoning")
        self.assertEqual(follow["messages"][2]["tool_call_id"], "server-1")
        self.assertIn("Verified excerpt.", follow["messages"][2]["content"])
        self.assertEqual(kwargs["preferred_uid"], "stable-account")
        self.assertEqual(kwargs["session_meta"]["conversation_request_id"], "same-turn")
        self.assertEqual([r[0]["completion_tokens"] for r in logged], [3, 7])
        self.assertTrue(all(r[1]["account"] == "stable-account" for r in logged))
        self.assertTrue(all(r.closed for r in upstreams))
        self.assertEqual(failed, [])
        search.assert_called_once()

    def test_stream_has_one_lifecycle_contiguous_indexes_sources_and_cumulative_usage(self):
        frames, opened, logged, failed, _, upstreams = run([
            response([tool()], text="Searching. "), response(text="Answer", output=7)], stream=True)
        types = [f["type"] for f in frames]
        self.assertEqual(types.count("message_start"), 1)
        self.assertEqual(types.count("message_stop"), 1)
        self.assertEqual(types[-2:], ["message_delta", "message_stop"])
        starts = [f for f in frames if f["type"] == "content_block_start"]
        self.assertEqual([f["index"] for f in starts], list(range(len(starts))))
        self.assertEqual([f["index"] for f in frames if f["type"] == "content_block_stop"], list(range(len(starts))))
        self.assertIn("server_tool_use", [f["content_block"]["type"] for f in starts])
        self.assertIn("web_search_tool_result", [f["content_block"]["type"] for f in starts])
        citations = [f["delta"]["citation"] for f in frames if f.get("delta", {}).get("type") == "citations_delta"]
        self.assertEqual(citations[0]["cited_text"], "Verified excerpt.")
        self.assertEqual(frames[-2]["usage"]["output_tokens"], 10)
        self.assertEqual(opened[0][1]["preferred_uid"], "stable-account")
        self.assertEqual(len(logged), 2)
        self.assertEqual(failed, [])
        self.assertTrue(all(r.closed for r in upstreams))

    def test_text_compatibility_hides_server_blocks_for_both_response_modes(self):
        for stream in (False, True):
            result, _, _, failed, _, _ = run([response([tool()]), response(text="Answer")], stream=stream, mode="text")
            blocks = ([f["content_block"] for f in result if f["type"] == "content_block_start"]
                      if stream else result[1]["content"])
            self.assertEqual({b["type"] for b in blocks}, {"text"})
            visible = ("".join(f.get("delta", {}).get("text", "") for f in result)
                       if stream else "".join(b["text"] for b in blocks))
            self.assertIn("https://example.org/article", visible)
            self.assertIn("Answer", visible)
            self.assertEqual(failed, [])

    def test_mixed_calls_finish_local_search_then_return_client_tool_without_followup(self):
        for stream in (False, True):
            result, opened, logged, failed, search, _ = run([
                response([tool(), tool("Bash", "client-1", '{"cmd":"ls"}')])], stream=stream)
            blocks = ([f["content_block"] for f in result if f["type"] == "content_block_start"]
                      if stream else result[1]["content"])
            self.assertEqual(blocks[-1]["type"], "tool_use")
            self.assertEqual(blocks[-1]["name"], "Bash")
            self.assertEqual(blocks[-1]["id"], "client-1")
            stop = result[-2]["delta"]["stop_reason"] if stream else result[1]["stop_reason"]
            self.assertEqual(stop, "tool_use")
            self.assertEqual(opened, [])
            self.assertEqual(len(logged), 1)
            self.assertEqual(failed, [])
            search.assert_called_once()

    def test_max_uses_returns_error_for_extra_parallel_search_and_removes_search_tool(self):
        for stream in (False, True):
            result, opened, _, failed, search, _ = run([
                response([tool(call_id="one"), tool(call_id="two")]), response(text="Answer")],
                stream=stream, max_uses=1)
            blocks = ([f["content_block"] for f in result if f["type"] == "content_block_start"]
                      if stream else result[1]["content"])
            results = [b for b in blocks if b["type"] == "web_search_tool_result"]
            self.assertEqual(results[1]["content"]["error_code"], "max_uses_exceeded")
            self.assertEqual(opened[0][0]["tools"], [])
            self.assertEqual(opened[0][0]["tool_choice"], "auto")
            self.assertEqual(failed, [])
            search.assert_called_once()

    def test_max_tokens_budget_stops_after_search_without_another_model_call(self):
        for stream in (False, True):
            result, opened, _, failed, _, _ = run([response([tool()], output=3)], stream=stream, max_tokens=3)
            stop = result[-2]["delta"]["stop_reason"] if stream else result[1]["stop_reason"]
            self.assertEqual(stop, "max_tokens")
            self.assertEqual(opened, [])
            self.assertEqual(failed, [])

    def test_truncated_search_never_executes_in_stream_or_nonstream(self):
        for stream in (False, True):
            result, opened, logged, failed, search, _ = run([
                response([tool()], finish="length")], stream=stream)
            self.assertEqual(opened, [])
            search.assert_not_called()
            self.assertEqual(len(failed), 1)
            charged = [r[0] for r in logged] + [r.get("usage") for r in failed]
            self.assertEqual(sum((u or {}).get("total_tokens", 0) for u in charged), 13)
            if stream:
                self.assertEqual(result[-1]["type"], "error")
                self.assertNotIn("message_stop", [f["type"] for f in result])
            else:
                self.assertEqual(result[0], 502)

    def test_cancel_during_result_output_does_not_charge_finished_round_twice(self):
        class Disconnected(io.BytesIO):
            def write(self, value):
                if b'"web_search_tool_result"' in value:
                    raise BrokenPipeError("synthetic result cancellation")
                return super().write(value)
        _, opened, logged, failed, search, upstreams = run([
            response([tool()])], stream=True, sink=Disconnected())
        self.assertEqual(opened, [])
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0][0]["total_tokens"], 13)
        self.assertEqual(failed, [])
        search.assert_called_once()
        self.assertTrue(upstreams[0].closed)

    def test_each_round_cancels_its_read_timer_before_reusing_a_connection(self):
        for stream in (False, True):
            with mock.patch.object(M.wb_webflow.threading, "Timer") as timer:
                result, _, _, failed, _, _ = run([
                    response([tool()]), response(text="Answer")], stream=stream)
            self.assertEqual(timer.call_count, 2)
            self.assertEqual(timer.return_value.cancel.call_count, 2)
            self.assertEqual(failed, [])

    def test_eof_and_upstream_error_never_emit_a_successful_terminal_event(self):
        broken = [Upstream(response([tool()])[:1], done=False),
                  Upstream([{"usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
                             "error": {"message": "synthetic failure"}}], done=False)]
        for upstream in broken:
            for stream in (False, True):
                result, opened, logged, failed, search, _ = run([upstream], stream=stream)
                self.assertEqual(opened, [])
                self.assertEqual(logged, [])
                self.assertEqual(len(failed), 1)
                search.assert_not_called()
                if stream:
                    self.assertEqual(result[-1]["type"], "error")
                    self.assertNotIn("message_stop", [f["type"] for f in result])
                else:
                    self.assertEqual(result[0], 502)
                self.assertTrue(upstream.closed)

    def test_cancel_records_confirmed_partial_usage_once_and_closes_upstream(self):
        class Disconnected(io.BytesIO):
            def write(self, value):
                raise BrokenPipeError("synthetic client cancellation")
        chunks = [{"usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                   "choices": [{"delta": {"content": "partial"}}]}]
        _, _, logged, failed, search, upstreams = run([chunks], stream=True, sink=Disconnected())
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0][0]["total_tokens"], 7)
        self.assertEqual(logged[0][1]["outcome"], "client_aborted")
        self.assertEqual(failed, [])
        search.assert_not_called()
        self.assertTrue(upstreams[0].closed)

    def test_missing_usage_is_not_mistaken_for_confirmed_output_budget(self):
        result, opened, _, failed, _, _ = run([
            response([tool()], text="Unreported usage", usage=False), response(text="Answer")], max_tokens=5)
        self.assertEqual(result[0], 200)
        self.assertEqual(opened[0][0]["max_tokens"], 5)
        self.assertEqual(failed, [])


class TranslationTests(unittest.TestCase):
    def test_dsh_main_header_auto_selects_text_but_search_user_agent_does_not(self):
        headers = Message()
        headers["User-Agent"] = "deepseek-harness/0.0.1"
        self.assertEqual(M.response_format(headers), "native")
        headers["X-DeepSeek-Harness-User-Id"] = "synthetic-user"
        self.assertEqual(M.response_format(headers), "text")
        headers["X-FHUB-Web-Format"] = "native"
        self.assertEqual(M.response_format(headers), "native")
        headers.replace_header("X-FHUB-Web-Format", "wrong")
        with self.assertRaises(ValueError):
            M.response_format(headers)

    def test_native_options_validate_and_ordinary_search_named_function_stays_client_owned(self):
        options = M.search_options([{"type": "web_search_20250305", "name": "web_search", "max_uses": 2,
                                     "allowed_domains": ["EXAMPLE.ORG.", "example.org"]}])
        self.assertEqual(options, {"max_uses": 2, "allowed_domains": ["example.org"]})
        self.assertIsNone(M.search_options([{"name": "web_search", "input_schema": {"type": "object"}}]))
        for extra in ({"max_uses": 0}, {"max_uses": True}, {"type": "web_search_20260209"},
                      {"allowed_domains": ["https://example.org"]}, {"allowed_domains": [], "blocked_domains": []},
                      {"user_location": {"country": "CN"}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                M.search_options([dict({"type": "web_search_20250305", "name": "web_search"}, **extra)])
        payload = {"model": "synthetic", "messages": [{"role": "user", "content": "hi"}],
                   "tools": [{"name": "web_search", "input_schema": {"type": "object"}}]}
        with mock.patch.object(P, "local_web_tools_enabled", return_value=True):
            chat = P.messages_to_chat(payload)
        self.assertNotIn("_messages_web_search", chat)
        self.assertEqual(P.tool_name_of(chat["tools"][0]), "web_search")

    def test_domain_filter_enforces_hostname_boundary_after_backend_search(self):
        rows = [dict(SOURCE["results"][0], url="https://" + host + "/") for host in
                ("example.org", "docs.example.org", "notexample.org", "example.org.evil.net")]
        with mock.patch.object(W, "_cached_search", return_value=(rows, None)):
            allowed = W.search_results("synthetic query", allowed_domains=["example.org"])
            blocked = W.search_results("synthetic query", blocked_domains=["example.org"])
        self.assertEqual([r["url"] for r in allowed["results"]], ["https://example.org/", "https://docs.example.org/"])
        self.assertEqual([r["url"] for r in blocked["results"]], ["https://notexample.org/", "https://example.org.evil.net/"])

    def test_prefix_key_is_stable_without_system_and_with_multiple_system_messages(self):
        for prefix in ([{"role": "user", "content": "first"}],
                       [{"role": "system", "content": "one"}, {"role": "system", "content": "two"},
                        {"role": "user", "content": "first"}]):
            with mock.patch.object(P, "AFFINITY_BY_PREFIX", True):
                self.assertEqual(P.derive_affinity_key(prefix), P.derive_affinity_key(prefix + [
                    {"role": "assistant", "content": "reply"}, {"role": "user", "content": "second"}]))
        headers = Message()
        headers["X-DeepSeek-Harness-Session-Id"] = "synthetic-session"
        self.assertEqual(P.extract_session_key(headers, {}), "synthetic-session")


class ReplayTests(unittest.TestCase):
    def test_sqlite_restart_replay_pairs_calls_results_and_preserves_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "workbody.sqlite3")
            # Simulate an existing v1.1.0 database with no web_replay table.
            with closing(sqlite3.connect(path)) as old:
                old.execute("PRAGMA user_version=1")
            database = D.Database(path, directory, directory)
            with mock.patch.object(D, "DATABASE", database):
                reference = M._remember(SOURCE["results"][0], "key-one")
            database.close_thread()
            restored = D.Database(path, directory, directory)
            try:
                with mock.patch.object(D, "DATABASE", restored):
                    blocks = [{"type": "thinking", "thinking": "prior reasoning"},
                              M.call_block({"id": "s1", "arguments": '{"query":"synthetic query"}'}),
                              {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [{
                                  "type": "web_search_result", "url": SOURCE["results"][0]["url"],
                                  "title": "Synthetic source", "encrypted_content": reference}]},
                              {"type": "text", "text": "Answer", "citations": [{
                                  "url": SOURCE["results"][0]["url"], "cited_text": "Verified excerpt."}]}]
                    translated = P._anthropic_blocks_to_messages("assistant", blocks, "key-one")
                    self.assertEqual([m["role"] for m in translated], ["assistant", "tool", "assistant"])
                    self.assertEqual(translated[0]["reasoning_content"], "prior reasoning")
                    self.assertEqual(translated[0]["tool_calls"][0]["id"], translated[1]["tool_call_id"])
                    self.assertIn("Verified excerpt.", translated[1]["content"])
                    self.assertIn("https://example.org/article", translated[2]["content"])
                    with self.assertRaises(ValueError):
                        P._anthropic_blocks_to_messages("assistant", blocks, "key-two")
                    restored.connection().execute("UPDATE web_replay SET expires_at=0")
                    with self.assertRaises(ValueError):
                        M._recall(reference, "key-one")
            finally:
                restored.close_thread()

    def test_parallel_result_history_remains_a_contiguous_chat_tool_group(self):
        blocks = [M.call_block({"id": "s1"}), M.call_block({"id": "s2"})]
        for call_id in ("s1", "s2"):
            blocks += [{"type": "web_search_tool_result", "tool_use_id": call_id, "content": []},
                       {"type": "text", "text": "excerpt"}]
        translated = P._anthropic_blocks_to_messages("assistant", blocks)
        self.assertEqual([m["role"] for m in translated], ["assistant", "tool", "tool", "assistant"])
        with self.assertRaises(ValueError):
            P._anthropic_blocks_to_messages("assistant", [M.call_block({"id": "missing"})])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _RUNTIME.cleanup()
