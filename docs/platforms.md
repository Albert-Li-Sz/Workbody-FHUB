# Cline、OpenCode、Command Code 与 Responses 会话（v1.2.4）

## 配置账号

账号池默认保留 WorkBuddy 的原有国内／国际页：OAuth 弹窗与跳转链接、客户端扫描、导入导出、积分、代理、身份、任务和其他按钮继续使用原代码。账号页顶部新增 Cline、OpenCode、Command Code 来源按钮；独立的「平台与会话」导航和页面已移除，Responses 配置迁至 **设置 → Responses 会话**。

### Cline

选择 **账号池 → Cline → 添加账号 (OAuth)**，弹出与 WorkBuddy 相同样式的三步登录窗口。点击其中完整的 HTTPS 授权链接，在官方页面登录并输入设备码（页面未自动带入时）；面板自动轮询、保存账号与刷新凭据。关闭或重新生成链接会取消旧请求，迟到的响应不能导入账号。

也可导入原始 Cline API Key，或带 refresh token 的 OAuth 凭据。API Key 使用普通 Bearer，OAuth 使用 WorkOS 前缀。账号可以限制为全部可用模型、仅 ClinePass 订阅或仅积分模型。模型目录的「配置渠道」同时适配 direct 和 planner，支持自动选择、限定渠道、偏好顺序、排除与排序；实际使用的渠道单独记录。

模型目录将官方 `clinePass` 分组置顶，可选择「ClinePass 订阅」单独查看完整模型 ID。仅订阅账号也可调用官方 `cline-free/` 模型；积分模型与 Pass 模型分别标注。公共模型采集不依赖第一个账号的登录凭据，单个账号过期不会阻断目录。

### OpenCode

选择 **账号池 → OpenCode → 添加账号 (OAuth)**，通过官方 console 设备授权登录。有多个组织时需在弹窗明确选择；使用该组织下发的 provider 配置、模型 ID、协议和网关凭据，官方 `{env:OPENCODE_CONSOLE_TOKEN}` 占位符仅解析为所选账号当前的 OAuth token；不读取进程环境或文件引用，不把它发送到旧版 Zen Key 网关。没有可用组织网关时显示待配置状态，刷新组织配置后才能调用。有在途请求或绑定的 Responses 历史时，组织切换会被拒绝，其他组织可以另加账号。

「导入账号凭据」还支持官方 Zen API Key，以及明确选择的 **公开免费模型（客户端模式）**。三种模式都使用参考客户端的 User-Agent、`x-opencode-client`、会话／请求／项目标识：会话稳定、请求唯一、账号与网关 Key 隔离。所选账号的 Authorization 保留；公开模式仅使用上游明确标为免费的模型。TLS 验证和绑定代理保持正常，不导入参考仓库中的随机代理、IP 扫描或关闭证书校验。

OAuth 组织配置同时包含 Zen 和 Go 时，两组网关、请求头和模型协议独立保存。Go 模型使用 **`opencode/go/<模型ID>`**，原 **`opencode/<模型ID>`** 继续使用 Zen；同名模型不能串用凭据、地址或计费。导入／导出、重启与 token 刷新保留此关联，旧版 OAuth 账号会自动重新同步组织配置，无需删除重加。仅导入 Zen API Key 不会自动获得 Go 路由。

官方 `cost` 显示为 USD／百万 Token；Go 显示订阅配额参考价，促销零价模型继续使用免费 Token 公平调度。Go 已确认额度耗尽和套餐限流只影响 Go，仍可使用同账号的 Zen 模型。钱包余额没有公开接口时显示未知，不以订阅剩余百分比冒充余额。

上游 `FreeTierError` 会返回 `opencode_free_tier_restricted`，`ModelDeprecated` 会返回 `model_deprecated`，并保留原生成 HTTP 状态。普通文本请求可能不符合某些免费模型的客户端要求；FHUB 保留客户端提交的工具与历史，不伪造工具或改投其他模型。模型目录可用和 OAuth 有效不保证所有免费模型允许任意请求。面板测试中的上游 401／403 返回 502 并保留具体原因，不再误退出面板会话。

参考的 opencode2api-free 自身没有 OAuth；设备 OAuth 实现依据官方 OpenCode 客户端。上游地区、套餐或公开模型权限错误保留原状态。

官方组织配置可省略内置 provider 的地址与模型表，仅下发网关 API Key。FHUB 按官方客户端方式继承已知 Zen／Go 地址，结合实时模型列表和客户端元数据解析模型协议；仍使用该组织自己的网关凭据。上游没有下发可用凭据时显示具体配置问题，不将空目录标记成同步成功。

