"""Authenticated HTTP and SOCKS5 transports using the standard library.

SOCKS framing follows RFC 1928; username/password auth follows RFC 1929.
No global socket patching: every connection carries its own proxy identity.
"""
import base64
from dataclasses import dataclass, field
import http.client
import ipaddress
import re
import socket
import time
import urllib.parse
import urllib.request


@dataclass(frozen=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)

    def auth_headers(self):
        if not self.username:
            return {}
        value = (self.username + ":" + self.password).encode("utf-8")
        return {"Proxy-Authorization": "Basic " + base64.b64encode(value).decode("ascii")}


def parse(url, username=None, password=None):
    try:
        raw = str(url or "").strip()
        if re.search(r"[\x00-\x20\x7f\\]", raw):
            raise ValueError()
        value = urllib.parse.urlsplit(raw)
        scheme = "socks5" if value.scheme == "socks" else value.scheme
        if scheme not in ("http", "https", "socks5", "socks5h") or not value.hostname:
            raise ValueError()
        if value.path not in ("", "/") or value.query or value.fragment:
            raise ValueError()
        port = value.port if value.port is not None else (
            1080 if scheme.startswith("socks") else 443 if scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        user = str(username) if username not in (None, "") else urllib.parse.unquote(value.username or "")
        secret = str(password) if password not in (None, "") else urllib.parse.unquote(value.password or "")
        if secret and not user:
            raise ValueError()
        if scheme.startswith("socks") and user:
            if not 1 <= len(user.encode()) <= 255 or not 1 <= len(secret.encode()) <= 255:
                raise ValueError()
        return Proxy(scheme, value.hostname, port, user, secret)
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("invalid proxy URL or credentials; use http://, https://, socks5:// or socks5h://") from None


def slot_url(slot):
    """Runtime URL including explicitly stored credentials (never a label)."""
    proxy = parse(slot["url"], slot.get("username"), slot.get("password"))
    value = urllib.parse.urlsplit(slot["url"])
    host = "[%s]" % proxy.host if ":" in proxy.host else proxy.host
    authority = host + (":" + str(value.port) if value.port is not None else "")
    if proxy.username:
        authority = (urllib.parse.quote(proxy.username, safe="") + ":"
                     + urllib.parse.quote(proxy.password, safe="") + "@" + authority)
    return proxy.scheme + "://" + authority


def clean_slot_url(url, username=None, password=None):
    proxy = parse(url, username, password)
    value = urllib.parse.urlsplit(str(url).strip())
    host = "[%s]" % proxy.host if ":" in proxy.host else proxy.host
    authority = host + (":" + str(value.port) if value.port is not None else "")
    return proxy.scheme + "://" + authority, proxy.username, proxy.password


def redact_url(url):
    try:
        value = urllib.parse.urlsplit(url)
        if value.username is None:
            return url
        return urllib.parse.urlunsplit((value.scheme, "***@" + value.netloc.rsplit("@", 1)[-1],
                                       value.path, value.query, value.fragment))
    except ValueError:
        return "(invalid proxy)"


def socks_connect(proxy, host, port, timeout=30):
    """Return a CONNECT socket; auth errors close it and never fall back direct."""
    if timeout is None or timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout = socket.getdefaulttimeout() or 30
    deadline = time.monotonic() + timeout
    sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("SOCKS handshake timed out")
        sock.settimeout(seconds)
    def send(data):
        remaining()
        sock.sendall(data)
    def read(count):
        data = b""
        while len(data) < count:
            remaining()
            part = sock.recv(count - len(data))
            if not part:
                raise OSError("SOCKS proxy closed the handshake")
            data += part
        return data
    try:
        method = 2 if proxy.username else 0
        send(bytes([5, 1, method]))
        if read(2) != bytes([5, method]):
            raise OSError("SOCKS authentication method rejected")
        if method == 2:
            user, secret = proxy.username.encode(), proxy.password.encode()
            send(bytes([1, len(user)]) + user + bytes([len(secret)]) + secret)
            if read(2) != b"\x01\x00":
                raise OSError("SOCKS username/password authentication failed")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if proxy.scheme == "socks5":
                host = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][4][0]
                address = ipaddress.ip_address(host)
            else:
                address = None
        if address is not None:
            target = bytes([1 if address.version == 4 else 4]) + address.packed
        else:
            name = host.encode("idna")
            if not 1 <= len(name) <= 255:
                raise ValueError("SOCKS destination name is too long")
            target = bytes([3, len(name)]) + name
        send(b"\x05\x01\x00" + target + int(port).to_bytes(2, "big"))
        version, status, reserved, kind = read(4)
        if version != 5 or reserved != 0 or status:
            raise OSError("SOCKS CONNECT rejected (code %d)" % status)
        if kind == 1:
            read(4)
        elif kind == 4:
            read(16)
        elif kind == 3:
            read(read(1)[0])
        else:
            raise OSError("invalid SOCKS reply address type")
        read(2)
        sock.settimeout(timeout)
        return sock
    except Exception:
        sock.close()
        raise


def socks_connection(host, port, proxy, secure=False, timeout=30, context=None, target_host=None):
    kind = http.client.HTTPSConnection if secure else http.client.HTTPConnection
    kwargs = {"timeout": timeout}
    if secure and context is not None:
        kwargs["context"] = context
    conn = kind(host, port, **kwargs)
    conn._create_connection = lambda target, wait, *args, **kwargs: socks_connect(
        proxy, target_host or target[0], target[1], wait)
    return conn


def tunnel_connection(host, port, proxy_url, secure=False, timeout=30):
    proxy = parse(proxy_url)
    if proxy.scheme.startswith("socks"):
        return socks_connection(host, port, proxy, secure=secure, timeout=timeout)
    if proxy.scheme != "http":
        raise ValueError("this tunnel requires an HTTP or SOCKS5 proxy")
    kind = http.client.HTTPSConnection if secure else http.client.HTTPConnection
    conn = kind(host, port, timeout=timeout)
    conn._create_connection = lambda _target, wait, *args, **kwargs: socket.create_connection(
        (proxy.host, proxy.port), timeout=wait)
    conn.set_tunnel(host, port, headers=proxy.auth_headers())
    return conn


class _SocksHandler(urllib.request.AbstractHTTPHandler):
    handler_order = 400

    def __init__(self, proxy):
        super().__init__()
        self.proxy = proxy

    def _open(self, request, secure):
        def connection(host, **kwargs):
            value = urllib.parse.urlsplit(("https://" if secure else "http://") + host)
            return socks_connection(value.hostname, value.port or (443 if secure else 80),
                                    self.proxy, secure=secure, **kwargs)
        return self.do_open(connection, request)

    def http_open(self, request):
        return self._open(request, False)

    def https_open(self, request):
        return self._open(request, True)


def build_opener(url):
    proxy = parse(url)
    if proxy.scheme.startswith("socks"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _SocksHandler(proxy))
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}))
