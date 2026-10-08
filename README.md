# Workbody-FHUB

WorkBuddy 国内与国际多账号网关。将已有账号接入 OpenAI Chat Completions、Responses 和 Anthropic Messages，提供账号调度、渠道绑定、积分余额查询和实时用量控制台。

当前版本 **1.1.2** · Python **3.9+** · 应用仅依赖 Python 标准库

[版本发布](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases) · [更新记录](CHANGELOG.md) · [升级与回滚](docs/upgrading.md) · [部署说明](docs/integration-plan.md) · [API 说明](docs/api.md) · [账号与调度](docs/account-scheduling.md)

## 功能

- **公平调度**：数字较小的账号优先。同优先级内，免费模型比较当天免费 Token 加在途预估；付费模型比较当天积分消耗加在途预估。国内、国际独立均衡，结束后按实际用量校正；免费会话默认使用 256K Token 换号窗口。
- **连接复用**：有界 HTTP/1.1 连接池，按目标、账号和代理隔离连接；保留带认证的 HTTP、SOCKS5／SOCKS5h 代理。
- **稳定流式生成**：三种生成协议支持 SSE，默认 15 秒无内容时发送心跳；配套 Nginx 关闭缓冲、延长流式读写超时。
- **自动 HTTPS**：Nginx 自动检测公网 IP，签发并续签 Let’s Encrypt IP 证书；也可配置域名，每六小时检查续签并重载证书。
- **本地持久化**：SQLite WAL 保存账号、优先级、设置、Key、用量和会话绑定；自动导入旧 JSON／JSONL，保留兼容导出。
- **实时控制台**：中性色侧栏布局，支持手机、深浅主题、简繁体；SSE 推送状态变化，账号分页与局部更新，断线重连和低频恢复刷新；Token 显示 `K/M/B`。
- **协议兼容**：模型详情、渠道积分余额、按 Key 查询 Token；支持 DeepSeek、Kimi、千问及 OpenAI 旧版余额响应格式。
- **Messages 联网搜索**：本地 DDG 执行与模型续轮，原生搜索结果及引用、DSH 文本兼容、搜索历史回放；支持次数限制与域名过滤，需开启面板本地网络工具。详见 [Messages 接入](docs/api.md#messages-搜索请求)。
- 账号导入／导出、OAuth、代理槽、保留积分、每日限额、签到和任务调度；可选[本地网络工具](docs/research/web-search-support.md)。

## 公网部署：Nginx + 自动 HTTPS

服务器公网 **80、443** 端口必须可达。首次安装使用已发布的应用与 Nginx 镜像：

```bash
git clone https://github.com/Albert-Li-Sz/Workbody-FHUB.git
cd Workbody-FHUB
cp deploy/environment.example .env
docker compose pull
docker compose up -d
docker compose logs nginx workbody-fhub
```

默认自动检测公网 IP，无需购买域名。可在 `.env` 设置 `WB_ACME_EMAIL`；IP 检测不准确时填入 `WB_PUBLIC_IP`，附加域名使用 `WB_TLS_DOMAINS=api.example.com`。IP 证书约六天有效，因此证书服务需要持续运行并保留数据目录。[Let’s Encrypt 说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)

| 入口 | 地址 |
| --- | --- |
| 管理控制台 | `https://<公网IP>/` |
| OpenAI Base URL | `https://<公网IP>/v1` |
| 证书状态 | `http://<公网IP>/tls/status` |
| 本机诊断入口 | `http://127.0.0.1:8788/health` |

证书就绪前 HTTP 业务入口返回 `503`，验证路径始终开放；就绪后 HTTP 跳转 HTTPS。首次启动日志显示面板初始密码与网关 API Key。所有持久化数据位于 `accounts`、`usage`、`.tls`、`.acme`。已有 1Panel／反代、内网部署、端口冲突和备份步骤见[部署说明](docs/integration-plan.md)。

## 本机或已有反代

仅启动应用：

```bash
docker compose -f docker-compose.direct.yml pull
docker compose -f docker-compose.direct.yml up -d
```

默认绑定 `127.0.0.1:8788`。局域网共享时设置 `WB_BIND_ADDRESS=0.0.0.0`。也可直接运行：

```bash
python3 wb_proxy.py --host 127.0.0.1 --port 8788
```

Windows、macOS、Linux 启动脚本继续可用。面板密码和 API Key 分别管理，已有自定义密码保留；密码文件可通过 `PANEL_PASSWORD_FILE` 指定。

## 从旧版升级

在原安装目录执行，先保留旧 Compose 配置：

```bash
curl -fL https://github.com/Albert-Li-Sz/Workbody-FHUB/releases/download/v1.1.2/update.sh -o update.sh
bash ./update.sh --dry-run
bash ./update.sh
```

工具校验发布附件，拉取固定版本镜像，停服备份源码、配置和 bind／named volume，自动导入 SQLite，启动失败自动恢复。默认保留原端口和反代；启用自动 HTTPS 使用 `--https`。升级后使用 `docker compose -f compose.runtime.json` 管理。原生 Python、指定 Compose、手动回滚和完整步骤见[升级文档](docs/upgrading.md)。

## API 接入

客户端 API Key 使用控制台生成的网关 Key，模型 ID 以该 Key 的 `GET /v1/models` 为准。

| 功能 | 路径 |
| --- | --- |
| 对话、Responses、Messages | `POST /v1/chat/completions`、`POST /v1/responses`、`POST /v1/messages` |
| 模型列表／详情 | `GET /v1/models`、`GET /v1/models/{id}` |
| 渠道积分余额／Key 的 Token 消耗 | `GET /api/billing/balance`、`GET /api/billing/usage` |
| DeepSeek 余额格式 | `GET /user/balance`、`GET /v1/user/balance` |
| Kimi 官方余额格式 | `GET /v1/users/me/balance` |
| 千问／阿里云余额格式 | `GET /?Action=QueryAccountBalance` |
| OpenAI 旧版余额格式 | `GET /dashboard/billing/credit_grants` |
| GLM／MiniMax 网关扩展 | `GET /api/billing/balance/glm`、`GET /api/billing/balance/minimax` |

```bash
curl https://<公网IP>/v1/models \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

所有余额入口返回 Key 对应渠道内全部账号的 **WorkBuddy 积分总和**，包含停用账号，协议金额字段不代表现金。GLM、MiniMax 使用网关扩展入口；千问适配阿里云响应结构，OpenAI 为旧版账单兼容。完整别名、来源和返回示例见[API 说明](docs/api.md)。

## 优先级与并发均衡

控制台 **账号池** 中输入优先级并点击“保存优先级”：默认 `100`，范围 `0–2147483647`，保存到 SQLite 并导出账号 JSON。推送刷新保留未提交草稿及输入焦点。

调度预估只用于账号选择，不计入账单。请求结束时先记录实际上游用量，再移除预估；取消请求已有确认的部分消耗也计入。上游未报告的取消消耗保持未知。具体规则见[账号与调度](docs/account-scheduling.md)。

## 存储与 Redis

数据库默认是 `accounts/workbody.sqlite3`；首次启动自动迁移旧文件，持续挂载原目录即可。请求用量先提交 SQLite，再经持久化队列后台导出 JSONL；统计不等待导出完成。SQLite 默认保留全部历史，`WB_SQLITE_RETENTION_DAYS` 可设置独立保留天数。价格政策历史仍在 `usage` 目录，应与数据库一起备份。

**单实例无需 Redis。** SQLite 保存数据，进程内锁完成原子选号与结算。现有可选 Upstash Redis 配置仅镜像会话绑定；多副本部署还需要共享在途租约、计量与事件发布，当前不能靠打开该选项实现分布式公平调度。[存储与备份](docs/integration-plan.md#sqlite-迁移与备份)

## 开发与发布

应用无额外 pip 依赖；Nginx 镜像额外包含 Certbot。发布工作流同时构建两个镜像的 `linux/amd64`、`linux/arm64` 版本，验证后更新稳定标签，并在 [Release](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases) 附带源码、升级脚本、SHA-256 和镜像摘要。

应用镜像为 `ghcr.io/albert-li-sz/workbody-fhub:1.1.2`，Nginx 为 `ghcr.io/albert-li-sz/workbody-fhub-nginx:1.1.2`。源码构建采用 `docker-compose.build.yml` overlay，见[升级文档](docs/upgrading.md#镜像与源码构建)。现有回归包含 94 个套件：77 个 Python + 17 个 JS，入口为 `python3 tests/run_all.py`，JavaScript 套件需要 Node.js。

提示词重试、首字耗时、连接与统计优化见[性能与可靠性说明](docs/performance.md)。

界面设计记录见 [docs/ui-design.md](docs/ui-design.md)，部署参数、升级与回滚见[部署说明](docs/integration-plan.md)。

## 来源与许可证

本项目派生自 [ardeyouxipianyi/workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub)，基于上游 **1.6.13**。采用 [Apache-2.0](LICENSE)，保留上游 [MIT 原文](LICENSE.upstream)、[版本记录](CHANGELOG.upstream.md)、Vibe Coding 声明及贡献者致谢，详见[来源与致谢](docs/credits.md)。

本项目为非官方自托管网关，使用已有合法授权账号，不提供账号或额度。
