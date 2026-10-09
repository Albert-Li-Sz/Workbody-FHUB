"""Cancellable device authorization for Cline and OpenCode's console.

Only public job metadata leaves this module. Device/refresh/access tokens
remain private, including while an organization choice is pending.
"""
import copy
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wb_opencode_client

CLINE_ISSUER = "https://api.workos.com"
CLINE_CLIENT = "client_01K3A541FN8TA3EPPHTD2325AR"
OPENCODE_CONSOLE = "https://opencode.ai/console"
OPENCODE_CLIENT = "opencode-cli"
PUBLIC_FIELDS = ("id", "upstream", "status", "expires_at", "url", "code", "account", "error", "orgs")


def official_url(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or ""))
        return bool(parsed.scheme == "https" and parsed.hostname and
                (parsed.hostname == "opencode.ai" or parsed.hostname.endswith(".opencode.ai")) and
                not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


def console_credential(value, token):
    """Resolve only the selected account's official console token reference.

    Never consult process environment or read files for remote configuration:
    those values belong to other accounts or to the host, not this tenant.
    Keep the template private so a refreshed token is used on every request.
    """
    if not isinstance(value, str) or len(value) > 16384 or any(c in value for c in "\r\n\x00"):
        raise ValueError("invalid OpenCode credential configuration")
    reference = "{env:OPENCODE_CONSOLE_TOKEN}"
    if reference in value:
        if not isinstance(token, str) or not token or any(c in token for c in "\r\n\x00"):
            raise ValueError("OpenCode console token is unavailable")
        value = value.replace(reference, token)
    if any(marker in value for marker in ("{env:", "{file:", "${")):
        raise ValueError("OpenCode credential configuration contains an unresolved reference")
    return value


def console_gateway(document, defaults=None):
    """Read provider configuration issued by the official console.

    Keep the tenant gateway and model list, including the token reference
    explicitly issued by the console, instead of substituting legacy Zen.
    """
    config = document.get("config", document) if isinstance(document, dict) else {}
    if not isinstance(config, dict):
        return None
    providers = config.get("provider") or config.get("providers") or {}
    ordered = list(providers.items()) if isinstance(providers, dict) else []
    ordered.sort(key=lambda item: item[0] not in ("opencode", "opencode_zen", "opencode-zen"))
    disabled = config.get("disabled_providers") or []
    gateways = {}
    for name, provider in ordered:
        if not isinstance(provider, dict) or isinstance(disabled, list) and name in disabled:
            continue
        options = provider.get("options") or {}
        if not isinstance(options, dict):
            continue
        inherited = (defaults or {}).get(name) or {}
        url = options.get("baseURL") or provider.get("baseURL") or provider.get("api") or inherited.get("api")
        if not official_url(url):
            continue
        models = provider.get("models") or inherited.get("models")
        if not isinstance(models, dict) or not models:
            continue
        # Restrict headers to protocol/tenant metadata. Secrets supplied in
        # configuration are stored privately and never serialized by view().
        headers = options.get("headers") or {}
        safe_headers = {}
        if isinstance(headers, dict):
            for key, value in headers.items():
                if (str(key).lower() in ("authorization", "x-api-key", "x-org-id", "x-opencode-org-id", "x-workspace-id")
                        and isinstance(value, str) and not any(c in value for c in "\r\n\x00")):
                    safe_headers[key] = value
        whitelist = provider.get("whitelist")
        blacklist = provider.get("blacklist") or []
        clean_models = {}
        for key, value in models.items():
            if (not isinstance(key, str) or not isinstance(value, dict) or value.get("disabled") is True
                    or value.get("status") == "deprecated"):
                continue
            if isinstance(whitelist, list) and key not in whitelist:
                continue
            if isinstance(blacklist, list) and key in blacklist:
                continue
            api = value.get("api") if isinstance(value.get("api"), dict) else {}
            override = value.get("provider") if isinstance(value.get("provider"), dict) else {}
            if any(endpoint and not official_url(endpoint) for endpoint in (api.get("url"), override.get("api"))):
                continue
            clean_models[key] = value
        api_key = options.get("apiKey") if isinstance(options.get("apiKey"), str) else ""
        if not clean_models or not (api_key or any(key.lower() in ("authorization", "x-api-key") and value for key, value in safe_headers.items())):
            continue
        try:
            console_credential(api_key, "configuration-validation")
            for value in safe_headers.values():
                console_credential(value, "configuration-validation")
        except ValueError:
            continue
        gateways[name] = {"url": str(url).rstrip("/"), "provider": name,
                "api_key": api_key,
                "headers": safe_headers, "models": copy.deepcopy(clean_models), "npm": provider.get("npm") or inherited.get("npm", "")}
    if not gateways:
        return None
    # Zen and Go can advertise the same model with different billing and
    # credentials. Keep an explicit namespace; a subscription request must
    # never fall back to the Zen wallet just because its wire ID matches.
    primary = next(iter(gateways.values()))
    combined, routes = {}, {}
    for name, gateway in gateways.items():
        for identifier, metadata in gateway["models"].items():
            alias = "go/" + identifier if name == "opencode-go" else identifier
            if alias in combined:
                continue
            meta = copy.deepcopy(metadata)
            meta.setdefault("npm", gateway["npm"])
            meta["console_provider"] = name
            if name == "opencode-go":
                meta.update(entitlement="subscription", billing_mode="paid")
            combined[alias] = meta
            routes[alias] = {"provider": name, "wire_id": identifier}
    return dict(primary, models=combined, provider_gateways=gateways, model_routes=routes, config_version=3)


def model_gateway(gateway, model=None, provider=None):
    """Select private provider credentials without mixing plans or accounts."""
    route = (gateway.get("model_routes") or {}).get(model) or {}
    name = provider or route.get("provider")
    if name:
        selected = (gateway.get("provider_gateways") or {}).get(name)
        if selected:
            return selected
        if name != gateway.get("provider"):
            raise ValueError("OpenCode provider gateway is unavailable")
    return gateway


def import_gateway(gateway):
    """Revalidate exported private configuration and rebuild trusted routes."""
    if not isinstance(gateway, dict):
        return None
    sources = gateway.get("provider_gateways")
    if not isinstance(sources, dict) or not sources:
        sources = {str(gateway.get("provider") or "opencode"): gateway}
    providers = {}
    for name, source in sources.items():
        if not isinstance(source, dict) or not official_url(source.get("url")):
            return None
        providers[name] = {"api": source["url"], "options": {"apiKey": source.get("api_key"),
            "headers": source.get("headers")}, "npm": source.get("npm", ""), "models": source.get("models")}
    return console_gateway({"provider": providers})


class DeviceLogins:
    def __init__(self, manager, error_type):
        self.manager, self.error = manager, error_type
        self.lock = threading.RLock()
        self.jobs = {}

    def _request(self, url, body=None, proxy="", form=False, token=None, org=None):
        data = ((urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode())
                if body is not None else None)
        headers = {"Accept": "application/json", "Content-Type":
                   "application/x-www-form-urlencoded" if form else "application/json"}
        if official_url(url):
            headers.update({"User-Agent": wb_opencode_client.USER_AGENT, "x-opencode-client": "cli"})
        if token:
            headers["Authorization"] = "Bearer " + token
        if org:
            headers["x-org-id"] = org
        request = urllib.request.Request(url, data=data, headers=headers)
        with self.manager.transport(request, timeout=20, proxy=proxy) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise self.error("authorization metadata exceeds the size limit", 502)
        return json.loads(raw)

    def _active(self, job):
        return (job["status"] in ("pending", "select_org") and not job["cancel"].is_set()
                and not self.manager.stopping.is_set() and time.time() < job["expires_at"])

    def view(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise self.error("login not found", 404)
            if job["status"] in ("pending", "select_org") and time.time() >= job["expires_at"]:
                job["status"] = "expired"
                job["cancel"].set()
                job.pop("tokens", None)
            return copy.deepcopy({key: job[key] for key in PUBLIC_FIELDS if key in job})

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job:
                raise self.error("login not found", 404)
            if job["status"] in ("pending", "select_org"):
                job.update(status="cancelled")
                job["cancel"].set()
                job.pop("tokens", None)
            return self.view(identifier)

    def start(self, upstream="cline", options=None):
        if upstream not in ("cline", "opencode_zen"):
            raise self.error("device login supports Cline and OpenCode")
        options = dict(options or {})
        options = {key: options[key] for key in ("name", "priority", "proxy_slot", "models", "access_scope") if key in options}
        self.manager.validate_options(options)
        proxy = self.manager.proxy_for_slot(options.get("proxy_slot", ""))
        issuer = CLINE_ISSUER if upstream == "cline" else OPENCODE_CONSOLE
        client = CLINE_CLIENT if upstream == "cline" else OPENCODE_CLIENT
        with self.lock:
            self.jobs = {key: value for key, value in self.jobs.items() if value["expires_at"] + 300 > time.time()}
            if sum(self._active(job) for job in self.jobs.values()) >= 10:
                raise self.error("too many pending device logins", 429)
            identifier = uuid.uuid4().hex
            job = {"id": identifier, "upstream": upstream, "status": "pending",
                   "expires_at": time.time() + 600, "cancel": threading.Event(),
                   "options": options, "proxy": proxy, "issuer": issuer, "client": client}
            self.jobs[identifier] = job
        try:
            auth = self._request(issuer + ("/user_management/authorize/device" if upstream == "cline" else "/auth/device/code"),
                                 {"client_id": client}, proxy, form=upstream == "cline")
            url = auth.get("verification_uri_complete") or auth.get("verification_uri")
            url = urllib.parse.urljoin(issuer + "/", str(url or ""))
            parsed = urllib.parse.urlsplit(url)
            if (not auth.get("device_code") or parsed.scheme != "https" or not parsed.hostname
                    or parsed.username or parsed.password or upstream == "opencode_zen" and not official_url(url)):
                raise self.error("invalid device authorization response", 502)
            lifetime = auth.get("expires_in", 600)
            if type(lifetime) not in (int, float) or not 0 < lifetime <= 86400:
                raise self.error("invalid authorization lifetime", 502)
            with self.lock:
                job.update(url=url, code=str(auth.get("user_code") or ""), expires_at=time.time() + min(1800, lifetime))
        except Exception as exc:
            with self.lock:
                job.update(status="failed", error="device authorization unavailable" +
                           (" (HTTP %d)" % exc.code if isinstance(exc, urllib.error.HTTPError) else ""))
                job["cancel"].set()
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            raise self.error(job["error"], 502, "device_authorization_failed") from exc
        threading.Thread(target=self._poll, args=(job, auth), daemon=True, name=upstream + "-device-login").start()
        return self.view(identifier)

    def _poll(self, job, auth):
        try:
            interval = max(1, min(60, float(auth.get("interval", 5))))
            while self._active(job) and not job["cancel"].wait(interval):
                fields = {"client_id": job["client"], "device_code": auth["device_code"],
                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
                try:
                    tokens = self._request(job["issuer"] + ("/user_management/authenticate" if job["upstream"] == "cline" else "/auth/device/token"),
                                           fields, job["proxy"], form=job["upstream"] == "cline")
                except urllib.error.HTTPError as exc:
                    try:
                        tokens = json.loads(exc.read(4096))
                    except ValueError:
                        raise self.error("device token request failed (HTTP %d)" % exc.code, 502) from exc
                    finally:
                        exc.close()
                    if not isinstance(tokens, dict) or not tokens.get("error"):
                        raise
                state = tokens.get("error")
                if state == "authorization_pending":
                    continue
                if state == "slow_down":
                    interval = min(60, interval + 5)
                    continue
                if state:
                    with self.lock:
                        if self._active(job):
                            job.update(status="denied" if state == "access_denied" else "expired" if state == "expired_token" else "failed",
                                       error="authorization " + str(state)[:80])
                    return
                if not tokens.get("access_token") or not tokens.get("refresh_token"):
                    raise self.error("invalid device token response", 502)
                if not self._active(job):
                    return
                if job["upstream"] == "cline":
                    result = self._request(self.manager.bases["cline"] + "/auth/register", {
                        "accessToken": tokens["access_token"], "refreshToken": tokens["refresh_token"]}, job["proxy"])
                    result = result.get("data", result)
                    info = result.get("userInfo") or {}
                    with self.lock:
                        if self._active(job):
                            imported = self.manager.import_accounts(dict(result, upstream="cline", auth_type="oauth",
                                email=info.get("email"), user_id=info.get("clineUserId"), **job["options"]))
                            job.update(status="completed", account=imported[0]["uid"])
                    return
                user = self._request(OPENCODE_CONSOLE + "/api/user", proxy=job["proxy"], token=tokens["access_token"])
                orgs = self._request(OPENCODE_CONSOLE + "/api/orgs", proxy=job["proxy"], token=tokens["access_token"])
                if not isinstance(user, dict) or not user.get("id") or not isinstance(orgs, list):
                    raise self.error("invalid OpenCode account response", 502)
                orgs = [{"id": str(org["id"]), "name": str(org.get("name") or org["id"])}
                        for org in orgs if isinstance(org, dict) and org.get("id")]
                if not orgs:
                    raise self.error("OpenCode account has no organization; create one in the official console first", 409, "organization_required")
                with self.lock:
                    if not self._active(job):
                        return
                    job.update(tokens=tokens, user=user, orgs=orgs, status="select_org")
                if len(job["orgs"]) == 1:
                    self.complete(job["id"], job["orgs"][0]["id"])
                return
            with self.lock:
                if job["status"] == "pending":
                    job["status"] = "expired"
        except Exception as exc:
            with self.lock:
                if self._active(job):
                    message = (str(exc) if isinstance(exc, self.error) and exc.code == "organization_required" else
                               "authorization failed" + (" (HTTP %d)" % exc.code if isinstance(exc, urllib.error.HTTPError) else " (%s)" % type(exc).__name__))
                    job.update(status="failed", error=message)
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
        finally:
            if job["status"] != "select_org":
                job.pop("tokens", None)
            try:
                self.manager.publish()
            finally:
                if self.manager.database:
                    self.manager.database.close_thread()

    def complete(self, identifier, org_id):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or not self._active(job) or job["status"] != "select_org":
                raise self.error("authorization is no longer pending", 409)
            if org_id not in [org["id"] for org in job["orgs"]]:
                raise self.error("organization is not available for this account")
            token = job["tokens"]["access_token"]
        config = self._request(OPENCODE_CONSOLE + "/api/config", proxy=job["proxy"], token=token, org=org_id)
        gateway = self.manager.console_gateway(config, proxy=job["proxy"])
        with self.lock:
            if not self._active(job):
                raise self.error("authorization was cancelled or expired", 409)
            # Store an authenticated account even if its organization has no
            # model provider yet; it stays unavailable until config is ready.
            imported = self.manager.import_accounts(dict(job["options"], upstream="opencode_zen", auth_type="oauth",
                access_token=token, refresh_token=job["tokens"]["refresh_token"],
                expires_at=time.time() + job["tokens"].get("expires_in", 3600),
                user_id=str(job["user"]["id"]), email=job["user"].get("email"), org_id=org_id,
                orgs=job["orgs"], console_gateway=gateway))
            job.update(status="completed", account=imported[0]["uid"])
            job.pop("tokens", None)
        self.manager.publish()
        return self.view(identifier)
