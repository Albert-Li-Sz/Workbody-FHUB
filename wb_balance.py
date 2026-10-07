"""Public balance summaries, without credentials or invented zero balances."""
from decimal import Decimal, InvalidOperation, localcontext
import math
import time


def _amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and math.isfinite(float(number)):
            return number
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        pass
    return None


def summarize(accounts, refresh_results=None):
    refreshed = refresh_results is not None
    rows, amounts = [], []
    groups = {realm: {"amounts": [], "account_count": 0, "unknown_count": 0}
              for realm in ("cn", "intl")}
    failed = 0
    for account in accounts:
        credits = account.credits if isinstance(account.credits, dict) else {}
        amount = _amount(credits.get("remain"))
        realm = account.realm if account.realm in groups else "intl"
        group = groups[realm]
        group["account_count"] += 1
        if amount is None:
            group["unknown_count"] += 1
        else:
            amounts.append(amount)
            group["amounts"].append(amount)
        refresh_ok = refresh_results.get(account.uid, False) if refreshed else None
        if refreshed and not refresh_ok:
            failed += 1
        rows.append({
            "uid": account.uid, "nickname": account.nickname, "realm": realm,
            "enabled": account.enabled, "remain": float(amount) if amount is not None else None,
            "updated_at": credits.get("updated_at"), "refresh_ok": refresh_ok,
        })
    def total(values):
        # Imported caches may contain large finite values. Default Decimal
        # precision cannot quantize them, and float overflow is not valid JSON.
        with localcontext() as context:
            integer_digits = max((number.adjusted() + 1 for number in values), default=1)
            decimal_places = min(324, max((-number.as_tuple().exponent for number in values), default=2))
            context.prec = max(28, integer_digits + max(2, decimal_places) + len(str(len(values))) + 2)
            number = float(sum(values, Decimal(0)).quantize(Decimal("0.01")))
        return number if math.isfinite(number) else None
    by_realm = {}
    for realm, group in groups.items():
        values = group.pop("amounts")
        by_realm[realm] = dict(group, total_remain=total(values), known_count=len(values))
    unknown = len(accounts) - len(amounts)
    total_remain = total(amounts)
    complete = (unknown == 0 and failed == 0 and total_remain is not None
                and all(group["total_remain"] is not None for group in by_realm.values()))
    return {"ok": True, "complete": complete,
            "total_remain": total_remain, "account_count": len(accounts),
            "known_count": len(amounts), "unknown_count": unknown,
            "by_realm": by_realm, "accounts": rows,
            "refreshed": refreshed, "refresh_failed": failed, "queried_at": time.time()}
