# -*- coding: utf-8 -*-
"""wb_reqlog.py — 請求歸檔的輪轉/查詢/指標（panel internal/reqlog 語義）。

SQLite 是配置后的事实来源；usage.jsonl 是可重放的兼容导出。

  - 輪轉：主檔超過 max_mb 時整段重命名，再新建主檔；不解析或重寫大文件。
    SQLite 統計不依賴導出進度；舊版 JSONL 讀者一起讀主檔和歸檔。
  - 保留：刪除超過 retention_days 的歸檔檔。
  - 查詢：since/until/model/account/status/outcome/error/path/request_id/
    limit 多維過濾。
  - 指標：完成成功率、HTTP 成功率、平均耗時、TTFB 平均與 p50/p95。

純標準庫，Python 3.9 兼容。
"""

import glob
import json
import os
import threading
import time
import wb_database
import wb_metrics

_last_check = {}
CHECK_INTERVAL_SECONDS = 60
ARCHIVE_PREFIX = "usage-archive-"

# Appends (wb_proxy._persist_usage) and the rotate read->replace chain share
# this lock, so a row written by another thread can never land on the file
# that rotation is about to replace (BUG-3 in the 2026-10-05 audit).
LOCK = threading.RLock()


def _file_stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def archive_files(usage_dir):
    return sorted(glob.glob(os.path.join(usage_dir, ARCHIVE_PREFIX + "*.jsonl")))


def log_files(usage_dir, main_name="usage.jsonl"):
    """Oldest first: archives, then the live main log."""
    files = archive_files(usage_dir)
    main = os.path.join(usage_dir, main_name)
    if os.path.exists(main):
        files.append(main)
    return files


def _iter_rows(path, max_bytes=None):
    """Stream complete rows; an explicit byte window is opt-in only."""
    try:
        with open(path, "rb") as fh:
            if max_bytes is not None and os.path.getsize(path) > max_bytes:
                fh.seek(max(0, os.path.getsize(path) - max_bytes))
                fh.readline()
            for line in fh:
                if not line.endswith(b"\n"):
                    continue
                try:
                    row = json.loads(line.decode("utf-8", "replace"))
                except (ValueError, UnicodeError):
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _files_stamp(usage_dir, main_name):
    """(path, mtime_ns, size) for every file that contributes rows."""
    stamp = []
    for path in log_files(usage_dir, main_name):
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp.append((path, st.st_mtime_ns, st.st_size))
    return tuple(stamp)


_rows_cache = {}


def read_rows(usage_dir, limit=None, main_name="usage.jsonl"):
    """All rows, oldest first; cached until a contributing file changes.

    /requests and /requests/metrics both parse the main log and every archive
    on the dashboard's 5s poll; the stamp cache makes that one parse per file
    change instead (audit #7).
    """
    database = wb_database.for_usage(os.path.join(usage_dir, main_name))
    if database:
        rows = list(database.usage_rows(limit=limit))
        return list(reversed(rows)) if limit else rows
    key = (os.path.abspath(str(usage_dir or ".")), main_name)
    stamp = _files_stamp(usage_dir, main_name)
    with LOCK:
        hit = _rows_cache.get(key)
        rows = hit[1] if (hit and hit[0] == stamp) else None
    if rows is None:
        rows = []
        for path in log_files(usage_dir, main_name):
            rows.extend(_iter_rows(path))
        rows.sort(key=lambda row: float(row.get("at") or 0))
        with LOCK:
            _rows_cache[key] = (stamp, rows)
    if limit:
        return list(rows[-int(limit):])
    return list(rows)


