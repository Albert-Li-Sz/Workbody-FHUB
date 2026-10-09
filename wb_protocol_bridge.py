"""Loss-aware protocol conversion for the two additional upstreams.

Native requests bypass conversion. Unsupported opaque or server-owned blocks
raise an error instead of turning a normal-looking reply into missing context.
"""
import base64
import copy
import json
import time
import uuid

from wb_platforms import PlatformError


def sse_events(lines, limit=50 * 1024 * 1024):
    event, parts, size = "", [], 0
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if parts:
                text = "\n".join(parts)
                yield event, text if text == "[DONE]" else json.loads(text)
            event, parts, size = "", [], 0
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            part = line[5:].lstrip(" ")
            parts.append(part)
            size += len(part.encode("utf-8"))
            if size > limit:
                raise PlatformError("upstream SSE event exceeds the size limit", 502, "upstream_stream_error")
    if parts:
        text = "\n".join(parts)
        yield event, text if text == "[DONE]" else json.loads(text)


def frame(event, data):
    value = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return (("event: " + event + "\n" if event else "") + "data: " + value + "\n\n").encode("utf-8")


def usage(value, protocol, upstream):
    value = value if isinstance(value, dict) else {}
    if not value:
        return None
    out = copy.deepcopy(value)
    if protocol != "chat":
        cached = (value.get("input_tokens_details") or {}).get("cached_tokens", 0) if protocol == "responses" else value.get("cache_read_input_tokens", 0)
        prompt = value.get("input_tokens", 0)
        if protocol == "messages":
            prompt += cached + value.get("cache_creation_input_tokens", 0)
            out["prompt_cache_write_tokens"] = value.get("cache_creation_input_tokens", 0)
        out.update(prompt_tokens=prompt, completion_tokens=value.get("output_tokens", 0),
                   total_tokens=prompt + value.get("output_tokens", 0),
                   prompt_tokens_details={"cached_tokens": cached})
        if protocol == "responses":
            out["completion_tokens_details"] = copy.deepcopy(value.get("output_tokens_details") or {})
    credit = value.get("creditsUsed", value.get("credits_used", value.get("credit"))) if upstream in ("cline", "commandcode") else value.get("costUsd", value.get("cost_usd", value.get("cost")))
    if type(credit) in (int, float):
        out["credit"] = credit
    return out


def validate_portable_responses(body):
    allowed = {None, "message", "user", "reasoning", "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output", "agent_message"}
    if body.get("include") or body.get("truncation") not in (None, "disabled"):
        raise PlatformError("include and automatic truncation require a native Responses upstream")
    for item in body.get("input") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in allowed or item.get("encrypted_content"):
            raise PlatformError("this Responses input item requires its native protocol: " + str(item.get("type")))
        for part in item.get("content") or [] if isinstance(item.get("content"), list) else []:
            if isinstance(part, dict) and part.get("type") not in ("input_text", "output_text", "text", "input_image", "image_url", "image", "refusal"):
                raise PlatformError("unsupported Responses content block: " + str(part.get("type")))


