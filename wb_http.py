"""Bounded HTTP/1.1 connection reuse, including authenticated HTTP/SOCKS proxies.

Connections are leased to exactly one response. A fully consumed response may
return its connection; cancellation, framing errors and unread bodies discard
it. Credentials and proxy identities never share a route.
"""
import atexit
import collections
import hashlib
import http.client
import io
import os
import select
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import wb_forward_proxy
import wb_metrics


class _TunnelIO(io.RawIOBase):
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        self.transport.file_refs += 1

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.transport.recv(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def fileno(self):
        return self.transport.fileno()

    def close(self):
        if not self.closed:
            super().close()
            self.transport.file_refs -= 1
            if self.transport.closed and not self.transport.file_refs:
                self.transport.outer.close()


class _TLSInsideTLS:
    """TLS to the origin inside an already verified HTTPS proxy tunnel."""
    def __init__(self, outer, context, hostname):
        self.outer = outer
        self.file_refs, self.closed = 0, False
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.inner = context.wrap_bio(self.incoming, self.outgoing,
                                      server_side=False, server_hostname=hostname)
        while True:
            try:
                self.inner.do_handshake()
                self._flush()
                break
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                self._flush()

    def _flush(self):
        while self.outgoing.pending:
            self.outer.sendall(self.outgoing.read())

    def _receive(self):
        self._flush()
        data = self.outer.recv(65536)
        if not data:
            self.incoming.write_eof()
        else:
            self.incoming.write(data)

    def recv(self, size):
        while True:
            try:
                data = self.inner.read(size)
                self._flush()
                return data
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                self._flush()
            except ssl.SSLZeroReturnError:
                return b""

    def sendall(self, data):
        view = memoryview(data)
        while view:
            try:
                sent = self.inner.write(view)
                view = view[sent:]
                self._flush()
            except ssl.SSLWantReadError:
                self._receive()
            except ssl.SSLWantWriteError:
                self._flush()

    def makefile(self, mode="rb", buffering=None):
        if mode != "rb":
            raise ValueError("HTTPS tunnel supports binary response reads")
        return io.BufferedReader(_TunnelIO(self), buffering or io.DEFAULT_BUFFER_SIZE)

    def settimeout(self, value):
        self.outer.settimeout(value)

    def gettimeout(self):
        return self.outer.gettimeout()

    def pending(self):
        return self.inner.pending()

    def fileno(self):
        return self.outer.fileno()

    def shutdown(self, how):
        self.outer.shutdown(how)

    def close(self):
        self.closed = True
        if not self.file_refs:
            self.outer.close()


class _HTTPSProxyConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, proxy, timeout):
        super().__init__(host, port, timeout=timeout)
        self.proxy = proxy
        self.set_tunnel(host, port, headers=proxy.auth_headers())

    def connect(self):
        raw = socket.create_connection((self.proxy.host, self.proxy.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.proxy.host)
            self._tunnel()
            self.sock = _TLSInsideTLS(self.sock, self._context, self.host)
        except Exception:
            raw.close()
            if self.sock is not None:
                self.sock.close()
            self.sock = None
            raise


class ConnectionPool:
    def __init__(self, max_connections=128, max_per_route=8, idle_seconds=60):
        self.max_connections = max(1, int(max_connections))
        self.max_per_route = max(1, int(max_per_route))
        self.idle_seconds = max(1, float(idle_seconds))
        self.condition = threading.Condition()
        self.idle = collections.defaultdict(list)
        self.counts = collections.Counter()
        self.created = self.reused = self.discarded = 0
        self.closed = False

    def _discard(self, key, connection):
        connection.close()
        self.counts[key] -= 1
        if not self.counts[key]:
            del self.counts[key]
        self.discarded += 1

    @staticmethod
    def _healthy(connection):
        sock = connection.sock
        if sock is None or sock.fileno() < 0:
            return False
        try:
            # An idle HTTP connection should have no readable bytes. This also
            # catches the server's FIN without consuming an SSL response.
            return not (getattr(sock, "pending", lambda: 0)()
                        or select.select([sock], [], [], 0)[0])
        except (OSError, ValueError):
            return False

    def acquire(self, key, factory, timeout):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if self.closed:
                    raise OSError("HTTP pool is closed")
                now = time.monotonic()
                for route in list(self.idle):
                    alive = []
                    for returned, connection in self.idle[route]:
                        if now - returned >= self.idle_seconds or not self._healthy(connection):
                            self._discard(route, connection)
                        else:
                            alive.append((returned, connection))
                    if alive:
                        self.idle[route] = alive
                    else:
                        self.idle.pop(route, None)
                if self.idle.get(key):
                    _, connection = self.idle[key].pop()
                    if not self.idle[key]:
                        del self.idle[key]
                    connection.timeout = max(0.001, deadline - now)
                    connection.sock.settimeout(connection.timeout)
                    self.reused += 1
                    return connection
                if sum(self.counts.values()) >= self.max_connections and self.idle:
                    route = min(self.idle, key=lambda r: self.idle[r][0][0])
                    _, connection = self.idle[route].pop(0)
                    self._discard(route, connection)
                    if not self.idle[route]:
                        del self.idle[route]
                if (self.counts[key] < self.max_per_route
                        and sum(self.counts.values()) < self.max_connections):
                    connection = factory(max(0.001, deadline - now))
                    self.counts[key] += 1
                    self.created += 1
                    return connection
                remaining = deadline - now
                if remaining <= 0:
                    raise TimeoutError("HTTP connection pool acquisition timed out")
                self.condition.wait(remaining)

    def release(self, key, connection, reusable):
        with self.condition:
            if reusable and not self.closed and connection.sock is not None:
                self.idle[key].append((time.monotonic(), connection))
            else:
                self._discard(key, connection)
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            idle = sum(len(value) for value in self.idle.values())
            return {"created": self.created, "reused": self.reused,
                    "discarded": self.discarded, "idle": idle,
                    "active": sum(self.counts.values()) - idle,
                    "max_connections": self.max_connections,
                    "max_per_route": self.max_per_route}

    def close(self):
        with self.condition:
            self.closed = True
            for key, entries in list(self.idle.items()):
                for _, connection in entries:
                    self._discard(key, connection)
            self.idle.clear()
            self.condition.notify_all()


POOL = ConnectionPool(os.environ.get("WB_HTTP_POOL_MAX", 128),
                      os.environ.get("WB_HTTP_POOL_PER_ROUTE", 8),
                      os.environ.get("WB_HTTP_POOL_IDLE", 60))
atexit.register(POOL.close)


class PooledResponse:
    def __init__(self, response, connection, key, url, response_socket=None):
        self.response, self.connection, self.key = response, connection, key
        self.url = url
        # http.client detaches a Connection: close socket from the connection
        # while its response file is still reading. Keep it interruptible too.
        self.response_socket = response_socket or connection.sock
        self.status = self.code = response.status
        self.reason, self.headers = response.reason, response.headers
        self.lock = threading.Lock()

    @property
    def fp(self):
        return self.response.fp

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def info(self):
        return self.headers

    def set_read_timeout(self, seconds):
        with self.lock:
            if self.connection is not None and self.response_socket is not None:
                self.response_socket.settimeout(seconds)

    def _finish(self, reusable):
        with self.lock:
            connection, self.connection = self.connection, None
            if connection is not None:
                POOL.release(self.key, connection,
                             reusable and not self.response.will_close)

    def read(self, amount=None):
        try:
            data = self.response.read(amount)
            if self.response.isclosed():
                self._finish(True)
            return data
        except Exception:
            self._finish(False)
            raise

    def readline(self, limit=-1):
        try:
            data = self.response.readline(limit)
            if not data or self.response.isclosed():
                self._finish(True)
            return data
        except Exception:
            self._finish(False)
            raise

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def abort(self):
        # Wake a reader thread before closing its buffered response file.
        with self.lock:
            sock = self.response_socket if self.connection is not None else None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.close()

    def close(self):
        self._finish(self.response.isclosed())
        self.response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _proxy_for(url, explicit):
    if explicit:
        return wb_forward_proxy.parse(explicit)
    target = urllib.parse.urlsplit(url)
    if urllib.request.proxy_bypass(target.netloc):
        return None
    value = urllib.request.getproxies().get(target.scheme)
    return wb_forward_proxy.parse(value) if value else None


def urlopen(request, timeout=30, proxy="", _redirects=0):
    if isinstance(request, str):
        request = urllib.request.Request(request)
    target = urllib.parse.urlsplit(request.full_url)
    if target.scheme not in ("http", "https") or not target.hostname:
        raise urllib.error.URLError("HTTP pool requires an http(s) URL")
    timeout = max(0.001, float(timeout))
    port = target.port or (443 if target.scheme == "https" else 80)
    headers = dict(request.header_items())
    lower = {name.lower(): value for name, value in headers.items()}
    identity = lower.get("x-user-id") or lower.get("authorization") or "anonymous"
    scope = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    outbound_proxy = _proxy_for(request.full_url, proxy)
    key = (target.scheme, target.hostname, port, scope, outbound_proxy)
    path = urllib.parse.urlunsplit(("", "", target.path or "/", target.query, ""))
    headers = {k: v for k, v in headers.items() if k.lower() != "proxy-authorization"}

    def factory(wait):
        if outbound_proxy is None:
            cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            return cls(target.hostname, port, timeout=wait)
        if outbound_proxy.scheme.startswith("socks"):
            return wb_forward_proxy.socks_connection(target.hostname, port, outbound_proxy,
                                                     secure=target.scheme == "https", timeout=wait)
        if target.scheme == "https":
            if outbound_proxy.scheme == "https":
                return _HTTPSProxyConnection(target.hostname, port, outbound_proxy, wait)
            connection = http.client.HTTPSConnection(target.hostname, port, timeout=wait)
            connection._create_connection = lambda _target, seconds, *a, **kw: socket.create_connection(
                (outbound_proxy.host, outbound_proxy.port), seconds)
            connection.set_tunnel(target.hostname, port, headers=outbound_proxy.auth_headers())
            return connection
        cls = http.client.HTTPSConnection if outbound_proxy.scheme == "https" else http.client.HTTPConnection
        return cls(outbound_proxy.host, outbound_proxy.port, timeout=wait)

    if outbound_proxy and not outbound_proxy.scheme.startswith("socks") and target.scheme == "http":
        path = request.full_url
        headers.update(outbound_proxy.auth_headers())
        headers.setdefault("Host", target.netloc)
    connection = None
    try:
        with wb_metrics.stage("connection_pool_wait_ms"):
            connection = POOL.acquire(key, factory, timeout)
        if connection.sock is None:
            with wb_metrics.stage("connect_ms"):
                connection.connect()
        with wb_metrics.stage("upstream_send_ms"):
            connection.request(request.get_method(), path, body=request.data, headers=headers)
        response_socket = connection.sock
        with wb_metrics.stage("upstream_headers_ms"):
            response = PooledResponse(connection.getresponse(), connection, key, request.full_url, response_socket)
    except Exception as exc:
        if connection is not None:
            POOL.release(key, connection, False)
        raise urllib.error.URLError(exc) from exc
    if response.status in (301, 302, 303, 307, 308) and response.headers.get("Location"):
        location = urllib.parse.urljoin(request.full_url, response.headers["Location"])
        destination = urllib.parse.urlsplit(location)
        method = request.get_method()
        permitted = (method in ("GET", "HEAD") or response.status in (301, 302, 303))
        if not permitted or _redirects >= 5 or destination.scheme not in ("http", "https"):
            response.close()
            raise urllib.error.HTTPError(request.full_url, response.status, "redirect rejected", response.headers, None)
        response.close()
        body = request.data
        if method != "HEAD" and response.status in (301, 302, 303):
            method, body = "GET", None
            headers = {k: v for k, v in headers.items() if k.lower() not in ("content-length", "content-type")}
        if (target.scheme, target.hostname, port) != (destination.scheme, destination.hostname,
                                                     destination.port or (443 if destination.scheme == "https" else 80)):
            headers = {k: v for k, v in headers.items()
                       if k.lower() not in ("authorization", "cookie", "host", "proxy-authorization")
                       and not k.lower().startswith("x-")}
        return urlopen(urllib.request.Request(location, data=body, headers=headers, method=method),
                       timeout=timeout, proxy=proxy, _redirects=_redirects + 1)
    if not 200 <= response.status < 300:
        try:
            body = response.read(1024 * 1024)
        finally:
            response.close()
        raise urllib.error.HTTPError(request.full_url, response.status, response.reason,
                                     response.headers, io.BytesIO(body))
    return response
