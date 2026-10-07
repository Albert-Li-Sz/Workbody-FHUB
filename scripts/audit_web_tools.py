"""Reproduce web-tool audit findings with synthetic completions and loopback only.

Run: python scripts/audit_web_tools.py
This is an audit probe, not a regression suite asserting the bugs are desired.
It does not read real accounts, use a real model, or contact an external site.
"""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wb_proxy as P
import wb_settings as S
import wb_webtools as W


class LocalPage(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/private" % self.server.server_port)
            self.end_headers()
            return
        body = b"LOCAL_TEST_SENTINEL"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def fetch_probe():
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_lookup = socket.getaddrinfo
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fake_dns(host, *args, **kwargs):
        return real_lookup("127.0.0.1" if host == "public.example" else host, *args, **kwargs)

    try:
        with mock.patch.object(socket, "getaddrinfo", side_effect=fake_dns), \
                mock.patch.object(W.urllib.request, "urlopen", side_effect=direct.open), \
                mock.patch.dict(os.environ, {"WB_WEB_PROXY": ""}):
            dns_result = W.fetch("http://public.example:%d/private" % server.server_port)
            redirect_result = W.fetch("http://public.example:%d/redirect" % server.server_port)
        return {
            "dns_to_loopback_read": "LOCAL_TEST_SENTINEL" in dns_result,
            "redirect_to_loopback_read": "LOCAL_TEST_SENTINEL" in redirect_result,
            "literal_loopback_initial_url_refused": W.fetch("http://127.0.0.1/").startswith("Error:"),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


class FakeResponse:
    def close(self):
        pass


class FakeAccount:
    uid = "synthetic-audit-account"


class FakeHandler:
    def _key_id(self):
        return None

    def _json(self, status, document):
        return status, document

    def _error(self, status, message):
        return status, {"error": message}


def completion(name=None, total=3, extra_call=False):
    message = {"role": "assistant", "content": "Final answer" if not name else None}
    if name:
        message["tool_calls"] = [{
            "id": "original-" + name, "type": "function",
            "function": {"name": name, "arguments": json.dumps(
                {"query": "synthetic audit"} if name == "web_search" else {"url": "https://example.com/"})},
        }]
    if extra_call:
        message["tool_calls"].append({"id": "client-call", "type": "function",
                                      "function": {"name": "exec_command", "arguments": "{}"}})
    return {"choices": [{"message": message}],
            "usage": {"prompt_tokens": total - 1, "completion_tokens": 1, "total_tokens": total}}


def run_nonstream(completions, max_rounds=3):
    opened, logged, executed = [], [], []

    def open_followup(body, **kwargs):
        opened.append(copy.deepcopy(body))
        return FakeResponse(), FakeAccount(), None

    def record(model, usage, **kwargs):
        logged.append(copy.deepcopy(usage))

    def execute(name, args):
        executed.append(name)
        if name == "web_search":
            return "Search results for: synthetic\n\n1. Synthetic source\n   https://example.com/\n   Snippet."
        return "URL: https://example.com/\nCharacters: 0-4 of 4\n\nPage"

    body = {"messages": [{"role": "user", "content": "synthetic audit"}], "_web_tools": True,
            "tools": [W.web_search_tool_def(), W.web_fetch_tool_def(),
                      {"type": "function", "name": "exec_command", "parameters": {}}]}
    with mock.patch.object(P, "aggregate_stream", side_effect=completions), \
            mock.patch.object(P, "open_upstream", side_effect=open_followup), \
            mock.patch.object(P, "record_usage", side_effect=record), \
            mock.patch.object(P, "record_error"), mock.patch.object(P, "log"), \
            mock.patch.object(W, "execute", side_effect=execute), \
            mock.patch.object(W, "MAX_WEB_ROUNDS", max_rounds):
        status, result = P.Handler._responses_nonstream_response(
            FakeHandler(), FakeResponse(), "synthetic-model", set(), {}, "synthetic-fp",
            FakeAccount(), time.time(), base_body=body, realm="intl")
    return status, result, opened, logged, executed


def orchestration_probe():
    status, result, opened, logged, executed = run_nonstream([
        completion("web_search", 3), completion("web_fetch", 5), completion(total=9)])
    history = {
        "status": status,
        "followup_message_counts": [len(body["messages"]) for body in opened],
        "second_followup_tool_history": [m.get("name") for m in opened[1]["messages"] if m["role"] == "tool"],
        "recorded_round_tokens": [(u or {}).get("total_tokens", 0) for u in logged],
        "expected_total_tokens": 17,
        "recorded_total_tokens": sum((u or {}).get("total_tokens", 0) for u in logged),
        "response_total_tokens": result["usage"]["total_tokens"],
    }
    status, result, opened, logged, executed = run_nonstream(
        [completion("web_search")] * 6 + [completion()], max_rounds=1)
    budget = {"configured_rounds": 1, "executed_tool_rounds": len(executed),
              "followup_requests": len(opened), "status": status}
    status, result, opened, logged, executed = run_nonstream(
        [completion("web_search", extra_call=True), completion()])
    mixed = {"client_call_in_original_completion": True, "handoff_without_followup": not opened,
             "client_call_in_followup": any(tc["function"]["name"] == "exec_command"
                 for b in opened for m in b["messages"] for tc in m.get("tool_calls", [])),
             "client_call_in_response": any(item.get("name") == "exec_command" for item in result.get("output", [])),
             "status": status}
    return {"nonstream_history_and_usage": history, "round_budget": budget, "mixed_tool_calls": mixed}


def main():
    # All settings lookups, including defaults, use a throwaway directory.
    with tempfile.TemporaryDirectory(prefix="workbody-audit-") as directory, \
            mock.patch.multiple(P, ACCOUNTS_DIR=directory, API_KEY=None, POOL=None):
        findings = {"scope": "synthetic model responses and local HTTP server only",
                    "fetch_ssrf": fetch_probe(), **orchestration_probe(),
                    "fresh_install_accepts_admin_password": S.verify_panel_password(directory, "admin")}
    print(json.dumps(findings, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
