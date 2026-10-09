"""Cline and OpenCode Zen credentials, catalogues and platform-local routing.

Network operations never hold the scheduling lock. Secrets stay in private
documents below accounts/upstreams; WorkBuddy's account importer ignores them.
"""
import copy
import datetime
import fnmatch
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import wb_events
import wb_forward_proxy
import wb_http
import wb_settings
import wb_storage
from wb_version import VERSION

BASES = {"cline": "https://api.cline.bot/api/v1", "opencode_zen": "https://opencode.ai/zen/v1"}
PREFIXES = {"cline": "cline/", "opencode_zen": "opencode/"}
WORKOS = "https://api.workos.com"
WORKOS_CLIENT = "client_01K3A541FN8TA3EPPHTD2325AR"


class PlatformError(ValueError):
    def __init__(self, message, status=400, code="invalid_request_error", wait=None):
        super().__init__(message)
        self.status, self.code, self.wait = status, code, wait
        self.message, self.detail = message, ""


def route(model, key_entry=None):
    allowed = wb_settings.key_upstreams(key_entry)
    model = str(model or "")
    for upstream, prefix in PREFIXES.items():
        if model.startswith(prefix):
            if upstream not in allowed:
                raise PlatformError("API Key does not allow this platform", 403, "platform_not_allowed")
            if not model[len(prefix):]:
                raise PlatformError("model ID is empty")
            return upstream, model[len(prefix):], model
    if len(allowed) == 1 and allowed[0] in PREFIXES:
        upstream = allowed[0]
        if not model:
            raise PlatformError("model is required for this platform")
        return upstream, model, PREFIXES[upstream] + model
    if "workbuddy" in allowed:
        return "workbuddy", model, model
    raise PlatformError("use a platform-prefixed model ID with a multi-platform API Key")


def _number(value):
    try:
        number = float(value)
        return number if not isinstance(value, bool) and math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _expiry(value):
    if not value:
        return 0
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        number = _number(value) or 0
        return number / 1000 if number >= 100000000000 else number


def _data(value):
    return value.get("data", value) if isinstance(value, dict) else value


def parse_catalog(upstream, document):
    """Accept official catalogue metadata without inventing context or prices."""
    document = _data(document)
    models = {}
    if upstream == "cline" and isinstance(document, dict):
        for group in ("recommended", "free", "clinePass", "clineCloud"):
            for item in document.get(group) or []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    old = models.get(item["id"], {})
                    models[item["id"]] = dict(old, **item, native_protocol="chat",
                        billing_mode="free" if group == "free" else "paid",
                        entitlement="subscription" if group == "clinePass" else group)
        # Authenticated /models can contain models outside the recommended list.
        entries = document.get("models") or []
    else:
        entries = document if isinstance(document, list) else (document or {}).get("models", [])
    if isinstance(entries, dict):
        entries = [dict(value, id=identifier) for identifier, value in entries.items() if isinstance(value, dict)]
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        identifier = item["id"]
        meta = dict(models.get(identifier, {}), **item)
        protocol = meta.get("native_protocol") or meta.get("protocol")
        endpoint = str(meta.get("endpoint") or meta.get("api") or "")
        provider = meta.get("provider") if isinstance(meta.get("provider"), dict) else {}
        package = str(meta.get("npm") or provider.get("npm") or "")
        if not protocol:
            if upstream == "cline" or "chat/completions" in endpoint or "openai-compatible" in package:
                protocol = "chat"
            elif "responses" in endpoint or package == "@ai-sdk/openai":
                protocol = "responses"
            elif "messages" in endpoint or "anthropic" in package:
                protocol = "messages"
            # These families use native endpoints in Zen's official docs.
            elif identifier.startswith(("gpt-", "grok-", "muse-spark-")):
                protocol = "responses"
            elif identifier.startswith("claude-") or re.match(r"qwen3\.(5|6|7|8)-(plus|flash|max)", identifier) and not identifier.startswith("qwen3.8-max"):
                protocol = "messages"
            elif identifier.startswith(("gemini-", "systemone", "jev-")):
                continue
            else:
                protocol = "chat"
        if protocol not in ("chat", "responses", "messages"):
            continue
        meta["native_protocol"] = protocol
        prices = meta.get("pricing") or meta.get("cost") or {}
        values = [_number(prices.get(field)) for field in ("input", "output", "prompt", "completion")]
        if meta.get("free") is True or any(value is not None for value in values) and all(value in (0, None) for value in values):
            meta["billing_mode"] = "free"
        else:
            meta.setdefault("billing_mode", "paid")
        models[identifier] = meta
    return models