def filter_rows(rows, model=None, account=None, status=None, outcome=None,
                error=None, path=None, since=None, until=None, request_id=None):
    out = []
    for row in rows:
        at = float(row.get("at") or 0)
        if since is not None and at < float(since):
            continue
        if until is not None and at > float(until):
            continue
        if model and row.get("model") != model:
            continue
        if account and row.get("account") != account:
            continue
        if status is not None and int(row.get("status") or 0) != int(status):
            continue
        if outcome and row.get("outcome") != outcome:
            continue
        if error is not None and bool(row.get("error")) != bool(error):
            continue
        if path and row.get("path") != path:
            continue
        if request_id and row.get("request_id") != request_id:
            continue
        out.append(row)
    return out


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((q / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, idx))]


def compute_metrics(rows):
    """Completion/HTTP success rates plus elapsed/TTFB averages and percentiles."""
    total = len(rows)
    errors = sum(1 for row in rows if row.get("error"))
    http_ok = sum(1 for row in rows
                  if 200 <= int(row.get("status") or 0) < 300)
    elapsed = [float(row["elapsed_ms"]) for row in rows
               if isinstance(row.get("elapsed_ms"), (int, float))]
    ttfb = [float(row["ttft_ms"]) for row in rows
            if isinstance(row.get("ttft_ms"), (int, float))]
    timings = {}
    for field in wb_metrics.TIMING_FIELDS:
        values = [float(row[field]) for row in rows if isinstance(row.get(field), (int, float))
                  and not isinstance(row[field], bool) and 0 <= row[field] < float("inf")]
        timings[field] = {"avg": sum(values) / len(values) if values else None,
                          "p50": _percentile(values, 50), "p95": _percentile(values, 95), "samples": len(values)}
    return {
        "requests": total,
        "timings": timings,
        "errors": errors,
        "completion_rate": ((total - errors) / total) if total else None,
        "http_success_rate": (http_ok / total) if total else None,
        "avg_elapsed_ms": (sum(elapsed) / len(elapsed)) if elapsed else None,
        "p50_elapsed_ms": _percentile(elapsed, 50),
        "p95_elapsed_ms": _percentile(elapsed, 95),
        "avg_ttfb_ms": (sum(ttfb) / len(ttfb)) if ttfb else None,
        "p50_ttfb_ms": _percentile(ttfb, 50),
        "p95_ttfb_ms": _percentile(ttfb, 95),
    }


def prune_archives(usage_dir, retention_days, now=None, log=None):
    """Delete archive files older than the retention window."""
    now = time.time() if now is None else float(now)
    cutoff = now - max(1, int(retention_days)) * 86400
    removed = 0
    for path in archive_files(usage_dir):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    if removed and log:
        log("request archive: pruned %d expired file(s)" % removed)
    return removed


def compact_main(path, max_mb, retention_days, now=None, log=None):
    """Rotate an append-only segment without parsing or rewriting its rows."""
    now = time.time() if now is None else float(now)
    with LOCK:
        try:
            if os.path.getsize(path) < max(1, int(max_mb)) * 1024 * 1024:
                return False
            import uuid
            name = ARCHIVE_PREFIX + time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + uuid.uuid4().hex[:8] + ".jsonl"
            archive = os.path.join(os.path.dirname(path), name)
            os.replace(path, archive)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except OSError:
            return False
    if log:
        log("request archive: rotated segment into %s" % name)
    return True

def rotate_if_needed(path, max_mb, retention_days, now=None, log=None):
    """Throttled rotation check (at most once per CHECK_INTERVAL_SECONDS)."""
    now = time.time() if now is None else float(now)
    key = os.path.abspath(path)
    if now - _last_check.get(key, 0.0) < CHECK_INTERVAL_SECONDS:
        return False
    _last_check[key] = now
    usage_dir = os.path.dirname(path) or "."
    database = wb_database.for_usage(path)
    if database:
        removed = database.prune_usage(now)
        if removed and log:
            log("SQLite usage: pruned %d record(s) outside configured retention" % removed)
    prune_archives(usage_dir, retention_days, now=now, log=log)
    return compact_main(path, max_mb, retention_days, now=now, log=log)
