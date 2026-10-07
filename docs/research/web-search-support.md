# Workbody-FHUB 网络搜索说明

日期：2026-10-07。网关使用 DuckDuckGo 的 HTML 搜索页，页面或网络异常时最多尝试一次 Lite 搜索页。两者是官方提供的非 JavaScript 版本，不是保证可用性的搜索 API；仍可能遇到验证码、限流和网络不可达。[DuckDuckGo 官方说明](https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript)

## 执行路径

本地网络工具默认关闭。启用后，Responses 请求中声明的搜索/抓取工具由网关替换为普通函数，模型生成调用，网关执行工具并回传结果，然后模型继续回答。流式与非流式 Responses 接入了此循环；Chat Completions 与 Messages 当前没有相同的代跑循环。配置和普通客户端工具的声明沿用原有规则。

HTML 与 Lite 结果由 Python 标准库 `HTMLParser` 解析，支持属性重排、单双引号、嵌套标签及 HTML 实体。DuckDuckGo 跳转只解码一次，保留目标地址中的转义；重复地址和广告结果被过滤。搜索来源与成功抓取的 URL 都可参与引用标注。[Python 官方 HTMLParser 文档](https://docs.python.org/3/library/html.parser.html)

## 网络与缓存

| 项目 | 当前行为 |
| --- | --- |
| HTML/Lite | 优先 HTML；验证码、未知页面或临时网络错误时最多回退一次 Lite，不提交或解决验证码。 |
| 限流和无结果 | HTTP 429 返回错误，不重试；明确的无结果页面返回无结果；两种布局都无法识别时返回错误。 |
| 成功缓存 | 120 秒，最多 128 个查询；结果数量不同可复用同一查询。同一查询的并发请求合并。 |
| 错误冷却 | 5 秒，保持错误语义，期满后可重新访问后端。 |
| 查询与输出 | 查询最长 2000 字符；最多 10 个结果，标题最多 300 字符、摘要最多 1200 字符。 |
| 响应 | 请求共享 20 秒预算；分块读取检查时间，传输及 gzip 解压后的内容均不超过 2 MiB，只接收文本。DNS 查询通过有界线程池并按剩余预算等待。 |
| 代理 | `WB_WEB_PROXY` 指定独立代理；未设置时使用进程代理与 NO_PROXY。HTTPS 目标使用 http:// CONNECT 代理；HTTPS 代理可转发 HTTP 目标，TLS 内再次嵌套 TLS 的组合会明确拒绝。代理转发目标也使用已验证的数值 IP，HTTPS 的证书与 SNI 仍校验原域名。WorkBuddy 账号代理槽不会自动成为搜索出口。 |

## 当前验证与限制

匿名查询 `Python documentation site:docs.python.org` 在此 Mac 上使用新的公网 DNS 校验和 IP 固定连接得到 3 个真实来源；首次 1533ms，重复请求命中缓存，耗时按毫秒取整为 0ms。记录见[实网证据](../search-2026-10-07-evidence.json)。这一次匿名结果不证明部署主机的网络、负载下可用性或真实模型的工具选择。

抓取现已校验初始 URL、全部 DNS 地址和最多 5 次重定向，并只连接验证过的公网 IP；拒绝回环、私网、共享地址段、保留地址及歧义 IP 表示。此策略同样用于搜索请求，保留原域名的 Host、TLS SNI 和证书校验。[OWASP SSRF 指引](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

工具编排由 `wb_webflow.py` 管理完整历史、调用 ID、来源、累计用量和预算。默认最多 3 轮（配置上限 8）、16 次工具调用，180 秒预算；超限明确失败。每轮按实际账号记录用量，最终响应汇总；模型和连接中断时保留已获用量。流式终止事件使用同一 response ID 和递增序号。

同次完成包含本地工具和客户端工具时，执行本地工具后，把其真实结果作为 assistant 文本连同客户端工具调用交回客户端；保留客户端调用 ID，不生成客户端工具的假结果，不在缺少这些结果时继续请求模型。完整回归和镜像验证见[修复报告](../audit-2026-10-07.md)。
