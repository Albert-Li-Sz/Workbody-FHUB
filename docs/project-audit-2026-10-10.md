# v1.2.4 项目检查（2026-10-10）

## 范围与证据

检查网关入口、三协议转换、账号与组织路由、凭据刷新、调度与用量、连接池、SQLite／私有文件、面板鉴权和动态 HTML、Docker 构建与升级发布路径。执行全部 108 个测试文件；合成后端与前端审计返回空 findings。合成测试使用隔离目录、模拟凭据与回环网络，真实联调仅使用用户已授权的 OpenCode OAuth 账号。

## 已确认并修复

| 问题 | 修复与验证 |
| --- | --- |
| OAuth 令牌占位符被直接发送，上游 401 | 仅解析当前账号的官方变量；切换账号、刷新 token 和重启均有回归 |
| 使用旧 Zen 地址，遗漏租户头与模型协议 | 读取官方 provider.api、组织头、每模型协议／地址；实际官方网关调用成功 |
| Zen／Go 同名模型混用，Go 请求进入钱包计费 | 独立网关与 `opencode/go/...`；凭据、协议、上游 wire ID、导入导出和重启测试 |
| 部分 provider 仅下发 Key 时目录丢失 | 分 provider 继承内置配置；完整 Zen 与不完整 Go 同时存在的回归 |
| Go 额度／套餐限流影响其他模型 | 正常、耗尽、缓存失败与 Go 429 隔离回归；Zen 仍可选 |
| 面板把上游 401／403 当作面板登录失败 | 仅已鉴权的管理操作映射为 502；原登录保护与实际生成状态保持 |
| Messages 输入 Token 与缓存重复计算 | 未缓存、缓存读、缓存写相加等于总输入；32 + 128 = 160 的实号结果 |
| Messages 缓存写入跨协议回放丢失 | 单位规范、往返与非法计数回归 |
| 官方 cost 字段未显示价格 | 规范为 USD／百万 Token；Go 标注配额参考价，未知余额保留未知 |
| 单个模型失败显示为整个账号冷却 | 区分部分模型与全账号；不因确定性免费限制反复换号 |
| 平台、订阅和提示难以辨认 | 平台色点／页签、计费徽标和语义提示；深浅主题十组文字／背景均达到 4.5:1 |

## 实际调用

- Zen `space-bunny-free`：Chat、Responses、Messages，各自非流式和 SSE 均 HTTP 200，返回 OK，并出现正常终止事件。
- Go `deepseek-v4.1-flash`：原生 Chat，非流式／SSE 均 HTTP 200。
- Go `claude-haiku-5-5`：原生 Messages，非流式／SSE 均 HTTP 200。
- Go `gpt-6-luna`：原生 Responses，非流式／SSE 均 HTTP 200。
- Responses 使用 `previous_response_id` 续接后记住上一轮测试内容；SSE 保留 `X-Accel-Buffering: no`。
- 官方 Go 额度接口返回 HTTP 200，显示 5 小时／每周／每月余量与重置时间；临时验证网关 Key 随后撤销。

## 保留与安全检查

WorkBuddy 的 core.js、accounts.js、wb_accounts.py 与正式 v1.2.1 保持相同内容；原账号区域与 OAuth DOM 的保护测试通过。凭据采用私有原子写入，公开模型／状态递归移除敏感字段；新 Go 网关通过官方 HTTPS 主机验证。连接池、代理、TLS、跨源跳转凭据剥离、会话归属、SQLite 参数查询、升级归档路径与私有数据排除均有现有回归。没有给新接入添加任意环境或文件读取能力。

## 验证边界

- 真实生成结果只覆盖列出的 OpenCode 账号与模型。当前没有新增 Cline／Command Code 实号，因此这两个来源依靠既有合成回归，不能由 OpenCode 的成功推出其付费模型全部可调用。
- 某些 Zen 免费模型仍返回官方 FreeTierError；exo-free 在测试时返回 ModelDeprecated。FHUB 明确返回对应代码，不添加假工具、删减上下文或更换模型来制造成功。
- 发布工作流独立验证 Linux amd64／arm64 应用和 Nginx、各旧版升级回滚并生成校验附件；完成状态以本版本 Release 的 images.json 和验证附件为准。
- 测试账号和模型列表、官方价格、额度及上游限制会变化；接口依实际账号配置为准。

## 后续性能方向

当前保留有界连接复用、按账号与代理隔离、有界刷新队列、目录缓存、SQLite WAL、SSE 局部更新和较大会话换号窗口。实号短请求验证不能代表并发长上下文性能；若继续优化，优先根据连接等待、上游首包与首字分段指标做负载测量，避免为降低首字耗时删改上下文。

[OpenCode Go 官方接口说明](https://opencode.ai/docs/go/) · [Zen 官方接口说明](https://opencode.ai/docs/zen/) · [Anthropic 缓存计数](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) · [界面配色参考](https://getdesign.md/airbnb/design-md)
