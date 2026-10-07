# 固定 OpenCode 出口

本整合分支在原来的 WorkBuddy 国内、国际固定出口之外，新增 API Key 的 `opencode` 绑定。继续使用 Python 3.9+、Docker / 1Panel 和现有 accounts / usage 数据卷。

## 配置与调用

1. 打开「设置 → OpenCode」，选择官方 Zen、官方 Go 或自建兼容网关。官方地址分别为 `https://opencode.ai/zen/v1`、`https://opencode.ai/zen/go/v1`；自建方式填写上游实际提供的 API Base URL。
2. 填写该上游的 API Key，启用出口，按需选择现有代理槽与超时，点击「保存 OpenCode 上游」。密码框留空保留已有 Key；只有勾选清除选项才删除已存 Key。
3. 在「设置 → API Keys」编辑需要使用的网关 Key，将出口绑定设为「固定 OpenCode 出口」并保存。修改已有 Key 的绑定时，Key 内容留空即可保留客户端凭据。
4. 客户端继续连接 `http://你的网关:8788/v1`，使用网关 Key。按模型支持的原生协议调用，`GET /v1/models` 自动返回 OpenCode 渠道目录。

上游 Key、网关 Key、面板会话分别认证。上游 Key 不从客户端请求取得，也不出现在设置读取响应中。默认 WorkBuddy 出口与旧 Key 行为不变；选择模型页渠道只影响目录。新增配置立即生效，无需重启。

## 当前兼容范围

| 接口 | 行为 |
| --- | --- |
| `POST /v1/chat/completions` | 透传 Chat 请求、工具与原生 JSON / SSE；上游 Bearer 认证。 |
| `POST /v1/responses` | 透传 Responses 请求、工具与原生事件；上游 Bearer 认证。 |
| `POST /v1/messages` | 透传 Messages 请求、工具与原生事件；上游 `x-api-key` 认证，保留 `anthropic-version` 与 `anthropic-beta`。 |
| `POST /v1/messages/count_tokens` | 原生转发，上游是否支持由其返回状态说明，不计入对话次数。 |
| `GET /v1/models` | Zen / Go 使用各自官方目录和元数据缓存；自建兼容网关读取其认证后的 `/models`。 |

这是原生协议转发，未增加跨协议转换、Google 原生接口或 agent 会话。客户端需要选择与上游模型匹配的协议；模型出现在目录中不代表这个账号有权使用。官方协议对应关系以 [Zen 文档](https://opencode.ai/docs/zen/) 与 [Go 文档](https://opencode.ai/docs/go/) 为准。

配置未启用、缺少上游 Key、绑定代理槽不存在或已停用时返回 503，不会自动改走 WorkBuddy 或直连。入口模型限制、封禁与公共并发上限仍生效。上游错误状态和 `Retry-After` 保留，错误体中的上游 Key 回显会被遮蔽；不跟随重定向，不自动换 IP 或重试。连接和读空闲超时由 OpenCode 配置控制。

流式字节原样输出，正常结束标记由上游提供；上游截断和客户端断开记录为中断，不补造成功结束事件。Token 用量统一归入 `realm: opencode`，Messages 的缓存输入参与 Token 统计，WorkBuddy 积分不参与。现有 OpenRouter 花费仍是等价估算，不代表 OpenCode 的实际账单。

## 验证边界

`tests/_test_opencode_exit.py` 启动真实本地 HTTP 网关与模拟上游，验证三协议、SSE、认证隔离、Key 绑定、模型限制、错误 / 重定向 / 截断、并发释放和私有持久化。JS 测试验证出口选项、历史徽标、保存载荷与代理槽异步加载。未使用真实 OpenCode 上游凭据完成模型回答；设置中的「已配置」只表示出口已启用并保存了 Key。

## 下一步建议

| 优先级 | 改进 | 解决的问题 |
| --- | --- | --- |
| 高 | 模型页显示可用协议与原生接口 | 避免客户端把 Responses 或 Messages 模型按 Chat 协议调用；未知能力保持未知。 |
| 高 | 完整备份恢复 | 一次迁移 WorkBuddy 账号、OpenCode 上游配置、代理槽与网关 Key 绑定。现有账号导出仅包含 WorkBuddy 账号，不能代表完整迁移。 |
| 中 | 分渠道诊断与手动调用验证 | 区分目录获取、保存配置、认证成功和完成回答，并展示 401 / 403 / 429 的具体原因。 |
| 中 | OpenCode 多上游与渠道额度 / 并发分配 | 在保持总并发保护的同时，避免单渠道占满全部容量；不把上游配额问题当作可重试的网络故障。 |

完整备份、多账号与平台发布的实施顺序见 [整合方案](integration-plan.md)。
