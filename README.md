# Workbody-FHUB

WorkBuddy 国内与国际多账号网关。将已有账号接入 OpenAI Chat Completions、Responses 和 Anthropic Messages 协议，提供账号调度、API Key 渠道绑定、积分余额查询和用量看板。

当前版本 **1.0.7** · Python **3.9+** · 镜像 **linux/amd64 / linux/arm64**

[版本发布](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases) · [更新记录](CHANGELOG.md) · [部署说明](docs/integration-plan.md) · [API 说明](docs/api.md) · [账号与调度](docs/account-scheduling.md)

## 主要功能

- 国内、国际账号池独立调度；API Key 可固定绑定渠道或跟随全局默认出口。
- 每个账号可设置持久化优先级，数字越小越早调用；同优先级内继续使用原有调度策略。
- 按 API Key 对应渠道汇总全部账号的剩余积分，支持 DeepSeek、Kimi、OpenAI 旧版账单等响应格式。
- 按 Key 查询 Token 用量；看板展示账号、模型、Key、请求流水、性能和成本估算。
- Token 数量与生成速度自动使用 `K/M/B`；请求次数、积分和金额各自使用对应格式。
- 支持账号导入／导出、OAuth 登录、代理槽、保留积分、每日限额、签到和任务调度。
- 可选本地网络搜索与网页抓取，默认关闭，详见[网络工具说明](docs/research/web-search-support.md)。

## 快速启动

### Docker Compose

```bash
git clone https://github.com/Albert-Li-Sz/Workbody-FHUB.git
cd Workbody-FHUB
docker compose pull
docker compose up -d
docker compose logs workbody-fhub
```

默认使用 `ghcr.io/albert-li-sz/workbody-fhub:1.0.7`。首次启动日志会显示面板初始密码和局域网 API Key。

| 入口 | 地址 |
| --- | --- |
| 管理面板 | `http://<服务器IP>:8788/` |
| OpenAI Base URL | `http://<服务器IP>:8788/v1` |
| 健康与运行版本 | `http://<服务器IP>:8788/health` |

账号及设置持久化在 `./accounts`，用量日志在 `./usage`。容器替换后继续挂载这两个目录即可保留账号、优先级、Key 和历史用量。公网访问建议使用 HTTPS 反向代理。

### 本机运行

```bash
python3 wb_proxy.py --host 127.0.0.1 --port 8788
```

也可使用项目启动脚本：Windows 双击 `start-wb-proxy.bat`，macOS 双击 `start-wb-proxy.command`，Linux 执行 `./start-wb-proxy.sh`。打开面板登录并添加或导入账号，然后在设置页创建 API Key。

面板密码与 API Key 分别管理。首次启动生成随机面板密码；可通过 `PANEL_PASSWORD_FILE` 指定私有密码文件。已有自定义密码保留。详细参数和 1Panel 操作见[部署说明](docs/integration-plan.md)。

## 账号优先级

进入 **账号池与运维**，选择国内或国际区域，在账号行的 **调度优先级** 输入数字，再点击 **保存优先级**。

- 默认 `100`，允许 `0–2147483647` 的整数；`0` 最优先。
- 名称旁的“优先级”徽章显示已保存值，输入框下面显示“未保存”或“已保存 · 重启保留”。
- 保存成功后写入账号 JSON，重启、凭证刷新和未指定优先级的重新登录会保留该值。
- 当前优先级没有可用账号时尝试下一优先级；停用、冷却、限额等规则仍参与可用性判断。

调度与会话粘性的具体规则见[账号与调度说明](docs/account-scheduling.md)。

## API 接入

把客户端 Base URL 设置为 `http://<服务器IP>:8788/v1`，API Key 使用面板生成的网关 Key。模型 ID 以该 Key 的 `GET /v1/models` 返回结果为准。

```bash
curl http://127.0.0.1:8788/v1/models \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

| 功能 | 路径 |
| --- | --- |
| 对话与流式生成 | `POST /v1/chat/completions` |
| Responses | `POST /v1/responses` |
| Anthropic Messages | `POST /v1/messages` |
| 模型列表／详情 | `GET /v1/models`、`GET /v1/models/{id}` |
| 原生积分余额 | `GET /api/billing/balance` |
| 当前 Key 的 Token 消耗 | `GET /api/billing/usage` |
| DeepSeek 余额格式 | `GET /user/balance`、`GET /v1/user/balance` |
| Kimi 官方余额格式 | `GET /v1/users/me/balance` |
| 千问／阿里云余额格式 | `GET /?Action=QueryAccountBalance` |
| OpenAI 旧版余额格式 | `GET /dashboard/billing/credit_grants` |
| GLM／MiniMax 网关扩展 | `GET /api/billing/balance/glm`、`GET /api/billing/balance/minimax` |

也可使用 `GET /api/billing/balance?provider=kimi`，`provider` 支持 `deepseek`、`kimi`、`glm`、`qwen`、`minimax`、`openai`。完整别名、返回示例、用量范围和错误码见[API 说明](docs/api.md)。

**余额来源与单位：**所有适配入口返回网关 Key 对应的国内或国际渠道内全部账号的积分总和，包含停用账号；金额字段保留客户端所需结构，数值单位始终是 WorkBuddy 积分。千问入口使用网关 Bearer Key，采用阿里云余额响应格式；OpenAI 为旧版账单兼容。GLM、MiniMax 的入口属于本网关扩展，目前未在官方文档中找到普通模型 Key 可用的公开现金余额接口。详见[兼容范围](docs/api.md#余额协议兼容范围)。

## 升级到 1.0.7

在原部署目录保留 `accounts`、`usage` 和 Compose 配置，指定新镜像后重新创建容器：

```bash
export WORKBODY_IMAGE=ghcr.io/albert-li-sz/workbody-fhub:1.0.7
docker compose pull
docker compose up -d
curl http://127.0.0.1:8788/health
```

确认 `/health` 的 `version` 为 `1.0.7`，再刷新面板。拉取镜像后需要重新创建容器，运行中的旧进程会继续提供旧界面和接口。备份、回滚和 404 排查见[部署与迁移说明](docs/integration-plan.md)。

## 开发与发布

项目主要使用 Python 标准库；测试目录包含 Python 与 JavaScript 套件。GitHub CI 覆盖 Linux Python 3.9／3.12、Windows Python 3.12，发布工作流构建双架构镜像并完成镜像检查后更新 `latest`。

```bash
python3 tests/run_all.py
```

本地运行 JavaScript 套件需要 Node.js。历史审计记录见 [docs](docs/)；已发布产物及校验文件见对应 [Release](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases)。

## 来源与许可证

本项目派生自 [ardeyouxipianyi/workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub)，基于上游 **1.6.13**。分支采用 [Apache-2.0](LICENSE)，保留上游 [MIT 许可证原文](LICENSE.upstream)、[版本记录](CHANGELOG.upstream.md)、Vibe Coding 声明和贡献者致谢，完整内容见[来源与致谢](docs/credits.md)。

本项目为非官方自托管网关，使用已有合法授权账号，不提供账号或额度。请遵守上游服务条款与适用的使用限制。
