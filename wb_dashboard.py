"""Cached dashboard template with immutable, compressed script/style assets."""
import collections
import gzip
import hashlib
import json
import os
import re
import threading
from pathlib import Path


def source_html(path):
    """Expand repository assets in order; the app is bundled in one JS scope."""
    page = Path(path)
    text = page.read_text(encoding="utf-8")
    root = page.parent / "dashboard_static"
    if not root.is_dir():
        return text
    manifest = json.loads((root / "bundles.json").read_text(encoding="utf-8"))
    def script(match):
        name = match.group(2)
        paths = manifest.get(name)
        if paths is None:
            raise ValueError("unknown dashboard bundle: " + name)
        content = ""
        for filename in paths:
            if Path(filename).name != filename:
                raise ValueError("invalid dashboard source path")
            content += (root / filename).read_text(encoding="utf-8")
        return "<script>" + content + "</script>"
    text = re.sub(r'<script src="dashboard_static/([^"/]+)\.js" data-bundle="([^"]+)"></script>', script, text)
    def style(match):
        return "<style" + match.group(1) + ">" + (root / (match.group(2) + ".css")).read_text(encoding="utf-8") + "</style>"
    return re.sub(r'<link([^>]*?) rel="stylesheet" href="dashboard_static/([^"/]+)\.css">', style, text)


class DashboardAssets:
    def __init__(self, limit=64):
        self.lock = threading.Lock()
        self.stamp = None
        self.template = b""
        self.assets = collections.OrderedDict()
        self.limit = limit

    def load(self, path, version):
        stat = os.stat(path)
        inputs = Path(path).parent / "dashboard_static"
        stamps = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(inputs.glob("*")) if p.is_file())
        stamp = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size, version, stamps)
        with self.lock:
            if stamp == self.stamp:
                return
            text = source_html(path).replace("__WORKBODY_VERSION__", version)
            def externalize(match, kind):
                attrs, content = match.group(1), match.group(2)
                body = content.encode("utf-8")
                digest = hashlib.sha256(body).hexdigest()[:24]
                url = "/assets/" + digest + "." + kind
                mime = "application/javascript; charset=utf-8" if kind == "js" else "text/css; charset=utf-8"
                self.assets[url] = (body, gzip.compress(body, mtime=0), mime, digest)
                self.assets.move_to_end(url)
                if kind == "js":
                    return '<script%s src="%s"></script>' % (attrs, url)
                return '<link%s rel="stylesheet" href="%s">' % (attrs, url)
            text = re.sub(r"<style\b([^>]*)>(.*?)</style>", lambda m: externalize(m, "css"), text, flags=re.S)
            text = re.sub(r"<script\b([^>]*)>(.*?)</script>", lambda m: externalize(m, "js") if "src=" not in m.group(1) else m.group(0), text, flags=re.S)
            while len(self.assets) > self.limit:
                self.assets.popitem(last=False)
            self.template, self.stamp = text.encode("utf-8"), stamp

    def html(self, path, version, nonce):
        self.load(path, version)
        with self.lock:
            return self.template.replace(b"<script", ('<script nonce="%s"' % nonce).encode("ascii"))

    def get(self, url, path, version):
        self.load(path, version)
        with self.lock:
            return self.assets.get(url)


ASSETS = DashboardAssets()


def accepts_gzip(value):
    for part in (value or "").lower().split(","):
        name, _, options = part.strip().partition(";")
        if name == "gzip":
            match = re.search(r"q\s*=\s*([0-9.]+)", options)
            try:
                return not match or float(match.group(1)) > 0
            except ValueError:
                return False
    return False
