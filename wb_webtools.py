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

from collections import OrderedDict
from contextvars import ContextVar
import gzip
import html as _html
from html.parser import HTMLParser
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wb_webnet

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
LITE_SEARCH_ENDPOINT = "https://lite.duckduckgo.com/lite/"
MAX_HTTP_BYTES = 2 * 1024 * 1024
MAX_QUERY_CHARS = 2000
SEARCH_CACHE_TTL = 120
SEARCH_ERROR_TTL = 5
SEARCH_CACHE_SIZE = 128
_search_cache = OrderedDict()
_search_pending = set()
_search_condition = threading.Condition()
_call_deadline = ContextVar("web_call_deadline", default=None)


class ResponseLimitError(ValueError):
    """The backend exceeded the wire or decompressed response limit."""


def _read_bounded(response, deadline):
    chunks = []
    size = 0
    read = getattr(response, "read1", response.read)
    # HTTPResponse.read(size) may wait for the entire size on a trickling
    # peer. read1 returns after one socket read, so the deadline is checked
    # between chunks as well as the ordinary socket idle timeout.
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("web response deadline exceeded")
        # Reading the last Content-Length bytes can close fp immediately.
        # Recheck it each iteration instead of touching a closed socket.
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        chunk = read(min(65536, MAX_HTTP_BYTES + 1 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_HTTP_BYTES:
            raise ResponseLimitError("response exceeds size limit")


def max_rounds():
    """最多代跑幾輪網路工具。環境變數可覆蓋，方便臨時關小。"""
    try:
        n = int(os.environ.get("WB_MAX_WEB_ROUNDS", "") or "")
    except (TypeError, ValueError):
        n = 0
    return min(8, n) if n > 0 else 3


MAX_WEB_ROUNDS = max_rounds()
MAX_WEB_CALLS = 16
MAX_WEB_TIME_SECONDS = 180


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


def _http_get(url, timeout=HTTP_TIMEOUT):
    deadline = time.monotonic() + timeout
    if _call_deadline.get() is not None:
        deadline = min(deadline, _call_deadline.get())
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
    }
    for hop in range(wb_webnet.MAX_REDIRECTS + 1):
        conn, resp = wb_webnet.open_response(url, deadline, headers)
        try:
            if resp.status in (301, 302, 303, 307, 308):
                target = resp.headers.get("Location")
                if not target or hop == wb_webnet.MAX_REDIRECTS:
                    raise ValueError("invalid or excessive web redirects")
                url = urllib.parse.urljoin(url, target)
                # The next hop goes through DNS validation and IP pinning too.
                continue
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)
            content_type = resp.headers.get_content_type()
            if not (content_type.startswith("text/") or content_type in (
                    "application/xhtml+xml", "application/xml", "application/json")):
                raise ValueError("web tools only read text responses")
            raw = _read_bounded(resp, deadline)
            encoding = (resp.headers.get("Content-Encoding") or "").lower().strip()
            if encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
                    raw = zipped.read(MAX_HTTP_BYTES + 1)
                if len(raw) > MAX_HTTP_BYTES:
                    raise ResponseLimitError("decompressed response exceeds size limit")
            elif encoding not in ("", "identity"):
                raise ValueError("unsupported response encoding")
            charset = resp.headers.get_content_charset() or "utf-8"
            break
        finally:
            resp.close()
            conn.close()
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
    try:
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(SEARCH_ENDPOINT, href))
        host = (parsed.hostname or "").lower()
        if host == "duckduckgo.com" or host.endswith(".duckduckgo.com"):
            if parsed.path != "/l/":
                return ""  # Navigation and advertising links are not sources.
            # parse_qs already decodes once. A second unquote corrupts %2F in
            # a target URL's own path/query and can point to a different page.
            href = (urllib.parse.parse_qs(parsed.query).get("uddg") or [""])[0]
        else:
            href = urllib.parse.urlunsplit(parsed)
        target, problem = _guard_url(href)
        return "" if problem else target
    except (ValueError, TypeError):
        return ""


class _SearchParser(HTMLParser):
    """Read both official non-JS layouts, independent of attribute ordering."""

    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                  "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.challenge = False
        self.no_results = False
        self._stack = []
        self._current = None
        self._capture = None
        self._seen = set()

    def _finish(self):
        row = self._current
        if row:
            title = re.sub(r"\s+", " ", "".join(row["title"])).strip()[:300]
            snippet = re.sub(r"\s+", " ", "".join(row["snippet"])).strip()[:1200]
            url = row["url"]
            if title and url and url not in self._seen and len(self.results) < MAX_RESULTS:
                self._seen.add(url)
                self.results.append({"title": title, "url": url, "snippet": snippet})
        self._current = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag not in self._void_tags:
            self._stack.append((tag, classes))
        if (attrs.get("id") == "challenge-form"
                or any(c.startswith("anomaly-modal") for c in classes)):
            self.challenge = True
        if any(c.startswith("no-results") for c in classes):
            self.no_results = True
        if tag == "a" and classes.intersection({"result__a", "result-link"}):
            self._finish()
            ad = any(cs.intersection({"result--ad", "result--sponsored"})
                     for _, cs in self._stack)
            target = _ddg_target(attrs.get("href"))
            if target and not ad:
                self._current = {"url": target, "title": [], "snippet": []}
                self._capture = ("title", len(self._stack))
        elif classes.intersection({"result__snippet", "result-snippet"}) and self._current:
            self._capture = ("snippet", len(self._stack))
        elif tag == "br" and self._capture and self._current:
            self._current[self._capture[0]].append(" ")

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if self._capture and len(self._stack) < self._capture[1]:
            self._capture = None

    def handle_data(self, text):
        if (self._capture and self._current
                and not any(tag in ("script", "style", "noscript") for tag, _ in self._stack)):
            self._current[self._capture[0]].append(text)

    def close(self):
        super().close()
        self._finish()


