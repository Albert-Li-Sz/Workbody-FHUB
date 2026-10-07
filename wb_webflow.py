"""State and hard budgets for one Responses request with local web tools."""
import copy
import json
import socket
import threading
import time
import uuid
import wb_webtools as W


class WebToolLimitError(RuntimeError):
    pass


def add_usage(total, part):
    out = copy.deepcopy(total) if isinstance(total, dict) else {}
    for key, value in (part or {}).items():
        if isinstance(value, dict):
            out[key] = add_usage(out.get(key), value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = (out.get(key) or 0) + value
        elif key not in out:
            out[key] = copy.deepcopy(value)
    return out or None


class WebToolFlow:
    def __init__(self, body):
        self.body = copy.deepcopy(body or {})
        self.messages = copy.deepcopy(self.body.get("messages") or [])
        self.sources = []
        self.usage = None
        self.rounds = self.calls = 0
        self.deadline = time.monotonic() + W.MAX_WEB_TIME_SECONDS
        self.results = []

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise WebToolLimitError("web tool time limit exceeded")
        return seconds

    def execute(self, calls, assistant_message=None):
        self.remaining()
        if self.rounds >= W.MAX_WEB_ROUNDS or self.calls + len(calls) > W.MAX_WEB_CALLS:
            raise WebToolLimitError("web tool round/call limit exceeded")
        self.rounds += 1
        self.calls += len(calls)
        tool_calls = [{"id": c.get("id") or "call_web_" + uuid.uuid4().hex,
                       "type": "function", "function": {
                           "name": c["name"], "arguments": c.get("arguments") or "{}"}}
                      for c in calls]
        message = copy.deepcopy(assistant_message) if assistant_message else {
            "role": "assistant", "content": None, "tool_calls": tool_calls}
        self.messages.append(message)
        results = []
        for tc in tool_calls:
            self.remaining()
            fn = tc["function"]
            token = W._call_deadline.set(self.deadline)
            try:
                result = W.execute(fn["name"], fn["arguments"])
            finally:
                W._call_deadline.reset(token)
            self.remaining()
            self.sources.extend(W.sources_from_result(result))
            results.append(result)
            self.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                  "name": fn["name"], "content": result})
        self.results = results
        return results

    def followup_body(self):
        self.remaining()
        body = copy.deepcopy(self.body)
        body["messages"] = copy.deepcopy(self.messages)
        body["stream"] = True
        if self.rounds >= W.MAX_WEB_ROUNDS or self.calls >= W.MAX_WEB_CALLS:
            body["tools"] = [t for t in body.get("tools") or []
                             if not W.is_internal_tool((t.get("function") or t).get("name"))]
            body["tool_choice"] = "auto"
            body["messages"].append({"role": "system", "content":
                "Web tools are exhausted. Answer using the available results or call a client-owned tool."})
        return body

    def iter_upstream(self, upstream, set_timeout):
        self.current_usage = None
        expired = threading.Event()

        def interrupt_read():
            expired.set()
            fp = getattr(upstream, "fp", None)
            sock = getattr(getattr(fp, "raw", None), "_sock", None) or getattr(fp, "_sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = threading.Timer(self.remaining(), interrupt_read)
        timer.daemon = True
        timer.start()
        try:
            iterator = iter(upstream)
            while True:
                set_timeout(upstream, self.remaining())
                try:
                    frame = next(iterator)
                except StopIteration:
                    self.remaining()
                    return
                except Exception:
                    if expired.is_set():
                        raise WebToolLimitError("web tool time limit exceeded") from None
                    raise
                self.remaining()
                try:
                    text = frame.decode("utf-8", "replace").strip()
                    chunk = json.loads(text[5:].strip()) if text.startswith("data:") else {}
                    if isinstance(chunk.get("usage"), dict):
                        self.current_usage = chunk["usage"]
                except (ValueError, AttributeError):
                    pass
                yield frame
        finally:
            timer.cancel()

    def result_text(self):
        return "Local web tool results:\n\n" + "\n\n".join(self.results)
