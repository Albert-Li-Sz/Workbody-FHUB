"""Validate upstream SSE completion and preserve confirmed partial usage."""
import hashlib
import json
import types


class UpstreamStreamError(RuntimeError):
    def __init__(self, message, usage=None, code="upstream_error"):
        super().__init__(message)
        self.usage = usage
        self.code = code


def affinity_key(session_id, realm, api_key_id=""):
    """Scope internal routing without changing the upstream conversation ID."""
    if not session_id:
        return None
    value = json.dumps([str(api_key_id or ""), str(realm or ""), str(session_id)],
                       ensure_ascii=False, separators=(",", ":"))
    return "session-v2:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class StreamState:
    def __init__(self, holder=None):
        self.holder = holder if holder is not None else {}
        self.usage = None
        self.saw_done = False
        self.saw_finish = False
        self.saw_choice = False

    def observe(self, value):
        if not isinstance(value, dict):
            raise UpstreamStreamError("upstream SSE data must be an object", self.usage)
        usage = value.get("usage")
        if isinstance(usage, dict) and usage:
            if self.usage is None or (usage.get("total_tokens") or 0) >= (self.usage.get("total_tokens") or 0):
                self.usage = usage
                self.holder["usage"] = usage
        error = value.get("error")
        if error is not None:
            message = error.get("message") if isinstance(error, dict) else str(error)
            code = error.get("code") if isinstance(error, dict) else "upstream_error"
            raise UpstreamStreamError(message or "upstream returned an error", self.usage,
                                      str(code or "upstream_error"))
        choices = value.get("choices") or []
        if not isinstance(choices, list) or any(not isinstance(c, dict) for c in choices):
            raise UpstreamStreamError("invalid upstream choices", self.usage)
        self.saw_choice = self.saw_choice or bool(choices)
        self.saw_finish = self.saw_finish or any(c.get("finish_reason") is not None for c in choices)

    def finish(self):
        if not self.saw_choice:
            raise UpstreamStreamError("empty upstream stream", self.usage)
        if not (self.saw_done or self.saw_finish):
            raise UpstreamStreamError("upstream stream ended before a completion marker", self.usage)


def checked_lines(raw_iter, holder=None):
    """One parser for Chat, Responses and Messages, streaming or aggregated.

    Accept comments, multi-line SSE data and providers omitting [DONE] after
    finish_reason. EOF without either terminal signal is a failed response.
    Complete JSON data lines are dispatched immediately for low latency.
    """
    state = StreamState(holder)
    pending = []
    try:
        for raw in raw_iter:
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            for line in text.splitlines():
                if line.startswith(":") or line.startswith(("event:", "id:", "retry:")):
                    continue
                if not line.strip():
                    if pending:
                        raise UpstreamStreamError("invalid upstream SSE JSON", state.usage)
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].lstrip()
                if data == "[DONE]":
                    if pending:
                        raise UpstreamStreamError("incomplete upstream SSE JSON", state.usage)
                    state.saw_done = True
                    state.finish()
                    yield b"data: [DONE]\n\n"
                    return
                pending.append(data)
                try:
                    value = json.loads("\n".join(pending))
                except ValueError:
                    if sum(map(len, pending)) > 8 * 1024 * 1024:
                        raise UpstreamStreamError("upstream SSE frame exceeds size limit", state.usage)
                    continue
                pending.clear()
                state.observe(value)
                yield ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode("utf-8")
        if pending:
            raise UpstreamStreamError("incomplete upstream SSE JSON", state.usage)
        state.finish()
    except (BrokenPipeError, ConnectionAbortedError):
        raise
    except UpstreamStreamError:
        raise
    except Exception as exc:
        raise UpstreamStreamError("upstream stream aborted: %s" % exc, state.usage) from exc
    finally:
        if isinstance(raw_iter, types.GeneratorType):
            raw_iter.close()
