"""Public-only HTTP transport: validate every hop and connect to validated IPs.

Host headers and TLS SNI retain the original hostname. Proxy requests also use
numeric destination addresses, so a proxy cannot resolve them to an internal
host. The configured proxy itself is an operator-controlled trusted endpoint.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import http.client
import ipaddress
import re
import socket
import ssl
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import os
import wb_forward_proxy

_dns_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-dns")
_dns_slots = threading.BoundedSemaphore(4)
MAX_REDIRECTS = 5


def public_ip(value):
    address = ipaddress.ip_address(value)
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_global and not address.is_multicast


def guard_url(url):
    url = str(url or "")
    if re.search(r"[\x00-\x20\x7f\\]", url):
        return None, "URL contains whitespace, control characters or backslashes."
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
        if parsed.scheme not in ("http", "https"):
            return None, "Only http:// or https:// URLs are supported."
        if parsed.username is not None or parsed.password is not None:
            return None, "Credentials in the URL are not allowed."
        if port is not None and not 1 <= port <= 65535:
            return None, "Invalid port."
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Reject non-canonical IPv4 spellings accepted by libc (octal,
            # shortened and integer forms), instead of resolving them later.
            if not host or re.fullmatch(r"[0-9.]+", host) or ":" in host:
                return None, "Invalid or ambiguous host."
            host = host.encode("idna").decode("ascii")
            if ("." not in host or host.endswith(".localhost")
                    or not re.fullmatch(r"[a-z0-9.-]+", host)
                    or any(not label or label.startswith("-") or label.endswith("-")
                           for label in host.split("."))):
                return None, "Private or invalid hosts are not allowed."
        else:
            if not public_ip(address):
                return None, "Non-public network addresses are not allowed."
        return url, ""
    except (ValueError, UnicodeError):
        return None, "Invalid URL."


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("web request deadline exceeded")
    return seconds


def resolve_public(host, port, deadline):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _dns_slots.acquire(timeout=remaining(deadline)):
            raise TimeoutError("web DNS workers are busy")
        try:
            task = _dns_pool.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        except Exception:
            _dns_slots.release()
            raise
        # A timed-out libc lookup can continue running. Keep its slot occupied
        # until it actually ends, so subsequent requests cannot grow the queue.
        task.add_done_callback(lambda _task, slots=_dns_slots: slots.release())
        try:
            records = task.result(timeout=remaining(deadline))
        except FutureTimeout:
            task.cancel()
            raise TimeoutError("web DNS deadline exceeded") from None
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    else:
        addresses = [str(address)]
    if not addresses or any(not public_ip(address) for address in addresses):
        raise ValueError("DNS resolved to a non-public network address")
    return addresses


def _authority(host, port):
    return ("[%s]" % host if ":" in host else host) + ":" + str(port)


def proxy_for(url):
    explicit = os.environ.get("WB_WEB_PROXY", "").strip()
    if explicit:
        return explicit
    parsed = urllib.parse.urlsplit(url)
    if urllib.request.proxy_bypass(parsed.hostname):
        return ""
    return urllib.request.getproxies().get(parsed.scheme, "")


class _TunnelHTTPS(http.client.HTTPSConnection):
    def __init__(self, *args, origin_host, **kwargs):
        self.origin_host = origin_host
        super().__init__(*args, **kwargs)

    def connect(self):
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.origin_host)


def open_response(url, deadline, headers):
    """Return (connection, response); callers must close both on every path."""
    safe, error = guard_url(url)
    if error:
        raise ValueError(error)
    parsed = urllib.parse.urlsplit(safe)
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = resolve_public(host, port, deadline)
    proxy_url = proxy_for(url)
    request_headers = dict(headers, Host=_authority(host, port))
    path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    last_error = None
    for address in addresses:
        if proxy_url:
            explicit = bool(os.environ.get("WB_WEB_PROXY", "").strip())
            proxy = wb_forward_proxy.parse(proxy_url,
                (os.environ.get("WB_WEB_PROXY_USERNAME") or None) if explicit else None,
                (os.environ.get("WB_WEB_PROXY_PASSWORD") or None) if explicit else None)
            # stdlib has no TLS-in-TLS socket. Fail explicitly rather than
            # downgrade an HTTPS proxy or silently send unvalidated hostnames.
            if parsed.scheme == "https" and proxy.scheme == "https":
                raise ValueError("HTTPS destinations require an http:// CONNECT proxy")
            credentials = proxy.auth_headers()
            if proxy.scheme.startswith("socks"):
                conn = wb_forward_proxy.socks_connection(host, port, proxy,
                    secure=parsed.scheme == "https", timeout=remaining(deadline),
                    context=context, target_host=address)
            elif parsed.scheme == "https":
                conn = _TunnelHTTPS(proxy.host, proxy.port, timeout=remaining(deadline),
                                    context=context, origin_host=host)
                conn.set_tunnel(address, port, headers=dict(credentials, Host=_authority(address, port)))
            else:
                kind = http.client.HTTPSConnection if proxy.scheme == "https" else http.client.HTTPConnection
                conn = kind(proxy.host, proxy.port,
                            timeout=remaining(deadline))
                request_headers.update(credentials)
                path = urllib.parse.urlunsplit((parsed.scheme, _authority(address, port),
                                               parsed.path or "/", parsed.query, ""))
        else:
            kind = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            conn = kind(host, port, timeout=remaining(deadline))
            # HTTPSConnection still verifies the certificate and SNI for host;
            # only its TCP destination changes. No second hostname lookup.
            conn._create_connection = lambda _target, timeout, *a, **kw: socket.create_connection(
                (address, port), timeout=min(timeout, remaining(deadline)))
        try:
            conn.request("GET", path, headers=request_headers)
            response = conn.getresponse()
            return conn, response
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            last_error = exc
    raise last_error or OSError("no usable public address")
