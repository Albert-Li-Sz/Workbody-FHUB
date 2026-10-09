"""Key-scoped Responses history. Each response owns a complete replay snapshot.

Content is deduplicated within an API Key, so deleting/expiring an ancestor
does not break its descendants or reveal equality across unrelated callers.
The original client instructions are never folded into the saved history.
"""
import copy
import hashlib
import json
import sqlite3
import time
import uuid

import wb_settings

DEFAULTS = {"enabled": True, "retention_days": 7, "max_mb": 1024}


class ResponseError(ValueError):
    def __init__(self, message, status=400, code="invalid_request_error"):
        super().__init__(message)
        self.status, self.code = status, code


def config(directory):
    raw = wb_settings.load(directory).get("responses", {})
    result = dict(DEFAULTS)
    if isinstance(raw, dict):
        result.update({key: raw[key] for key in DEFAULTS if key in raw})
    return validate_config(result)


def validate_config(raw):
    if not isinstance(raw, dict) or any(key not in DEFAULTS for key in raw):
        raise ValueError("invalid Responses storage settings")
    result = dict(DEFAULTS, **raw)
    if type(result["enabled"]) is not bool:
        raise ValueError("responses.enabled must be a boolean")
    for field, minimum, maximum in (("retention_days", 1, 365), ("max_mb", 1, 1048576)):
        if type(result[field]) is not int or not minimum <= result[field] <= maximum:
            raise ValueError("responses.%s must be an integer from %d to %d" % (field, minimum, maximum))
    return result