class Account:
    def __init__(self, document, path):
        self.document, self.path = document, path
        self.uid, self.upstream = document["uid"], document["upstream"]
        self.refresh_lock = threading.Lock()
        self.cooldowns = {}
        self.last_error = ""
        self.verified_at = 0
        self.realm = ""

    @property
    def enabled(self):
        return self.document.get("enabled", True)

    @property
    def priority(self):
        return self.document.get("priority", 100)

    @property
    def token(self):
        token = self.document.get("access_token") or self.document.get("api_key") or ""
        if self.upstream == "cline" and not token.lower().startswith("workos:"):
            token = "workos:" + token
        return token

    def allows(self, model):
        patterns = self.document.get("models") or []
        return not patterns or any(fnmatch.fnmatchcase(model, value) for value in patterns)

    def save(self):
        wb_storage.write_private_json(self.path, self.document)

    def view(self):
        return {"uid": self.uid, "upstream": self.upstream, "nickname": self.document.get("name") or self.uid,
                "enabled": self.enabled, "priority": self.priority, "models": self.document.get("models") or [],
                "public": self.document.get("public", False), "expires_at": self.document.get("expires_at", 0),
                "balance": copy.deepcopy(self.document.get("balance")), "last_error": self.last_error,
                "verified_at": self.verified_at or self.document.get("verified_at", 0),
                "proxy_slot": self.document.get("proxy_slot", ""),
                "has_refresh_token": bool(self.document.get("refresh_token")),
                "cooldowns": {model: max(0, int(until-time.time())) for model, until in self.cooldowns.items() if until > time.time()}}


class Lease:
    def __init__(self, manager, response, account, reservation, model, mode):
        self.manager, self._response, self.account = manager, response, account
        self._upstream, self._realm = account.upstream, ""
        self.reservation, self.model, self.billing_mode = reservation, model, mode
        self.cost_unit = "credits" if account.upstream == "cline" else "USD"
        self.settled, self.closed = False, False

    def __getattr__(self, name):
        return getattr(self._response, name)

    def __iter__(self):
        return iter(self._response)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def release(self):
        # record_usage calls release after writing. Keep the concurrency slot
        # until the transport/handler is closed, including terminal SSE writes.
        pass

    def settle(self, row):
        if not self.settled:
            self.manager.settle(self.reservation, row)
            self.settled = True

    def abort(self):
        abort = getattr(self._response, "abort", self._response.close)
        abort()

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self._response.close()
            finally:
                self.manager.release(self.reservation)


