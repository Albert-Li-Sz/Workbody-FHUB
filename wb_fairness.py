"""Estimates pending consumption; upstream usage remains the billing truth."""
import collections
import json
import math
import threading
import time

LOCK = threading.Lock()
PROFILES = collections.OrderedDict()
MAX_PROFILES = 2000


def observe(row):
    if row.get("usage_missing") or row.get("outcome", "completed") != "completed":
        return
    try:
        output = max(0, int(row.get("completion_tokens") or 0))
        tokens = max(0, int(row.get("total_tokens") or 0))
        credit = float(row.get("credit") or 0) if row.get("has_credit") else None
    except (ValueError, TypeError, OverflowError):
        return
    if credit is not None and (not math.isfinite(credit) or credit < 0):
        credit = None
    with LOCK:
        keys = [(row.get("realm"), row.get("model"))]
        if row.get("account"):
            keys.append((row.get("realm"), row.get("model"), row["account"]))
        for key in keys:
            prior = PROFILES.get(key, {})
            profile = dict(prior)
            profile["output"] = output if "output" not in prior else prior["output"] * 0.8 + output * 0.2
            if credit is not None:
                profile["credit"] = credit if "credit" not in prior else prior["credit"] * 0.8 + credit * 0.2
                if tokens:
                    unit = credit / tokens
                    profile["unit_credit"] = unit if "unit_credit" not in prior else prior["unit_credit"] * 0.8 + unit * 0.2
            PROFILES[key] = profile
            PROFILES.move_to_end(key)
        while len(PROFILES) > MAX_PROFILES:
            PROFILES.popitem(last=False)


def estimate(payload, realm, account=None, measured_credit=None):
    # CJK characters need a different rough factor from an ASCII prompt. This
    # is a reservation estimate, never a claimed provider token count.
    text = json.dumps({"messages": payload.get("messages") or [], "tools": payload.get("tools") or []},
                      ensure_ascii=False)
    non_ascii = len(text) - len(text.encode("ascii", "ignore"))
    prompt = max(1, math.ceil(non_ascii + (len(text) - non_ascii) / 4.0))
    with LOCK:
        profile = dict(PROFILES.get((realm, payload.get("model")), {}))
    output = max(1, round(profile.get("output", 512)))
    for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        maximum = payload.get(field)
        if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum > 0:
            output = min(output, maximum)
    credit = measured_credit if measured_credit is not None else (
        profile["unit_credit"] * (prompt + output) if profile.get("unit_credit", 0) > 0
        else profile.get("credit", 1.0))
    try:
        credit = max(0.0, float(credit))
    except (TypeError, ValueError):
        credit = 1.0
    return {"tokens": prompt + output, "credit": credit if math.isfinite(credit) else 1.0,
            "day": time.strftime("%Y-%m-%d"), "model": str(payload.get("model") or "")}


def account_credit(estimate, realm, uid):
    """Account-specific observed rates refine a paid request's reservation."""
    with LOCK:
        profile = PROFILES.get((realm, estimate["model"], uid), {})
        unit = profile.get("unit_credit", 0)
        credit = unit * estimate["tokens"] if unit > 0 else profile.get("credit", estimate["credit"])
    return credit if math.isfinite(credit) and credit > 0 else 1.0
