"""Durable SQLite usage with a bounded, asynchronous JSONL export outbox."""
import os
import threading
import wb_background
import wb_reqlog

EXPORTS = wb_background.WorkQueue("usage-export")
_STOP = threading.Event()


def start_retry_monitor(database, path, config, log=None):
    def monitor():
        try:
            while not _STOP.wait(30):
                if database.connection().execute("SELECT 1 FROM usage_exports LIMIT 1").fetchone():
                    options = config()
                    schedule_export(database, path, log=log, max_mb=options["archive_max_mb"], retention_days=options["retention_days"])
        finally:
            database.close_thread()
    threading.Thread(target=monitor, name="usage-export-monitor", daemon=True).start()


def stop_monitor():
    _STOP.set()


def schedule_export(database, path, log=None, max_mb=100, retention_days=7):
    def export():
        try:
            while True:
                rows = database.pending_exports(limit=256)
                if not rows:
                    break
                with wb_reqlog.LOCK:
                    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as target:
                        for _, payload in rows:
                            target.write(payload + "\n")
                    database.confirm_exports([sequence for sequence, _ in rows])
                wb_reqlog.rotate_if_needed(path, max_mb, retention_days, log=log)
        except Exception as exc:
            if log:
                log("usage export pending in SQLite: %s" % exc)
        finally:
            database.close_thread()
    # A rejected notification is harmless: the durable outbox remains in SQL.
    # The next usage event or startup schedules another drain.
    EXPORTS.submit(database.path, export)
