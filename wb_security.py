"""Trusted proxy addresses and atomic, bounded panel login verification."""
import collections
import ipaddress
import os
import socket
import threading
import time


class TrustedProxies:
    def __init__(self, configured=None):
        self.entries = (configured if configured is not None else
                        os.environ.get("WB_TRUSTED_PROXIES", "127.0.0.1/32,::1/128")).split(",")
        self.lock = threading.Lock()
        self.addresses = set()
        self.updated_at = 0
        self.networks, self.hosts = [], []
        for entry in self.entries:
            entry = entry.strip()
            if not entry:
                continue
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                self.hosts.append(entry)

    def contains(self, address):
        try:
            peer = ipaddress.ip_address(address)
        except ValueError:
            return False
        if any(peer in network for network in self.networks):
            return True
        if self.hosts:
            now = time.monotonic()
            with self.lock:
                if now - self.updated_at >= (30 if self.addresses else 1):
                    addresses = set()
                    for host in self.hosts:
                        try:
                            addresses.update(item[4][0] for item in socket.getaddrinfo(host, None))
                        except OSError:
                            pass
                    self.addresses, self.updated_at = addresses, now
                return address in self.addresses
        return False

    def client_ip(self, peer, headers):
        if self.contains(peer):
            value = str(headers.get("X-Real-IP") or "").strip()
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                pass
        return peer


class LoginLimiter:
    """Reserve attempts before PBKDF2; track failed and in-progress attempts."""
    def __init__(self, limit=5, window=60, max_clients=4096, concurrent=4):
        self.limit, self.window, self.max_clients = limit, window, max_clients
        self.lock = threading.Lock()
        self.attempts = collections.OrderedDict()
        self.verifiers = threading.BoundedSemaphore(concurrent)

    def begin(self, ip):
        now = time.monotonic()
        with self.lock:
            entries = [entry for entry in self.attempts.get(ip, []) if now - entry[0] < self.window]
            if len(entries) >= self.limit:
                return None, max(1, int(self.window - (now - entries[0][0])) + 1)
            if not self.verifiers.acquire(blocking=False):
                return None, 1
            ticket = (now, object())
            entries.append(ticket)
            self.attempts[ip] = entries
            self.attempts.move_to_end(ip)
            while len(self.attempts) > self.max_clients:
                self.attempts.popitem(last=False)
            return ticket, 0

    def finish(self, ip, ticket, success=False):
        try:
            if success:
                with self.lock:
                    # A successful login must not erase other in-flight attempts.
                    entries = self.attempts.get(ip, [])
                    self.attempts[ip] = [entry for entry in entries if entry is not ticket]
        finally:
            self.verifiers.release()


TRUSTED_PROXIES = TrustedProxies()
LOGIN_LIMITER = LoginLimiter()
