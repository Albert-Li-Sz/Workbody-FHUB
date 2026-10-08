"""Nginx + Certbot supervisor. HTTP-01 stays available throughout renewal.

No Docker socket, host cron or manual Nginx plugin installation is required.
The public IP is discovered without inheriting the model account's proxy.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request

WEBROOT = Path("/var/lib/letsencrypt/webroot")
CONFIG = Path("/etc/nginx/conf.d/default.conf")
LIVE = Path("/etc/letsencrypt/live/workbody")
STATE = Path("/var/lib/letsencrypt/workbody-state.json")
STATUS = Path("/run/workbody/tls-status.json")
CERTBOT = "/opt/acme/bin/certbot"
STOPPED = False
NGINX = None


def log(message):
    print("[workbody-nginx] " + message, flush=True)


def atomic_text(path, text, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(temporary), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w") as output:
        output.write(text)
    os.replace(temporary, path)


def publish_status(status, identifiers=None, error=None):
    payload = {"status": status, "identifiers": identifiers or [], "updated_at": time.time(),
               "automatic_renewal": os.environ.get("WB_TLS_MODE", "auto") != "off"}
    if error:
        payload["error"] = error
    atomic_text(STATUS, json.dumps(payload))


def public_ip():
    configured = os.environ.get("WB_PUBLIC_IP", "").strip()
    if configured:
        address = ipaddress.ip_address(configured)
        if not address.is_global:
            raise ValueError("WB_PUBLIC_IP must be a public IP address")
        return str(address)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in ("https://api.ipify.org", "https://ipv4.icanhazip.com"):
        try:
            with opener.open(url, timeout=10) as response:
                raw = response.read(128).decode("ascii").strip()
            address = ipaddress.ip_address(raw)
            if address.is_global:
                return str(address)
        except (OSError, ValueError):
            pass
    raise RuntimeError("cannot discover a public IP; set WB_PUBLIC_IP to the server's public address")


def domains():
    entries = [value.strip().lower() for value in os.environ.get("WB_TLS_DOMAINS", "").split(",") if value.strip()]
    for value in entries:
        if (len(value) > 253 or "." not in value
                or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split("."))):
            raise ValueError("WB_TLS_DOMAINS must contain comma-separated DNS names")
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        raise ValueError("use WB_PUBLIC_IP for IP addresses")
    return sorted(set(entries))


def config_text(tls=False):
    upstream = os.environ.get("WB_NGINX_UPSTREAM", "workbody-fhub:8788")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+:[0-9]{1,5}", upstream):
        raise ValueError("WB_NGINX_UPSTREAM must be a hostname:port")
    common = """
    resolver 127.0.0.11 valid=10s ipv6=off;
    resolver_timeout 5s;
    client_max_body_size 50m;
    client_body_timeout 60s;
    send_timeout 360s;
    location = /nginx-health { access_log off; return 200 'ok\\n'; }
    location = /tls/status { alias /run/workbody/tls-status.json; default_type application/json; }
    location ^~ /.well-known/acme-challenge/ {
        root /var/lib/letsencrypt/webroot;
        default_type text/plain;
        try_files $uri =404;
    }
"""
    proxy = """
    location / {
        set $workbody_backend %s;
        proxy_pass http://$workbody_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_send_timeout 300s;
        proxy_read_timeout 360s;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        proxy_pass_header X-Accel-Buffering;
        proxy_ignore_client_abort off;
        gzip off;
    }
""" % upstream
    mode = os.environ.get("WB_TLS_MODE", "auto").strip().lower()
    http_location = proxy if mode == "off" else (
        "    location / { return 308 https://$host$request_uri; }\n" if tls else
        "    location / { default_type application/json; return 503 '{\"error\":\"TLS certificate is being provisioned; see /tls/status\"}'; }\n")
    # $request_uri / $request / Referer can contain a legacy API key query.
    # Keep access logs useful without recording URL query credentials.
    text = """log_format workbody '$remote_addr [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent $request_time';
access_log /var/log/nginx/access.log workbody;
""" + "server {\n    listen 80 default_server;\n    listen [::]:80 default_server;\n    server_name _;\n" + common + http_location + "}\n"
    if tls and mode != "off":
        text += """
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name _;
    ssl_certificate /etc/letsencrypt/live/workbody/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/workbody/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:workbody_tls:10m;
    ssl_session_timeout 1d;
