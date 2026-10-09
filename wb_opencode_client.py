"""OpenCode client protocol metadata, independent of account authentication."""
import hashlib
import uuid

# Official release v1.18.35 and session/llm/request.ts, revision 3884062.
# Authentication remains the selected account's credential; TLS is verified.
USER_AGENT = "opencode/1.18.35"


def _identifier(prefix, value):
    return prefix + "_" + hashlib.sha256((prefix + "\0" + value).encode()).hexdigest()[:24]


def headers(account, session="", owner="", body=None):
    metadata = (body or {}).get("metadata") or {}
    project = metadata.get("project_id", "default") if isinstance(metadata, dict) else "default"
    session_id = _identifier("ses", account + "\0" + owner + "\0" + (session or uuid.uuid4().hex))
    request_id = "msg_" + uuid.uuid4().hex
    return {"User-Agent": USER_AGENT, "x-opencode-client": "cli",
            "x-opencode-session": session_id, "x-opencode-session-id": session_id,
            "x-opencode-request": request_id, "x-opencode-request-id": request_id,
            "x-opencode-project": _identifier("prj", owner + "\0" + str(project)),
            "Accept": "application/json", "Content-Type": "application/json"}
