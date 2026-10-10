"""Verify both Docker platforms with synthetic state and no external network."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wb_version import VERSION
IMAGE = "workbody-fhub:" + VERSION
REVISION = None
READY_TIMEOUT = 60.0


def run(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode:
        # Do not print container logs: those contain temporary bootstrap keys.
        raise RuntimeError("command failed: %s\n%s" % (args[0:3], result.stderr[-2000:]))
    return result.stdout


def source_bytes(name):
    if REVISION:
        return subprocess.check_output(["git", "show", REVISION + ":" + name], cwd=ROOT)
    return (ROOT / name).read_bytes()


def expected_source():
    if REVISION:
        names = run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", REVISION]).splitlines()
        documentation = [name for name in names if name.startswith("docs/")]
        dashboard_files = [name for name in names if name.startswith("dashboard_static/")]
    else:
        names = [item.name for item in ROOT.glob("wb_*.py")]
        documentation = [str(item.relative_to(ROOT)) for item in (ROOT / "docs").rglob("*") if item.is_file()]
        dashboard_files = [str(item.relative_to(ROOT)) for item in (ROOT / "dashboard_static").glob("*") if item.is_file()]
    names = [name for name in names if "/" not in name and name.startswith("wb_") and name.endswith(".py")]
    names += ["dashboard.html", "README.md", "CHANGELOG.md", "CHANGELOG.upstream.md",
              "LICENSE", "LICENSE.upstream", "upstreams.json"] + documentation + dashboard_files
    hashes = {name: hashlib.sha256(source_bytes(name)).hexdigest() for name in names}
    if "wb_version.py" in names:
        version = re.search(r'^VERSION\s*=\s*"([^"]+)"', source_bytes("wb_version.py").decode(), re.M).group(1)
    else:
        version = re.search(r'"version"\s*:\s*"([^"]+)"', source_bytes("wb_proxy.py").decode()).group(1)
    return hashes, version


@contextmanager
def fixture_tree():
    """Use the requested release's tests as well as its source hashes."""
    if not REVISION:
        yield ROOT
        return
    with tempfile.TemporaryDirectory(prefix="workbody-image-fixtures-") as directory:
        root = Path(directory)
        archive_path = root / "fixtures.tar"
        run(["git", "-C", str(ROOT), "archive", "--format=tar", "--output", str(archive_path),
             REVISION, "tests", "scripts"])
        with tarfile.open(archive_path) as archive:
            for member in archive:
                parts = Path(member.name).parts
                if not parts or parts[0] not in ("tests", "scripts") or ".." in parts:
                    raise RuntimeError("invalid fixture archive member")
                target = root / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source:
                        target.write_bytes(source.read())
                else:
                    raise RuntimeError("fixture archive must contain ordinary files")
        yield root


def smoke(platform, non_root=False):
    name = "workbody-fhub-smoke-" + uuid.uuid4().hex[:10]
    try:
        options = (["--user", "1000:1000", "--tmpfs", "/app/accounts:uid=1000,gid=1000,mode=0700",
                    "--tmpfs", "/app/usage:uid=1000,gid=1000,mode=0700"] if non_root else [])
        run(["docker", "run", "--rm", "-d", "--platform", platform, "--network", "none",
             "--name", name] + options + [IMAGE])
        ready = '''import json, os, pathlib, time, urllib.request
deadline = time.monotonic() + READY_TIMEOUT_PLACEHOLDER
last_error = None
while time.monotonic() < deadline:
    try:
        urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=1).close()
        break
    except Exception as exc:
        last_error = {'type': type(exc).__name__, 'status': getattr(exc, 'code', None)}
        time.sleep(0.2)
else:
    directories = {}
    for name in ['/app/accounts', '/app/usage']:
        stat = pathlib.Path(name).stat()
        directories[name] = {'uid': stat.st_uid, 'gid': stat.st_gid,
                             'mode': oct(stat.st_mode & 0o777)}
    raise RuntimeError('gateway did not become ready: ' + json.dumps(
        {'uid': os.getuid(), 'last_error': last_error, 'directories': directories}))
print('ready')
'''.replace('READY_TIMEOUT_PLACEHOLDER', repr(READY_TIMEOUT))
        run(["docker", "exec", "-i", name, "python", "-"], ready)
        logs = run(["docker", "logs", name])
        match = re.search(r"PANEL BOOTSTRAP PASSWORD: ([A-Za-z0-9_-]+)", logs)
        if not match:
            raise RuntimeError("no random bootstrap password was generated")
        hashes, expected_version = expected_source()
        verify = '''import hashlib, json, os, pathlib, platform, sys, urllib.request, urllib.error
password = PASSWORD_PLACEHOLDER
expected_hashes = HASHES_PLACEHOLDER
expected_machine = MACHINE_PLACEHOLDER
expected_version = VERSION_PLACEHOLDER
expected_uid = UID_PLACEHOLDER
hardened_diagnostics = tuple(map(int, expected_version.split('.'))) >= (1, 2, 8)
assert platform.machine() == expected_machine
assert sys.version_info[:2] >= (3, 9)
assert os.getuid() == expected_uid
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
status, health = request('/health')
assert status == 200
if hardened_diagnostics:
    assert health == {'ok': True, 'service': 'workbody-fhub',
                      'version': expected_version, 'api_key_required': True}
    status, realm = request('/realm')
    assert status == 200 and realm == {'ok': True, 'version': expected_version, 'auth_required': True}
    status, panel = request('/panel/status')
    assert status == 200 and panel == {'ok': True, 'version': expected_version,
                                      'panel_password_required': True, 'authenticated': False}
assert request('/v1/models')[0] == 401
assert request('/panel/login', {'password': 'admin'})[0] == 401
status, login = request('/panel/login', {'password': password})
assert status == 200
status, settings = request('/settings', headers={'X-Panel-Token': login['token']})
assert status == 200 and settings['auth_required'] is True
assert settings['panel_password_is_default'] is False
assert settings['version'] == expected_version
status, health = request('/health', headers={'X-Panel-Token': login['token']})
assert status == 200 and health['accounts'] == 0 and 'realm' in health
stored = pathlib.Path('/app/accounts/settings.json')
assert stored.stat().st_mode & 0o777 == 0o600
stored_settings = json.loads(stored.read_text())
keys = [stored_settings.get('launcher_key'), stored_settings.get('api_key')] + [
    item.get('key') for item in stored_settings.get('api_keys', [])]
if hardened_diagnostics:
    assert any(keys), 'startup did not persist a gateway key'
    for key in keys:
        if key:
            assert key not in STARTUP_LOGS_PLACEHOLDER, 'gateway key appeared in captured startup logs'
            status, health = request('/health', headers={'Authorization': 'Bearer ' + key})
            assert status == 200 and health['accounts'] == 0 and 'realm' in health
    assert '?key=' not in STARTUP_LOGS_PLACEHOLDER
assert not pathlib.Path('/app/wb_opencode.py').exists()
assert '100% Vibe Coding' in pathlib.Path('/app/docs/credits.md').read_text()
assert 'MIT License' in pathlib.Path('/app/LICENSE.upstream').read_text()
assert 'Apache License' in pathlib.Path('/app/LICENSE').read_text()
receipt = {'health': 200, 'anonymous_api': 401, 'admin_login': 401,
                  'bootstrap_login': 200, 'authenticated_settings': 200,
                  'version': settings['version'], 'settings_mode': '0600',
                  'machine': platform.machine(), 'python': platform.python_version(),
           'uid': os.getuid(), 'source_files_verified': len(expected_hashes)}
if hardened_diagnostics:
    receipt.update({'anonymous_diagnostics': 'minimal', 'startup_api_key': 'redacted'})
print(json.dumps(receipt))
'''.replace("PASSWORD_PLACEHOLDER", repr(match.group(1))).replace(
            "HASHES_PLACEHOLDER", repr(hashes)).replace(
            "MACHINE_PLACEHOLDER", repr("x86_64" if platform == "linux/amd64" else "aarch64")).replace(
            "VERSION_PLACEHOLDER", repr(expected_version)).replace("UID_PLACEHOLDER", repr(1000 if non_root else 0)).replace(
            "STARTUP_LOGS_PLACEHOLDER", repr(logs))
        return json.loads(run(["docker", "exec", "-i", name, "python", "-"], verify))
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)


