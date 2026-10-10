"""Public balance summaries, without credentials or invented zero balances."""
from decimal import Decimal, InvalidOperation, localcontext
from concurrent.futures import ThreadPoolExecutor
import math
import threading
import time
import uuid


# Provider names select a response adapter, never a different account pool.
PROVIDERS = {"deepseek": "deepseek", "kimi": "kimi", "moonshot": "kimi",
             "glm": "glm", "zhipu": "glm", "qwen": "qwen", "dashscope": "qwen",
             "minimax": "minimax", "openai": "credit_grants"}


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


def _total(values):
    # Imported caches may contain large finite values. Default Decimal
    # precision cannot quantize them, and float overflow is not valid JSON.
    with localcontext() as context:
        integer_digits = max((number.adjusted() + 1 for number in values), default=1)
        decimal_places = min(324, max((-number.as_tuple().exponent for number in values), default=2))
        context.prec = max(28, integer_digits + max(2, decimal_places) + len(str(len(values))) + 2)
        number = float(sum(values, Decimal(0)).quantize(Decimal("0.01")))
    return number if math.isfinite(number) else None


def refresh_accounts(accounts):
    """Refresh a fixed account snapshot; failed queries keep the cached balance."""
    def fetch(account):
        try:
            return account.uid, bool(account.fetch_credits().get("ok"))
        except Exception:
            return account.uid, False
    with ThreadPoolExecutor(max_workers=4) as executor:
        return dict(executor.map(fetch, accounts))


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
    by_realm = {}
    for realm, group in groups.items():
        values = group.pop("amounts")
        by_realm[realm] = dict(group, total_remain=_total(values), known_count=len(values))
    unknown = len(accounts) - len(amounts)
    total_remain = _total(amounts)
    complete = (unknown == 0 and failed == 0 and total_remain is not None
                and all(group["total_remain"] is not None for group in by_realm.values()))
    return {"ok": True, "complete": complete,
            "total_remain": total_remain, "account_count": len(accounts),
            "known_count": len(amounts), "unknown_count": unknown,
            "by_realm": by_realm, "accounts": rows,
            "refreshed": refreshed, "refresh_failed": failed, "queried_at": time.time()}


def summarize_channel(accounts, realm, refresh_results=None):
    """Only expose one channel's totals, without account or credential details."""
    accounts = [account for account in accounts if account.realm == realm]
    remaining, used = [], []
    failed = 0
    for account in accounts:
        # Read each replaced credit dictionary once so remaining and used
        # amounts belong to the same upstream snapshot during scheduler work.
        cached = account.credits
        credits = cached if isinstance(cached, dict) else {}
        amount = _amount(credits.get("remain"))
        if amount is not None:
            remaining.append(amount)
        used.append(_amount(credits.get("used")))
        if refresh_results is not None and not refresh_results.get(account.uid, False):
            failed += 1
    unknown = len(accounts) - len(remaining)
    total_remain = _total(remaining)
    total_used = _total(used) if all(value is not None for value in used) else None
    total_granted = None
    if unknown == 0 and total_remain is not None and total_used is not None:
        total_granted = _total([_amount(total_remain), _amount(total_used)])
    return {"ok": True, "object": "balance", "realm": realm, "currency": "credits",
            "channel": {"cn": "workbuddy-cn", "intl": "workbuddy-intl"}[realm],
            "total_remain": total_remain, "total_used": total_used, "total_granted": total_granted,
            "account_count": len(accounts), "known_count": len(remaining), "unknown_count": unknown,
            "complete": unknown == 0 and failed == 0 and total_remain is not None,
            "refreshed": refresh_results is not None, "refresh_failed": failed,
            "queried_at": time.time()}