### Command Code

先使用官方 CLI 登录，再把 `~/.commandcode/auth.json` 上传到 **账号池 → Command Code → 导入账号文件**；文件的 `apiKey` 为 `user_*` 凭据，账号名称和用户 ID 一同导入。也可手填，或明确点击「导入服务器 CLI 登录」读取运行 FHUB 的服务器上的该文件（不会读取远端浏览器所在机器）。

请求转换成官方 CLI 的 `/alpha/generate` envelope，NDJSON 增量转换成 Chat、Messages、Responses／SSE。保留完整历史、系统指令、图片、推理和工具调用；只有正式 finish 事件才作为完成，断流保留确认的部分用量。默认不注入额外 CLI 提示词。

显示官方余额、套餐和 5 小时／每周窗口。`used/cap` 是请求条数，不是 Token。402 积分耗尽后不再分配付费请求，确认余额恢复才解锁；429 使用上游重置时间冷却全账号。账号切换始终在 Command Code 内进行。

### 通用操作

各来源均支持启停、删除、导入导出、持久化名称／优先级／代理／模型白名单、调用测试、目录和用量。凭据编辑留空保留旧值。可选择自动均衡、轮询或指定优先账号；指定账号不可用时在同来源内切换，恢复后重新优先使用。

凭据保存在私有 `accounts/upstreams` 和 SQLite 文档中。普通面板只返回脱敏元数据，显式导出账号才包含凭据。手动刷新后台执行，失败保留缓存；目录同步不等于调用成功。

## 网关 Key 与模型 ID

在 **设置 → API Key** 勾选 `allowed_upstreams`。合法值为 `workbuddy`、`cline`、`opencode_zen`、`commandcode`。旧 Key 缺少字段时默认仅允许 WorkBuddy；旧页面保存也保留已设置的平台权限。WorkBuddy 的 `realm=cn|intl` 独立于平台权限。

| Key 范围 | 模型 ID |
| --- | --- |
| WorkBuddy | 原来的模型 ID |
| Cline | `cline/<原始ID>`；仅允许 Cline 的 Key 也接受原始 ID |
| Zen | `opencode/<原始ID>`；仅允许 Zen 的 Key 也接受原始 ID |
| Command Code | `commandcode/<原始ID>`；仅允许 Command Code 的 Key 也接受原始 ID |
| 多个外部平台 | 使用平台前缀，避免同名歧义 |

```bash
curl 'https://<公网IP>/v1/models?upstream=cline' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

`GET /v1/models/{id}` 支持包含斜线的 ID。Cline 目录合并官方推荐、免费、Pass／Cloud 分组与官方客户端使用的 OpenRouter 文本输出目录；OpenRouter 价格标记为参考 USD／Token，不用于推算 Cline 实际积分。能否调用取决于账号订阅、地区和实际权益。

Zen 目录取自官方 `/zen/v1/models`，该接口仅返回模型 ID。FHUB 用官方客户端采用的 [models.dev](https://models.dev/) 元数据补齐价格、上下文和协议，只保留实时列表中的模型；输入与输出价格都为零时才将其作为公开免费模型。单凭 `-free` 名称不推断免费权益。协议优先读取上游元数据，缺少时采用官方 Zen 模型表；需要原生 Gemini 协议的模型当前不纳入目录。官方目录变化后需刷新，具体协议以模型详情为准。

`GET /v1/models` 与 `GET /v1/models/{id}` 返回对应模型的价格与元数据。Zen 的 `pricing` 与 ClinePass 的 `reference_pricing` 使用 `unit: USD/1M tokens`；原 OpenRouter 参考价保留 `USD/token`，面板统一换算显示每百万 Token。价格缺失显示「上游未提供」。Pass 价格是参考价，不能与钱包积分混为实际扣费。元数据缓存持久化，采集失败保留已知数据并标明过期状态。

## 三种生成协议

| 客户端入口 | 行为 |
| --- | --- |
| `/v1/chat/completions` | 同协议保留原生响应／SSE；其他协议转换为 Chat |
| `/v1/responses` | 同协议保留原生输出项与事件；其他协议转换并提供本地会话续接 |
| `/v1/messages` | 同协议保留原生内容块与事件；其他协议转换为 Messages |

保留系统指令、完整历史、文本／图片、函数调用 ID、工具结果和可表达的推理参数。无法表示的签名、密文、未知块或选项返回 `400`。已保存的原生 Responses 密文会固定原账号；该账号不可用时明确返回错误。上游上下文超限返回 `context_length_exceeded`，不自动裁剪历史或压缩提示词。

三种入口支持 SSE 心跳和 `X-Accel-Buffering: no`。重试在发出生成事件前进行，只选择请求平台的账号；不跨平台回退。Cline 使用稳定 `session_id` 和 `X-Task-ID`。生成 WebSocket、原生 Gemini、后台 Responses 和 Conversations API 当前不提供。

原生 Messages／Responses 工具由上游或客户端按协议执行。跨协议时可使用现有 FHUB 本地网络工具，结果保存进 Responses 历史；不可转换的上游专用工具明确报错。

## 调度与实际消费

同平台、同优先级的免费账号比较当天免费 Token 加在途预估；付费账号比较当天实际积分／USD 加在途预估。预估只用于选择，实际用量入库后移除预估。自动模式默认使用 262144 Token 换号窗口，付费窗口按已确认消费折算，减少小幅增长引起的频繁切换。已确认的取消／失败用量也计入；未知消费保持未知。

Cline 同步官方当天积分明细，并按 generation ID 与本机请求去重；订阅模型的零积分调用仍归入订阅／付费路径。Zen 官方未提供的消费或余额不推算为实际账单。连接按账号及代理身份隔离，代理不可用会报错。

## 余额和 Token

```bash
curl 'https://<公网IP>/api/billing/balance?upstream=cline&refresh=1' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
curl 'https://<公网IP>/api/billing/usage?upstream=opencode_zen' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

