"""Channel-scoped model aliases and switches over the private settings store."""
import copy

import wb_settings

PREFIXES = {"cline": "cline/", "opencode_zen": "opencode/", "commandcode": "commandcode/"}
CHANNELS = ("workbuddy-cn", "workbuddy-intl", *PREFIXES)


class PolicyError(ValueError):
    def __init__(self, message, status=400, code="invalid_model_policy"):
        super().__init__(message)
        self.status, self.code = status, code


def channel_for(upstream, realm=None):
    return {"cn": "workbuddy-cn", "intl": "workbuddy-intl"}.get(realm) if upstream == "workbuddy" else upstream


def canonical_id(channel, model_id, real_ids=None):
    if channel == "cline" and isinstance(model_id, str) and model_id.startswith("cline/") and model_id not in (real_ids or ()):
        return model_id[len("cline/"):]
    return model_id


def normalize_rules(channel, rules, legacy=False):
    if channel != "cline" or not legacy:
        return rules
    result = {}
    for model_id, policy in rules.items():
        target = canonical_id(channel, model_id)
        result[target] = dict(policy, alias=canonical_id(channel, policy.get("alias") or "")) if isinstance(policy, dict) else policy
    return result


def _legacy(data, channel):
    return (data.get("model_policy_formats") or {}).get(channel) != "native"


def _mark_native(data, channel):
    if channel == "cline":
        data["model_policy_formats"] = dict(data.get("model_policy_formats") or {}, cline="native")


def policies(directory, channel):
    if channel not in CHANNELS:
        raise PolicyError("invalid model channel")
    data = wb_settings.load(directory)
    channels = data.get("model_policies") or {}
    rules = channels.get(channel, {}) if isinstance(channels, dict) else {}
    return normalize_rules(channel, rules, _legacy(data, channel)) if isinstance(rules, dict) else {}


def rule(rules, model_id):
    value = rules.get(model_id)
    return value if isinstance(value, dict) else {}


def alias_id(channel, alias):
    if channel == "cline":
        return alias
    prefix = PREFIXES.get(channel, "")
    return prefix + alias if alias and prefix and not alias.startswith(prefix) else alias


def decorate(entries, rules, channel):
    """One administrative row per real model, including disabled rows."""
    result = []
    for entry in entries:
        model_id = entry["id"]
        policy = rule(rules, model_id)
        result.append(dict(entry, channel=channel, canonical_id=model_id, is_alias=False,
                           alias=alias_id(channel, policy.get("alias") or ""),
                           enabled=policy.get("enabled") is not False))
    return result


def expand(entries, rules, channel, real_ids=None):
    """Keep the original ID and add its alias, sharing the same entitlement."""
    real_ids = set(real_ids or ()) | {entry["id"] for entry in entries}
    result = []
    for entry in decorate(entries, rules, channel):
        if not entry["enabled"]:
            continue
        result.append(entry)
        alias = entry["alias"]
        # An upstream may introduce a real ID that was formerly our alias.
        # The real model always owns that ID; never silently route it elsewhere.
        if alias and alias not in real_ids:
            result.append(dict(entry, id=alias, is_alias=True))
    return result


def resolve(directory, channel, model_id, real_ids=None):
    rules = policies(directory, channel)
    aliases = {alias_id(channel, value.get("alias") or "") for value in rules.values() if isinstance(value, dict)}
    model_id = canonical_id(channel, model_id, set(real_ids or ()) | aliases)
    canonical = model_id
    if real_ids is None or model_id not in real_ids:
        for target, policy in rules.items():
            if isinstance(policy, dict) and policy.get("alias") and alias_id(channel, policy["alias"]) == model_id:
                canonical = target
                break
    if rule(rules, canonical).get("enabled") is False:
        raise PolicyError("model is disabled in this channel", 403, "model_disabled")
    return canonical


def update(directory, channel, model_id, patch, real_ids):
    if channel not in CHANNELS:
        raise PolicyError("invalid model channel")
    model_id = canonical_id(channel, model_id, real_ids)
    if not isinstance(model_id, str) or model_id not in real_ids:
        raise PolicyError("model is not in this channel's catalogue", 404, "model_not_found")
    if "enabled" in patch and type(patch["enabled"]) is not bool:
        raise PolicyError("enabled must be a boolean")
    if not any(field in patch for field in ("alias", "enabled")):
        raise PolicyError("pass alias or enabled")
    with wb_settings._lock:
        data = wb_settings.load(directory)
        channels = copy.deepcopy(data.get("model_policies") or {})
        rules = channels[channel] = normalize_rules(channel, channels.get(channel) or {}, _legacy(data, channel))
        value = dict(rule(rules, model_id))
        if "alias" in patch:
            alias = patch["alias"]
            if not isinstance(alias, str):
                raise PolicyError("alias must be a string")
            alias = alias.strip()
            if len(alias) > 256 or any(character.isspace() or ord(character) < 32 for character in alias):
                raise PolicyError("alias must be at most 256 characters without whitespace")
            alias = canonical_id(channel, alias) if channel == "cline" else alias_id(channel, alias)
            own_prefix = PREFIXES.get(channel)
            if alias and any(alias.startswith(prefix) and prefix != own_prefix for prefix in PREFIXES.values()):
                raise PolicyError("alias must stay in the selected channel")
            if patch["alias"].strip() == own_prefix:
                raise PolicyError("alias must contain a model name")
            if alias and alias in real_ids:
                raise PolicyError("alias conflicts with an existing model ID")
            if alias and any(target != model_id and alias_id(channel, rule(rules, target).get("alias") or "") == alias
                             for target in rules):
                raise PolicyError("alias is already assigned in this channel")
            value["alias"] = alias
        if "enabled" in patch:
            value["enabled"] = patch["enabled"]
        rules[model_id] = value
        data["model_policies"] = channels
        _mark_native(data, channel)
        wb_settings.save(directory, data)
    return {"model_id": model_id, "channel": channel, "alias": value.get("alias") or "",
            "enabled": value.get("enabled") is not False}


def update_enabled(directory, channel, model_ids, enabled, real_ids):
    """Validate the whole selection before one atomic settings write."""
    if channel not in CHANNELS:
        raise PolicyError("invalid model channel")
    if type(enabled) is not bool:
        raise PolicyError("enabled must be a boolean")
    if not isinstance(model_ids, list) or not model_ids or any(not isinstance(value, str) for value in model_ids):
        raise PolicyError("model_ids must be a non-empty list of model IDs")
    targets = list(dict.fromkeys(canonical_id(channel, value, real_ids) for value in model_ids))
    if any(value not in real_ids for value in targets):
        raise PolicyError("model is not in this channel's catalogue", 404, "model_not_found")
    with wb_settings._lock:
        data = wb_settings.load(directory)
        channels = copy.deepcopy(data.get("model_policies") or {})
        rules = channels[channel] = normalize_rules(channel, channels.get(channel) or {}, _legacy(data, channel))
        for model_id in targets:
            rules[model_id] = dict(rule(rules, model_id), enabled=enabled)
        data["model_policies"] = channels
        _mark_native(data, channel)
        wb_settings.save(directory, data)
    return {"channel": channel, "model_ids": targets, "enabled": enabled, "count": len(targets)}
