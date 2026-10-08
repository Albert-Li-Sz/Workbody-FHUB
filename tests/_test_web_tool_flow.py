"""Regression coverage for the audited Responses orchestration failures."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.audit_web_tools import completion, run_nonstream, FakeAccount, FakeHandler
import wb_proxy as P
import wb_webtools as W


class NonstreamFlowTests(unittest.TestCase):
    def test_history_original_call_ids_and_all_usage_survive_multiple_rounds(self):
        status, result, opened, logged, executed = run_nonstream([
            completion("web_search", 3), completion("web_fetch", 5), completion(total=9)])
        self.assertEqual(status, 200)
        self.assertEqual([len(b["messages"]) for b in opened], [3, 5])
        self.assertEqual(opened[0]["messages"][1]["tool_calls"][0]["id"], "original-web_search")
        self.assertEqual([m.get("name") for m in opened[1]["messages"] if m["role"] == "tool"],
                         ["web_search", "web_fetch"])
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertEqual([u["total_tokens"] for u in logged], [3, 5, 9])

    def test_exact_hard_round_limit_refuses_further_model_calls(self):
        status, result, opened, logged, executed = run_nonstream(
            [completion("web_search")] * 6 + [completion()], max_rounds=1)
        self.assertEqual(status, 502)
        self.assertEqual(executed, ["web_search"])
        self.assertEqual(len(opened), 1)
        self.assertIn("limit", str(result).lower())

    def test_mixed_tools_return_client_call_and_local_results_without_followup(self):
        status, result, opened, logged, executed = run_nonstream([
            completion("web_search", extra_call=True), completion()])
        self.assertEqual(status, 200)
        calls = [item for item in result["output"] if item.get("type") == "function_call"]
        self.assertEqual([(c["name"], c["call_id"]) for c in calls], [("exec_command", "client-call")])
        self.assertIn("Synthetic source", result["output_text"])
        self.assertEqual(opened, [], "do not invent a result for a client-owned tool")
        self.assertEqual(executed, ["web_search"])

    def test_call_count_limit_rejects_an_oversized_batch_before_execution(self):
        batch = completion("web_search")
        call = batch["choices"][0]["message"]["tool_calls"][0]
        batch["choices"][0]["message"]["tool_calls"] = [dict(call, id="c%d" % i) for i in range(3)]
        with mock.patch.object(W, "MAX_WEB_CALLS", 2, create=True):
            status, _, opened, _, executed = run_nonstream([batch, completion()])
        self.assertEqual(status, 502)
        self.assertEqual(executed, [])
        self.assertEqual(opened, [])

    def test_expired_time_budget_refuses_tool_execution(self):
        with mock.patch.object(W, "MAX_WEB_TIME_SECONDS", -1):
            status, _, opened, _, executed = run_nonstream([completion("web_search"), completion()])
        self.assertEqual(status, 502)
        self.assertEqual(opened, [])
        self.assertEqual(executed, [])

    def test_initial_upstream_connection_consumes_the_same_request_budget(self):
        class EntryHandler(FakeHandler, P.Handler):
            def __init__(self):
                self.headers = {}

            def _request_realm(self):
                return "intl"

            def _cross_realm_error(self, *args):
                return None

            def _banned_model_error(self, *args):
                return None

            def _key_model_error(self, *args):
                return None

        body = {"model": "synthetic", "messages": [], "_web_tools": True}
        clock = [0]
        opened = []

        def connect(*args, **kwargs):
            opened.append(kwargs)
            clock[0] += 2
            return Upstream(completion("web_search") if len(opened) == 1 else completion()), FakeAccount(), None

        with mock.patch.object(P, "responses_to_chat", return_value=body), \
                mock.patch.object(P, "open_upstream", side_effect=connect), \
                mock.patch.object(P, "record_error"), mock.patch.object(P, "record_usage"), \
                mock.patch.object(P, "log"), mock.patch.object(W, "execute", return_value="Synthetic result") as execute, \
                mock.patch.object(W, "MAX_WEB_TIME_SECONDS", 1), \
                mock.patch.object(time, "monotonic", side_effect=lambda: clock[0]):
            status, _ = EntryHandler()._handle_responses({"model": "synthetic", "input": "synthetic"})
        self.assertEqual(status, 502)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["deadline"], 1)
        execute.assert_not_called()

    def test_usage_is_charged_to_each_actual_upstream_account(self):
        documents = [completion("web_search", 3), completion("web_fetch", 5), completion(total=9)]
        responses = [Upstream(d) for d in documents]
        accounts = [type("Account", (), {"uid": "round-%d" % i})() for i in range(3)]
        upcoming = iter(zip(responses[1:], accounts[1:]))
        recorded = []
        body = {"messages": [{"role": "user", "content": "synthetic"}], "_web_tools": True,
                "tools": [W.web_search_tool_def(), W.web_fetch_tool_def()]}
        with mock.patch.object(P, "open_upstream", side_effect=lambda *a, **kw: (*next(upcoming), None)), \
                mock.patch.object(P, "record_usage", side_effect=lambda m, u, **kw: recorded.append((kw["account"], u["total_tokens"]))), \
                mock.patch.object(P, "record_error") as errors, \
                mock.patch.object(W, "execute", return_value="Synthetic result"):
            status, result = P.Handler._responses_nonstream_response(FakeHandler(), responses[0],
                "synthetic", set(), {}, "fp", accounts[0], time.time(), base_body=body, realm="intl")
        self.assertEqual(status, 200)
        self.assertEqual(recorded, [("round-0", 3), ("round-1", 5), ("round-2", 9)])
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertTrue(all(r.closed for r in responses))
        errors.assert_not_called()

    def test_partial_usage_is_recorded_when_the_upstream_fails(self):
        class Broken(Upstream):
            def __iter__(self):
                yield from self.frames[:2]
                raise OSError("synthetic disconnect")
        response = Broken(completion(total=7))
        body = {"messages": [], "_web_tools": True}
        with mock.patch.object(P, "record_error") as error, mock.patch.object(P, "record_usage") as usage:
            status, _ = P.Handler._responses_nonstream_response(FakeHandler(), response, "synthetic",
                set(), {}, "fp", FakeAccount(), time.time(), base_body=body)
        self.assertEqual(status, 502)
        self.assertEqual(error.call_args.kwargs["usage"]["total_tokens"], 7)
        usage.assert_not_called()
        self.assertTrue(response.closed)


class Upstream:
    def __init__(self, document):
        message = document["choices"][0]["message"]
        delta = dict(message)
        for i, call in enumerate(delta.get("tool_calls") or []):
            call["index"] = i
        self.frames = [
            b'data: ' + json.dumps({"choices": [{"delta": delta}]}).encode() + b'\n',
            b'data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                     "usage": document["usage"]}).encode() + b'\n',
            b'data: [DONE]\n',
        ]
        self.closed = False

    def __iter__(self):
        return iter(self.frames)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class StreamHandler:
    path = "/v1/responses"

    def __init__(self):
        self.wfile = io.BytesIO()

    def _key_id(self):
        return None

    def send_response(self, *args):
        pass

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass


def run_stream(documents, max_rounds=3):
    responses = [Upstream(d) for d in documents]
    opened, logged, errors, executed = [], [], [], []
    handler = StreamHandler()
    body = {"messages": [{"role": "user", "content": "synthetic"}], "_web_tools": True,
            "tools": [W.web_search_tool_def(), W.web_fetch_tool_def()]}

    def follow(body, **kwargs):
        opened.append(json.loads(json.dumps(body)))
        return responses[len(opened)], FakeAccount(), None

    def execute(name, args):
        executed.append(name)
        return "Search results for: synthetic\n\n1. Synthetic source\n   https://example.com/\n   Snippet."

    with tempfile.TemporaryDirectory() as directory, \
            mock.patch.multiple(P, ACCOUNTS_DIR=directory, API_KEY=None, POOL=None), \
            mock.patch.object(P, "open_upstream", side_effect=follow), \
            mock.patch.object(P, "record_usage", side_effect=lambda model, usage, **kw: logged.append(usage)), \
            mock.patch.object(P, "record_error", side_effect=lambda *a, **kw: errors.append(kw)), \
            mock.patch.object(P, "log"), mock.patch.object(W, "execute", side_effect=execute), \
            mock.patch.object(W, "MAX_WEB_ROUNDS", max_rounds):
        P.Handler._responses_stream_response(handler, responses[0], "synthetic-model", set(), {},
            "synthetic-fp", FakeAccount(), time.time(), base_body=body, realm="intl")
    events = []
    for line in handler.wfile.getvalue().decode().splitlines():
        if line.startswith("data: {"):
            events.append(json.loads(line[6:]))
    return events, opened, logged, errors, executed, responses


class StreamFlowTests(unittest.TestCase):
    def test_search_completed_event_is_emitted_only_after_backend_returns(self):
        handler = StreamHandler()
        body = {"messages": [], "_web_tools": True, "tools": [W.web_search_tool_def()]}
        snapshots = []

        def execute(*args):
            snapshots.append(handler.wfile.getvalue().decode())
            return "Search results for: synthetic\n\n1. Source\n   https://example.org/\n   Snippet."

        with mock.patch.object(P, "open_upstream", return_value=(Upstream(completion()), FakeAccount(), None)), \
                mock.patch.object(P, "record_usage"), mock.patch.object(P, "record_error") as error, \
                mock.patch.object(W, "execute", side_effect=execute):
            P.Handler._responses_stream_response(handler, Upstream(completion("web_search")),
                "synthetic", set(), {}, "fp", FakeAccount(), time.time(), base_body=body)
        self.assertEqual(len(snapshots), 1)
        self.assertIn("response.web_search_call.searching", snapshots[0])
        self.assertNotIn("response.web_search_call.completed", snapshots[0])
        self.assertIn("response.web_search_call.completed", handler.wfile.getvalue().decode())
        error.assert_not_called()

    def test_failed_terminal_usage_includes_the_partially_received_round(self):
        class Broken(Upstream):
            def __iter__(self):
                yield from self.frames[:2]
                raise OSError("synthetic disconnect")

        responses = [Upstream(completion("web_search", 3)), Broken(completion(total=7))]
        handler = StreamHandler()
        body = {"messages": [], "_web_tools": True, "tools": [W.web_search_tool_def()]}
        with mock.patch.object(P, "open_upstream", return_value=(responses[1], FakeAccount(), None)), \
                mock.patch.object(P, "record_usage"), mock.patch.object(P, "record_error") as error, \
                mock.patch.object(W, "execute", return_value="Synthetic result"):
            P.Handler._responses_stream_response(handler, responses[0], "synthetic", set(), {},
                "fp", FakeAccount(), time.time(), base_body=body)
        events = [json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                  if line.startswith("data: {")]
        failed = next(event["response"] for event in events if event["type"] == "response.failed")
        self.assertEqual(failed["usage"]["total_tokens"], 10)
        self.assertEqual(error.call_args.kwargs["usage"]["total_tokens"], 7)
        self.assertTrue(all(response.closed for response in responses))

    def test_history_final_usage_and_per_round_accounting(self):
        events, opened, logged, _, _, responses = run_stream([
            completion("web_search", 3), completion("web_fetch", 5), completion(total=9)])
        self.assertEqual([len(b["messages"]) for b in opened], [3, 5])
        final = [e for e in events if e["type"] == "response.completed"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["response"]["usage"]["total_tokens"], 17)
        self.assertEqual([u["total_tokens"] for u in logged], [3, 5, 9])
        self.assertTrue(all(r.closed for r in responses))
        ids = [e["response"]["id"] for e in events if "response" in e]
        self.assertEqual(len(set(ids)), 1)
        sequence = [e["sequence_number"] for e in events]
        self.assertEqual(sequence, sorted(set(sequence)))

    def test_hard_limit_emits_failed_terminal_event(self):
        events, opened, _, _, executed, responses = run_stream(
            [completion("web_search")] * 6 + [completion()], max_rounds=1)
        self.assertEqual(executed, ["web_search"])
        self.assertEqual(len(opened), 1)
        self.assertEqual([e["type"] for e in events if e["type"] in ("response.failed", "response.completed")],
                         ["response.failed"])
        self.assertTrue(responses[1].closed)

    def test_mixed_calls_are_delivered_once_with_local_results(self):
        events, opened, _, _, executed, _ = run_stream([
            completion("web_search", extra_call=True), completion()])
        final = [e for e in events if e["type"] == "response.completed"][-1]["response"]
        calls = [i for i in final["output"] if i.get("type") == "function_call"]
        self.assertEqual([(c["name"], c["call_id"]) for c in calls], [("exec_command", "client-call")])
        self.assertIn("Synthetic source", final["output_text"])
        self.assertEqual(opened, [])
        self.assertEqual(executed, ["web_search"])


if __name__ == "__main__":
    unittest.main()