def chat_to_responses(body):
    result = {"model": body.get("model"), "input": [], "stream": body.get("stream", False), "store": False}
    for message in body.get("messages") or []:
        role = message.get("role", "user")
        if role == "tool":
            output = message.get("content") or ""
            if isinstance(output, list):
                output = chat_to_responses({"messages": [{"role": "user", "content": output}]})["input"][0]["content"]
            result["input"].append({"type": "function_call_output", "call_id": message.get("tool_call_id"), "output": output})
            continue
        if message.get("reasoning_content"):
            result["input"].append({"type": "reasoning", "summary": [{"type": "summary_text", "text": message["reasoning_content"]}]})
        content = message.get("content")
        if content:
            parts = []
            if isinstance(content, str):
                parts = [{"type": "input_text" if role != "assistant" else "output_text", "text": content}]
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str):
                        part = {"type": "text", "text": part}
                    if part.get("type") == "text":
                        parts.append({"type": "input_text" if role != "assistant" else "output_text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        image = part["image_url"]
                        parts.append({"type": "input_image", "image_url": image.get("url") if isinstance(image, dict) else image,
                                      "detail": image.get("detail", "auto") if isinstance(image, dict) else "auto"})
                    else:
                        raise PlatformError("unsupported Chat content for Responses: " + str(part.get("type")))
            result["input"].append({"type": "message", "role": role, "content": parts})
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            result["input"].append({"type": "function_call", "call_id": call.get("id"), "name": fn.get("name"), "arguments": fn.get("arguments") or "{}"})
    for field in ("temperature", "top_p", "parallel_tool_calls", "metadata"):
        if field in body:
            result[field] = body[field]
    if body.get("max_tokens") or body.get("max_completion_tokens"):
        result["max_output_tokens"] = body.get("max_completion_tokens") or body["max_tokens"]
    if body.get("reasoning_effort"):
        result["reasoning"] = {"effort": body["reasoning_effort"]}
    if body.get("tools"):
        tools = []
        for tool in body["tools"]:
            if tool.get("type") != "function":
                raise PlatformError("unsupported Chat tool for Responses")
            tools.append(dict(tool["function"], type="function"))
        result["tools"] = tools
    choice = body.get("tool_choice")
    if choice is not None:
        if isinstance(choice, dict) and choice.get("type") == "function":
            choice = {"type": "function", "name": choice.get("function", {}).get("name")}
        result["tool_choice"] = choice
    if body.get("response_format"):
        fmt = body["response_format"]
        if fmt.get("type") == "json_schema":
            fmt = dict(fmt.get("json_schema") or {}, type="json_schema")
        result["text"] = {"format": fmt}
    if body.get("verbosity") is not None:
        result.setdefault("text", {})["verbosity"] = body["verbosity"]
    for field in ("service_tier", "safety_identifier", "user"):
        if body.get(field) is not None:
            result[field] = body[field]
    if body.get("n") not in (None, 1) or any(body.get(key) is not None for key in ("logprobs", "top_logprobs", "seed", "frequency_penalty", "presence_penalty")):
        raise PlatformError("requested Chat option cannot be represented by this Responses upstream")
    return result


def chat_to_messages(body, meta=None):
    meta = meta or {}
    result = {"model": body.get("model"), "messages": [], "stream": body.get("stream", False),
              "max_tokens": body.get("max_tokens") or body.get("max_completion_tokens") or meta.get("max_output_tokens") or 4096}
    system = []
    for message in body.get("messages") or []:
        role = message.get("role")
        content = message.get("content")
        if role in ("system", "developer"):
            if isinstance(content, str):
                system.append({"type": "text", "text": content})
            else:
                for part in content or []:
                    if isinstance(part, str):
                        part = {"type": "text", "text": part}
                    if part.get("type") != "text":
                        raise PlatformError("Messages system content must be text")
                    system.append(dict(part))
            continue
        if role == "tool":
            output = content or ""
            if isinstance(output, list):
                output = chat_to_messages({"messages": [{"role": "user", "content": output}]}, meta)["messages"][0]["content"]
            blocks = [{"type": "tool_result", "tool_use_id": message.get("tool_call_id"), "content": output}]
            role = "user"
        else:
            blocks = []
            if message.get("reasoning_content"):
                # A thinking signature cannot be invented. Models that require
                # signed thinking must use their original Messages protocol.
                raise PlatformError("replayed reasoning requires native Messages thinking blocks")
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str):
                        part = {"type": "text", "text": part}
                    if part.get("type") == "text":
                        blocks.append(dict(part))
                    elif part.get("type") == "image_url":
                        image = part["image_url"]
                        url = image.get("url") if isinstance(image, dict) else image
                        if isinstance(url, str) and url.startswith("data:"):
                            header, data = url.split(",", 1)
                            if not header.endswith(";base64"):
                                raise PlatformError("image data must use base64")
                            blocks.append({"type": "image", "source": {"type": "base64", "media_type": header[5:-7], "data": data}})
                        else:
                            blocks.append({"type": "image", "source": {"type": "url", "url": url}})
                    else:
                        raise PlatformError("unsupported Chat content for Messages")
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except ValueError as exc:
                    raise PlatformError("tool arguments are not valid JSON") from exc
                blocks.append({"type": "tool_use", "id": call.get("id"), "name": fn.get("name"), "input": arguments})
        if not blocks:
            continue
        if result["messages"] and result["messages"][-1]["role"] == role:
            result["messages"][-1]["content"].extend(blocks)
        else:
            result["messages"].append({"role": role, "content": blocks})
    if system:
        result["system"] = system
    for field in ("temperature", "top_p"):
        if field in body:
            result[field] = body[field]
    if body.get("tools"):
        result["tools"] = []
        for tool in body["tools"]:
            if tool.get("type") != "function":
                raise PlatformError("unsupported Chat tool for Messages")
            fn = tool.get("function") or {}
            result["tools"].append({"name": fn.get("name"), "description": fn.get("description", ""), "input_schema": fn.get("parameters") or {"type": "object"}})
    choice = body.get("tool_choice")
    if choice is not None:
        if isinstance(choice, str):
            result["tool_choice"] = {"type": {"required": "any"}.get(choice, choice)}
        elif isinstance(choice, dict):
            result["tool_choice"] = {"type": "tool", "name": choice.get("function", {}).get("name")}
    if body.get("stop"):
        result["stop_sequences"] = [body["stop"]] if isinstance(body["stop"], str) else body["stop"]
    if body.get("parallel_tool_calls") is False:
        result.setdefault("tool_choice", {"type": "auto"})["disable_parallel_tool_use"] = True
    if body.get("user") is not None:
        result["metadata"] = {"user_id": body["user"]}
    if body.get("n") not in (None, 1) or any(body.get(key) is not None for key in ("reasoning_effort", "response_format", "verbosity", "service_tier", "safety_identifier", "logprobs", "top_logprobs", "seed", "frequency_penalty", "presence_penalty")):
        raise PlatformError("requested Chat option cannot be represented by this Messages upstream")
    return result


def chat_lines(response, native, upstream):
    """Incremental native SSE -> Chat chunks, retaining IDs and confirmed use."""
    if native == "chat":
        last_usage, done, finished = None, False, set()
        try:
            for event, data in sse_events(response):
                if data == "[DONE]":
                    done = True
                elif not isinstance(data, dict) or data.get("error") or event == "error" or data.get("type") == "error":
                    raise PlatformError("upstream generation failed", 502, "upstream_stream_error")
                else:
                    if hasattr(response, "observe"):
                        response.observe(data)
                    if data.get("id"):
                        response.generation_id = data["id"]
                    if data.get("usage"):
                        last_usage = data["usage"] = usage(data["usage"], native, upstream)
                    for choice in data.get("choices") or []:
                        if choice.get("finish_reason") is not None:
                            finished.add(choice.get("index", 0))
                yield frame("", data)
            if not done and len(finished) < (getattr(response, "expected_choices", 1) or 1):
                raise PlatformError("upstream ended without a terminal event", 502, "upstream_stream_error")
        except Exception as exc:
            exc.usage = last_usage
            raise
        return
    identifier, created = "chatcmpl_" + uuid.uuid4().hex, int(time.time())
    tools, initial_usage, last_usage, done = {}, {}, None, False
    def chunk(delta=None, finish=None, tokens=None):
        value = {"id": identifier, "object": "chat.completion.chunk", "created": created,
                 "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if delta is not None or finish else []}
        if tokens:
            value["usage"] = tokens
        return frame("", value)
    try:
        for event, data in sse_events(response):
            if not isinstance(data, dict):
                continue
            event = data.get("type") or event
            result_id = (data.get("response") or data.get("message") or {}).get("id")
            if result_id:
                response.generation_id = result_id
            if data.get("error") or event in ("error", "response.failed"):
                raise PlatformError("upstream generation failed", 502, "upstream_stream_error")
            if native == "responses":
                if event == "response.output_text.delta":
                    yield chunk({"content": data.get("delta", "")})
                elif event in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
                    yield chunk({"reasoning_content": data.get("delta", "")})
                elif event == "response.output_item.added":
                    item = data.get("item") or {}
                    if item.get("type") == "function_call":
                        index = len(tools)
                        tools[item["id"]] = index
                        yield chunk({"tool_calls": [{"index": index, "id": item.get("call_id") or item["id"], "type": "function",
                            "function": {"name": item.get("name"), "arguments": item.get("arguments") or ""}}]})
                    elif item.get("type") not in ("message", "reasoning"):
                        raise PlatformError("upstream output requires native Responses: " + str(item.get("type")), 502)
                elif event == "response.function_call_arguments.delta":
                    if data.get("item_id") not in tools:
                        raise PlatformError("upstream tool delta has no tool ID", 502)
                    yield chunk({"tool_calls": [{"index": tools[data["item_id"]], "function": {"arguments": data.get("delta", "")}}]})
                elif event in ("response.completed", "response.incomplete"):
                    result = data.get("response") or {}
                    last_usage = usage(result.get("usage"), native, upstream)
                    if any(item.get("encrypted_content") for item in result.get("output") or []):
                        raise PlatformError("opaque reasoning requires native Responses", 502)
                    reason = "length" if event == "response.incomplete" else "tool_calls" if tools else "stop"
                    yield chunk({}, reason, last_usage)
                    done = True
            else:
                if event == "message_start":
                    initial_usage = dict((data.get("message") or {}).get("usage") or {})
                    last_usage = usage(initial_usage, native, upstream)
                elif event == "content_block_start":
                    block = data.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        index = len(tools)
                        tools[data["index"]] = index
                        yield chunk({"tool_calls": [{"index": index, "id": block.get("id"), "type": "function",
                            "function": {"name": block.get("name"), "arguments": ""}}]})
                    elif block.get("type") not in ("text", "thinking"):
                        raise PlatformError("upstream output requires native Messages: " + str(block.get("type")), 502)
                    elif block.get("text"):
                        yield chunk({"content": block["text"]})
                elif event == "content_block_delta":
                    delta = data.get("delta") or {}
                    kind = delta.get("type")
                    if kind == "text_delta":
                        yield chunk({"content": delta.get("text", "")})
                    elif kind == "thinking_delta":
                        yield chunk({"reasoning_content": delta.get("thinking", "")})
                    elif kind == "signature_delta":
                        raise PlatformError("signed thinking requires native Messages", 502)
                    elif kind == "input_json_delta":
                        yield chunk({"tool_calls": [{"index": tools[data["index"]], "function": {"arguments": delta.get("partial_json", "")}}]})
                elif event == "message_delta":
                    initial_usage.update(data.get("usage") or {})
                    last_usage = usage(initial_usage, native, upstream)
                    reason = {"tool_use": "tool_calls", "max_tokens": "length"}.get((data.get("delta") or {}).get("stop_reason"), "stop")
                    yield chunk({}, reason, last_usage)
                elif event == "message_stop":
                    done = True
        if not done:
            raise PlatformError("upstream ended without a terminal event", 502, "upstream_stream_error")
        yield b"data: [DONE]\n\n"
    except Exception as exc:
        exc.usage = last_usage
        raise


class ChatLease:
    def __init__(self, lease, native):
        self.lease, self.native = lease, native

    def __getattr__(self, name):
        return getattr(self.lease, name)

    def __iter__(self):
        return chat_lines(self.lease, self.native, self.lease._upstream)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.lease.close()
