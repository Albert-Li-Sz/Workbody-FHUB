# 从旧版升级到 1.2.8

升级工具为根目录的 `update.sh` 和 `update.py`。适用于单实例、本机 Docker Compose 安装；原生 Python 安装使用 `--source-only`。在**原安装目录**执行，不能先用新版 Compose 覆盖旧配置。

## Docker Compose

服务器需要 Python 3.9+、Docker Compose v2，以及 GitHub、GHCR 网络访问。使用能管理原 Docker 容器、读写原安装目录的用户。脚本通过容器读取 root 所有的数据，不需要放宽账号文件权限。

旧安装没有更新脚本时，先下载固定版本：

```bash
curl -fL https://github.com/Albert-Li-Sz/Workbody-FHUB/releases/download/v1.2.8/update.sh -o update.sh
bash ./update.sh --dry-run
bash ./update.sh
```

下载到文件后再执行。引导脚本核对本地 `update.py` 的版本；缺失或版本不同则下载并校验匹配的迁移器，避免仍按旧版升级。迁移工具校验源码附件的 SHA-256；`--dry-run` 只下载、解析并显示计划，不停服、不拉镜像、不写安装目录。

默认保留原 Compose 项目、服务名、端口、环境、用户、网络、命令和数据挂载；不新增公网入口。原来使用 `0.0.0.0:8788`、1Panel 或独立反代的安装继续使用原入口。

有额外编排文件时明确传入，顺序与原启动命令一致：

```bash
bash ./update.sh --compose-file docker-compose.yml \
  --compose-file docker-compose.override.yml --service workbody-fhub
```

工具优先使用显式文件，其次使用已有 `compose.runtime.json`，再识别 `COMPOSE_FILE` 或标准 Compose 文件及 override。特殊 `.env` 变量展开、不同 `--env-file`、非标准项目目录，请先在原环境中设置相同环境变量并显式指定文件。

### 执行过程

1. 下载固定版本的源码附件与校验文件，检查版本及归档路径。
2. 解析旧编排、识别容器与实际挂载，拉取固定版本镜像并检查新配置。
3. 固定旧容器的实际镜像 ID 和数据卷，包括原来的匿名卷；停止应用和本项目的 Nginx，备份全部可写 bind mount、named volume、将被覆盖的源码及旧编排。
4. 安装源码，生成私有 `compose.runtime.json`，启动新版；首次启动导入旧账号、优先级、Key、设置和 JSONL 用量到 SQLite。
5. 从容器内确认 `/health` 返回 `version: 1.2.8`；使用配套 Nginx 时同时检查 `nginx -t`、Nginx 健康入口和已启用的代理入口。启动失败时自动恢复升级前数据、源码、配置和旧镜像；已产生的新数据另存为 `failed-state-*.tar.gz`。

备份位于 `.update-backups/<时间-随机标识>/`，目录权限 `0700`、归档与配置权限 `0600`。旧 JSON／JSONL 不会因迁移被删除。SQLite 主文件、WAL 与 SHM 在停服后一起保存，避免只复制主文件漏掉已提交数据。

脚本更新 Release 中的源码文件，不执行 `git reset`，不覆盖 `.env`、账号、用量、证书和用户 override；本地修改过的源码先备份，再替换。数据目录未挂载、整个 `/app` 被挂载、远程 Docker、多实例、特殊设备文件、指向挂载外部的符号链接需要先整理或手动迁移。新镜像健康确认不代表上游账号或公网证书已经可用。

### 升级后的管理命令

```bash
docker compose -f compose.runtime.json ps
docker compose -f compose.runtime.json logs --tail 100 workbody-fhub
docker compose -f compose.runtime.json up -d
```

`compose.runtime.json` 是升级后采用的完整配置，其中环境变量已展开，可能包含密码或代理凭据，请勿上传 Git 或发送给他人。修改配置时编辑该文件；单独修改 `.env` 不会改变其中已固定的值。再次执行更新工具会继续采用这个文件。**不要直接运行新版默认 YAML 来管理迁移后的安装**，它的默认入口与旧版不同。

## 同时启用自动 HTTPS

没有现成反代，且公网 80／443 可用时：

```bash
bash ./update.sh --https
```

该模式添加本项目的 Nginx 镜像，业务入口改为 `https://<公网IP>/`，应用诊断端口改为 `127.0.0.1:8788`。公网 IP 自动发现；证书签发与续签在后台进行。可显式指定 IP、邮箱或域名：