class ChannelBalances:
    """Coalesce per-channel queries and briefly cache successes and failures."""
    def __init__(self, cache_seconds=60):
        self.cache_seconds = cache_seconds
        self._locks = {realm: threading.Lock() for realm in ("cn", "intl")}
        self._attempts = {realm: {} for realm in ("cn", "intl")}

    def query(self, accounts, realm, refresh=None, require_used=True):
        accounts = [account for account in accounts if account.realm == realm]
        if refresh is False:
            return summarize_channel(accounts, realm)
        with self._locks[realm]:
            attempts = self._attempts[realm]
            live_ids = {id(account) for account in accounts}
            for identity in list(attempts):
                if identity not in live_ids:
                    del attempts[identity]
            targets, results = [], {}
            now = time.time()
            for account in accounts:
                cached = account.credits
                credits = cached if isinstance(cached, dict) else {}
                updated_at = _amount(credits.get("updated_at"))
                fresh = (updated_at is not None and 0 <= now - float(updated_at) < self.cache_seconds
                         and _amount(credits.get("remain")) is not None
                         and (not require_used or _amount(credits.get("used")) is not None))
                previous = attempts.get(id(account))
                recent_attempt = previous and 0 <= now - previous[1] < self.cache_seconds
                updated_since_attempt = fresh and previous and float(updated_at) > previous[1]
                if refresh is not True and recent_attempt and not updated_since_attempt:
                    results[account.uid] = previous[2]
                elif refresh is not True and fresh:
                    results[account.uid] = True
                else:
                    targets.append(account)
            if targets:
                fetched = refresh_accounts(targets)
                attempted_at = time.time()
                for account in targets:
                    # Keep the object alive so an imported replacement cannot
                    # inherit a removed account's refresh result by id reuse.
                    attempts[id(account)] = (account, attempted_at, fetched[account.uid])
                results.update(fetched)
            summary = summarize_channel(accounts, realm, results)
            summary["refreshed"] = bool(targets)
            return summary


def billing_response(summary, kind):
    """Client billing shapes; preserve the queried platform's actual unit."""
    if kind in ("deepseek", "kimi", "qwen", "glm", "minimax", "billing_balance", "credit_grants"):
        if not summary["complete"] or summary["total_remain"] is None:
            return None
        response = dict(summary)
        remaining = summary["total_remain"]
        amount = format(_amount(remaining), ".2f")
        response["unit"] = summary.get("unit", "credits")
        if kind in ("billing_balance", "glm", "minimax"):
            response["balance"] = summary["total_remain"]
            if kind != "billing_balance":
                response["provider"] = kind
                response["compatibility"] = "gateway_extension"
        elif kind == "kimi":
            response.update(provider="kimi", code=0, scode="0x0", status=True,
                            data={"available_balance": remaining,
                                  "voucher_balance": max(0, remaining),
                                  "cash_balance": min(0, remaining)})
        elif kind == "qwen":
            # Alibaba BSS QueryAccountBalance envelope. This gateway accepts
            # its own API key; it does not implement Alibaba RPC signatures.
            response.update(provider="qwen", Code="200", Message="success", Success=True,
                            RequestId=str(uuid.uuid4()), Data={"AvailableAmount": amount,
                                "AvailableCashAmount": "0.00", "CreditAmount": "0.00",
                                "MybankCreditAmount": "0.00", "Currency": "percent" if summary.get("unit") == "percent" else "USD"})
        elif kind == "credit_grants":
            response.update(provider="openai", object="credit_summary", total_available=remaining,
                            grants={"object": "list", "data": []})
        else:
            # USD is a protocol label so clients do not apply a CNY exchange
            # rate to points. The outer currency still declares credits.
            # WorkBuddy has no prepaid cash wallet; report the credit grant
            # as one balance, without claiming a topped-up cash amount.
            response.update(is_available=summary["total_remain"] > 0,
                            balance_infos=[{"currency": "percent" if summary.get("unit") == "percent" else "USD", "total_balance": amount,
                                            "granted_balance": amount,
                                            "topped_up_balance": "0.00"}])
        return response
    if not summary["complete"] or summary["total_used"] is None or summary["total_granted"] is None:
        return None
    response = dict(summary)
    if kind == "subscription":
        response.update(object="billing_subscription", has_payment_method=True,
                        soft_limit_usd=summary["total_granted"],
                        hard_limit_usd=summary["total_granted"],
                        system_hard_limit_usd=summary["total_granted"], access_until=0)
    elif kind == "usage":
        usage = _total([_amount(summary["total_used"]) * 100])
        if usage is None:
            return None
        response.update(object="list", total_usage=usage)
    else:
        raise ValueError("unknown billing response kind")
    return response
