"""Shared validation at the HTTP boundary, before protocol conversion."""
import math


class RequestValidationError(ValueError):
    pass


def _messages(value, field):
    if not isinstance(value, list) or not value:
        raise RequestValidationError("%s must be a non-empty array" % field)
    for index, item in enumerate(value):
        prefix = "%s[%d]" % (field, index)
        if not isinstance(item, dict):
            raise RequestValidationError("%s must be an object" % prefix)
        if "role" in item and not isinstance(item["role"], str):
            raise RequestValidationError("%s.role must be a string" % prefix)
        content = item.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise RequestValidationError("%s.content must be a string or array" % prefix)
        if isinstance(content, list) and any(not isinstance(part, (dict, str)) for part in content):
            raise RequestValidationError("%s.content entries must be objects or strings" % prefix)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") is not None and not isinstance(part["type"], str):
                    raise RequestValidationError("%s.content type must be a string" % prefix)
        if item.get("tool_calls") is not None:
            _tools(item["tool_calls"], prefix + ".tool_calls")
        if item.get("function_call") is not None and not isinstance(item["function_call"], dict):
            raise RequestValidationError("%s.function_call must be an object" % prefix)


def _tools(value, field="tools", depth=0):
    if not isinstance(value, list):
        raise RequestValidationError("%s must be an array" % field)
    if depth > 4:
        raise RequestValidationError("tool namespaces are nested too deeply")
    for index, tool in enumerate(value):
        prefix = "%s[%d]" % (field, index)
        if not isinstance(tool, dict):
            raise RequestValidationError("%s must be an object" % prefix)
        if "type" in tool and not isinstance(tool["type"], str):
            raise RequestValidationError("%s.type must be a string" % prefix)
        if "function" in tool and not isinstance(tool["function"], dict):
            raise RequestValidationError("%s.function must be an object" % prefix)
        function = tool.get("function") or tool
        if "name" in function and not isinstance(function["name"], str):
            raise RequestValidationError("%s.name must be a string" % prefix)
        if "parameters" in function and function["parameters"] is not None and not isinstance(function["parameters"], dict):
            raise RequestValidationError("%s.parameters must be an object" % prefix)
        if "tools" in tool:
            _tools(tool["tools"], prefix + ".tools", depth + 1)


def validate_request(payload, protocol="chat"):
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be an object")
    if "model" in payload and (not isinstance(payload["model"], str) or not payload["model"].strip()):
        raise RequestValidationError("model must be a non-empty string")
    if payload.get("stream") is not None and not isinstance(payload["stream"], bool):
        raise RequestValidationError("stream must be a boolean")
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise RequestValidationError("metadata must be an object")
    for source in (payload, metadata or {}):
        for field in ("conversation_id", "session_id", "conversation_request_id"):
            value = source.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 1024):
                raise RequestValidationError("%s must be a non-empty string of at most 1024 characters" % field)
    for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        value = payload.get(field)
        if value is not None and (type(value) is not int or value <= 0):
            raise RequestValidationError("%s must be a positive integer" % field)
    for field in ("temperature", "top_p"):
        value = payload.get(field)
        if value is not None:
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise RequestValidationError("%s must be a finite number" % field)
    if payload.get("tools") is not None:
        _tools(payload["tools"])
    if payload.get("functions") is not None:
        _tools(payload["functions"], "functions")
    if payload.get("tool_choice") is not None and not isinstance(payload["tool_choice"], (str, dict)):
        raise RequestValidationError("tool_choice must be a string or object")
    for field in ("stream_options", "response_format", "reasoning", "text", "output_config", "thinking"):
        if payload.get(field) is not None and not isinstance(payload[field], dict):
            raise RequestValidationError("%s must be an object" % field)
    if payload.get("n") is not None and (type(payload["n"]) is not int or payload["n"] <= 0):
        raise RequestValidationError("n must be a positive integer")
    if protocol == "responses":
        value = payload.get("input")
        if value is not None and not isinstance(value, (str, list)):
            raise RequestValidationError("input must be a string or array")
        if isinstance(value, list):
            if any(not isinstance(item, (str, dict)) for item in value):
                raise RequestValidationError("input entries must be objects or strings")
            # Message entries share the Chat content shape; tool items keep
            # their own fields (function_call_output, images, custom tools).
            for item in value:
                if isinstance(item, dict) and item.get("type") is not None and not isinstance(item["type"], str):
                    raise RequestValidationError("input type must be a string")
                if isinstance(item, dict) and ("role" in item or item.get("type") == "message"):
                    _messages([item], "input")
        if payload.get("instructions") is not None and not isinstance(payload["instructions"], str):
            raise RequestValidationError("instructions must be a string")
    else:
        _messages(payload.get("messages"), "messages")
