# -*- coding: utf-8 -*-
"""反代代跑 web_search / web_fetch（開關在 wb_proxy.LOCAL_WEB_TOOLS）

背景：Codex App 會宣告 web_search 這種 Responses 的伺服器端工具，但 WorkBuddy
上游沒有任何搜尋服務——v1.5.3 的 revert 已經量測過，直接把 web_search /
web_search_preview / web_fetch 丟給 chat endpoint，模型的回答跟完全不給工具
一樣（零個 tool call）。所以沒有現成的執行器可以轉接，只能由反代自己跑。

v1.5.0 ~ 1.5.2 做過同一件事，被 revert（issue #43）。三個缺陷都在這裡修掉：

  1. 只認 args["query"] 這個字串。模型改送 queries 陣列時會收到一句「你沒問
     問題」，於是必然重試、必然把回合數耗光。-> query_args() 同時接受
     query / queries / q，並把多個查詢合併成一次搜尋。
  2. 去重只看已展開成 chat 形狀的 function，漏掉客戶端原本那份伺服器端宣告，
     上游因此同時看到兩個同名的 web_search。-> install_tool_defs() 先把同名
     項目全部拿掉，再放進唯一一份我們的定義。
  3. 回合用盡時合成一個 resp_wrapup（status=completed、output=[]）收尾，把
     失敗偽裝成正常結束，客戶端看到的是「講到一半斷掉」。-> 這裡不合成任何
     東西：呼叫端在最後一輪把工具收回，讓模型自己用文字收尾。

搜尋後端是 DuckDuckGo 的 HTML 版（不需要 API key）。任何失敗都回一句可讀的
錯誤給模型，不假造結果。只用 Python 標準庫。
"""

import html as _html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

WEB_SEARCH_NAME = "web_search"
WEB_FETCH_NAME = "web_fetch"

# 客戶端會用這幾種 type 宣告同一個工具
SEARCH_DECL_TYPES = ("web_search", "web_search_preview", "web_search_preview_2025_03_11")
FETCH_DECL_TYPES = ("web_fetch",)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

MAX_RESULTS = 10
MAX_FETCH_CHARS = 100000
HTTP_TIMEOUT = 20
SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"


def max_rounds():
    """最多代跑幾輪網路工具。環境變數可覆蓋，方便臨時關小。"""
    try:
        n = int(os.environ.get("WB_MAX_WEB_ROUNDS", "") or "")
    except (TypeError, ValueError):
        n = 0
    return min(8, n) if n > 0 else 3


MAX_WEB_ROUNDS = max_rounds()


def web_search_tool_def():
    return {
        "type": "function",
        "name": WEB_SEARCH_NAME,
        "description": (
            "Searches the web for real-time information and returns ranked results "
            "with titles, URLs and snippets. Use it for current events, documentation "
            "lookup, or anything beyond your knowledge cutoff. To read a page in full, "
            "call web_fetch on its URL afterwards."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query (at least 2 characters).",
                },
                "numResults": {
                    "type": "number",
                    "description": "How many results to return (1-10, default 5).",
                },
            },
            "required": ["query"],
        },
    }


def web_fetch_tool_def():
    return {
        "type": "function",
        "name": WEB_FETCH_NAME,
        "description": (
            "Fetches a URL and returns its readable text. Use startIndex to page "
            "through a long page."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute http:// or https:// URL to fetch.",
                },
                "startIndex": {
                    "type": "number",
                    "description": "Character offset to continue reading a long page.",
                },
            },
            "required": ["url"],
        },
    }


def _declared(tools, types):
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        if str(t.get("type") or "").strip().lower() in types:
            return True
        # 有些客戶端會把它包成 function 形狀
        if str(t.get("name") or "").strip().lower() in types:
            return True
    return False


def client_wants_web(tools):
    """客戶端宣告了哪幾個網路工具（伺服器端或 function 形狀都算）。"""
    return {
        "search": _declared(tools, SEARCH_DECL_TYPES + (WEB_SEARCH_NAME,)),
        "fetch": _declared(tools, FETCH_DECL_TYPES + (WEB_FETCH_NAME,)),
    }


