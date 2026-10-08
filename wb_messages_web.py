"""Messages server search, source blocks and bounded local history replay.

The backend is DDG, not DeepSeek's search service. encrypted_content carries
an opaque FHUB reference, understood only by this gateway; it is never a
fabricated DeepSeek ciphertext. SQLite retains references across restarts.
"""
from collections import OrderedDict
import copy
import json
import re
import secrets
import threading
import time

import wb_database
import wb_webflow
import wb_webtools as W

REPLAY_PREFIX = "fhub_web_v1:"
REPLAY_TTL = 7 * 86400
REPLAY_LIMIT = 4096
_replay = OrderedDict()
_replay_lock = threading.Lock()


def search_options(tools):
    """Recognize server declarations only; ordinary functions stay client-owned."""
    found = None
    if tools is not None and not isinstance(tools, list):
        raise ValueError("tools must be an array")
    for tool in tools or []:
        if not isinstance(tool, dict):
            raise ValueError("tools entries must be objects")
        typ = tool.get("type") or ""
        if not isinstance(typ, str):
            raise ValueError("tool type must be a string")
        if typ != "web_search" and not typ.startswith("web_search_"):
            continue
        if typ not in ("web_search", "web_search_20250305"):
            raise ValueError("unsupported Messages search version: " + typ)
        if found is not None:
            raise ValueError("declare only one Messages server web_search tool")
        if tool.get("name") != W.WEB_SEARCH_NAME:
            raise ValueError("Messages server web_search must be named web_search")
        unsupported = set(tool) - {"type", "name", "max_uses", "allowed_domains",
                                    "blocked_domains", "cache_control"}
        if unsupported:
            raise ValueError("unsupported local search options: " + ", ".join(sorted(unsupported)))
        max_uses = tool.get("max_uses", 5)
        if type(max_uses) is not int or max_uses < 1:
            raise ValueError("web_search.max_uses must be a positive integer")
        if tool.get("allowed_domains") is not None and tool.get("blocked_domains") is not None:
            raise ValueError("web_search cannot combine allowed_domains and blocked_domains")
        found = {"max_uses": max_uses}
        for key in ("allowed_domains", "blocked_domains"):
            domains = tool.get(key)
            if domains is None:
                continue
            if not isinstance(domains, list) or len(domains) > 100:
                raise ValueError("web_search.%s must be an array of at most 100 domains" % key)
            normalized = []
            for domain in domains:
                if not isinstance(domain, str):
                    raise ValueError("web_search domain entries must be strings")
                try:
                    host = domain.strip().rstrip(".").lower().encode("idna").decode("ascii")
                except UnicodeError:
                    raise ValueError("invalid web_search domain") from None
                if len(host) > 253 or not re.fullmatch(
                        r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
                    raise ValueError("web_search domains must be hostnames without a URL scheme or path")
                if host not in normalized:
                    normalized.append(host)
            found[key] = normalized
    return found


def response_format(headers):
    mode = (headers.get("X-FHUB-Web-Format") or "auto").strip().lower()
    if mode not in ("auto", "native", "text"):
        raise ValueError("X-FHUB-Web-Format must be auto, native or text")
    if mode == "auto":
        # DSH's main LLM supplies this header; its auxiliary search provider
        # does not. Both share a User-Agent, so UA detection is insufficient.
        return "text" if headers.get("x-deepseek-harness-user-id") is not None else "native"
    return mode


def _remember(row, scope):
    reference = REPLAY_PREFIX + secrets.token_urlsafe(24)
    expires = time.time() + REPLAY_TTL
    payload = {"scope": scope or "", "result": copy.deepcopy(row)}
    database = wb_database.DATABASE
    if database:
        database.put_web_result(reference, payload, expires, REPLAY_LIMIT)
    else:
        with _replay_lock:
            _replay[reference] = (expires, payload)
            while len(_replay) > REPLAY_LIMIT:
                _replay.popitem(last=False)
    return reference


def _recall(reference, scope):
    database = wb_database.DATABASE
    if database:
        payload = database.get_web_result(reference)
    else:
        with _replay_lock:
            item = _replay.get(reference)
            payload = item[1] if item and item[0] > time.time() else None
            if item and payload is None:
                _replay.pop(reference, None)
    if not payload or payload.get("scope") != (scope or ""):
        raise ValueError("FHUB search history is expired or belongs to another API key; resend visible search results")
    return copy.deepcopy(payload["result"])


def citations_from_blocks(blocks):
    cited = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for citation in block.get("citations") or []:
            if isinstance(citation, dict) and citation.get("url") and citation.get("cited_text"):
                cited.setdefault(str(citation["url"]), []).append(str(citation["cited_text"]))
    return cited


def text_with_citations(block):
    text = block.get("text") or ""
    notes = []
    for citation in block.get("citations") or []:
        if isinstance(citation, dict) and citation.get("url"):
            notes.append("%s (%s): %s" % (citation.get("title") or citation["url"],
                                         citation["url"], citation.get("cited_text") or ""))
    return str(text) + ("\n[Web citations]\n" + "\n".join(notes) if notes else "")


def history_result_text(block, cited, scope=None):
    content = block.get("content")
    if isinstance(content, dict) and content.get("type") == "web_search_tool_result_error":
        return "Error: web_search " + str(content.get("error_code") or "unavailable")
    if not isinstance(content, list):
        raise ValueError("web_search_tool_result.content must be an array or search error")
    rows, opaque = [], False
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "web_search_result":
            raise ValueError("unsupported web_search_tool_result content item")
        reference = item.get("encrypted_content")
        if isinstance(reference, str) and reference.startswith(REPLAY_PREFIX):
            row = _recall(reference, scope)
            if item.get("url") != row["url"]:
                raise ValueError("FHUB search history URL does not match its reference")
        else:
            row = {"url": str(item.get("url") or ""), "title": str(item.get("title") or ""),
                   "snippet": "\n".join(cited.get(str(item.get("url") or ""), []))
                              or str(item.get("snippet") or "")}
            if reference and not row["snippet"]:
                opaque = True
        rows.append(row)
    text = W.format_search_results({"query": "historical search", "results": rows})
    if opaque:
        text += "\nFull content of externally encrypted results is unavailable to FHUB; only visible sources are retained."
    return text


def call_block(call):
    try:
        arguments = json.loads(call.get("arguments") or "{}")
    except (TypeError, ValueError):
        arguments = {}
    return {"type": "server_tool_use", "id": call["id"], "name": W.WEB_SEARCH_NAME,
            "input": arguments if isinstance(arguments, dict) else {}}


class MessagesWebFlow(wb_webflow.WebToolFlow):
    def __init__(self, body, mode="native", scope=None):
        super().__init__(body)
        self.options = body["_messages_web_search"]
        self.mode, self.scope = mode, scope
        self.searches = 0
        self.confirmed_output_tokens = 0
        self.completed_blocks = []
        self._search_results = []

    def is_internal_tool(self, name):
        return name == W.WEB_SEARCH_NAME

    def exhausted(self):
        return super().exhausted() or self.searches >= self.options["max_uses"]

    def remaining_output_tokens(self):
        limit = self.body.get("max_tokens")
        if type(limit) is not int:
            return None
        return max(0, limit - self.confirmed_output_tokens)

    def followup_body(self):
        body = super().followup_body()
        remaining = self.remaining_output_tokens()
        if remaining is not None:
            if remaining == 0:
                raise wb_webflow.WebToolLimitError("Messages max_tokens budget exhausted")
            body["max_tokens"] = remaining
        if self.rounds and body.get("tool_choice") == "required":
            body["tool_choice"] = "auto"
        return body

    def iter_upstream(self, upstream, set_timeout):
        finished = False
        raw = super().iter_upstream(upstream, set_timeout)
        try:
            for frame in raw:
                text = frame.decode("utf-8", "replace").strip()
                done = False
                if text.startswith("data:"):
                    data = text[5:].strip()
                    if data == "[DONE]":
                        finished = done = True
                    else:
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            chunk = {}
                        if isinstance(chunk, dict):
                            if chunk.get("error"):
                                raise RuntimeError("Messages upstream returned an error: %s" % chunk["error"])
                            finished = finished or any(c.get("finish_reason") for c in chunk.get("choices") or [])
                yield frame
                if done:
                    return
            if not finished:
                raise RuntimeError("Messages upstream stream ended before completion")
        finally:
            raw.close()
            used = (self.current_usage or {}).get("completion_tokens")
            if type(used) is int and used >= 0:
                self.confirmed_output_tokens += used

    def internal_calls(self, message):
        return [{"id": tc["id"], "name": (tc.get("function") or {})["name"],
                 "arguments": (tc.get("function") or {}).get("arguments") or "{}"}
                for tc in message.get("tool_calls") or []
                if self.is_internal_tool((tc.get("function") or {}).get("name"))]

    def execute_call(self, name, arguments):
        if name != W.WEB_SEARCH_NAME:
            raise ValueError("Messages server tool is not owned by FHUB")
        if self.searches >= self.options["max_uses"]:
            result = {"error": "Error: web_search max_uses exceeded", "error_code": "max_uses_exceeded"}
        else:
            self.searches += 1
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                if not isinstance(args, dict):
                    raise ValueError("search input must be an object")
                result = W.search_results(W.query_args(args), args.get("numResults") or 5,
                                          self.options.get("allowed_domains"), self.options.get("blocked_domains"))
            except (ValueError, TypeError):
                result = {"error": "Error: web_search input must be valid JSON", "error_code": "invalid_input"}
            except Exception as exc:
                result = {"error": "Error: web_search backend unavailable (%s)" % type(exc).__name__}
        self._search_results.append(result)
        return W.format_search_results(result)

    def execute(self, calls, assistant_message=None):
        self._search_results = []
        results = super().execute(calls, assistant_message)
        if self.mode == "text":
            self.completed_blocks = []
            return results
        blocks, excerpts = [], []
        for call, result in zip(calls, self._search_results):
            if result.get("error"):
                content = {"type": "web_search_tool_result_error",
                           "error_code": result.get("error_code") or "unavailable"}
            else:
                content = []
                for row in result.get("results") or []:
                    content.append({"type": "web_search_result", "url": row["url"],
                                    "title": row["title"], "encrypted_content": _remember(row, self.scope)})
            blocks.append({"type": "web_search_tool_result", "tool_use_id": call["id"], "content": content})
            # DSH's search provider obtains snippets from text citations.
            # Emit the real backend excerpts as attributed text, not as an
            # invented citation to a model-generated answer.
            for item, row in zip(content if isinstance(content, list) else [], result.get("results") or []):
                if row.get("snippet"):
                    excerpts.append({"type": "text", "text": row["snippet"], "citations": [{
                        "type": "web_search_result_location", "url": row["url"], "title": row["title"],
                        "cited_text": row["snippet"], "encrypted_index": item["encrypted_content"]}]})
        self.completed_blocks = blocks + excerpts
        return results

    def output_results(self):
        if self.mode == "text":
            return [{"type": "text", "text": self.result_text()}]
        return self.completed_blocks
