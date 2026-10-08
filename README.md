# Workbody-FHUB — WorkBuddy 国内与国际多账号网关

<p align="center">
  <a href="https://github.com/Albert-Li-Sz/Workbody-FHUB/releases"><img src="https://img.shields.io/badge/Workbody_FHUB-v1.0.6-2496ED?style=flat-square" alt="Workbody-FHUB 1.0.6"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/API-OpenAI_Compatible-412991?style=flat-square" alt="OpenAI API">
  <img src="https://img.shields.io/badge/Dual_Realm-Intl_&_CN-0DBD8B?style=flat-square" alt="Dual Realm">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-green.svg?style=flat-square" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/Vibe_Coding-100%25-ff69b4?style=flat-square" alt="Vibe Coding">
</p>

Workbody-FHUB 是 [ardeyouxipianyi/workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub) 的衍生项目，当前版本 **1.0.6**，基于上游 **1.6.13**。本衍生项目沿用目标仓库的 [Apache-2.0 许可证](LICENSE)；原项目的 Vibe Coding 声明、致谢、贡献者、免责声明和 [MIT 许可证原文](LICENSE.upstream)均保留。本分支负责自己的安全修复、网络搜索和镜像构建。

把腾讯 **[www.workbuddy.ai](https://www.workbuddy.ai)**（国际版）与 **[codebuddy.cn](https://www.codebuddy.cn)**（国内版）的原生服务封装成标准 OpenAI 兼容接口（Chat Completions 与 Responses API），并补齐多账号调度与运维能力：

本分支沿用 Python + Docker / 1Panel 部署，模型页保留 **WorkBuddy 国内 / WorkBuddy 国际** 两个渠道，API Key 可固定绑定对应出口，模型目录切换只影响展示。账号导入保留产品身份、代理绑定和添加时间。本地网络搜索采用 DuckDuckGo HTML，异常时最多回退一次至 Lite，并提供短期缓存、并发合并与响应大小限制。部署与迁移见 [项目说明](docs/integration-plan.md)，搜索行为见 [网络搜索说明](docs/research/web-search-support.md)，搜索修复见 [早期审计记录](docs/audit-2026-10-07.md)，本次全项目审计及修复见 [1.0.1 修复报告](docs/project-repair-2026-10-07.md)。

- **开箱即用**：绿色包自带精简 Python，双击脚本即启；
- **双区域独立路由**：国际版 / 国内版独立配置与调度，看板一键切换，状态落盘；
- **模型目录对齐官方桌面端**：剔除代码补全通道与底层专线变体，能力与规格按桌面端宣告；
- **设备指纹隔离 (`derive_id`)**：以账号 UID 稳定派生机器码与会话标识，防多号关联风控；
- **OAuth 免客户端登录**：看板点链接完成授权即自动入库；
- **桌面客户端凭据导入**：直接读本机已登录的 WorkBuddy 桌面端账号，客户端加密存储的 token 也能就地解密；
- **国内版自动化**：每日签到、成长任务与积分任务自动接取点亮领奖、猫猫日常旅行与连续打卡；
- **国际版每日活跃打卡**：自动建网页端会话并接上沙箱把这一轮真正跑完（ACP over HTTP+SSE），全自动领满官方每日活跃 30/50 积分奖励；
- **后台定时调度器**：09:00/21:00 国内签到旅行与国际版活跃打卡 · 22:00 保活 · 01:00 夜猫；
- **每日积分限额**：账号当日积分花超后只服务免费模型，付费模型自动切号，次日 0 点解封（默认关闭，可设阈值）；
- **按模型每日 Token 限额**：单模型 token 用满只禁该模型，同账号其他模型照常（默认不限）；
- **OpenRouter 价估算**：把请求 token 按 OpenRouter 公布的模型价折算成等价花费（按条件定价的模型按每条请求的输入长度与时间取档），定价按版本留档、刷新间隔可配，每条请求都标出用的是哪一版，人民币/美元可切，看板多处并列展示；**上游新增模型无需改代码即可自动进入取价**（取价输入 = 内置目录 ∪ 网关实时目录；两次取价之间就被调用就按需补价；带渠道后缀的名字向基准模型继承，命不中就不定价），仍未定价的模型在面板列出原因，可手填 OpenRouter id 收口；
- **三协议支持**：Chat Completions、Responses API（Codex）与原生 Anthropic Messages API（Claude Code / Anthropic SDK）；
- **Web 看板**：指标卡片、模型性能与用量大表、按 API Key 的用量归属、实时请求流水一屏可查。
- **积分与权益包明细查看**：完整解析账号各套餐包/加量包额度、已用、剩余、生效状态及有效期周期，看板一键弹窗并支持实时刷新；

原项目声明（保留原文）：

> ⚡ **Vibe Coding 产物**：本项目为 100% Vibe Coding 协同产物，由人类开发者提出架构与业务意图，AI 助手端到端完成逆向分析、链路调度、WAF 指纹脱敏与界面编写。

---

## 一、快速启动

### 1. 本机单机使用

**Windows**：双击 **`start-wb-proxy.bat`**，保持窗口运行。**macOS**：双击 **`start-wb-proxy.command`**（首次被 Gatekeeper 拦截时，右键 →「打开」确认一次），或在终端执行：

```bash
./start-wb-proxy.sh          # 默认 8788 端口
./start-wb-proxy.sh 9000     # 自定义端口
```

启动后：

- **API 接口地址**：`http://127.0.0.1:8788/v1`
- **Web 监控看板**：`http://127.0.0.1:8788/`

首次启动若无账号，打开看板点 **「+ 添加账号 (OAuth)」** 完成授权即自动入库。macOS 启动脚本会自动挑选可用的 Python 3.9+（`/usr/bin/python3`、Homebrew 或包内 `python/bin/python3`），未安装可用 `xcode-select --install` / `brew install python`。

请求头和请求体默认分别有 **30 秒接收时限**，可通过环境变量 `WB_HTTP_READ_TIMEOUT` 调整（正数，单位秒）；持续少量发送数据不会延长时限，上游等待和正常流式生成不受这个接收时限影响。提前拒绝且请求体未读完时，网关会立即返回错误并用 `Connection: close` 关闭连接，客户端应重新连接；完整请求仍支持连接复用。对话并发限制也包含请求体上传阶段。

Unix 系统上的账号目录权限为 `0700`，凭证和 Key 设置文件权限为 `0600`；临时文件从创建起即限制访问，启动或读取旧文件时会收紧旧权限。Windows 的访问权限仍由系统 ACL 管理。

> zip 解压后若提示权限不足，先执行一次：
> `chmod +x start-wb-proxy.sh start-wb-proxy.command start-wb-proxy-lan.sh start-wb-proxy-lan.command allow-firewall.command`

### 2. 面板访问密码

首次启动自动生成随机面板密码，仅保存 PBKDF2-SHA256 摘要，明文只在该次启动日志的 `PANEL BOOTSTRAP PASSWORD` 行显示。已有自定义密码继续有效；旧默认 `admin` 会在启动时自动替换，且不能再设置为新密码。该密码与 API Key 独立。

可用 `PANEL_PASSWORD` / `--panel-password` 指定密码；Docker secret 或私有文件可通过 `PANEL_PASSWORD_FILE` / `--panel-password-file` 读取。忘记密码时可用这些启动参数设置新密码。面板中的密码修改仍验证当前密码。持续设置 `PANEL_PASSWORD` 或密码文件时，每次重启都会覆盖网页修改；面板会提示这一状态。登录密码不再通过 URL 参数传递。

### 3. 局域网共享模式
允许局域网内其他设备（手机、平板、协同电脑）访问：

- **Windows**：双击 `start-wb-proxy-lan.bat`；**macOS**：双击 `start-wb-proxy-lan.command`，或：

```bash
./start-wb-proxy-lan.sh              # 端口 8788，自动生成/复用 API Key
./start-wb-proxy-lan.sh 8788 我的Key  # 自定义端口与 Key
```

- **Base URL**：`http://<本机局域网IP>:8788/v1`；带密钥直达面板：`http://<IP>:8788/?key=生成的Key`；
- **API Key**：不使用写死的默认密钥，首次启动生成高强度随机 Key 保存到 `accounts/settings.json` 并在终端打印，重启复用；也可用第二个参数传入自己的 Key（以传入的为准）；
- **macOS 防火墙**：首次监听端口时系统会询问是否允许 Python 接受连接，选「允许」；macOS 15+ 还需在「系统设置 → 隐私与安全性 → 本地网络」中允许终端访问。可用 `./allow-firewall.command` 查看状态并把 Python 加入允许列表。

---

### 4. 多 API Key 管理与出口绑定

在「设置」页可管理多个 API Key，并为每个 Key 指定独立出口——不同客户端各用各的 Key，国内 / 国外流量互不干扰，无需频繁切换全局出口：

- **添加与生成**：输入名称后点「生成随机 Key」，可随时复制；
- **出口绑定**：可固定走 🌐 国际版（`www.workbuddy.ai`）或 🇨🇳 国内版（`copilot.tencent.com`）；不绑定则跟随看板顶部的全局出口开关；
- **模型限制**：可为每个 Key 填写允许调用的模型（如 `deepseek*`、`gpt-6-astra`，支持 `*` 通配，多个用逗号分隔）；留空表示不限制。不在列表内的模型请求在本机直接返回可读的 400，既不会送达上游、也不会消耗任何额度——用来挡掉客户端背景请求偷偷调用的付费模型；
- **启停与删除**：可单独启用 / 停用；删除会立刻抹掉密钥（该 Key 再也无法调用），但条目本身以只读形式留在「设置」页底部的「已删除」折叠区，好让看板里的历史用量仍然显示它的名字；所有 Key 保存在 `accounts/settings.json`，重启保持；
- **用量归因**：看板「数据指标」页在账号表下方多一张按 API Key 归属的表——每个 Key 的请求数、Token、缓存命中、积分与模型分布（窗口内最多列 5 个模型，其余并入「其他」），口径与账号表一致，两表的请求数应当相等。该维度从升级后开始记录，更早的请求会一直留在「(切换前)」一行里；没绑定出口却两个出口都用过的 Key 会标成「跟随 · 混合」，它的积分是两套价格相加的结果；
- **防冲突**：面板保存过 Key 后，启动命令或脚本里的旧参数（如 `--api-key`）自动失效；
- **区域自检**：Key 绑定的出口与其请求的模型不匹配时（如用国际版 Key 调国内独占的 `deepseek-v4-pro`），直接返回可读的 400 校验错误，而不是上游晦涩的 WAF 拒流报错。

### 5. Workbody-FHUB Docker 镜像

云镜像发布到 **`ghcr.io/albert-li-sz/workbody-fhub`**，包含 `linux/amd64`、`linux/arm64`，固定版本为 `1.0.6`，稳定版本别名为 `latest`。发布和构建状态可在[本仓库 Releases](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases)及[镜像工作流](https://github.com/Albert-Li-Sz/Workbody-FHUB/actions/workflows/docker-publish.yml)查看。

```bash
docker compose pull
docker compose up -d
# 或在当前项目目录执行
./quick-deploy.sh
```

默认 `docker-compose.yml` 直接拉取已发布的云镜像，端口映射固定为 **`0.0.0.0:8788:8788`**，可通过服务器 IP 访问：

- **Web 看板**：`http://<服务器IP>:8788/`
- **API Base URL**：`http://<服务器IP>:8788/v1`

账号和日志继续挂载 `./accounts`、`./usage`。首次启动密码和 API Key 见 `docker compose logs workbody-fhub`。更新时通过 `WORKBODY_IMAGE` 指定目标版本，然后重新执行 `docker compose pull` 和 `docker compose up -d`，或运行 `./quick-deploy.sh`。

容器支持 `PUID` / `PGID`（默认 `0:0`；使用普通 UID 时请先为该 UID 准备可写的 `accounts`、`usage` 目录），并带 `/health` 健康检查。代码中的 WorkBuddy 账号代理槽继续路由模型，`WB_WEB_PROXY` 单独路由网络工具。

在「设置 → 代理槽位」填写 `http://host:port`、`socks5://host:port` 或 `socks5h://host:port`，需要认证时单独填写用户名和密码，再保存并绑定账号。`socks5` 在网关解析目标域名，`socks5h` 交给代理解析；旧的 `http://user:password@host:port` 格式也可导入，保存时会拆成独立字段。同一地址可配置多个使用不同凭据的槽位。账号 API、积分刷新、代理测试和网页打卡通道均使用所绑定槽位。

搜索代理可在 `.env` 中分别设置 `WB_WEB_PROXY`、`WB_WEB_PROXY_USERNAME`、`WB_WEB_PROXY_PASSWORD`，修改后运行 `docker compose up -d`。用户名、密码留空时使用 URL 中的凭据。搜索即使通过 SOCKS5h，也会连接本机校验后的公网 IP，保留原始 Host 与 TLS 域名验证。

维护者可使用 `Dockerfile` 独立构建及保存镜像。默认底镜采用 Docker 官方 Python 3.11 镜像的 ECR 来源，并固定内容摘要；`docker build --build-arg PYTHON_IMAGE=可信底镜` 可覆盖来源。构建上下文排除账号、日志、`.env*` 和凭据文件。[Docker 官方镜像的 ECR 来源说明](https://aws.amazon.com/blogs/containers/docker-official-images-now-available-on-amazon-elastic-container-registry-public/)。

```bash
# 独立构建及保存，便于向其他服务器导入
docker build -t workbody-fhub:1.0.6 .
docker save workbody-fhub:1.0.6 | gzip > workbody-fhub-1.0.6.tar.gz
# 目标主机：docker load < workbody-fhub-1.0.6.tar.gz
```

构建双架构镜像并验证两种架构的启动、鉴权和关键回归：

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t workbody-fhub:1.0.6 --load .
python3 scripts/verify_image.py workbody-fhub:1.0.6 --non-root
```

验证脚本使用隔离的临时数据卷与 `--network none`，结束后清理测试容器。审计发现、修复证据和剩余验证边界见[修复报告](docs/project-repair-2026-10-07.md)。

发布流程先校验统一版本与测试，再构建并推送两种架构的固定版本镜像；成品通过启动、鉴权、关键回归及普通 UID 验证后，再更新 `latest`。配置 Docker Hub 凭据时也发布同名镜像。验证已有云镜像可增加 `--revision v1.0.6 --pull`，按指定 release 比对源码。镜像包含 release 源码及两份许可证。

### 6. 测试

全部测试集中在 `tests/`，一条命令跑完：

```bash
python tests/run_all.py            # 全部套件
python tests/run_all.py realm      # 只跑名字里含 realm 的
```

- 90 个套件：74 个 Python + 16 个 JS；JS 需要 PATH 上有 `node`，缺失时会跳过并提示。每个套件默认 180 秒超时，可用 `WB_TEST_TIMEOUT_SECONDS` 调整。
- `tests/_mobile_check.py` 是独立的 Playwright 手机/桌面布局检查器（需自行安装 Playwright），按需手动运行，不在上面的套件集里；fixtures／截图默认放系统 temp，可用 `WB_MOBILE_FIXTURES` / `WB_MOBILE_SHOTS` 覆盖，Windows 可直接运行。
- CI（`.github/workflows/tests.yml`）跑同一条命令：Ubuntu 上 python 3.9 与 3.12（3.9 是本项目声称的最低版本），Windows 上 python 3.12。推送 `v*` tag 时额外断言 **tag == 源码版本**（以 `wb_version.VERSION` 为准，同时检查 API、Dockerfile、Compose 与 README；`-ci` 演练 tag 豁免 tag 比较）。

---

## 二、核心特性详解

### 1. 模型列表严格按照桌面应用 1:1 对齐

针对官方本地配置清单（50+ 底层模型）进行了深度清洗，剔除行内代码补全专用模型（如 `codewise-*`、`completion-gf`、`hunyuan-3b/7b`）与底层多云专线变体（如 `*-volc`、`*-lkeap`），严格对齐官方Windows桌面端，每个模型均宣告完整桌面软件中显示的上下文窗口（K/M 规范）、单次最大输出、视觉支持、工具调用以及推理档位。

* **🌐 国际版 (17 个)**：`hy4-preview-f`、`hy3`、`deepseek-v4.1-flash`、`gpt-6-astra`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.5`、`gpt-5.4`、`grok-4.7`、`gemini-3.5-flash`、`glm-5.3-flash`、`glm-5.3`、`glm-5.2`、`kimi-k3`、`kimi-k2.6`、`kimi-k2.8-preview`。
* **🇨🇳 国内版 (14 个)**：`hy4-preview-f`、`hy3`、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`glm-5.3`、`glm-5.3-flash`、`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`minimax-m3`、`kimi-k3-1`、`kimi-k2.8-preview`、`kimi-k2.7`、`kimi-k2.6`。

> 清单与上游 `GET /v3/config` 的 `agents[cli].models` 保持同步，没装桌面端的机器也能取到同一份（接口不可用时依次回落到桌面端缓存文件、内置快照）。过滤规则：去掉 5 个档位别名与 `auto`，去掉 `-sg` / `-x` 变体，同名的只留 0.00 倍率那一档。上游新上的模型无需发版即可出现在 `/v1/models`。

> 💡 **关于同模型跨区域混合轮询的说明**：
> 目前对于同时存在于国内版和国际版的同名模型（如 `deepseek-v4.1-flash` 等），**暂未实现跨国内/国际账号的自动混合轮询**，而是作为两个独立区域分别配置与调度，请求只能走当前所选网关的独立出口。这主要是出于各区域网络环境隔离、出站指纹对齐与账号防风控安全考量；待作者后续实测验证确认长期使用稳定且无封号风险后，会尽快跟进并补齐同名模型的跨区域混合轮询能力。

### 2. 稳定物理设备指纹隔离 (`derive_id`)
国际版与国内版共用同一套算法内核：以账号 UID 结合固定业务盐值单向哈希派生机器码与会话标识——同一账号每次出站都来自同一台虚拟设备，不随机漂移；不同账号之间彼此独立，阻断跨账号关联风控。

### 3. 国内版每日签到、成长任务与积分任务全自动完成
- **每日签到**：一键完成国内版打卡领积分；
- **成长任务与积分任务**：自动批量接取未接任务，构造规范行为事件上报点亮（画布创建、灵感案例、模板使用、模型体验、多轮对话等 14 项），并自动领奖入账；
- **猫猫日常**：自动检查旅行状态，在家自动派出、归来自动领奖。

### 4. 后台常驻定时调度器 (Scheduler) 与每日自动化
常驻后台，每日按固定整点执行自动化运维排程：

- **每日 09:00 & 21:00**：国内版账号自动签到与猫猫旅行闭环；国际版账号自动执行每日活跃打卡对话（领官方每日 30/50 积分福利）；
- **每日 22:00**：集中扫描全库账号，Token 剩余寿命不足 2 小时自动调用 Refresh Token 保活；
- **每日 01:00**：深夜时段自动执行夜猫子任务；
- **国际版动态自适应**：切换至国际版视图时，看板顶部提供「每日活跃打卡 (国际版)」一键触发按钮。

### 5. 保留积分（避免余额被用尽）
看板「设置 → 保留积分」可设定一个最低余额，账号剩余积分低于该值时不再接单，账号行会显示「保留积分」标记。

- 上游在余额耗尽后会给账号发提醒短信，设一个阈值即可避免余额被用到 0；
- 填 `0` 表示关闭，这是默认值；
- 判定依据是最近一次查询到的余额（看板「积分」列），从未查询过余额的账号不受影响；
- 账号只是停止接单，仍留在池中并继续定时任务（签到与猫猫旅行本身是赚积分），充值后自动恢复可用。

### 6. 每日积分限额与按模型 Token 限额

两个与「保留积分」并列的账号级守卫，都按**本地时间 0 点**自动解封，且都只在请求路径生效（定时任务不受影响）：

- **每日积分限额**（看板「设置 → 每日积分限额」，**默认 0 即关闭**）：账号当日消费的积分（按上游返回的 `credit` 累计）达到该值后，只允许请求**免费模型**（目录中标记为 `x0.00` 的模型，如免费期的 `deepseek-v4.1-flash`），需要花费积分的模型自动切到其他账号。免费/付费以各出口自己的模型目录为准——同一个模型 id 在不同出口的免费状态可以不同。
- **按模型每日 Token 限额**（看板「设置 → 按模型每日 Token 限额」，默认 `0` 即不限）：账号在**单个模型**上当日消耗的 token 达到该值后，只把该模型切到其他账号，同一账号的其他模型照常服务。例如把 `hy4-preview` 用满 2 亿后，该账号的 `hy4-preview` 被跳过，但 `deepseek-v4.1-flash` 仍然可用。

两者都是**单账号独立计数**：A 号用满不影响 B 号。账号行会显示「积分限额」徽章与 `模型 · N tok 达限` 标记（悬停看今日用量）；全部账号都达额时请求返回 `429`（文案说明本地 0 点恢复，`Retry-After` 指向 0 点）。统计与「每日 Token 限额」共用同一份增量扫描，热路径开销不变。
### 7. OpenRouter 价估算（等价 token 花费）

把每条请求的 token 消耗按 **OpenRouter 公布的模型价**折算成等价金额，回答「这些 token 放在 OpenRouter 上值多少钱」——与账号实际扣除的积分（`credit`）是两个口径，看板里并列显示：

- **定价来源**：OpenRouter 模型目录（`/api/v1/models`，美元 / 每 token，按版本里的汇率折算成人民币）。取的是**模型级公布价**——OpenRouter 模型页上展示的那个数字，对应它默认路由的那家 provider；同一个模型在 OpenRouter 上往往由多家 provider 承接、价格各异（实测 `deepseek-v4.1-flash` 有 33 家、`gpt-6-astra` 有 7 家），换一家可能更便宜，所以这个数是「OpenRouter 公布的该模型价格」，不是「最省的买法」。`wb_pricing.py` 里另内嵌一份快照作为出厂价（镜像自包含，无需额外文件），供还没有历史的机器兜底；`tools/fetch_pricing.py` 用来重新生成它（`--embed` 回写内嵌副本、`--dry-run` 只打印）。
- **计价口径**：输入按缓存命中/未命中两档单价拆分（`cached_tokens`），输出单独单价，乘上 token 数再按汇率折算。输出的 token 数取上游的 `completion_tokens`，它**已经包含推理 token**（上游把 `reasoning_tokens` 记在 completion 内，实测与 1.5 万条历史行都如此，`total_tokens = prompt + completion`），所以推理 token 不另计——单独再加会重复计费；这条前提有测试钉住。OpenRouter 上有不少模型是**按条件定价**的，条件写在条目的 `overrides` 里，共两类，都会被原样搬进快照的 `bands`：
  - **按输入长度**：超过阈值后改用更贵的价——`gpt-6-astra`、`gpt-5.5`、`gpt-5.4`、`gpt-5.6-*` 在 272000 token 以上翻倍，`grok-4.7` 在 200000 以上翻倍（OpenRouter 的 `overrides` 是按阈值升序排列的）；
  - **按时段（UTC）**：`hy3`、`hy3-x`、`hy4-preview` 系列——北京时间 08:00–24:00 比 00:00–08:00 贵，`hy3` 约贵 60%。

  计价时按每条请求的输入长度与时间在 `bands` 里取**最紧的那一条**，取不到就退回该模型的基准价，所以最坏退化成单一价而不会算成 0。`overrides` 里的缓存写入价与音频价计不了：本地 usage 日志只记 prompt / completion / reasoning / cached，没有对应的 token 数。既没有厂商一手页，也没有本地维护的峰谷表，各处展示的都是同一个口径。
- **定价策略与引用**：网关每隔一段时间（「设置 → 定价刷新」，默认 **5 分钟**，单位即分钟，填 0 关闭自动刷新）去 OpenRouter 取一次价。周期短并没有额外代价：只有价格真的变了才写策略与时间轴，价格不动时每个周期只是一次 HTTP GET。每份价格按**内容**存成一条独立的「定价策略」（模型 + 各档价 + 汇率一起做哈希当 id），内容相同的只存一条：同一个模型若走出 A → B → A，表里始终只有 A、B 两条，第三次直接指回 A。另有一条**时间轴**声明每个模型在各时刻生效的是哪一条策略，只在生效分配真的变化时才追加一行——价格长期不动时，取再多次也不会长大。
  - **每条请求记的是「引用了哪条策略」**，不内嵌价格：`usage.jsonl` 每行带 `cost_policy`（策略 id）。计价按这个 id 直接查，所以之后调价不会改写之前的数字；悬停里会写出策略 id 与它首次取到的时刻。
  - 请求发生在某模型**还没有价**的时候，用之后第一次取到的价补算，并在金额后标 `*`。
  - **无用策略会被清掉**：抓取后若产生了新策略，就顺带清理一次——没有任何请求引用、且已不是当前生效的那条会被删；每个模型至少留一条，刚取到的那批不动。
  - 所有汇总——按模型、按账号、按区间的——都是把每条请求各自的估算**加起来**，而不是拿汇总 token 乘一个单价重算。
  - 面板上能看当前生效的是哪一份（可展开逐模型查看）、策略表条数、上次/下次取价时间与最后一次失败原因，也能点「立即取价」手动取一次。
- **新增模型自动取价（无需改代码）**：取价的候选清单 = 内置目录 `wb_catalog.py` ∪ 网关**实时目录**里新增的模型（intl / cn 两个区域各自的实时目录一起并进来，与 `/v1/models` 走同一套过滤，别名与 `-sg`/`-x` 之类付费档位不进清单），所以上游新上架一个名字，5 分钟内就会进入取价并出现在策略表/时间线里；若它在这两次取价之间就被调用，**第一笔请求**也会带上价——按需补价用最近一次抓取留在内存里的目录登记策略，请求路径不发任何网络请求，命不中还是老老实实未定价。匹配顺序是「面板手填覆盖 → 人工覆盖表 `OVERRIDES` → 名字归一化后全等且唯一 → **变体后缀继承**（剥掉 `-lkeap`、`-taiji`、`-volc`、`-sg` 这类渠道/发行后缀，拿基名重走前三步，仍要求唯一命中）」，继承来的策略记 `via=variant` 与 `inherited_from`，面板能看出这条价不是同名匹配来的；`-f`/`-dev`/`-x` 故意不剥（它们是 hub 自己的档位，单价可能不同）。这条规则可在「设置 → 定价刷新 → 变体后缀继承」整体关掉，关掉即恢复「只有覆盖表与同名匹配才定价」。整套匹配仍然遵循「宁可漏也不错」：多轮都没命中的就不写价，费用列显示 `—`。
- **未定价可见化与手填收口**：`/pricing` 返回未定价清单，每条带分类——`alias`（`default-model` 一类虚拟别名，不是模型，不计入缺口统计）、`or_missing`（OpenRouter 无对应）、`variant_unmatched`（剥后缀后仍无唯一基准），并给出相似度 top 3 候选（**仅建议，绝不自动采用**）。面板「设置 → 定价刷新」下可直接展开逐条查看，为某条模型手填一个 OpenRouter id 并「登记」：映射写进数据目录的 `pricing-overrides.json`（运行期覆盖，不改源码里的 `OVERRIDES`，升级镜像不丢），登记后立即触发一次取价；留空提交即删除该映射。
- **`tools/fetch_pricing.py` 支持 `--extra-ids-file <path>`**（离线内置快照工具）：默认仍只读内置静态目录、不引入网络依赖，需要额外 id 时给一份「每行一个模型名」的文件即可，与运行时的并集输入同一条 `build_snapshot()` 路径。
- **展示位置**：数据指标看板 KPI 卡片「OpenRouter 价估算」（跟随今日/本周/本月/全部区间切换）、各账号用量透视**最后一列**、模型性能与用量一览**最后一列**（含合计行）、网关与运维页「OpenRouter 价估算」卡片、最近请求**最后一列**（逐条金额，悬停可看完整定价策略，见下条；补算的金额后带 `*`）。
- **悬停即可看清单条请求的价是怎么来的**：最近请求最后一列的金额带一个自绘气泡，鼠标停上去给出——**三档原始单价**（缓存命中输入 / 缓存未命中输入 / 输出，USD / 每百万 token，按策略原样显示、不做折算）、版本里的汇率与折算说明、**匹配来源的完整证据链**（`direct` 给出命中的 OpenRouter id；`override` 给出「原名 → 映射到的 id」；`variant` 给出「原名 → 基准名 → OpenRouter id」并标明剥掉的后缀）、命中的**条件档位与该档三档价**、策略 id 与它首次取到的时刻、以及补算标记 `*`；没有定价的行仍只说「该模型暂无定价数据」，不编数字。这些字段由 `/usage/recent` 每行直接带出（`cost_rates`、`cost_unit`、`cost_currency`、`cost_usd_cny`、`cost_or_id`、`cost_via`、`cost_inherited_from`、`cost_override_from`、`cost_band_note`、`cost_via_derived`），面板不为展示再开接口，未定价整组为 `null`、与 `cost_cny` 同口径。气泡挂在 `body` 上且 `pointer-events: none`，不会抢走鼠标；表格每 5 秒整体重画，重画后按行键复位回同一行。**加这些字段没有动计价口径**：`policy_id` 的算法一字未改，全量 15176 行逐行的 `source` 与改动前 0 条失配，历史策略 id 逐条不变；早于 `via` 字段写下的策略行没有记录可查，气泡按当前映射表推断并明确标注是推断（`via_derived=true`），映射表改过或指不到就不认。
- **人民币 / 美元一键切换**：金额按快照汇率换算，选择记在浏览器本地，刷新后保留；快照覆盖不到的模型显示 `—` 并计入「未覆盖」提示，不做猜测。当前未覆盖的只有 4 个真实名字：OpenRouter 尚未收录的 `kimi-k2.8-preview`、目录里对应 Claude-3.7/4.0-Sonnet 的 `default-1.1` / `default-1.2`（OpenRouter 无同名条目），以及 `kimi-k2-instruct-taiji`（剥掉 `-taiji` 后基名仍无唯一对应）；它们都在面板未定价区列出原因与候选，可按需手填映射。另有 5 个档位别名（`default-model` 等）本就不是真实模型，只在清单里标注、不计入缺口统计。

### 8. 本地网络工具（可选，默认关闭）

部分客户端（如 Codex App）会在 Responses 请求里宣告 `web_search` / `web_fetch` 这类服务端工具，而上游没有对应的执行器——声明送上去，模型看得到工具却没有执行器，客户端最后只拿到一句 unsupported call。

看板「设置 → 本地网络工具」打开后，网关把那份声明换成自己的同名 function、拦下模型的调用、在本地执行（搜索走 DuckDuckGo HTML 版，抓页面抓模型给出的 URL），再把结果喂回模型，默认轮数配置为 3（`WB_MAX_WEB_ROUNDS` 可调，配置上限 8；同时最多 16 次工具调用、180 秒编排预算，超限明确失败）；搜索过程会作为 `web_search_call` 卡片事件与 `url_citation` 引用回到客户端。

- **默认关闭**：工具声明原样透传，客户端自己声明的搜索工具照常拿到调用（v1.5.3 之后的既有行为，升级不受影响）；
- 打开后网关会主动出网抓取模型给出的 URL（每次 DNS 解析与重定向都检查公网地址，并固定连接到校验后的 IP），且每轮代跑都会多跑一次上游、多消耗该账号额度；国内网络下 DuckDuckGo 可能连不上，那时模型拿到的是错误文本；
- 搜索先访问 HTML，网络/页面异常时最多回退一次到 Lite；真正无结果不重试，HTTP 429 直接报限流，验证码页不会被当作无结果。成功结果缓存 120 秒、错误冷却 5 秒，最多 128 个查询，同一查询的并发请求共用一次检索；
- 搜索与抓取共用 20 秒请求预算，响应及 gzip 解压后内容均限制为 2 MiB；可用 `WB_WEB_PROXY=http://proxy-host:port` 或 `socks5h://proxy-host:port` 单独指定网络工具出口，并通过 `WB_WEB_PROXY_USERNAME` / `WB_WEB_PROXY_PASSWORD` 设置凭据，未设置代理时沿用进程的 `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY`。账号代理槽不自动控制搜索；
- 代跑接在 Responses 的流式/非流式路径，保留多轮工具历史、调用 ID，并按每轮实际使用的账号记录用量。安全边界与验证结果见[修复报告](docs/project-repair-2026-10-07.md)。
- 只影响声明了这两个工具的客户端，普通 `/v1/chat/completions` 客户端不经过这条路径。

---

## 三、账号添加与管理

打开看板 `http://127.0.0.1:8788/`，在「账号」区域操作：

若上游对某账号的单个模型返回 429，账号行会显示受限模型和预计恢复时间（浏览器本地时间）；该账号仍可用于其他模型。模型冷却状态仅在当前服务进程中保留，重启后清空。

### 方式一：浏览器 OAuth 授权（推荐，免客户端）
1. 点击 **「+ 添加账号 (OAuth)」**；
2. 选择要登录的区域（国际版 / 国内版），点击弹出的官方授权链接并在浏览器完成登录；
3. 程序自动检测回调，完成后账号自动加入账号池，无需手动复制凭证。

### 方式二：从本地桌面应用导入（Windows）
1. 让 **WorkBuddy 桌面客户端保持运行并已登录**（网关要从它的进程内存里取解码密钥，这一步不能省）；
2. 看板点 **「扫描桌面客户端账号」**，弹窗里会列出本机 `.info` 里已登录的国际版 / 国内版账号；
3. 若提示凭据已加密，先点弹窗里的 **「回收密钥」**（只读，实测 1 秒内完成），再点账号行的 **「导入」**。

关于加密凭据：

- 桌面客户端从 2026-09-24 起把 `accessToken` / `refreshToken`（国内版还有 `nickname` / `phoneNumber`）存成 `$wbEncrypted` 信封，网关按客户端 `packages/at-rest-crypto` 的同一套方案（AES-256-GCM + `WB-AAD` 帧头）就地解密，导入的仍是可直接使用的 token；
- 解码密钥（`atRestSecretKey`）编译在客户端的原生模块里、磁盘上没有明文，只能从**正在运行的**桌面端进程内存里找回来。密钥只保存在网关进程内存中，不落盘、不写日志，网关重启后重新回收一次即可；
- 这一步只读目标进程的私有内存（`OpenProcess(PROCESS_VM_READ)` + `ReadProcessMemory`），不会向客户端写任何东西；提示权限不足时，以管理员身份启动网关再试一次；
- 仅 Windows 可用；Docker / Linux / macOS 下请用方式一。

~~相关代码保留未删（前端 `scanDesktop()` 与后端 `/accounts/import/desktop` 都在），等解密打通或改走其他凭据来源之后再放出来。~~

---

## 四、客户端配置与接入

- **API 接口地址 (Base URL)**：`http://127.0.0.1:8788/v1`（局域网为 `http://<局域网IP>:8788/v1`）
- **API Key**：
  - 本机单机模式（未配置 Key 且未开 LAN）：可留空或填任意字符；
  - 已在看板配置 Key 或 LAN 模式：在看板「设置」页面添加或复制已绑好出口的 API Key（如固定走国际版的 Key 或国内版的 Key）。
- **模型名称**：填入 `/v1/models` 中列出的任意官方对齐模型 ID（如 `deepseek-v4.1-flash`、`gpt-6-astra`、`glm-5.3` 等）

### Codex CLI / Claude Code (Responses API)
网关原生内置 Responses 协议双向转换与 WAF 指纹脱敏：
```bash
export OPENAI_BASE_URL="http://127.0.0.1:8788/v1"
export OPENAI_API_KEY="你在看板设置中添加并绑定的API_Key"
```

### Claude Code (原生 Anthropic Messages API)

网关同样原生实现 Anthropic Messages 协议（`/v1/messages`，流式与非流式），Claude Code / Anthropic SDK 可以直连，不再经过 Responses 转换层：

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8788"
export ANTHROPIC_API_KEY="你在看板设置中添加并绑定的API_Key"
```

模型名沿用网关的官方对齐 ID（如 `deepseek-v4.1-flash`、`gpt-6-astra`、`glm-5.3`）。

协议映射与边界（都按 Anthropic 官方 Messages 规格实现）：

- `system`（字符串或文本块数组）→ 上游 system 消息；`text` / `image` / `document` / `tool_use` / `tool_result` 内容块双向转换；`tools` + `tool_choice` + `disable_parallel_tool_use`、`stop_sequences`、`metadata.user_id`、`thinking` / `output_config.effort` 全部映射到上游对应字段；
- 流式输出是原生事件序列：`message_start` → `content_block_start` / `content_block_delta`（`text_delta` / `input_json_delta`）→ `content_block_stop` → `message_delta`（含 `stop_reason` 与用量）→ `message_stop`；
- 鉴权接受 `x-api-key` 或 `Authorization: Bearer`，错误一律用 Anthropic 的 `{"type":"error","error":{"type":...}}` 信封；
- 服务端工具（`web_search` 等，Anthropic 侧执行的）上游不支持，会被丢弃并在 system 里注明，不会伪造调用；
- `thinking` / `redacted_thinking` 块不会回放（上游不提供可验证签名）；`top_k`、`cache_control`、`context_management` 与 `betas` 会被忽略；
- `/v1/messages/count_tokens` 返回的是网关的 CJK 感知估算值（与用量统计同一套估算器），**不是**官方分词器的精确值。

---

## 五、看板与接口一览

访问 `http://127.0.0.1:8788/` 即可使用集成看板，核心接口包括：

「数据指标看板」页顶部可切换统计口径：**今日 / 本周 / 本月 / 全部历史 / 自定义**。本周自周一零点起算、本月自 1 号零点起算，自定义可指定起止时间（任一侧留空表示不限）。切换后 KPI 卡片、账号用量透视表与模型性能表会一起切到同一窗口。

账号池页面的「查询全部余额」会向上游刷新所有账号，返回积分总和（含停用账号）、国内／国际小计及各账号明细。`GET /accounts/balance` 读取当前缓存；`POST /accounts/balance` 以空 JSON 对象刷新后查询。均沿用管理接口鉴权（`X-Panel-Token` 面板会话；已配置 API Key 时还需对应认证）。响应含 `total_remain`、`by_realm`、`accounts`、`unknown_count`、`refresh_failed` 和 `complete`。未知余额不当作 0，查询失败保留缓存且 `complete=false`；无账号时总和为 0。

**客户端余额查询**：`GET /v1/balance`（也支持 `/balance`）携带 `Authorization: Bearer <API Key>`，返回该 Key 对应渠道的账号剩余积分总和 `total_remain`，包含停用账号。国内 Key 只汇总 `cn`，国际 Key 只汇总 `intl`，未固定渠道的 Key 跟随面板当前渠道；`X-Realm`、`realm`、`channel` 参数不会改变余额查询范围。响应包含 `realm`、`channel`、`currency: "credits"`、账号数量及完整程度，不包含账号身份、凭据或其他渠道明细。该接口始终要求有效 API Key，面板会话和关闭模型接口鉴权均不能替代 Key。

默认按需刷新超过 60 秒或尚未知晓的余额，并在同一渠道合并并发刷新；成功与失败结果均短期缓存，避免客户端轮询重复查询上游。`?refresh=1` 强制刷新该渠道，`?refresh=0` 只读本地缓存。`complete=false` 时 `total_remain` 是已知余额的小计，需同时查看 `unknown_count` 和 `refresh_failed`；空渠道返回 0。

```bash
curl http://127.0.0.1:8788/v1/balance \
  -H "Authorization: Bearer $API_KEY"
```

兼容经典中转站客户端的 `GET /dashboard/billing/credit_grants`、`/dashboard/billing/subscription`、`/dashboard/billing/usage`，三个路径也均支持 `/v1` 前缀，使用相同的 Key、渠道范围及刷新参数。账单格式参考 [One API](https://github.com/songquanpeng/one-api/blob/main/controller/billing.go)。`credit_grants.total_available` 返回剩余积分；`subscription.hard_limit_usd` 返回剩余积分加当前权益包已用积分，`usage.total_usage` 返回当前权益包已用积分乘 100，客户端按 `hard_limit_usd - total_usage / 100` 得到剩余积分。所有金额字段的单位均为积分，`*_usd` 仅保留兼容字段名，未折算美元；用量是当前权益包快照，日期参数不用于历史区间统计。余额或已用积分不完整时，兼容接口返回 HTTP 503，具体状态可通过 `/v1/balance` 查询。

#### DeepSeek 与 billing 接口

`GET /user/balance` 与 `/v1/user/balance` 使用 [DeepSeek 余额格式](https://api-docs.deepseek.com/api/get-user-balance/)，返回 Key 对应渠道全部账号的剩余积分（包含停用账号），不返回账号身份或凭据。例如剩余积分为 1234.5 时，兼容字段如下；响应还带有上述汇总与完整程度字段：

```json
{
  "currency": "credits",
  "is_available": true,
  "balance_infos": [{
    "currency": "USD",
    "total_balance": "1234.50",
    "granted_balance": "1234.50",
    "topped_up_balance": "0.00"
  }]
}
```

金额字段均为两位小数的字符串，单位仍为积分；内层 `USD` 是协议兼容标签，避免客户端把积分按 CNY 汇率换算，不代表美元现金。积分总额放在 `granted_balance`，不拆分现金充值余额；`is_available` 表示剩余积分大于 0。余额未知或刷新失败时返回 503，已用积分未知不影响此接口。刷新参数与 `/v1/balance` 相同。

`GET /api/billing/balance` 返回同一渠道的汇总，另提供数值型 `balance` 字段，单位为积分；不完整时返回 503。`GET /api/billing/usage` 返回当前 API Key 在对应渠道的 `prompt_tokens`、`completion_tokens`、`reasoning_tokens`、`cached_tokens`、`total_tokens`、`requests` 和 `errors`，不返回其他 Key 或账号明细。默认统计现存日志的全部历史；支持 `?range=today`、`week`、`month`、`all` 和 `custom&since=<epoch秒>&until=<epoch秒>`，响应 `window` 表明实际区间，缓存沿用指标页的短期缓存。Token 口径沿用指标页，不把思考 Token 再加到已包含它的输出 Token 上。两个 billing 路径也支持 `/v1` 前缀。

上述接口即使关闭模型请求的 Key 校验，也始终要求有效 API Key。未绑定出口的 Key 跟随面板当前渠道，`X-Realm`、`realm` 和 `channel` 参数不能扩大余额或用量查询范围。

#### 账号优先级与 Token 显示

账号页的「优先级」列可直接输入 0 至 2147483647 的整数，修改后自动保存；默认 100。数字越小越早调用，当前优先级内没有可用账号时再尝试下一优先级。区域、停用、冷却、额度与模型限制继续生效；同一优先级内维持免费模型的区域独立公平轮询、收费模型的加权／轮询与会话绑定。较小数字的账号恢复可用后，后续请求优先使用它，已有会话也会重新绑定。配置随账号保存、重启和导入导出保留。管理 API 可通过 `POST /accounts/set` 传入 `{"uid":"账号UID","priority":10}` 修改。

看板的 Token 数量自动使用 K／M／B（1000／100万／10亿），最多保留两位小数；统计、API 与导出保持原始数值。积分、费用和请求次数仍使用各自的原有显示格式。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web 用量与任务监控看板 |
| POST | /v1/chat/completions | 标准 Chat Completions 接口 |
| POST | /v1/responses | Responses API 协议接口 |
| POST | /v1/messages | 原生 Anthropic Messages 协议接口（流式 / 非流式，`x-api-key` 或 `Authorization` 鉴权） |
| POST | /v1/messages/count_tokens | Anthropic 计数接口（CJK 感知估算值，非官方分词器） |
| GET | /v1/models | 官方对齐模型列表（含能力与规格宣告） |
| GET | /v1/models/{id} | 当前渠道的单个模型详情；支持 URL 编码的模型 ID，不存在时返回 404 |
| GET | /v1/balance | API Key 对应渠道的积分总和与完整程度（API Key 鉴权） |
| GET | /user/balance | DeepSeek 余额格式，也支持 /v1/user/balance（API Key 鉴权） |
| GET | /api/billing/balance | Key 对应渠道的余额，balance 为剩余积分（API Key 鉴权） |
| GET | /api/billing/usage | 当前 Key 对应渠道的 Token 消耗及区间（API Key 鉴权） |
| GET | /v1/dashboard/billing/credit_grants | 经典中转站余额格式，`total_available` 为剩余积分 |
| GET | /v1/dashboard/billing/subscription | 经典中转站额度格式（积分单位） |
| GET | /v1/dashboard/billing/usage | 经典中转站用量格式（当前权益包已用积分 × 100） |
| GET | /accounts/balance | 所有账号的缓存余额总和、两区小计与明细（管理鉴权） |
| POST | /accounts/balance | 刷新所有账号并返回余额总和、失败状态与明细（管理鉴权） |
| GET | /pricing | 定价状态：当前生效策略、上次/下次取价时间、未定价清单（分类 + 候选） |
| POST | /pricing/refresh | 立即取一次价（需面板会话） |
| POST | /pricing/mapping | 手填 / 清除「模型 → OpenRouter id」运行期映射，随后自动取价（需面板会话） |
| GET | /tasks | 国内版成长任务、连续打卡与猫猫日常状态 |
| POST | /tasks/run | 触发国内成长任务全自动点亮与领奖 |
| POST | /tasks/travel | 触发猫猫日常旅行（派出 / 领奖） |
| GET | /scheduler | 定时调度器运行状态与排程日志 |
| POST | /scheduler/trigger | 手动立即执行后台巡检保活 |

---

## 六、Workbody-FHUB 更新记录

### 1.0.6

- 新增 DeepSeek `user/balance` 余额格式、`api/billing/balance` 余额查询与 `api/billing/usage` Token 消耗查询；支持裸路径与 `/v1` 前缀，按有效 Key 限定查询范围。
- 新增 `GET /v1/models/{id}`，返回与模型列表一致的单个模型详情，未知 ID 返回 404。
- 增加持久化账号调度优先级，数字越小越早调用；不可用时依次回退，同优先级保留原调度规则，账号页可直接修改。
- Token 数量统一自动显示为 K／M／B，覆盖用量、账号、模型、请求和趋势图；原始 API 与导出数值保持不变。

### 1.0.3

- 新增 `GET /v1/balance`，按 API Key 绑定的国内／国际渠道汇总剩余积分，包含停用账号；未绑定渠道的 Key 跟随面板当前渠道。只返回汇总与完整程度。
- 兼容旧 OpenAI `dashboard/billing` 余额、额度及用量查询路径，支持裸路径和 `/v1` 前缀；所有数值保持积分单位。
- 按渠道合并刷新，默认缓存 60 秒；支持强制刷新和只读缓存，未知余额及刷新失败明确标记，兼容接口遇到不完整数据返回 503。
- 余额查询始终要求有效 API Key，忽略跨渠道参数，访问日志隐藏密钥；两种架构的镜像验证增加客户端余额回归套件。

### 1.0.2

具体行为、验证与部署边界见[网关与账号池更新说明](docs/gateway-pool-update-2026-10-07.md)。

- 生成速度统一为有效请求的总输出 Token / 总生成时间，三种协议均从首个生成内容帧计到末个内容帧；失败、取消、缺少用量和单帧输出不参与平均值。历史日志按已有耗时重新汇总，旧日志的错误首字时间无法追回。
- 账号池增加国内／国际切换；列表、OAuth 默认区域、批量启停、导出和分配代理跟随当前区域。默认 API 出口仍由网关设置及 Key 绑定决定。
- 增加全部账号余额查询，显示总积分、两区小计和未知／查询失败状态，包含停用账号。
- 免费模型默认在国内、国际各自的账号池内公平轮询，按区域及模型维护游标；跳过不可用账号，免费请求不绑定会话。收费模型维持原策略，可在设置中关闭 `pool.free_fair_pick`。
- 代理槽位支持 HTTP 与 SOCKS5／SOCKS5h，用户名、密码独立设置，保存、重载与测试保留凭据；搜索支持独立代理认证，HTTPS 保留目标域名证书验证。

### 1.0.1

- 修复配置损坏与删除最后一个 Key 时的旧密钥回退。
- 修复日志轮转后的每日预算计量，以及大日志查询漏算。
- 修复后台调度器启动、停止和设置更新的线程状态。
- 增加模型请求字段校验；改进密码错误提示与健康检查。
- 移除 URL 密码登录并对访问日志中的凭据参数脱敏。
- 修复过程与复现证据见[修复报告](docs/project-repair-2026-10-07.md)。

[上游历史更新记录](CHANGELOG.upstream.md)保留原文。原项目声明、致谢与许可证继续保留在本项目。

维护工具位于 `tools/`：`fix_launchers.py` 重建 Windows 启动器，`fetch_pricing.py` 更新内置定价快照。运行服务无需调用这些工具。

---

## 七、致谢与引用声明 (Credits & References)

协议兼容、风控规避与任务链路设计过程中，参考并吸纳了以下开源项目的经验与逆向成果：

- **[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)**：成长任务全链路逆向、设备指纹稳定派生（`derive_id`）、整点排程调度（`Scheduler`）、指纹脱敏与 `reasoning_content` 回填；
- **[CangShui/workbuddy-cliproxy-fix](https://github.com/CangShui/workbuddy-cliproxy-fix)**：早期客户端代理修复与接口差异参考；
- **[lovingfish/workbuddy-cliproxy](https://github.com/lovingfish/workbuddy-cliproxy)** 与 **[mmqz/cpa-multi-plugins](https://github.com/mmqz/cpa-multi-plugins)**：网关通信与多插件管理原型参考；
- **[ardeyouxipianyi/workbuddy2api](https://github.com/ardeyouxipianyi/workbuddy2api)**：国内版分发包逆向分析与出站 User-Agent 规范参考。

PR 贡献者（v1.4.5 之前的改动未进上方更新记录，这里一并列出）：

- **[@ddddd-ren](https://github.com/ddddd-ren)**：用量日志倒序检索与看板防堆叠（PR #14）、原子写入与并发竞争修复（PR #13）、账号池 JSON 导出导入（PR #5）；
- **[@wylftw0314-glitch](https://github.com/wylftw0314-glitch)**：Responses API custom 工具协议双向转译（PR #12）；
- **[@shuishuipingan](https://github.com/shuishuipingan)**：成长任务领取竞态与专家/团队事件 id 去重、猫猫旅行派出修复、夜猫子任务接入调度器、启动端口误判（PR #21）、按模型冷却限流（PR #22）、任务接取强化与轮询加速（PR #27）、网络抖动重试与 403 直通（PR #28）、HTTP 连接同步（PR #30）；
- **[@ayeaaaa](https://github.com/ayeaaaa)**：按账号绑定出口代理槽（PR #26）、DeepSeek `reasoning_content` 回填（PR #36）、看板移动端布局（PR #37）；
- **[@t-789](https://github.com/t-789)**：macOS 启动脚本与防火墙助手（PR #31）；
- **[@Cekxri](https://github.com/Cekxri)**：Codex App namespace 工具支持（PR #33）；
- **[@wiggins-kong](https://github.com/wiggins-kong)**：API Key 行 id 唯一化（PR #40）、Docker 镜像缺少运行时模块（PR #41）；
- **[@Pro-XK](https://github.com/Pro-XK)**：看板积分消耗与账号昵称（PR #45）；
- **[@teddyli18000](https://github.com/teddyli18000)**：单模型限流可视化（PR #50）、`/health` 鉴权状态修正（PR #52）；
- **[@LuFering](https://github.com/LuFering)**：Docker 部署下的 Linux 桌面凭据挂载说明（PR #55）；
- **[@zhangzm0](https://github.com/zhangzm0)**：`tool_choice="none"` 保留工具声明（PR #57）。

---

## 八、免责声明 (Disclaimer)

1. 本项目为非官方自托管网关，仅供技术研究、逆向协议学习与个人合法授权账号在私有环境测试使用。
2. 本项目不提供任何账号及额度。请严格遵守官方服务条款，禁止用于任何商业转售、恶意并发或违规滥用。
