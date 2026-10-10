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


def policies(directory, channel):
    if channel not in CHANNELS:
        raise PolicyError("invalid model channel")
    channels = wb_settings.load(directory).get("model_policies") or {}
    rules = channels.get(channel, {}) if isinstance(channels, dict) else {}
    return rules if isinstance(rules, dict) else {}


def rule(rules, model_id):
    value = rules.get(model_id)
    return value if isinstance(value, dict) else {}


def alias_id(channel, alias):
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
    if not isinstance(model_id, str) or model_id not in real_ids:
        raise PolicyError("model is not in this channel's catalogue", 404, "model_not_found")
    if "enabled" in patch and type(patch["enabled"]) is not bool:
        raise PolicyError("enabled must be a boolean")
    if not any(field in patch for field in ("alias", "enabled")):
        raise PolicyError("pass alias or enabled")
    with wb_settings._lock:
        data = wb_settings.load(directory)
        channels = copy.deepcopy(data.get("model_policies") or {})
        rules = channels.setdefault(channel, {})
        value = dict(rule(rules, model_id))
        if "alias" in patch:
            alias = patch["alias"]
            if not isinstance(alias, str):
                raise PolicyError("alias must be a string")
            alias = alias.strip()
            if len(alias) > 256 or any(character.isspace() or ord(character) < 32 for character in alias):
                raise PolicyError("alias must be at most 256 characters without whitespace")
            alias = alias_id(channel, alias)
            own_prefix = PREFIXES.get(channel)
            if alias and any(alias.startswith(prefix) and prefix != own_prefix for prefix in PREFIXES.values()):
                raise PolicyError("alias must stay in the selected channel")
            if alias == own_prefix:
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
        wb_settings.save(directory, data)
    return {"model_id": model_id, "channel": channel, "alias": value.get("alias") or "",
            "enabled": value.get("enabled") is not False}
