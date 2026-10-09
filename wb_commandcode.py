"""Command Code's generate envelope and NDJSON-to-Chat transport adapter.

Wire fields checked against command-code@1.79.2. No prompts are truncated,
usage is never estimated as a bill, and an interrupted stream cannot finish
successfully. The existing Chat/Responses/Messages handlers own client SSE.
"""
import copy
import datetime
import json
import math
import os
import re
import time
import uuid
from wb_commandcode_catalog import MODELS

PROTOCOL_VERSION = "1.79.2"
MAX_EVENT_BYTES = 50 * 1024 * 1024


def builtin_models():
    return copy.deepcopy(MODELS)


def headers(token, session):
    return {"Content-Type": "application/json", "Authorization": "Bearer " + token,
            "User-Agent": "cli", "x-command-code-version": PROTOCOL_VERSION,
            "x-cli-environment": "production", "x-project-slug": "workbody-fhub",
            "x-taste-learning": "false", "x-session-id": session,
            "traceparent": "00-" + uuid.uuid4().hex + "-" + uuid.uuid4().hex[:16] + "-01"}


def envelope(body, session, error):
    messages_input = body.get("messages") or []
    if not isinstance(messages_input, list) or any(not isinstance(message, dict) for message in messages_input):
        raise error("Command Code messages must be an array of objects")
    for message in messages_input:
        content = message.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise error("invalid Command Code message content")
        if isinstance(content, list) and any(not isinstance(part, dict) for part in content):
            raise error("Command Code content blocks must be objects")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list) or any(not isinstance(call, dict) or not isinstance(call.get("function"), dict) for call in calls):
            raise error("invalid Command Code tool calls")
    if body.get("n") not in (None, 1):
        raise error("Command Code supports one completion per request")
    for option in ("response_format", "logprobs", "top_logprobs", "audio", "modalities"):
        if body.get(option) is not None:
            raise error("Command Code does not support this option: " + option)
    system, messages, names = [], [], {}
    for message in body.get("messages") or []:
        for tool in message.get("tool_calls") or []:
            names[tool.get("id")] = (tool.get("function") or {}).get("name", "")
    for message in body.get("messages") or []:
        role, content = message.get("role"), message.get("content")
        if role in ("system", "developer"):
            parts = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
            for part in parts:
                if part.get("type") != "text":
                    raise error("Command Code system messages must be text")
                system.append(copy.deepcopy(part))
            continue
        if role == "tool":
            if isinstance(content, list):
                if any(part.get("type") != "text" for part in content):
                    raise error("Command Code tool results must be text")
                content = "\n".join(part.get("text", "") for part in content)
            messages.append({"role": "tool", "content": [{"type": "tool-result",
                "toolCallId": message.get("tool_call_id"), "toolName": names.get(message.get("tool_call_id")) or message.get("name") or "unknown",
                "output": {"type": "text", "value": content if content is not None else ""}}]})
            continue
        if role not in ("user", "assistant"):
            raise error("unsupported Command Code message role: " + str(role))
        parts = []
        if role == "assistant" and message.get("reasoning_content"):
            parts.append({"type": "reasoning", "text": message["reasoning_content"]})
        for part in ([{"type": "text", "text": content}] if isinstance(content, str) else content or []):
            if part.get("type") in ("text", "reasoning"):
                parts.append(copy.deepcopy(part))
            elif part.get("type") == "image_url":
                value = part.get("image_url")
                image = value.get("url") if isinstance(value, dict) else value
                if not isinstance(image, str):
                    raise error("invalid Command Code image input")
                item = {"type": "image", "image": image}
                mime = re.match(r"data:([^;,]+)", image)
                if mime:
                    item["mimeType"] = mime[1]
                parts.append(item)
            else:
                raise error("unsupported Command Code content block: " + str(part.get("type")))
        for tool in message.get("tool_calls") or []:
            function = tool.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except ValueError as exc:
                raise error("invalid tool arguments in Command Code history") from exc
            parts.append({"type": "tool-call", "toolCallId": tool.get("id"), "toolName": function.get("name"), "input": arguments})
        messages.append({"role": role, "content": parts})
    for part in system[:-1]:
        part["text"] = str(part.get("text") or "") + "\n"
    if not system:
        # An omitted system prompt lets the upstream inject its CLI prompt.
        system = [{"type": "text", "text": " "}]
    if body.get("prompt_cache_key") and not any(part.get("cache_control") for part in system):
        system[-1]["cache_control"] = {"type": "ephemeral"}
    params = {"model": body["model"], "messages": messages, "system": system,
              "max_tokens": body.get("max_completion_tokens") or body.get("max_tokens") or 64000,
              "stream": True, "tools": []}
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type", "function") != "function":
            raise error("Command Code requires function tools")
        function = tool.get("function") or tool
        params["tools"].append({"name": function.get("name"), "description": function.get("description", ""),
                                "input_schema": copy.deepcopy(function.get("parameters") or {"type": "object", "properties": {}})})
    for option in ("temperature", "reasoning_effort", "parallel_tool_calls", "stop", "top_p"):
        if option in body:
            params[option] = copy.deepcopy(body[option])
    if "tool_choice" in body:
        choice = body["tool_choice"]
        if isinstance(choice, str):
            params["tool_choice"] = {"type": {"required": "any"}.get(choice, choice)}
        elif isinstance(choice, dict) and choice.get("type") == "function":
            params["tool_choice"] = {"type": "tool", "name": (choice.get("function") or {}).get("name")}
        else:
            params["tool_choice"] = copy.deepcopy(choice)
    return {"config": {"workingDir": "/workspace", "date": str(datetime.date.today()), "environment": "linux",
            "structure": [], "isGitRepo": False, "currentBranch": "", "mainBranch": "", "gitStatus": "", "recentCommits": []},
            "memory": None, "taste": None, "skills": None, "permissionMode": "standard", "threadId": session,
            "mode": "agent", "params": params}


