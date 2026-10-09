"""HTTP generation orchestration for Cline and OpenCode Zen.

Existing FHUB converters and web-tool workflows consume ChatLease streams;
matching protocols keep their native events and payloads intact.
"""
import copy
import json
import sys
import time
from types import SimpleNamespace

import wb_metrics
import wb_protocol_bridge as bridge
import wb_stream
import wb_platforms
import wb_responses


def _proxy(handler):
    for cls in handler.__class__.__mro__:
        if cls.__name__ == "Handler":
            module = sys.modules[cls.__module__]
            if hasattr(module, "PLATFORMS") and hasattr(module, "open_upstream"):
                return module
    raise RuntimeError("missing gateway handler")


def _context(handler, body, proxy):
    proxy.set_request_context(request_id=handler.headers.get("X-Request-ID") or "",
        client_ip=handler._client_ip(), user_agent=handler.headers.get("User-Agent") or "",
        path=handler.path.split("?")[0], key_id=handler._key_id())


def _session(handler, body, proxy):
    context = handler._response_context
    if context:
        return context["conversation"]
    return proxy.extract_session_key(handler.headers, body) or proxy.derive_affinity_key(body.get("messages")) or ""


def _native_body(chat, native, meta):
    body = {key: copy.deepcopy(value) for key, value in chat.items() if not key.startswith("_")}
    if native == "responses":
        body = bridge.chat_to_responses(body)
    elif native == "messages":
        body = bridge.chat_to_messages(body, meta)
    body["stream"] = True
    if native == "chat":
        body["stream_options"] = dict(body.get("stream_options") or {}, include_usage=True)
    return body


def _open(manager, upstream, raw_model, body, meta, session, owner, bound=None):
    # All retries finish before any generated event is delivered. Scope stays
    # fixed to this platform; a bound opaque history never changes account.
    attempts = 1 if bound else max(1, min(4, sum(a.enabled and a.upstream == upstream for a in manager.accounts.values())))
    previous_error = None
    for attempt in range(attempts):
        try:
            return manager.open(upstream, raw_model, body, meta, session, owner, bound)
        except wb_platforms.PlatformError as exc:
            if exc.code == "account_unavailable" and previous_error is not None:
                raise previous_error from exc
            if attempt == attempts-1 or exc.status not in (401, 403, 429, 502, 503, 504):
                raise
            previous_error = exc


def open_chat(proxy, payload, session_key=None, preferred_uid=None):
    upstream, raw_model, public_model = wb_platforms.route(payload.get("model"),
        {"allowed_upstreams": ["cline", "opencode_zen"]})
    manager = proxy.PLATFORMS
    meta = manager.model(upstream, raw_model)
    body = _native_body(payload, meta["native_protocol"], meta)
    session = session_key or proxy.derive_affinity_key(payload.get("messages")) or ""
    lease = _open(manager, upstream, raw_model, body, meta, session,
                  getattr(proxy._REQ_CONTEXT, "key_id", ""), preferred_uid)
    proxy._apply_stream_idle_timeout(lease, proxy.upstream_timeouts()[1])
    return bridge.ChatLease(lease, meta["native_protocol"]), lease.account, payload.get("reasoning_effort")


def handle(handler, payload, protocol, upstream, raw_model, public_model):
    proxy = _proxy(handler)
    _context(handler, payload, proxy)
    try:
        return _handle(handler, payload, protocol, upstream, raw_model, public_model)
    except (wb_platforms.PlatformError, wb_responses.ResponseError) as exc:
        if not getattr(exc, "recorded", False):
            meta = proxy.PLATFORMS.catalogues.get(upstream, {}).get("models", {}).get(raw_model, {})
            error_context = SimpleNamespace(_upstream=upstream, _realm="", billing_mode=meta.get("billing_mode", "paid"),
                cost_unit="credits" if upstream == "cline" else "USD", release=lambda: None)
            proxy.record_error(public_model, exc.status, str(exc), account=getattr(exc, "account_uid", None),
                stream=payload.get("stream", False), upstream=error_context, key=handler._key_id())
        raise
    except ValueError as exc:
        raise wb_platforms.PlatformError("request cannot be converted: " + str(exc)) from exc


