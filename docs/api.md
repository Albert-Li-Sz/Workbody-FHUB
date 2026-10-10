# API 与余额协议说明

适用版本：**1.2.7**。

## 地址与鉴权

客户端 Base URL 通常为 `https://<公网IP>/v1`（独立 HTTP 编排为 `http://127.0.0.1:8788/v1`），请求头使用面板生成的网关 Key：

```http
Authorization: Bearer <WORKBODY_API_KEY>
```

本文路径相对于服务根地址。WorkBuddy 通过 Chat Completions 转换；Cline 和 Zen 支持同协议原生转发与跨协议转换；Command Code 的官方 CLI NDJSON 转成三种客户端协议，详见[多平台接入](platforms.md)。兼容范围以本文为准；余额和用量接口始终要求有效、已启用的网关 Key，面板会话及关闭模型调用鉴权不能绕过这一要求。余额和用量返回使用 `Cache-Control: no-store`。

Key 的 `allowed_upstreams` 限定可用平台，旧 Key 默认只允许 WorkBuddy。WorkBuddy Key 固定绑定 `cn` 或 `intl` 时，查询只读取该渠道；未绑定时跟随当前默认出口。余额与客户端用量不接受 `X-Realm`、`realm` 或 `channel` 参数覆盖 Key 的渠道。

## 模型与生成

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| GET | `/v1/models` | 当前渠道可用模型列表 |
| GET | `/v1/models/{id}` | 单个模型详情，与列表条目的字段一致 |
| POST | `/v1/chat/completions` | Chat Completions，支持流式 |
| POST | `/v1/responses` | Responses，支持流式 |
| POST | `/v1/messages` | Anthropic Messages |
| GET / DELETE | `/v1/responses/{id}` | 当前 Key 的已保存响应；删除不破坏其他分支 |

