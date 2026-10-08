#!/usr/bin/env python3
"""Upgrade an existing installation, preserving its runtime configuration."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid

VERSION = "1.1.1"
REPOSITORY = "Albert-Li-Sz/Workbody-FHUB"
REGISTRY = "ghcr.io/albert-li-sz"
RUNTIME_FILE = "compose.runtime.json"
BACKUPS = ".update-backups"
EXCLUDED = {"accounts", "usage", ".tls", ".acme", ".git", BACKUPS,
            RUNTIME_FILE, ".env", ".update.lock", "docker-compose.override.yml",
            "docker-compose.override.yaml", "compose.override.yml", "compose.override.yaml"}
MAX_DOWNLOAD = 64 * 1024 * 1024


class UpgradeError(RuntimeError):
    pass


def say(message):
    print("[update] " + message, flush=True)


def run(arguments, directory=None, input_text=None, timeout=300):
    """Capture configuration output; never print environment values or logs."""
    result = subprocess.run(arguments, cwd=directory, input=input_text, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise UpgradeError("%s 执行失败（退出码 %s）；请在服务器终端检查该操作。" %
                           (" ".join(arguments[:2]), result.returncode))
    return result.stdout


def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, data):
    private_write(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def download(url, maximum=MAX_DOWNLOAD):
    if not url.startswith(("https://github.com/", "https://api.github.com/")):
        raise UpgradeError("拒绝非 GitHub 发布地址。")
    request = urllib.request.Request(url, headers={"User-Agent": "Workbody-FHUB-updater/" + VERSION})
    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise UpgradeError("发布附件超过允许大小。")
    return content


def release_source(version, destination):
    tag = "v" + version
    release = json.loads(download("https://api.github.com/repos/%s/releases/tags/%s" %
                                  (REPOSITORY, tag), 2 * 1024 * 1024))
    if release.get("draft") or release.get("prerelease") or release.get("tag_name") != tag:
        raise UpgradeError("需要已发布的正式版本。")
    assets = {item["name"]: item["browser_download_url"] for item in release.get("assets", [])}
    name = "workbody-fhub-%s-source.tar.gz" % version
    if name not in assets or "checksums.txt" not in assets:
        raise UpgradeError("该版本缺少源码附件或 checksums.txt。")
    checksums = download(assets["checksums.txt"], 1024 * 1024).decode()
    expected = None
    for line in checksums.splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?(.+)", line)
        if match and match[2] == name:
            expected = match[1].lower()
    archive = download(assets[name])
    if not expected or hashlib.sha256(archive).hexdigest() != expected:
        raise UpgradeError("源码附件校验失败，未修改安装目录。")
    files, expanded = [], 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        members = source.getmembers()
        prefixes = {PurePosixPath(item.name).parts[0] for item in members if item.name}
        if len(prefixes) != 1:
            raise UpgradeError("发布归档必须只有一个顶层目录。")
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or ".." in parts or member.name.startswith("/")
                    or "\\" in member.name or ":" in member.name):
                raise UpgradeError("源码归档包含非法路径。")
            if not member.isdir() and not member.isfile():
                raise UpgradeError("源码归档不能包含符号链接或设备文件。")
            if len(parts) < 2 or member.isdir():
                continue
            relative = Path(*parts[1:])
            if (relative.parts[0] in EXCLUDED or relative.parts[0].startswith(".env.")
                    or relative.parts[0] in ("logs", "python", "dist")):
                raise UpgradeError("发布归档包含运行时私有数据。")
            expanded += member.size
            if expanded > 128 * 1024 * 1024 or len(files) >= 10000:
                raise UpgradeError("源码归档展开后超过允许大小。")
            target = destination / relative
            if target.exists():
                raise UpgradeError("源码归档包含重复文件。")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as content, target.open("wb") as output:
                shutil.copyfileobj(content, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            files.append(relative.as_posix())
    text = (destination / "wb_version.py").read_text(encoding="utf-8")
    if not re.search(r'^VERSION\s*=\s*"' + re.escape(version) + r'"$', text, re.M):
        raise UpgradeError("源码版本与发布标签不符。")
    return files


def compose_command(directory, filenames):
    command = ["docker", "compose", "--project-directory", str(directory)]
    for filename in filenames:
        command.extend(["-f", str(filename)])
    return command


def existing_compose_files(directory, supplied):
    if supplied:
        files = [Path(name) if Path(name).is_absolute() else directory / name for name in supplied]
    elif (directory / RUNTIME_FILE).is_file():
        files = [directory / RUNTIME_FILE]
    else:
        configured = os.environ.get("COMPOSE_FILE", "")
        if not configured and (directory / ".env").is_file():
            for line in (directory / ".env").read_text(encoding="utf-8").splitlines():
                match = re.fullmatch(r'\s*(?:export\s+)?COMPOSE_FILE\s*=\s*(.*?)\s*', line)
                if match:
                    configured = match[1].strip("\"'")
        if configured:
            if "$" in configured or " #" in configured:
                raise UpgradeError("COMPOSE_FILE 包含变量或注释，请用 --compose-file 明确指定每个配置文件。")
            separator = os.environ.get("COMPOSE_PATH_SEPARATOR", os.pathsep)
            files = [Path(name) if Path(name).is_absolute() else directory / name
                     for name in configured.split(separator) if name]
            if not files or any(not path.is_file() for path in files):
                raise UpgradeError("COMPOSE_FILE 指定的配置文件不存在。")
            return files
        base = next((directory / name for name in ("compose.yaml", "compose.yml",
                    "docker-compose.yml", "docker-compose.yaml") if (directory / name).is_file()), None)
        if base is None:
            raise UpgradeError("找不到 Compose 配置；原生 Python 安装请使用 --source-only。")
        files = [base]
        override_names = ("compose.override.yaml", "compose.override.yml",
                          "docker-compose.override.yml", "docker-compose.override.yaml")
        override = next((directory / name for name in override_names if (directory / name).is_file()), None)
        if override:
            files.append(override)
    if any(not path.is_file() for path in files):
        raise UpgradeError("指定的 Compose 文件不存在。")
    return files


def app_service(model, requested):
    services = model.get("services") or {}
    if requested:
        if requested not in services:
            raise UpgradeError("指定的应用服务不存在。")
        return requested
    candidates = [name for name, cfg in services.items()
                  if "workbody-fhub-nginx" not in str(cfg.get("image", ""))
                  and ("workbody-fhub" in str(cfg.get("image", ""))
                       or "workbuddy2api-hub" in str(cfg.get("image", ""))
                       or name in ("workbody-fhub", "workbuddy2api-hub"))]
    if len(candidates) != 1:
        raise UpgradeError("无法唯一识别网关服务；使用 --service 指定服务名。")
    return candidates[0]


def app_port(config):
    value = (config.get("environment") or {}).get("PORT") or 8788
    command = config.get("command") or []
    if isinstance(command, str):
        command = shlex.split(command)
    for index, item in enumerate(command):
        if item == "--port" and index + 1 < len(command):
            value = command[index + 1]
        elif str(item).startswith("--port="):
            value = str(item).split("=", 1)[1]
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise UpgradeError("无法识别应用监听端口。") from None
    if not 1 <= port <= 65535:
        raise UpgradeError("应用端口超出范围。")
    return port


def managed_nginx(model):
    return [name for name, cfg in model["services"].items()
            if "workbody-fhub-nginx" in str(cfg.get("image", ""))]


def deployment_model(old, app, version, args, directory):
    model = copy.deepcopy(old)
    cfg = model["services"][app]
    cfg["image"] = REGISTRY + "/workbody-fhub:" + version
    cfg.pop("build", None)
    cfg.pop("pull_policy", None)
    nginx_services = managed_nginx(old)
    for name in nginx_services:
        nginx = model["services"][name]
        nginx["image"] = REGISTRY + "/workbody-fhub-nginx:" + version
        nginx.pop("build", None)
        nginx.pop("pull_policy", None)
    if args.https and not nginx_services:
        if "nginx" in model["services"]:
            raise UpgradeError("已有非本项目的 nginx 服务；请继续使用原反代或先单独调整配置。")
        if cfg.get("network_mode"):
            raise UpgradeError("--https 需要普通 Compose 网络，当前服务使用了 network_mode。")
        port = app_port(cfg)
        if any(int(p["target"]) != port for p in cfg.get("ports") or []):
            raise UpgradeError("--https 不能自动调整多端口应用，请先整理端口映射。")
        cfg["ports"] = [{"target": port, "published": "8788", "host_ip": "127.0.0.1", "protocol": "tcp"}]
        network_names = list(cfg.get("networks") or {"default": None})
        nginx = {
            "image": REGISTRY + "/workbody-fhub-nginx:" + version,
            "restart": "unless-stopped", "stop_grace_period": "30s",
            "depends_on": {app: {"condition": "service_started"}},
            "ports": [{"target": 80, "published": "80", "protocol": "tcp"},
                      {"target": 443, "published": "443", "protocol": "tcp"}],
            "environment": {"TZ": "Asia/Shanghai", "WB_TLS_MODE": "auto",
                            "WB_NGINX_UPSTREAM": "%s:%d" % (app, port)},
            "networks": {name: None for name in network_names},
            "volumes": [{"type": "bind", "source": str(directory / ".tls"), "target": "/etc/letsencrypt"},
                        {"type": "bind", "source": str(directory / ".acme"), "target": "/var/lib/letsencrypt"}]
        }
        model["services"]["nginx"] = nginx
        nginx_services = ["nginx"]
    if args.https:
        for name in nginx_services:
            env = model["services"][name].setdefault("environment", {})
            env["WB_TLS_MODE"] = "domain" if args.tls_mode == "domain" else "auto"
            for key, value in (("WB_PUBLIC_IP", args.public_ip), ("WB_TLS_DOMAINS", args.domains),
                               ("WB_ACME_EMAIL", args.acme_email)):
                if value is not None:
                    env[key] = value
    return model, [app] + nginx_services


def container_for(command, service, directory):
    ids = run(command + ["ps", "-a", "-q", service], directory).split()
    if len(ids) > 1:
        raise UpgradeError("迁移脚本仅支持单实例，不能迁移多副本网关。")
    return json.loads(run(["docker", "inspect", ids[0]]))[0] if ids else None


def persistent_mounts(containers):
    mounts, seen = [], set()
    for container in containers.values():
        if container is None:
            continue
        for mount in container.get("Mounts", []):
            if not mount.get("RW", True) or mount["Type"] not in ("bind", "volume"):
                continue
            source = mount.get("Name") if mount["Type"] == "volume" else mount["Source"]
            key = (mount["Type"], source)
            if key not in seen:
                mounts.append({"type": mount["Type"], "source": source,
                               "destination": mount["Destination"]})
                seen.add(key)
    return mounts


def pin_container_mounts(model, containers):
    """Preserve actual volumes, including anonymous Dockerfile VOLUMEs."""
    model = copy.deepcopy(model)
    aliases = {}
    for name, container in containers.items():
        if not container:
            continue
        cfg = model["services"][name]
        volumes = {volume["target"]: volume for volume in cfg.get("volumes") or []}
        for mount in container.get("Mounts", []):
            if mount["Type"] not in ("bind", "volume"):
                continue
            target = mount["Destination"]
            volume = copy.deepcopy(volumes.get(target) or {})
            volume.update(type=mount["Type"], target=target, read_only=not mount.get("RW", True))
            if mount["Type"] == "bind":
                volume["source"] = mount["Source"]
            else:
                source = mount["Name"]
                if source not in aliases:
                    alias = "workbody_preserved_" + hashlib.sha256(source.encode()).hexdigest()[:12]
                    aliases[source] = alias
                    model.setdefault("volumes", {})[alias] = {"external": True, "name": source}
                volume["source"] = aliases[source]
            volumes[target] = volume
        cfg["volumes"] = list(volumes.values())
    return model


def require_persisted_data(container):
    config = container.get("Config") or {}
    environment = dict(item.split("=", 1) for item in config.get("Env") or [] if "=" in item)
    paths = {"--accounts-dir": environment.get("ACCOUNTS_DIR") or "/app/accounts",
             "--usage-dir": environment.get("WB_PROXY_USAGE_DIR") or "/app/usage"}
    command = config.get("Cmd") or []
    for index, item in enumerate(command):
        flag, _, value = item.partition("=")
        if flag in paths:
            paths[flag] = value or (command[index + 1] if index + 1 < len(command) else paths[flag])
    if environment.get("WB_SQLITE_PATH"):
        paths["WB_SQLITE_PATH"] = posixpath.dirname(environment["WB_SQLITE_PATH"]) or "."
    for label, path in paths.items():
        path = posixpath.normpath(posixpath.join(config.get("WorkingDir") or "/app", path))
        if not any(mount["Type"] in ("bind", "volume") and mount.get("RW", True)
                   and (path == mount["Destination"] or path.startswith(mount["Destination"].rstrip("/") + "/"))
                   for mount in container.get("Mounts", [])):
            raise UpgradeError(label + " 指向容器内未持久化的数据，尚未停止服务；请先迁移该目录到数据卷。")


# This helper has no network access. Docker can read root-owned bind mounts and
# named volumes without making private account data world-readable on the host.
DATA_HELPER = r'''
import copy, os, pathlib, shutil, sys, tarfile
operation, count, prefix, uid, gid = sys.argv[1:]
def backup_filter(member):
    if ".update-backups" in pathlib.PurePosixPath(member.name).parts:
        return None
    # Reject unsupported special files and escaping links before an upgrade
    # can change data that would then be impossible to restore safely.
    tarfile.data_filter(member, str(path))
    return member
def restore_filter(member, destination):
    safe = copy.copy(tarfile.data_filter(member, destination))
    safe.uid, safe.gid = member.uid, member.gid
    safe.uname = safe.gname = None
    safe.mode = member.mode & 0o777
    return safe
for index in range(int(count)):
    path = pathlib.Path("/data", str(index))
    archive = pathlib.Path("/backup", prefix + "-%03d.tar.gz" % index)
    if operation == "save":
        with tarfile.open(archive, "w:gz", dereference=False) as target:
            target.add(path, arcname=".", recursive=True, filter=backup_filter)
        os.chmod(archive, 0o600)
        if int(uid) >= 0:
            os.chown(archive, int(uid), int(gid))
    else:
        if path.is_dir():
            with tarfile.open(archive) as source:
                for member in source:
                    restore_filter(member, str(path))
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            with tarfile.open(archive) as source:
                source.extractall(path, filter=restore_filter, numeric_owner=True)
        else:
            with tarfile.open(archive) as source:
                item = source.getmember(".")
                with source.extractfile(item) as content, path.open("wb") as output:
                    shutil.copyfileobj(content, output)
'''


def mount_operation(image, backup, mounts, operation, prefix="data"):
    if not mounts:
        return
    if "," in str(backup):
        raise UpgradeError("备份路径包含逗号，需更换安装目录或手动迁移。")
    command = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE", "--cap-add", "CHOWN",
               "--cap-add", "FOWNER", "--security-opt", "no-new-privileges",
               "--entrypoint", "python", "--mount", "type=bind,source=%s,target=/backup" % backup]
    for index, mount in enumerate(mounts):
        if "," in mount["source"]:
            raise UpgradeError("数据挂载路径包含逗号，需手动备份后迁移。")
        command.extend(["--mount", "type=%s,source=%s,target=/data/%d%s" %
                        (mount["type"], mount["source"], index, ",readonly" if operation == "save" else "")])
    uid = os.getuid() if hasattr(os, "getuid") else -1
    gid = os.getgid() if hasattr(os, "getgid") else -1
    command.extend([image, "-", operation, str(len(mounts)), prefix, str(uid), str(gid)])
    run(command, input_text=DATA_HELPER, timeout=None)


def archive_source(directory, files, backup):
    existing = []
    with tarfile.open(backup / "source.tar.gz", "w:gz") as target:
        for name in files:
            path = directory / name
            # Refuse symlinks even in a parent directory of a source file.
            if any(parent.is_symlink() for parent in [path] + list(path.parents) if parent != directory.parent):
                raise UpgradeError("源码目录包含符号链接，请先整理后迁移。")
            if path.exists():
                if not path.is_file():
                    raise UpgradeError("源码文件被同名目录占用：" + name)
                target.add(path, arcname=name, recursive=False)
                existing.append(name)
    (backup / "source.tar.gz").chmod(0o600)
    return existing


def install_source(directory, staging, files):
    for name in files:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".update-tmp")
        shutil.copyfile(staging / name, temporary)
        temporary.chmod((staging / name).stat().st_mode & 0o777)
        os.replace(temporary, target)


def restore_source(directory, files, existing, backup):
    for name in set(files) - set(existing):
        (directory / name).unlink(missing_ok=True)
    with tarfile.open(backup / "source.tar.gz") as source:
        for member in source:
            path = directory / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as content:
                private_write(path, content.read())
            path.chmod(member.mode & 0o777)


def wait_application(command, app, directory, version, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container = container_for(command, app, directory)
        if container and container["State"].get("Running"):
            port = app_port(json.loads(run(command + ["config", "--format", "json"], directory))["services"][app])
            probe = ("import json,urllib.request; "
                     "r=json.load(urllib.request.urlopen('http://127.0.0.1:%d/health',timeout=3)); "
                     "print(r.get('version',''))") % port
            try:
                found = run(["docker", "exec", container["Id"], "python", "-c", probe], timeout=10).strip()
                if found == version:
                    return container
            except (UpgradeError, subprocess.TimeoutExpired):
                pass
        time.sleep(2)
    raise UpgradeError("新应用未在指定时间内返回版本 %s，将回退。" % version)


def source_only(directory, staging, files, backup):
    existing = archive_source(directory, files, backup)
    roots = [directory / name for name in ("accounts", "usage", ".tls", ".acme") if (directory / name).exists()]
    with tarfile.open(backup / "native-data.tar.gz", "w:gz", dereference=False) as target:
        for path in roots:
            target.add(path, arcname=path.name)
    (backup / "native-data.tar.gz").chmod(0o600)
    write_json(backup / "state.json", {"mode": "source", "directory": str(directory),
               "files": files, "existing": existing})
    try:
        install_source(directory, staging, files)
    except Exception:
        restore_source(directory, files, existing, backup)
        raise
    say("源码已更新。请使用原启动方式重新启动；首次启动自动导入 SQLite。")


def upgrade(args):
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        raise UpgradeError("安装目录不存在。")
    version = args.version.removeprefix("v") if sys.version_info >= (3, 9) else args.version.lstrip("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise UpgradeError("版本应为 1.1.1 或 v1.1.1 形式。")
    with tempfile.TemporaryDirectory(prefix="workbody-update-") as temporary:
        staging = Path(temporary)
        say("下载 v%s 的源码和校验文件。" % version)
        files = release_source(version, staging)
        if args.source_only:
            say("原生安装：更新源码，保留账号和配置；执行前请停止原 Python 进程。")
            if args.dry_run:
                say("仅查看：将覆盖 %d 个源码文件，升级前备份 accounts/usage 及原源码。" % len(files))
                return
            backup = create_backup(directory)
            source_only(directory, staging, files, backup)
            say("备份：" + str(backup))
            return
        run(["docker", "compose", "version"], timeout=30)
        context = json.loads(run(["docker", "context", "inspect"]))[0]
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not endpoint.startswith(("unix://", "npipe://")) or os.environ.get("DOCKER_HOST", "").startswith(("tcp:", "ssh:")):
            raise UpgradeError("请在 Docker 所在服务器本地执行迁移，不能使用远程 Docker context。")
        original_files = existing_compose_files(directory, args.compose_file)
        old_command = compose_command(directory, original_files)
        old_model = json.loads(run(old_command + ["config", "--format", "json"], directory))
        app = app_service(old_model, args.service)
        old_managed = [app] + managed_nginx(old_model)
        containers = {name: container_for(old_command, name, directory) for name in old_managed}
        mounts = persistent_mounts(containers)
        if containers[app] is None:
            raise UpgradeError("没有找到现有应用容器；首次安装请直接使用 docker compose up -d。")
        require_persisted_data(containers[app])
        old_model = pin_container_mounts(old_model, containers)
        new_model, managed = deployment_model(old_model, app, version, args, directory)
        for mount in mounts:
            if "," in mount["source"] or "," in str(directory):
                raise UpgradeError("安装或数据挂载路径包含逗号，需手动备份后迁移。")
            if mount["destination"] in ("/", "/app"):
                raise UpgradeError("整个 /app 或根目录被挂载，需先拆分源码与数据目录再迁移。")
            if mount["type"] == "bind":
                source = Path(mount["source"]).resolve()
                if source == directory or source in directory.parents:
                    raise UpgradeError("数据挂载覆盖了安装目录，需先拆分源码与数据目录再迁移。")
        say("应用服务：%s；目标版本：%s。" % (app, version))
        say("入口：" + ("启用自动 HTTPS（80/443，应用诊断端口改为本机 8788）。"
                       if args.https else "保留原端口、挂载、环境及反代方式。"))
        say("备份 %d 个持久化挂载；失败时恢复原数据及原镜像。" % len(mounts))
        if args.dry_run:
            say("仅查看完成，未停止容器、拉取镜像或修改安装目录。")
            return
        new_app_image = new_model["services"][app]["image"]
        # Download and validate everything before taking the serving app down.
        for name in managed:
            say("拉取 " + new_model["services"][name]["image"])
            run(["docker", "pull", new_model["services"][name]["image"]], timeout=None)
        staged_runtime = staging / RUNTIME_FILE
        write_json(staged_runtime, new_model)
        staged_command = compose_command(directory, [staged_runtime])
        run(staged_command + ["config", "--quiet"], directory)
        backup = create_backup(directory)
        say("备份：" + str(backup))
        source_names = files + ([] if RUNTIME_FILE in files else [RUNTIME_FILE])
        existing = archive_source(directory, source_names, backup)
        write_json(backup / "old-compose.json", old_model)
        rollback_model = copy.deepcopy(old_model)
        previously_running = []
        for name, container in containers.items():
            if container:
                tag = "workbody-fhub-rollback:%s-%s" % (backup.name.lower(), name.lower())
                run(["docker", "tag", container["Image"], tag])
                rollback_model["services"][name]["image"] = tag
                rollback_model["services"][name].pop("build", None)
                rollback_model["services"][name].pop("pull_policy", None)
                if container["State"].get("Running"):
                    previously_running.append(name)
        write_json(backup / "rollback-compose.json", rollback_model)
        state = {"mode": "compose", "directory": str(directory), "version": version, "app_service": app,
                   "original_compose_files": [str(path) for path in original_files],
                   "files": source_names, "existing": existing, "mounts": mounts,
                   "previously_running": previously_running, "managed": managed,
                   "helper_image": new_app_image, "backup_complete": False}
        write_json(backup / "state.json", state)
        installed = data_saved = runtime_installed = False
        runtime_command = compose_command(directory, [directory / RUNTIME_FILE])
        try:
            run(old_command + ["stop"] + old_managed, directory)
            mount_operation(new_app_image, backup, mounts, "save")
            data_saved = True
            state["backup_complete"] = True
            write_json(backup / "state.json", state)
            installed = True
            install_source(directory, staging, files)
            write_json(directory / RUNTIME_FILE, new_model)
            runtime_installed = True
            run(runtime_command + ["up", "-d", "--no-build", "--pull", "never"] + managed, directory)
            wait_application(runtime_command, app, directory, version, args.timeout)
        except BaseException:
            say("升级未完成，正在恢复原安装。")
            try:
                if runtime_installed:
                    run(runtime_command + ["stop"] + managed, directory)
                if data_saved:
                    # Retain any data produced by the failed new process too.
                    try:
                        mount_operation(new_app_image, backup, mounts, "save", "failed-state")
                    except Exception:
                        say("失败状态归档未完成，继续恢复升级前数据。")
                    mount_operation(new_app_image, backup, mounts, "restore")
                if installed:
                    restore_source(directory, source_names, existing, backup)
                if previously_running:
                    rollback_command = compose_command(directory, [backup / "rollback-compose.json"])
                    run(rollback_command + ["up", "-d", "--no-build", "--pull", "never"] + previously_running, directory)
                say("已恢复原数据与配置，并启动升级前运行的服务；请确认原入口可用。")
            except Exception as error:
                say("自动恢复未完成：" + str(error))
                say("保留此备份，按 docs/upgrading.md 的手动恢复步骤操作：" + str(backup))
            raise
        say("升级完成，应用 /health.version = " + version)
        say("以后管理此安装使用：docker compose -f " + RUNTIME_FILE)
        if managed_nginx(new_model):
            say("证书签发在后台进行；查看 /tls/status 和 nginx 日志。")
        say("旧数据已由应用导入 SQLite；原 JSON/JSONL 与升级前备份保留。")


def rollback(args):
    directory = Path(args.directory).resolve()
    backup = Path(args.rollback).resolve()
    state = json.loads((backup / "state.json").read_text(encoding="utf-8"))
    if state.get("directory") != str(directory):
        raise UpgradeError("备份不属于当前安装目录；跨机器恢复请按迁移文档操作。")
    if state.get("mode") != "compose":
        raise UpgradeError("原生 Python 备份请先停服，再按文档恢复 source.tar.gz 与 native-data.tar.gz。")
    if not state.get("backup_complete"):
        raise UpgradeError("该升级的停服备份尚未完成，不能使用自动回滚。")
    mounts = state["mounts"]
    for index in range(len(mounts)):
        if not (backup / ("data-%03d.tar.gz" % index)).is_file():
            raise UpgradeError("持久化数据备份不完整，不能回滚。")
    command = compose_command(directory, [directory / RUNTIME_FILE])
    if args.dry_run:
        say("将停止新版服务、另存当前数据，再恢复：" + str(backup))
        return
    rollback_model = json.loads((backup / "rollback-compose.json").read_text(encoding="utf-8"))
    for name in state["previously_running"]:
        try:
            run(["docker", "image", "inspect", rollback_model["services"][name]["image"]])
        except UpgradeError:
            raise UpgradeError("回滚镜像已被清理，尚未停止服务；请先恢复备份中的原镜像。") from None
    helper = state["helper_image"]
    try:
        run(["docker", "image", "inspect", helper])
    except UpgradeError:
        run(["docker", "pull", helper], timeout=None)
    prefix = "before-rollback-" + time.strftime("%Y%m%d-%H%M%S")
    say("停止新版服务；当前数据另外保存为 " + prefix)
    run(command + ["stop"] + state["managed"], directory)
    # Failure here stops before overwriting any current data.
    mount_operation(helper, backup, mounts, "save", prefix)
    mount_operation(helper, backup, mounts, "restore")
    restore_source(directory, state["files"], state["existing"], backup)
    rollback_command = compose_command(directory, [backup / "rollback-compose.json"])
    if state["previously_running"]:
        run(rollback_command + ["up", "-d", "--no-build", "--pull", "never"] +
            state["previously_running"], directory)
    say("已恢复升级前数据与源码，并启动原服务；请确认原入口可用。当前数据归档保留。")
    say("原镜像固定在 rollback-compose.json；后续管理可使用该文件。")


def create_backup(directory):
    parent = directory / BACKUPS
    parent.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        parent.chmod(0o700)
    path = parent / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    path.mkdir(mode=0o700)
    return path


def main():
    if sys.version_info < (3, 9):
        say("需要 Python 3.9 或更新版本。")
        return 1
    parser = argparse.ArgumentParser(description="Workbody-FHUB 旧版迁移：备份、更新源码及镜像、失败恢复。")
    parser.add_argument("--directory", default=str(Path(__file__).resolve().parent), help="原安装目录")
    parser.add_argument("--version", default=VERSION, help="目标正式版本，默认 " + VERSION)
    parser.add_argument("--compose-file", action="append", default=[], help="原 Compose 文件，可重复传入")
    parser.add_argument("--service", help="应用服务名，默认自动识别")
    parser.add_argument("--https", action="store_true", help="显式增加 Nginx 自动 HTTPS，使用公网 80/443")
    parser.add_argument("--tls-mode", choices=("auto", "domain"), default="auto", help="--https 的证书模式")
    parser.add_argument("--public-ip", help="--https 的公网 IP；不指定时自动发现")
    parser.add_argument("--domains", help="--https 的域名，多个域名用逗号分隔")
    parser.add_argument("--acme-email", help="--https 的证书联系邮箱")
    parser.add_argument("--source-only", action="store_true", help="原生 Python 安装；先停止服务，更新后自行重启")
    parser.add_argument("--dry-run", action="store_true", help="只查看迁移计划，不改安装或拉取镜像")
    parser.add_argument("--rollback", help="恢复本机指定的升级前备份；先另存当前数据")
    parser.add_argument("--timeout", type=int, default=180, help="应用启动等待秒数，默认 180")
    args = parser.parse_args()
    if args.timeout < 5:
        parser.error("--timeout 至少 5 秒")
    if args.source_only and args.https:
        parser.error("--https 只能用于 Docker Compose 安装")
    if args.tls_mode == "domain" and not args.domains:
        parser.error("--tls-mode domain 需要 --domains")
    if not args.https and (args.public_ip or args.domains or args.acme_email or args.tls_mode != "auto"):
        parser.error("证书选项需要同时使用 --https")
    if args.rollback and (args.source_only or args.https or args.compose_file):
        parser.error("--rollback 不与迁移模式或 Compose 文件选项同时使用")
    lock = Path(args.directory).resolve() / ".update.lock"
    locked = False
    try:
        if not args.dry_run:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(str(os.getpid()) + "\n")
            locked = True
        rollback(args) if args.rollback else upgrade(args)
        return 0
    except FileExistsError:
        say("已有升级锁。确认没有其他升级进程后，才可移除 .update.lock 再重试。")
        return 1
    except KeyboardInterrupt:
        say("升级被中断。")
        return 130
    except Exception as error:
        # Download failures may carry signed redirect URLs; do not echo them.
        say(str(error) if isinstance(error, UpgradeError) else "升级失败（%s），原配置及备份保留。" % type(error).__name__)
        return 1
    finally:
        if locked:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
