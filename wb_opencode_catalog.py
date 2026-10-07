"""Provider-specific model metadata without changing inference routing.

OpenCode publishes its catalogue at /zen/v1/models; models.dev is the model
index maintained by the OpenCode team. Metadata is not an account health test.
Only standard-library dependencies are used.
"""
import copy
import gzip
import io
import json
import os
import threading
import time
import urllib.request

import wb_storage

OPENCODE_MODELS_URL = "https://opencode.ai/zen/v1/models"
MODELSDEV_URL = "https://models.dev/api.json"
CACHE_TTL = 300
FAILURE_TTL = 30
FETCH_TIMEOUT = 5
MAX_BODY = 32 * 1024 * 1024
_lock = threading.Lock()
_cache = {}
_failures = {}


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if 0 < result <= 10 ** 9 else None


def _model(mid, metadata=None, listed=None):
    metadata = metadata if isinstance(metadata, dict) else {}
    item = {"id": mid, "object": "model", "owned_by": "opencode", "channel": "opencode"}
    if listed and isinstance(listed.get("created"), (int, float)):
        item["created"] = listed["created"]
    for field in ("name", "description"):
        if isinstance(metadata.get(field), str):
            item[field] = metadata[field]
    limit = metadata.get("limit") or {}
    if isinstance(limit, dict):
        for source, target in (("context", "context_length"), ("output", "max_output_tokens")):
            value = _positive_int(limit.get(source))
            if value:
                item[target] = value
    modalities = metadata.get("modalities") or {}
    if isinstance(modalities, dict) and isinstance(modalities.get("input"), list):
        item["input_modalities"] = [v for v in modalities["input"] if isinstance(v, str)]
        item["supports_vision"] = "image" in item["input_modalities"]
    for source, target in (("tool_call", "supports_tool_calls"), ("reasoning", "supports_reasoning")):
        if isinstance(metadata.get(source), bool):
            item[target] = metadata[source]
    efforts = []
    options = metadata.get("reasoning_options")
    for option in options if isinstance(options, list) else []:
        if isinstance(option, dict) and option.get("type") == "effort" \
                and isinstance(option.get("values"), list):
            efforts.extend(v for v in option["values"] if isinstance(v, str))
    if efforts:
        item["reasoning_efforts"] = efforts
    cost = metadata.get("cost")
    if isinstance(cost, dict):
        item["pricing"] = {k: v for k, v in cost.items()
                           if k in ("input", "output", "cache_read", "cache_write")
                           and isinstance(v, (int, float)) and not isinstance(v, bool)
                           and 0 <= v < float("inf")}
        item["pricing_unit"] = "USD per million tokens"
    return item


def build_opencode_catalog(index, live=None):
    """Combine exact upstream IDs with OpenCode's metadata, preserving -free."""
    provider = index.get("opencode") if isinstance(index, dict) else None
    metadata = provider.get("models") if isinstance(provider, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    listed = live.get("data") if isinstance(live, dict) else None
    rows = {}
    if isinstance(listed, list):
        for entry in listed:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"].strip():
                rows[entry["id"]] = entry
    live_available = bool(rows)
    if not rows:
        rows = {mid: {} for mid, info in metadata.items()
                if isinstance(mid, str) and mid.strip() and isinstance(info, dict)}
    if not rows:
        raise ValueError("OpenCode catalogue has no model entries")
    return {"object": "list", "channel": "opencode", "realm": None,
            "source": "opencode+models.dev" if live_available and metadata else
                      "opencode" if live_available else "models.dev",
            "catalogue_only": True, "inference_ready": False, "stale": False,
            "data": [_model(mid, metadata.get(mid), rows[mid]) for mid in sorted(rows)]}


def _get_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "User-Agent": "workbody-hub/catalog"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        compressed = response.headers.get("Content-Encoding", "").lower() == "gzip"
        body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("model catalogue exceeds size limit")
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("model catalogue exceeds size limit")
    return json.loads(body.decode("utf-8"))


def opencode_catalog(directory):
    """Bounded fetch, a separate cache, and explicit stale data on failure."""
    key = os.path.abspath(directory)
    path = os.path.join(key, "catalogs", "opencode.json")
    with _lock:
        now = time.time()
        if _failures.get(key, 0) > now:
            raise ValueError("OpenCode model catalogue is temporarily unavailable")
        cached = _cache.get(key)
        if cached is None:
            try:
                with open(path, encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict) and isinstance(stored.get("catalog"), dict) \
                        and stored["catalog"].get("channel") == "opencode" \
                        and isinstance(stored["catalog"].get("data"), list):
                    cached = {"at": float(stored.get("at") or 0), "catalog": stored["catalog"]}
            except (OSError, ValueError, TypeError):
                pass
        if cached and now - cached["at"] < CACHE_TTL:
            _cache[key] = cached
            return copy.deepcopy(cached["catalog"])
        live = index = None
        for url, target in ((OPENCODE_MODELS_URL, "live"), (MODELSDEV_URL, "index")):
            try:
                payload = _get_json(url)
                if target == "live":
                    live = payload
                else:
                    index = payload
            except Exception:
                pass
        try:
            catalog = build_opencode_catalog(index, live)
        except ValueError:
            if cached and cached["catalog"].get("data"):
                catalog = copy.deepcopy(cached["catalog"])
                catalog["stale"] = True
                _cache[key] = {"at": now - CACHE_TTL + FAILURE_TTL, "catalog": catalog}
                return catalog
            _failures[key] = time.time() + FAILURE_TTL
            raise ValueError("OpenCode model catalogue is temporarily unavailable") from None
        _failures.pop(key, None)
        fetched_at = time.time()
        catalog["fetched_at"] = fetched_at
        _cache[key] = {"at": fetched_at, "catalog": catalog}
        try:
            wb_storage.write_private_json(path, {"at": fetched_at, "catalog": catalog})
        except OSError:
            pass  # A read-only data volume can still display live metadata.
        return copy.deepcopy(catalog)
