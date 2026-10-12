# -*- coding: utf-8 -*-
"""wb_prompt.py — 網關自有系統提示詞模式（panel prompt.go / degrade.go 語義）。

客戶端（Codex / Claude Code 等）在 system prompt 裡注入固定模板句時，上游內容
審核可能按逐字匹配誤殺合法流量。本模組讓網關在出站前改寫 system/developer
訊息，從源頭消滅 system 來源的指紋誤報；user/assistant/tool 訊息不動（既有
sanitize 指紋清洗照舊，兩層互不替代）。

模式（settings.json 的 prompt.mode，預設 passthrough）：
  - passthrough：透傳客戶端 system/developer（hub 原本的行為）；
  - custom：刪除所有 system/developer，換成一條網關提示詞；
  - append：在開頭連續 system/developer 區塊之後插入一條網關提示詞，
    客戶端既有訊息逐字保留。

可選重試（passthrough / append）：預設關閉。僅明確的 11140 內容攔截可讓
該請求用中性提示詞重試一次；不影響其他請求。custom 模式不走重試路徑。
"""

import json
import threading
import time

# 內置默認提示詞：用於 custom / append 模式（file > text > 內置）。
DEFAULT_PROMPT = """你是一名工程助手，幫助用戶完成軟件工程任務。

- 先理解代碼與上下文再動手，遵循既有模式與約定。
- 最小改動：只改必要部分，不做無關重構。
- 改動後要驗證：跑測試或構建確認結果，不假設「應該沒問題」。
- 對不確定的事保持誠實：說明不確定並給出驗證路徑，不編造。
- 跟隨用戶語言；簡潔直接，技術術語精確。
- 如實報告失敗與邊界，不掩蓋、不粉飾。
"""

# 降級提示詞：刻意極簡中性，只用於繞開 system 來源的審核誤報。
DEGRADED_PROMPT = ("You are a helpful assistant. Respond in the user's language, "
                   "follow the user's instructions, and be direct and concise.")

VALID_MODES = ("passthrough", "custom", "append")
MAX_PROMPT_BYTES = 256 * 1024
_retry_lock = threading.Lock()
_retry_status = {"scope": "request", "count": 0, "last_at": None, "last_model": None}


def is_content_rejection(detail):
    """Only the provider's explicit content rejection code permits a retry."""
    try:
        value = json.loads(detail)
    except (TypeError, ValueError):
        return False
    for _ in range(5):
        if not isinstance(value, dict):
            return False
        if str(value.get("code") or value.get("error_code") or "") == "11140":
            return True
        value = value.get("error") or value.get("data")
    return False


def record_retry(model):
    with _retry_lock:
        _retry_status.update(count=_retry_status["count"] + 1,
                             last_at=time.time(), last_model=model)


def retry_status():
    with _retry_lock:
        return dict(_retry_status)


def normalize_mode(value):
    """未知模式回退 passthrough（保守默認，不意外改寫客戶端提示詞）。"""
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_MODES else "passthrough"


def load_prompt(mode, file_path="", text=""):
    """Load bounded UTF-8 source text; never send rendered HTML upstream."""
    path = str(file_path or "").strip()
    if path:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_PROMPT_BYTES + 1)
        if len(raw) > MAX_PROMPT_BYTES:
            raise ValueError("prompt file exceeds 256 KiB")
        value = raw.decode("utf-8-sig")
        if not value.strip():
            raise ValueError("prompt file is empty")
        return value
    if text:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("prompt text must contain non-whitespace text")
        if len(text.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("prompt text exceeds 256 KiB")
        return text
    return DEFAULT_PROMPT


def preview(cfg):
    """Admin-only source preview, including the fail-open state of bad files."""
    source = "file" if cfg.get("file") else "text" if cfg.get("text") else "builtin"
    result = {"source": source, "text": "", "default_text": DEFAULT_PROMPT, "error": "",
              "active": normalize_mode(cfg.get("mode")) != "passthrough"}
    try:
        result["text"] = load_prompt(cfg.get("mode"), cfg.get("file"), cfg.get("text", ""))
    except (OSError, UnicodeError, ValueError) as exc:
        result.update(error=str(exc), active=False)
    return result


def rewrite(messages, system_prompt):
    """刪除所有 system/developer，頭部插入一條網關 system 訊息。"""
    if not system_prompt:
        return messages
    kept = [m for m in (messages or [])
            if not (isinstance(m, dict)
                    and m.get("role") in ("system", "developer"))]
    return [{"role": "system", "content": system_prompt}] + kept


def append(messages, system_prompt):
    """在開頭連續 system/developer 區塊之後插入網關提示詞，其餘訊息不動。"""
    if not system_prompt:
        return messages
    msgs = list(messages or [])
    insert_at = 0
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("system", "developer"):
            break
        insert_at += 1
    return (msgs[:insert_at]
            + [{"role": "system", "content": system_prompt}]
            + msgs[insert_at:])


def apply_mode(messages, mode, text, degraded=False):
    """按模式路由一次請求的 messages；degraded 只影響 passthrough/append。"""
    mode = normalize_mode(mode)
    if mode == "custom":
        return rewrite(messages, text)
    if mode == "append":
        if degraded:
            return rewrite(messages, DEGRADED_PROMPT)
        return append(messages, text)
    if degraded:
        return rewrite(messages, DEGRADED_PROMPT)
    return messages


def apply_payload(payload, protocol, mode, text, degraded=False):
    """Apply a policy at the outbound boundary without changing client history.

    Native protocols retain opaque blocks and cache metadata. Responses has
    both instructions and system/developer input items; custom replaces both.
    Append preserves instructions and inserts after the leading input block.
    """
    mode = normalize_mode(mode)
    if degraded and mode != "custom":
        mode, text = "custom", DEGRADED_PROMPT
    if mode == "passthrough" or not text:
        return payload
    body = dict(payload)
    if protocol == "chat":
        body["messages"] = apply_mode(payload.get("messages"), mode, text)
    elif protocol == "responses":
        items = payload.get("input")
        if mode == "custom":
            body["instructions"] = text
            if isinstance(items, list):
                body["input"] = [item for item in items if not _instruction(item)]
        else:
            items = ([{"role": "user", "content": items}] if isinstance(items, str)
                     else list(items or []))
            index = 0
            while index < len(items) and _instruction(items[index]):
                index += 1
            body["input"] = (items[:index] + [{"type": "message", "role": "system",
                                             "content": text}] + items[index:])
    elif protocol == "messages":
        if mode == "custom":
            body["system"] = text
            if isinstance(payload.get("messages"), list):
                body["messages"] = [item for item in payload["messages"] if not _instruction(item)]
        else:
            system = payload.get("system")
            if isinstance(system, list):
                body["system"] = system + [{"type": "text", "text": text}]
            else:
                body["system"] = (system + "\n\n" + text) if system else text
    else:
        raise ValueError("unknown prompt protocol: " + str(protocol))
    return body


def _instruction(item):
    return isinstance(item, dict) and item.get("role") in ("system", "developer")
