# Workbody-FHUB 全项目审查

日期：2026-10-07。代码基线：`01ccabc1753eeb7a76005a264e66248959d75910`。

> 后续状态：本报告的 10 项缺陷已在 1.0.1 修复，见[修复报告](project-repair-2026-10-07.md)。下文保留修复前的证据和基线源码链接；当前复现脚本已扩展为回归探针，运行修复后的版本应返回 0。

检查范围包括 Python 服务与协议转换、账户和权限、用量与归档、后台任务、前端交互、Docker/Compose、发布工作流、测试和当前文档。以下区分可复现缺陷、结构与配置建议、尚需实际环境验证的部分。

本次重新运行现有测试：**82 个套件通过，0 个失败，0 个整套跳过**，其中 68 个 Python、14 个 JavaScript；部分套件内部的平台专用或外网用例仍按条件跳过。本机为 Python 3.14.7、Node 24.18.0。新增隔离探针复现了 **10 个缺陷，2 个 P1、8 个 P2**。现有测试没有覆盖这些错误输入、配置损坏、日志容量和线程生命周期边界。

P1 表示优先处理的权限或限额失效问题；P2 表示应修复的功能、可用性或凭据处理问题。该评级针对已经验证的触发条件，不代表所有部署都已经受影响。

## 复现方式与证据

- [后端复现脚本](../scripts/audit_project.py)：临时数据目录、合成账户和密钥、随机回环端口；上游请求全部替换为模拟实现。
- [前端复现脚本](../scripts/audit_project_ui.js)：从实际 HTML 提取函数，在 Node VM 中模拟 HTTP 和 DOM。
- [后端结果](../docs/project-audit-2026-10-07-backend.json)、[前端结果](../docs/project-audit-2026-10-07-frontend.json)。证据只包含合成数据及结果，没有真实账户、密码或 API Key。

在项目目录中运行 `python3 scripts/audit_project.py` 和 `node scripts/audit_project_ui.js` 即可复现。**退出码 1 表示成功复现了问题**，0 表示没有检出，2 表示后端探针自身失败。这两个脚本独立于现有测试入口。

## 已确认的缺陷

### A01 · P1 · 配置损坏会重新接受已经退役的启动 API Key