class Manager:
    def __init__(self, directory, database=None, bases=None, transport=None):
        self.directory, self.database = directory, database
        self.root = os.path.join(directory, "upstreams")
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        self.bases = dict(BASES, **(bases or {}))
        self.transport = transport or wb_http.urlopen
        self.lock = threading.RLock()
        self.accounts, self.catalogues, self.catalog_errors = {}, {}, {}
        self.refreshing, self.jobs, self.reservations = set(), {}, {}
        self.refresh_attempts = {}
        self.daily, self.day = {}, ""
        self.load()
        for upstream in BASES:
            try:
                self.catalogues[upstream] = wb_storage.read_private_json(os.path.join(self.root, upstream + "-catalog.json"))
            except (OSError, ValueError):
                self.catalogues[upstream] = {"models": {}, "updated_at": 0}
        self.stopping = threading.Event()
        self.worker = None

    def load(self):
        for path in wb_storage.document_paths(self.root):
            if not os.path.basename(path).startswith("account-"):
                continue
            try:
                document = wb_storage.read_private_json(path)
                if document.get("upstream") in BASES and document.get("uid"):
                    self.accounts[document["uid"]] = Account(document, path)
            except (OSError, ValueError, TypeError):
                continue

    def import_accounts(self, payload):
        entries = payload if isinstance(payload, list) else [payload]
        if not entries or len(entries) > 500:
            raise PlatformError("import between 1 and 500 accounts")
        plan = []
        for raw in entries:
            if not isinstance(raw, dict) or raw.get("upstream") not in BASES:
                raise PlatformError("upstream must be cline or opencode_zen")
            upstream = raw["upstream"]
            token = str(raw.get("access_token") or raw.get("accessToken") or raw.get("api_key") or "").strip()
            if upstream == "cline" and token.lower().startswith("workos:"):
                token = token[7:]
            public = raw.get("public") is True
            if public:
                if upstream != "opencode_zen":
                    raise PlatformError("public compatibility is only available for Zen")
                token = "public"
            if not token or len(token) > 16384 or re.search(r"[\r\n\x00]", token):
                raise PlatformError("a valid access token or API Key is required")
            priority = raw.get("priority", 100)
            if type(priority) is not int or not 0 <= priority <= 2147483647:
                raise PlatformError("priority must be an integer from 0 to 2147483647")
            models = raw.get("models") or []
            if not isinstance(models, list) or any(not isinstance(value, str) or not value for value in models):
                raise PlatformError("models must be an array of model patterns")
            refresh = str(raw.get("refresh_token") or raw.get("refreshToken") or "")
            if len(refresh) > 16384 or re.search(r"[\r\n\x00]", refresh):
                raise PlatformError("invalid refresh token")
            uid = upstream + "-" + hashlib.sha256(token.encode()).hexdigest()[:20]
            document = {"uid": uid, "upstream": upstream, "name": str(raw.get("name") or raw.get("email") or uid)[:200],
                        "enabled": raw.get("enabled", not public) is True, "priority": priority, "models": models,
                        "public": public, "expires_at": _expiry(raw.get("expires_at") or raw.get("expiresAt")),
                        "refresh_token": refresh, "proxy_slot": str(raw.get("proxy_slot") or "")}
            if document["proxy_slot"] and not wb_settings.find_proxy_slot(self.directory, document["proxy_slot"]):
                raise PlatformError("proxy slot not found")
            document["access_token" if upstream == "cline" else "api_key"] = token
            if raw.get("user_id"):
                document["user_id"] = str(raw["user_id"])
            plan.append((document, set(raw)))
        saved = []
        with self.lock:
            for document, provided in plan:
                uid = document["uid"]
                existing = next((a for a in self.accounts.values() if document.get("user_id") and
                    a.upstream == document["upstream"] and a.document.get("user_id") == document["user_id"]), None)
                if existing:
                    uid = document["uid"] = existing.uid
                account = self.accounts.get(uid)
                if account:
                    for field in ("priority", "models", "proxy_slot", "enabled", "name", "refresh_token"):
                        aliases = {"refresh_token": ("refresh_token", "refreshToken")}.get(field, (field,))
                        if not any(alias in provided for alias in aliases):
                            document.pop(field, None)
                    account.document.update(document)
                else:
                    account = Account(document, os.path.join(self.root, "account-" + uid + ".json"))
                    self.accounts[uid] = account
                account.save()
                saved.append(account.view())
        for upstream in {doc["upstream"] for doc, _ in plan}:
            self.refresh_async(upstream, force=True)
        return saved

    def update_account(self, uid, patch):
        with self.lock:
            account = self.accounts.get(uid)
            if not account:
                raise PlatformError("account not found", 404)
            if patch.get("delete") is True:
                if any(value["uid"] == uid for value in self.reservations.values()):
                    raise PlatformError("account has requests in flight", 409)
                wb_storage.delete_private_json(account.path)
                del self.accounts[uid]
                return {"deleted": True}
            values = {}
            if "priority" in patch:
                value = patch["priority"]
                if type(value) is not int or not 0 <= value <= 2147483647:
                    raise PlatformError("invalid priority")
                values["priority"] = value
            if "enabled" in patch:
                if type(patch["enabled"]) is not bool:
                    raise PlatformError("enabled must be a boolean")
                values["enabled"] = patch["enabled"]
            if "models" in patch:
                if not isinstance(patch["models"], list) or any(not isinstance(value, str) or not value for value in patch["models"]):
                    raise PlatformError("invalid model patterns")
                values["models"] = patch["models"]
            if "proxy_slot" in patch:
                slot = str(patch["proxy_slot"] or "")
                if slot and not wb_settings.find_proxy_slot(self.directory, slot):
                    raise PlatformError("proxy slot not found")
                values["proxy_slot"] = slot
            if "name" in patch:
                values["name"] = str(patch["name"])[:200]
            for field in ("access_token", "api_key", "refresh_token"):
                if field not in patch:
                    continue
                if field == "access_token" and account.upstream != "cline":
                    target = "api_key"
                else:
                    target = field
                token = patch[field]
                if not isinstance(token, str) or len(token) > 16384 or re.search(r"[\r\n\x00]", token):
                    raise PlatformError("invalid credential")
                if target != "refresh_token" and not token.strip():
                    raise PlatformError("credential must not be empty")
                values[target] = token.strip()
            account.document.update(values)
            account.save()
            return account.view()

    def proxy(self, account):
        slot = account.document.get("proxy_slot")
        if not slot:
            return ""
        entry = wb_settings.find_proxy_slot(self.directory, slot)
        if not entry or entry.get("enabled") is False:
            raise PlatformError("bound proxy slot is unavailable", 503)
        return wb_forward_proxy.slot_url(entry)

    def headers(self, account=None):
        headers = {"Content-Type": "application/json", "User-Agent": "Workbody-FHUB/" + VERSION,
                   "X-CLIENT-TYPE": "cli", "X-CLIENT-VERSION": VERSION}
        if account:
            headers["Authorization"] = "Bearer " + account.token
            if account.upstream == "opencode_zen":
                headers["x-api-key"] = account.token
                headers["anthropic-version"] = "2023-06-01"
        return headers

    def request_json(self, upstream, path, account=None, body=None, timeout=15):
        url = self.bases[upstream].rstrip("/") + path
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers=self.headers(account))
        with self.transport(request, timeout=timeout, proxy=self.proxy(account) if account else "") as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise PlatformError("upstream metadata exceeds the size limit", 502)
            return json.loads(raw)

    def ensure_token(self, account, force=False, failed_token=None):
        if account.upstream != "cline" or not account.document.get("refresh_token"):
            return
        with account.refresh_lock:
            if failed_token is not None and account.token != failed_token:
                return
            expires = account.document.get("expires_at", 0)
            if not force and (not expires or expires > time.time() + 300):
                return
            try:
                result = _data(self.request_json("cline", "/auth/refresh", account=account, body={
                    "refreshToken": account.document["refresh_token"], "grantType": "refresh_token"}))
                if not isinstance(result, dict) or not result.get("accessToken"):
                    raise PlatformError("invalid Cline token refresh response", 502)
                with self.lock:
                    account.document.update(access_token=result["accessToken"],
                        refresh_token=result.get("refreshToken") or account.document["refresh_token"],
                        expires_at=_expiry(result.get("expiresAt")))
                    info = result.get("userInfo") or {}
                    if info.get("clineUserId"):
                        account.document["user_id"] = info["clineUserId"]
                    account.last_error = ""
                    account.save()
            except urllib.error.HTTPError as exc:
                detail = exc.read(2000).decode("utf-8", "replace")
                if exc.code in (400, 401, 403) and re.search(r"invalid_grant|invalid_token|revoked|expired", detail, re.I):
                    account.document["enabled"] = False
                    account.save()
                account.last_error = "Cline credential refresh failed (HTTP %d)" % exc.code
                raise PlatformError(account.last_error, 503, "credential_refresh_failed") from exc
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if isinstance(exc, PlatformError):
                    raise
                account.last_error = "Cline credential refresh unavailable"
                account.cooldowns["*"] = time.time() + 5
                raise PlatformError(account.last_error, 503, "credential_refresh_failed") from exc

    def refresh_catalog(self, upstream):
        candidates = [account for account in list(self.accounts.values()) if account.upstream == upstream and account.enabled]
        account = candidates[0] if candidates else None
        if account:
            self.ensure_token(account)
        document = self.request_json(upstream, "/ai/cline/recommended-models" if upstream == "cline" else "/models", account)
        models = parse_catalog(upstream, document)
        supplemental_error = ""
        if upstream == "cline":
            # Official Cline's broader selector uses OpenRouter catalogue IDs.
            # This is metadata only: Cline credentials never leave Cline.
            try:
                request = urllib.request.Request("https://openrouter.ai/api/v1/models",
                    headers={"User-Agent": "Workbody-FHUB/" + VERSION})
                with self.transport(request, timeout=10, proxy=self.proxy(account) if account else "") as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise PlatformError("catalogue exceeds the size limit", 502)
                catalogue = _data(json.loads(raw))
                for item in catalogue if isinstance(catalogue, list) else []:
                    identifier = item.get("id") if isinstance(item, dict) else None
                    outputs = (item.get("architecture") or {}).get("output_modalities") or ["text"]
                    if not identifier or outputs != ["text"]:
                        continue
                    supplementary = {"id": identifier, "name": item.get("name") or identifier,
                        "native_protocol": "chat", "billing_mode": "paid", "entitlement": "account",
                        "catalog_source": "openrouter", "context_length": item.get("context_length"),
                        "max_output_tokens": (item.get("top_provider") or {}).get("max_completion_tokens"),
                        "supported_parameters": item.get("supported_parameters") or [],
                        "reference_pricing": {"unit": "USD/token", **(item.get("pricing") or {})}}
                    models[identifier] = dict(supplementary, **models.get(identifier, {}))
            except Exception:
                supplemental_error = "Cline recommendations synced; broader catalogue unavailable"
                for identifier, old in self.catalogues.get(upstream, {}).get("models", {}).items():
                    if old.get("catalog_source") == "openrouter" and identifier not in models:
                        models[identifier] = dict(old, stale=True)
        if not models:
            raise PlatformError("upstream returned no supported models", 502)
        cache = {"models": models, "updated_at": time.time()}
        wb_storage.write_private_json(os.path.join(self.root, upstream + "-catalog.json"), cache)
        with self.lock:
            self.catalogues[upstream], self.catalog_errors[upstream] = cache, supplemental_error
        return cache

    def refresh_balance(self, account):
        if account.upstream != "cline":
            # Zen does not document a public balance endpoint. Unknown remains
            # unknown; per-request billing is independent of wallet balance.
            return
        self.ensure_token(account)
        user = _data(self.request_json("cline", "/users/me", account))
        uid = (user or {}).get("id") or (user or {}).get("clineUserId") or account.document.get("user_id")
        if not uid:
            raise PlatformError("Cline user ID is missing", 502)
        balance = _data(self.request_json("cline", "/users/" + urllib.parse.quote(str(uid), safe="") + "/balance", account))
        amount = _number((balance or {}).get("balance"))
        with self.lock:
            account.document.update(user_id=str(uid), balance={"remain": amount, "unit": "credits", "updated_at": time.time()})
            account.save()

    def refresh_paid_usage(self, account):
        """Reconcile official Cline credit transactions without counting them twice."""
        if account.upstream != "cline" or not account.document.get("user_id"):
            return
        path = "/users/" + urllib.parse.quote(account.document["user_id"], safe="") + "/usages"
        document = _data(self.request_json("cline", path, account))
        items = document.get("items") if isinstance(document, dict) else None
        if not isinstance(items, list):
            raise PlatformError("invalid Cline usage response", 502)
        day = time.strftime("%Y-%m-%d")
        transactions = []
        for item in items:
            if not isinstance(item, dict):
                continue
            at, cost = _expiry(item.get("createdAt")), _number(item.get("creditsUsed"))
            if not at or time.strftime("%Y-%m-%d", time.localtime(at)) != day or cost is None:
                continue
            transactions.append({"id": str(item.get("generationId") or item.get("id") or ""),
                                 "credit": cost, "tokens": _number(item.get("totalTokens")) or 0})
        with self.lock:
            account.document["paid_usage"] = {"day": day, "unit": "credits", "transactions": transactions,
                                               "updated_at": time.time()}
            account.save()

    def refresh_async(self, upstream, force=False):
        with self.lock:
            now = time.time()
            if upstream in self.refreshing or not force and now - self.refresh_attempts.get(upstream, 0) < 60:
                return
            self.refresh_attempts[upstream] = now
            self.refreshing.add(upstream)
        def run():
            try:
                if force or time.time() - self.catalogues.get(upstream, {}).get("updated_at", 0) >= 300:
                    try:
                        self.refresh_catalog(upstream)
                    except Exception as exc:
                        self.catalog_errors[upstream] = "%s catalogue refresh failed (%s%s)" % (
                            upstream, type(exc).__name__, " %s" % exc.code if isinstance(exc, urllib.error.HTTPError) else "")
                for account in list(self.accounts.values()):
                    if account.upstream == upstream and (account.enabled or force):
                        try:
                            self.ensure_token(account)
                            cached = account.document.get("balance") or {}
                            if force or time.time() - cached.get("updated_at", 0) >= 300:
                                self.refresh_balance(account)
                                self.refresh_paid_usage(account)
                        except Exception as exc:
                            account.last_error = "%s refresh failed (%s)" % (upstream, type(exc).__name__)
            finally:
                with self.lock:
                    self.refreshing.discard(upstream)
                wb_events.BROKER.publish("accounts", "models", "platforms")
        threading.Thread(target=run, daemon=True, name="platform-refresh-" + upstream).start()

    def balance(self, upstream, refresh=False):
        if refresh:
            self.refresh_async(upstream, force=True)
        amounts, owners, unknown = [], set(), 0
        for account in list(self.accounts.values()):
            if account.upstream != upstream:
                continue
            owner = account.document.get("user_id") or account.uid
            if owner in owners:
                continue
            owners.add(owner)
            cached = account.document.get("balance") or {}
            value = _number(cached.get("remain"))
            if value is None:
                unknown += 1
            else:
                amounts.append(value)
        unit = "credits" if upstream == "cline" else "USD"
        return {"ok": True, "object": "balance", "upstream": upstream, "currency": unit, "unit": unit,
                "total_remain": round(sum(amounts), 6) if amounts else None, "total_used": None, "total_granted": None,
                "account_count": len(owners), "known_count": len(amounts), "unknown_count": unknown,
                "complete": bool(owners) and unknown == 0, "refreshed": False,
                "refreshing": upstream in self.refreshing, "queried_at": time.time()}

    def start(self):
        if self.worker:
            return
        def run():
            while not self.stopping.is_set():
                for upstream in BASES:
                    if any(a.enabled and a.upstream == upstream for a in list(self.accounts.values())):
                        self.refresh_async(upstream)
                self.stopping.wait(60)
        self.worker = threading.Thread(target=run, daemon=True, name="platform-maintenance")
        self.worker.start()

    def model(self, upstream, identifier):
        meta = (self.catalogues.get(upstream, {}).get("models") or {}).get(identifier)
        if meta is None:
            self.refresh_async(upstream)
            raise PlatformError("model is not in the synchronized platform catalogue; refresh models first", 404, "model_not_found")
        return meta

    def models(self, allowed):
        data = []
        for upstream in BASES:
            if upstream not in allowed:
                continue
            cache = self.catalogues.get(upstream, {})
            if time.time() - cache.get("updated_at", 0) > 300:
                self.refresh_async(upstream)
            for identifier, meta in (cache.get("models") or {}).items():
                if not any(a.upstream == upstream and a.enabled and a.allows(identifier) and
                           (not a.document.get("public") or meta.get("billing_mode") == "free") for a in list(self.accounts.values())):
                    continue
                item = dict(meta, id=PREFIXES[upstream] + identifier, object="model", owned_by=upstream,
                            upstream=upstream, upstream_model=identifier, created=int(cache.get("updated_at", 0)),
                            stale=bool(meta.get("stale")) or time.time() - cache.get("updated_at", 0) > 600)
                limits = meta.get("limit") or {}
                if limits.get("context"):
                    item["context_length"] = limits["context"]
                if limits.get("output"):
                    item["max_output_tokens"] = limits["output"]
                data.append(item)
        return data

    def _today(self, exclude_row=None):
        today = time.strftime("%Y-%m-%d")
        if self.day == today:
            return
        self.day, self.daily = today, {}
        if self.database:
            since = time.mktime(time.localtime(time.time())[:3] + (0, 0, 0, 0, 0, -1))
            for upstream in BASES:
                for row in self.database.usage_rows(since=since, upstream=upstream):
                    if row != exclude_row:
                        self._count(row)

    def _count(self, row):
        entry = self.daily.setdefault(row.get("account"), {"free_tokens": 0, "paid_cost": 0, "tokens": 0,
            "requests": 0, "paid_tokens": 0, "paid_generations": set()})
        tokens = max(0, int(row.get("total_tokens") or 0))
        entry["tokens"] += tokens
        entry["requests"] += int(row.get("outcome") == "completed")
        if row.get("billing_mode") == "free":
            entry["free_tokens"] += tokens
        elif row.get("has_credit"):
            entry["paid_cost"] += _number(row.get("credit")) or 0
            entry["paid_tokens"] += tokens
            if row.get("upstream_generation_id"):
                entry["paid_generations"].add(row["upstream_generation_id"])

    def _paid_load(self, account):
        stat = self.daily.get(account.uid, {})
        local = stat.get("paid_cost", 0)
        remote = account.document.get("paid_usage") or {}
        if remote.get("day") != self.day or remote.get("unit") != "credits":
            return local
        known = stat.get("paid_generations", set())
        transactions = remote.get("transactions") or []
        if any(not item.get("id") for item in transactions):
            return max(local, sum(item["credit"] for item in transactions))
        return local + sum(item["credit"] for item in transactions if item["id"] not in known)

    def _paid_estimate(self, upstream, meta, tokens):
        if upstream == "cline":
            # Cline catalogue prices can be USD; scheduling compares credits.
            # Learn an estimate from actual credits, never add USD to credits.
            cost = count = 0
            for account in self.accounts.values():
                if account.upstream != upstream:
                    continue
                stat = self.daily.get(account.uid, {})
                cost += stat.get("paid_cost", 0)
                count += stat.get("paid_tokens", 0)
                remote = account.document.get("paid_usage") or {}
                if remote.get("day") == self.day:
                    for item in remote.get("transactions") or []:
                        if item["id"] not in stat.get("paid_generations", set()):
                            cost += item["credit"]
                            count += item["tokens"]
            return tokens * cost / count if count else 1.0
        prices = meta.get("pricing") or meta.get("cost") or {}
        price = _number(prices.get("output"))
        return tokens / 1000000 * price if price is not None else 1.0

    def reserve(self, upstream, model, meta, session, owner, estimated, bound_uid=None):
        with self.lock:
            self._today()
            now = time.time()
            mode = meta.get("billing_mode", "paid")
            if mode != "free":
                estimated = self._paid_estimate(upstream, meta, estimated)
            maximum = wb_settings.pool_config(self.directory).get("max_in_flight", 0)
            flights = {}
            pending = {}
            for ticket in self.reservations.values():
                flights[ticket["uid"]] = flights.get(ticket["uid"], 0) + 1
                if ticket["mode"] == mode:
                    pending[ticket["uid"]] = pending.get(ticket["uid"], 0) + ticket["estimate"]
            candidates = [a for a in self.accounts.values() if a.upstream == upstream and a.enabled and a.allows(model)
                and a.cooldowns.get("*", 0) <= now and a.cooldowns.get(model, 0) <= now
                and (not maximum or flights.get(a.uid, 0) < maximum)
                and (not a.document.get("public") or mode == "free")]
            if bound_uid:
                candidates = [a for a in candidates if a.uid == bound_uid]
            if not candidates:
                raise PlatformError("the bound account is unavailable" if bound_uid else "no eligible accounts in this platform", 503, "account_unavailable")
            best_priority = min(a.priority for a in candidates)
            candidates = [a for a in candidates if a.priority == best_priority]
            def load(a):
                stat = self.daily.get(a.uid, {})
                return (stat.get("free_tokens", 0) if mode == "free" else self._paid_load(a)) + pending.get(a.uid, 0)
            chosen = min(candidates, key=lambda a: (load(a), flights.get(a.uid, 0), a.uid))
            affinity = hashlib.sha256((owner + "\0" + upstream + "\0" + session).encode()).hexdigest() if session else None
            previous = self.database.affinity_get("platform:" + affinity) if affinity and self.database else None
            window = wb_settings.pool_config(self.directory).get("free_switch_window_tokens", 262144)
            old = next((a for a in candidates if a.uid == previous), None)
            if old and mode == "free" and load(old) - load(chosen) < window:
                chosen = old
            if affinity and self.database:
                self.database.affinity_set("platform:" + affinity, chosen.uid, 7200)
            identifier = uuid.uuid4().hex
            self.reservations[identifier] = {"uid": chosen.uid, "estimate": estimated, "mode": mode}
            return chosen, identifier

    def settle(self, identifier, row):
        with self.lock:
            self._today(exclude_row=row)
            ticket = self.reservations.get(identifier)
            if ticket and not ticket.get("settled"):
                ticket.update(settled=True, estimate=0)
                self._count(row)
                if row.get("outcome") == "completed":
                    account = self.accounts.get(ticket["uid"])
                    if account and time.time() - account.verified_at > 60:
                        account.verified_at = time.time()
                        account.document["verified_at"] = account.verified_at
                        account.last_error = ""
                        try:
                            account.save()
                        except OSError:
                            account.last_error = "could not persist verification metadata"

    def release(self, identifier):
        with self.lock:
            self.reservations.pop(identifier, None)

    def open(self, upstream, model, body, meta, session="", owner="", bound_uid=None):
        mode = meta.get("billing_mode", "paid")
        estimated = max(1, len(json.dumps(body, ensure_ascii=False)) // 3 + int(body.get("max_tokens") or body.get("max_output_tokens") or 4096))
        account, ticket = self.reserve(upstream, model, meta, session, owner, estimated, bound_uid)
        try:
            self.ensure_token(account)
            native = meta["native_protocol"]
            request_body = copy.deepcopy(body)
            request_body["model"] = model
            if upstream == "cline":
                request_body["session_id"] = session or uuid.uuid4().hex
            for attempt in range(2):
                token = account.token
                headers = self.headers(account)
                if upstream == "cline":
                    headers["X-Task-ID"] = request_body["session_id"]
                request = urllib.request.Request(self.bases[upstream] + {"chat": "/chat/completions", "responses": "/responses", "messages": "/messages"}[native],
                    data=json.dumps(request_body, ensure_ascii=False, allow_nan=False).encode(), headers=headers)
                try:
                    timeout = wb_settings.upstream_config(self.directory)["header_timeout_seconds"]
                    response = self.transport(request, timeout=timeout, proxy=self.proxy(account))
                    lease = Lease(self, response, account, ticket, model, mode)
                    lease.expected_choices = body.get("n") if type(body.get("n")) is int else 1
                    return lease
                except urllib.error.HTTPError as exc:
                    detail = exc.read(4096).decode("utf-8", "replace")
                    if exc.code == 401 and account.document.get("refresh_token") and attempt == 0:
                        self.ensure_token(account, force=True, failed_token=token)
                        continue
                    wait = None
                    if exc.code == 429:
                        try:
                            wait = min(86400, max(1, int(exc.headers.get("Retry-After", "60"))))
                        except (ValueError, TypeError):
                            wait = 60
                        hours = re.search(r"(?:try again in|reset in)\s*(?:(\d+)h)?\s*(?:(\d+)m)?", detail, re.I)
                        if hours and any(hours.groups()):
                            wait = max(wait, int(hours[1] or 0) * 3600 + int(hours[2] or 0) * 60)
                        scope = "*" if "INFERENCE_CAP_ERROR" in detail else model
                        account.cooldowns[scope] = time.time() + wait
                    elif exc.code in (401, 402, 403):
                        account.cooldowns[model] = time.time() + 300
                    elif exc.code >= 500:
                        account.cooldowns["*"] = time.time() + 5
                    account.last_error = "upstream HTTP %d" % exc.code
                    # Error bodies may echo submitted data; expose a bounded
                    # protocol message, never the authorization header/body.
                    error = PlatformError("%s rejected the request (HTTP %d)" % (upstream, exc.code), exc.code, "upstream_error", wait)
                    if exc.code in (400, 413, 422) and re.search(r"context[_ ](?:length|window|limit)|maximum context|max(?:imum)?[_ ]input[_ ]tokens", detail, re.I):
                        error = PlatformError("conversation exceeds this model's context window; start a new conversation or use a larger-context model",
                                              exc.code, "context_length_exceeded")
                    error.account_uid = account.uid
                    raise error from exc
                except (urllib.error.URLError, OSError) as exc:
                    account.cooldowns["*"] = time.time() + 5
                    account.last_error = "upstream connection failed"
                    error = PlatformError(account.last_error, 502, "upstream_connection_error")
                    error.account_uid = account.uid
                    raise error from exc
        except PlatformError as exc:
            if exc.status in (401, 403, 502, 503, 504):
                account.cooldowns["*"] = max(account.cooldowns.get("*", 0), time.time() + 5)
            exc.account_uid = account.uid
            self.release(ticket)
            raise
        except Exception:
            self.release(ticket)
            raise

    def snapshot(self):
        with self.lock:
            self._today()
            accounts = []
            for a in self.accounts.values():
                view = a.view()
                view["in_flight"] = sum(ticket["uid"] == a.uid for ticket in self.reservations.values())
                view["today"] = {key: value for key, value in self.daily.get(a.uid, {}).items() if key != "paid_generations"}
                view["today"]["paid_cost"] = self._paid_load(a)
                accounts.append(view)
            model_revision = hashlib.sha256(json.dumps([
                [(upstream, cache.get("updated_at", 0)) for upstream, cache in self.catalogues.items()],
                [(a.uid, a.enabled, a.document.get("models")) for a in self.accounts.values()]], sort_keys=True).encode()).hexdigest()
            return {"accounts": accounts, "models_revision": model_revision, "catalogues": {upstream: {
                "updated_at": cache.get("updated_at", 0), "stale": time.time() - cache.get("updated_at", 0) > 600,
                "count": len(cache.get("models", {})), "error": self.catalog_errors.get(upstream, ""),
                "refreshing": upstream in self.refreshing} for upstream, cache in self.catalogues.items()}}

    def start_login(self):
        body = urllib.parse.urlencode({"client_id": WORKOS_CLIENT}).encode()
        request = urllib.request.Request(WORKOS + "/user_management/authorize/device", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.transport(request, timeout=15) as response:
            auth = json.load(response)
        if not auth.get("device_code") or not auth.get("verification_uri"):
            raise PlatformError("invalid device authorization response", 502)
        login_url = auth.get("verification_uri_complete") or auth["verification_uri"]
        parsed = urllib.parse.urlsplit(login_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise PlatformError("invalid device authorization URL", 502)
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "status": "pending", "expires_at": time.time() + min(1800, auth.get("expires_in", 600)),
               "url": login_url, "code": auth.get("user_code", "")}
        with self.lock:
            self.jobs = {key: value for key, value in self.jobs.items() if value["expires_at"] > time.time()}
            if len(self.jobs) >= 10:
                raise PlatformError("too many pending device logins", 429)
            self.jobs[job_id] = job
        def poll():
            interval = max(5, auth.get("interval", 5))
            try:
                while time.time() < job["expires_at"] and not self.stopping.wait(interval):
                    fields = {"client_id": WORKOS_CLIENT, "device_code": auth["device_code"],
                              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
                    request = urllib.request.Request(WORKOS + "/user_management/authenticate",
                        data=urllib.parse.urlencode(fields).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
                    try:
                        with self.transport(request, timeout=15) as response:
                            tokens = json.load(response)
                    except urllib.error.HTTPError as exc:
                        data = json.loads(exc.read(2000))
                        if data.get("error") == "authorization_pending":
                            continue
                        if data.get("error") == "slow_down":
                            interval += 5
                            continue
                        raise
                    result = _data(self.request_json("cline", "/auth/register", body={
                        "accessToken": tokens["access_token"], "refreshToken": tokens["refresh_token"]}))
                    info = result.get("userInfo") or {}
                    imported = self.import_accounts(dict(result, upstream="cline", email=info.get("email"), user_id=info.get("clineUserId")))
                    job.update(status="completed", account=imported[0]["uid"])
                    return
                job["status"] = "expired"
            except Exception as exc:
                job.update(status="failed", error="Cline login failed (%s)" % type(exc).__name__)
            finally:
                wb_events.BROKER.publish("accounts", "platforms")
        threading.Thread(target=poll, daemon=True, name="cline-device-login").start()
        return copy.deepcopy(job)
