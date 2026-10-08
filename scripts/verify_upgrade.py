"""Exercise real Compose upgrade/rollback and native source migration with synthetic data.

Local images and an exact packaged source archive are required. Only release download
and docker pull are replaced with local fixtures; backup, SQL migration, startup and
rollback use the actual updater and Docker processes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import update
import wb_settings
from wb_version import VERSION
from scripts.package_release import package

PASSWORD = "synthetic-upgrade-password"
KEY = "synthetic-upgrade-api-key"


def extract_source(archive, directory):
    with tarfile.open(archive) as source:
        for member in source:
            parts = Path(member.name).parts[1:]
            if not parts:
                continue
            target = directory.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.extractfile(member).read())
                target.chmod(member.mode & 0o777)


def seed(directory):
    accounts, usage = directory / "accounts", directory / "usage"
    accounts.mkdir(exist_ok=True); usage.mkdir(exist_ok=True)
    (accounts / "fixture.json").write_text(json.dumps({"uid":"fixture-account", "nickname":"Fixture",
        "realm":"cn", "accessToken":"synthetic-not-a-real-token", "enabled":False, "priority":7}))
    wb_settings.set_panel_password(str(accounts), PASSWORD)
    wb_settings.set_api_keys(str(accounts), [{"id":"fixture-key", "name":"Fixture", "key":KEY, "realm":"cn"}])
    row = {"event_id":"fixture-usage", "at":time.time()-10, "realm":"cn", "account":"fixture-account",
           "key":"fixture-key", "model":"fixture-model", "outcome":"completed", "total_tokens":123,
           "prompt_tokens":100, "completion_tokens":23, "credit":0, "billing_mode":"free"}
    (usage / "usage.jsonl").write_text(json.dumps(row) + "\n")


def assert_data(directory, schema):
    accounts = directory / "accounts"
    settings = wb_settings.load(str(accounts))
    assert settings["api_keys"][0]["key"] == KEY
    assert wb_settings.verify_panel_password(str(accounts), PASSWORD)
    account = json.loads((accounts / "fixture.json").read_text())
    assert account["priority"] == 7 and account["enabled"] is False
    connection = sqlite3.connect(accounts / "workbody.sqlite3")
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == schema
        assert connection.execute("SELECT SUM(total_tokens),COUNT(*) FROM usage_records").fetchone() == (123,1)
        if schema == 2:
            assert connection.execute("SELECT SUM(total_tokens) FROM usage_hourly").fetchone()[0] == 123
    finally:
        connection.close()


def arguments(directory, **options):
    values = dict(directory=str(directory),version=VERSION,compose_file=[],service=None,https=False,
                  tls_mode="auto",public_ip=None,domains=None,acme_email=None,source_only=False,
                  dry_run=False,timeout=60,rollback=None)
    values.update(options)
    return SimpleNamespace(**values)


def compose_case(old_version, new_image, old_image, root):
    directory = root / ("compose-" + old_version)
    directory.mkdir()
    old_assets = root / ("old-assets-" + old_version)
    package("v"+old_version, old_assets)
    extract_source(old_assets / ("workbody-fhub-%s-source.tar.gz" % old_version), directory)
    seed(directory)
    project = "wb-upgrade-check-" + uuid.uuid4().hex[:10]
    model = {"name":project,"services":{"workbody-fhub":{"image":old_image,"pull_policy":"never",
        "network_mode":"none", "environment":{"HOST":"0.0.0.0","PORT":"8788","PANEL_PASSWORD":PASSWORD},
        "volumes":[str(directory/"accounts")+":/app/accounts",str(directory/"usage")+":/app/usage"]}}}
    if old_version == "1.1.1":
        model["services"]["workbody-fhub"].pop("network_mode")
        model["networks"] = {"default":{"internal":True}}
        for name in (".tls", ".acme"):
            (directory/name).mkdir()
        model["services"]["nginx"] = {"image":"ghcr.io/albert-li-sz/workbody-fhub-nginx:v1.1.1",
            "pull_policy":"never", "environment":{"WB_TLS_MODE":"off","WB_NGINX_UPSTREAM":"workbody-fhub:8788"},
            "volumes":[str(directory/".tls")+":/etc/letsencrypt",str(directory/".acme")+":/var/lib/letsencrypt"]}
    compose = directory / "compose.fixture.json"
    compose.write_text(json.dumps(model))
    command = update.compose_command(directory, [compose])
    try:
        update.run(command+["up","-d","--pull","never"],directory)
        update.wait_application(command,"workbody-fhub",directory,old_version,60)
        assert_data(directory,1)
        update.upgrade(arguments(directory,compose_file=[str(compose)]))
        assert_data(directory,2)
        runtime = update.compose_command(directory,[directory/update.RUNTIME_FILE])
        if old_version == "1.1.1":
            assert update.wait_gateway(runtime,"nginx",directory,VERSION,30)["status"] == "disabled"
        backups = list((directory/".update-backups").iterdir())
        assert len(backups) == 1
        update.rollback(arguments(directory,rollback=str(backups[0])))
        update.wait_application(update.compose_command(directory,[backups[0]/"rollback-compose.json"]),
                                "workbody-fhub",directory,old_version,60)
        assert_data(directory,1)
        print("Verified Compose %s -> %s -> rollback; priority/key/password/123 tokens preserved." % (old_version,VERSION))
    finally:
        update.run(["docker","compose","-p",project,"-f",str(compose),"down","--remove-orphans"],directory)


def native_case(root):
    directory=root/"native";directory.mkdir()
    assets=root/"native-old-assets";package("v1.1.0",assets)
    extract_source(assets/"workbody-fhub-1.1.0-source.tar.gz",directory)
    seed(directory)
    update.upgrade(arguments(directory,source_only=True))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1",0));port=listener.getsockname()[1]
    env=dict(os.environ,ACCOUNTS_DIR=str(directory/"accounts"),WB_PROXY_USAGE_DIR=str(directory/"usage"))
    with tempfile.TemporaryFile() as output:
        process=subprocess.Popen([sys.executable,str(directory/"wb_proxy.py"),"--host","127.0.0.1","--port",str(port)],
                                 cwd=directory,env=env,stdout=output,stderr=output)
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try:
                    result=json.load(urllib.request.urlopen("http://127.0.0.1:%d/health"%port,timeout=2))
                    if result.get("version")==VERSION: break
                except OSError: pass
                time.sleep(0.2)
            else: raise RuntimeError("native upgraded gateway failed to start")
            assert_data(directory,2)
            assert (directory/"dashboard_static"/"bundles.json").exists()
            print("Verified native 1.1.0 -> %s startup and persisted data."%VERSION)
        finally:
            process.terminate();process.wait(timeout=10)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",required=True)
    parser.add_argument("--image",default="workbody-fhub:"+VERSION)
    parser.add_argument("--nginx-image",default="workbody-fhub-nginx:"+VERSION)
    args=parser.parse_args()
    archive=Path(args.archive).read_bytes()
    name="workbody-fhub-%s-source.tar.gz"%VERSION
    release={"tag_name":"v"+VERSION,"assets":[{"name":asset,"browser_download_url":"https://github.com/fixtures/"+asset}
             for asset in (name,"checksums.txt")]}
    original_download,original_run,original_registry=update.download,update.run,update.REGISTRY
    local_image="workbody-upgrade-fixture/workbody-fhub:"+VERSION
    update.run(["docker","tag",args.image,local_image])
    local_nginx="workbody-upgrade-fixture/workbody-fhub-nginx:"+VERSION
    update.run(["docker","tag",args.nginx_image,local_nginx])
    def download(url,maximum=update.MAX_DOWNLOAD):
        if "/releases/tags/" in url: return json.dumps(release).encode()
        if url.endswith("checksums.txt"):return (hashlib.sha256(archive).hexdigest()+"  "+name+"\n").encode()
        if url.endswith(name):return archive
        raise AssertionError("unexpected release download")
    def run(command,*pos,**kwargs):
        if command[:2]==["docker","pull"]:
            original_run(["docker","image","inspect",command[2]])
            return "local synthetic image fixture"
        return original_run(command,*pos,**kwargs)
    try:
        update.download=download;update.run=run;update.REGISTRY="workbody-upgrade-fixture"
        with tempfile.TemporaryDirectory(prefix="workbody-migration-check-") as temporary:
            root=Path(temporary)
            native_case(root)
            for version in ("1.1.0","1.1.1"):
                compose_case(version,args.image,"workbody-fhub:"+version,root)
    finally:
        update.download,update.run,update.REGISTRY=original_download,original_run,original_registry
        subprocess.run(["docker","image","rm",local_image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(["docker","image","rm",local_nginx],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=="__main__":main()
