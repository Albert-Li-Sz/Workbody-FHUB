# 上游同步：2026-10-09

本次对照 [workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub) `main` 的提交 `e4e8e495901fcf9f2d0893cd5fb42c05cc5b7976`（v1.6.17，2026-10-08）选择合入，Workbody-FHUB 发布为 **1.1.3**。来源与逐条提交记录保存在 [upstreams.json](../upstreams.json)，上游版本记录保存在 [CHANGELOG.upstream.md](../CHANGELOG.upstream.md)。

## 合入的更新

| 上游提交 | 内容 | 本分支实现 |
| --- | --- | --- |
| `01a45c229e` / #180 | Claude Code 会话内 system 消息 | Messages 接受 system／developer，按原位置转为上游 system，保留文字块 |
| `41872af8d6` / #177 | 部分实时推理配置覆盖 | 按字段合并 reasoning，保留 supportedEfforts，不错误固定可选 effort |
| `74ea87e859` / #178 | 连续添加 Key 丢失原 Key | 显式删除 upsert、保留省略字段、按密钥保持原 id；补充已删除 id 防复活与整次校验 |
| `e94dee93b9` / #179 | 批量刷新账号凭证 | 账号页按钮，最多 2 个后台任务，异步进度与批次合并，兼容原同步入口 |
| `9ac97c8` / #149 | 企业空间额度查询 | 从 JWT 识别企业，按周期已用与额度计算余额；缺失、非有限或非法额度不返回伪造 0 |
| `30e3543` / #130 | 国内／国际限额覆盖 | 全局默认＋分渠道覆盖，留空继承、0 关闭；读取旧平面设置并写入 SQLite |
| `396014e584` / #174 | 抵扣截止时间及临期积分优先 | 抵扣截止时间解析、长期占位包过滤、余额锁与后台退避；临期窗口默认关闭，仅新付费选号采用 |
| `1a7c41b` / #133 | 费用估算总开关 | 关闭取价与估算，保持 Token／实际积分；开关纳入 SQL 分析缓存版本 |
| `5a04d080d8` / #186 | 积分扣减历史的昵称与表头 | 缓存请求行，账号加载后补绘昵称，桌面滚动时表头固定 |
| `37b6e6fb81` / #185 | 计价缓存热点优化 | 策略文件 stat TTL 1 秒＋内部写入立即失效；时间线时间戳缓存供二分查找 |
| `6887e3a095` / #181–184 | 有上限并行测试、失败诊断、共享 DOM | 每套件独立数据目录、默认最多 4 并行、可保留日志、超时清理进程树；新 UI 测试使用严格共享 DOM |

## 与既有功能衔接

账号手动优先级继续先于同级分配，免费模型在国内／国际分别比较当天 Token 与在途预估，免费会话的 256K 换号窗口继续使用。临期优先作用于新的付费选号；已有会话先沿用现有亲和判断，搜索续轮仍优先使用上一轮账号。

SQLite WAL、schema 2 小时用量汇总与持久化导出队列、HTTP 连接池、SSE 心跳与 Nginx、严格流式终止检查、Messages 本地搜索回放、默认提示词透传继续由本分支维护。上游 JSON 用量扫描／趋势缓存对应的功能已由 SQL 汇总和增量视图覆盖。面板改进适配现有拆分脚本与简繁体布局，旧全局限额无需手动搬迁。

生成协议使用 HTTP/SSE。此次同步没有新增 WebSocket 生成协议。

## 验证入口

```bash
python3 tests/run_all.py --logs /tmp/workbody-fhub-tests
python3 tests/_mobile_check.py
python3 scripts/verify_image.py <镜像> --revision HEAD --pull --non-root
python3 scripts/verify_nginx_image.py <Nginx镜像> --app-image <应用镜像> --revision HEAD --pull
python3 scripts/verify_upgrade.py --archive <源码归档> --image <应用镜像> --nginx-image <Nginx镜像>
```

新增回归覆盖消息位置、实时推理配置、Key 保存、分渠道继承与 0、手动优先级与临期规则、免费公平及会话窗口、企业额度、失效时间、余额退避、批量凭证并发、计价缓存、SQLite 重载及 UI 操作。升级检查包含原生 1.1.0、Compose 1.1.0／1.1.1／1.1.2 到本版并回滚，使用合成数据。实际供应商接口、真实账号以及公网证书签发需在部署环境确认。