位置：[设置读取](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_settings.py#L67)、[鉴权回退](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L220)。

`load()` 遇到 JSON 解析错误会吞掉异常并返回空设置；`configured_keys()` 因而认为面板没有密钥，`identify_key()` 重新把进程启动时的 `API_KEY` 加入可接受凭据。

复现：先配置新的面板 Key，确认旧启动 Key 被拒绝；将临时 `settings.json` 写成损坏 JSON。之后旧 Key 被接受，新 Key 被拒绝。这个行为破坏了密钥撤销的保证，也把文件损坏和首次安装混为一谈。

建议：区分文件不存在与内容损坏；读取失败时保留最后一次有效鉴权快照，或拒绝受保护请求并提示修复配置。已经启用面板密钥管理后，不能因读取失败重新启用旧启动凭据。本次没有把这个结果扩大为“默认 Docker 已允许匿名调用”。

### A02 · P1 · 日志轮转会减少当天预算计数

位置：[当天用量扫描](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L1014)、[归档轮转](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_reqlog.py#L198)。

当天 Token、积分和按模型 Token 限额都依赖主文件 `usage.jsonl`。轮转会把容量超出的旧行移到归档，其中可以包含当天数据；主文件缩小时扫描器清空累计状态，随后只重算主文件。

复现：1200 条当天记录，每条 1 Token，设置合法的 1 MiB 轮转阈值。轮转后当天累计从 **1200 降到 484**，另外 716 条已经归档。探针使用小阈值缩短复现；默认 100 MiB 达到容量上限时也走同一条逻辑。

影响：已经达到每日预算的账户可能再次接单，模型限额与积分限额也受到同源计量影响。仅修改前端统计不能解决接单判断。

建议：用独立的当天累计账本维护限额，或让计量扫描覆盖当天主文件和归档，并处理文件替换、重启、并发追加和重复计数。

### A03 · P2 · 请求历史和指标静默丢弃每个文件前面的记录

位置：[固定 8 MiB 读取窗口](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_reqlog.py#L55)、[声明读取全部记录的入口](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_reqlog.py#L98)。

`_iter_rows()` 默认只读取每个文件末尾 8 MiB，`read_rows()` 和 `/requests`、`/requests/metrics` 却把结果当作完整记录使用。默认主文件轮转阈值是 100 MiB，两者的容量约定不一致。

复现：约 9.07 MB、2200 条记录的主文件，查询只返回 **2034 条**，首条索引为 **166**。响应没有说明前 166 条被截断。

影响：历史搜索、时间过滤、请求数和成功率可能偏差；归档文件同样受限。此问题与 A02 的预算扫描是两个独立读取路径，需要分别修复。

建议：按行流式遍历并在查询层分页/筛选，或明确返回数据窗口和截断标记。统计接口必须使用明确且完整的统计范围。

### A04 · P2 · URL 自动登录密码进入访问日志，页面也不清理该参数

位置：[URL 自动登录](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/dashboard.html#L4378)、[原始请求日志](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L7204)。

页面支持 `/?pwd=...` 自动登录；`bootPanel()` 和实际登录函数都没有清理 `pwd`。服务端访问日志直接记录包含查询参数的请求行。

复现：用合成值访问 `/?pwd=...`，HTTP 返回 200，日志捕获确认包含该值；运行实际启动函数确认会发起自动登录，URL 参数没有移除。

影响：使用这种登录方式时，明文密码留在浏览器 URL/历史和服务日志中。随机密码加盐存储无法覆盖这个泄漏路径。

建议：移除通过 URL 传递密码的入口，或用一次性登录凭据替代；服务端对 `pwd`、`key` 等敏感查询参数脱敏。仅在前端清理地址，无法撤回首次 GET 已经产生的日志。

### A05 · P2 · 匿名健康检查会触发同步账户刷新

位置：[健康检查](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L7617)、[账户可用性统计](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_accounts.py#L2092)、[带刷新副作用的 ready()](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_accounts.py#L683)、[容器探针](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/Dockerfile#L35)。

`/health` 在鉴权判断前调用 `POOL.count_ready()`，后者会对过期或接近过期的账户调用 `refresh()`。一个匿名 GET 因而能触发带凭据的上游刷新，并等待其完成。

复现：临时池内放一个过期的合成账户，将刷新模拟为等待 150 ms。匿名健康检查返回 200、耗时约 **162 ms**，刷新调用次数为 **1**。

影响：上游变慢或不可达时，健康检查也跟着阻塞。容器探针请求超时为 3 秒、Docker 检查超时为 5 秒，与实际刷新耗时没有隔离；重复访问还能制造额外的刷新请求。本次没有发出真实凭据刷新请求。

建议：健康检查使用内存快照，严格限制耗时；需要刷新时由后台维护任务或明确的管理操作执行。

### A06 · P2 · 保存排程设置后，“重启”可能实际停止调度器

位置：[设置保存调用 stop/start](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L8424)、[线程生命周期](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_scheduler.py#L76)。

保存排程设置时，后端调用 `stop()` 然后立刻 `start()`。`stop()` 只设置停止事件，不等待线程退出；`start()` 看到旧线程仍活着直接返回。旧线程随后按停止事件退出，后端却报告 `scheduler: restarted`。

复现：在线程启动等待阶段设置同步屏障，执行与设置保存相同的 `stop()` → `start()`。没有创建新线程，释放屏障后旧线程退出，**调度器不再有存活的工作线程**。

建议：设计明确的停止与启动生命周期，使用可中断等待并确认旧线程已结束；或直接更新运行配置，不为每次设置变更重启线程。返回结果应与实际运行状态一致。

### A07 · P2 · 启动初次巡检忽略暂停和停止状态

位置：[启动巡检](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_scheduler.py#L88)。

启动后等待 10 秒，随后无条件执行 `_execute_cycle()`；只有后续循环才检查停止事件和 `enabled`。用户在启动等待阶段暂停或停止调度器，仍可能执行一次自动任务。

复现：设置 `enabled=False` 且停止事件已置位，使用当前小时的签到排程与合成账户，跳过真实等待。初次巡检仍调用签到 **1 次**。

建议：初次巡检前同时检查停止和启用状态，等待使用事件机制，以便及时停止。保留手动触发任务的独立语义。

### A08 · P2 · 部分非法请求类型导致断开 HTTP 连接

位置：[Chat 转换入口](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L9857)、[消息归一化](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L3126)、[Responses 工具转换入口](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L9347)。

请求只经过 JSON 解析，缺少转换前的字段类型检查；部分转换发生在上游错误处理的 `try` 之外。

复现两个已鉴权请求：

```json
{"model":"deepseek-v4.1-flash","messages":[null]}
```

发送到 `/v1/chat/completions`，以及：

```json
{"model":"deepseek-v4.1-flash","input":"test","tools":42}
```

发送到 `/v1/responses`。两者都返回 **RemoteDisconnected**，服务端分别抛出 `AttributeError`、`TypeError`，没有正常的 HTTP 错误响应。

影响：客户端看到网络故障，无法区分参数错误；自动重试可能重复发送同一非法请求。其他类型错误还可能直接进入上游路径。

建议：转换前统一验证消息、工具、模型、布尔和数值字段，给出相应协议格式的 400 错误。对转换异常设置保护边界；不能把所有异常都伪装成上游 502。

### A09 · P2 · 将密码改为 admin 时，异常没有转换成参数错误

位置：[修改密码处理](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L8542)、[底层拒绝旧默认密码](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_settings.py#L214)。

HTTP 入口只检查新密码至少 4 个字符，`admin` 能通过这一关；底层存储函数明确禁止 `admin` 并抛出 `ValueError`，但调用方没有捕获。

复现：有效面板会话、正确当前密码、新密码 `admin`，结果为 **RemoteDisconnected**，服务端记录 `ValueError`。正确行为应是拒绝该密码并返回明确的 400 提示。

建议：复用同一套密码校验规则，把校验错误转成可读的参数错误。继续保留对旧默认密码的禁用政策。

### A10 · P2 · 输错当前密码会清除仍有效的前端会话

位置：[修改密码的 401 响应](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L8546)、[统一请求助手](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/dashboard.html#L2871)、[会话清理](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/dashboard.html#L4316)。

修改密码时，当前密码错误返回 401，但面板 token 仍然有效。`postJSON()` 遇到任意 401/403 都调用 `panelSessionLost()`，因此清除 token、停止轮询，并将错误变成“会话失效”。

复现：真实 HTTP 处理返回 401，同时后端确认面板 token 有效；在 VM 中运行实际 `postJSON()`，确认调用了会话清理且最终错误为 `unauthorized`。前端证据属于函数执行级验证，未在真实浏览器中再走一次完整交互。

建议：用明确的错误码区分会话失效和修改密码的校验失败。当前密码输入错误应保留现有会话并显示原始校验消息。

## 结构与排布建议

这些是维护成本和职责边界问题，不与上面 10 个已复现缺陷混计。

| 观察 | 不合理之处 | 建议 |
| --- | --- | --- |
| 后端入口 [wb_proxy.py](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py) 有 10,328 行 | 路由、鉴权、协议转换、日志计量、管理操作和启动代码集中；修一个边界很容易漏掉另一个入口 | 先提取公共请求校验、鉴权与用量服务，再分别拆 Chat、Responses、Messages 适配器和面板路由 |
| 前端 [dashboard.html](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/dashboard.html) 有 6,847 行 | CSS、DOM 模板、HTTP 助手、业务状态和操作函数混在一个文件，业务 401 与会话 401 被同一个助手处理 | 拆出静态 CSS/JS，集中错误码与会话管理；按账户、指标、模型、任务、设置组织功能 |
| `POOL`、`PANEL`、`SCHEDULER`、密钥等运行状态集中在入口全局变量 | 服务和模块之间通过全局变量耦合；调度器日志还反向导入入口模块 | 用显式运行上下文和日志回调传递依赖，使管理请求与模型请求共享清晰的状态接口 |
| 根目录混有运行模块、平台启动器、[批处理重写工具](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/_fixbats.py#L237)、取价维护工具 | 运行、开发和维护用途不易辨认；`_fixbats.py` 会在顶层直接重写启动脚本 | 维护工具移到 `tools/` 或 `scripts/`，增加 main 入口；运行模块按领域组织，启动器单独归类 |
| 当前操作说明与大量上游历史更新混在 README | 当前规则、旧行为和已经修复的问题不易区分 | README 保留简洁安装、使用、当前限制和原项目声明，历史更新移入独立文档并保持可追溯 |

建议按功能边界逐步拆分，先修复缺陷并补回归验证，避免一次移动所有文件导致启动器、Docker COPY 和跨平台路径同时变化。

## 配置与发布流程建议

1. **日志容量需要一致的契约。** [默认归档阈值](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_settings.py#L119) 为 100 MiB、查询窗口为 8 MiB，而限额还依赖轮转后的主文件。应分别定义“保留期”“查询分页”“统计账本”，避免一个容量参数改变业务限额。
2. **密码环境变量优先级需要显式展示。** Compose 可持续传入 `PANEL_PASSWORD`，[启动代码](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_proxy.py#L10150) 每次启动都会重新设置它。在网页修改密码后，重启可能恢复环境变量里的值。这符合当前启动覆盖规则，属于容易误解的配置行为；应在面板和部署文档说明持续覆盖，或提供明确的一次性重置方式。
3. **默认 root 是部署取舍。** [Compose](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/docker-compose.yml#L6) 默认 UID/GID 为 `0:0`，已支持自定义。可以考虑为新部署准备普通 UID 及数据目录初始化流程；迁移前要处理已有目录权限，不能只改 UID。
4. **暂停接单与暂停任务应说明区别。** [任务默认配置](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/wb_settings.py#L623) 的 `include_disabled_in_tasks=True`，停用账户仍可能执行签到和保活。这是已有、可配置的策略，不能直接视为 bug；建议在停用按钮附近解释，或提供单独暂停后台任务的操作。
5. **版本号有多处手工来源。** API 版本、HTTP server version、Docker 标签、Compose 默认镜像、README 和 [镜像验证脚本](../scripts/verify_image.py#L11) 都包含 `1.0.0`。现有发布检查只比对两个 Python 字符串和 tag。建议统一版本来源，并检查镜像与安装配置的版本一致性。
6. **发布后缺少自动容器验证。** [镜像发布工作流](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/.github/workflows/docker-publish.yml#L37) 在构建前运行宿主机测试，随后构建推送两种架构，没有自动运行成品镜像的启动、鉴权和非 root 数据目录测试。可以接入现有验证脚本，使用隔离卷和明确的发布 revision 验证产物。
7. **镜像验证依赖当前工作树，容易产生误报。** [验证脚本](../scripts/verify_image.py#L49) 将当前工作树的 README 等文件哈希与镜像比较；当前 main 与 `v1.0.0` 的 README 已不同。拿 main 去验证旧版本镜像会因为文档变化失败。应显式指定预期的 release revision，并从那个 revision 生成预期文件哈希。
8. **测试运行器缺少套件超时。** [测试入口](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/tests/run_all.py#L81) 对每个子进程没有超时；卡住的套件会一直阻塞后续测试。建议增加合理的单套件超时并保留诊断输出。
9. **当前 README 仍写着已经修复的网络防护缺陷。** [网络工具说明](https://github.com/Albert-Li-Sz/Workbody-FHUB/blob/01ccabc1753eeb7a76005a264e66248959d75910/README.md#L231) 仍描述“只挡字面私网地址”，并称 DNS、重定向、多轮历史与计量仍有已复现问题；当前实现和对应回归已经包含这些修复。还存在重复的 Web 看板功能项。应更新当前能力与限制，保留原项目声明、致谢和许可证原文。

`0.0.0.0:8788` 是用户指定的部署目标，当前 Compose 与该要求一致，本次不把这一绑定列为错误。

## 验证边界与处理顺序

本次功能复现使用隔离本地 HTTP 服务和合成数据。真实上游模型、真实 OAuth、生产网络中的 DuckDuckGo HTML/Lite、代理与 DNS 波动、真实浏览器的移动端交互，以及新的 Docker 成品构建均未在本次重新验证；不据此宣称生产服务或镜像异常。现有发布和部署状态也不由本地测试替代。

优先处理 A01、A02；随后处理调度器的 A06/A07 和公共请求校验 A08；接着修复凭据 URL、健康检查、归档查询和密码交互。修复时用完整计量、真实线程生命周期和实际 HTTP 响应做回归，再逐步调整目录与文件边界。
