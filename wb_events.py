"""Bounded panel invalidations and numeric activity deltas; never credentials."""
import json
import threading
import time


class Subscription:
    def __init__(self, broker, realm):
        self.broker, self.realm = broker, realm
        self.condition = threading.Condition()
        self.pending = set()
        self.changes = {}
        self.revision = 0
        self.closed = False

    def put(self, topics, revision, changes=None):
        with self.condition:
            self.pending.update(topics)
            for kind, accounts in (changes or {}).items():
                target = self.changes.setdefault(kind, {})
                for uid, fields in accounts.items():
                    item = target.setdefault(uid, {})
                    for name, value in fields.items():
                        item[name] = item.get(name, 0) + value if kind == "usage" else value
                if len(target) > 512:
                    self.pending.add("accounts")
                    self.changes.pop(kind, None)
            self.revision = revision
            self.condition.notify()

    def next(self, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: bool(self.pending or self.changes) or self.closed, timeout)
            if self.closed or not (self.pending or self.changes):
                return None
            event = {"topics": sorted(self.pending), "revision": self.revision, "at": time.time()}
            if self.changes:
                event["changes"] = self.changes
                self.changes = {}
            self.pending.clear()
            return event

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.broker.unsubscribe(self)


class Broker:
    def __init__(self, limit=64):
        self.lock = threading.Lock()
        self.clients = set()
        self.revision = 0
        self.limit = limit
        self.ticker = None

    def subscribe(self, realm=None):
        with self.lock:
            if len(self.clients) >= self.limit:
                return None
            client = Subscription(self, realm)
            self.clients.add(client)
            client.put({"usage", "accounts", "tasks", "scheduler", "settings"}, self.revision)
            if self.ticker is None:
                self.ticker = threading.Thread(target=self._tick, name="dashboard-clock", daemon=True)
                self.ticker.start()
            return client

    def _tick(self):
        last_day = time.strftime("%Y-%m-%d")
        while True:
            # State such as cooldown expiry changes without a database write.
            threading.Event().wait(60)
            day = time.strftime("%Y-%m-%d")
            topics = ("usage", "accounts", "tasks", "scheduler") if day != last_day else ("accounts", "scheduler")
            last_day = day
            with self.lock:
                active = bool(self.clients)
            if active:
                self.publish(*topics)

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)

    def publish(self, *topics, realm=None, changes=None):
        with self.lock:
            self.revision += 1
            for client in self.clients:
                if realm and client.realm and client.realm != realm:
                    continue
                client.put(topics, self.revision, changes)


BROKER = Broker()


def frame(event):
    return ("id: %d\nevent: refresh\ndata: %s\n\n" %
            (event["revision"], json.dumps(event, ensure_ascii=False))).encode("utf-8")