def install_tool_defs(chat_tools, wants):
    """把客戶端的網路工具宣告換成我們的 function。

    同名項目（伺服器端的 {"type": "web_search"}、客戶端自己帶的 function、
    以及上一輪從我們這裡學到的定義）一律先移除，只留唯一一份；否則上游會
    同時看到兩個 web_search，模型會挑錯那個去呼叫。
    """
    names = set()
    if wants.get("search"):
        names.add(WEB_SEARCH_NAME)
    if wants.get("fetch"):
        names.add(WEB_FETCH_NAME)

    kept = []
    for t in chat_tools or []:
        if not isinstance(t, dict):
            kept.append(t)
            continue
        type_name = str(t.get("type") or "").strip().lower()
        name = str(t.get("name") or "").strip().lower()
        if isinstance(t.get("function"), dict):
            name = name or str((t.get("function") or {}).get("name") or "").strip().lower()
        if name in names or type_name in names:
            continue
        kept.append(t)

    if wants.get("search"):
        kept.append(web_search_tool_def())
    if wants.get("fetch"):
        kept.append(web_fetch_tool_def())
    return kept


def is_internal_tool(name):
    return str(name or "").strip() in (WEB_SEARCH_NAME, WEB_FETCH_NAME)


def query_args(args):
    """從工具參數取出查詢字串。

    舊版只讀 args["query"] 這個字串，模型改送 queries 陣列時就會被回一句
    「你沒問問題」——issue #43 就是這樣一路重試到回合用盡。這裡接受
    query / queries / q，陣列會用 " or " 接起來。
    """
    if not isinstance(args, dict):
        return ""
    raw = args.get("query")
    if raw is None:
        raw = args.get("queries")
    if raw is None:
        raw = args.get("q")
    if isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw if str(x or "").strip()]
        return " or ".join(parts)
    return str(raw or "").strip()


def url_arg(args):
    if not isinstance(args, dict):
        return ""
    raw = args.get("url")
    if raw is None:
        raw = args.get("urls")
    if isinstance(raw, (list, tuple)):
        for x in raw:
            if str(x or "").strip():
                return str(x).strip()
        return ""
    return str(raw or "").strip()


def _http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, "replace")
    except Exception:
        return raw.decode("utf-8", "replace")


