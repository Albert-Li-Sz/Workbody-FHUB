"""Bound accepted HTTP connections before allocating handler threads."""
import os
import threading
from http.server import ThreadingHTTPServer


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, *args, max_connections=None, **kwargs):
        value = max_connections if max_connections is not None else os.environ.get("WB_HTTP_MAX_CONNECTIONS", "128")
        self.max_connections = max(8, min(4096, int(value)))
        self.connection_slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            body = b'{"error":{"message":"gateway connection limit reached","type":"server_error"}}'
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nRetry-After: 1\r\n"
                                b"Content-Type: application/json\r\nContent-Length: " + str(len(body)).encode("ascii")
                                + b"\r\n\r\n" + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()