def input_items(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [{"type": "message", "role": "user", "content": value}]
    return [({"type": "message", "role": "user", "content": item}
             if isinstance(item, str) else copy.deepcopy(item)) for item in value]


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def account_bound(value):
    if isinstance(value, list):
        return any(account_bound(item) for item in value)
    if isinstance(value, dict):
        if value.get("encrypted_content") or value.get("signature"):
            return True
        return any(account_bound(item) for item in value.values())
    return False


class ResponseStore:
    def __init__(self, database, directory):
        self.db, self.directory = database, directory
        self.last_cleanup = 0
        with self.db.write_lock:
            self.db.connection().executescript("""
                CREATE TABLE IF NOT EXISTS response_items (
                    digest TEXT PRIMARY KEY, payload TEXT NOT NULL, size INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS responses (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, conversation TEXT NOT NULL,
                    upstream TEXT NOT NULL, realm TEXT NOT NULL, model TEXT NOT NULL,
                    account TEXT, bound INTEGER NOT NULL, created_at REAL NOT NULL,
                    expires_at REAL NOT NULL, refs TEXT NOT NULL, payload TEXT NOT NULL,
                    size INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS responses_owner_time ON responses(owner,created_at);
                CREATE INDEX IF NOT EXISTS responses_expiry ON responses(expires_at);
                CREATE INDEX IF NOT EXISTS responses_conversation ON responses(conversation);
            """)
        self.cleanup(force=True)

    def _collect(self, connection):
        connection.execute("""DELETE FROM response_items WHERE digest NOT IN (
            SELECT j.value FROM responses r, json_each(r.refs) j)""")

    def cleanup(self, force=False, now=None):
        now = time.time() if now is None else now
        if not force and now - self.last_cleanup < 300:
            return
        with self.db.write_lock:
            connection = self.db.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM responses WHERE expires_at<=?", (now,))
                self._collect(connection)
                connection.execute("COMMIT")
                self.last_cleanup = now
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get(self, identifier, owner, allowed, include_history=False):
        if not owner:
            raise ResponseError("response not found", 404, "response_not_found")
        row = self.db.connection().execute("""SELECT payload,refs,conversation,upstream,realm,model,account,bound
            FROM responses WHERE id=? AND owner=? AND expires_at>?""", (identifier, owner, time.time())).fetchone()
        if not row or row[3] not in allowed:
            raise ResponseError("response not found", 404, "response_not_found")
        result = {"response": json.loads(row[0]), "conversation": row[2], "upstream": row[3],
                  "realm": row[4], "model": row[5], "account": row[6], "bound": bool(row[7])}
        if include_history:
            # One statement takes a consistent snapshot even if cleanup runs
            # concurrently. No caller can see another owner's content hashes.
            values = self.db.connection().execute("""SELECT i.payload FROM responses r,
                json_each(r.refs) j JOIN response_items i ON i.digest=j.value
                WHERE r.id=? AND r.owner=? AND r.expires_at>? ORDER BY CAST(j.key AS INTEGER)""",
                (identifier, owner, time.time())).fetchall()
            refs = json.loads(row[1])
            if len(values) != len(refs):
                raise ResponseError("response not found", 404, "response_not_found")
            result["history"] = [json.loads(value[0]) for value in values]
        return result

    def prepare(self, payload, owner, allowed, max_bytes):
        for field in ("store",):
            if field in payload and type(payload[field]) is not bool:
                raise ResponseError("%s must be a boolean" % field)
        previous = payload.get("previous_response_id")
        if previous is not None and (not isinstance(previous, str) or not previous or len(previous) > 256):
            raise ResponseError("previous_response_id must be a non-empty string")
        if payload.get("background"):
            raise ResponseError("background Responses are not supported")
        if payload.get("conversation"):
            raise ResponseError("use previous_response_id for conversation state")
        cfg = config(self.directory)
        store = bool(owner and cfg["enabled"] and payload.get("store", True))
        context = {"owner": owner, "store": store, "id": "resp_" + uuid.uuid4().hex,
                   "previous": previous, "conversation": "conv_" + uuid.uuid4().hex, "bound": False}
        body = copy.deepcopy(payload)
        history = []
        if previous:
            if not cfg["enabled"]:
                raise ResponseError("response not found", 404, "response_not_found")
            saved = self.get(previous, owner, allowed, include_history=True)
            if payload.get("model") and payload["model"] != saved["model"]:
                raise ResponseError("a response chain keeps its model; send full history to start another chain")
            body["model"] = saved["model"]
            context.update(conversation=saved["conversation"], upstream=saved["upstream"],
                           realm=saved["realm"], account=saved["account"], bound=saved["bound"])
            history = saved["history"]
        body.pop("previous_response_id", None)
        body["input"] = history + input_items(payload.get("input"))
        if len(_json(body).encode("utf-8")) > max_bytes:
            raise ResponseError("restored conversation exceeds the request size limit", 413, "context_length_exceeded")
        context["input"] = copy.deepcopy(body["input"])
        context["request"] = {name: copy.deepcopy(payload[name]) for name in
                              ("instructions", "metadata", "tools", "tool_choice", "parallel_tool_calls") if name in payload}
        return body, context

    def finish(self, response, context, upstream, realm, model, account=None):
        result = copy.deepcopy(response)
        result.update(id=context["id"], model=model, store=context["store"],
                      previous_response_id=context["previous"])
        result.update(context["request"])
        if result.get("status") not in ("completed", "incomplete") or not context["store"]:
            return result
        if result.get("status") == "incomplete" and (result.get("incomplete_details") or {}).get("reason") != "max_output_tokens":
            return result
        self.cleanup()
        history = context["input"] + copy.deepcopy(context.get("replay_tail", result.get("output") or []))
        items, refs = {}, []
        for item in history:
            raw = _json(item)
            digest = hashlib.sha256((context["owner"] + "\0" + raw).encode("utf-8")).hexdigest()
            refs.append(digest)
            items[digest] = (raw, len(raw.encode("utf-8")))
        raw, raw_refs = _json(result), _json(refs)
        size = len(raw.encode("utf-8")) + len(raw_refs.encode("utf-8"))
        now = time.time()
        cfg = config(self.directory)
        with self.db.write_lock:
            connection = self.db.connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute("SELECT COALESCE(SUM(size),0) FROM response_items").fetchone()[0]
                current += connection.execute("SELECT COALESCE(SUM(size),0) FROM responses").fetchone()[0]
                additional = size + sum(value[1] for digest, value in items.items()
                    if not connection.execute("SELECT 1 FROM response_items WHERE digest=?", (digest,)).fetchone())
                if current + additional > cfg["max_mb"] * 1024 * 1024:
                    raise ResponseError("Responses storage is full; delete expired conversations or increase capacity", 507, "response_storage_full")
                connection.executemany("INSERT OR IGNORE INTO response_items VALUES(?,?,?)",
                    [(digest, value[0], value[1]) for digest, value in items.items()])
                connection.execute("INSERT INTO responses VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (context["id"], context["owner"], context["conversation"], upstream, realm or "", model,
                     account, int(context["bound"] or account_bound(history)), now, now + cfg["retention_days"] * 86400,
                     raw_refs, raw, size))
                connection.execute("COMMIT")
                self.db._restrict()
            except sqlite3.Error as exc:
                connection.execute("ROLLBACK")
                raise ResponseError("Responses history could not be stored", 503, "response_storage_unavailable") from exc
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return result

    def delete(self, identifier, owner, allowed):
        with self.db.write_lock:
            self.get(identifier, owner, allowed)
            self.db.connection().execute("DELETE FROM responses WHERE id=? AND owner=?", (identifier, owner))
            self._collect(self.db.connection())
        return {"id": identifier, "object": "response.deleted", "deleted": True}

    def delete_conversation(self, conversation):
        if not isinstance(conversation, str) or not conversation.startswith("conv_"):
            raise ResponseError("invalid conversation id")
        with self.db.write_lock:
            cursor = self.db.connection().execute("DELETE FROM responses WHERE conversation=?", (conversation,))
            self._collect(self.db.connection())
        return {"deleted": cursor.rowcount}

    def snapshot(self):
        self.cleanup()
        connection = self.db.connection()
        return {**config(self.directory), "count": connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0],
                "bytes": connection.execute("SELECT COALESCE(SUM(size),0) FROM responses").fetchone()[0]
                         + connection.execute("SELECT COALESCE(SUM(size),0) FROM response_items").fetchone()[0],
                "conversations": [dict(zip(("id", "upstream", "model", "created_at", "expires_at", "responses"), row))
                    for row in connection.execute("""SELECT conversation,upstream,model,MAX(created_at),MAX(expires_at),COUNT(*)
                        FROM responses GROUP BY conversation ORDER BY MAX(created_at) DESC LIMIT 100""")]}
