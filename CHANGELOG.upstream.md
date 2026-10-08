# 上游版本记录

来源：[workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub)，截至提交 `e4e8e495901fcf9f2d0893cd5fb42c05cc5b7976`（v1.6.17）。上游原文保留；本分支实际行为与选择合入记录见 [CHANGELOG](CHANGELOG.md)。

## 六、版本更新记录 (Changelog)

### v1.6.17

重磅生态兼容与架构演进版本：正式支持 Claude Code、修复 API Key 误覆盖、引入临期积分优先分派机制，并实现测试基础设施多进程并行加速：

- **全面兼容 Claude Code 接入**（[PR #180](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/180)，感谢 [@LeoK77S](https://github.com/LeoK77S)，issue #171）：自动将 `messages` 内部的 `system` 角色提取并与顶层 system 合并，彻底解决 Claude Code 调用 `/v1/messages` 报 400 失败的问题；
- **修复 API Key 连续添加时误覆盖老 Key**（[PR #178](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/178)，感谢 [@LeoK77S](https://github.com/LeoK77S)，issue #175）：前端与服务端采用 upsert 语义同步，彻底杜绝连续添加 Key 导致老 Key 与出口绑定被意外软删除的问题；
- **智能调度：平滑加权优先分派临期积分账号**（[PR #174](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/174)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：自动识别 7 天内即将过期的账号积分包，采用平滑加权轮询优先消耗快过期的账号额度，杜绝积分浪费；
- **大幅提升用量统计与时序端点性能**（[PR #185](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/185)，感谢 [@aodianjun](https://github.com/aodianjun)）：内存缓存消除重复 stat，解决万级日志时面板与时序图加载慢的痛点；
- **修复上游 live 目录只声明默认思考时丢掉可选档位**（[PR #177](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/177)，感谢 [@LeoK77S](https://github.com/LeoK77S)，issue #170）；
- **账号工具栏新增「一键刷新全部凭证」**（[PR #179](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/179)，感谢 [@LeoK77S](https://github.com/LeoK77S)，issue #167）；
- **数据指标看板「积分扣减历史」表头吸顶与账号昵称显示**（[PR #186](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/186)，感谢 [@LeoK77S](https://github.com/LeoK77S)）；
- **测试基础设施全面升级**（[PR #181](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/181) ~ [PR #184](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/184)，感谢 [@teddyli18000](https://github.com/teddyli18000)，issue #151）：统一抽取严格标准的 `tests/_dom_stub.js`，支持 `--jobs 4` 多进程安全并发跑测试，测试耗时从 2 分钟缩短至 27 秒；
- **看板 UI 全面优化**：彻底清理侧栏网格空隙恢复原生全宽布局，顶部卡片精简并突出账号可用对比。


### v1.6.16

重大稳定性与观测治理版本：涵盖账号熔断降权、工具调用防拆分修复、时序图表、全页面导航及多项深度优化：

- **上游工具调用配对修复**（[PR #153](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/153)，感谢 [@Cekxri](https://github.com/Cekxri)）：自动合并被部分客户端拆散的连续 assistant tool_calls 批次并丢弃截断参数，根治 DeepSeek 报 400 失败；
- **账号级软限流指数退避、熔断与降权治理**（[PR #163](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/163)，感谢 [@Cekxri](https://github.com/Cekxri)）：账号连续失败时自动指数退避，连续硬错误熔断，有效保护账号不被频繁失败打挂；
- **402 余额不足账号精准冷却至次日 04:00**（[PR #157](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/157)，感谢 [@Cekxri](https://github.com/Cekxri)）：余额用尽账号避免频繁重试，支持余额恢复后实时提前解冻；
- **面板新增 Token 时序图与积分扣减历史**（[PR #161](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/161)，感谢 [@Cekxri](https://github.com/Cekxri)）：新增 `/usage/timeseries` 时序聚合接口与看板可视化走势图；
- **侧栏区块导航推广至所有主页面**（[PR #169](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/169)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：通用化侧边栏组件，网关运维与数据指标页均支持左侧吸顶导航与滚动高亮；
- **系统提示词模式注入与 403 重试**（[PR #160](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/160)，感谢 [@Cekxri](https://github.com/Cekxri)）：支持 passthrough/custom/append 三种系统提示词模式；
- **缓存命中别名归一化**（[PR #164](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/164)，感谢 [@Cekxri](https://github.com/Cekxri)）：消除别名遮蔽，客户端始终读取统一的真实缓存命中数；
- **错误信封新增 gateway_hint 归因解释**（[PR #154](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/154)，感谢 [@Cekxri](https://github.com/Cekxri)）；
- **面板一键同步账号昵称**（[PR #158](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/158)，感谢 [@Cekxri](https://github.com/Cekxri)）；
- **会话亲和历史长度上限与号池弹性并发**（[PR #152](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/152)，感谢 [@ddddd-ren](https://github.com/ddddd-ren)）；
- **四级模型上下文/输出查找链与输出上限探针**（[PR #165](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/165)、[PR #166](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/166)，感谢 [@Cekxri](https://github.com/Cekxri)）；
- **看板 UI 深度打磨**：最近请求表格表头与数据全列居中对齐、模型与推理强度拆分为独立列、KPI 卡片双币种优雅对齐。


### 未发布

两项与「大请求 + 号池规模」相关的可调限制，默认行为不变：

- **会话亲和加长度上限（`WB_AFFINITY_MAX_MSGS`，默认 400）**：前缀亲和把整段对话钉在同一个账号上以吃满上游的账号级 prompt cache，但对话上下文是单调增长的，于是那个账号要反复接收越来越大的请求体。实测某生产实例（wk4，333 个请求）请求体与上游断连率的关系：

  | 消息条数 | 请求数 | 断连率 |
  |---|---|---|
  | < 150 | 82 | 0.0% |
  | 150–300 | 59 | 3.4% |
  | 300–400 | 64 | 7.8% |
  | 400–500 | 50 | 10.0% |

  断连（`TimeoutError` / `RemoteDisconnected`）触发重试，把 8.8s 的请求拖到 11.6s，首字延迟随之翻倍。超过上限的对话不再绑定账号，重新参与轮询：代价是丢掉前缀缓存，收益是断连与重试消失。设 `0` 关闭该上限，恢复原有行为。阈值不宜调低——同一实例 94% 的请求靠亲和拿到 98.5% 的缓存命中率。

- **聊天并发上限可按号池规模自动取值（`WB_MAX_CONCURRENT_CHAT=auto`）**：原先是固定 32，与号池里有几个账号无关，5 个账号和 200 个账号的部署共用同一个值。设为 `auto` 后取「就绪账号数」，且不低于 32。仅扩容、不缩容：已在飞行的请求持有旧信号量的许可，缩容会让归还次数超过上限并触发 `BoundedSemaphore` 的 `ValueError`。默认仍是固定值 32，行为不变。

- 新增 `tests/_test_affinity_length_cap.py`（13 项）：钉住阈值边界（`msgs == cap` 仍绑定、`cap + 1` 释放）、`0` 关闭上限、长对话的键稳定性、不同对话不碰撞、`None` / 空列表安全，以及并发上限的按池取值、下限回落、只增不减、固定值下为空操作、脏输入忽略与扩容后的许可计数。

- **修复 `tests/run_all.py` 在非 UTF-8 控制台下崩溃**（Windows CI 长期红灯的根因）：各套件本身以 `PYTHONIOENCODING=utf-8` 运行、输出也按 utf-8 从日志读回，但 `run_all.py` **自己**再打印这行摘要时用的是控制台编码。Windows runner 的 stdout 是 cp1252，于是第一条含中文的摘要就抛 `UnicodeEncodeError` —— 而这时所有套件其实**已经全部通过**，是汇总环节把整轮判成了失败。main 上连续多个版本（含 v1.6.15 自身）的 Windows job 都是这么挂的。现在启动时把本进程的 stdout/stderr 重设为 utf-8，并以 `errors="replace"` 兜底（生僻码位退化成 `?` 而不是终止整轮）。新增 `tests/_test_run_all_encoding.py`（3 项）：分别在 cp1252 与 utf-8 下跑一个含中文摘要的套件，断言退出码为 0、输出里没有 `UnicodeEncodeError`，并确认摘要确实来自被选中的那个套件。

- **一键刷新凭证**：账号工具栏新增批量按钮，等价于对池中每个账号点一次「刷新凭证」——后端 `/accounts/refresh` 不带 `uid` 时本就刷新整池，但看板上一直没有入口，`refreshAccounts()` 是没人调用的死代码（issue #167）。按钮在飞行期间禁用并显示「刷新中...」，结束后按成功数回报（全部成功为绿色，有失败则降级为黄色，并附上首个错误与失败条数），随后重画账号卡片让新凭证立刻可见。新增 `tests/_test_refresh_all_credentials.js`（10 项）：只发一次不带 `uid` 的请求、成功 / 部分失败 / 网络异常三档回报与配色、缺失 `error` 时兜底、刷新后必重载列表、按钮禁用与复位、按钮与英文词条确实在页面上。

### v1.6.15

里程碑版本：正式支持原生 Anthropic Messages 协议、完善企业版积分查询，以及多项重要修复与移动端体验优化：

- **原生 Anthropic Messages 协议支持 (`/v1/messages`)**（[PR #147](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/147)，感谢 [@Cekxri](https://github.com/Cekxri)）：原生提供 `POST /v1/messages`（流式 / 非流式）与 `POST /v1/messages/count_tokens`，鉴权支持 `x-api-key` 与 `Authorization: Bearer`，支持完整的 Anthropic 原生 SSE 事件序列与双向工具调用映射，现可无缝接入 Claude Code、Cursor 等全套 Anthropic 客户端生态；
- **修复设置页加载异常**（[PR #141](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/141)，issue #138）：修复 `loadSettings()` 遗漏 `pricingOn` 变量引发 ReferenceError 导致 API Key 列表与底部设置项无法加载的问题；
- **企业版账号积分显示与护栏修复**（[PR #149](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/149)，感谢 [@johnsken-jerry](https://github.com/johnsken-jerry)）：适配企业空间计费接口，彻底解决企业账号积分查回为 0/0 以及误触保留积分拦截的问题；
- **上游 SSE 超时保护与流式容错**（[PR #148](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/148)，感谢 [@Cekxri](https://github.com/Cekxri)）：增加上游 header/idle 读超时配置，防止流式挂起与死锁；
- **移动端中英文切换优化**（issue #150）：中英双胶囊按钮重构为紧凑单按钮一键切换（中 ⇄ EN），与主题图标按钮完全对齐，彻底解决小屏下顶部 UI 挤压变形；
- **修复多模态孤立函数输出报错**（[PR #145](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/145)，感谢 [@yorushikasama](https://github.com/yorushikasama)）：修复 Codex 等客户端在 `/v1/responses` 传递带图片的结构化输出时的 AttributeError 崩溃；
- **防止陈旧 429 报错跨重启复活**（[PR #144](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/144)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：重启时自动清理过期的 `cooldownUntil`，消除历史冷却误报；
- **模型用量占比基准校准**（[PR #140](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/140)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：表格百分比分母改为全体模型总 Token，避免第一名失真显示 100%；
- **价估算胶囊开关体验优化**（[PR #142](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/142)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：开关改为即点即存交互并补齐英文翻译词条；
- **测试环境 DOM 桩补全**（[PR #139](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/139)）。


### v1.6.14

重磅功能与体验升级版本，涵盖限额护栏统一矩阵、看板双语切换、设置项侧栏直达、估算开关以及多处界面优化：

- **限额护栏统一配置表与国际/国内版独立阈值**（[PR #130](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/130)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：将「保留积分」、「每日 Token 限额」、「每日积分限额」、「按模型每日 Token 限额」合并为统一的矩阵配置表；支持针对国际版与国内版分别指定不同的限额阈值（留空自动继承全局，升级自动兼容无损迁移旧配置）；
- **看板新增 CN/EN 中英双语切换与完整翻译**（[PR #134](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/134)，感谢 [@many1337](https://github.com/many1337)）：看板右上角支持一键切换简体中文与 English，内置全量前端英文化翻译字典并持久化记忆；
- **设置页动态左侧锚点导航栏**（[PR #129](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/129)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：依据页面区块动态渲染左侧吸顶/浮动侧边栏，支持滚动高亮与点击直达，大幅改善多设置项下的查找体验；
- **账号错误悬停查看完整响应与当前禁用总览**（[PR #132](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/132)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：账号卡片支持悬停查看上游完整报错（429 恢复时刻一眼可见）；新增「当前禁用账号与模型」总览表，集中感知限流与停用状态；
- **增加 OpenRouter 价估算总开关**（[PR #133](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/133)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：为估价模块补齐总开关（默认开启），关闭后彻底停用后台抓取与逐行折算开销，提升大日志量下的处理性能；
- **清理设置页合并冲突残留标记**（[PR #131](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/131)，issue #137）。
- **原生 Anthropic Messages 协议（2026-10-07）**：`/v1/messages` 与 `/v1/messages/count_tokens` 全原生实现（流式事件序列、`x-api-key` 鉴权、Anthropic 错误信封、内容块与工具双向映射），Claude Code / Anthropic SDK 可直连；服务端工具、thinking 回放与 `top_k` / `cache_control` 的取舍见「四、客户端配置与接入」。


### v1.6.13

- **修复看板右上角颜色主题菜单按钮无法打开**（[PR #127](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/127)，感谢 [@LeoK77S](https://github.com/LeoK77S)）：修正 IIFE 作用域中 `toggleThemeMenu` 与 `selectTheme` 的全局导出时机，修复点击按钮报 `ReferenceError` 导致下拉菜单无法弹出的问题，现可正常手动选择「浅色 / 深色 / 跟随系统」；新增 `tests/_test_dashboard_theme.js` DOM 级可达性与交互回归测试；
- **Docker 一键安装脚本补充国内网络加速与权限说明**（issue #126）：README 补充国内网络环境下通过 GitHub 代理加速拉取命令与 NAS 非 root 账户下的 `sudo bash` 说明。

### v1.6.12

- **Docker 部署与更新生态全面升级**（PR #125）：
  - **一键部署与更新脚本 (`quick-deploy.sh`)**：终端仅需执行一行命令 `curl -fsSL https://raw.githubusercontent.com/ardeyouxipianyi/workbuddy2api-hub/main/quick-deploy.sh | bash`。首次运行自动检测环境并拉取启动；后续再次执行同一命令即可完成自动平滑升级，账号配置与历史用量绝不丢失；
  - **NAS / 面板单文件 Compose 模板（免源码克隆）**：官方 `docker-compose.yml` 剔除 `build: .` 依赖，飞牛 fnOS、群晖、1Panel 等用户无需 `git clone`，直接复制粘贴 YAML 即可建站并支持面板一键更新；开发者本地构建单独拆分为 `docker-compose.build.yml`；
  - **支持双镜像仓库推送（GHCR + Docker Hub）**：工作流新增对 Docker Hub（`ardeyouxipianyi/workbuddy2api-hub`）的自动同步推送，消除前缀缺省报错困扰，兼顾国内 Docker 镜像加速器拉取；
  - **Watchtower 全自动静默更新**：提供开箱即用的 Watchtower 配置与命令，支持后台无感自动升级。


### v1.6.11

- **修复 Codex Responses 缺省 max_output_tokens 导致 32k 截断**（issue #121）：当客户端未显式传入输出上限时，网关自动根据模型目录中宣告的 `maxOutputTokens`（如 `deepseek-v4.1-flash` 为 128,000）进行兜底补全，避免长推理因触发上游默认 32k 限额而中断无正文。
- **修复面板新增 API Key 时已有 Key 模型限制被清空**（issue #92）：补齐 `/settings` 接口返回的 API Key 列表中的 `models` 字段，防止前端重新打包保存时将未带限制的数组传回导致误清空。

- **新增「每日积分限额」：账号当日积分花超后只服务免费模型**（默认 `0` 关闭，面板可设阈值）：账号当日消费的积分（按上游 `credit` 累计）达到阈值后，需要花费积分的模型自动切到其他账号，目录中标记为 `x0.00` 的免费模型照常服务——例如 `gpt-6-astra` 花满 50 积分后，免费期的 `deepseek-v4.1-flash` 不受影响。免费/付费判定以**各出口自己的模型目录**为准（同一 id 在不同出口可以一个免费一个收费），未知模型按付费处理（保守）。本地时间 0 点自动解封；单账号独立计数。账号行显示「积分限额」徽章，池子卡片显示「N 个达积分限额」，全部账号达额时返回 `429`（文案说明免费模型仍可用）。
- **新增「按模型每日 Token 限额」**（默认 `0` 不限）：账号在单个模型上当日消耗的 token 达到阈值后，只把**该模型**切到其他账号，同一账号的其他模型不受影响——例如 `hy4-preview` 用满 2 亿后该模型被跳过，`deepseek-v4.1-flash` 仍可用。账号行显示 `模型 · N tok 达限` 标记；本地时间 0 点自动解封；单账号独立计数。
- 两个限额与现有「每日 Token 限额」共用同一份增量扫描（`daily_usage_stats`），请求热路径开销不变；新增 `tests/_test_daily_credit_limit.py`（10 项），整套增至 30 个套件（25 个 Python + 5 个 JS）全绿。
- **新增「OpenRouter 价估算（等价 token 花费）」**：把请求 token 按 OpenRouter 公布的模型价折算成等价金额，与账号实际扣除的积分并列展示。定价快照内嵌在 `wb_pricing.py`（单一来源：OpenRouter 目录，美元，按快照汇率折算；大多数模型一个价，按条件定价的模型（输入长度阈值或 UTC 时段）按每条请求取档），`_fetch_pricing.py` 可随时刷新（支持 `--embed` 回写内嵌、`--dry-run` 只打印，`--extra-ids-file` 额外覆盖一批名字），并按「面板手填覆盖 → 人工覆盖表 → 名字归一化全等 → 变体后缀继承」依次为模型取价。计价含缓存命中/未命中分档。看板显示位：数据指标看板 KPI 卡片、账号透视表最后一列、模型用量表最后一列（含合计）、网关页卡片、最近请求最后一列；**人民币/美元一键切换**，无定价模型显示 `—` 并计入「未覆盖」。
- **定价按策略留档、定时自动刷新**：网关每隔一段时间（面板「设置 → 定价刷新」，默认 **5 分钟**，单位即分钟，填 0 关闭）去 OpenRouter 取一次价，按**内容**存成一条条独立的定价策略（同一模型同一份价格只存一条，A → B → A 只占两条），并用一条时间轴声明每个模型当前生效的是哪一条。`usage.jsonl` 每条请求记下它**引用了哪条策略**，计价按引用查——之后上游调价不会改写昨天已经算出的数字；当时还没有价的模型用之后第一次取到的价补算并标 `*`。没有任何请求引用、又已经不作数的策略会在抓取后清掉（每个模型至少留一条，刚取到的那批不动）。所有汇总都是把逐条估算相加，不拿汇总 token 乘单价重算。取价逻辑一并从 `_fetch_pricing.py` 移进 `wb_pricing.py`（Docker 镜像只 COPY `wb_*.py`，运行时取不到那个脚本），后者只负责生成出厂快照。
- **取价间隔改为分钟计（默认 5 分钟），旧的小时配置自动折算**：此前该设置按小时计、存在 `pricing_refresh_hours`；现在统一为分钟并存 `pricing_refresh_minutes`，`settings.json` 里遗留的小时值在升级后第一次读取时按 ×60 折算写回新键、旧键删除（只迁移一次），所以「6 小时」不会变成「6 分钟」。0 仍表示关闭自动刷新，「立即取价」不受影响。
- **上游新增模型无需改代码即可自动取价**：取价的候选清单从「只读 `wb_catalog.py`」改为 **静态目录 ∪ 网关实时目录里新增的模型**（intl 与 cn 两个区域各自的实时目录都会并进来，走 `/v1/models` 同一套过滤；某个区域取不到时该区域回落静态目录，一次抓取失败不会让覆盖变少）。两次取价之间新模型就被调用时，第一笔请求也会带价：`wb_pricing.ensure_policy()` 用最近一次抓取留在内存的目录按需登记策略，**请求路径零网络 I/O**，登记在 `RLock` 内完成、并发重复调用也只写一条，新登记会打一条 `[定价]` 日志。匹配链新增**变体后缀继承**（`VARIANT_SUFFIXES`：剥掉 `-lkeap` / `-taiji` / `-volc` / `-sg` 等渠道后缀，拿基名重走解析链，仍要求唯一命中），继承来的策略记 `via=variant` 与 `inherited_from` 供面板审计；设置页新增「变体后缀继承」开关（默认开，关掉即恢复只有覆盖表与同名匹配才定价）。`-f` / `-dev` / `-x` 不剥——它们是 hub 自己的档位，单价可能不同。匹配始终「宁可漏也不错」，多轮未命中的不写价。
- **未定价模型可见化，并可在面板手填 OpenRouter id 收口**：`GET /pricing` 新增未定价清单，每条带分类（`alias` 虚拟别名，不计入缺口 / `or_missing` OpenRouter 无对应 / `variant_unmatched` 剥后缀后仍无唯一基准）与相似度 top 3 候选（**仅建议，绝不自动采用**）；面板「设置 → 定价刷新」下新增未定价区域，可为某条模型直接填 OpenRouter id「登记」，映射写入数据目录的 `pricing-overrides.json`（运行期覆盖，不改源码 `OVERRIDES`，升级镜像不丢），提交后立即触发一次取价；留空提交即删除映射。新增 `POST /pricing/mapping`。
- **修好「立即取价」按钮的 404**（顺带）：`POST /pricing/refresh` 此前从未注册进 `do_POST`（`is_account_route` 不覆盖 `/pricing`），面板点「立即取价」实际收到 404；现在与 `/pricing/mapping` 一起走面板会话鉴权的新分支。新增文本级回归测试钉住这两条路由必须在 `do_POST` 里出现。
- 新增 `tests/_test_pricing_auto.py`（40 项）：并集输入、按需补价（含并发幂等与写路径计价）、变体后缀继承与否决项（`kimi-k2-instruct-taiji`、`kimi-k2.8-preview`、5 个别名保持未定价）、缺口分类与候选、面板映射端点与开关。整套增至 32 个套件（27 Python + 5 JS），全绿。
- **悬停即可看清一条请求的价是怎么来的**：最近请求最后一列的金额加了自绘气泡，给出三档原始单价（缓存命中/未命中输入、输出，USD 每百万 token）、汇率与折算说明、匹配来源的证据链（`direct` / `override` / `variant`，`variant` 还会写出基准名与剥掉的后缀）、命中的条件档位与该档单价、策略 id 与首次取到时刻、补算标记；没有定价的行仍只说「暂无定价数据」，不编 0。`/usage/recent` 每行直接带上 `cost_rates` / `cost_unit` / `cost_currency` / `cost_usd_cny` / `cost_or_id` / `cost_via` / `cost_inherited_from` / `cost_override_from` / `cost_band_note` / `cost_via_derived`，不为展示再开接口。**没有动计价口径**：`policy_id` 的算法一字未改，全量 15176 行逐行 `source` 与改动前 0 条失配，历史策略 id 逐条不变，已固化成测试。早于 `via` 字段写下的策略行按当前映射表推断并标注是推断（`via_derived=true`），指不到就不认。新增 `tests/_test_pricing_tooltip.py` 与 `tests/_test_pricing_tooltip.js`（夹具取自 2026-10-02 的线上现场），整套增至 34 个套件（28 Python + 6 JS），全绿。

- **「扫描桌面客户端账号」重新可用：桌面端加密凭据现在能在网关里直接解密**（入口此前因加密改造被隐藏）：桌面客户端从 2026-09-24 起把 `accessToken` / `refreshToken`（国内版还连带 `nickname` / `phoneNumber`）改成 `$wbEncrypted` 信封存储，扫描只能读到信封文本，导入后聊天、刷新凭证、查积分一律 401，当时只能把入口摘掉、让用户改走 OAuth。现在按客户端 `packages/at-rest-crypto` 的同一套方案就地解密（`key = sha256(atRestSecretKey)`、`keyId = sha256(key)[:16]`、AAD 为 `WB-AAD\0` + 版本 + `LP(WBEF1/WBEV1)` + `LP("sym-v1")` + `u32(suite)` + `LP(keyId)` + 帧代码 + 两个 0），入口放回来了。
  - 解码密钥只存在于客户端原生模块的运行内存里、磁盘上没有明文，所以网关从**正在运行的** `WorkBuddy.exe` 主进程内存里把它找回来（`OpenProcess(PROCESS_VM_READ)` + `VirtualQueryEx` + `ReadProcessMemory`，全程只读，不向目标进程写任何东西）；找到后用 keyblob 的 `protectorKeyId` 与一次 GCM 解封双重校验，校验不过就当没找到。密钥只留在网关进程内存中，不落盘、不进日志，网关重启后重新回收一次。
  - 内存回收不再逐字节哈希。三档扫描、命中即止：先按 `atRestSecretKey` 字段名和孤立的 44 字符规范 base64 捞出密钥载荷直接推导（正则走 C 层，约 460 MB/s），不中再按 8 字节栅格逐窗口哈希，最后才逐字节兜底；内存段按 64 MB 切片后均分给多个扫描子进程，任意一个命中其余立刻收工。对比上游那版逐字节脚本（单进程 1.36 MB/s、12 进程 16 MB/s），实测 462 MB 的客户端内存 **0.8 秒**拿到密钥。
  - 新模块 `wb_atrest.py` 只用标准库（自带 AES-256-GCM 与 GF(2^128) 实现，不引入任何 pip 依赖，绿色包内置的 Python 直接能跑）；并行用的是 `sys.executable` 拉子进程，而不是 `multiprocessing`——绿色包那份精简 Python 里根本没有这个模块，用它会直接报错。
  - 实测完整链路（Windows + 真实客户端）：两个 `.info`（国内版 / 国际版）的 token 与昵称都正常解出并导入成功；导入后的国内版账号 `/accounts/test` 直接拿到模型回复，国际版账号的凭证查询接口返回真实积分（顺带确认导入的是可直接使用的那串 token，不是信封）。
- **修掉区域判定的两处旧账**（手动导入 JSON 时「明明是国内版却进了国际版」就是这么来的）：`detect_realm_from_token()` 只认 `copilot.tencent.com` 与 `codebuddy.cn`，而国内版后来把出口换成了 `workbuddy.cn`（新版国内客户端的 JWT issuer 就是 `https://www.workbuddy.cn/…`），这类国内账号一律被判成国际版；JSON 里没有 `realm` 字段就会中招，而且一旦存错，导出再导入还会把这个错误一路带着。现在：
  - 三个国内出口（`copilot.tencent.com` / `codebuddy.cn` / `workbuddy.cn`）都认，国际版认 `workbuddy.ai` / `codebuddy.ai`，两边都看不出时不再假装知道（`realm_evidence()` 返回空，由调用方决定怎么兜底）；
  - 区域判定以 **token 自己的 issuer** 为准，域名只作兜底——同一台机器切区登录过时，`.info` 里的 `domain` 字段可能还是另一边的，不能让它盖过 token；
  - 桌面凭据的文件名（`workbuddy-desktop.info` = 国内、`-ai.info` = 国际）退为提示：同一个文件里登录另一区域账号时按 token 归位；扫描列表和导入用的是同一套判断，不会再出现「列表里写着国内版、导入却跑进国际版」；
  - `X-Domain` 头跟着最终区域走，不会拿着上一边的域名去请求另一边的出口；
  - 新增 `tests/_test_desktop_realm.py`（19 项）：三个国内出口 × 域名/issuer 组合、过期的 `realm` 字段、显式 `realm` 覆盖、导出再导入不漂移。
- 看板：工具栏入口放回；扫描结果新增「已加密 / 待解码」状态，遇到加密凭据会提示先点「回收密钥」（后端在同一接口上新增 `{"recoverKey": true}` / `{"forgetKey": true}` 两个动作，沿用面板鉴权），拿不到密钥时（客户端没开、非 Windows、权限不足）直接把原因显示出来，并引导回 OAuth。
  - 新增 `tests/_test_desktop_atrest.py`（26 项：FIPS-197 的 AES-256 分组向量、信封往返 / 篡改 / 错钥 / 帧隔离、keyblob 自检、路径限制，以及拉起一个靶子进程真跑一遍内存回收、确认密钥不落盘），整套 31 个测试文件全绿。

- **新增：积分与套餐权益包全维度明细查看与到期管理**：
  - 参考 CodeBuddy 官方直连计费接口（`/billing/meter/get-user-resource-summary`、`get-user-resource-free-packages`、`get-user-resource-paid-packages` 与 `checkin-activity-status`），实现各账号积分与权益包的秒级同步与完整解析；
  - **全维度信息透出**：解析各套餐包名称、子产品名称、发放来源/原因（如官方活动发放、裂变拉新、月度赠送等）、资源 ID、订单号、生效时间与精确到秒的到期时间、总容量、已用及剩余可用积分；
  - **到期倒计时与临期提醒**：自动按当前时间计算剩余天数，区分「已过期」、「≤3天即将到期」、「≤7天到期提醒」及「长期有效」；账号池主表实时感知临期状态并在「积分」列透出警示徽章，弹窗内设「最近将过期」概览卡片；
  - **交互体验与筛选排序**：看板支持 Tab 快速筛选（全部 / 有剩余 / 即将到期 / 已用完过期）、多字段模糊搜索（名称/代码/来源）以及四档动态排序（最快到期优先、剩余额度最大、已用最多、总容量最大），并支持一键实时向上游刷新；「积分」列精简为单入口（点击 `[明细]` / `[查询]` 徽章唤起窗口）。
- **新增：看板明/暗主题切换（浅色 / 深色 / 跟随系统）**：
  - 顶部右侧新增主题切换按钮，下拉可选「浅色」「深色」「跟随系统」三档，图标随当前偏好变化（太阳 / 月亮 / 显示器）；
  - 全看板配色改为 CSS 变量驱动，深色主题（`[data-theme="dark"]`）覆盖背景、面板、边框、文字、徽章、模态遮罩等全套组件，`color-scheme` 同步切换；
  - 偏好持久化到 `localStorage`（`wb-theme`），刷新与重开看板保持；内联脚本在 `<body>` 解析前即设定主题，避免首屏白闪；
  - 「跟随系统」实时监听 `prefers-color-scheme` 变化，系统切换深浅色时看板即时跟随；移动端同步适配主题按钮尺寸。

### v1.6.10

- **修复停用账号会丢掉出口绑定**（issue #89，感谢 [@lkxlzx](https://github.com/lkxlzx)）：此前停用账号时会顺手把它的 `proxySlot` 清空（`set_all_enabled` 与启动时的迁移也一样），重新启用不会恢复，那条账号就回落到直连——报告人说的「启用禁用账号后代理出口会被重置为直连」正是这个。现在绑定是操作者的选择，停用/启用不再动它：停用只是不接单，重新启用仍走原来的出口。
  - 槽位卡片的「已绑定」计数依旧只统计**启用中**的账号（表示这条出口当前有谁在用）；要真正解绑就显式选「直连」，或把槽位删掉（删槽位仍会把绑在它上面的账号解绑）。
  - `tests/_test_proxy_slots.py` 与 `tests/_test_proxy_slot_lifecycle.py` 里那几条「停用即释放」的断言改成钉住新行为：停用后绑定仍在、运行时出口不变、重新启用仍走同一槽位。

### v1.6.9

- **修好网页通道打卡：会话会被真正驱动到完成**（issue #90，感谢 [@Saracino34](https://github.com/Saracino34) 的准确定位；issue #75）：v1.6.4 只建了会话，而建会话只是**排队**——agent 要等客户端接上这条会话的沙箱并请求这一轮才会跑，所以网关建的那些会话全部停在 `CREATING`、没有任何输出，第二天自然不加积分（报告人 4/4 复现：手动发的会话十几秒 `completed`，网关建的一条都没动过）。现在按网页端的顺序走完：建会话 → `GET /console/as/conversations/{id}/session` 取沙箱 `link` + `token` → ACP（JSON-RPC over HTTP，服务端事件走 SSE）`initialize` → `session/load` → `session/prompt` → 轮询到 `completed`。实现放在新的 `wb_webagent.py`，只用标准库。
  - 打卡结果里带上会话状态与输出段数（如「网页通道 completed：12 段输出，15420 ms」），跑没跑成一眼可见，不用等第二天看积分；失败时错误里带会话 id。
  - 一轮最多等 120 秒（`WB_WEB_TURN_TIMEOUT` 可调）；实测一条「Hi」18.6 秒跑完、12 段输出。
  - 顺带更正 v1.6.4 的一条判断：`GET /v2/activity/banner` 返回的 `{"code":12302,"msg":"activity is offline"}` 只是 banner 模块自己的状态，不能当作「活动停发」的证据。
- **本地网络工具（`web_search` / `web_fetch`）改成默认关闭的看板开关**（[PR #87](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/87)，感谢 [@Cekxri](https://github.com/Cekxri)）：默认「直通」——工具声明原样透传，客户端自己声明的搜索工具照常拿到调用（v1.5.3 之后的既有行为，升级不受影响）；要在看板「设置 → 本地网络工具」打开，网关才会把声明换成自己的同名函数、在本地执行并喂回模型。关闭时连同名调用的拦截也一并关掉，客户端自己的 `web_search` 不会被吞。
- 新增 `tests/_test_web_agent.py`（6 项，钉住驱动顺序与结果上报）；`tests/_test_daily_chat.py` 扩到 10 项、`tests/_test_local_web_tools.py` 扩到 68 项；整套 29 个测试文件全绿。

### v1.6.8

- **模型列表改为跟随上游 `GET /v3/config` 的实时清单**（issue #85，感谢 [@Jay-Young](https://github.com/Jay-Young)）：此前只认桌面端缓存文件与内置快照，没装桌面端的机器（Docker / NAS / Linux 服务器）拿不到桌面端 picker 的那份列表。现在 `/v1/models` 直接向出口要 `agents[cli].models`——与桌面端同一份清单，缓存文件退为回落。
  - 过滤规则：去掉 5 个档位别名（`default-model`、`fast-model`、`balanced-model`、`primary-model`、`deep-model`）与国内版的 `auto` 路由项，去掉 `-sg` / `-x` 变体，同名的只留 0.00 倍率那一档（国际版留 `deepseek-v4.1-flash`、丢 `-sg`，留 `hy4-preview-f`、丢 `hy4-preview`）。
  - 上游新上的模型无需发版即可出现在 `/v1/models`（表外的新名字按上游顺序追加在末尾）；表顺序与国内版 `hy4-preview-f` 这类免费档的保留不变。
  - 回落顺序：远端 → 桌面端缓存文件 → 窄端点（仍走旧白名单）→ 内置快照；10 秒一次、最多两次（聊天桌面 UA 失败后换应用 UA）。
  - 顺带修掉一处隐性退化：缓存文件是同一份文档但没有 `data` 信封，旧解析只认 `data.agents`，会让缓存路径悄悄退回旧读取器（数量对、元数据丢）；现在两种形态都认，并优先取 `cli` 这个 agent。
- **国际版模型清单补上 `grok-4.7`**：16 → 17，看板国际版专属标记同步。
- 新增 `tests/_test_remote_catalog.py`（10 项）钉住解析、过滤规则、免费同级优先、免发版追加、缓存文件驱动与回落不泄漏窄端点未知名。

### v1.6.5
### v1.6.6
### v1.6.7

- **新增：按 API Key 限制可用模型**（issue #73 由 [PR #84](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/84) 实现，感谢 [@Cekxri](https://github.com/Cekxri)）：每个 Key 可以填一个模型白名单（如 `deepseek*`、`gpt-6-astra`，支持 `*` 通配、多个用逗号分隔），不在名单里的模型请求在网关本地直接返回可读的 400——不送上游、不消耗额度。留空 = 不限制，旧 `settings.json` 读回来一律不限制，升级无需迁移。主要用来挡客户端自己发的背景请求（标题生成、记忆整理、自动复核这类不经过模型选择器、直接按目录模型 ID 发出的调用）。面板 Key 编辑卡新增「模型限制」一栏，设了限制的 Key 会显示徽章。
  - 匹配用 `fnmatch`、大小写不敏感；`deepseek*` 同时覆盖 `deepseek-v4.1-flash` 这种裸 ID 和 `deepseek/deepseek-v4.1-flash` 这种带前缀的形态；精确名字不会连带命中后缀（`gpt-6-astra` 不含 `gpt-6-astra-high`，要连带就写 `gpt-6-astra*`）。
  - `/settings/save` 在提交的行省略该字段时保留已存的值，旧版缓存面板不会把限制洗掉；`/v1/chat/completions` 与 `/v1/responses` 两条路径都会拦。
- **修复 `BLOCK_BACKGROUND_REQUESTS` 误拦使用者的「压缩上下文」**（[PR #86](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/86)，感谢 [@Cekxri](https://github.com/Cekxri)）：该开关的关键字表里有 `compaction`，而使用者按「压缩上下文」时发出的请求 `request_kind` 同样是 `compaction`，于是开关一打开，按钮收到的是拒绝报文而不是摘要。现在按「这次压缩是谁发起的」区分：客户端自己发起的压缩带 `thread_source=memory_consolidation`（继续拦），使用者在自己线程上按的压缩放行；`auto_review` 这类即使跑在用户线程上也仍然拦。新增 `tests/_test_background_requests.py` 钉住区分规则。
- **新增 Docker 镜像发布工作流**（[PR #83](https://github.com/ardeyouxipianyi/workbuddy2api-hub/pull/83)，感谢 [@xihan123](https://github.com/xihan123)）：Release 发布后自动构建并推送 `linux/amd64` + `linux/arm64` 双架构镜像到 GHCR（`ghcr.io/ardeyouxipianyi/workbuddy2api-hub`，正式版同步打 `latest`），README 补了从 GHCR 拉取运行的说明（GHCR 新包默认私有，要免登录拉取需在 Packages 设置里改为 Public）。


- **新增「每日 Token 限额」：按账号当天用量提前停用、自动切号**（issue #82，感谢 [@RiggTIan](https://github.com/RiggTIan)、[@lkxlzx](https://github.com/lkxlzx)）：上游的免费额度是按 token 计窗口的（如 `deepseek-v4.1-flash` 约 2 亿 / 12 小时），打满后该账号当天只能等窗口重置——报告里「把用满的号停用后，另一个号也请求失败」，实际是上游把第二个号的大请求也判了限额（`code 6004`），而 1 条消息的小请求仍能通过，所以账号行「测试」显示正常、大请求却 429。现在看板「设置 → 每日 Token 限额」填一个数即可：账号当日消耗的 token 达到该值后暂停接单、请求自动切到其他账号，本地时间 0 点后自动恢复；**填 0 表示不限**（默认值）。
  - 计数取自 `usage.jsonl` 里该账号当天的 token 合计，与看板「今日消耗」同一口径（跳过客户端中断的行）；增量扫描 + 15 秒缓存，热路径只读新增的行。计数由日志折算，重启后停用状态依然有效。
  - 被停用的账号在账号行显示「日限额」徽章（悬停可看今日已用 / 上限），池子卡片显示「N 个达日限额」，控制台打印 `account xxx parked: daily token limit reached (...)`；所有账号都达额时请求返回 `429` + `Retry-After`（到本地 0 点），文案说明是本地限额，不碰上游。
  - 定时任务（签到、打卡、保活）不受影响，与「保留积分」一致：只是不接新单。两个限制各自独立、按「或」生效——账号要同时不触发两者才会接单（卡片说明里已写明）。
  - 新增 `tests/_test_daily_token_limit.py`：钉住「0 = 不限」「只有计数过的天才拦」「只统计今天、跳过客户端中断的行、按字节偏移增量折叠」「池子跳过被停账号并发布状态」；`_test_model_cooldowns.py` 的桩池补上了新的池方法。


- **修复代理槽编辑器被轮询刷掉**（issue #79，感谢 [@lkxlzx](https://github.com/lkxlzx)）：点「+ 添加槽位」后刚加的那一行撑不过 15 秒就消失——`loadAccounts()` 挂在 15 秒轮询上，而它会顺带刷新代理槽，刷新是「拉服务端列表 → 整体替换 → 重绘整张表」，那一行还没保存到服务端，于是被旧列表顶掉，正好是报告里说的「还没来得及填写内容就返回了」。（同一个机制也会把已有行的改动打回服务端版本，只是行还在、不容易察觉。）
  - 现在编辑器里有未保存改动时会跳过刷新，「代理槽」标题旁显示「（N 个 · 未保存）」，让「列表为什么不再自动刷新」是看得见的；保存成功后清零、轮询恢复——点「测试」时触发的那次自动保存同样会清零。
  - 新增 `tests/_test_slot_editor.js`：在假 DOM 下加一行、调用轮询用的 `loadProxySlots()`，断言工作副本没有被服务端列表替换；再断言保存之后会正常刷新。

### v1.6.4

- **国际版每日活跃打卡改走网页通道**（issue #75、issue #59）：两位报告人的实测一致——网关自动发出的桌面端身分对话拿不到每日 30 积分，而在网页版手动发一句就能拿到。顺着这条线索抓包后确认：网页版 app 的「对话」根本不是 `chat/completions`，而是 `/console/as/conversations/` 下的 agent 会话，创建会话时带上 prompt，后端就按该 prompt 起一次任务；而且这条链路只用 `Authorization: Bearer <accessToken>` 与 `X-User-Id` 两个凭据头（没有桌面端的 `X-IDE-*` 指纹），所以网关手里同一份账号凭据可以直接调用，不需要额外的网页登录——实测 GET 会话列表、POST batch-get 都返回业务响应而不是 401。
  - 现在国际版打卡是两步：先发一条桌面端身分的轻量对话（保持原行为），再在网页通道建一个带 prompt 的会话；返回结果里会带上会话 id，便于核对是否真的建上。
  - 账号栏新增 **「网页通道打卡 (国际版)」** 按钮：手动为所有已启用的国际版账号各建一个网页端会话，点击后会先弹一次确认（它会真的起任务、消耗少量积分）。这个按钮不写 `lastDailyChat`，所以不会让定时巡检跳过当天的正常打卡流程。
  - 「设置」页新增「国际版每日活跃打卡」开关（默认开启），关掉即回到只发桌面端对话的旧行为；取值同样严格限定 JSON 布尔，字符串一律 400 拒绝。
  - 需要留意：网页通道会真的起一次任务，会消耗该账号少量积分，换来的是每日 30/50 积分活跃奖励；面板上已写明这一点。
  - 另外记录一条上游状态：抓包期间 `GET /v2/activity/banner` 返回 `{"code":12302,"msg":"activity is offline"}`，即该活动模块当前处于下线状态。如果网页端也拿不到积分，原因可能在上游而不在通道——这条留待后续观察。

### v1.6.3

- **修复空状态「登录新账号 (OAuth)」按钮点击无反应**（issue #66，感谢 [@shis23](https://github.com/shis23) 的准确定位）：该按钮调用的是 `startLogin()`，而这个函数早在 v1.1.0 引入 `openLoginModal()` 时就已经不存在了，因此从 v1.1.0 起，账号池为空的首次部署用户点它不会有任何反应，浏览器控制台报 `startLogin is not defined`，而顶部工具栏的同名入口一直正常。现已改为调用真实存在的入口，并新增 `tests/_test_dashboard_handlers.js`：扫描 `dashboard.html` 中全部内联事件处理器，断言每一个都能找到对应的函数定义。这类「按钮绑定了一个不存在的函数」的问题只会在浏览器里、且只在该按钮被点击时暴露，任何服务端测试都看不见它。
- **看板时间范围扩展：本周 / 本月 / 自定义区间**（issue #68）：
  - 除「今日 / 全部历史」外，新增「本周」（周一零点起）、「本月」（1 号零点起）与「自定义」（起止时间自选，任一侧留空表示该侧不限）。口径与既有「今日」保持一致，都是本地零点锚定的自然区间；刻意不提供「最近 7 天 / 30 天」这类滚动别名，否则按钮标签在一周里有六天是错的。
  - `/usage`、`/usage/perf`、`/usage/analytics` 三个取数端点统一接受 `range` / `since` / `until` 参数，KPI 卡片、账号透视表与模型性能表会一起切到同一窗口，第一列的标题同步变为「本周消耗 Token」等，不会再出现「卡片显示今日、表格显示全部」的口径分裂。
  - 缓存键由原来的 today/all 二值改为真实窗口边界：本周与本月是重叠区间，二值键会让其中一个窗口的数字被另一个顶掉。
  - 模型性能表的延迟 / 速度列取自日志末尾的采样，窗口比采样更宽时会在表头注明覆盖起点，不再让局部数据冒充整个窗口。
- **修复出站身分切换后重启即丢失**（issue #76，感谢 [@1766266028](https://github.com/1766266028) 的完整定位与复现）：账号加载时把出站身分硬编码成默认的 WorkBuddy 桌面端，凭证文件里保存的值被读进一个全仓无人使用的字段（`saved_product`），于是面板上的 WB / VSC / CLI 切换（以及启用后的 429 自动切换）虽然确实写进了凭证文件，重启后却一律打回 WB——`set_product()` 的注释承诺「重启后仍然有效」，与实际行为矛盾。现在加载时读回凭证文件中的身分，非法值仍由 `normalize_product()` 回退到默认；同时面板切换在改完内存后立即落盘，不必再等 refresh / 签到 / 查积分之类的路径顺带保存——切完就重启容器的人不会再白白丢掉这次切换。新增 `tests/_test_product_persistence.py`（17 项断言）覆盖加载、别名归一、非法值回退、切换落盘与重载，以及身分最终落到端点与出站标头。

- **429 自动切换出站身分改为面板开关**（issue #67）：切换逻辑本身一直存在（WB / VSC / CLI 轮转、每轮最多 4 次、60 秒内算同一轮、成功即归零），但总开关是源码里的常量 `AUTO_SWITCH_PRODUCT = False`，面板上没有入口，想用只能改代码。现在改为「设置」页的开关，默认关闭（与改动前行为一致），保存后下一次请求即生效，不再需要动源码。取值严格限定为 JSON 布尔：字符串 `"false"` 之类一律 400 拒绝，否则一个真值字符串会把开关悄悄打开，而这正是关掉它的人最不希望发生的事。需要留意的是，开启后切换到的身分同样会随凭证文件持久化（见上一条），重启后不会自动回到 WB——面板上已写明这一点。

### v1.6.2

- **全套测试收拢与官方 CI 流水线建设**（PR #65，感谢 [@teddyli18000](https://github.com/teddyli18000)）：
  - 将散落在根目录的 20 个测试套件整齐规整至 `tests/` 目录下；
  - 新增统一测试运行器 `tests/run_all.py`，支持一键隔离运行全部 20 个测试套件或按关键词过滤；
  - 引入官方 GitHub Actions 自动化 CI 流水线（`.github/workflows/tests.yml`），每次提交与 PR 自动覆盖 Ubuntu（Python 3.9/3.12）与 Windows 跨平台测试矩阵。

### v1.6.1

- **修复 Docker 部署默认无鉴权开放代理漏洞**（PR #64，感谢 [@teddyli18000](https://github.com/teddyli18000)）：容器 CMD 默认追加 `--lan` 启动并移除写死的 `--port 8788`。无显式 `API_KEY` 时将自动生成高强度 Key 持久化保存并打印在日志中，拒绝匿名公网调用，消除未授权盗刷风险，同时支持通过 `PORT` 环境变量动态指定内部端口。
- **修复签到与活跃打卡后视图强制跳转**（PR #63，感谢 [@teddyli18000](https://github.com/teddyli18000)）：拆分 `refreshActiveRealm()` 与 `initRealm()`，国内签到和国际版每日活跃打卡完成后仅更新出口状态与用量，不再将当前浏览的区域视图强行跳回默认出口。

### v1.6.0

- **国际版每日活跃自动打卡领 30/50 积分**（issue #59）：官方国际站订阅规则规定「通过客户端发起有效对话可领每日活跃 30 积分（Pro 为 50 积分），网页端对话不计入」。现为国际版账号新增每日活跃自动化支持：
  - 后台调度器排程自动在 09:00 / 21:00 巡检时为当日未活跃的国际版账号发送一条轻量微型对话（默认走官方 `WB` 客户端出站标头与低消耗模型）；
  - 看板切换至国际版视图时，顶部工具栏提供「每日活跃打卡 (国际版)」一键触发按钮；
  - 严格记录 `lastDailyChat`，保证每个账号每天仅触发一次，不浪费额度。

### v1.5.9

- **修复 OmO / OpenCode 子代理 11128 WAF 拦截**（PR #62，感谢 [@Sakura1618](https://github.com/Sakura1618)，issue #61）：在 `deepseek-v4.1-flash` 上驱动 OmO 等多智能体调度框架时，上游 WAF 会对 `Sisyphus-Junior - Focused executor from OhMyOpenCode` 这一连续短语进行指纹特征匹配并拒流返回 `code: 11128 (Illegal API invocation from an unapproved channel)`。现于脱敏管线中针对性将该短语清洗为 `Sisyphus-Junior - Focused executor`（去掉末尾归属文本），既保留子代理业务身份与指令执行，又彻底消除拦截。

### v1.5.8

- **隐藏「扫描桌面客户端账号」入口**：桌面客户端自 2026-09-24 起把 `accessToken` / `refreshToken` 改成加密存储（`$wbEncrypted` 信封），扫描仍能读到文件，但拿不到可用的 token——导入后聊天、刷新凭证、查积分全部返回 401。入口已隐藏，请改用 OAuth 添加账号；相关代码（前端 `scanDesktop()` 与后端 `/accounts/import/desktop`）保留未删，等解密打通或改走其他凭据来源后再放出来。
- **两个按钮改名**：「一键自动分配出口」→「分配代理出口给未绑定账号」（它只给尚未绑定出口的已启用账号轮询分配，已有绑定的账号不动，原名容易被读成重新平衡全部账号；同时补了 tooltip 并修正两条 toast 的措辞）；账号行的「刷新」→「刷新凭证」（换的是该账号的登录凭证，不是页面、积分或账号列表）。
- **README 全面精简**：345 行压到 305 行、字符数减少约 23%，事实与贡献者记录一条未删；顺带修掉两处已失效的说法——头部特性里的「亦支持扫描本地客户端导入」，以及 Docker 那节整段的桌面凭据挂载说明。

### v1.5.7

- **`tool_choice="none"` 不再删除工具声明**（PR #57，感谢 [@zhangzm0](https://github.com/zhangzm0)，issue #56）：此前客户端发 `tool_choice="none"` 时，`normalize_tool_choice()` 会把 `tools` / `functions` 声明整个删掉。模型失去结构化工具通道后，把调用降级成 DSML／伪 JSON 文本塞进 `content`（`tool_calls` 为空、`finish_reason=stop`），Agent 客户端解析不到调用只能再追问一轮，模型重复一遍 —— 上下文每轮 +2 条消息、token 线性膨胀，直到撑爆窗口或用户手动断开。现在保留工具声明，由 `tool_choice` 字段自己表达「本轮不许调用」；上游只认字符串，对象形式仍降级成字符串（发对象会 11101）。实测上游并不真正遵守 `tool_choice="none"`，保留声明后它仍可能返回 `tool_calls`——这比让 Agent 原地空转好；确实需要禁止调用时，请由客户端不传 `tools`。

### v1.5.6

- **Docker 部署下的 Linux 桌面凭据挂载**（PR #55，感谢 [@LuFering](https://github.com/LuFering)）：新增 `docker-compose.override.yml.example`，以只读方式把宿主机 `~/.local/share/CodeBuddyExtension/Data/Public/auth` 挂进容器，补上 Linux + Docker 场景下看板扫描不到桌面凭据的说明；`.gitignore` 同时忽略本地 `docker-compose.override.yml`。
- **保留积分开关**（issue #44）：看板「设置」新增最低保留积分，账号余额低于该值时不再接单，避免余额被用尽后触发上游的提醒短信。填 `0` 关闭（默认）；从未查询过余额的账号不受影响；账号只是停止接单，仍在池中并继续定时任务，充值后自动恢复。阈值保存在 `accounts/settings.json` 的 `reserve_credits`，改动即时生效、无需重启。

### v1.5.5

- **出站身分改为三套模式**：账号行新增 `WB` / `VSC` / `CLI` 三档切换，默认 `WB`（WorkBuddy 独立桌面客户端，`X-IDE-Type: WorkBuddy`），另可切到官方 VSCode 插件（`VSCode`）或官方 CodeBuddy CLI（`CLI`），三者各自对应不同的出站指纹与端点。原先的两档实现把桌面端与插件端混为一谈，且默认走 CLI。
- **国际版 CLI 端点修正**：`www.codebuddy.ai` 在实测网络上无法解析（getaddrinfo 失败，系统解析器回 0.0.0.1 空路由），国际版 CLI 身分改走 `www.workbuddy.ai`，该域名接受 CLI 头并正常应答。此前国际版账号在默认身分下直接 502。
- **国际版模型列表对齐官方客户端**（issue #51）：现为 16 个，取自官方缓存 `agents[0]` 声明的真实模型（已排除 5 个档位别名与同名的 SG 区域变体）。补上 `glm-5.3-flash`（0.06x）与 `kimi-k2.8-preview`（0.77x），移除官方并未提供的 `hy4-preview` 与 `gpt-5.3-codex`。
- **`kimi-k2.8-preview` 解除国内独占限制**：此前被 `CN_EXCLUSIVE` 拦下并提示“请改用对应出口的 Key”，但官方国际版账号实测可正常调用（HTTP 200 且正常出内容），现已在两个区域同时开放。同类误判的 `glm-5.1`、`glm-5v-turbo`、`minimax-m3` 已实测可用但未动，留待后续处理。
- **国内版 `deepseek-v4.1-flash` 倍率修正**（issue #51）：看板此前对该模型写死显示「独家优惠 0.03x」，与实际上游计价的 0.11x 无关（官方国内版缓存中该模型没有任何促销折扣），现已改为直接沿用上报倍率。内置快照同步由 0.03 修正为 0.11。
- **`/health` 鉴权状态修正**（PR #52，感谢 [@teddyli18000](https://github.com/teddyli18000)）：`api_key_required` 此前只反映启动参数里的 Key，仅配了面板 Key 时会误报 `false`，与 `/v1` 实际拒绝无 Key 请求的行为矛盾。现改为复用手持路径的判定。
- **单模型限流可视化**（PR #50，感谢 [@teddyli18000](https://github.com/teddyli18000)）：`/accounts` 新增 `modelCooldowns`，看板账号行显示受限模型与本地恢复时间；429 状态改由独立短锁保护，避免看板读取与请求线程更新竞争。
- **国内账号昵称容错**：国内桌面端把昵称存成 `{"$wbEncrypted": ...}` 加密信封，此前会被 `str()` 成一整行字典画在账号行上；现在非字符串值一律回退显示 UID 前缀。

### v1.5.4

- **国内版目录补上 `hy4-preview-f`**：内置静态目录里只有旧 id `hy4-preview`（x0.29），它不在白名单里会被裁掉，而 `hy4-preview-f` 只能靠本机桌面端缓存补进来——没装过国内版桌面端的机器上该模型会消失。现按桌面端缓存补进静态目录（x0.00、1M 输入 / 64k 输出、推理档 high）。
- **看板显示积分消耗与账号昵称**（PR #45，感谢 [@Pro-XK](https://github.com/Pro-XK)）：最近请求表新增「积分」列，账号列改显示昵称（tooltip 保留完整 uid，账号不在池中时回退 uid 前缀）；「网关调用量」卡片副标题追加累计积分；账号透视表新增「消耗积分」列。
- **积分口径统一**：卡片与透视表此前一个只累计成功请求、一个含失败请求，同一页面上两个「消耗积分」永远对不上。现统一为「上游实际计费过的请求都计入，客户端取消不计」，并各自写明覆盖范围；credit 为 0 的行显示 `0.00` 而非 `—`。

### v1.5.3

- **移除网关内置的 `web_search` / `web_fetch` 代跑**（issue #43）：实测上游本来就没有服务端搜索能力（声明与不声明工具时模型反应一致、调用次数为 0），而代跑实现有参数名只认 `query`、工具重复下发、失败时发合成 `resp_wrapup` 把失败伪装成正常结束三处缺陷。现工具声明原样透传，客户端自己声明的搜索工具会正常拿到调用。

### v1.5.2

- **修复 Docker 镜像缺少运行时模块**（PR #41，感谢 [@wiggins-kong](https://github.com/wiggins-kong)）：Dockerfile 的显式 COPY 清单漏掉 v1.5.0 新增的 `wb_identity.py` 与 `wb_webtools.py`，容器启动即 `ModuleNotFoundError`。现改为 `COPY wb_*.py dashboard.html ./`。仅影响 Docker 部署，绿色包与本地运行不受影响。

### v1.5.1

- **看板时间范围与筛选修正**（issue #39）：「今日 / 全部历史」此前只影响部分指标卡，现首张卡跟随切换、第二张固定为累计并注明差异原因；模型性能表跟随所选范围（`/usage` 与 `/usage/perf` 新增 `range` 参数），并新增「账号」「模型」筛选，汇总行随筛选重算、失效筛选自动清除。
- **修复账号用量透视表丢失**：该表格标记曾被误删，`getElementById` 恒为 null，整个「各账号用量透视」区块从未渲染；现恢复并适配移动端卡片布局。
- **新增测试**：`_test_usage_range.py`（22 项断言）与 `_test_matrix_filters.js`（19 项断言）。

### v1.5.0

- **Codex App namespace 工具支持**（PR #33，感谢 [@Cekxri](https://github.com/Cekxri)）：展开 `namespace` 后转发，回程补上该字段；同时支持 `agent_message`（子代理）与无 `call_id` 的 `function_call_output`。
- **出站身分标头修正**（PR #33）：原 `X-Product: WorkBuddy` 为自创组合，官方为 `X-Product: SaaS`；账号行可按需切换 WB / VSC / CLI 三套身分。
- **本地 `web_search` / `web_fetch`**（PR #33）：客户端声明时由网关代跑（v1.5.3 已移除）。
- **DeepSeek 多轮 `reasoning_content` 回填补全**（PR #36，感谢 [@ayeaaaa](https://github.com/ayeaaaa)）：thinking 开启即回填，并把字段镜像到 `reasoning` 且保证非空；与 v1.4.9 的档位注入互补。
- **看板移动端布局**（PR #37，感谢 [@ayeaaaa](https://github.com/ayeaaaa)）：新增 `≤640px` 手机布局与 `≤400px` 微调，桌面布局不变。
- **API Key 行 id 唯一化**（PR #40，感谢 [@wiggins-kong](https://github.com/wiggins-kong)）：避免两行同 id 时 `/settings/reveal` 返回别人的 key；读取时也去重，历史文件自愈。
- **修复 `/v1/responses` 非流式路径崩溃**：该路径引用了未定义的 `ns_map`，任何非流式请求都会抛 `NameError` 断开连接；流式路径不受影响。

### v1.4.9

- **DeepSeek 思维链默认开启**：此前只注入 `thinking:{type:"enabled"}` 而不带推理档位，上游仍按「不思考」应答。现缺档时按模型目录声明的默认档补齐（无声明回退 `high`）；客户端显式档位不覆盖，`thinking:{type:"disabled"}` 与 `reasoning_effort:"none"` 照常退出。
- **工具调用配对自愈**：客户端写不回工具结果时，坏历史被每轮重放、上游对之后每条消息返回 `400 code 11148`，一次失败调用即可报废整条会话；并行调用间插入的消息（如 Codex 的 `image_resize_notice`）同样打断配对。现出站前把结果块移回所属批次，并按同一份 id 集合对称裁剪孤儿。
- **`prompt_cache_key` 注入（默认关闭）**：按账号隔离的缓存键（`wb2a-<uid8>-<摘要>`），用 `WB_PROMPT_CACHE_KEY=1` 开启。默认关闭是因为实测该上游本就会复用重复前缀，带不带结果一致。
- **新增 `_test_upstream_repairs.py`**（49 项断言，无网络依赖）。

### v1.4.8

- **HTTP 连接同步修复**（PR #30）：请求被提前拒绝时未读取请求体，会让后续请求在同一 keep-alive 连接上解析失败（日志表现为空请求行的伪 414）；同时支持 chunked 请求体、`Expect: 100-continue`、超大请求体立即 413。
- **超长请求行回复丢失修复**：414 后直接关闭会因未读数据触发 RST，客户端收不到响应；现先有限度排空再回复。
- **macOS 启动脚本**（PR #31）：新增 `start-wb-proxy.sh` / `.command`、局域网版本与防火墙助手；Windows `.bat` 未修改。

### v1.4.7

- **每账号独立出口代理**（PR #26，感谢 [@ayeaaaa](https://github.com/ayeaaaa)）：新增可命名、可启停的代理槽位，账号绑定后其全部出站请求固定走该出口；看板支持槽位增删、出口 IP 测试与逐账号绑定。
- **账号身份请求全量走代理**：`refresh` / `checkin` / `fetch_credits` 此前从宿主机真实 IP 发出，会把账号身份与宿主 IP 关联在一起。
- **槽位 ID 不再回收**：ID 改由持久化计数器分配，删除槽位时同步解绑指向它的账号。
- **顶部 GitHub 仓库入口**。

### v1.4.6

- **看板数据口径与展示修正**：指标看板固定展示两区合计，不再跟随当前出口；模型性能表按「模型 × 出口 × 账号」逐行展开，新增「失败」列与三色分列。
- **看板会话与页面保持**：会话失效后立即停止轮询并清除旧凭证，不再刷 401 日志；刷新后保持所在页面。

### v1.4.5

- **GPT 系列流式 Token 与生成速度修复**：忽略中间帧全 0 的 usage 占位，并加入断流 Fallback 估算，修复 `gpt-5.6-luna` / `gpt-6-astra` 等模型输入输出为 0、生成速度缺失的问题。

---
