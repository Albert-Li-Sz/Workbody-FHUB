"""Native OpenCode forwarding; gateway keys never become upstream credentials."""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URLS = {"zen": "https://opencode.ai/zen/v1", "go": "https://opencode.ai/zen/go/v1"}
DEFAULTS = {"enabled": False, "mode": "zen", "base_url": BASE_URLS["zen"],
            "api_key": "", "proxy_slot": "", "timeout_seconds": 120}
PATHS = {"/models", "/chat/completions", "/responses", "/messages", "/messages/count_tokens"}
MAX_RESPONSE_BYTES = 50 * 1024 * 1024


def validate_config(raw, existing=None):
    if not isinstance(raw, dict):
        raise ValueError("opencode must be an object")
    allowed = set(DEFAULTS) | {"clear_api_key"}
    if set(raw) - allowed:
        raise ValueError("unknown OpenCode setting")
    out = dict(DEFAULTS, **(existing or {}))
    for field in ("enabled", "clear_api_key"):
        if field in raw and not isinstance(raw[field], bool):
            raise ValueError("%s must be true or false" % field)
    for field in ("mode", "base_url", "api_key", "proxy_slot"):
        if field in raw and not isinstance(raw[field], str):
            raise ValueError("%s must be a string" % field)
    out.update({k: v for k, v in raw.items() if k != "clear_api_key"})
    out["mode"] = out["mode"].strip().lower()
    if out["mode"] not in ("zen", "go", "custom"):
        raise ValueError("OpenCode mode must be zen, go or custom")
    if out["mode"] in BASE_URLS:
        out["base_url"] = BASE_URLS[out["mode"]]
    else:
        out["base_url"] = out["base_url"].strip().rstrip("/")
    try:
        url = urllib.parse.urlsplit(out["base_url"])
        valid = (url.scheme in ("https", "http") and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment)
        url.port
    except ValueError:
        valid = False
    if not valid or any(c.isspace() for c in out["base_url"]):
        raise ValueError("OpenCode base URL must be http(s), without credentials, query or fragment")
    # Blank means keep. Clearing a stored secret is an explicit operation.
    if raw.get("clear_api_key"):
        out["api_key"] = ""
    elif "api_key" in raw and not raw["api_key"].strip():
        out["api_key"] = (existing or {}).get("api_key", "")
    out["api_key"] = out["api_key"].strip()
    if any(c.isspace() for c in out["api_key"]):
        raise ValueError("OpenCode API key cannot contain whitespace")
    timeout = out["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
        raise ValueError("OpenCode timeout must be a whole number from 1 to 600 seconds")
    out["proxy_slot"] = out["proxy_slot"].strip()
    return out


def configured(config):
    return bool(config.get("enabled") and config.get("api_key"))


def public_config(config):
    return {k: config[k] for k in DEFAULTS if k != "api_key"} | {
        "api_key_set": bool(config.get("api_key")), "configured": configured(config)}


class ConfigurationError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the upstream secret to another host.


def open_request(config, path, payload=None, inbound_headers=None, slots=()):
    """Return a closable native HTTP response, including non-2xx responses."""
    path = path[3:] if path.startswith("/v1/") else path
    if path not in PATHS:
        raise ValueError("OpenCode supports chat/completions, responses and messages; use their native endpoints")
    if not configured(config):
        raise ConfigurationError("OpenCode 出口尚未配置，请在设置中启用上游并填写上游 Key")
    proxy = ""
    slot_id = config.get("proxy_slot")
    if slot_id:
        slot = next((s for s in slots if s.get("id") == slot_id and s.get("enabled", True)), None)
        if not slot or not slot.get("url"):
            raise ConfigurationError("OpenCode 绑定的代理槽不存在或已停用，请检查出口配置")
        proxy = slot["url"]
    headers = {"Accept": "text/event-stream, application/json", "Accept-Encoding": "identity",
               "User-Agent": "workbuddy2api-hub/opencode"}
    if path.startswith("/messages"):
        inbound = inbound_headers or {}
        headers["x-api-key"] = config["api_key"]
        headers["anthropic-version"] = inbound.get("anthropic-version") or "2023-06-01"
        if inbound.get("anthropic-beta"):
            headers["anthropic-beta"] = inbound["anthropic-beta"]
    else:
        headers["Authorization"] = "Bearer " + config["api_key"]
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(config["base_url"] + path, data=body, headers=headers)
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
    try:
        return opener.open(request, timeout=config["timeout_seconds"])
    except urllib.error.HTTPError as response:
        return response


def response_usage(document):
    if not isinstance(document, dict):
        return None
    if isinstance(document.get("response"), dict):
        document = document["response"]
    return document.get("usage") if isinstance(document.get("usage"), dict) else None


def normalize_usage(usage, anthropic=False):
    """Normalize accounting only; native response bodies remain untouched."""
    if not isinstance(usage, dict) or not any(k in usage for k in (
            "prompt_tokens", "input_tokens", "completion_tokens", "output_tokens")):
        return None
    out = dict(usage)
    def count(field):
        value = usage.get(field, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    prompt = count("prompt_tokens") if "prompt_tokens" in usage else count("input_tokens")
    if anthropic:
        prompt += count("cache_read_input_tokens") + count("cache_creation_input_tokens")
    output = count("completion_tokens") if "completion_tokens" in usage else count("output_tokens")
    out.update(prompt_tokens=prompt, completion_tokens=output,
               total_tokens=count("total_tokens") or prompt + output)
    if isinstance(usage.get("output_tokens_details"), dict):
        out["completion_tokens_details"] = usage["output_tokens_details"]
    out.pop("credit", None)  # OpenCode has no WorkBuddy credit ledger.
    return out


class StreamUsage:
    """Observe native SSE usage/termination without modifying forwarded bytes."""
    def __init__(self):
        self.buffer = b""
        self.data = []
        self.usage = {}
        self.completed = False
        self.failed = False

    def feed(self, chunk):
        self.buffer += chunk
        # Metadata is best effort; an oversized event must not retain content
        # unboundedly. It is still forwarded unchanged to the client.
        if len(self.buffer) + sum(map(len, self.data)) > 1024 * 1024:
            self.buffer = b""
            self.data = []
            return
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line:
                self._event()
            elif line.startswith(b"data:"):
                self.data.append(line[5:].lstrip(b" "))

    def _event(self):
        data, self.data = b"\n".join(self.data), []
        if data == b"[DONE]":
            self.completed = True
            return
        try:
            event = json.loads(data)
        except (ValueError, UnicodeError):
            return
        if not isinstance(event, dict):
            return
        usage = response_usage(event)
        if event.get("type") == "message_start":
            usage = response_usage(event.get("message"))
        if usage:
            self.usage.update(usage)
        kind = event.get("type")
        if kind in ("response.completed", "message_stop"):
            self.completed = True
        elif kind in ("error", "response.failed", "response.incomplete"):
            self.failed = True
