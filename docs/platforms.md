# Cline、OpenCode Zen 与 Responses 会话（1.2.1）

## 配置账号

在 **平台与会话** 添加账号。Cline 可选择设备登录，在官方页面授权后由面板轮询完成导入；也可导入 access token 与 refresh token。网关沿用官方 WorkOS 授权格式，刷新凭证走该账号绑定的代理。Zen 填写从官方控制台取得的 API Key。

账号支持名称、启用状态、非负整数优先级、代理槽及模型通配白名单。优先级默认 `100`，数字越小越早调用。编辑时凭据留空保留现有值。批量导入可上传 JSON 数组：

```json
[
  {"upstream":"cline", "access_token":"<token>", "refresh_token":"<refresh>", "priority":100},
  {"upstream":"opencode_zen", "api_key":"<key>", "priority":100, "models":["*"]}
]
```

凭据保存在私有 `accounts/upstreams` 和 SQLite 文档中，面板返回账号状态和脱敏元数据。模型目录、余额与 Cline 已付积分定期后台刷新；手动「刷新」可立即触发。目录失败时保留缓存并显示错误，不把目录同步视为真实调用成功。

## 网关 Key 与模型 ID

在 **设置 → API Key** 勾选 `allowed_upstreams`。合法值为 `workbuddy`、`cline`、`opencode_zen`。旧 Key 缺少字段时默认仅允许 WorkBuddy；旧页面保存也保留已设置的平台权限。WorkBuddy 的 `realm=cn|intl` 独立于平台权限。

| Key 范围 | 模型 ID |
| --- | --- |
| WorkBuddy | 原来的模型 ID |
| Cline | `cline/<原始ID>`；仅允许 Cline 的 Key 也接受原始 ID |
| Zen | `opencode/<原始ID>`；仅允许 Zen 的 Key 也接受原始 ID |
| 多个外部平台 | 使用平台前缀，避免同名歧义 |

```bash
curl 'https://<公网IP>/v1/models?upstream=cline' \
  -H "Authorization: Bearer $WORKBODY_API_KEY"
```

`GET /v1/models/{id}` 支持包含斜线的 ID。Cline 目录合并官方推荐、免费、Pass／Cloud 分组与官方客户端使用的 OpenRouter 文本输出目录；OpenRouter 价格标记为参考 USD／Token，不用于推算 Cline 实际积分。能否调用取决于账号订阅、地区和实际权益。

Zen 目录取自官方 `/zen/v1/models`。协议优先读取上游元数据，缺少时采用官方 Zen 模型表：GPT、Grok、Muse 使用 Responses；Claude、部分 Qwen 系列使用 Messages；其他受支持模型使用 Chat。需要原生 Gemini 协议的模型当前不纳入目录。官方目录变化后需刷新，具体协议以模型详情为准。

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

同平台、同优先级的免费账号比较当天免费 Token 加在途预估；付费账号比较当天实际积分／USD 加在途预估。预估只用于选择，实际用量入库后移除预估。免费会话默认 262144 Token 换号窗口，减少小幅增长引起的频繁切换。已确认的取消／失败用量也计入；未知消费保持未知。

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

多平台通过 `upstream` 分别查询，不能把积分和 USD 相加。含 WorkBuddy 的 Key 未指定平台时默认查询 WorkBuddy；只允许一个外部平台时默认该平台；允许多个外部平台时必须指定。`provider=deepseek|kimi|…` 仅控制兼容响应格式。Token 查询只统计当前网关 Key 发起的请求；平台每日调度统计可包含 Cline 同步到的其他实际积分消费。

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
