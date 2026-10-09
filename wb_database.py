"""Local SQLite persistence with indexed usage, private documents and affinity.

WAL is for a single host's gateway. Legacy JSON/JSONL files remain portable
exports; startup imports them without duplicating records after a restart.
"""
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import uuid

SCHEMA_VERSION = 3
DATABASE = None


class Database:
    def __init__(self, path, accounts_dir, usage_dir):
        self.path = os.path.abspath(path)
        self.roots = {"accounts": os.path.abspath(accounts_dir), "usage": os.path.abspath(usage_dir)}
        self.local = threading.local()
        self.write_lock = threading.RLock()
        self.revision = 0
        self.history_epoch = 0
        self.retention_days = max(0, int(os.environ.get("WB_SQLITE_RETENTION_DAYS", 0)))
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if os.name != "nt":
            os.chmod(directory, 0o700)
        connection = self.connection()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("SQLite database was created by a newer Workbody-FHUB version")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL,
                export_stamp TEXT
            );
            CREATE TABLE IF NOT EXISTS usage_records (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                at REAL NOT NULL, account TEXT, realm TEXT,
                model TEXT, api_key TEXT, outcome TEXT, billing_mode TEXT,
                total_tokens INTEGER NOT NULL DEFAULT 0, credit REAL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS usage_at ON usage_records(at);
            CREATE INDEX IF NOT EXISTS usage_account_at ON usage_records(account, at);
            CREATE INDEX IF NOT EXISTS usage_realm_at ON usage_records(realm, at);
            CREATE INDEX IF NOT EXISTS usage_key_at ON usage_records(api_key, at);
            CREATE INDEX IF NOT EXISTS usage_model_at ON usage_records(model, at);
            CREATE INDEX IF NOT EXISTS usage_at_sequence ON usage_records(at, sequence);
            CREATE INDEX IF NOT EXISTS usage_realm_at_sequence ON usage_records(realm, at, sequence);
            CREATE INDEX IF NOT EXISTS usage_key_realm_at_sequence ON usage_records(api_key, realm, at, sequence);
            CREATE TABLE IF NOT EXISTS usage_exports (sequence INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS affinity (
                key TEXT PRIMARY KEY, account TEXT NOT NULL, expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS affinity_expiry ON affinity(expires_at);
            CREATE TABLE IF NOT EXISTS web_replay (
                reference TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS web_replay_expiry ON web_replay(expires_at);
        """)
        connection.execute("BEGIN IMMEDIATE")
        try:
            if "upstream" not in {row[1] for row in connection.execute("PRAGMA table_info(usage_records)")}:
                connection.execute("ALTER TABLE usage_records ADD COLUMN upstream TEXT NOT NULL DEFAULT 'workbuddy'")
            connection.execute("CREATE INDEX IF NOT EXISTS usage_upstream_at ON usage_records(upstream,at)")
            self._configure_rollups(connection, version)
            connection.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        self._restrict()

    def _configure_rollups(self, connection, previous_version):
        fields = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")
        if previous_version < 3:
            for operation in ("insert", "delete", "update"):
                connection.execute("DROP TRIGGER IF EXISTS usage_hourly_" + operation)
            connection.execute("DROP TABLE IF EXISTS usage_hourly")
        connection.execute("""CREATE TABLE IF NOT EXISTS usage_hourly (
            dimensions TEXT PRIMARY KEY, hour INTEGER NOT NULL, realm TEXT, account TEXT, model TEXT, api_key TEXT,
            upstream TEXT NOT NULL,
            requests INTEGER NOT NULL, client_aborted INTEGER NOT NULL, errors INTEGER NOT NULL,
            prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, reasoning_tokens INTEGER NOT NULL,
            cached_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL)""")
        connection.execute("CREATE INDEX IF NOT EXISTS hourly_time ON usage_hourly(hour)")
        connection.execute("CREATE INDEX IF NOT EXISTS hourly_key_realm_time ON usage_hourly(api_key,realm,hour)")
        connection.execute("CREATE INDEX IF NOT EXISTS hourly_account_time ON usage_hourly(account,hour)")
        connection.execute("CREATE INDEX IF NOT EXISTS hourly_upstream_time ON usage_hourly(upstream,hour)")
        def expressions(prefix=""):
            outcome = "COALESCE(%soutcome, CASE WHEN json_extract(%spayload,'$.error') THEN 'failed' ELSE 'completed' END)" % (prefix, prefix)
            hour = "CAST(%sat/3600 AS INTEGER)*3600" % prefix
            dimensions = "json_array(%srealm,%saccount,%smodel,%sapi_key,%supstream,%s)" % (prefix, prefix, prefix, prefix, prefix, hour)
            stats = ["CASE WHEN " + outcome + "='completed' THEN 1 ELSE 0 END",
                     "CASE WHEN " + outcome + "='client_aborted' THEN 1 ELSE 0 END",
                     "CASE WHEN " + outcome + " NOT IN ('completed','client_aborted') THEN 1 ELSE 0 END"]
            stats.extend("CASE WHEN COALESCE(json_extract(%spayload,'$.usage_missing'),0)=0 THEN COALESCE(json_extract(%spayload,'$.%s'),0) ELSE 0 END" % (prefix, prefix, field) for field in fields)
            return dimensions, hour, stats
        dims, hour, stats = expressions()
        if previous_version < 3:
            connection.execute("INSERT OR REPLACE INTO usage_hourly SELECT " + dims + "," + hour
                               + ",realm,account,model,api_key,upstream," + ",".join("SUM(" + stat + ")" for stat in stats)
                               + " FROM usage_records GROUP BY " + dims)
        names = ("requests", "client_aborted", "errors") + fields
        for operation, prefix, sign in (("INSERT", "NEW.", 1), ("DELETE", "OLD.", -1)):
            dims, hour, stats = expressions(prefix)
            values = [dims, hour] + [prefix + field for field in ("realm", "account", "model", "api_key", "upstream")]
            values.extend("(%s)*%d" % (stat, sign) for stat in stats)
            connection.execute("""CREATE TRIGGER IF NOT EXISTS usage_hourly_%s AFTER %s ON usage_records BEGIN
                INSERT INTO usage_hourly VALUES(%s) ON CONFLICT(dimensions) DO UPDATE SET %s;
                DELETE FROM usage_hourly WHERE requests+client_aborted+errors=0;
                END""" % (operation.lower(), operation, ",".join(values),
                          ",".join(field + "=" + field + "+excluded." + field for field in names)))
        updates = []
        for prefix, sign in (("OLD.", -1), ("NEW.", 1)):
            dims, hour, stats = expressions(prefix)
            values = [dims, hour] + [prefix + field for field in ("realm", "account", "model", "api_key", "upstream")]
            values.extend("(%s)*%d" % (stat, sign) for stat in stats)
            updates.append("INSERT INTO usage_hourly VALUES(" + ",".join(values)
                           + ") ON CONFLICT(dimensions) DO UPDATE SET "
                           + ",".join(field + "=" + field + "+excluded." + field for field in names) + ";")
        connection.execute("CREATE TRIGGER IF NOT EXISTS usage_hourly_update AFTER UPDATE ON usage_records BEGIN "
                           + " ".join(updates) + " DELETE FROM usage_hourly WHERE requests+client_aborted+errors=0; END")
        connection.execute("CREATE TRIGGER IF NOT EXISTS usage_export_delete AFTER DELETE ON usage_records BEGIN "
                           "DELETE FROM usage_exports WHERE sequence=OLD.sequence; END")

    def _restrict(self):
        if os.name != "nt":
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.chmod(self.path + suffix, 0o600)
                except FileNotFoundError:
                    pass

    def connection(self):
        connection = getattr(self.local, "connection", None)
        if connection is None:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            self.local.connection = connection
        return connection

    def close_thread(self):
        connection = getattr(self.local, "connection", None)
        if connection is not None:
            connection.close()
            del self.local.connection

    def put_web_result(self, reference, payload, expires_at, limit=4096):
        """Bounded opaque Messages search references; never account credentials."""
        with self.write_lock:
            connection = self.connection()
            connection.execute("DELETE FROM web_replay WHERE expires_at<=?", (time.time(),))
            connection.execute("INSERT OR REPLACE INTO web_replay VALUES(?,?,?)",
                               (reference, json.dumps(payload, ensure_ascii=False), expires_at))
            connection.execute("""DELETE FROM web_replay WHERE reference IN (
                SELECT reference FROM web_replay ORDER BY expires_at DESC LIMIT -1 OFFSET ?
            )""", (limit,))
            self._restrict()

    def get_web_result(self, reference):
        row = self.connection().execute(
            "SELECT payload FROM web_replay WHERE reference=? AND expires_at>?",
            (reference, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def document_key(self, path):
        path = os.path.abspath(path)
        for scope, root in self.roots.items():
            try:
                if os.path.commonpath((path, root)) == root:
                    relative = os.path.relpath(path, root).replace(os.sep, "/")
                    return scope if relative == "." else scope + "/" + relative
            except ValueError:
                pass
        return None

    @staticmethod
    def stamp(path):
        try:
            st = os.stat(path)
            return "%s:%s" % (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return None

    def save_document(self, path, data):
        key = self.document_key(path)
        if key is None:
            return
        with self.write_lock:
            self.connection().execute(
                "INSERT OR REPLACE INTO documents(key,payload,updated_at,export_stamp) VALUES(?,?,?,?)",
                (key, json.dumps(data, ensure_ascii=False), time.time(), self.stamp(path)))
            self.revision += 1
            self._restrict()

    def load_document(self, path):
        key = self.document_key(path)
        record = self.connection().execute(
            "SELECT payload,export_stamp FROM documents WHERE key=?", (key,)).fetchone() if key else None
        stamp = self.stamp(path)
        if record is not None and (stamp is None or record[1] == stamp):
            return json.loads(record[0])
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
        self.save_document(path, data)
        return data

    def has_document(self, path):
        key = self.document_key(path)
        return bool(key and self.connection().execute("SELECT 1 FROM documents WHERE key=?", (key,)).fetchone())

    def delete_document(self, path):
        key = self.document_key(path)
        if key:
            with self.write_lock:
                self.connection().execute("DELETE FROM documents WHERE key=?", (key,))
                self.revision += 1

    def document_paths(self, directory):
        key = self.document_key(os.path.join(directory, ""))
        if key is None:
            return []
        prefix = key.rstrip("/") + "/"
        records = self.connection().execute("SELECT key FROM documents WHERE substr(key,1,?)=?",
                                            (len(prefix), prefix))
        out = []
        for (name,) in records:
            relative = name[len(prefix):]
            if "/" not in relative and relative.endswith(".json"):
                out.append(os.path.join(directory, relative))
        return out

    @staticmethod
    def _usage_tuple(row):
        if any(row.get(field) is not None and not isinstance(row.get(field), str)
               for field in ("event_id", "account", "realm", "model", "key", "outcome", "billing_mode", "upstream")):
            return None
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        identifier = row.get("event_id") or hashlib.sha256(payload.encode("utf-8")).hexdigest()
        try:
            at = float(row.get("at") or 0)
            tokens = max(0, int(row.get("total_tokens") or 0))
            credit = float(row.get("credit") or 0) if row.get("has_credit") else None
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(at) or credit is not None and not math.isfinite(credit):
            return None
        return (identifier, at, row.get("account"), row.get("realm"), row.get("model"),
                row.get("key"), row.get("outcome"), row.get("billing_mode"), tokens, credit, payload,
                row.get("upstream") or "workbuddy")

    def append_usage(self, row):
        row.setdefault("event_id", uuid.uuid4().hex)
        values = self._usage_tuple(row)
        if values is None:
            raise ValueError("invalid usage record")
        with self.write_lock:
            connection = self.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO usage_records(id,at,account,realm,model,api_key,outcome,billing_mode,total_tokens,credit,payload,upstream) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", values)
                if inserted.rowcount:
                    connection.execute("INSERT OR IGNORE INTO usage_exports VALUES(?)", (inserted.lastrowid,))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            self.revision += 1
            self._restrict()

    def pending_exports(self, limit=256):
        return self.connection().execute("""SELECT u.sequence,u.payload FROM usage_exports e
            JOIN usage_records u ON u.sequence=e.sequence ORDER BY e.sequence LIMIT ?""", (limit,)).fetchall()

    def confirm_exports(self, sequences):
        with self.write_lock:
            connection = self.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executemany("DELETE FROM usage_exports WHERE sequence=?", [(n,) for n in sequences])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def import_usage_file(self, path):
        if not os.path.exists(path):
            return 0
        st = os.stat(path)
        key = "import:" + os.path.abspath(path)
        saved = self.connection().execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        prior = json.loads(saved[0]) if saved else {}
        cutoff_row = self.connection().execute("SELECT value FROM metadata WHERE key='usage_cutoff'").fetchone()
        cutoff = float(cutoff_row[0]) if cutoff_row else 0
        file_id = "%s:%s" % (st.st_dev, st.st_ino)
        offset = int(prior.get("offset") or 0) if prior.get("file") == file_id else 0
        if offset > st.st_size:
            offset = 0
        count, batch = 0, []
        with open(path, "rb") as source:
            source.seek(offset)
            while True:
                position = source.tell()
                line = source.readline()
                if not line or not line.endswith(b"\n"):
                    offset = position
                    break
                offset = source.tell()
                try:
                    row = json.loads(line)
                    values = self._usage_tuple(row) if isinstance(row, dict) else None
                except (ValueError, UnicodeError):
                    values = None
                if values and values[1] >= cutoff:
                    batch.append(values)
                if len(batch) >= 500:
                    count += self._import_batch(batch)
                    batch = []
            count += self._import_batch(batch)
        self.connection().execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                                  (key, json.dumps({"file": file_id, "offset": offset})))
        self._restrict()
        return count

    def _import_batch(self, batch):
        if not batch:
            return 0
        with self.write_lock:
            connection = self.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.executemany("INSERT OR IGNORE INTO usage_records(id,at,account,realm,model,api_key,outcome,billing_mode,total_tokens,credit,payload,upstream) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            return cursor.rowcount

    @staticmethod
    def usage_where(since=None, until=None, realm=None, account=None, model=None, api_key=None,
                    after_sequence=None, before_sequence=None, status=None, outcome=None, error=None,
                    path=None, request_id=None, upstream=None):
        clauses, params = [], []
        for name, operator, value in (("at", ">=", since), ("at", "<=", until),
                                     ("realm", "=", realm), ("account", "=", account),
                                     ("model", "=", model), ("api_key", "=", api_key),
                                     ("upstream", "=", upstream),
                                     ("sequence", ">", after_sequence), ("sequence", "<=", before_sequence)):
            if value is not None:
                clauses.append(name + operator + "?")
                params.append(value)
        for name, value in (("status", status), ("outcome", outcome), ("error", error),
                            ("path", path), ("request_id", request_id)):
            if value is not None:
                expression = "COALESCE(json_extract(payload,'$.%s'),0)" % name if name in ("status", "error") else "json_extract(payload,'$.%s')" % name
                clauses.append(expression + "=?")
                params.append(int(value) if isinstance(value, bool) else value)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    def usage_rows(self, since=None, until=None, realm=None, account=None, model=None, api_key=None, limit=None, raw=False,
                   descending=False, after_sequence=None, before_sequence=None, offset=0, **filters):
        where, params = self.usage_where(since, until, realm, account, model, api_key,
                                        after_sequence, before_sequence, **filters)
        direction = "DESC" if limit or descending else "ASC"
        query = "SELECT payload FROM usage_records" + where + " ORDER BY at " + direction + ",sequence " + direction
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend((max(1, int(limit)), max(0, int(offset))))
        cursor = self.connection().execute(query, params)
        try:
            for (payload,) in cursor:
                yield payload + "\n" if raw else json.loads(payload)
        finally:
            cursor.close()

    def usage_count(self, **filters):
        where, params = self.usage_where(**filters)
        return self.connection().execute("SELECT COUNT(*) FROM usage_records" + where, params).fetchone()[0]

    def _raw_usage_totals(self, group_by=(), **filters):
        allowed = {"account", "model", "realm", "api_key", "upstream"}
        if any(field not in allowed for field in group_by):
            raise ValueError("invalid usage grouping")
        where, params = self.usage_where(**filters)
        fields = ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens", "total_tokens")
        outcome = "COALESCE(outcome, CASE WHEN json_extract(payload,'$.error') THEN 'failed' ELSE 'completed' END)"
        sums = ["SUM(CASE WHEN " + outcome + "='completed' THEN 1 ELSE 0 END)",
                "SUM(CASE WHEN " + outcome + "='client_aborted' THEN 1 ELSE 0 END)",
                "SUM(CASE WHEN " + outcome + " NOT IN ('completed','client_aborted') THEN 1 ELSE 0 END)"]
        sums.extend("COALESCE(SUM(CASE WHEN COALESCE(json_extract(payload,'$.usage_missing'),0)=0 THEN COALESCE(json_extract(payload,'$.%s'),0) ELSE 0 END),0)" % field for field in fields)
        query = "SELECT " + ",".join(list(group_by) + sums) + " FROM usage_records" + where
        if group_by:
            query += " GROUP BY " + ",".join(group_by)
        names = list(group_by) + ["requests", "client_aborted", "errors"] + list(fields)
        return [dict(zip(names, values)) for values in self.connection().execute(query, params)]

    def usage_totals(self, group_by=(), **filters):
        """Hourly materialized sums plus exact raw rows at partial-hour edges."""
        names = ("requests", "client_aborted", "errors", "prompt_tokens", "completion_tokens",
                 "reasoning_tokens", "cached_tokens", "total_tokens")
        allowed = {"realm", "account", "model", "api_key", "upstream", "since", "until"}
        if any(field not in allowed and value is not None for field, value in filters.items()):
            return self._raw_usage_totals(group_by=group_by, **filters)
        if any(field not in ("account", "model", "realm", "api_key", "upstream") for field in group_by):
            raise ValueError("invalid usage grouping")
        lo, hi = filters.get("since"), filters.get("until")
        start = math.ceil(lo / 3600) * 3600 if lo is not None else None
        end = math.floor(hi / 3600) * 3600 if hi is not None else None
        if start is not None and end is not None and start >= end:
            rows = self._raw_usage_totals(group_by=group_by, **filters)
        else:
            base = {key: value for key, value in filters.items() if key not in ("since", "until")}
            where, params = self.usage_where(**base)
            clauses = []
            if start is not None:
                clauses.append("hour>=?")
                params.append(start)
            if end is not None:
                clauses.append("hour<?")
                params.append(end)
            if clauses:
                where += (" AND " if where else " WHERE ") + " AND ".join(clauses)
            query = "SELECT " + ",".join(list(group_by) + ["COALESCE(SUM(" + name + "),0)" for name in names]) + " FROM usage_hourly" + where
            if group_by:
                query += " GROUP BY " + ",".join(group_by)
            rows = [dict(zip(list(group_by) + list(names), values)) for values in self.connection().execute(query, params)]
            if lo is not None and lo < start:
                rows.extend(self._raw_usage_totals(group_by=group_by, **dict(base, since=lo, until=math.nextafter(float(start), float("-inf")))))
            if hi is not None:
                rows.extend(self._raw_usage_totals(group_by=group_by, **dict(base, since=end, until=hi)))
        merged = {}
        for row in rows:
            key = tuple(row.get(field) for field in group_by)
            item = merged.setdefault(key, {**dict(zip(group_by, key)), **{name: 0 for name in names}})
            for name in names:
                item[name] += row.get(name) or 0
        return list(merged.values())

    def request_metrics(self, **filters):
        where, params = self.usage_where(**filters)
        import wb_reqlog
        import wb_metrics
        fields = ("error", "status", "elapsed_ms", "ttft_ms") + wb_metrics.TIMING_FIELDS
        columns = ",".join("json_extract(payload,'$.%s')" % name for name in fields)
        values = self.connection().execute("SELECT " + columns + " FROM usage_records" + where, params)
        # Decode scalar metrics only; arbitrary request payloads stay in SQL.
        return wb_reqlog.compute_metrics([dict(zip(fields, row)) for row in values])

    def resolve_usage_realms(self, resolver):
        rows = self.connection().execute("SELECT sequence,payload FROM usage_records WHERE realm IS NULL").fetchall()
        if rows:
            self.history_epoch += 1
        for start in range(0, len(rows), 256):
            updates = []
            for sequence, payload in rows[start:start+256]:
                row = json.loads(payload)
                row["realm"] = resolver(row)
                updates.append((row["realm"], json.dumps(row, ensure_ascii=False), sequence))
            with self.write_lock:
                self.connection().executemany("UPDATE usage_records SET realm=?,payload=? WHERE sequence=?", updates)

    def affinity_get(self, key):
        row = self.connection().execute("SELECT account FROM affinity WHERE key=? AND expires_at>?",
                                        (key, time.time())).fetchone()
        return row[0] if row else None

    def affinity_set(self, key, account, ttl):
        with self.write_lock:
            connection = self.connection()
            connection.execute("DELETE FROM affinity WHERE expires_at<?", (time.time(),))
            connection.execute("INSERT OR REPLACE INTO affinity VALUES(?,?,?)", (key, account, time.time() + ttl))
            self._restrict()

    def affinity_delete(self, key):
        with self.write_lock:
            self.connection().execute("DELETE FROM affinity WHERE key=?", (key,))

    def prune_usage(self, now=None):
        """Optional SQL retention; old exports cannot resurrect pruned rows."""
        if not self.retention_days:
            return 0
        cutoff = (time.time() if now is None else now) - self.retention_days * 86400
        with self.write_lock:
            connection = self.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute("SELECT value FROM metadata WHERE key='usage_cutoff'").fetchone()
                cutoff = max(cutoff, float(previous[0]) if previous else 0)
                removed = connection.execute("DELETE FROM usage_records WHERE at<?", (cutoff,)).rowcount
                connection.execute("INSERT OR REPLACE INTO metadata VALUES('usage_cutoff',?)", (str(cutoff),))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            if removed:
                self.revision += 1
                self.history_epoch += 1
            return removed

    def snapshot(self):
        connection = self.connection()
        return {"engine": "sqlite", "schema_version": SCHEMA_VERSION, "journal_mode": "wal",
                "retention_days": self.retention_days,
                "path": self.path, "usage_records": connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0],
                "hourly_buckets": connection.execute("SELECT COUNT(*) FROM usage_hourly").fetchone()[0],
                "pending_exports": connection.execute("SELECT COUNT(*) FROM usage_exports").fetchone()[0],
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "affinity": connection.execute("SELECT COUNT(*) FROM affinity WHERE expires_at>?", (time.time(),)).fetchone()[0]}

    def backup(self, destination):
        """Online backup also includes committed WAL transactions."""
        target = sqlite3.connect(destination)
        try:
            self.connection().backup(target)
        finally:
            target.close()
        if os.name != "nt":
            os.chmod(destination, 0o600)


def configure(accounts_dir, usage_dir, log=None):
    global DATABASE
    path = os.environ.get("WB_SQLITE_PATH") or os.path.join(accounts_dir, "workbody.sqlite3")
    DATABASE = Database(path, accounts_dir, usage_dir)
    imported = 0
    for root in DATABASE.roots.values():
        os.makedirs(root, mode=0o700, exist_ok=True)
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if name.endswith(".json"):
                try:
                    DATABASE.load_document(path)
                except (ValueError, OSError) as exc:
                    if log:
                        log("SQLite document import skipped %s: %s" % (name, exc))
            elif root == os.path.abspath(usage_dir) and (name == "usage.jsonl" or
                    name.startswith("usage-archive-") and name.endswith(".jsonl")):
                imported += DATABASE.import_usage_file(path)
    if log:
        log("SQLite ready: %d legacy usage record(s) imported" % imported)
    return DATABASE


def for_usage(path):
    if DATABASE and os.path.abspath(os.path.dirname(path)) == DATABASE.roots["usage"]:
        return DATABASE
    return None


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Create a private online SQLite backup, including WAL transactions")
    parser.add_argument("--source", default="accounts/workbody.sqlite3")
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    if not os.path.isfile(args.source):
        parser.error("source database does not exist")
    destination = os.path.abspath(args.backup)
    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect(Path(args.source).resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    print("SQLite backup saved: " + destination)