""" + common + proxy + "}\n"
    return text


def install_config(tls=False, reload=False):
    old = CONFIG.read_text() if CONFIG.exists() else None
    atomic_text(CONFIG, config_text(tls))
    checked = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if checked.returncode:
        if old is not None:
            atomic_text(CONFIG, old)
        raise RuntimeError("Nginx configuration rejected: " + checked.stderr.strip())
    if reload:
        subprocess.run(["nginx", "-s", "reload"], check=True)


def run_certbot(arguments):
    common = [CERTBOT, "--non-interactive", "--agree-tos", "--no-eff-email"]
    email = os.environ.get("WB_ACME_EMAIL", "").strip()
    common += ["--email", email] if email else ["--register-unsafely-without-email"]
    if os.environ.get("WB_ACME_STAGING", "0").lower() in ("1", "true", "yes"):
        common += ["--staging"]
    result = subprocess.run(common + arguments, timeout=300)
    return result.returncode == 0


def provision():
    mode = os.environ.get("WB_TLS_MODE", "auto").strip().lower()
    if mode == "off":
        publish_status("disabled")
        return True
    ip = public_ip() if mode == "auto" else None
    names = domains()
    if mode == "domain" and not names:
        raise ValueError("domain mode requires WB_TLS_DOMAINS")
    identifiers = ([ip] if ip else []) + names
    try:
        previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    except (ValueError, OSError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    staging = os.environ.get("WB_ACME_STAGING", "0").lower() in ("1", "true", "yes")
    changed = previous.get("identifiers") != identifiers or previous.get("staging") != staging
    if not LIVE.joinpath("fullchain.pem").exists() or changed:
        publish_status("issuing", identifiers)
        arguments = ["certonly", "--webroot", "--webroot-path", str(WEBROOT),
                     "--cert-name", "workbody", "--preferred-profile", "shortlived"]
        if changed and LIVE.joinpath("fullchain.pem").exists():
            arguments += ["--force-renewal"]
        if ip:
            arguments += ["--ip-address", ip]
        for name in names:
            arguments += ["-d", name]
        if not run_certbot(arguments):
            publish_status("retrying", identifiers, "certificate request failed; check public port 80 and container logs")
            return False
    else:
        publish_status("renewing", identifiers)
        if not run_certbot(["renew", "--cert-name", "workbody", "--quiet"]):
            publish_status("retrying", identifiers, "certificate renewal failed; check container logs")
            return False
    install_config(tls=True, reload=True)
    atomic_text(STATE, json.dumps({"identifiers": identifiers, "staging": staging}), private=True)
    publish_status("staging" if staging else "ready", identifiers)
    log("HTTPS ready for " + ", ".join(identifiers) + "; automatic certificate checks every six hours")
    return True


def stop(signum, frame):
    global STOPPED
    STOPPED = True
    if NGINX and NGINX.poll() is None:
        NGINX.send_signal(signal.SIGQUIT)


def main():
    global NGINX
    mode = os.environ.get("WB_TLS_MODE", "auto").strip().lower()
    if mode not in ("auto", "domain", "off"):
        raise ValueError("WB_TLS_MODE must be auto, domain or off")
    WEBROOT.mkdir(parents=True, exist_ok=True)
    publish_status("disabled" if mode == "off" else "starting")
    try:
        install_config(tls=LIVE.joinpath("fullchain.pem").exists() and LIVE.joinpath("privkey.pem").exists())
    except RuntimeError:
        log("Existing TLS files could not be loaded; starting HTTP-01 for recovery")
        install_config(tls=False)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    NGINX = subprocess.Popen(["nginx", "-g", "daemon off;"])
    due = time.monotonic()
    try:
        while not STOPPED:
            if NGINX.poll() is not None:
                raise RuntimeError("Nginx exited with status %s" % NGINX.returncode)
            if time.monotonic() >= due and mode != "off":
                try:
                    success = provision()
                except Exception as exc:
                    success = False
                    publish_status("retrying", error="TLS provisioning failed; check container logs")
                    log(str(exc))
                period = "WB_ACME_CHECK_SECONDS" if success else "WB_ACME_RETRY_SECONDS"
                due = time.monotonic() + max(300, float(os.environ.get(period, 21600 if success else 1800)))
            time.sleep(1)
    finally:
        if NGINX.poll() is None:
            NGINX.send_signal(signal.SIGQUIT)
            try:
                NGINX.wait(timeout=15)
            except subprocess.TimeoutExpired:
                NGINX.terminate()
                NGINX.wait(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log(str(error))
        sys.exit(1)