def _search_backend(query):
    """At most two requests, sharing one timeout budget; never solve challenges."""
    deadline = time.monotonic() + HTTP_TIMEOUT
    if _call_deadline.get() is not None:
        deadline = min(deadline, _call_deadline.get())
    error = "Error: the search backend returned an unrecognized HTML page."
    for endpoint in (SEARCH_ENDPOINT, LITE_SEARCH_ENDPOINT):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        url = endpoint + "?" + urllib.parse.urlencode({"q": query})
        try:
            page = _http_get(url, timeout=remaining)
            parser = _SearchParser()
            parser.feed(page)
            parser.close()
            if parser.challenge:
                error = "Error: DuckDuckGo requires a CAPTCHA; search results are unavailable."
            elif parser.results:
                return parser.results, ""
            elif parser.no_results:
                return [], ""
            else:
                error = "Error: DuckDuckGo returned no recognizable results or no-results marker."
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            error = "Error: the search backend answered HTTP %s." % code
            if code == 429:
                return [], error + " Rate limited; retry later."
            if code < 500:
                return [], error
        except ResponseLimitError:
            return [], "Error: the search backend response exceeds the size limit."
        except Exception as exc:
            error = "Error: could not reach or read the search backend (%s)." % type(exc).__name__
    return [], error


def _cached_search(query):
    key = (query, os.environ.get("WB_WEB_PROXY", ""))
    deadline = time.monotonic() + HTTP_TIMEOUT
    if _call_deadline.get() is not None:
        deadline = min(deadline, _call_deadline.get())
    with _search_condition:
        while key in _search_pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [], "Error: timed out waiting for an ongoing search."
            _search_condition.wait(remaining)
        cached = _search_cache.get(key)
        if cached and cached[0] > time.monotonic():
            _search_cache.move_to_end(key)
            return cached[1], cached[2]
        _search_pending.add(key)
    try:
        rows, error = _search_backend(query)
        with _search_condition:
            ttl = SEARCH_ERROR_TTL if error else SEARCH_CACHE_TTL
            _search_cache[key] = (time.monotonic() + ttl, rows, error)
            _search_cache.move_to_end(key)
            while len(_search_cache) > SEARCH_CACHE_SIZE:
                _search_cache.popitem(last=False)
        return rows, error
    finally:
        with _search_condition:
            _search_pending.discard(key)
            _search_condition.notify_all()


def search_results(query, num_results=5, allowed_domains=None, blocked_domains=None):
    """Structured DDG results shared by the Responses and Messages adapters."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    result = {"query": query, "results": []}
    if len(query) < 2:
        result["error"] = ('Error: web_search needs a query of at least 2 characters; '
                           'got %r. Pass it as {"query": "..."}.' % query)
        return result
    if len(query) > MAX_QUERY_CHARS:
        result["error"] = "Error: web_search query exceeds %d characters." % MAX_QUERY_CHARS
        return result
    try:
        n = int(num_results)
    except (TypeError, ValueError, OverflowError):
        n = 5
    n = max(1, min(MAX_RESULTS, n))

    backend_query = query
    if allowed_domains:
        backend_query += " (" + " OR ".join("site:" + d for d in allowed_domains) + ")"
    if blocked_domains:
        backend_query += " " + " ".join("-site:" + d for d in blocked_domains)
    if len(backend_query) > MAX_QUERY_CHARS:
        result["error"] = "Error: web_search query with domain filters exceeds %d characters." % MAX_QUERY_CHARS
        return result
    rows, error = _cached_search(backend_query)
    if error:
        result["error"] = error
        return result

    def matches(host, domains):
        return any(host == d or host.endswith("." + d) for d in domains or [])

    filtered = []
    for row in rows:
        try:
            host = (urllib.parse.urlsplit(row["url"]).hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
        except (ValueError, UnicodeError):
            continue
        if allowed_domains and not matches(host, allowed_domains):
            continue
        if matches(host, blocked_domains):
            continue
        filtered.append(dict(row))
    result["results"] = filtered[:n]
    return result


def format_search_results(result):
    """Keep the readable tool format used by models and source extraction."""
    if result.get("error"):
        return result["error"]
    query, results = result.get("query") or "", result.get("results") or []

    if not results:
        return ("No results found for: %s%sTry a broader or differently worded query."
                % (query, chr(10) + chr(10)))

    lines = ["%d. %s%s   %s%s   %s" % (i, r["title"], chr(10), r["url"], chr(10), r["snippet"])
             for i, r in enumerate(results, 1)]
    return ("Search results for: %s%s%s%s%sCite the sources you used at the end of "
            "your answer." % (query, chr(10) + chr(10), (chr(10) + chr(10)).join(lines),
                              chr(10) + chr(10), ""))


def search(query, num_results=5):
    return format_search_results(search_results(query, num_results))


def _guard_url(url):
    return wb_webnet.guard_url(url)


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
    text = str(result or "")
    # Fetch uses a different, paged format from search. Its successful URL
    # header is also a real source and must reach citation annotations.
    fetched = re.match(r"^URL: (https?://[^\s]+)\nCharacters: \d+-\d+ of \d+\n", text)
    if fetched:
        url = fetched.group(1)
        return [{"title": url, "url": url}]
    pattern = r"(?m)^\d+\.\s*(.+?)\s*\n\s*(https?://\S+)\s*$"
    for m in re.finditer(pattern, text):
        url = m.group(2).strip()
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