def _handle(handler, payload, protocol, upstream, raw_model, public_model):
    proxy = _proxy(handler)
    manager = proxy.PLATFORMS
    _context(handler, payload, proxy)
    meta = manager.model(upstream, raw_model)
    native = meta["native_protocol"]
    payload = dict(payload, model=public_model)
    # Tokenizers and image budgets differ by model. The upstream validates its
    # context limit; never truncate or reject valid images using JSON length.
    if protocol == native:
        return _native(handler, payload, protocol, upstream, raw_model, public_model, meta, proxy)
    if protocol == "responses":
        bridge.validate_portable_responses(payload)
        chat = proxy.responses_to_chat(payload)
    elif protocol == "messages":
        # Signed reasoning and server-owned blocks must keep native Messages.
        for message in payload.get("messages") or []:
            for part in message.get("content") or [] if isinstance(message.get("content"), list) else []:
                if isinstance(part, dict) and (part.get("signature") or part.get("type") == "redacted_thinking"):
                    raise wb_platforms.PlatformError("this content block requires native Messages")
                if isinstance(part, dict) and part.get("type") not in ("text", "image", "thinking", "tool_use", "tool_result", "server_tool_use", "web_search_tool_result"):
                    raise wb_platforms.PlatformError("unsupported Messages content block: " + str(part.get("type")))
                if isinstance(part, dict) and part.get("type") == "web_search_tool_result" and isinstance(part.get("content"), list):
                    for item in part["content"]:
                        reference = item.get("encrypted_content") if isinstance(item, dict) else None
                        if reference and not str(reference).startswith(proxy.wb_messages_web.REPLAY_PREFIX):
                            raise wb_platforms.PlatformError("externally encrypted search results require native Messages")
        if payload.get("top_k") is not None or payload.get("context_management") or (payload.get("output_config") or {}).get("format"):
            raise wb_platforms.PlatformError("requested Messages option requires a native Messages upstream")
        chat = proxy.messages_to_chat(payload, replay_scope=handler._key_id())
    else:
        chat = copy.deepcopy(payload)
    chat["model"] = public_model
    session = _session(handler, chat, proxy)
    bound = handler._response_context.get("account") if handler._response_context and handler._response_context.get("bound") else None
    # Tools in a gateway web workflow retain their definitions in Chat; only
    # the wire body is converted for the model's native upstream endpoint.
    native_body = _native_body(chat, native, meta)
    lease = _open(manager, upstream, raw_model, native_body, meta, session, handler._key_id() or "", bound)
    proxy._apply_stream_idle_timeout(lease, proxy.upstream_timeouts()[1])
    account = lease.account
    raw = bridge.ChatLease(lease, native)
    t_start = wb_metrics.request_started_at()
    fp = proxy.prompt_fingerprint(chat.get("messages"))
    effort = chat.get("reasoning_effort")
    try:
        if protocol == "responses":
            namespace = chat.pop("_namespace_map", None)
            request_meta = {key: payload[key] for key in ("tools", "tool_choice", "parallel_tool_calls") if key in payload}
            method = handler._responses_stream_response if payload.get("stream") else handler._responses_nonstream_response
            return method(raw, public_model, proxy.custom_tool_names(payload.get("tools")), request_meta, fp,
                          account, t_start, namespace, base_body=chat, session_key=session, realm="", effort=effort)
        if protocol == "messages":
            method = handler._messages_stream_response if payload.get("stream") else handler._messages_nonstream_response
            flow = (proxy.wb_messages_web.MessagesWebFlow(chat, proxy.wb_messages_web.response_format(handler.headers), handler._key_id())
                    if "_messages_web_search" in chat else None)
            return method(raw, public_model, fp, account, t_start, base_body=chat, session_key=session, realm="", effort=effort, web_flow=flow)
        method = handler._chat_stream_response if payload.get("stream") else handler._chat_nonstream_response
        return method(raw, public_model, fp, account, t_start, effort=effort)
    finally:
        raw.close()


