# OpenCode Free Gate 与当前 OpenCode 接入调研

核查日期：2026-10-07（Asia/Shanghai）。使用 GitHub API、固定提交源码、官方文档和公开模型目录；没有运行下载的网关、调用推理接口或读取用户凭据。本文的“源码已确认”“维护者说明”“用户报告”“设计建议”分别标明证据强度，目录可读取不代表账号可调用模型。

## 结论

**当前适合落地的是 OpenCode 模型目录，以及后续使用真实 API key 的官方 Zen / Go 适配器。** `opencode-free-gate` 的 main 和未合并 PR #3 都主要模拟 OpenCode 客户端并使用匿名 `public` 凭据。官方维护者已明确免费层不能用于其他 harness；补请求头、换代理、补工具不构成受支持的外部免费模型 API 接入方式。[网关主线配置](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/project.go#L33-L65)、[官方维护者说明](https://github.com/anomalyco/opencode/issues/49621#issuecomment-5723383322)

官方另有 `opencode serve` 和 `opencode acp`，供客户端使用完整的 OpenCode agent。它们可以成为独立的 agent 集成模式，但具备会话、工具执行和权限语义，不能承诺与透明 Chat Completions / Responses 代理等价，也不能承诺所有免费模型在当前版本均可用。[Server 文档](https://opencode.ai/docs/server/)、[ACP 文档](https://opencode.ai/docs/acp/)、[近期仍开放的免费层误判报告](https://github.com/anomalyco/opencode/issues/53347)

本项目近期 UI 应保持用户指定的三个独立目录渠道：**OpenCode / WorkBuddy CN / WorkBuddy Intl**。OpenCode 目录选择先与推理启用解耦；下面的账号和协议方案属于后续实现建议。

## 固定版本、部署与许可

| 项目 | 已核实结果 | 来源 |
| --- | --- | --- |
| `GuJi08233/opencode-free-gate` main | `215c725bdf3a5c0d916edf7a491ac3bf7fd1120b`，提交时间 `2026-08-19T21:17:19Z`；Go 1.24；tag `v2.5.0` 指向同一提交 | [提交](https://github.com/GuJi08233/opencode-free-gate/commit/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b)、[go.mod](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/go.mod)、[tags API](https://api.github.com/repos/GuJi08233/opencode-free-gate/tags) |
| 部署 | 独立 Go HTTP 网关，默认端口 `13339`；Docker 的 Go 构建阶段、Alpine 运行阶段，非 root 用户；Compose 使用 `ghcr.io/guji08233/opencode-free-gate:latest` | [Dockerfile](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/Dockerfile)、[Compose](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/docker-compose.yml) |
| 发布 | workflow 仅在 `v*` tag 推送时触发，配置运行 Go tests、构建 `linux/amd64` / `linux/arm64` 并发布；GitHub Releases API 当前为空。未验证 GHCR `latest` 的实际 digest，也未重跑测试 | [发布 workflow](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/.github/workflows/docker-publish.yml)、[Releases API](https://api.github.com/repos/GuJi08233/opencode-free-gate/releases) |
| 许可 | GitHub `license: null`；完整 main 树没有 LICENSE / COPYING / NOTICE。Dockerfile 与 workflow 的 OCI label 声称 MIT，但未提供许可正文；不能仅凭标签认定源码已有完整 MIT 授权 | [仓库 metadata](https://api.github.com/repos/GuJi08233/opencode-free-gate)、[完整树](https://api.github.com/repos/GuJi08233/opencode-free-gate/git/trees/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b?recursive=1)、[镜像许可标签](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/Dockerfile#L18-L21) |
| OpenCode 官方源码快照 | `anomalyco/opencode` 的 dev：`ecc4916b5a9608c30e6dd58a67f2137b594407ca`，提交时间 `2026-10-06T22:32:45Z`。dev 快照不是本次对线上部署版本的证明 | [官方提交](https://github.com/anomalyco/opencode/commit/ecc4916b5a9608c30e6dd58a67f2137b594407ca) |

设计建议：保持现有 Python + Docker / 1Panel 部署，独立编写适配器；若拟复制该 Go 网关代码，先补齐许可依据。

## 网关主线实际行为

- **路由与协议**：公开前缀是 `/openai`、`/anthropic`、`/codex`，支持模型目录、`/v1/chat/completions`、`/v1/messages`、`/v1/responses` 和 `/healthz`。源码只是移除前缀再转发对应协议，没有在本地把 Anthropic / Responses 任意转换为 Chat Completions；前缀本身也没有约束后面的协议路径。[路由实现](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/main.go#L123-L174)、[项目规格](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/project.go#L52-L57)
- **凭据与入口认证**：上游固定 `https://opencode.ai/zen`、`Authorization: Bearer public`；客户端 Authorization / x-api-key 不在透传头列表中。Messages 路径把该固定凭据转换为 x-api-key。虽然读取 `GATEWAY_KEY`，当前项目没有启用 `gatewayAuth`，所以该环境变量不会保护当前 OpenCode 网关路由；它没有账号池、OAuth 登录或账号导入导出接口。[固定配置](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/project.go)、[认证及请求头实现](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/main.go#L144-L158)、[上游认证实现](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/main.go#L259-L292)
- **客户端模拟**：main 使用 `opencode/1.18.18` 加 Go runtime 信息，session 是 `ses_` 加 24 个十六进制字符，request 是 `req_` 加随机十六进制字符；这些是该网关自己定义的哈希/随机值，不是当前真实 OpenCode 会话的完整语义。[ids.go](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/ids.go)
- **模型目录**：请求官方 `/zen/v1/models`，按需使用 60 秒 TTL；仅选 `-free` 后缀并去掉后缀展示，另总是添加 `big-pickle`。刷新失败时使用旧缓存；没有缓存时也可能返回本地合成的 `big-pickle`。因此目录成功不能当模型可用性测试。[目录与重写源码](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/models.go#L16-L108)、[合成响应](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/models.go#L139-L169)
- **代理与重试**：默认公共代理池 → ZenProxy relay → 自定义代理 → 直连；支持 HTTP / HTTPS / SOCKS5 / SOCKS5H、会话出口亲和。流式单次首字节预算默认 3 秒、选择/重试总预算 10 秒，非流式总预算 300 秒。401、403、429 和部分其他状态统一重试，没有按 FreeTierError / RegionError / quota 分类。这只能说明源码策略，不能证明轮换可解除权限或配额限制。[配置](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/config.go#L40-L88)、[调度及重试](https://github.com/GuJi08233/opencode-free-gate/blob/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b/gateway.go#L701-L950)

## 全部可访问 issue / PR / discussion 核查

仓库 metadata 显示 `has_issues=false`、`has_discussions=false`。GitHub issues API 的 `state=all` 返回两个条目，**两个都是 PR，没有独立 issue**；`open_issues_count=1` 对应开放 PR #3。不能把 Issues 页面为空理解为“没有兼容性问题”，也不能声称存在已阅读的 Discussion。[metadata](https://api.github.com/repos/GuJi08233/opencode-free-gate)、[全部 issue/PR 条目](https://api.github.com/repos/GuJi08233/opencode-free-gate/issues?state=all&per_page=100)

| 条目 | 日期与当前状态（UTC） | 源码和证据结论 |
| --- | --- | --- |
| [PR #2：适配风控、Key 透传与模型映射](https://github.com/GuJi08233/opencode-free-gate/pull/2) | 2026-09-20 14:00 创建，14:24 关闭；`merged_at=null`；head `f8f2c0df1cf05a8bce5c0eafcee6874c01082dcb` | diff 确实增加客户端 Authorization / `OPENCODE_API_KEY` 选择、强制 stream/tools 等，但**未合入 main**。无 issue comments、review comments 或 reviews。关闭事件由 PR 作者 27xk 发起，没有已修复/已上线证据。[PR API](https://api.github.com/repos/GuJi08233/opencode-free-gate/pulls/2)、[files API](https://api.github.com/repos/GuJi08233/opencode-free-gate/pulls/2/files) |
| [PR #3：补工具、会话与代理重试](https://github.com/GuJi08233/opencode-free-gate/pull/3) | 2026-09-20 15:59 创建，当前 open；`merged_at=null`；head `221548127aade3e6f6c685b93cd2bc67c9c70fc3`（27xk fork） | 增加 `stream:true`、bash/read 工具、ID/cache、代理冷却和 SSE 聚合。实际源码**仍固定 Bearer public**，没有保留 #2 的 key 透传；也没有评论/审核/官方维护者确认。PR 文案的“解决403”属于作者声称，本次未做推理验证。[PR API](https://api.github.com/repos/GuJi08233/opencode-free-gate/pulls/3)、[固定上游凭据](https://github.com/27xk/opencode-free-gate/blob/221548127aade3e6f6c685b93cd2bc67c9c70fc3/project.go#L33-L65)、[补工具实现](https://github.com/27xk/opencode-free-gate/blob/221548127aade3e6f6c685b93cd2bc67c9c70fc3/ids.go#L308-L378) |

PR #3 的实现还会给非 Anthropic 路径统一套 OpenAI Chat Completions 的嵌套 `function` 工具形状；Responses 的原生工具结构需要单独核实。自动增加下游未提供的 bash/read 也会改变模型可见工具，不能直接纳入透明兼容层。[PR #3 工具转换](https://github.com/27xk/opencode-free-gate/blob/221548127aade3e6f6c685b93cd2bc67c9c70fc3/ids.go#L318-L377)

## 官方限制与新的 Console key 接入

**已确认的产品边界**：官方 collaborator 在 2026-09-18 明确说明收紧逻辑防滥用，免费层不能用于其他 harness，该限制不涵盖其他层。另一条维护者回复承认当时 compaction 曾被误判并已修复，也承认非常定制化的配置可能受影响。因此应分别处理“外部免费层不受支持”和“真实 OpenCode 被误判”的问题。[#49621 维护者回复](https://github.com/anomalyco/opencode/issues/49621#issuecomment-5723383322)、[#49590 维护者回复](https://github.com/anomalyco/opencode/issues/49590#issuecomment-5723721001)

**最新 dev 源码的 key 迁移**：`inference-proxy.ts` 把 `oc_sk_` 识别为新 Console key；旧 key 只在所属 workspace 已标记 migrated 时转发新 inference 服务。`public` 或缺失 key 明确不进入该迁移分支。目的端来自 `Resource.ConsoleMigration.inferenceUrl`，不是一个可从本文确定的公开地址；内部 `/openai/v1`、`/go/openai/v1`、`/anthropic/v1` 是 remap 目标，不能拿来替换客户端正式 base URL。[固定版本迁移源码](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/console/app/src/lib/inference-proxy.ts#L7-L90)

**稳定的外部 API**：官方文档仍提供 `https://opencode.ai/zen/v1` 和 `https://opencode.ai/zen/go/v1`。Zen 通过 Console 登录、配置计费并取得 key；Go 通过订阅取得 key。按模型选择 Chat Completions / Responses / Messages 等协议，而不是把所有模型强制走同一路径。文档明确支持这些 API 的外部访问；新 key 的兼容转发有源码依据，但本次没有真实 key 的线上成功请求。[Zen](https://opencode.ai/docs/zen/)、[Go](https://opencode.ai/docs/go/)

**不能从公开资料确认的内容**：线上完整免费层判别算法、TLS 指纹或所谓嵌入式秘密、每模型精确生产配额、PR #3 的最新可用率。本次官方源码搜索没有找到公开 FreeTierError 判别器；旧 IP limiter 的 checkHeaders 甚至处于注释状态，而模型限制来自私有 `ZEN_MODELS*` 资源。这些旧源码不能反证真实线上限制不存在，也不能用来承诺固定日额度。[旧 IP limiter](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/console/app/src/routes/zen/util/ipRateLimiter.ts)、[模型资源配置](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/console/core/src/model.ts#L23-L116)

## 目录、模型 ID 与协议

| 接入 | 正式发现接口 / 元数据来源 | 协议注意事项 |
| --- | --- | --- |
| Zen API | `GET https://opencode.ai/zen/v1/models` | 官方按模型列 Responses、Chat Completions、Anthropic Messages、Google 原生端点。GPT、Claude、Gemini 和开源模型不能只按目录渠道猜协议。[官方端点表](https://opencode.ai/docs/zen/) |
| Go API | `GET https://opencode.ai/zen/go/v1/models` | Go 列表独立；例如 GPT / Grok 使用 Responses，GLM / Kimi 使用 Chat Completions。订阅和区域条件仍由服务端执行。[官方端点表](https://opencode.ai/docs/go/) |
| OpenCode agent | `GET /provider`、`GET /config/providers` | 返回 provider、connected、models 信息；发送时明确 `{providerID, modelID}`，不等同公开 Zen 目录。[Server 文档](https://opencode.ai/docs/server/) |
| UI 描述元数据 | Models.dev 是 OpenCode 官方客户端采用的模型元数据来源 | 可补充显示名称、上下文、能力、SDK 等；目录信息不能替代账号授权或实际请求检查。[Providers 文档](https://opencode.ai/docs/providers/) |

本次 web 浏览工具成功读取两个官方 models JSON；本机 Python urllib 的匿名 GET 返回403，未确定其原因。公开 JSON 的单项只有 `id/object/created/owned_by`，不包含价格、上下文、协议和当前账号权限。故目录合并应注明来源和抓取时间，并区分“有目录”“账号可用”“完成推理验证”。[Zen 实时目录](https://opencode.ai/zen/v1/models)、[Go 实时目录](https://opencode.ai/zen/go/v1/models)

读取时 Zen 免费标记项包括：`big-pickle`、`jev-1.13-free`、`exo-free`、`deepseek-v4-flash-free`、`muse-spark-1.3-contributor-free`、`muse-spark-1.2-contributor-free`、`mimo-v2.6-flash-free`、`space-bunny-free`、`longcat-2.5-preview-free`、`mimo-v2.5-free`、`ling-3.0-flash-fin-free`、`nemotron-3-ultra-free`、`nemotron-3.5-lightning-free`、`fledge-alpha-free`、`ling-3.1-flash-free`；名单会变化，不是可对外代理服务承诺。[官方目录](https://opencode.ai/zen/v1/models)

设计建议：完整保留上游 ID 和 `-free` 后缀，并以 `provider + channel + upstream_model_id` 建立内部身份。当前目录同时存在 `jev-1.13` / `jev-1.13-free`、`deepseek-v4-flash` / `deepseek-v4-flash-free`；沿用 old gate 去后缀会把免费与付费版本混淆。模型页的三个渠道选择只控制目录展示和获取来源。

## 凭据与导入导出格式

OpenCode 官方 `/connect` 保存到 `~/.local/share/opencode/auth.json`。当前源码以 provider ID 为键，值为认证 union：`api` 包含 `key` 和可选 `metadata`；`oauth` 包含 `refresh/access/expires` 及可选 `accountId/enterpriseUrl`；`wellknown` 包含 `key/token`。文件写入权限为0600；`OPENCODE_AUTH_CONTENT` 可覆盖认证读取。[凭据文档](https://opencode.ai/docs/providers/#credentials)、[认证 schema / 存储源码](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/opencode/src/auth/index.ts#L11-L107)

结构示例（仅占位符）：

```json
{
  "opencode": { "type": "api", "key": "<ZEN_API_KEY>" },
  "opencode-go": { "type": "api", "key": "<GO_API_KEY>" }
}
```

这个格式不是 `opencode-free-gate` 的账号导出格式，也不是 WorkBuddy 账号结构。OAuth provider 的 access/refresh token 不能自动视为 Zen API key；OpenCode 的 provider map 也不是多账号数组。[网关完整树](https://api.github.com/repos/GuJi08233/opencode-free-gate/git/trees/215c725bdf3a5c0d916edf7a491ac3bf7fd1120b?recursive=1)、[官方认证 schema](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/opencode/src/auth/index.ts#L16-L44)

设计建议：保持现有 `workbuddy-accounts` v1 导入导出兼容；后续另加带版本的 provider-neutral envelope，明确 `provider`、接入模式（`zen_api` / `go_api` / `opencode_server`）、base URL、认证类型、模型/协议映射和出口配置。导入 OpenCode auth.json 时只选择用户指定的 provider，API key 原样存储；不自动转换 OAuth，不把 Server Basic Auth 密码当上游 key。OpenCode API key、当前 WorkBuddy API key 和服务入口 key 必须保留各自用途。

## `serve` / ACP 的受支持用途和实现接口

`opencode serve` 默认 `127.0.0.1:4096`；通过 `OPENCODE_SERVER_PASSWORD` 启用 HTTP Basic Auth，用户名默认 `opencode`，可用 `OPENCODE_SERVER_USERNAME` 设置。`/doc` 是 OpenAPI 3.1 描述；接入时应按实际运行版本的 spec 校验，不能只靠 dev 文档。[Server 官方文档](https://opencode.ai/docs/server/)

agent 适配器可使用 `GET /global/health`、`GET /provider`、`POST /session`、`POST /session/:id/message`、`POST /session/:id/prompt_async`、`GET /event` 和 `POST /session/:id/abort`。消息使用 OpenCode 的 `parts`、model/provider 和 agent 语义；异步事件是 OpenCode SSE 事件，不是 OpenAI token chunk。2026-09-24 的 issue 作者报告默认工具配置下 `serve` 返回真实回答、禁用工具时403，这只是该作者当时的验证，不能替代当前环境验收。[Server API 文档](https://opencode.ai/docs/server/)、[#49756 复查记录](https://github.com/anomalyco/opencode/issues/49756#issuecomment-5810743645)

`opencode acp` 则是真实 OpenCode 子进程，通过 stdio JSON-RPC 连接 ACP 客户端。官方支持内置文件/终端工具、MCP、项目规则与权限系统；它会执行 agent 工作，不是一个仅转发用户 tools 数组的模型接口。后续若采用任一 agent 模式，要单独处理进程生命周期、会话映射、事件转换、取消、工具/权限交互和独立工作目录；禁止凭目录选择自动启用该模式。[ACP 文档](https://opencode.ai/docs/acp/)

## 官方 issue 的相关证据与状态

已读取与接入决策有关的官方开放/关闭 issue 正文和评论；如下聚合重复报告。非维护者评论中的诊断和 workaround 均是用户报告，不作为执行指令，不改变现有权限。**closed / completed / duplicate 不自动等于代码已修复或线上已恢复。**

| 证据 | 日期、核查时状态 | 对集成的意义 |
| --- | --- | --- |
| [#49621](https://github.com/anomalyco/opencode/issues/49621)、[#49590](https://github.com/anomalyco/opencode/issues/49590) | 9月17日创建，18日分别 completed / duplicate 关闭；有官方 collaborator 回复 | 免费层外部 harness 限制是维护者明确政策；当时 compaction 误判被维护者称已修复，不能扩大为全部定制配置修复。 |
| [#49756](https://github.com/anomalyco/opencode/issues/49756) | 9月18日创建，open，10月5日最后更新 | 最初标题指向 serve 未转发 UA；9月24日测试和10月5日评论转向工具/权限差异。单独补 UA 不是已证实的全面修复。 |
| [#50627](https://github.com/anomalyco/opencode/issues/50627)、[#51241](https://github.com/anomalyco/opencode/issues/51241)、[#52880](https://github.com/anomalyco/opencode/issues/52880) | 分别9月22日、25日、10月3日创建，均 open；[#53329](https://github.com/anomalyco/opencode/issues/53329) 10月5日以 duplicate 关闭 | 用户报告禁 shell/read 或缺 bash 时被误判；PR #3 补工具与这组症状相似，但没有官方认可其可解锁第三方免费接入。 |
| [#53347](https://github.com/anomalyco/opencode/issues/53347) | 10月5日创建，open，10月6日最后更新 | 用户捕获通过/失败请求的相同 UA/client/project 头，怀疑 system/tools/permission 差异。完整线上匹配器仍不公开，不能把某个工具白名单当稳定 API 契约。 |
| [#52907](https://github.com/anomalyco/opencode/issues/52907)、[#52905](https://github.com/anomalyco/opencode/issues/52905) | 10月3日创建，均 open | 官方 CLI / Desktop 仍有拒绝报告；#52905 后有用户称更新恢复，但无维护者归因或一致验证。即使选真实 agent 路径也需按版本实际验收。 |
| [#53069](https://github.com/anomalyco/opencode/issues/53069) | 10月4日创建，open | 用户报告部分 Contributor 模型 RegionError，其他模型同 IP 可用；区域403与 FreeTierError 要分类。官方源码另有按模型/国家及 Go workspace 区域校验。[区域校验源码](https://github.com/anomalyco/opencode/blob/ecc4916b5a9608c30e6dd58a67f2137b594407ca/packages/console/app/src/routes/zen/util/handler.ts#L137-L171) |
| [#42090](https://github.com/anomalyco/opencode/issues/42090)、[PR #40210](https://github.com/anomalyco/opencode/pull/40210) | issue 8月12日创建，open；PR 8月22日关闭，`merged_at=null` | Responses → Chat 工具转换、web_search 及 SSE 生命周期存在报告；不能把 PR closed 误记成修复已合并。Native 协议优先，转换必须独立验收。 |
| [#51906](https://github.com/anomalyco/opencode/issues/51906) | 9月28日创建，同日 completed 关闭，没有解释修复的人工评论 | 用户报告 agent 达 steps 上限时 `tool_choice:none` 被模型拒绝；无本次可确认的修复提交，不能承诺任意 tool_choice 都兼容。 |
| [#33318](https://github.com/anomalyco/opencode/issues/33318)、[#53569](https://github.com/anomalyco/opencode/issues/53569)、[#53574](https://github.com/anomalyco/opencode/issues/53574) | #33318 6月22日创建，open；后两项10月6日创建，分别 not_planned 关闭 / open | 免费模型配额/限流与账号有余额是不同事实。固定 Bearer public 会丢失真实账号身份；改变代理不能被当作配额恢复策略。 |

## 后续实现建议与验收边界

1. **当前模型页**：三个渠道分别获取/缓存/显示；保留真实模型 ID、来源、更新时间。OpenCode 目录失败可使用有标记的缓存或官方 Models.dev 元数据，不能伪造“已连接成功”。
2. **正式 API 适配器**：Zen / Go 作为 OpenCode 渠道下的账号接入模式，选择正确 native 协议；入口认证与上游 key 分开；使用账号已有固定出口。401、FreeTierError、RegionError 和带 Retry-After 的配额错误分类，不复制 old gate 的统一403/429出口轮换。
3. **可选 agent 集成**：独立适配 serve 或 ACP；明确 agent 语义，按所部署版本处理会话、工具与权限；不作为普通免费模型透传的默认路线。
4. **验证**：源码/目录是本次已验证内容。后续分别验证模型刷新失败与旧缓存、三渠道 UI 隔离、旧 WorkBuddy 导入导出兼容、不同协议流式/非流式/取消/错误传播；真实上游连通性需要用户授权的有效账号再验证。本次没有上线或推理可用性结论。
