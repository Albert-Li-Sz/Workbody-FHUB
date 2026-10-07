"""Verify both Docker platforms with synthetic state and no external network."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "workbody-fhub:1.0.0"


def run(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode:
        # Do not print container logs: those contain temporary bootstrap keys.
        raise RuntimeError("command failed: %s\n%s" % (args[0:3], result.stderr[-2000:]))
    return result.stdout


def smoke(platform):
    name = "workbody-fhub-smoke-" + uuid.uuid4().hex[:10]
    try:
        run(["docker", "run", "--rm", "-d", "--platform", platform, "--network", "none",
             "--name", name, IMAGE])
        ready = '''import time, urllib.request
for attempt in range(100):
    try:
        urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=1).close()
        break
    except Exception:
        time.sleep(0.1)
else:
    raise RuntimeError('gateway did not become ready')
print('ready')
'''
        run(["docker", "exec", "-i", name, "python", "-"], ready)
        logs = run(["docker", "logs", name])
        match = re.search(r"PANEL BOOTSTRAP PASSWORD: ([A-Za-z0-9_-]+)", logs)
        if not match:
            raise RuntimeError("no random bootstrap password was generated")
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in [*ROOT.glob("wb_*.py"), ROOT / "dashboard.html", ROOT / "README.md", ROOT / "LICENSE", ROOT / "LICENSE.upstream"]}
        verify = '''import hashlib, json, os, pathlib, platform, sys, urllib.request, urllib.error
password = PASSWORD_PLACEHOLDER
expected_hashes = HASHES_PLACEHOLDER
expected_machine = MACHINE_PLACEHOLDER
assert platform.machine() == expected_machine
assert sys.version_info[:2] == (3, 11)
for name, digest in expected_hashes.items():
    assert hashlib.sha256(pathlib.Path('/app', name).read_bytes()).hexdigest() == digest, name
base = 'http://127.0.0.1:8788'
def request(path, payload=None, headers=None):
    req = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
        headers=dict({'Content-Type': 'application/json'}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)
assert request('/health')[0] == 200
assert request('/v1/models')[0] == 401
assert request('/panel/login', {'password': 'admin'})[0] == 401
status, login = request('/panel/login', {'password': password})
assert status == 200
status, settings = request('/settings', headers={'X-Panel-Token': login['token']})
assert status == 200 and settings['auth_required'] is True
assert settings['panel_password_is_default'] is False
assert settings['version'] == '1.0.0'
stored = pathlib.Path('/app/accounts/settings.json')
assert stored.stat().st_mode & 0o777 == 0o600
assert not pathlib.Path('/app/wb_opencode.py').exists()
assert '100% Vibe Coding' in pathlib.Path('/app/README.md').read_text()
assert 'MIT License' in pathlib.Path('/app/LICENSE.upstream').read_text()
assert 'Apache License' in pathlib.Path('/app/LICENSE').read_text()
print(json.dumps({'health': 200, 'anonymous_api': 401, 'admin_login': 401,
                  'bootstrap_login': 200, 'authenticated_settings': 200,
                  'version': settings['version'], 'settings_mode': '0600',
                  'machine': platform.machine(), 'python': platform.python_version(),
                  'source_files_verified': len(expected_hashes)}))
'''.replace("PASSWORD_PLACEHOLDER", repr(match.group(1))).replace(
            "HASHES_PLACEHOLDER", repr(hashes)).replace(
            "MACHINE_PLACEHOLDER", repr("x86_64" if platform == "linux/amd64" else "aarch64"))
        return json.loads(run(["docker", "exec", "-i", name, "python", "-"], verify))
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


def regressions(platform):
    suites = ["ddg_search", "web_security", "web_tool_flow", "panel_bootstrap", "removed_exit", "health_auth"]
    command = " && ".join("python tests/_test_%s.py" % suite for suite in suites)
    run(["docker", "run", "--rm", "--platform", platform, "--network", "none",
         "--mount", "type=bind,source=%s,target=/app/tests,readonly" % (ROOT / "tests"),
         "--mount", "type=bind,source=%s,target=/app/scripts,readonly" % (ROOT / "scripts"),
         "--entrypoint", "sh", IMAGE, "-c", command])
    return suites


def main():
    results = {"image": IMAGE, "network": "none", "accounts": "synthetic anonymous Docker volumes",
               "platforms": {}}
    for platform in ("linux/amd64", "linux/arm64"):
        results["platforms"][platform] = {"smoke": smoke(platform), "regression_suites": regressions(platform)}
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
