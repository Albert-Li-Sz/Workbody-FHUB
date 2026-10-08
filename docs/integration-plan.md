# 部署、HTTPS 与数据迁移

适用版本：**1.1.2**。协议见 [API 说明](api.md)，账号规则见[调度说明](account-scheduling.md)，旧安装见[升级与回滚](upgrading.md)。

## 公网 Docker Compose

```bash
git clone https://github.com/Albert-Li-Sz/Workbody-FHUB.git
cd Workbody-FHUB
cp deploy/environment.example .env
docker compose pull
docker compose up -d
docker compose logs nginx workbody-fhub
```

Compose 包含应用和 Nginx 两个服务，默认拉取两个已发布的固定版本镜像。应用监听容器内 `8788`，宿主机调试端口仅绑定 `127.0.0.1:8788`；Nginx 提供公网 `80/443`。源码构建额外采用 `docker-compose.build.yml`，见[构建说明](upgrading.md#镜像与源码构建)。

| 宿主机目录 | 容器位置 | 内容 |
| --- | --- | --- |
| `accounts` | `/app/accounts` | SQLite、账号 JSON、优先级、Key、设置及代理槽 |
| `usage` | `/app/usage` | JSONL 导出、归档、价格政策历史与手动映射 |
| `.tls` | `/etc/letsencrypt` | ACME 账号、证书、私钥及续签配置 |
| `.acme` | `/var/lib/letsencrypt` | HTTP-01 验证文件和签发状态 |

首次日志显示随机面板密码和 API Key。控制台入口为 `https://<公网IP>/`，Base URL 为 `https://<公网IP>/v1`。证书状态可读取 `http://<公网IP>/tls/status`，应用运行版本读取本机 `http://127.0.0.1:8788/health`。

### 自动签发与续签

- `WB_TLS_MODE=auto`：通过直连公网 IP 查询服务发现服务器地址，签发 IP 证书；可附加 `WB_TLS_DOMAINS`。
- `WB_TLS_MODE=domain`：仅使用指定域名，域名 A／AAAA 记录应指向当前服务器。
- `WB_TLS_MODE=off`：Nginx 提供 HTTP，不调用 ACME；适合内网或已有 TLS 入口。
- `WB_PUBLIC_IP` 可覆盖检测结果，支持公网 IPv4／IPv6。NAT、双出口或出口 IP 不等于入站 IP 时应设置此值。
- HTTP-01 验证需要公网 **80** 到达本容器，业务 HTTPS 需要公网 **443**。修改宿主机映射后，仍需让公网 80／443 转发至对应端口。
- 首次证书就绪前，HTTP 业务返回 `503`；`/.well-known/acme-challenge/`、`/tls/status` 和 `/nginx-health` 可访问。就绪后 HTTP 跳转 HTTPS。
- 每六小时运行续签检查；失败默认半小时后重试。成功后执行 `nginx -t`，再平滑重载，无需挂载 Docker socket 或配置宿主机 cron。
- `WB_ACME_STAGING=1` 用于预部署签发，证书不受浏览器信任；改回 `0` 并重建容器后切换正式证书。保留 `.tls/.acme`，避免每次重建都重复申请。

Let’s Encrypt 的 IP 证书采用 `shortlived` 配置，有效期 **160 小时**；本镜像使用 Certbot **5.8.0** 的 `--ip-address` 和 webroot 验证。证书服务应长期运行。[证书说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)、[Certbot IP 支持](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)

`/nginx-health` 只表示 Nginx 能响应；`/tls/status` 的 `ready` 才表示本服务完成正式证书配置。实际签发取决于当前服务器公网地址和验证端口可达性。

### 1Panel／已有反代

已有反代占用 80／443 时，可使用应用独立编排：

```bash
docker compose -f docker-compose.direct.yml pull
docker compose -f docker-compose.direct.yml up -d
```

把原反代指向 `http://127.0.0.1:8788`；反代在另一个容器内时，需使用可达的 Docker 网络地址或宿主机地址，容器自己的 `127.0.0.1` 不是应用宿主机。继续挂载原 `accounts/usage` 目录。1Panel 可直接拉取固定镜像；从源码构建时需要上传完整仓库。

已有 Nginx 的流式 location 建议：

```nginx
location / {
    proxy_pass http://127.0.0.1:8788;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    proxy_read_timeout 360s;
    proxy_send_timeout 300s;
    send_timeout 360s;
    gzip off;
}
```

应用 SSE 返回 `X-Accel-Buffering: no` 与 `Cache-Control: no-cache, no-transform`。若外层还有 CDN 或负载均衡，同样需要允许长连接并关闭事件流缓存。[Nginx 缓冲说明](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)

### 普通 UID 与内网

`PUID/PGID` 默认 `0:0`，只控制应用容器用户。使用普通 UID 时先为其创建可写的账号、用量目录。Unix 私有目录使用 `0700`，账号文件和数据库使用 `0600`；Windows 由 ACL 管理。

独立编排默认绑定本机地址。局域网共享可在 `.env` 设置 `WB_BIND_ADDRESS=0.0.0.0`，然后访问 `http://<内网IP>:8788/`。私有地址不能申请此公网 IP 证书。

## 本机运行

```bash
python3 wb_proxy.py --host 127.0.0.1 --port 8788 \
  --accounts-dir ./accounts --usage-dir ./usage
```

Python 3.9+，无额外 pip 依赖。Windows、macOS、Linux 启动脚本继续可用。`--lan` 会监听所有接口并启用 API Key。

密码可通过 `PANEL_PASSWORD`／`--panel-password` 或 `PANEL_PASSWORD_FILE`／`--panel-password-file` 指定。持续设置覆盖项时，每次重启都会采用该值。密码文件需要自行挂载并传入容器内路径。

## 参数

复制 `deploy/environment.example` 到 `.env` 后按需修改。

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `WB_TLS_MODE` | `auto` | `auto`／`domain`／`off` |
| `WB_PUBLIC_IP` | 空 | 自动发现；可显式指定公网 IP |
| `WB_TLS_DOMAINS` | 空 | 逗号分隔的附加域名 |
| `WB_ACME_EMAIL` | 空 | 可选 ACME 联系邮箱 |
| `WB_ACME_STAGING` | `0` | `1` 使用测试签发服务 |
| `WB_ACME_CHECK_SECONDS` | `21600` | 续签检查间隔，至少 300 秒 |
| `WB_ACME_RETRY_SECONDS` | `1800` | 失败重试间隔，至少 300 秒 |
| `WB_HTTP_PORT`／`WB_HTTPS_PORT` | `80`／`443` | Nginx 宿主机端口 |
| `WB_DIRECT_PORT` | `8788` | 本机应用诊断端口 |
| `WB_BIND_ADDRESS` | `127.0.0.1` | 仅独立编排使用 |
| `WB_HTTP_POOL_MAX` | `128` | 全局上游连接数上限 |
| `WB_HTTP_POOL_PER_ROUTE` | `8` | 每个目标／账号／代理路由的连接上限 |
| `WB_HTTP_POOL_IDLE` | `60` | 空闲连接淘汰秒数 |
| `WB_HTTP_MAX_CONNECTIONS` | `128` | HTTP 已接受连接上限（含面板与 SSE，8–4096） |
| `WB_TRUSTED_PROXIES` | Nginx 与 loopback | 仅可信来源的 `X-Real-IP` 参与登录限流与可选客户端日志 |
| `WB_SSE_HEARTBEAT_SECONDS` | `15` | 生成流无内容时的心跳间隔 |
| `WB_SQLITE_RETENTION_DAYS` | `0` | SQL 用量保留天数；`0` 保留全部历史 |
| `WB_SQLITE_PATH` | `accounts/workbody.sqlite3` | 直接运行时可改路径；Compose 改路径时需同时添加环境与持久化挂载 |

连接池只归还已经完整读取的响应；取消、未读完和损坏响应丢弃连接。账号凭据及代理身份相互隔离，查询界面只显示连接计数。上游不允许保持连接时仍按普通连接处理。

上游首部／空闲超时仍由控制台现有 transport 配置控制，入站接收限制为 `WB_HTTP_READ_TIMEOUT`（默认 30 秒）。心跳保持客户端与反代连接活跃，不会无限延长失效上游的等待。

## SQLite 迁移与备份

首次启动会创建 WAL 数据库并导入账号及设置 JSON、`usage.jsonl` 和 `usage-archive-*.jsonl`；重复启动通过记录 ID、文件偏移及内容摘要去重。价格政策 JSONL 不作为请求日志导入。

账号、设置和 Key 使用数据库读写，并保留原子 JSON 导出。外部修改合法 JSON 后下次读取会导入数据库；缺少导出文件时可从数据库恢复。删除账号应使用控制台操作，单独删除 JSON 不等同于删除数据库中的账号。

请求用量先写入 SQLite，再导出 JSONL；SQL 查询通过时间、账号、渠道、模型及 Key 的索引读取。会话绑定重启后可恢复。价格政策历史仍使用 `usage/pricing-*.jsonl`，与数据库共同构成成本统计所需数据。

JSONL 归档大小和保留天数沿用原面板设置。SQLite 默认保留全部请求历史，可通过 `WB_SQLITE_RETENTION_DAYS` 开启独立清理；清理后的旧导出不会在重启时自动回灌。该选项会删除窗口外的数据库请求记录，启用前请备份。

运行中的数据库不能只复制主 `.sqlite3` 文件，已提交记录可能仍在 WAL 中。可使用内置在线备份命令：

```bash
docker compose exec workbody-fhub python wb_database.py \
  --source /app/accounts/workbody.sqlite3 \
  --backup /app/accounts/workbody-backup.sqlite3
```

备份目标必须不存在，文件创建为私有权限。直接运行时使用 `python3 wb_database.py --source accounts/workbody.sqlite3 --backup accounts/workbody-backup.sqlite3`。

完整迁移或回滚备份应先停止相关服务，再保存 `accounts`、`usage`、`.tls`、`.acme` 与 `.env`：

```bash
docker compose stop
umask 077
tar -czf workbody-data-backup.tar.gz accounts usage .tls .acme .env
docker compose start
```

独立编排使用同样的 `-f docker-compose.direct.yml` 参数，并只归档实际存在的目录。SQLite 文件应放在本机持久磁盘；WAL 不适合由多台机器共用 NFS 数据目录。[SQLite WAL 文档](https://www.sqlite.org/wal.html)

## 从 1.0.x 升级

在原目录使用 `bash ./update.sh`，脚本保留原入口、环境和挂载，停服备份后拉取新版，失败自动恢复。旧安装缺少脚本时，下载 Release 附件后执行；具体命令见[升级文档](upgrading.md)。

启用自动 HTTPS 使用 `--https`；默认不会更改原反代。数据库首次启动自动迁移，账号优先级和 Key 渠道保留。升级后的配置固定在私有 `compose.runtime.json`，使用 `docker compose -f compose.runtime.json` 管理；不要直接切换到新版默认 YAML。

确认 `/health` 的版本为 `1.1.2`；启用证书服务后另行确认 `/tls/status` 为 `ready`。发布或拉取镜像不会自动改变正在运行的旧进程。

### 回滚

使用 `bash ./update.sh --rollback .update-backups/<备份目录>`。工具先另存当前数据，再恢复升级前的整个快照与实际旧镜像。原生安装及手动恢复见[回滚步骤](upgrading.md#回滚)。较旧版本不会显示新控制台和在途预估。

## Redis 与多副本

当前是单进程、多线程网关。SQLite WAL 持久化，进程内锁完成原子选号、在途预估和实际用量校正，事件代理向面板发布 SSE。单实例无需 Redis。

现有 Upstash Redis 配置仅同步会话绑定，没有共享调度锁、在途用量或面板事件。多副本需要另行实现原子租约、共享计量、过期回收及 pub/sub，并采用适合多机的数据库；当前不要让多个应用实例共用此 SQLite／JSON 数据目录。

## 常见问题

| 现象 | 排查 |
| --- | --- |
| HTTP 返回 TLS 配置中 `503` | 查看 `/tls/status` 与 `docker compose logs nginx`；确认公网 80 可达、IP 检测正确 |
| 浏览器提示证书不可信 | 检查 staging 配置、地址是否在证书中及服务器时间 |
| 长生成集中返回 | 检查每一层反代的缓冲、压缩、缓存与读超时 |
| 面板显示重连 | 检查 `/api/events` 是否被外层反代阻断；后台标签会主动暂停推送 |
| 新接口 404／界面仍旧 | 读取 `/health` 的版本，确认重建容器及反代目标、浏览器 HTML 缓存 |
| SQLite 只读或锁错误 | 确认数据目录 UID／权限、可用磁盘及是否有另一实例共用目录 |
| 余额 `503 balance_unavailable` | 检查原生余额响应的未知数／失败数，在控制台刷新积分及查看账号出口 |

## 发布

`wb_version.py` 为应用版本来源，Dockerfile、Compose、更新脚本和文档同步更新。Release 工作流同时发布应用与 Nginx 双架构镜像，验证后更新稳定标签；附件包括源码、升级脚本、校验文件与镜像摘要。构建记录、Release、运行实例与公网证书分别确认，发布镜像不会自动重启已有部署。
