"""External account adapters, catalogues and platform-local routing.

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
import wb_opencode_client
import wb_device_auth
import wb_commandcode
import wb_cline_routes
from wb_version import VERSION

BASES = {"cline": "https://api.cline.bot/api/v1", "opencode_zen": "https://opencode.ai/zen/v1",
         "commandcode": "https://api.commandcode.ai"}
PREFIXES = {"cline": "cline/", "opencode_zen": "opencode/", "commandcode": "commandcode/"}
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


def _public_metadata(value):
    if isinstance(value, dict):
        hidden = {"options", "headers", "apikey", "api_key", "access_token", "accesstoken", "refresh_token", "refreshtoken",
                  "client_secret", "clientsecret", "password", "authorization", "token"}
        return {key: _public_metadata(item) for key, item in value.items() if str(key).lower() not in hidden}
    if isinstance(value, list):
        return [_public_metadata(item) for item in value]
    return value


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
        api = meta.get("api") if isinstance(meta.get("api"), dict) else {}
        package = str(api.get("npm") or meta.get("npm") or provider.get("npm") or "")
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
        self.config_lock = threading.RLock()
        self.document.setdefault("auth_type", "api_key" if document.get("api_key") or
            str(document.get("access_token") or "").startswith(("sk_", "sk-")) else "oauth" if self.upstream == "cline" else "api_key")
        self.cooldowns = {key: value for key, value in (document.get("cooldowns") or {}).items()
                          if type(value) in (int, float) and value > time.time()}
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
        if self.upstream == "cline" and self.document.get("auth_type") == "oauth" and not token.lower().startswith("workos:"):
            token = "workos:" + token
        return token

    def allows(self, model, meta=None):
        patterns = self.document.get("models") or []
        if patterns and not any(fnmatch.fnmatchcase(model, value) for value in patterns):
            return False
        if self.upstream == "cline":
            scope = self.document.get("access_scope", "all")
            if scope == "subscription" and not model.startswith("cline-pass/"):
                return False
            if scope == "credits" and model.startswith("cline-pass/"):
                return False
        if self.upstream == "opencode_zen" and self.document.get("auth_type") == "oauth":
            gateway = self.document.get("console_gateway") or {}
            configured = (gateway.get("models") or {}).get(model)
            if configured is None:
                return False
            if meta and meta.get("native_protocol"):
                local = parse_catalog("opencode_zen", {"models": [{"npm": gateway.get("npm"), **configured, "id": model}]}).get(model)
                return bool(local and local["native_protocol"] == meta["native_protocol"])
            return True
        if self.upstream == "commandcode" and meta and meta.get("min_plan") and self.document.get("plan"):
            rank = {"go": 0, "provider": 0, "pro": 1, "pro-v1": 1, "teams-pro": 1, "goat": 2, "max": 3, "maxx": 4, "ultra": 4}
            plan = self.document["plan"].lower().replace("individual-", "")
            if plan in rank and rank.get(meta["min_plan"], 0) > rank[plan]:
                return False
        return True

    def save(self):
        wb_storage.write_private_json(self.path, self.document)

    def view(self):
        return {"uid": self.uid, "upstream": self.upstream, "nickname": self.document.get("name") or self.uid,
                "enabled": self.enabled, "priority": self.priority, "models": self.document.get("models") or [],
                "public": self.document.get("public", False), "expires_at": self.document.get("expires_at", 0),
                "balance": copy.deepcopy(self.document.get("balance")), "last_error": self.last_error,
                "verified_at": self.verified_at or self.document.get("verified_at", 0),
                "proxy_slot": self.document.get("proxy_slot", ""),
                "auth_type": self.document.get("auth_type"), "access_scope": self.document.get("access_scope", "all"),
                "org_id": self.document.get("org_id", ""), "orgs": copy.deepcopy(self.document.get("orgs") or []),
                "plan": self.document.get("plan"), "quota": copy.deepcopy(self.document.get("quota")),
                "last_provider": copy.deepcopy(self.document.get("last_provider")),
                "credit_exhausted": bool(self.document.get("credit_exhausted")),
                "credential_ready": self.document.get("auth_type") != "oauth" or self.upstream != "opencode_zen" or bool(self.document.get("console_gateway")),
                "has_refresh_token": bool(self.document.get("refresh_token")),
                "cooldowns": {model: max(0, int(until-time.time())) for model, until in self.cooldowns.items() if until > time.time()}}


class Lease:
    def __init__(self, manager, response, account, reservation, model, mode):
        self.manager, self._response, self.account = manager, response, account
        self._upstream, self._realm = account.upstream, ""
        self.reservation, self.model, self.billing_mode = reservation, model, mode
        self.cost_unit = "credits" if account.upstream in ("cline", "commandcode") else "USD"
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
            if getattr(self, "observed_provider", None):
                row["actual_provider"] = self.observed_provider["provider"]
                row["provider_pipeline"] = self.observed_provider["pipeline"]
                with self.manager.lock:
                    self.account.document["last_provider"] = self.observed_provider
                    try:
                        self.account.save()
                    except Exception:
                        self.account.last_error = "could not persist provider metadata"
            self.manager.settle(self.reservation, row)
            self.settled = True

    def observe(self, value):
        if self._upstream == "cline":
            observed = wb_cline_routes.observed(value)
            if observed:
                self.observed_provider = observed

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
        self.last_picks = {}
        self.refresh_attempts = {}
        self.daily, self.day = {}, ""
        self.load()
        for upstream in BASES:
            try:
                self.catalogues[upstream] = wb_storage.read_private_json(os.path.join(self.root, upstream + "-catalog.json"))
            except (OSError, ValueError):
                self.catalogues[upstream] = {"models": {}, "updated_at": 0}
        self.stopping = threading.Event()
        if not self.catalogues.get("commandcode", {}).get("models"):
            self.catalogues["commandcode"] = {"models": wb_commandcode.builtin_models(), "updated_at": 0}
        self.logins = wb_device_auth.DeviceLogins(self, PlatformError)
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

    def publish(self):
        wb_events.BROKER.publish("accounts", "models", "platforms")

    def validate_options(self, options):
        if "priority" in options and (type(options["priority"]) is not int or not 0 <= options["priority"] <= 2147483647):
            raise PlatformError("priority must be an integer from 0 to 2147483647")
        if "models" in options and (not isinstance(options["models"], list) or len(options["models"]) > 500 or
                any(not isinstance(value, str) or not value or len(value) > 500 for value in options["models"])):
            raise PlatformError("invalid account model patterns")
        if options.get("access_scope", "all") not in ("all", "subscription", "credits"):
            raise PlatformError("invalid Cline model scope")
        slot = options.get("proxy_slot")
        if slot:
            self.proxy_for_slot(slot)

    def routing(self):
        return copy.deepcopy(wb_settings.load(self.directory).get("account_routing") or {})

    def set_routing(self, upstream, mode="fair", uid=None):
        if upstream not in BASES or mode not in ("fair", "roundrobin", "manual"):
            raise PlatformError("invalid account routing mode")
        if mode == "manual":
            account = self.accounts.get(uid)
            if not account or account.upstream != upstream or not account.enabled:
                raise PlatformError("select an enabled account in this platform")
        with wb_settings._lock:
            data = wb_settings.load(self.directory)
            data.setdefault("account_routing", {})[upstream] = {"mode": mode, "uid": uid if mode == "manual" else None}
            wb_settings.save(self.directory, data)
        self.publish()
        return self.routing()

    def export_accounts(self, uids=None, upstream=None, secrets=True):
        selected = set(uids or [])
        with self.lock:
            rows = [copy.deepcopy(account.document) if secrets else account.view()
                    for account in self.accounts.values() if (not selected or account.uid in selected)
                    and (not upstream or account.upstream == upstream)]
        return rows

    def _cache_console_models(self, account):
        gateway = account.document.get("console_gateway") or {}
        entries = [{"npm": gateway.get("npm"), **metadata, "id": identifier}
                   for identifier, metadata in (gateway.get("models") or {}).items() if isinstance(metadata, dict)]
        parsed = parse_catalog("opencode_zen", {"models": entries})
        # A model may exist in more than one org. Per-account eligibility is
        # checked separately; this catalogue is a display/routing union.
        with self.lock:
            cache = self.catalogues.setdefault("opencode_zen", {"models": {}, "updated_at": 0})
            cache["models"].update(parsed)
            cache["updated_at"] = time.time()
            wb_storage.write_private_json(os.path.join(self.root, "opencode_zen-catalog.json"), cache)

    def refresh_console(self, account, org_id=None):
        with account.config_lock:
            return self._refresh_console(account, org_id)

    def _refresh_console(self, account, org_id=None):
        self.ensure_token(account)
        options = {"proxy": self.proxy(account), "token": account.token}
        orgs = self.logins._request(wb_device_auth.OPENCODE_CONSOLE + "/api/orgs", **options)
        if not isinstance(orgs, list):
            raise PlatformError("invalid OpenCode organization response", 502)
        org_id = org_id or account.document.get("org_id")
        if org_id not in [org.get("id") for org in orgs if isinstance(org, dict)]:
            raise PlatformError("select an available OpenCode organization")
        config = self.logins._request(wb_device_auth.OPENCODE_CONSOLE + "/api/config", org=org_id, **options)
        gateway = wb_device_auth.console_gateway(config)
        with self.lock:
            if org_id != account.document.get("org_id"):
                if any(ticket["uid"] == account.uid for ticket in self.reservations.values()):
                    raise PlatformError("account has requests in flight", 409)
                if self.database and self.database.connection().execute("SELECT 1 FROM sqlite_master WHERE name='responses'").fetchone():
                    if self.database.connection().execute("SELECT 1 FROM responses WHERE account=? AND bound=1 AND expires_at>? LIMIT 1", (account.uid, time.time())).fetchone():
                        raise PlatformError("this organization has a bound Responses history; add another OAuth account for the other organization", 409)
            account.document.update(org_id=org_id, orgs=[{"id": org["id"], "name": org.get("name") or org["id"]}
                for org in orgs if isinstance(org, dict) and org.get("id")], console_gateway=gateway)
            account.save()
            self._cache_console_models(account)
        return account.view()

    def set_cline_route(self, model, value):
        self.model("cline", model)
        value = wb_cline_routes.validate(value)
        with wb_settings._lock:
            data = wb_settings.load(self.directory)
            data.setdefault("cline_routes", {})[model] = value
            wb_settings.save(self.directory, data)
        self.publish()
        return value

    def import_accounts(self, payload, dry_run=False):
        entries = payload if isinstance(payload, list) else [payload]
        if not entries or len(entries) > 500:
            raise PlatformError("import between 1 and 500 accounts")
        plan = []
        for raw in entries:
            if not isinstance(raw, dict) or raw.get("upstream") not in BASES:
                raise PlatformError("upstream must be cline, opencode_zen or commandcode")
            upstream = raw["upstream"]
            token = str(raw.get("api_key") or raw.get("apiKey") or raw.get("access_token") or raw.get("accessToken") or "").strip()
            auth_type = raw.get("auth_type") or ("api_key" if raw.get("api_key") or raw.get("apiKey") or
                token.startswith(("sk_", "sk-")) else "oauth" if upstream == "cline" else "api_key")
            if auth_type not in ("api_key", "oauth") or upstream == "commandcode" and auth_type != "api_key":
                raise PlatformError("invalid account credential type")
            if upstream == "cline" and token.lower().startswith("workos:"):
                token = token[7:]
            public = raw.get("public") is True
            if public:
                if upstream != "opencode_zen":
                    raise PlatformError("public compatibility is only available for Zen")
                token = "public"
            if not token or len(token) > 16384 or re.search(r"[\r\n\x00]", token):
                raise PlatformError("a valid access token or API Key is required")
            if upstream == "commandcode" and not re.fullmatch(r"user_[a-zA-Z0-9_-]{8,}", token):
                raise PlatformError("Command Code requires its CLI user_* credential")
            priority = raw.get("priority", 100)
            if type(priority) is not int or not 0 <= priority <= 2147483647:
                raise PlatformError("priority must be an integer from 0 to 2147483647")
            models = raw.get("models") or []
            if not isinstance(models, list) or any(not isinstance(value, str) or not value for value in models):
                raise PlatformError("models must be an array of model patterns")
            refresh = str(raw.get("refresh_token") or raw.get("refreshToken") or "")
            if len(refresh) > 16384 or re.search(r"[\r\n\x00]", refresh):
                raise PlatformError("invalid refresh token")
            identity = token + ("\0" + str(raw["org_id"]) if raw.get("org_id") else "")
            uid = upstream + "-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            if raw.get("uid") in self.accounts and self.accounts[raw["uid"]].upstream == upstream:
                uid = raw["uid"]
            document = {"uid": uid, "upstream": upstream, "auth_type": auth_type, "name": str(raw.get("name") or raw.get("userName") or raw.get("email") or uid)[:200],
                        "enabled": raw.get("enabled", not public) is True, "priority": priority, "models": models,
                        "public": public, "expires_at": _expiry(raw.get("expires_at") or raw.get("expiresAt")),
                        "refresh_token": refresh, "proxy_slot": str(raw.get("proxy_slot") or "")}
            if document["proxy_slot"] and not wb_settings.find_proxy_slot(self.directory, document["proxy_slot"]):
                raise PlatformError("proxy slot not found")
            self.validate_options(raw)
            document["access_token" if auth_type == "oauth" else "api_key"] = token
            document["access_scope"] = raw.get("access_scope", "all")
            if upstream == "opencode_zen" and auth_type == "oauth":
                orgs = raw.get("orgs") or []
                if not isinstance(orgs, list) or any(not isinstance(org, dict) or not org.get("id") for org in orgs):
                    raise PlatformError("invalid OpenCode organization list")
                gateway = raw.get("console_gateway")
                if gateway is not None:
                    if not isinstance(gateway, dict) or not wb_device_auth.official_url(gateway.get("url")):
                        raise PlatformError("OpenCode gateway must be an official HTTPS endpoint")
                    gateway = wb_device_auth.console_gateway({"provider": {str(gateway.get("provider") or "opencode"): {
                        "options": {"baseURL": gateway["url"], "apiKey": gateway.get("api_key"), "headers": gateway.get("headers")},
                        "models": gateway.get("models"), "npm": gateway.get("npm", "")}}})
                    if not gateway:
                        raise PlatformError("OpenCode gateway must provide models and its own credential")
                document.update(org_id=str(raw.get("org_id") or ""), orgs=[{"id":str(org["id"]),
                    "name":str(org.get("name") or org["id"])} for org in orgs], console_gateway=gateway)
            if raw.get("user_id") or raw.get("userId"):
                document["user_id"] = str(raw.get("user_id") or raw["userId"])
            plan.append((document, set(raw)))
        if dry_run:
            return [Account(document, "").view() for document, _ in plan]
        saved = []
        with self.lock:
            for document, provided in plan:
                uid = document["uid"]
                existing = next((a for a in self.accounts.values() if document.get("user_id") and
                    a.upstream == document["upstream"] and a.document.get("user_id") == document["user_id"] and
                    a.document.get("org_id", "") == document.get("org_id", "")), None)
                if existing:
                    uid = document["uid"] = existing.uid
                account = self.accounts.get(uid)
                if account:
                    for field in ("priority", "models", "proxy_slot", "enabled", "name", "refresh_token", "access_scope"):
                        aliases = {"refresh_token": ("refresh_token", "refreshToken")}.get(field, (field,))
                        if not any(alias in provided for alias in aliases):
                            document.pop(field, None)
                    if document["auth_type"] == "api_key":
                        account.document.pop("access_token", None)
                    else:
                        account.document.pop("api_key", None)
                    account.document.update(document)
                else:
                    account = Account(document, os.path.join(self.root, "account-" + uid + ".json"))
                    self.accounts[uid] = account
                account.save()
                if account.upstream == "opencode_zen" and account.document.get("console_gateway"):
                    self._cache_console_models(account)
                saved.append(account.view())
        for upstream in {doc["upstream"] for doc, _ in plan}:
            self.refresh_async(upstream, force=True)
        self.publish()
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
                self.publish()
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
            if "auth_type" in patch:
                if patch["auth_type"] not in ("api_key", "oauth") or account.upstream == "commandcode" and patch["auth_type"] != "api_key":
                    raise PlatformError("invalid account credential type")
                values["auth_type"] = patch["auth_type"]
            if "access_scope" in patch:
                self.validate_options(patch)
                values["access_scope"] = patch["access_scope"]
            for field in ("access_token", "api_key", "refresh_token"):
                if field not in patch:
                    continue
                if field == "access_token" and values.get("auth_type", account.document.get("auth_type")) != "oauth":
                    target = "api_key"
                else:
                    target = field
                token = patch[field]
                if not isinstance(token, str) or len(token) > 16384 or re.search(r"[\r\n\x00]", token):
                    raise PlatformError("invalid credential")
                if target != "refresh_token" and not token.strip():
                    raise PlatformError("credential must not be empty")
                values[target] = token.strip()
            kind = values.get("auth_type", account.document.get("auth_type"))
            if kind != account.document.get("auth_type") and not values.get("api_key" if kind == "api_key" else "access_token"):
                raise PlatformError("provide the credential when changing its type")
            if account.upstream == "commandcode" and "api_key" in values and not re.fullmatch(r"user_[a-zA-Z0-9_-]{8,}", values["api_key"]):
                raise PlatformError("Command Code requires its CLI user_* credential")
            credential_changed = any(field in values for field in ("access_token", "api_key", "auth_type"))
            if credential_changed:
                if values.get("auth_type", account.document.get("auth_type")) == "api_key":
                    account.document.pop("access_token", None)
                else:
                    account.document.pop("api_key", None)
                account.cooldowns.clear()
                values["cooldowns"] = {}
                values["verified_at"] = 0
                account.verified_at = 0
                account.last_error = ""
            account.document.update(values)
            account.save()
            self.publish()
            return account.view()

    def proxy(self, account):
        return self.proxy_for_slot(account.document.get("proxy_slot"))

    def proxy_for_slot(self, slot):
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
                if account.document.get("auth_type") == "oauth":
                    headers.pop("Authorization", None)
                    headers.pop("x-api-key", None)
                    headers["x-org-id"] = account.document.get("org_id", "")
                    gateway = account.document.get("console_gateway") or {}
                    if gateway.get("api_key"):
                        headers["Authorization"] = "Bearer " + gateway["api_key"]
                        headers["x-api-key"] = gateway["api_key"]
                    for key, value in (gateway.get("headers") or {}).items():
                        existing = next((name for name in headers if name.lower() == key.lower()), key)
                        headers[existing] = value
                headers.pop("X-CLIENT-TYPE", None)
                headers.pop("X-CLIENT-VERSION", None)
                headers.update(wb_opencode_client.headers(account.uid))
            elif account.upstream == "commandcode":
                headers.update(wb_commandcode.headers(account.token, str(uuid.uuid5(uuid.NAMESPACE_URL, account.uid))))
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
        if account.document.get("auth_type") != "oauth" or not account.document.get("refresh_token"):
            return
        with account.refresh_lock:
            if failed_token is not None and account.token != failed_token:
                return
            expires = account.document.get("expires_at", 0)
            if not force and (not expires or expires > time.time() + 300):
                return
            try:
                if account.upstream == "opencode_zen":
                    result = self.logins._request(wb_device_auth.OPENCODE_CONSOLE + "/auth/device/token", {
                        "grant_type": "refresh_token", "refresh_token": account.document["refresh_token"],
                        "client_id": wb_device_auth.OPENCODE_CLIENT}, proxy=self.proxy(account))
                    if not result.get("access_token") or not result.get("refresh_token"):
                        raise PlatformError("invalid OpenCode token refresh response", 502)
                    with self.lock:
                        account.document.update(access_token=result["access_token"], refresh_token=result["refresh_token"],
                                                expires_at=time.time() + result.get("expires_in", 3600))
                        account.save()
                        account.last_error = ""
                    return
                if account.upstream != "cline":
                    return
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
                try:
                    detail = exc.read(2000).decode("utf-8", "replace")
                finally:
                    exc.close()
                if exc.code in (400, 401, 403) and re.search(r"invalid_grant|invalid_token|revoked|expired", detail, re.I):
                    account.document["enabled"] = False
                    account.save()
                account.last_error = "%s credential refresh failed (HTTP %d)" % (account.upstream, exc.code)
                raise PlatformError(account.last_error, 503, "credential_refresh_failed") from exc
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if isinstance(exc, PlatformError):
                    raise
                account.last_error = account.upstream + " credential refresh unavailable"
                account.cooldowns["*"] = time.time() + 5
                raise PlatformError(account.last_error, 503, "credential_refresh_failed") from exc

    def refresh_catalog(self, upstream):
        candidates = [account for account in list(self.accounts.values()) if account.upstream == upstream and account.enabled]
        account = candidates[0] if candidates else None
        if account:
            self.ensure_token(account)
        if upstream == "commandcode":
            models = wb_commandcode.builtin_models()
            # Go accounts can use the generate protocol without permission
            # for /provider/v1/models. Keep the versioned official catalogue.
            cache = {"models": models, "updated_at": time.time(), "source": "command-code@" + wb_commandcode.PROTOCOL_VERSION}
            with self.lock:
                self.catalogues[upstream], self.catalog_errors[upstream] = cache, ""
            wb_storage.write_private_json(os.path.join(self.root, upstream + "-catalog.json"), cache)
            return cache
        if upstream == "opencode_zen" and any(item.document.get("auth_type") == "oauth" for item in candidates):
            for item in candidates:
                if item.document.get("auth_type") == "oauth":
                    self.refresh_console(item)
            legacy = next((item for item in candidates if item.document.get("auth_type") != "oauth"), None)
            if legacy:
                models = parse_catalog(upstream, self.request_json(upstream, "/models", legacy))
                with self.lock:
                    self.catalogues[upstream]["models"].update(models)
                    wb_storage.write_private_json(os.path.join(self.root, upstream + "-catalog.json"), self.catalogues[upstream])
            self.catalog_errors[upstream] = ""
            return self.catalogues[upstream]
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
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    exc.close()
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
        if account.upstream == "commandcode":
            identity = _data(self.request_json("commandcode", "/alpha/whoami?limits=1", account, timeout=30))
            org_id = (identity.get("org") or {}).get("id") or identity.get("orgId")
            suffix = "?" + urllib.parse.urlencode({"orgId": org_id}) if org_id else ""
            document = self.request_json("commandcode", "/alpha/billing/credits" + suffix, account, timeout=30)
            credits = document.get("credits") or {}
            values = [_number(credits.get(key)) for key in ("monthlyCredits", "purchasedCredits", "freeCredits")]
            amount = sum(value for value in values if value is not None) if any(value is not None for value in values) else None
            quota = document.get("windowLimits") or {}
            with self.lock:
                account.document.update(balance={"remain": amount, "unit": "credits", "updated_at": time.time()},
                    quota=quota, user_id=str((identity.get("user") or {}).get("id") or account.document.get("user_id") or account.uid))
                for window in (quota.get("fiveHour") or {}, quota.get("weekly") or {}):
                    until = _expiry(window.get("resetAt"))
                    if window.get("exceeded") and until > time.time():
                        account.cooldowns["*"] = max(account.cooldowns.get("*", 0), until)
                if amount is not None and amount > 0:
                    account.document.pop("credit_exhausted", None)
                if amount is not None and amount > 0 and not quota.get("exceeded") and not any(window.get("exceeded") for window in quota.values() if isinstance(window, dict)):
                    account.cooldowns.pop("*", None)
                account.document["cooldowns"] = dict(account.cooldowns)
                account.save()
            try:
                subscription = _data(self.request_json("commandcode", "/alpha/billing/subscriptions" + suffix, account, timeout=30))
                with self.lock:
                    account.document["plan"] = subscription.get("planId")
                    account.save()
            except (urllib.error.URLError, OSError, ValueError):
                pass
            return
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
                        if isinstance(exc, urllib.error.HTTPError):
                            exc.close()
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
                            if isinstance(exc, urllib.error.HTTPError):
                                exc.close()
            finally:
                with self.lock:
                    self.refreshing.discard(upstream)
                try:
                    wb_events.BROKER.publish("accounts", "models", "platforms")
                finally:
                    if self.database:
                        self.database.close_thread()
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
        unit = "credits" if upstream in ("cline", "commandcode") else "USD"
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
                if not any(a.upstream == upstream and a.enabled and a.allows(identifier, meta) and
                           (not a.document.get("public") or meta.get("billing_mode") == "free") for a in list(self.accounts.values())):
                    continue
                public_meta = _public_metadata(meta)
                item = dict(public_meta, id=PREFIXES[upstream] + identifier, object="model", owned_by=upstream,
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
        else:
            entry["paid_tokens"] += tokens
            if row.get("has_credit"):
                entry["paid_cost"] += _number(row.get("credit")) or 0
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
        if upstream in ("cline", "commandcode"):
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
            # Before the first measured bill, keep estimates proportional to
            # tokens so the large session window still has meaning. This
            # temporary scheduling weight is never recorded as billed usage.
            return tokens * cost / count if cost > 0 and count else tokens / 1000000
        prices = meta.get("pricing") or meta.get("cost") or {}
        price = _number(prices.get("output"))
        return tokens / 1000000 * price if price is not None else tokens / 1000000

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
            candidates = [a for a in self.accounts.values() if a.upstream == upstream and a.enabled and a.allows(model, meta)
                and a.cooldowns.get("*", 0) <= now and a.cooldowns.get(model, 0) <= now
                and (not maximum or flights.get(a.uid, 0) < maximum)
                and (not a.document.get("public") or mode == "free")
                and not (a.document.get("credit_exhausted") and mode != "free")]
            if bound_uid:
                candidates = [a for a in candidates if a.uid == bound_uid]
            if not candidates:
                raise PlatformError("the bound account is unavailable" if bound_uid else "no eligible accounts in this platform", 503, "account_unavailable")
            routing = self.routing().get(upstream) or {}
            pinned = next((a for a in candidates if routing.get("mode") == "manual" and routing.get("uid") == a.uid), None)
            if pinned and not bound_uid:
                candidates = [pinned]
            best_priority = min(a.priority for a in candidates)
            candidates = [a for a in candidates if a.priority == best_priority]
            def load(a):
                stat = self.daily.get(a.uid, {})
                return (stat.get("free_tokens", 0) if mode == "free" else self._paid_load(a)) + pending.get(a.uid, 0)
            chosen = min(candidates, key=lambda a: (load(a), flights.get(a.uid, 0),
                self.daily.get(a.uid, {}).get("paid_tokens", 0) if mode != "free" else 0, a.uid))
            if routing.get("mode") == "roundrobin" and not bound_uid:
                chosen = min(candidates, key=lambda a: (self.last_picks.get(a.uid, 0), a.uid))
            affinity = hashlib.sha256((owner + "\0" + upstream + "\0" + session).encode()).hexdigest() if session else None
            previous = self.database.affinity_get("platform:" + affinity) if affinity and self.database else None
            window = wb_settings.pool_config(self.directory).get("free_switch_window_tokens", 262144)
            old = next((a for a in candidates if a.uid == previous), None)
            tolerance = window if mode == "free" else self._paid_estimate(upstream, meta, window)
            if old and routing.get("mode", "fair") == "fair" and load(old) - load(chosen) < tolerance:
                chosen = old
            if affinity and self.database:
                self.database.affinity_set("platform:" + affinity, chosen.uid, 7200)
            identifier = uuid.uuid4().hex
            self.reservations[identifier] = {"uid": chosen.uid, "estimate": estimated, "mode": mode}
            self.last_picks[chosen.uid] = time.monotonic()
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
                policy = (wb_settings.load(self.directory).get("cline_routes") or {}).get(model)
                try:
                    request_body = wb_cline_routes.apply(request_body, policy)
                except ValueError as exc:
                    raise PlatformError(str(exc)) from exc
            if upstream == "commandcode":
                command_session = str(uuid.uuid5(uuid.NAMESPACE_URL, owner + "\0" + account.uid + "\0" + (session or uuid.uuid4().hex)))
                request_body = wb_commandcode.envelope(request_body, command_session, PlatformError)
            client_headers = wb_opencode_client.headers(account.uid, session, owner, body) if upstream == "opencode_zen" else {}
            for attempt in range(2):
                token = account.token
                headers = self.headers(account)
                headers.update(client_headers)
                if upstream == "cline":
                    headers["X-Task-ID"] = request_body["session_id"]
                base = self.bases[upstream]
                if upstream == "opencode_zen" and account.document.get("auth_type") == "oauth":
                    gateway = account.document.get("console_gateway") or {}
                    if not gateway.get("url"):
                        raise PlatformError("OpenCode organization has no model gateway; refresh its configuration", 503, "account_unavailable")
                    base = gateway["url"]
                    configured = (gateway.get("models") or {}).get(model) or {}
                    api = configured.get("api") if isinstance(configured.get("api"), dict) else {}
                    if api.get("url"):
                        if not wb_device_auth.official_url(api["url"]):
                            raise PlatformError("OpenCode model endpoint is not an official gateway", 503)
                        base = api["url"]
                    request_body["model"] = api.get("id") or configured.get("id") or model
                endpoint = {"chat": "/chat/completions", "responses": "/responses", "messages": "/messages"}[native]
                if upstream == "commandcode":
                    endpoint = "/alpha/generate"
                    headers.update(wb_commandcode.headers(account.token, command_session))
                request = urllib.request.Request(base.rstrip("/") + endpoint,
                    data=json.dumps(request_body, ensure_ascii=False, allow_nan=False).encode(), headers=headers)
                try:
                    timeout = wb_settings.upstream_config(self.directory)["header_timeout_seconds"]
                    response = self.transport(request, timeout=timeout, proxy=self.proxy(account))
                    if upstream == "commandcode":
                        response = wb_commandcode.ChatResponse(response, dict(body, model=model), PlatformError)
                    lease = Lease(self, response, account, ticket, model, mode)
                    lease.expected_choices = body.get("n") if type(body.get("n")) is int else 1
                    return lease
                except urllib.error.HTTPError as exc:
                    try:
                        detail = exc.read(4096).decode("utf-8", "replace")
                    finally:
                        exc.close()
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
                        scope = "*" if "INFERENCE_CAP_ERROR" in detail or upstream == "commandcode" and "USAGE_EXCEEDED" in detail else model
                        if upstream == "commandcode":
                            try:
                                parsed = json.loads(detail)
                                failure = parsed.get("error") if isinstance(parsed.get("error"), dict) else parsed
                                limit = failure.get("rateLimit") or parsed.get("rateLimit") or (failure.get("details") or {}).get("rateLimit") or {}
                                if limit.get("window") in ("fiveHour", "weekly") or failure.get("code") == "USAGE_EXCEEDED":
                                    scope = "*"
                                    wait = max(wait, int(_expiry(limit.get("reset")) - time.time()) + 1) if limit.get("reset") else max(wait, 600)
                                quota = parsed.get("windowLimits") or {}
                                resets = [_expiry(value.get("resetAt")) for value in quota.values() if isinstance(value, dict) and value.get("exceeded")]
                                if resets:
                                    wait = max(wait, int(max(resets) - time.time()) + 1)
                            except (ValueError, AttributeError):
                                pass
                        account.cooldowns[scope] = time.time() + wait
                    elif exc.code in (401, 402, 403):
                        account.cooldowns["*" if upstream == "commandcode" and exc.code == 402 else model] = time.time() + 300
                        if upstream == "commandcode" and exc.code == 402:
                            account.document["credit_exhausted"] = True
                    elif exc.code >= 500:
                        account.cooldowns["*"] = time.time() + 5
                    account.last_error = "upstream HTTP %d" % exc.code
                    account.document["cooldowns"] = dict(account.cooldowns)
                    account.save()
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
            return {"accounts": accounts, "routing": self.routing(),
                    "cline_routes": copy.deepcopy(wb_settings.load(self.directory).get("cline_routes") or {}),
                    "models_revision": model_revision, "catalogues": {upstream: {
                "updated_at": cache.get("updated_at", 0), "stale": time.time() - cache.get("updated_at", 0) > 600,
                "count": len(cache.get("models", {})), "error": self.catalog_errors.get(upstream, ""),
                "refreshing": upstream in self.refreshing} for upstream, cache in self.catalogues.items()}}

    def start_login(self, upstream="cline", options=None):
        return self.logins.start(upstream, options)

    def poll_login(self, identifier):
        return self.logins.view(identifier)

    def cancel_login(self, identifier):
        return self.logins.cancel(identifier)

    def complete_login(self, identifier, org_id):
        return self.logins.complete(identifier, org_id)
