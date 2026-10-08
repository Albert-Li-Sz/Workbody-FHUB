"""Bounded daemon workers with coalesced keys and explicit draining."""
import collections
import logging
import threading
import time


class WorkQueue:
    def __init__(self, name, workers=1, max_pending=8192, on_error=None):
        self.name, self.workers, self.max_pending = name, workers, max_pending
        self.on_error = on_error or (lambda exc: logging.getLogger("workbody.background").warning("background work failed: %s", exc))
        self.condition = threading.Condition()
        self.pending = collections.OrderedDict()
        self.active = set()
        self.started = False
        self.closed = False

    def submit(self, key, function):
        with self.condition:
            if self.closed or key not in self.pending and len(self.pending) >= self.max_pending:
                return False
            self.pending[key] = function
            if not self.started:
                self.started = True
                for index in range(self.workers):
                    threading.Thread(target=self._run, name=self.name + "-" + str(index), daemon=True).start()
            self.condition.notify_all()
            return True

    def _run(self):
        while True:
            with self.condition:
                while not any(key not in self.active for key in self.pending):
                    if self.closed and not self.pending:
                        return
                    self.condition.wait()
                key = next(key for key in self.pending if key not in self.active)
                function = self.pending.pop(key)
                self.active.add(key)
            try:
                function()
            except Exception as exc:
                try:
                    self.on_error(exc)
                except Exception:
                    logging.getLogger("workbody.background").exception("background error callback failed")
            finally:
                with self.condition:
                    self.active.discard(key)
                    self.condition.notify_all()

    def drain(self, timeout=5):
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.pending or self.active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True

    def close(self, timeout=5):
        result = self.drain(timeout)
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        return result


AFFINITY_WRITES = WorkQueue("affinity-store")