公开模型列表同时列出本名和配置的渠道别名，`canonical_id` 指向实际本名，`is_alias` 表示是否别名；两者的能力、权益与价格相同。Cline 直接使用上游 ID，兼容旧 `cline/` 调用。详情与生成均支持两种 ID，停用后移除两个入口并拒绝新调用。面板管理接口 `GET /settings/models?channel=...` 保留停用行，`POST /settings/models` 接受 `channel`、`model_id`、`alias`、`enabled`；批量启停使用 `channel`、非空 `model_ids` 数组和布尔 `enabled`，全部验证后一次保存，保留别名。需要面板 token，详见[模型管理](platforms.md#模型别名与启停)。

模型 ID 可以 URL 编码，包含 `/` 时使用 `%2F`。未知模型详情返回 `404 model not found`。目录可随上游更新，具体 ID、上下文、输出上限和能力以当前响应为准。

### 联网搜索兼容范围

| 接口 | 当前执行路径 | 兼容边界 |
| --- | --- | --- |
| Chat Completions | 普通函数工具由客户端执行，再回传结果 | 没有接入网关本地搜索执行循环 |
| Responses | 开启面板的本地网络工具，并在请求中声明搜索／抓取工具后，由网关执行 DuckDuckGo 搜索／网页抓取，再让模型继续回答 | 支持流式和非流式；搜索后端及结果格式不等同于 DeepSeek 官方原生搜索 |
| Messages | 开启面板的本地网络工具后，识别原生搜索声明，执行 DDG 搜索，再将真实结果回传模型续轮 | 支持流式、非流式及普通工具混合调用；提供原生结果和文本兼容两种输出 |

[DeepSeek 官方 Anthropic 兼容文档](https://api-docs.deepseek.com/guides/anthropic_api/)已列出 `server_tool_use` 和 `web_search_tool_result` 支持。FHUB 通过本地 DDG 后端适配这些块；普通函数仍交给客户端执行。混合调用完成服务端搜索后返回 `stop_reason: "tool_use"`，等待客户端结果，不伪造普通工具结果。

### Messages 搜索请求

支持 `/v1/messages`、`/messages`、`/anthropic/v1/messages`、`/anthropic/messages`，各路径也支持 `/count_tokens` 后缀。仍使用 FHUB 网关 Key；不能传 DeepSeek 账号令牌代替。

```json
{
  "model": "deepseek-v4.1-flash",
  "max_tokens": 4096,
  "messages": [{"role": "user", "content": "搜索相关资料并注明来源"}],
  "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
}
```

支持 `web_search_20250305` 及 `web_search` 声明，支持 `max_uses`，以及二选一的 `allowed_domains`／`blocked_domains`（域名及其子域名）。位置参数、新版动态过滤工具或其他未实现选项返回 `400`。本地工具开关关闭时，原生搜索请求也明确返回 `400`。普通 `input_schema` 函数不受该开关影响；原生和客户端函数不能同时占用 `web_search` 名称。

一次请求默认最多执行 3 轮工具、16 次调用、180 秒，`WB_MAX_WEB_ROUNDS` 可配置为 1–8；`max_uses` 是额外的搜索次数限制。达到工具预算时撤下服务端工具，让模型使用已有结果作答；超时或不完整的上游流返回错误。续轮按上游已报告的输出 Token 扣减 `max_tokens`，用尽时返回 `stop_reason: "max_tokens"`；上游未报告用量时无法精确扣减。Token 用量汇总所有模型续轮，调度记账按每轮实际账号进行；搜索阶段也持续发送 SSE 心跳。Responses 的 `web_search_call.completed` 在本地执行返回后发送。

同一次联网请求的续轮优先使用上一轮账号；免费会话跨请求使用默认 256K Token 换号窗口，面板可持久化调整。详见[账号调度与会话绑定](account-scheduling.md#免费与付费均衡)。

### 输出格式与 DSH

请求头 `X-FHUB-Web-Format` 控制 Messages 的搜索输出：

| 值 | 行为 |
| --- | --- |
| `native` | 返回配对的 `server_tool_use`／`web_search_tool_result`，真实来源与摘录的 `text.citations` |
| `text` | 搜索仍由网关执行，返回包含来源、摘录或错误的文本，普通客户端工具仍返回 `tool_use` |
| `auto`（默认） | 带 `x-deepseek-harness-user-id` 时选择 `text`，其他请求选择 `native`；可用上面两个值覆盖 |

自动选择依据已核对的 [DSH 主聊天请求头](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/llm-deepseek/src/adapter.ts#L113-L124)：该适配器不接受服务端工具块。辅助搜索未发送这个标识，并且[要求结构化搜索结果](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/provider.ts#L109-L168)，因此使用原生模式。不同版本或反代移除标识时，可显式设置 `X-FHUB-Web-Format: text`。SSE 响应头会返回实际格式。

DSH 的辅助搜索入口独立配置，需将 `DEEPSEEK_SEARCH_BASE_URL` 或搜索插件 `baseURL` 指向 FHUB 的 `/v1`（也可使用 `/anthropic/v1`），搜索模型填写本网关 `/v1/models` 返回的 ID。只修改聊天入口不会改变辅助搜索入口。

### 搜索历史与存储

回传完整的 assistant 内容块，调用 ID 与 `tool_use_id` 必须配对。FHUB 将其按“助手调用 → 工具结果 → 后续助手文本”转为上游历史，保留 URL、标题、摘录、文本引用和输入的真实 `thinking`；本次续轮也保留上游的 `reasoning_content`。不能恢复外部 `redacted_thinking`，也不生成官方思考签名。

原生结果的 `encrypted_content`／`encrypted_index` 使用 `fhub_web_v1:` 开头的 FHUB 不透明回放引用，与当前网关 Key ID 绑定，并非 DeepSeek 官方密文。结果存入 SQLite 的 `web_replay` 表，保留 7 天，最多 4096 条；没有数据库时使用同样上限的进程内存，重启后失效。引用失效或 Key 不匹配会明确返回 `400`，不会悄悄丢弃结果；可改传可读结果文本。来自其他服务的密文无法解密，只保留可见 URL、标题及引用摘录，并在上游上下文注明完整内容不可用。

协议差异、客户端报错出处及修复方案见[DeepSeek 联网搜索核对报告](research/deepseek-web-search-compatibility-2026-10-08.md)。

## 余额来源与刷新

WorkBuddy 余额入口汇总当前 Key 渠道内全部账号的剩余积分，包含停用账号。ClinePass 与 OpenCode Go 返回 5 小时剩余百分比合计，按 Cline 用户／OpenCode 组织去重，包含停用账号。80% 与 60% 合计为 140%，响应标明 `unit=percent`、`currency=percent`、`window=fiveHour`；缺失或过期额度不补零、不用钱包余额代替。Command Code 仍返回积分。`upstream=workbuddy|cline|opencode_zen|commandcode` 指定当前 Key 允许的平台；含 WorkBuddy 的 Key 默认查询 WorkBuddy，单个外部平台 Key 默认该平台，多个外部平台 Key 需指定。不同平台分别查询。数值单位以顶层 `unit` 为准，不把订阅百分比、积分或现金互相换算。

| 参数 | 行为 |
| --- | --- |
| 不传 `refresh` | 使用对应平台缓存，过期或缺失数据自动刷新 |
| `refresh=1` | 强制刷新当前平台余额／额度；Cline、OpenCode 和 Command Code 在后台刷新 |
| `refresh=0` | 仅读本机已有余额／额度缓存 |

WorkBuddy 沿用 60 秒查询缓存；Cline／OpenCode 的额度超过 10 分钟或已到重置时间时标记过期，后台查询完成后更新缓存。

原生查询允许返回已知小计和完整性状态；Cline／OpenCode 的 `accounts` 只包含各去重额度的百分比、重置时间与缓存状态，`known_count`、`unknown_count`、`stale_count` 区分可用／未知／过期。兼容余额格式在余额或额度不完整时返回 `503 balance_unavailable`。已用积分未知不会阻止纯余额查询，旧版 `subscription` 和账单 `usage` 仍要求完整的已用信息。

## 余额协议兼容范围

| 协议 | 网关入口 | 读取余额字段 | 接口来源与限制 |
| --- | --- | --- | --- |
| 原生 | `/api/billing/balance` | `balance`、`total_remain` | 网关积分查询 |
| DeepSeek | `/user/balance`、`/v1/user/balance` | `balance_infos[0].total_balance` | [官方余额协议](https://api-docs.deepseek.com/zh-cn/api/get-user-balance/) |
| Kimi | `/v1/users/me/balance`、`/users/me/balance` | `data.available_balance` | [官方查询余额](https://platform.kimi.com/docs/api/balance) |
| 千问／阿里云 | `/?Action=QueryAccountBalance` | `Data.AvailableAmount` | [BSS 官方响应格式](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance)，网关使用 Bearer Key |
| OpenAI 旧版 | `/dashboard/billing/credit_grants` | `total_available` | 旧版账单兼容；当前 [OpenAI 官方 Usage API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage) 是用量查询，未在其公开文档中找到普通模型 Key 的余额查询 API |
| GLM | `/api/billing/balance/glm` | `balance`、`total_remain` | 网关扩展，未在 [GLM 官方文档索引](https://docs.bigmodel.cn/llms.txt)找到公开现金余额 API |
| MiniMax | `/api/billing/balance/minimax` | `balance`、`total_remain` | 网关扩展，[官方账户说明](https://platform.minimaxi.com/docs/faq/about-account)主要提供控制台余额管理 |

千问的官方账户余额属于阿里云费用与成本服务，需要阿里云 AccessKey／RPC 签名，普通百炼模型 Key 不等同于 AccessKey。本网关适配返回结构，使用本网关 Key 查询 WorkBuddy 积分，不验证阿里云签名。

MiniMax Token Plan 的 `token_plan/remains` 属于订阅额度，单位和积分不同，本项目余额入口采用上表的网关扩展。GLM、MiniMax 扩展响应包含 `compatibility: "gateway_extension"`，文档和客户端配置应使用这个名称。

### 统一选择与别名

`GET /api/billing/balance?provider=<name>` 与 `/api/billing/balance/<name>` 均可选择适配格式。支持 `deepseek`、`kimi`、`glm`、`qwen`、`minimax`、`openai`；别名 `moonshot`、`zhipu`、`dashscope` 分别对应 Kimi、GLM、千问。

上述原生和命名入口同时支持 `/v1/api/billing/...` 前缀。阿里云 Action 查询支持根路径、`/v1`、`/v1/`。OpenAI 旧版 `credit_grants`、`subscription`、`usage` 支持 `/dashboard/billing/`、`/v1/dashboard/billing/`、`/billing/`、`/v1/billing/` 四种前缀。

`provider` 只选择响应格式，实际平台由 `upstream` 与当前 Key 的权限决定，WorkBuddy 渠道仍由 Key 决定。不要将官方厂商 Key 传给本网关作为账号凭据。

### 原生余额示例

```bash
curl 'http://127.0.0.1:8788/api/billing/balance?refresh=0' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

主要字段：

```json
{
  "ok": true,
  "object": "balance",
  "realm": "cn",
  "channel": "workbuddy-cn",
  "currency": "credits",
  "unit": "credits",
  "balance": 1234.5,
  "total_remain": 1234.5,
  "total_used": 100,
  "total_granted": 1334.5,
  "account_count": 2,
  "known_count": 2,
  "unknown_count": 0,
  "complete": true,
  "refreshed": false,
  "refresh_failed": 0
}
```

`/balance` 和 `/v1/balance` 返回原生汇总及 `queried_at`，可用于检查不完整数据。无账号的渠道返回余额 `0`；未知余额不会被伪造为零。不包含账号 UID、昵称、账号凭证或其他 Key。

### Kimi 示例

```bash
curl --request GET 'http://127.0.0.1:8788/v1/users/me/balance' \
  --header "Authorization: Bearer $WORKBODY_API_KEY"
```

返回保留公共汇总字段，并增加：

```json
{
  "provider": "kimi",
  "unit": "credits",
  "code": 0,
  "scode": "0x0",
  "status": true,
  "data": {
    "available_balance": 1234.5,
    "voucher_balance": 1234.5,
    "cash_balance": 0
  }
}
```

积分放入可用／赠送余额，现金余额为 `0`；若总积分为负，现金位置保留该负值、赠送位置为 `0`。数值仍为积分。

DeepSeek 使用两位小数的字符串余额，`is_available` 表示剩余积分是否大于零。WorkBuddy 的 `balance_infos[].currency` 为 `USD` 协议标签，用于兼容优先读取 USD 的客户端；顶层仍声明 `currency: "credits"`。千问 `Data.Currency` 同样为 `USD` 协议标签，`AvailableAmount` 是积分字符串，现金和授信字段为 `"0.00"`。

OpenAI 旧版 `subscription.hard_limit_usd` 为剩余＋已用积分；旧版账单 `usage.total_usage` 为已用积分×100，以适配旧客户端的 `/100` 计算。这些字段名不代表真实美元金额。

## 当前 Key 的 Token 用量

```bash
curl 'http://127.0.0.1:8788/api/billing/usage?range=today' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

同时支持 `/v1/api/billing/usage`。返回当前 Key 在所选渠道日志中记录的 `requests`、`errors`、`prompt_tokens`、`completion_tokens`、`reasoning_tokens`、`cached_tokens`、`total_tokens`，以及 `realm`、`channel`、`window`、`unit: "tokens"`。

`range` 可用 `today`、`week`、`month`、`all`、`custom`，默认全部历史；`since`、`until` 使用 Unix 秒。自定义范围示例：`?range=custom&since=1791388800&until=1791475200`。无记录返回零。推理 Token 已包含在输出计数内，总 Token 不额外重复相加；数据来源为网关日志，不包含绕过本网关的厂商调用。

返回的 `requests` 为完成次数，`errors` 为失败次数，`client_aborted` 为客户端取消次数。Token／积分总计包含取消及失败前已经确认的消耗。

## Token 显示

面板统一使用十进制单位：`K=1,000`、`M=1,000,000`、`B=1,000,000,000`，最多两位小数。例如 `8300 → 8.3K`、`131072 → 131.07K`、`1250000000 → 1.25B`；跨单位四舍五入后会提升单位。

覆盖账号表、用量卡片、模型与 Key 统计、输入／输出／思考／缓存数量、最近请求、趋势图、模型上下文与最大输出、限额提示、价格单位和生成速度。生成速度带 `tok/s`，小数显示保留一位；API、导出、原始日志和可编辑数字输入框保持完整数值。

## 错误与管理边界

| HTTP | 情况 |
| --- | --- |
| 400 | 非法 `refresh`、不支持的 `provider`、非法优先级等参数 |
| 401 | Key 缺失、无效、停用或删除；管理路由缺少面板会话 |
| 404 | 未知模型详情、未知路径或不存在的账号 |
| 503 | 渠道配置异常、余额不完整或当前适配所需数据不可用 |

错误遵循 `{"error": {"message": "...", "type": "...", "code": ...}}`。管理路由 `/accounts/*`、`/settings/*`、`/usage/*` 面向管理面板，受管理鉴权保护；客户端使用上文的 billing 入口。

## SSE 与面板事件

三种生成接口使用 `stream:true` 返回 SSE，默认无内容 15 秒时发送 `: heartbeat` 注释。响应包含 `X-Accel-Buffering: no` 和 `Cache-Control: no-cache, no-transform`，每帧及时刷新；心跳不算 Token 或首字时间。当前没有 WebSocket 生成端点。

控制台事件入口为 `GET /api/events?realm=all`，支持 `cn`、`intl`、`all`。需要有效面板会话，使用 `X-Panel-Token` 请求头，不接受 URL 中的面板 Token。推送合并后的刷新主题与版本号，控制台按当前页面读取受鉴权的数据。

```text
event: refresh
data: {"topics":["accounts","usage"],"revision":12,"at":1791417600}
```

事件连接包含心跳和重连提示，每实例最多 64 个订阅。会话过期返回 `session_expired`；客户端应重新登录。断线后重新读取当前状态，无需重放历史通知。前端使用支持自定义鉴权头的 fetch 流，支持自动重连与不可用时的 30 秒恢复刷新。

生成取消时已确认的部分用量计入消费，`client_aborted` 单独计数，不纳入有效生成速度。未知用量不会使用调度预估替代。[调度说明](account-scheduling.md)


## 管理设置补充（需面板认证）

- `POST /settings/save` 支持 `limits`，键为 `reserve_credits`、`daily_token_limit`、`daily_credit_limit`、`model_daily_token_limit`、`expiring_window_days`。每项包含 `global`、`intl`、`cn`，渠道 `null` 表示继承；旧平面字段继续更新全局值。负数、小数及非法数值整次拒绝，不做部分写入。
- `pricing_enabled` 为 JSON 布尔值，默认 `true`；关闭后暂停费用估算和取价，Token 与实际积分继续记录。`credits_refresh_hours` 为 `0–72` 的数字，默认 `0.5`。
- 保存 `api_keys` 时带 `deleted_api_key_ids` 数组采用显式删除与新增／更新：遗漏的已有 Key 保留；空密钥保留对应原值；未提交的名称、渠道、模型范围和启用状态保留。只提交删除数组也可删除。旧调用方不带数组仍采用完整替换语义。已删除的 id 不能重新启用。
- `POST /accounts/refresh` 发送 `{"async":true}` 返回 `202` 与 `id`、`total`、`completed`、`running`、`results`；`GET /accounts/refresh/status?id=...` 查询批次。只保留当前批次；重启后任务状态清除。省略 `async` 或指定 `uid` 保留同步调用兼容。

Messages 支持 Claude Code 在会话中插入的 `system`／`developer` 消息，按原位置转换为上游 system 消息。部分实时推理元数据按字段合并；未声明 `supportedEfforts` 时保留内置可选档位，防止仅返回默认 effort 的模型被错误锁定。

## Responses 持久化

默认对已鉴权请求保存响应，支持 `previous_response_id` 续接、GET／DELETE 和并发分支。默认保留 7 天、1024 MiB 逻辑容量；`store:false` 不保存当前响应。指令不继承，完整历史按 Key 隔离；保存失败不会发出成功终止事件。详见[续接、分支与删除](platforms.md#responses-续接分支与删除)。


## 新增账号来源的管理接口

这些接口要求面板会话；原 WorkBuddy `/accounts/*`、导入导出及 OAuth 接口继续保持原行为。

| 路径（根 `/accounts/upstreams`） | 方法 | 用途 |
| --- | --- | --- |
| 根路径、`/models`、`/usage?upstream=...` | GET | 来源账号、模型、用量 |
| `/accounts/import` | POST | 外部来源 JSON、数组或导出文件的 accounts 数组 |
| `/accounts/export?upstream=...&uid=...` | GET | 导出外部账号，可设置 includeSecrets=0 脱敏 |
| `/accounts/update`、`/accounts/batch` | POST | 保存优先级、凭据、代理、启停或删除；批量启停／代理 |
| `/accounts/cli-import` | POST | 明确导入服务器的 Command Code CLI 登录文件 |
| `/accounts/org` | POST | 切换 OpenCode OAuth 组织；在途请求或绑定的 Responses 历史阻止切换 |
| `/routing` | POST | mode=fair/roundrobin/manual，manual 时指定 uid |
| `/cline-route` | POST | Cline 模型的渠道偏好、限定及排除 |
| `/accounts/test` | POST | 真实短调用（消耗用量），成功后更新验证状态 |
| `/refresh` | POST | 后台刷新指定来源 |
| `/login/start`、`/login/cancel`、`/login/complete` | POST | Cline／OpenCode OAuth；complete 选择组织 |
| `/login/poll?id=...` | GET | 只返回公开授权状态、跳转链接与设备码 |

旧 `/platforms/*` 管理 API 保留兼容，独立页面已移除。Responses 设置在 GET/POST `/settings/responses`，整会话删除在 POST `/settings/responses/delete`。