```bash
bash ./update.sh --https --public-ip 203.0.113.10 --acme-email admin@example.com
# 仅域名证书
bash ./update.sh --https --tls-mode domain --domains api.example.com
```

示例 IP 应替换为服务器实际公网 IP。查看 `http://<公网IP>/tls/status` 和 `docker compose -f compose.runtime.json logs nginx`。证书未就绪时 HTTP 业务返回 `503`；证书失败不会触发应用数据回滚。80／443 已由其他服务使用时，先继续原反代，按[部署说明](integration-plan.md)关闭流式缓冲并设置超时。

## 回滚

保留升级脚本、备份和 `workbody-fhub-rollback:*` 本地镜像，确认新版稳定前不要清理这些镜像。回滚恢复升级前快照，因此升级后的新请求和配置不会留在正在使用的数据里；工具会先把当前数据另存为 `before-rollback-*.tar.gz`。

```bash
bash ./update.sh --rollback .update-backups/<备份目录> --dry-run
bash ./update.sh --rollback .update-backups/<备份目录>
```

工具会在停服前检查旧镜像是否仍在和备份是否完整。回滚后以备份中的 `rollback-compose.json` 管理原服务，避免旧版 `latest` 指向了新镜像：

```bash
docker compose -f .update-backups/<备份目录>/rollback-compose.json ps
```

如果自动恢复中断，保留所有归档并停止相关服务。`state.json` 记录每个 `data-NNN.tar.gz` 对应的 bind 路径或 named volume；按对应挂载恢复**整个目录**，包括 SQLite、WAL、SHM 和 JSON／JSONL，再恢复 `source.tar.gz` 与原配置，使用 `rollback-compose.json` 启动。不要向运行中的 SQLite 目录覆盖快照，也不要混合不同时点的数据。原本停止的服务不会因回滚自动启动。

若升级进程被强制终止，确认没有其他升级进程后再删除 `.update.lock`。备份中 `backup_complete: false` 说明停服数据归档尚未完成，不可直接当完整快照恢复。

应用、Nginx 和 TLS 分别报告：证书仍在签发／重试或使用测试证书时，不会显示 HTTPS 生产证书已就绪；查看 `/tls/status` 的状态与到期时间。Nginx 配置、进程或已启用代理不可用时自动回退。1.1.2 增加 SQLite 小时汇总与持久化导出队列（schema 2）。1.1.3 沿用 schema 2，旧全局限额自动成为分渠道限额的默认值，临期优先调度默认关闭；回退旧程序必须恢复升级前的完整数据备份，不能直接让旧程序打开新版数据库。

## 1.2.2 数据迁移

SQLite schema 2→3 在事务中为用量增加 `upstream`，旧请求归入 WorkBuddy；重建带平台维度的小时汇总。启动中断会回滚该迁移，版本号仅在全部步骤成功后更新。旧 Key 缺少平台字段时仍仅允许 WorkBuddy，原账号、优先级、限额、代理与密码保留。

Cline／Zen 凭据新增在私有 `accounts/upstreams`；Responses 正文与分支快照存入同一数据库。升级不会自动授权旧 Key 使用新平台。所有数据都位于已有 accounts 挂载中，备份／回滚继续恢复完整目录；使用旧程序前恢复 schema 2 的升级前快照。

1.2.1 升级到 1.2.2 沿用 schema 3；原 Cline／Zen 凭据和 Responses 历史继续保留。账号入口迁至「账号池」的来源页签，Responses 保留配置迁至设置页；WorkBuddy 原入口与 OAuth 保持原样。

1.2.2 升级到 1.2.3 继续沿用 schema 3，保留 WorkBuddy 与新增来源的账号、组织、优先级、Key、代理及 Responses 历史。价格元数据缓存新增在 `accounts/upstreams/client-model-metadata.json`，余额与订阅查询状态保存在原账号文档中，随原数据挂载一起备份和回滚。

1.2.3 升级到 1.2.4 同样沿用 schema 3。启动后自动重新同步旧 OpenCode OAuth 组织配置，解析当前账号的官方令牌占位符，并分别保存 Zen／Go 网关；原账号、优先级、组织、Key、代理、用量和 Responses 历史保留。旧源码和完整私有数据仍纳入升级备份，回滚恢复旧状态。