def regressions(platform):
    suites = ["ddg_search", "web_security", "web_tool_flow", "panel_bootstrap", "removed_exit", "health_auth", "project_repairs",
              "generation_speed", "account_balance", "client_balance", "free_fairness", "socks_proxy",
              "messages_web", "anthropic_http", "anthropic_messages", "gateway_hardening",
              "api_key_save_merge", "upstream_integration", "remote_catalog",
              "platforms", "platform_http", "unified_accounts", "unified_http",
              "commandcode", "response_store", "workbuddy_preserved", "audit_2026_10_11"]
    with fixture_tree() as fixtures:
        suites = [suite for suite in suites if (fixtures / "tests" / ("_test_%s.py" % suite)).exists()]
        if not suites:
            raise RuntimeError("no image regression suites found")
        command = " && ".join("python tests/_test_%s.py" % suite for suite in suites)
        run(["docker", "run", "--rm", "--platform", platform, "--network", "none",
             "--mount", "type=bind,source=%s,target=/app/tests,readonly" % (fixtures / "tests"),
             "--mount", "type=bind,source=%s,target=/app/scripts,readonly" % (fixtures / "scripts"),
             "--entrypoint", "sh", IMAGE, "-c", command])
    return suites


def main():
    global IMAGE, REVISION, READY_TIMEOUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=IMAGE)
    parser.add_argument("--revision", help="release revision for source hashes; defaults to the working tree")
    parser.add_argument("--platform", action="append", choices=["linux/amd64", "linux/arm64"])
    parser.add_argument("--pull", action="store_true", help="pull the requested platform before verification")
    parser.add_argument("--non-root", action="store_true", help="also verify UID/GID 1000 with private temporary data")
    parser.add_argument("--ready-timeout", type=float, default=READY_TIMEOUT,
                        help="seconds allowed for cold startup, including QEMU emulation (default 60)")
    args = parser.parse_args()
    IMAGE = args.image
    if not math.isfinite(args.ready_timeout) or args.ready_timeout <= 0:
        parser.error("--ready-timeout must be a positive finite number")
    READY_TIMEOUT = args.ready_timeout
    if args.revision:
        if args.revision.startswith("-"):
            parser.error("invalid revision")
        REVISION = run(["git", "-C", str(ROOT), "rev-parse", "--verify", args.revision + "^{commit}"]).strip()
    results = {"image": IMAGE, "source": REVISION or "working tree", "network": "none", "accounts": "synthetic temporary Docker data",
               "platforms": {}}
    for platform in args.platform or ("linux/amd64", "linux/arm64"):
        print("Verifying %s: root smoke and regression suites" % platform, file=sys.stderr, flush=True)
        if args.pull:
            run(["docker", "pull", "--platform", platform, IMAGE])
        results["platforms"][platform] = {"smoke": smoke(platform), "regression_suites": regressions(platform)}
        if args.non_root:
            print("Verifying %s: UID/GID 1000 smoke" % platform, file=sys.stderr, flush=True)
            results["platforms"][platform]["non_root"] = smoke(platform, non_root=True)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
