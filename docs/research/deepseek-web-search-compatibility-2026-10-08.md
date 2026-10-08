# DeepSeek 联网搜索与 FHUB 兼容性核对

核对日期：2026-10-08（Asia/Shanghai）。FHUB 核对基线为 `v1.1.0`，提交 `2342fe423ddd5f90f29b0399739508b035d1c54e`；下面的差异表描述该发布版本。DeepSeek Harness（DSH）源码固定为 `5badb15009ae1756c3afe0ae0cef1faafc290ccc`。网关修复已纳入 v1.1.1，见文末；运行验证使用本地模拟上游与搜索结果，没有调用真实模型 API。

## 结论

`DeepSeek Messages does not support response block server_tool_use` 与 DSH 主聊天适配器的错误完全相同。它拒绝服务端工具块，而 DeepSeek 官方 Messages 文档明确支持该块。与此同时，FHUB 的 Messages 联网执行与搜索历史回放确实不完整。两处兼容问题需要分别处理；尚不能确定用户这次返回原生块的是哪个服务。[DSH 解析器](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/llm-deepseek/src/translate.ts#L40-L56)、[DeepSeek Messages 文档](https://api-docs.deepseek.com/guides/anthropic_api/)

## 官方接口与 DSH 的实际要求

DeepSeek Messages 支持 `server_tool_use`、`web_search_tool_result`。官方 DSH 搜索插件向 `/anthropic/v1/messages` 发起非流式请求，工具声明形如以下示例，无需普通函数的 `input_schema`；`max_uses` 取配置值。一次搜索包含一次模型调用。[官方兼容表](https://api-docs.deepseek.com/guides/anthropic_api/)、[搜索请求源码](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/provider.ts#L197-L234)

```json
{"type":"web_search_20250305","name":"web_search","max_uses":5}
```

| DSH 通道 | 当前源码行为 |
| --- | --- |
| 主聊天 `llm-deepseek` | 流式块只接受 `text`、`thinking`、`tool_use`；其他块触发上述错误。停止原因也没有 `pause_turn` 分支。[解析器](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/llm-deepseek/src/translate.ts#L40-L89) |
| 辅助搜索 `web-search-deepseek` | 必须收到 `web_search_tool_result`；从结果读取 URL、标题、页面时间，再按 URL 拼接 `text.citations[].cited_text` 摘录；缺少结果块明确失败。[结果转换](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/provider.ts#L109-L168) |
| 搜索入口配置 | 独立使用 `web-search-deepseek.baseURL` 或 `DEEPSEEK_SEARCH_BASE_URL`，不会复用聊天的 `DEEPSEEK_BASE_URL`。改聊天入口不能证明搜索也走 FHUB。[配置解析](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/index.ts#L73-L121) |

DeepSeek 当前 Responses 文档明确忽略内置 `web_search`，但会把历史 `web_search_call` 重新放入上下文。不能将 Messages 原生搜索支持推广到所有协议。[Responses 工具与输入兼容表](https://api-docs.deepseek.com/guides/responses_api/)

## v1.1.0 已确认的差异

| 优先级 | 静态代码证据与影响 |
| --- | --- |
| P1 | Messages 工具没有 `input_schema`/`parameters` 就被跳过，随后加入“不可调用”提示；原生搜索声明因此不会成为可执行工具。[`wb_proxy.py:6215–6238、6363–6380`](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6215-L6380) |
| P1 | `_handle_messages` 只转成 Chat 请求，流式/非流式处理均没有 `WebToolFlow` 续轮。当前输出仅有 `text`/`tool_use`，不产生 `server_tool_use`。[请求与执行](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L9931-L10066)、[响应转换](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6456-L6511) |
| P1 | 历史 `server_tool_use` 被当成普通函数调用；`web_search_tool_result` 没有按 `tool_use_id` 配对。通用文本提取只读 `text`/`content`，丢失结果的 URL、标题、加密字段及文本引用。[块转换](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6132-L6139)、[历史转换](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6273-L6329) |
| P1 | Messages 历史的 `thinking` 全部跳过。DeepSeek 官方 Chat 工具多轮规则要求回传历次 `reasoning_content`，该转换不能保持此规则；补空值只可能容错，不能恢复推理内容。[转换](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6283-L6284)、[官方工具思考规则](https://api-docs.deepseek.com/guides/thinking_mode/) |
| P2 | Responses 仅在本地工具开关启用时执行 DDG 搜索；这不是 DeepSeek 官方搜索。工具安装只接收搜索/抓取布尔值，没有传递原生 `max_uses`、域名过滤、位置设置。[注入条件](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6011-L6018)、[`wb_webtools.py:45–57、184–214`](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_webtools.py#L45-L214) |
| P2 | Responses 流在收齐调用参数时已发 `web_search_call.completed`，真实搜索在外层循环随后执行；完成事件应移到执行结束之后。[事件](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L6988-L7024)、[执行顺序](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/2342fe423ddd5f90f29b0399739508b035d1c54e/wb_proxy.py#L9817-L9840) |

## 子协议边界

Anthropic 搜索格式规定：服务端调用与结果通过 ID 配对；加密结果与引用索引原样回放；长任务可用 `pause_turn` 续轮；流中搜索结果属于独立内容块。这是格式参照，不能据此断言 DeepSeek 已支持所有子字段、暂停行为或新版搜索工具。DeepSeek 已读文档只明确块级支持；DSH 辅助搜索也未实现暂停续轮或加密回放。[Anthropic 官方格式](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)、[DSH 消费字段](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/types.ts#L6-L39)

## v1.1.1 网关修复

v1.1.1 的实现：

1. `wb_messages_web.py` 接入共享 DDG 后端与 `WebToolFlow`，支持原生搜索声明、真实执行、流式和非流式模型续轮；逐轮累计用量并记录实际账号。本地开关关闭时明确拒绝原生搜索。普通函数仍交给客户端，混合调用返回客户端工具后等待真实结果。
2. 实现 `max_uses` 和域名过滤。位置设置及新版动态搜索不作静默降级，返回 `400`；继续使用调用／轮数／时间预算及 SSE 心跳。不完整的网络工具流报错，不生成成功结尾。
3. 原生模式返回配对的调用／结果块与真实摘录引用。SQLite 的 `web_replay` 表保存绑定 Key ID 的本地不透明引用，7 天、最多 4096 条；不伪造 DeepSeek 密文。历史转换保留 URL、标题、摘录、引用和输入思考，本次续轮保留真实 `reasoning_content`；外部密文及 `redacted_thinking` 不能恢复。
4. `X-FHUB-Web-Format: native|text|auto` 选择原生或文本格式。依据固定 DSH 源码，主聊天的 `x-deepseek-harness-user-id` 标识触发文本兼容，辅助搜索使用原生结果；该推断依赖标识仍被转发，可手动覆盖。[主聊天请求头](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/llm-deepseek/src/adapter.ts#L113-L124)、[辅助搜索请求](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/web/web-search-deepseek/src/provider.ts#L197-L234)
5. 新增 `/anthropic/v1/messages` 等入口别名；Responses 的搜索完成事件移至实际执行返回之后。
6. 联网续轮优先沿用上一轮账号，免费会话增加默认 256K Token 换号窗口及面板持久化设置；绑定键识别 DSH 会话标识，缺少标识时使用稳定系统／用户前缀。健康、限额、并发与优先级约束继续生效。

参数、模式、入口与回放边界见 [API 说明](../api.md#messages-搜索请求)。当前缺少客户端版本、聊天／辅助搜索实际入口及原始响应，仍不能确认原报错的完整链路；本地回归已覆盖服务端 HTTP 路由、搜索续轮、原生／文本输出、SSE 生命周期、Token 预算、断流、取消计量和 SQLite 重启回放；未在用户实际客户端上验证。仍需确认 DSH 辅助搜索已指向 FHUB；直接访问 DeepSeek 的请求不会经过本网关兼容层。
