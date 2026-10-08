# 部署、升级与迁移

适用版本：**1.0.9**。入口索引见 [README](../README.md)，协议和鉴权见 [API 说明](api.md)。

## Docker Compose 部署

```bash
git clone https://github.com/Albert-Li-Sz/Workbody-FHUB.git
cd Workbody-FHUB
docker compose pull
docker compose up -d
docker compose logs workbody-fhub
```

默认镜像 `ghcr.io/albert-li-sz/workbody-fhub:1.0.9`，支持 `linux/amd64` 和 `linux/arm64`。Compose 映射 `0.0.0.0:8788:8788`；面板为 `http://<服务器IP>:8788/`，OpenAI Base URL 为 `http://<服务器IP>:8788/v1`。

| 宿主机数据 | 容器位置 | 内容 |
| --- | --- | --- |
| `./accounts` | `/app/accounts` | 账号凭证、优先级、Key、设置和代理槽 |
| `./usage` | `/app/usage` | 请求与用量日志 |

首次启动日志显示 `PANEL BOOTSTRAP PASSWORD` 和生成的 API Key。登录面板后添加账号，在设置页配置 Key 的国内／国际绑定。密码与 API Key 分别管理，余额接口始终要求有效 API Key。

### 1Panel

在编排中导入仓库的 Compose 配置，将 `./accounts`、`./usage` 换成所选宿主机持久化目录。选择固定版本 `1.0.9`，开放或反代 `8788` 端口，查看容器日志取得初始密码。升级时修改镜像版本，拉取并重新部署同一编排，继续使用原数据目录。

### 普通 UID

Compose 的 `PUID`／`PGID` 默认 `0:0`。改用普通 UID 时，先给该 UID 创建可写的账号和日志目录，再设置 `PUID`、`PGID`。Unix 账号目录权限使用 `0700`，凭证和 Key 文件使用 `0600`；Windows 由系统 ACL 管理。

## 本机运行

安装 Python 3.9+，在项目目录执行：

```bash
python3 wb_proxy.py --host 127.0.0.1 --port 8788 \
  --accounts-dir ./accounts --usage-dir ./usage
```

项目提供 Windows、macOS、Linux 启动脚本。局域网共享可使用 `--lan`，该模式监听 `0.0.0.0` 并要求 API Key。仅在本机使用时保持默认 `127.0.0.1`。

面板密码可通过 `PANEL_PASSWORD`／`--panel-password` 或私有密码文件 `PANEL_PASSWORD_FILE`／`--panel-password-file` 设置。持续设置这些覆盖项时，每次重启会再次使用该值。容器使用密码文件时需自行挂载文件，并在 Compose 的 environment 中传入容器内路径。

## 升级

先备份现有持久化目录，再在原部署目录执行：

```bash
tar -czf workbody-data-backup.tar.gz accounts usage
export WORKBODY_IMAGE=ghcr.io/albert-li-sz/workbody-fhub:1.0.9
docker compose pull
docker compose up -d
curl http://127.0.0.1:8788/health
```

确认响应中的 `version` 是 `1.0.9`。若 `.env` 已配置 `WORKBODY_IMAGE`，同时更新其中的值，确保后续重启仍使用所选版本。本机脚本部署需要更新源码并重新启动原服务，继续使用原账号与日志路径。

升级后检查：

1. 面板 **账号池与运维** 显示“调度优先级”“保存优先级”和名称旁的已保存徽章。
2. 在原 Key 上确认渠道绑定，使用 `GET /v1/users/me/balance` 或 `/api/billing/balance` 查询对应渠道积分。
3. 用量页、模型页和最近请求的 Token 数量使用 `K/M/B`；数字输入框、JSON API、导出和原始日志保留完整数值。

### 回滚

指定之前的已发布镜像，例如 `ghcr.io/albert-li-sz/workbody-fhub:1.0.6`，重新拉取并创建容器。沿用原数据目录。跨较旧版本回滚前保留备份；旧版本界面可能没有优先级输入或新的余额路径。

## 404 或界面未更新

| 现象 | 排查 |
| --- | --- |
| 新余额接口 404 | 先读 `/health` 的运行版本，确认已重建容器或重启 Python 服务 |
| 已拉取镜像但版本仍旧 | 用 `docker compose images`、`docker compose ps` 确认当前编排和镜像，再执行 `up -d` |
| 面板看不到保存优先级 | 确认版本，刷新浏览器；检查反向代理是否缓存 HTML、是否指向旧端口或另一台实例 |
| 401 | 使用网关 Key 的 `Authorization: Bearer ...`，检查 Key 启用状态 |
| 503 `balance_unavailable` | 查询 `/v1/balance` 中的 `unknown_count`、`refresh_failed`；在面板刷新积分及检查账号代理 |

发布 Release 和镜像后，已有部署需要执行升级步骤。`/health` 和当前实例的返回结果用于确认运行版本。

## 代理与网络

账号请求在设置页配置代理槽，可用 HTTP、SOCKS5、SOCKS5h，用户名和密码分别保存。账号页绑定槽位后，模型请求、积分刷新和网页任务使用对应出口。

本地网络工具单独使用 `WB_WEB_PROXY`、`WB_WEB_PROXY_USERNAME`、`WB_WEB_PROXY_PASSWORD`。公网反代建议启用 HTTPS。请求头／体接收时限默认 30 秒，可通过 `WB_HTTP_READ_TIMEOUT` 调整；此限制与上游流式生成等待分别处理。

## 旧出口配置

网关当前渠道为 `workbuddy-cn`、`workbuddy-intl`。从曾带有其他出口的旧配置升级时，重新编辑绑定已移除出口的 Key 并明确选择现有渠道后启用。Key 名称和历史用量继续保留。

## 构建与发布

`wb_version.py` 为版本来源，发布同时更新 Dockerfile、Compose 和 README。GitHub 发布工作流校验版本、运行现有 CI、构建双架构镜像、检查镜像源码和启动结果，再将稳定版本同步到 `latest`。实际构建和发布结果见对应 Release 与 Actions；历史审计见 [修复记录](project-repair-2026-10-07.md)。
