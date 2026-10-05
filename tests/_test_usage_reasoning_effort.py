"""The usage row records the reasoning effort the request actually ran at.

    build_upstream_body() resolves the effort (the client's value, else the model
    default), open_upstream() hands it back to the response handlers, and
    record_usage() writes it as reasoning_effort so the panel's recent-requests
    table can show it next to the model. Rows without one - models that have no
    reasoning controls, and rows written before the field existed - must stay
    exactly as they were.

    No network: the log is written to a temp directory.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="wb-effort-")
os.environ["ACCOUNTS_DIR"] = os.path.join(_TMP, "accounts")
os.environ["WB_PROXY_USAGE_DIR"] = _TMP
os.makedirs(os.environ["ACCOUNTS_DIR"], exist_ok=True)

import wb_proxy as P

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s  %s" % (label, extra))


def rows():
    with open(P.USAGE_LOG, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 3,
         "cached_tokens": 4, "total_tokens": 15}

P.record_usage("deepseek-v4.1-flash", USAGE, stream=True, elapsed_ms=1200, ttft_ms=800,
               gen_ms=400, account=None, effort="high")
row = rows()[-1]
check("the resolved effort is written on the row",
      row.get("reasoning_effort") == "high", row.get("reasoning_effort"))

P.record_usage("hy3", USAGE, stream=False, elapsed_ms=900, effort=None)
check("a request without an effort writes no field",
      "reasoning_effort" not in rows()[-1], rows()[-1].get("reasoning_effort"))

P.record_usage("gemini-3.5-flash", USAGE, stream=False, elapsed_ms=900, effort="medium")
check("a fixed-effort model records its fixed value",
      rows()[-1].get("reasoning_effort") == "medium", rows()[-1].get("reasoning_effort"))

# The panel reads rows through recent_usage(); the field has to survive it.
got = P.recent_usage(limit=10, realm=P.CURRENT_REALM)
latest = got["rows"][0]
check("recent_usage passes the field through",
      latest.get("reasoning_effort") == "medium", latest.get("reasoning_effort"))
check("recent_usage still returns the other fields",
      latest.get("model") == "gemini-3.5-flash" and latest.get("total_tokens") == 15,
      latest)
old = [r for r in got["rows"] if r.get("model") == "hy3"][0]
check("a row written without the field stays without it",
      "reasoning_effort" not in old, old)

print("")
print("  PASS=%d FAIL=%d" % (PASS, FAIL))
if FAIL:
    sys.exit(1)
print("OK")
