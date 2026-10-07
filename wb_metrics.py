"""Measure generation independently of protocol framing and HTTP teardown."""
import json
import math
import time


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

    def observe(self, chunk):
        if generated_content(chunk):
            at = time.time()
            if self.first_at is None:
                self.first_at = at
            self.last_at = at

    def wrap(self, raw_iter):
        for line in raw_iter:
            try:
                data = line.decode("utf-8", "replace").strip()
                if data.startswith("data:"):
                    self.observe(json.loads(data[5:].strip()))
            except (ValueError, TypeError, AttributeError):
                pass
            yield line

    def fields(self):
        return {
            "ttft_ms": (max(0, round((self.first_at - self.started_at) * 1000))
                        if self.first_at is not None else None),
            "gen_ms": (round((self.last_at - self.first_at) * 1000, 3)
                       if self.first_at is not None and self.last_at > self.first_at else None),
        }