def usage(value):
    if not isinstance(value, dict) or not value:
        return None
    prompt = value.get("inputTokens")
    completion = value.get("outputTokens")
    if type(prompt) not in (int, float) or type(completion) not in (int, float) or not math.isfinite(prompt) or not math.isfinite(completion):
        return None
    details = value.get("inputTokenDetails") or {}
    if not isinstance(details, dict):
        details = {}
    cached = value.get("cachedInputTokens", details.get("cacheReadTokens", 0))
    cached = int(cached) if type(cached) in (int, float) and math.isfinite(cached) and cached >= 0 else 0
    result = {"prompt_tokens": max(0, int(prompt)), "completion_tokens": max(0, int(completion)),
              "total_tokens": max(0, int(prompt)) + max(0, int(completion)),
              "prompt_tokens_details": {"cached_tokens": min(cached, max(0, int(prompt)))}}
    credit = value.get("creditsUsed", value.get("totalCredits"))
    if type(credit) in (int, float) and math.isfinite(credit) and credit >= 0:
        result["creditsUsed"] = credit
        result["credit"] = credit
    return result


class ChatResponse:
    """File-like response with incremental translation and real cancellation."""
    def __init__(self, response, body, error):
        self.response, self.error = response, error
        self.model, self.streaming = body["model"], bool(body.get("stream"))
        self.id, self.created = "chatcmpl-" + uuid.uuid4().hex, int(time.time())
        self.headers = {"Content-Type": "text/event-stream" if self.streaming else "application/json"}
        self.status = getattr(response, "status", 200)
        self.current_usage = None
        self.finish, self.saw_finish = None, False
        self.tool_index, self.pending_tools = {}, {}
        self.buffer = b""
        self.eof = False
        self.frames = self._frames()

    def __getattr__(self, name):
        return getattr(self.response, name)

    def _chunk(self, delta, finish=None, measured=None):
        result = {"id": self.id, "object": "chat.completion.chunk", "created": self.created, "model": self.model,
                  "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        if measured:
            result["usage"] = measured
        return ("data: " + json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode()

    def _frames(self):
        while True:
            line = self.response.readline(MAX_EVENT_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_EVENT_BYTES:
                raise self.error("Command Code event exceeds the size limit", 502)
            if not line.strip() or line.startswith(b":"):
                continue
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise self.error("invalid Command Code stream event", 502, "upstream_stream_error") from exc
            if not isinstance(event, dict):
                raise self.error("invalid Command Code stream event", 502)
            kind = event.get("type")
            if kind in ("text-delta", "reasoning-delta"):
                text = event.get("text", event.get("delta", ""))
                if text:
                    yield self._chunk({"role": "assistant", "content" if kind == "text-delta" else "reasoning_content": text})
            elif kind == "tool-input-start":
                identifier = event.get("id") or event.get("toolCallId")
                self.pending_tools[identifier] = {"name": event.get("toolName", ""), "arguments": ""}
            elif kind == "tool-input-delta":
                identifier = event.get("id") or event.get("toolCallId")
                if identifier in self.pending_tools:
                    self.pending_tools[identifier]["arguments"] += event.get("delta", event.get("text", ""))
            elif kind == "tool-call":
                if event.get("providerExecuted"):
                    raise self.error("server-executed Command Code tools require an explicit client protocol", 502)
                identifier = event.get("toolCallId") or "call_" + uuid.uuid4().hex
                index = self.tool_index.setdefault(identifier, len(self.tool_index))
                pending = self.pending_tools.pop(identifier, {})
                arguments = event.get("input", event.get("args", pending.get("arguments") or {}))
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                yield self._chunk({"role": "assistant", "tool_calls": [{"index": index, "id": identifier, "type": "function",
                    "function": {"name": event.get("toolName") or pending.get("name", ""), "arguments": arguments}}]})
            elif kind in ("finish-step", "finish"):
                measured = usage(event.get("totalUsage") or event.get("usage"))
                if measured:
                    self.current_usage = measured
                raw = event.get("rawFinishReason") or event.get("finishReason")
                aliases = {"tool_use": "tool_calls", "tool-calls": "tool_calls", "max_tokens": "length",
                           "max_output_tokens": "length", "model_context_window_exceeded": "length", "pause_turn": "length", "end_turn": "stop"}
                if raw in ("network_error", "network-error", "connection_error", "upstream_error"):
                    raise self.error("Command Code generation was interrupted", 502, "upstream_stream_error")
                if raw and raw != "other":
                    self.finish = aliases.get(raw, raw)
                    if self.finish not in ("stop", "length", "tool_calls", "content_filter"):
                        raise self.error("Command Code returned an unsupported completion reason", 502, "upstream_stream_error")
                if kind == "finish-step" and measured:
                    yield self._chunk({}, measured=self.current_usage)
                if kind == "finish":
                    if not self.finish:
                        raise self.error("Command Code ended without a completion reason", 502, "upstream_stream_error")
                    self.saw_finish = True
                    yield self._chunk({}, self.finish, self.current_usage)
            elif kind in ("error", "abort"):
                detail = event.get("error") or {}
                status = detail.get("statusCode") if isinstance(detail, dict) else None
                status = status if type(status) is int and 400 <= status < 600 else 502
                raise self.error("Command Code generation failed", status, "upstream_stream_error")
        if not self.saw_finish:
            raise self.error("Command Code stream ended before completion", 502, "upstream_stream_error")
        yield b"data: [DONE]\n\n"

    def _collect(self):
        content, reasoning, tools = [], [], {}
        size = 0
        for frame in self.frames:
            size += len(frame)
            if size > MAX_EVENT_BYTES:
                raise self.error("Command Code response exceeds the size limit", 502)
            if frame == b"data: [DONE]\n\n":
                break
            event = json.loads(frame[6:])
            delta = event["choices"][0]["delta"]
            content.append(delta.get("content") or "")
            reasoning.append(delta.get("reasoning_content") or "")
            for call in delta.get("tool_calls") or []:
                tools[call["index"]] = {key: value for key, value in call.items() if key != "index"}
        message = {"role": "assistant", "content": "".join(content)}
        if reasoning:
            message["reasoning_content"] = "".join(reasoning)
        if tools:
            message["tool_calls"] = [tools[index] for index in sorted(tools)]
        result = {"id": self.id, "object": "chat.completion", "created": self.created, "model": self.model,
                  "choices": [{"index": 0, "message": message, "finish_reason": self.finish}]}
        if self.current_usage:
            result["usage"] = self.current_usage
        return json.dumps(result, ensure_ascii=False).encode()

    def read(self, amount=None):
        if not self.streaming and not self.eof:
            self.buffer = self._collect()
            self.eof = True
        if self.streaming:
            while not self.eof and (amount is None or len(self.buffer) < amount):
                try:
                    self.buffer += next(self.frames)
                except StopIteration:
                    self.eof = True
        if amount is None or amount < 0:
            result, self.buffer = self.buffer, b""
        else:
            result, self.buffer = self.buffer[:amount], self.buffer[amount:]
        return result

    def readline(self, limit=-1):
        while b"\n" not in self.buffer and not self.eof:
            try:
                self.buffer += next(self.frames)
            except StopIteration:
                self.eof = True
        length = self.buffer.find(b"\n") + 1
        length = length or len(self.buffer)
        if limit >= 0:
            length = min(length, limit)
        line, self.buffer = self.buffer[:length], self.buffer[length:]
        return line

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def abort(self):
        return getattr(self.response, "abort", self.response.close)()

    def close(self):
        self.response.close()


def cli_credentials(path=None):
    """Read the official auth file only after an explicit panel import."""
    path = path or os.environ.get("WB_COMMANDCODE_AUTH_FILE") or os.path.expanduser("~/.commandcode/auth.json")
    with open(path, "rb") as file:
        raw = file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Command Code credential file is too large")
    value = json.loads(raw)
    key = value.get("apiKey") if isinstance(value, dict) else None
    if not isinstance(key, str) or not re.fullmatch(r"user_[a-zA-Z0-9_-]{8,}", key):
        raise ValueError("no Command Code CLI credential found")
    return {"upstream": "commandcode", "api_key": key, "name": value.get("userName") or "Command Code",
            "user_id": value.get("userId")}