1.2.4 升级到 1.2.5 继续沿用 schema 3，五渠道模型库复用现有账号池目录和元数据缓存，无需重新登录或导入账号。原账号、优先级、组织、Key、代理、用量及 Responses 历史保留；原 WorkBuddy 倍率与输出探测结果继续显示。

1.2.5 升级到 1.2.6 继续沿用 schema 3。模型别名与启停保存在原私有设置的 `model_policies`，未配置模型默认启用、无别名；账号、Key、代理和 Responses 历史继续保留。旧设置锚点自动进入对应独立页面。Cline／OpenCode 公共余额数值改为 5 小时剩余百分比合计，单位为 `percent`，可超过 100%；数据不完整时兼容余额接口返回 `503 balance_unavailable`。WorkBuddy 与 Command Code 继续使用原积分单位。

1.2.6 升级到 1.2.7 沿用 schema 3。Cline 目录直接返回上游 ID，旧 `cline/` 调用、Key 白名单、模型别名／启停策略和 Responses 历史继续兼容；保存 Cline 模型设置时将对应策略转为原始 ID。模型页增加跨页全选筛选结果和批量启停，无需重新登录或配置账号。

1.2.7 升级到 1.2.8 继续沿用 schema 3，账号、Key、代理、模型策略与 Responses 历史保留。匿名 `/health`、`/realm` 和 `/panel/status` 仅返回基础状态；依赖账号或渠道详情的监控需要有效网关 Key 或面板会话。平台账号导出默认不含凭据，迁移／恢复请选择「导出含凭据」并确认，API 使用 `includeSecrets=1`。容器及重定向日志中的网关 Key 会脱敏，完整 Key 从面板「设置 → API Key」读取。

验证脚本 `scripts/verify_upgrade.py` 覆盖 1.1.0、1.1.1、1.1.2、1.1.3、1.2.1、1.2.2、1.2.3、1.2.4、1.2.5、1.2.6、1.2.7 的 Compose 升级与回滚，以及原生源码迁移；包含旧平台凭据与 Responses 历史保留检查，使用模拟账号／日志，不需要真实凭据。

## 原生 Python／Windows 安装

先用原服务管理方式停止 Python 网关。将 Release 的 `update.py` 下载到原安装目录：

```bash
python3 update.py --source-only --dry-run
python3 update.py --source-only
```

Windows 使用 `python update.py`；下载的附件可通过同一 Release 的 `checksums.txt` 校验。工具更新源码并备份根目录内的 `accounts`、`usage`、`.tls`、`.acme`，随后用原启动脚本或 systemd 重新启动，检查 `/health` 的版本。自定义数据路径在安装目录之外时，需要另外停服备份；原生模式不自动管理服务或 Docker。

原生回滚时先停服，将当前数据目录移到另一个备份位置，再解包 `native-data.tar.gz` 和 `source.tar.gz` 到原安装目录，以原启动方式重启。为保留原 UID／权限，Linux 解包时使用有对应权限的用户；Windows 继续按原 ACL 管理。升级新增的文件列表在 `state.json` 的 `files`，原来存在的文件在 `existing`，两者差集可在恢复旧源码前删除。

## 镜像与源码构建

正式镜像均支持 `linux/amd64` 与 `linux/arm64`：

```text
ghcr.io/albert-li-sz/workbody-fhub:1.2.8
ghcr.io/albert-li-sz/workbody-fhub-nginx:1.2.8
```

Release 同时附带源码归档、升级脚本、`checksums.txt` 与 `images.json`。后者记录应用／Nginx 摘要和提交，`latest` 在应用与 Nginx 两种架构镜像验证通过后才更新；校验文件最后生成，并附各镜像验证回执。

维护者打包源码使用 `python3 scripts/package_release.py --ref <发布标签> --output-dir <输出目录>`。工具仅读取该 Git 提交，排除 `accounts`、`usage` 等运行时目录；这些目录即使只有跟踪的 `README.txt` 占位说明，也不能进入升级归档。发布工作流采用同一打包工具，并在上传全部附件后刷新校验文件。

源码构建使用独立 overlay，不需要修改默认发布镜像配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --pull never
```

迁移后的自定义安装若采用源码构建，应基于自己的 `compose.runtime.json` 添加 build 配置，保留其中的端口和挂载。发布新镜像不会自动升级任何运行中的服务器。
