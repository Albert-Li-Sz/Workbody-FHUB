# API 与余额协议说明

适用版本：**1.0.8**。

## 地址与鉴权

客户端 Base URL 通常为 `http://<服务器IP>:8788/v1`，请求头使用面板生成的网关 Key：

```http
Authorization: Bearer <WORKBODY_API_KEY>
```

本文路径相对于服务根地址。模型协议遵循对应 SDK；余额和用量接口始终要求有效、已启用的网关 Key，面板会话及关闭模型调用鉴权不能绕过这一要求。返回使用 `Cache-Control: no-store`。

Key 固定绑定 `cn` 或 `intl` 时，查询只读取该渠道；未绑定时跟随当前默认出口。余额与客户端用量不接受 `X-Realm`、`realm` 或 `channel` 参数覆盖 Key 的渠道。

## 模型与生成

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| GET | `/v1/models` | 当前渠道可用模型列表 |
| GET | `/v1/models/{id}` | 单个模型详情，与列表条目的字段一致 |
| POST | `/v1/chat/completions` | Chat Completions，支持流式 |
| POST | `/v1/responses` | Responses，支持流式 |
| POST | `/v1/messages` | Anthropic Messages |

模型 ID 可以 URL 编码，包含 `/` 时使用 `%2F`。未知模型详情返回 `404 model not found`。目录可随上游更新，具体 ID、上下文、输出上限和能力以当前响应为准。

## 余额来源与刷新

所有余额入口都汇总当前 Key 渠道内全部账号的 WorkBuddy 剩余积分，包含停用账号。币种名称及金额字段是响应协议标签，数值单位统一为积分，不做人民币、美元或 Token 的换算。

| 参数 | 行为 |
| --- | --- |
| 不传 `refresh` | 过期或缺失数据自动刷新，默认查询缓存 60 秒 |
| `refresh=1` | 强制刷新当前渠道账号积分 |
| `refresh=0` | 仅读本机已有积分缓存 |

原生查询允许返回已知小计和完整性状态；各余额格式适配在剩余积分未知或刷新失败时返回 `503 balance_unavailable`。已用积分未知不会阻止纯余额查询，旧版 `subscription` 和账单 `usage` 仍要求完整的已用信息。

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

`provider` 只选择响应格式，实际数据渠道仍由当前 Key 决定。不要将官方厂商 Key 传给本网关作为账号凭据。

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

DeepSeek 使用两位小数的字符串余额，`is_available` 表示剩余积分是否大于零。`balance_infos[].currency` 为 `USD` 协议标签，用于兼容优先读取 USD 的客户端；顶层仍声明 `currency: "credits"`。千问 `Data.Currency` 同样为 `USD` 协议标签，`AvailableAmount` 是积分字符串，现金和授信字段为 `"0.00"`。

OpenAI 旧版 `subscription.hard_limit_usd` 为剩余＋已用积分；旧版账单 `usage.total_usage` 为已用积分×100，以适配旧客户端的 `/100` 计算。这些字段名不代表真实美元金额。

## 当前 Key 的 Token 用量

```bash
curl 'http://127.0.0.1:8788/api/billing/usage?range=today' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

同时支持 `/v1/api/billing/usage`。返回当前 Key 在所选渠道日志中记录的 `requests`、`errors`、`prompt_tokens`、`completion_tokens`、`reasoning_tokens`、`cached_tokens`、`total_tokens`，以及 `realm`、`channel`、`window`、`unit: "tokens"`。

`range` 可用 `today`、`week`、`month`、`all`、`custom`，默认全部历史；`since`、`until` 使用 Unix 秒。自定义范围示例：`?range=custom&since=1791388800&until=1791475200`。无记录返回零。推理 Token 已包含在输出计数内，总 Token 不额外重复相加；数据来源为网关日志，不包含绕过本网关的厂商调用。

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
