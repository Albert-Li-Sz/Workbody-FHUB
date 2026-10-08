"""Verify Nginx source, startup, proxy streaming and gzip on both image architectures.

Uses an isolated Docker network and a synthetic backend; no API calls or ACME requests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BACKEND = r'''
import json,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/events':
            self.send_response(200); self.send_header('Content-Type','text/event-stream')
            self.send_header('X-Accel-Buffering','no'); self.send_header('Connection','close'); self.end_headers()
            self.wfile.write(b'data: first\n\n'); self.wfile.flush()
            time.sleep(1.5)
            self.wfile.write(b': heartbeat\n\ndata: second\n\n'); self.wfile.flush()
            self.close_connection=True
        else:
            body=b'var cached_asset=true;\n'*300 if self.path.startswith('/assets/') else b'{"ok":true}'
            self.send_response(200); self.send_header('Content-Type','application/javascript' if self.path.startswith('/assets/') else 'application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
ThreadingHTTPServer(('0.0.0.0',8788),Handler).serve_forever()
'''
PROBE = r'''
import gzip,json,time,urllib.request
base='http://127.0.0.1'
assert urllib.request.urlopen(base+'/nginx-health',timeout=5).read()==b'ok\n'
assert json.load(urllib.request.urlopen(base+'/health',timeout=5))['ok'] is True
assert json.load(urllib.request.urlopen(base+'/tls/status',timeout=5))['status']=='disabled'
begin=time.monotonic()
response=urllib.request.urlopen(urllib.request.Request(base+'/events',headers={'Accept-Encoding':'gzip'}),timeout=5)
assert not response.headers.get('Content-Encoding'),dict(response.headers)
assert response.headers.get('X-Accel-Buffering')=='no',dict(response.headers)
assert response.readline()==b'data: first\n'
first=time.monotonic()-begin
assert first<1.4,('first frame buffered',first)
remaining=response.read()
assert b': heartbeat' in remaining and b'data: second' in remaining
asset=urllib.request.urlopen(urllib.request.Request(base+'/assets/synthetic.js',headers={'Accept-Encoding':'gzip'}),timeout=5)
assert asset.headers.get('Content-Encoding')=='gzip',dict(asset.headers)
assert gzip.decompress(asset.read()).startswith(b'var cached_asset=true;')
print(json.dumps({'stream_first_frame_seconds':round(first,3),'heartbeat':True,'sse_gzip':False,'asset_gzip':True,'tls':'disabled'}))
'''


def run(command, timeout=180):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("command failed: %s\n%s" % (" ".join(command[:6]), result.stderr[-2500:]))
    return result.stdout.strip()


def verify(image, backend_image, platform, expected):
    suffix = uuid.uuid4().hex[:12]
    network, backend, gateway = ["wb-nginx-check-" + suffix + "-" + item for item in ("network", "backend", "gateway")]
    run(["docker", "network", "create", "--internal", network])
    try:
        run(["docker", "run", "-d", "--name", backend, "--platform", platform, "--network", network,
             "--entrypoint", "python", backend_image, "-u", "-c", BACKEND])
        run(["docker", "run", "-d", "--name", gateway, "--platform", platform, "--network", network,
             "-e", "WB_TLS_MODE=off", "-e", "WB_NGINX_UPSTREAM=" + backend + ":8788", image])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                run(["docker", "exec", gateway, "python3", "-c",
                     "import urllib.request;urllib.request.urlopen('http://127.0.0.1/nginx-health',timeout=2)"], timeout=10)
                break
            except (RuntimeError, subprocess.TimeoutExpired):
                time.sleep(1)
        else:
            raise RuntimeError("nginx startup timed out: " + run(["docker", "logs", gateway]))
        run(["docker", "exec", gateway, "nginx", "-t"])
        digest = run(["docker", "exec", gateway, "python3", "-c",
                      "import hashlib;print(hashlib.sha256(open('/opt/workbody/gateway.py','rb').read()).hexdigest())"])
        if digest != expected:
            raise RuntimeError("nginx image source differs from requested revision")
        certbot = run(["docker", "exec", gateway, "certbot", "--version"])
        result = json.loads(run(["docker", "exec", gateway, "python3", "-c", PROBE], timeout=20))
        result.update(source_sha256=digest, certbot=certbot, configuration=True)
        return result
    finally:
        for name in (gateway, backend):
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--platform", action="append", choices=["linux/amd64", "linux/arm64"])
    parser.add_argument("--pull", action="store_true")
    args = parser.parse_args()
    revision = None
    if args.revision:
        if args.revision.startswith("-"):
            parser.error("invalid Git revision")
        revision = subprocess.check_output(["git", "rev-parse", "--verify", args.revision + "^{commit}"], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(["git", "show", revision + ":deploy/nginx/gateway.py"], cwd=ROOT) if revision else (ROOT / "deploy/nginx/gateway.py").read_bytes()
    results = {"image": args.image, "source": revision or "working tree", "platforms": {}}
    for platform in args.platform or ("linux/amd64", "linux/arm64"):
        if args.pull:
            for image in (args.image, args.app_image):
                run(["docker", "pull", "--platform", platform, image])
        results["platforms"][platform] = verify(args.image, args.app_image, platform, hashlib.sha256(source).hexdigest())
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