| 上游 | 实际单位 | 查询范围 |
| --- | --- | --- |
| WorkBuddy | 积分 | Key 绑定的国内／国际渠道，包含停用账号 |
| Cline | 积分 | 本机配置账号，按官方用户 ID 去重，包含停用账号 |
| OpenCode Zen | USD | 无公开余额接口时返回未知／不完整，不伪造余额 |
| Command Code | 积分 | 官方 credits 的月度、购买、免费余额；未知字段不填零 |

多平台通过 `upstream` 分别查询，不能把积分和 USD 相加。含 WorkBuddy 的 Key 未指定平台时默认查询 WorkBuddy；只允许一个外部平台时默认该平台；允许多个外部平台时必须指定。`provider=deepseek|kimi|…` 仅控制兼容响应格式。Token 查询只统计当前网关 Key 发起的请求；平台每日调度统计可包含 Cline 同步到的其他实际积分消费。

**账号池 → 对应来源 → 查询余额／额度** 后台刷新该来源账号：

- Cline 分别查询积分、订阅套餐及官方 5 小时／每周／每月额度，显示已用百分比、剩余百分比和重置时间。一个查询失败不会覆盖其他已知结果。
- OpenCode Go 使用官方 `/zen/go/v1/usage` 查询组织网关 Key 对应的订阅额度；Zen 钱包余额仍需在官方控制台查看。没有订阅权益时显示查询错误，旧额度标记为缓存。
- Command Code 保留官方积分、套餐及请求条数窗口，WorkBuddy 保留原积分查询。

面板鉴权的 `GET /accounts/upstreams/billing?uid=<账号ID>` 或 `?upstream=cline` 返回账号的 `balance`、`subscription`、`quota`、`billing_status` 和查询错误。加 `refresh=1` 后异步刷新，`refreshing` 表示进度，账号 SSE 会推送结果；该接口需要 `X-Panel-Token`，不返回凭据。`GET /accounts/upstreams/models?upstream=cline&group=subscription` 可单独查询 Pass 目录与参考价格。

公共 `GET /v1/balance?upstream=cline` 继续返回去重的积分总额，并提供 `quota_windows` 中各窗口已知账号的剩余百分比范围；不将百分比相加。失败的缓存额度不参与范围统计，缓存余额使 `complete=false`，`stale_count` 表示缓存余额数量。

## Responses 续接、分支与删除

```json
{"model":"cline/<目录中的模型ID>","input":"记住项目名是 FHUB","store":true}
```

取返回的本地 `resp_...` ID 继续：

```json
{"previous_response_id":"resp_...","input":"项目叫什么？"}
```

模型可以省略，沿用前一响应；切换模型／平台返回错误。恢复前面的输入、输出、函数调用和结果，并追加当前输入。`instructions` 只作用于当前请求，后续请求需重新传入。

