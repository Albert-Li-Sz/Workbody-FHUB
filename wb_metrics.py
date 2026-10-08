"""Measure generation independently of protocol framing and HTTP teardown."""
import json
import math
import time
import contextlib
import threading
import types

REQUEST = threading.local()
TIMING_FIELDS = ("queue_ms", "parse_ms", "normalize_ms", "account_selection_ms",
                 "connection_pool_wait_ms", "connect_ms", "upstream_send_ms", "upstream_headers_ms",
                 "first_event_ms", "upstream_text_ms", "first_text_ms")


class RequestTiming:
    def __init__(self):
        self.started_at = time.time()
        self.started = time.monotonic()
        self.durations = {}
        self.first_event = None
        self.first_text = None
        self.first_upstream_text = None

    def observe(self, chunk):
        now = time.monotonic()
        if self.first_event is None and generated_content(chunk):
            self.first_event = now
        if self.first_upstream_text is None and any(isinstance(choice, dict) and
                isinstance(choice.get("delta"), dict) and choice["delta"].get("content")
                for choice in chunk.get("choices") or []):
            self.first_upstream_text = now

    def fields(self):
        result = {key: round(value * 1000, 3) for key, value in self.durations.items()}
        result["first_event_ms"] = round((self.first_event - self.started) * 1000, 3) if self.first_event is not None else None
        result["first_text_ms"] = round((self.first_text - self.started) * 1000, 3) if self.first_text is not None else None
        result["upstream_text_ms"] = round((self.first_upstream_text - self.started) * 1000, 3) if self.first_upstream_text is not None else None
        return result


def observe_client_frame(frame):
    timing = getattr(REQUEST, "timing", None)
    if timing is None or timing.first_text is not None:
        return
    try:
        text = frame.decode("utf-8", "replace") if isinstance(frame, bytes) else str(frame)
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            value = json.loads(line[5:].strip())
            visible = (value.get("type") == "response.output_text.delta" and bool(value.get("delta")))
            delta = value.get("delta") or {}
            if isinstance(delta, dict):
                visible = visible or delta.get("type") == "text_delta" and bool(delta.get("text"))
            for choice in value.get("choices") or []:
                visible = visible or bool((choice.get("delta") or {}).get("content"))
            if visible:
                timing.first_text = time.monotonic()
                return
    except (ValueError, TypeError, AttributeError):
        pass


def begin_request():
    REQUEST.timing = RequestTiming()
    return REQUEST.timing


def request_started_at():
    timing = getattr(REQUEST, "timing", None)
    return timing.started_at if timing else time.time()


@contextlib.contextmanager
def stage(name):
    started = time.monotonic()
    try:
        yield
    finally:
        timing = getattr(REQUEST, "timing", None)
        if timing:
            timing.durations[name] = timing.durations.get(name, 0) + time.monotonic() - started


def positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def speed_sample(row):
    """Return matching (output tokens, generation ms), excluding partial calls."""
    outcome = row.get("outcome")
    if outcome not in ("completed", "client_aborted", "upstream_aborted", "failed"):
        outcome = "failed" if row.get("error") else "completed"
    if outcome != "completed":
        return None
    tokens, duration = row.get("completion_tokens"), row.get("gen_ms")
    if row.get("usage_missing") or not positive_number(tokens) or not positive_number(duration):
        return None
    return tokens, duration


def generated_content(chunk):
    if not isinstance(chunk, dict):
        return False
    for choice in chunk.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        if delta.get("content") or delta.get("reasoning_content"):
            return True
        for tool in delta.get("tool_calls") or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") or {}
            if isinstance(function, dict) and (function.get("name") or function.get("arguments")):
                return True
    return False


class GenerationTiming:
    """Observe the same upstream content for Chat, Responses and Messages.

    One content frame cannot establish a generation interval. Leave its speed
    unknown rather than dividing an entire output by a few teardown ms.
    Each upstream round has its own observer, excluding local tool execution.
    """
    def __init__(self, started_at):
        self.started_at = started_at
        self.first_at = None
        self.last_at = None
        self.first_tick = None
        self.last_tick = None

    def observe(self, chunk):
        request = getattr(REQUEST, "timing", None)
        if request:
            request.observe(chunk)
        if generated_content(chunk):
            at = time.time()
            tick = time.monotonic()
            if self.first_at is None:
                self.first_at = at
                self.first_tick = tick
            self.last_at = at
            self.last_tick = tick

    def wrap(self, raw_iter):
        try:
            for line in raw_iter:
                try:
                    data = line.decode("utf-8", "replace").strip()
                    if data.startswith("data:"):
                        self.observe(json.loads(data[5:].strip()))
                except (ValueError, TypeError, AttributeError):
                    pass
                yield line
        finally:
            if isinstance(raw_iter, types.GeneratorType):
                raw_iter.close()

    def fields(self):
        return {
            "ttft_ms": (max(0, round((self.first_at - self.started_at) * 1000))
                        if self.first_at is not None else None),
            "gen_ms": (round((self.last_tick - self.first_tick) * 1000, 3)
                       if self.first_tick is not None and self.last_tick > self.first_tick else None),
        }