def _strip_tags(text):
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?is)<br\s*/?>", chr(10), text)
    text = re.sub(r"(?is)</(p|div|li|tr|h[1-6])>", chr(10), text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = text.replace(chr(160), " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", chr(10), text)
    text = re.sub(chr(10) + "{3,}", chr(10) + chr(10), text)
    return text.strip()


def _ddg_target(href):
    """解開 DuckDuckGo 的 /l/?uddg= 轉址。"""
    href = _html.unescape(str(href or "").strip())
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urllib.parse.urlparse(href)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            target = (urllib.parse.parse_qs(parsed.query).get("uddg") or [""])[0]
            if target:
                return urllib.parse.unquote(target)
    except Exception:
        pass
    return href


def search(query, num_results=5):
    """DuckDuckGo HTML 版搜尋，回傳要餵給模型的可讀字串。"""
    query = str(query or "").strip()
    if len(query) < 2:
        return ('Error: web_search needs a query of at least 2 characters; '
                'got %r. Pass it as {"query": "..."}.' % query)
    try:
        n = int(num_results)
    except (TypeError, ValueError):
        n = 5
    n = max(1, min(MAX_RESULTS, n))

    url = SEARCH_ENDPOINT + "?" + urllib.parse.urlencode({"q": query})
    try:
        page = _http_get(url)
    except urllib.error.HTTPError as exc:
        return "Error: the search backend answered HTTP %s for %r." % (exc.code, query)
    except Exception as exc:
        return "Error: could not reach the search backend for %r (%s)." % (
            query, type(exc).__name__)

    blocks = re.split(r'(?is)<div[^>]+class="[^"]*result__body[^"]*"', page)
    results = []
    for block in blocks[1:]:
        m_link = re.search(
            r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not m_link:
            continue
        href = _ddg_target(m_link.group(1))
        title = _strip_tags(m_link.group(2))
        m_snip = re.search(r'(?is)class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block)
        snippet = _strip_tags(m_snip.group(1)) if m_snip else ""
        if not href or not title:
            continue
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= n:
            break

    if not results:
        return ("No results found for: %s%sTry a broader or differently worded query."
                % (query, chr(10) + chr(10)))

    lines = ["%d. %s%s   %s%s   %s" % (i, r["title"], chr(10), r["url"], chr(10), r["snippet"])
             for i, r in enumerate(results, 1)]
    return ("Search results for: %s%s%s%s%sCite the sources you used at the end of "
            "your answer." % (query, chr(10) + chr(10), (chr(10) + chr(10)).join(lines),
                              chr(10) + chr(10), ""))


def _guard_url(url):
    """只允許對外的一般 http(s) 網址。"""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return None, "Invalid URL."
    if parsed.scheme.lower() not in ("http", "https"):
        return None, "Only http:// or https:// URLs are supported."
    if parsed.username or parsed.password:
        return None, "Credentials in the URL are not allowed."
    host = (parsed.hostname or "").lower()
    if not host or "." not in host or host.endswith(".localhost"):
        return None, "Private, loopback or single-label hosts are not allowed."
    if re.match(r"^(127\.|10\.|192\.168\.|169\.254\.|0\.)", host) or \
            re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host):
        return None, "Private network addresses are not allowed."
    return url, ""


def fetch(url, start_index=0):
    url, problem = _guard_url(url)
    if problem:
        return "Error: %s" % problem
    try:
        page = _http_get(url)
    except urllib.error.HTTPError as exc:
        return "Error: %s answered HTTP %s." % (url, exc.code)
    except Exception as exc:
        return "Error: could not fetch %s (%s)." % (url, type(exc).__name__)

    text = _strip_tags(page)
    try:
        start = max(0, int(start_index))
    except (TypeError, ValueError):
        start = 0
    if start >= len(text):
        return ("Error: startIndex %d is past the end of the page (%d characters "
                "total)." % (start, len(text)))

    end = min(start + MAX_FETCH_CHARS, len(text))
    head = "URL: %s%sCharacters: %d-%d of %d" % (url, chr(10), start, end, len(text))
    tail = ""
    if end < len(text):
        tail = (chr(10) + chr(10) + "[Truncated. Call web_fetch again with startIndex=%d "
                "to continue.]" % end)
    return head + chr(10) + chr(10) + text[start:end] + tail


def sources_from_result(result):
    """把搜尋結果裡的 (標題, 網址) 讀回來。

    餵給模型的是文字，但客戶端要畫引用來源需要結構化資料，所以在這裡從我們
    自己產出的格式反解，不必另外保存狀態。
    """
    out = []
    pattern = r"(?m)^\d+\.\s*(.+?)\s*\n\s*(https?://\S+)\s*$"
    for m in re.finditer(pattern, str(result or "")):
        url = m.group(2).strip().rstrip(".,;:!?")
        title = m.group(1).strip()
        if url and not any(s["url"] == url for s in out):
            out.append({"title": title or url, "url": url})
    return out


def execute(name, args_raw):
    """執行一次內部網路工具。永不拋例外，永遠回一句能餵回模型的字串。"""
    name = str(name or "").strip()
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw or "{}")
        except Exception:
            args = {}
    elif isinstance(args_raw, dict):
        args = args_raw
    else:
        args = {}
    if not isinstance(args, dict):
        args = {}

    try:
        if name == WEB_SEARCH_NAME:
            return search(query_args(args), args.get("numResults") or 5)
        if name == WEB_FETCH_NAME:
            return fetch(url_arg(args), args.get("startIndex") or 0)
        return "Error: %s is not a tool this gateway runs." % name
    except Exception as exc:
        return "Error running %s: %s: %s" % (name, type(exc).__name__, exc)