"""Generation speed uses matching output tokens and generation durations."""
import json
import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.TemporaryDirectory(prefix="wb-speed-")
os.environ["ACCOUNTS_DIR"] = os.path.join(_TMP.name, "accounts")
os.environ["WB_PROXY_USAGE_DIR"] = _TMP.name

import wb_proxy as P


class GenerationSpeedTests(unittest.TestCase):
    def write_rows(self, rows):
        with open(P.USAGE_LOG, "w", encoding="utf-8") as sink:
            for row in rows:
                sink.write(json.dumps(row) + "\n")

    def test_gateway_speed_weights_generation_time(self):
        rows = [
            {"at": 100, "model": "test-model", "account": "synthetic-cn",
             "realm": "cn", "outcome": "completed", "stream": True,
             "completion_tokens": 100, "gen_ms": 1000, "tokens_per_sec": 100},
            {"at": 200, "model": "test-model", "account": "synthetic-cn",
             "realm": "cn", "outcome": "completed", "stream": True,
             "completion_tokens": 100, "gen_ms": 10000, "tokens_per_sec": 10},
        ]
        self.write_rows(rows)
        analytics = P.compute_usage_analytics(ttl=0, range="all")
        actual = analytics["summary"]["window"]["speed_avg"]
        # 200 output tokens / 11 s, rather than the 55 tok/s mean of two rates.
        self.assertEqual(actual, 18.2)
        self.assertEqual(analytics["accounts"][0]["window"]["speed_avg"], 18.2)
        perf = P.perf_stats(ttl=0, realm="all", range="all")
        for block in (perf["tokens_per_sec"], perf["by_model"]["test-model"]["tokens_per_sec"],
                      perf["by_model_realm"]["test-model"]["cn"]["tokens_per_sec"],
                      perf["by_model_acct"]["test-model"]["cn"]["synthetic-cn"]["tokens_per_sec"]):
            self.assertEqual(block["avg"], 18.2)
            self.assertEqual(block["samples"], 2)

    def test_invalid_and_partial_rows_do_not_affect_generation_speed(self):
        base = {"at": 100, "model": "test", "completion_tokens": 100,
                "gen_ms": 1000, "tokens_per_sec": 999999, "outcome": "completed"}
        rows = [dict(base)]
        for patch in ({"gen_ms": None}, {"gen_ms": 0}, {"gen_ms": -1},
                      {"gen_ms": float("nan")}, {"gen_ms": float("inf")},
                      {"completion_tokens": None}, {"completion_tokens": True},
                      {"completion_tokens": 0}, {"usage_missing": True},
                      {"outcome": "failed"}, {"outcome": "upstream_aborted"},
                      {"outcome": "client_aborted"}):
            rows.append(dict(base, **patch))
        self.write_rows(rows)
        stat = P.compute_usage_analytics(ttl=0, range="all")["summary"]["window"]
        self.assertEqual(stat["speed_n"], 1)
        self.assertEqual(stat["speed_avg"], 100)
        self.assertEqual(P.perf_stats(ttl=0, realm="all")["tokens_per_sec"]["avg"], 100)
        self.write_rows(rows[1:])
        self.assertIsNone(P.compute_usage_analytics(ttl=0, range="all")["summary"]["window"]["speed_avg"])

    def test_single_frame_is_unknown_but_reasoning_and_tool_arguments_are_timed(self):
        timing = P.wb_metrics.GenerationTiming(100)
        with mock.patch.object(P.time, "time", return_value=101):
            timing.observe({"choices": [{"delta": {"reasoning_content": "think"}}]})
        self.assertIsNone(timing.fields()["gen_ms"])
        with mock.patch.object(P.time, "time", return_value=103):
            timing.observe({"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "{}"}}]}}]})
        self.assertEqual(timing.fields(), {"ttft_ms": 1000, "gen_ms": 2000})

    def test_every_protocol_times_generated_content(self):
        class Handler(P.Handler):
            def __init__(self):
                self.wfile = io.BytesIO()
                self.headers = {}
                self.path = "/v1/chat/completions"

            def send_response(self, *args): pass
            def send_header(self, *args): pass
            def end_headers(self): pass
            def _key_id(self): return "synthetic"
            def _json(self, status, payload): self.response = (status, payload)

        for protocol in ("chat", "messages", "responses"):
            for streaming in (False, True):
                with self.subTest(protocol=protocol, streaming=streaming):
                    clock = [1000.0]
                    class Upstream:
                        def __iter__(self):
                            chunks = [
                                (1000.1, {"choices": [{"delta": {"role": "assistant"}}]}),
                                (1001.0, {"choices": [{"delta": {"content": "hello"}}]}),
                                (1003.0, {"choices": [{"delta": {"content": " world"}}]}),
                                (1008.0, {"choices": [{"delta": {}, "finish_reason": "stop"}],
                                          "usage": {"prompt_tokens": 10, "completion_tokens": 100,
                                                    "total_tokens": 110}}),
                            ]
                            for at, chunk in chunks:
                                clock[0] = at
                                yield ("data: " + json.dumps(chunk) + "\n").encode()
                            clock[0] = 1009.0
                            yield b"data: [DONE]\n"
                        def close(self): pass

                    h = Handler()
                    account = types.SimpleNamespace(uid="synthetic")
                    method = getattr(h, "_" + protocol + ("_stream_response" if streaming else "_nonstream_response"))
                    args = (Upstream(), "test-model", None, account, 1000.0)
                    if protocol == "responses":
                        args = (Upstream(), "test-model", set(), {}, None, account, 1000.0)
                    with mock.patch.object(P.time, "time", side_effect=lambda: clock[0]), \
                            mock.patch.object(P, "record_usage") as record:
                        method(*args)
                    self.assertEqual(record.call_count, 1)
                    fields = record.call_args.kwargs
                    self.assertEqual(fields.get("ttft_ms"), 1000)
                    self.assertEqual(fields.get("gen_ms"), 2000)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _TMP.cleanup()
