"""Join live provider IDs with client metadata and normalize billing displays.

Metadata never grants access to a model absent from the live provider list.
ClinePass reference prices describe quota usage, not charges to its wallet.
"""
import copy
import math

REGISTRY_URL = "https://models.dev/api.json"
ZEN_URL = "https://opencode.ai/zen/v1"


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def provider(document, name):
    if not isinstance(document, dict):
        return {}
    providers = document.get("providers", document)
    value = providers.get(name, {}) if isinstance(providers, dict) else {}
    return value if isinstance(value, dict) else {}


def enrich(upstream, models, registry, stale=False):
    name = "cline-pass" if upstream == "cline" else "opencode"
    entries = provider(registry, name).get("models") or {}
    if not isinstance(entries, dict):
        return models
    for identifier, meta in models.items():
        detail = entries.get(identifier)
        if detail is None and upstream == "cline":
            detail = entries.get(identifier.removeprefix("cline-pass/"))
        if not isinstance(detail, dict):
            continue
        for field in ("name", "description", "limit", "modalities", "reasoning", "reasoning_options", "tool_call", "interleaved", "provider"):
            if field in detail and (field not in meta or field == "name" and meta[field] == identifier):
                meta[field] = copy.deepcopy(detail[field])
        cost = detail.get("cost")
        if isinstance(cost, dict):
            pricing = {key: number(cost.get(key)) for key in ("input", "output", "cache_read", "cache_write") if number(cost.get(key)) is not None}
            if pricing:
                pricing.update(unit="USD/1M tokens", source="models.dev", stale=stale)
                if upstream == "cline":
                    meta["reference_pricing"] = pricing
                elif not meta.get("pricing") and not meta.get("cost"):
                    meta["pricing"] = pricing
                    if pricing.get("input") == 0 and pricing.get("output") == 0:
                        meta["billing_mode"] = "free"
        meta["metadata_source"] = "models.dev"
        meta["metadata_stale"] = stale
    return models


def subscription(document):
    plan = (document.get("plan") or {}) if isinstance(document, dict) else {}
    if not isinstance(plan, dict):
        plan = {}
    price = number(plan.get("pricePerSeatCents"))
    return {"id": str(plan.get("id") or "")[:200],
            "name": str(plan.get("displayName") or plan.get("name") or "")[:200],
            "price": price / 100 if price is not None else None, "currency": "USD",
            "interval": str(plan.get("interval") or "")[:30],
            "current_period_end": str(document.get("currentPeriodEnd") or "")[:100] if isinstance(document, dict) else None}


def quota(document):
    """Official Cline app: limits[type, percentUsed, resetsAt]."""
    limits = document.get("limits") if isinstance(document, dict) else None
    if not isinstance(limits, list):
        raise ValueError("invalid subscription usage limits")
    result = {}
    aliases = {"fivehour": "fiveHour", "fivehours": "fiveHour", "5hour": "fiveHour", "5hours": "fiveHour",
               "rolling": "fiveHour", "hourly": "fiveHour", "weekly": "weekly", "week": "weekly", "monthly": "monthly", "month": "monthly"}
    for item in limits:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            continue
        name = item["type"][:50]
        normalized = "".join(character.lower() for character in name if character.isalnum())
        used = number(item.get("percentUsed"))
        result[aliases.get(normalized, name)] = {"percent_used": used,
            "remaining_percent": max(0, 100-used) if used is not None else None,
            "reset_at": str(item.get("resetsAt") or "")[:100], "unit": "percent"}
    return result
