# 性能与可靠性（1.1.3）

## 提示词与流式失败

默认 `prompt.mode=passthrough`，`prompt.retry_on_content_rejection=false`。需要启用时在设置中显式勾选：只对上游明确的 `11140` 内容拦截，将该请求改为中性提示词重试一次。普通 403 不触发，其他请求继续使用原模式。`/settings` 的 `prompt_retry_status` 显示次数、最后模型与时间，不保存提示词正文。

Chat、Messages、Responses 共用上游帧和终止检查。上游 SSE 的错误对象、非法 JSON、没有完成标记的 EOF 都算失败；正常 `finish_reason` 后省略 `[DONE]` 可接受。已经报告的部分用量仍入账，没有 usage 时标记 `usage_missing`，不推算输入 Token。

Responses 正常结束使用 `response.completed`；输出上限使用 `response.incomplete`；失败使用 `response.failed`，与 [OpenAI 流事件定义](https://developers.openai.com/api/reference/resources/responses/streaming-events) 对应。

## 首字与各阶段耗时

请求计时从 HTTP 请求进入开始，包含上传解析及排队。生成时长使用单调时钟，避免系统时间调整影响速度。请求归档的首字单元格提示显示各阶段，`/usage/perf` 与 `/requests/metrics` 的 `timings` 提供样本数、平均值及 P50/P95。

| 字段 | 测量范围 |
| --- | --- |
| `queue_ms` | 等待生成并发名额 |
| `parse_ms` / `normalize_ms` | 请求解析／协议转换 |
| `account_selection_ms` | 调度锁与选择账号 |
| `connection_pool_wait_ms` | 等待上游连接池 |
| `connect_ms` | 新连接建立，含 DNS／TCP／TLS 或代理握手 |
| `upstream_send_ms` / `upstream_headers_ms` | 发送请求／等待响应头 |
| `first_event_ms` | 首个推理、工具参数或正文事件 |
| `upstream_text_ms` | 首个上游正文 |
| `first_text_ms` | 首个正文成功写给客户端（SSE） |

这些值不是互不重叠的分账项；重试会累计阶段等待。`first_text_ms` 不等于客户端屏幕实际显示时间，网络与客户端缓冲仍可能增加延迟。旧记录没有新增字段；无正文、仅工具调用或非流式请求可能没有正文时间。保留的 `ttft_ms` 继续表示首个生成内容事件。

## 热路径与统计

- 请求选择不再同步刷新全池凭据。后台提前 300 秒刷新，两个工作线程、同账号合并，失败退避 30–600 秒。
- 每轮选择读取一份调度配置和每日计量快照。实际消费提交与移除在途预估共用调度锁；JSONL 导出、轮转及 Redis 镜像在锁外执行。
- SQLite schema 2 的小时汇总通过事务内触发器维护。Token 汇总读小时桶，首尾不足一小时的范围读取原记录，保留精确边界。请求归档筛选、LIMIT/OFFSET、Key 与渠道筛选在 SQL 内执行。
- 费用与复杂分析首次建立视图后只合并新增记录；清理历史或价格政策改变时重新建立。缓存最多 16 个视图。性能分位数默认只采样最近 5000 条，并报告样本范围。
- SQLite 用量是事实来源，JSONL 是兼容导出。待导出记录保存在数据库，文件写入失败后每 30 秒重试；进程重启继续导出。极端中断可能重复导出最后一批，记录 `event_id` 可去重，数据库统计不重复。
- JSONL 达到大小上限后整段重命名，不解析重写大文件。归档清理与 SQLite 保留策略独立，默认 SQL 保留全部历史。

计价策略文件的 stat 结果最多缓存 1 秒；内部写入立即清除该缓存，外部文件编辑最多延迟 1 秒可见。价格时间线缓存可供二分查找的时间戳列表，减少重复构建。费用估算总开关与变体继承设置纳入分析视图版本，关闭／重开立即重建，Token 与实际积分计量继续保留。

## 面板、连接与任务

SSE 合并活动状态与用量变化，每 750ms 更新变化的账号行；每页最多 50 个账号。首次连接、重连和每分钟同步完整状态。账号编辑时延后重绘，代理槽缓存一分钟。

JS/CSS 源码位于 `dashboard_static/`，服务端按原顺序合并脚本，提供内容摘要 URL、ETag、gzip 与一年缓存。HTML 使用 nonce。Nginx 仅静态资源开启 gzip，生成流与面板 SSE 关闭缓冲和压缩，继续发送空闲心跳。

`WB_HTTP_MAX_CONNECTIONS=128` 限制已接受 HTTP 连接线程，超过返回 503 和 Retry-After；长驻面板 SSE 也占用名额。原生成并发预算独立。任务扫描四个工作线程、整次最多 60 秒；任务执行保持每账号串行、账号间最多三个工作线程。

手动批量凭证刷新采用同一个有界队列（最多 2 个任务并发），面板提交后轮询轻量进度，多个页面共用正在执行的批次。启用临期调度后，后台每轮仅挑选一个需要更新的账号余额，按设置的缓存时间和失败退避刷新。

登录在验证密码前原子预留尝试；默认同 IP 每分钟五次，最多四个并行密码验证。只有 `WB_TRUSTED_PROXIES` 列出的反代能提供 `X-Real-IP`；配套 Nginx 重写该头。使用其他反代时显式配置可信来源。

当前为单实例 SQLite 调度；Redis 可选镜像会话，不能替代共享计量与在途租约。生成协议继续为 HTTP/SSE，尚无 WebSocket 生成入口。

## 发布检查

应用与 Nginx 镜像都验证 amd64／arm64，应用另外验证 UID/GID 1000。Nginx 校验源码摘要、配置、启动、静态 gzip 与流式首帧／心跳。两者通过后推广 `latest`，最后统一生成所有附件的 SHA-256；Release 附带 `app-verification.json`、`nginx-verification.json` 和镜像摘要。

本地与 CI 使用合成账号及离线后端。这能确认协议、调度、迁移和缓冲行为；公网 Let’s Encrypt 签发／续签及真实上游首字速度需在实际部署网络中观察。
