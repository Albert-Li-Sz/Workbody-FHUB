"""Serialize SSE frames and send heartbeats during any quiet generation stage."""
import os
import threading
import time
import wb_metrics

HEARTBEAT_SECONDS = max(1.0, float(os.environ.get("WB_SSE_HEARTBEAT_SECONDS", 15)))


class HeartbeatWriter:
    """One heartbeat thread; upstream reads remain on the handler thread.

    Complete frames and comments share a write lock, including during local
    tool execution. A failed heartbeat interrupts a blocked upstream read;
    the handler then records the confirmed partial usage as client_aborted.
    """
    def __init__(self, writer, owner, interval=HEARTBEAT_SECONDS):
        self.writer, self.owner, self.interval = writer, owner, interval
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.last_write = time.monotonic()
        self.failure = None
        self.thread = None

    @staticmethod
    def _cancel_error(error):
        if isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return error
        return ConnectionAbortedError("SSE client connection closed: %s" % error)

    def check(self):
        if self.failure is not None:
            raise self._cancel_error(self.failure)

    def write(self, frame):
        with self.lock:
            self.check()
            try:
                result = self.writer.write(frame)
                wb_metrics.observe_client_frame(frame)
                self.last_write = time.monotonic()
                return result
            except (OSError, ValueError) as exc:
                self.failure = exc
                raise self._cancel_error(exc) from exc

    def flush(self):
        with self.lock:
            self.check()
            try:
                self.writer.flush()
            except (OSError, ValueError) as exc:
                self.failure = exc
                raise self._cancel_error(exc) from exc

    def iterate(self, upstream):
        try:
            for line in upstream:
                self.check()
                yield line
            self.check()
        except Exception:
            # An abort triggered by a heartbeat is a client disconnect even
            # when shutting down the upstream socket reports IncompleteRead.
            self.check()
            raise

    def _heartbeat(self):
        while not self.stopped.is_set():
            with self.lock:
                remaining = max(0, self.interval - (time.monotonic() - self.last_write))
            if self.stopped.wait(remaining):
                return
            try:
                with self.lock:
                    if self.stopped.is_set() or time.monotonic() - self.last_write < self.interval:
                        continue
                    self.check()
                    self.writer.write(b": heartbeat\n\n")
                    self.writer.flush()
                    self.last_write = time.monotonic()
            except (OSError, ValueError) as exc:
                self.failure = exc
                self.stopped.set()
                try:
                    upstream = self.owner()
                    abort = getattr(upstream, "abort", None)
                    if abort:
                        abort()
                except Exception:
                    pass
                return

    def __enter__(self):
        self.thread = threading.Thread(target=self._heartbeat, name="sse-heartbeat", daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def __exit__(self, *args):
        self.close()
