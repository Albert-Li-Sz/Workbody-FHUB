"""Cline provider policies for the direct and planner routing pipelines."""
import copy
import re


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError("Cline route must be an object")
    mode = raw.get("mode", "auto")
    pipeline = raw.get("pipeline", "auto")
    sort = raw.get("sort") or None
    if mode not in ("auto", "strict", "preferred") or pipeline not in ("auto", "direct", "planner"):
        raise ValueError("invalid Cline routing mode or pipeline")
    if sort not in (None, "cost", "latency", "throughput", "ttft", "tps"):
        raise ValueError("invalid provider sort")
    lists = {}
    for field in ("providers", "excluded", "known_providers"):
        values = raw.get(field) or []
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(value, str) or
                not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:/ -]{0,99}", value) for value in values):
            raise ValueError("invalid provider list: " + field)
        lists[field] = list(dict.fromkeys(values))
    if mode != "auto" and not lists["providers"]:
        raise ValueError("select at least one provider")
    if lists["excluded"] and pipeline in ("auto", "planner") and not lists["known_providers"]:
        raise ValueError("planner exclusions require the available provider list")
    return {"mode": mode, "pipeline": pipeline, "sort": sort, **lists}


def apply(body, policy):
    if not policy:
        return body
    policy = validate(policy)
    result = copy.deepcopy(body)
    chosen = [value for value in policy["providers"] if value not in policy["excluded"]]
    allowed = [value for value in policy["known_providers"] if value not in policy["excluded"]]
    direct, planner = {}, {}
    if policy["mode"] == "strict":
        if not chosen:
            raise ValueError("all selected providers are excluded")
        direct["only"] = chosen
        planner["only"] = chosen
    elif policy["mode"] == "preferred":
        if not chosen:
            raise ValueError("all selected providers are excluded")
        direct["order"] = chosen
        planner["order"] = chosen
    if policy["excluded"]:
        direct["ignore"] = policy["excluded"]
        if not allowed:
            raise ValueError("all known providers are excluded")
        if policy["mode"] != "strict":
            planner["only"] = allowed
    if policy["sort"]:
        direct["sort"] = {"ttft": "latency", "tps": "throughput"}.get(policy["sort"], policy["sort"])
        planner["sort"] = {"latency": "ttft", "throughput": "tps"}.get(policy["sort"], policy["sort"])
    if policy["pipeline"] in ("auto", "direct") and direct:
        result["provider"] = dict(result.get("provider") or {}, **direct)
    if policy["pipeline"] in ("auto", "planner") and planner:
        options = result.setdefault("providerOptions", {})
        options["gateway"] = dict(options.get("gateway") or {}, **planner)
    return result


def observed(value):
    if not isinstance(value, dict):
        return None
    value = value.get("data", value)
    choices = value.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") or first.get("delta") or {}
    metadata = message.get("provider_metadata") or value.get("provider_metadata") or {}
    gateway = (metadata.get("gateway") or {}).get("routing") or {}
    provider = gateway.get("finalProvider") or value.get("provider")
    if not isinstance(provider, str) or len(provider) > 100:
        return None
    return {"provider": provider, "pipeline": "planner" if gateway.get("finalProvider") else "direct",
            "model": str(value.get("model") or "")[:300]}