- `GET /v1/responses/{id}`：当前 Key 查询已保存响应。
- `DELETE /v1/responses/{id}`：删除一个响应；其他分支的完整快照仍可续接。
- 面板「删除整个会话」：删除该会话全部分支及未被引用的数据项。
- 其他 Key、过期响应、平台权限已撤销或不存在的 ID：统一 `404 response_not_found`。
- `store:false`／匿名请求／关闭保存：不写当前响应；其 ID 不能用于下一次续接。

默认保留 7 天、逻辑容量 1024 MiB，可在面板修改。快照按内容去重，父响应删除或过期不破坏仍存活的子响应。保存发生在成功终止事件之前；容量满返回 `507 response_storage_full`，数据库写入失败返回 `503 response_storage_unavailable`。断流、失败、取消不保存不完整上下文；有效输出上限结果可保存为 `incomplete`。

会话正文、工具结果和上游密文属于持久化内容，停服备份完整 `accounts`／`usage`。逻辑容量包含存活的去重项与响应数据，不等于 SQLite、WAL、用量等全部文件大小。过期清理会回收逻辑容量，物理文件不保证立即缩小。禁用保存不会立即删除已有数据，可在面板删除会话。

## 来源与验证

实现独立编写，参考 [Cline-proxy](https://github.com/YuJunZhiXue/Cline-proxy/tree/b07b46ef2da3b2126514270b7b88675398e7e810) 的功能范围，并核对 [Cline 官方源码](https://github.com/cline/cline/tree/fa840c741c3fc2eb49e7e0a4484895a99dae5cc5)、[Zen 官方文档](https://opencode.ai/docs/zen/) 和 [OpenRouter 模型目录文档](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)。

自动回归使用本地模拟上游，覆盖三种原生协议 × 三种客户端协议 × 流式／非流式、工具续接、部分消费、权限、分支、容量和 schema 2→3 原子迁移。真实上游验证需要配置合法凭据；面板仅在生成成功后标记「真实调用已验证」，该标记对应该账号曾完成调用，不代表目录中全部模型都已验证。

真实设备授权入口检查已返回成功：Cline 返回 `authkit.cline.bot` 跳转链接，OpenCode 返回 `opencode.ai` 跳转链接。检查作业在未登录账号时取消；这证明入口与链接可用，完整授权后的实际生成仍待配置真实账号。


参考固定版本：

- [ClinePass switcher 02538a3](https://github.com/munmunjaklin458-afk/cline-pass-switcher/tree/02538a3137a08948a94f26f17dd4aeff8c029ed1)：账号切换与 direct/planner 渠道策略。
- [OpenCode 客户端代理 656b088](https://github.com/spfnas/opencode2api-free/tree/656b088a042f01d07b47aa5edbead3460376e198)：客户端请求头与稳定会话标识。
- [OpenCode 官方客户端 3884062](https://github.com/anomalyco/opencode/blob/388406238bd5ca15564a762840a2362c3a45bd9c/packages/opencode/src/account/account.ts)：设备 OAuth、刷新与组织配置。
- [CommandCodeGo-manager 856430b](https://github.com/learningdog1/CommandCodeGo-manager/tree/856430ba9e10f78c15c80d7f4d1370864b80cd57)：CLI 凭据导入、额度与切换；wire 格式另核对官方 `command-code@1.79.2`。

这些新增内容从正式 1.2.2 源码与镜像提供。测试分为本地协议回归、浏览器界面检查和真实上游：前两类使用独立模拟数据，真实账号授权／生成需要合法凭据，不能用模拟通过代替真实联调。

## 1.2.4 联调与来源

已用合法 OAuth 账号完成 Zen `space-bunny-free` 的三协议流式／非流式请求，以及 Go 的 DeepSeek Chat、Claude Messages、GPT Responses；Responses 续接保留上一轮内容。该结果仅覆盖测试账号和模型，其他账号按其实际套餐与上游权限使用。

- [OpenCode Go 官方说明与网关](https://opencode.ai/docs/go/)
- [OpenCode Zen 官方说明](https://opencode.ai/docs/zen/)
- [官方客户端凭据变量解析](https://github.com/anomalyco/opencode/blob/388406238bd5ca15564a762840a2362c3a45bd9c/packages/opencode/src/config/variable.ts)
- [官方客户端模型与协议选择](https://github.com/anomalyco/opencode/blob/388406238bd5ca15564a762840a2362c3a45bd9c/packages/opencode/src/provider/provider.ts)
- [Anthropic 缓存 Token 计数规则](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