def _native(handler, payload, protocol, upstream, raw_model, public_model, meta, proxy):
    body = {key: copy.deepcopy(value) for key, value in payload.items() if not key.startswith("_")}
    if protocol == "responses":
        body["store"] = False
    if protocol == "chat" and payload.get("stream"):
        body["stream_options"] = dict(body.get("stream_options") or {}, include_usage=True)
    session = _session(handler, payload, proxy)
    bound = handler._response_context.get("account") if handler._response_context and handler._response_context.get("bound") else None
    t_start = wb_metrics.request_started_at()
    lease = _open(proxy.PLATFORMS, upstream, raw_model, body, meta, session, handler._key_id() or "", bound)
    proxy._apply_stream_idle_timeout(lease, proxy.upstream_timeouts()[1])
    account = lease.account
    if not payload.get("stream"):
        tokens, recorded = None, False
        try:
            value = lease.read(proxy.MAX_PAYLOAD_BYTES + 1)
            if len(value) > proxy.MAX_PAYLOAD_BYTES:
                raise wb_platforms.PlatformError("upstream response exceeds the size limit", 502)
            result = json.loads(value)
            result = result.get("data", result) if isinstance(result, dict) else result
            if not isinstance(result, dict) or result.get("error"):
                raise wb_platforms.PlatformError("invalid upstream response", 502)
            valid = (isinstance(result.get("choices"), list) and bool(result["choices"]) if protocol == "chat" else
                     result.get("type") == "message" and isinstance(result.get("content"), list) if protocol == "messages" else
                     result.get("object") == "response" and result.get("status") in ("completed", "incomplete") and isinstance(result.get("output"), list))
            if not valid:
                raise wb_platforms.PlatformError("upstream response does not match its protocol", 502)
            lease.generation_id = result.get("id")
            tokens = bridge.usage(result.get("usage"), protocol, upstream)
            result["model"] = public_model
            if protocol == "responses":
                result = handler._finish_response(result, public_model, account.uid, upstream)
            proxy.record_usage(public_model, tokens, stream=False, account=account.uid, upstream=lease,
                key=handler._key_id(), elapsed_ms=int((time.time()-t_start)*1000))
            recorded = True
            return handler._json(200, result)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            if not recorded:
                proxy.record_usage(public_model, tokens, stream=False, account=account.uid, upstream=lease,
                    key=handler._key_id(), outcome="client_aborted")
        except Exception as exc:
            error = exc if isinstance(exc, (wb_platforms.PlatformError, wb_responses.ResponseError)) else wb_platforms.PlatformError("upstream response failed", 502)
            if not recorded:
                proxy.record_error(public_model, error.status, str(error), usage=tokens, account=account.uid, upstream=lease, key=handler._key_id())
            error.recorded = True
            raise error from (exc if error is not exc else None)
        finally:
            lease.close()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "close")
    if proxy.cors_origin_allowed(handler.path):
        handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    current_usage, tokens, done, recorded = {}, None, False, False
    finished_choices = set()
    timing = wb_metrics.GenerationTiming(t_start)
    try:
        with wb_stream.HeartbeatWriter(handler.wfile, lambda: lease) as writer:
            for event, data in bridge.sse_events(timing.wrap(writer.iterate(lease))):
                if data == "[DONE]":
                    if protocol != "chat":
                        continue
                    done = True
                    writer.write(bridge.frame(event, data))
                    writer.flush()
                    continue
                if not isinstance(data, dict):
                    raise wb_platforms.PlatformError("invalid upstream SSE event", 502)
                kind = data.get("type") or event
                generation_id = ((data.get("response") or data.get("message") or {}).get("id")
                                 if protocol != "chat" else data.get("id"))
                if generation_id:
                    lease.generation_id = generation_id
                if data.get("error") or kind in ("error", "response.failed"):
                    raise wb_platforms.PlatformError("upstream generation failed", 502)
                if protocol == "messages":
                    if kind == "message_start":
                        message = data.get("message") or {}
                        message["model"] = public_model
                        current_usage.update(message.get("usage") or {})
                    elif kind == "message_delta":
                        current_usage.update(data.get("usage") or {})
                    elif kind == "message_stop":
                        done = True
                    tokens = bridge.usage(current_usage, protocol, upstream)
                elif protocol == "responses":
                    result = data.get("response") or {}
                    if result:
                        result["model"] = public_model
                        if result.get("usage"):
                            tokens = bridge.usage(result["usage"], protocol, upstream)
                    if kind in ("response.completed", "response.incomplete"):
                        done = True
                        # Persist/settle before the final event is delivered.
                        outgoing = handler._response_frame(bridge.frame(kind, data), public_model, account.uid, upstream)
                        proxy.record_usage(public_model, tokens, stream=True, account=account.uid, upstream=lease,
                            key=handler._key_id(), elapsed_ms=int((time.time()-t_start)*1000), **timing.fields())
                        recorded = True
                    else:
                        outgoing = handler._response_frame(bridge.frame(kind, data), public_model, account.uid, upstream)
                    writer.write(outgoing)
                    writer.flush()
                    continue
                else:
                    data["model"] = public_model
                    if data.get("usage"):
                        tokens = bridge.usage(data["usage"], protocol, upstream)
                    for choice in data.get("choices") or []:
                        if choice.get("finish_reason") is not None:
                            finished_choices.add(choice.get("index", 0))
                writer.write(bridge.frame(event, data))
                writer.flush()
            if protocol == "chat" and len(finished_choices) >= (lease.expected_choices or 1):
                done = True
            if not done:
                raise wb_platforms.PlatformError("upstream ended without a terminal event", 502, "upstream_stream_error")
            if not recorded:
                proxy.record_usage(public_model, tokens, stream=True, account=account.uid, upstream=lease,
                    key=handler._key_id(), elapsed_ms=int((time.time()-t_start)*1000), **timing.fields())
                recorded = True
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        if not recorded:
            proxy.record_usage(public_model, tokens, stream=True, account=account.uid, upstream=lease, key=handler._key_id(),
                outcome="client_aborted", elapsed_ms=int((time.time()-t_start)*1000), **timing.fields())
    except Exception as exc:
        if not recorded:
            proxy.record_error(public_model, 502, "upstream stream failed", usage=tokens, stream=True, account=account.uid,
                               upstream=lease, key=handler._key_id(), outcome="upstream_aborted")
        try:
            error = {"type": "error", "error": {"type": "api_error", "message": str(exc), "code": getattr(exc, "code", "upstream_stream_error")}}
            if protocol == "responses":
                error = {"type": "response.failed", "response": {"id": handler._response_context["id"], "object": "response", "model": public_model,
                        "status": "failed", "error": error["error"]}}
            handler.wfile.write(bridge.frame(error["type"] if protocol != "chat" else "", error))
            handler.wfile.flush()
        except OSError:
            pass
    finally:
        lease.close()
