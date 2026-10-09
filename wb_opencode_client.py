"""OpenCode client protocol metadata, independent of account authentication."""
import hashlib
import uuid

# Compatibility profile from spfnas/opencode2api-free, revision 656b088.
# Authentication remains the selected account's credential; TLS is verified.
USER_AGENT = "opencode/1.18.16 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14"


def _identifier(prefix, value):
    return prefix + "_" + hashlib.sha256((prefix + "\0" + value).encode()).hexdigest()[:24]


def headers(account, session="", owner="", body=None):
    metadata = (body or {}).get("metadata") or {}
    project = metadata.get("project_id", "default") if isinstance(metadata, dict) else "default"
    return {"User-Agent": USER_AGENT, "x-opencode-client": "cli",
            "x-opencode-session": _identifier("ses", account + "\0" + owner + "\0" + (session or uuid.uuid4().hex)),
            "x-opencode-request": "req_" + uuid.uuid4().hex,
            "x-opencode-project": _identifier("prj", owner + "\0" + str(project)),
            "Accept": "application/json", "Content-Type": "application/json"}
