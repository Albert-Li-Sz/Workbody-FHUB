# 来源、致谢与使用说明

Workbody-FHUB 派生自 [ardeyouxipianyi/workbuddy2api-hub](https://github.com/ardeyouxipianyi/workbuddy2api-hub)，最初基于上游 1.6.13，选择合入截至 1.6.17 的适用更新（[同步记录](upstream-sync-2026-10-09.md)）。分支采用 [Apache-2.0](../LICENSE)，保留上游 [MIT 许可证原文](../LICENSE.upstream)、[版本记录](../CHANGELOG.upstream.md)及 [来源清单](../upstreams.json)。

原项目声明（保留原文）：

> ⚡ **Vibe Coding 产物**：本项目为 100% Vibe Coding 协同产物，由人类开发者提出架构与业务意图，AI 助手端到端完成逆向分析、链路调度、WAF 指纹脱敏与界面编写。

## 致谢与引用声明 (Credits & References)

协议兼容、风控规避与任务链路设计过程中，参考并吸纳了以下开源项目的经验与逆向成果：

- **[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)**：成长任务全链路逆向、设备指纹稳定派生（`derive_id`）、整点排程调度（`Scheduler`）、指纹脱敏与 `reasoning_content` 回填；
- **[CangShui/workbuddy-cliproxy-fix](https://github.com/CangShui/workbuddy-cliproxy-fix)**：早期客户端代理修复与接口差异参考；
- **[lovingfish/workbuddy-cliproxy](https://github.com/lovingfish/workbuddy-cliproxy)** 与 **[mmqz/cpa-multi-plugins](https://github.com/mmqz/cpa-multi-plugins)**：网关通信与多插件管理原型参考；
- **[ardeyouxipianyi/workbuddy2api](https://github.com/ardeyouxipianyi/workbuddy2api)**：国内版分发包逆向分析与出站 User-Agent 规范参考。

PR 贡献者（v1.4.5 之前的改动未进上方更新记录，这里一并列出）：

- **[@ddddd-ren](https://github.com/ddddd-ren)**：用量日志倒序检索与看板防堆叠（PR #14）、原子写入与并发竞争修复（PR #13）、账号池 JSON 导出导入（PR #5）；
- **[@wylftw0314-glitch](https://github.com/wylftw0314-glitch)**：Responses API custom 工具协议双向转译（PR #12）；
- **[@shuishuipingan](https://github.com/shuishuipingan)**：成长任务领取竞态与专家/团队事件 id 去重、猫猫旅行派出修复、夜猫子任务接入调度器、启动端口误判（PR #21）、按模型冷却限流（PR #22）、任务接取强化与轮询加速（PR #27）、网络抖动重试与 403 直通（PR #28）、HTTP 连接同步（PR #30）；
- **[@ayeaaaa](https://github.com/ayeaaaa)**：按账号绑定出口代理槽（PR #26）、DeepSeek `reasoning_content` 回填（PR #36）、看板移动端布局（PR #37）；
- **[@t-789](https://github.com/t-789)**：macOS 启动脚本与防火墙助手（PR #31）；
- **[@Cekxri](https://github.com/Cekxri)**：Codex App namespace 工具支持（PR #33）；
- **[@wiggins-kong](https://github.com/wiggins-kong)**：API Key 行 id 唯一化（PR #40）、Docker 镜像缺少运行时模块（PR #41）；
- **[@Pro-XK](https://github.com/Pro-XK)**：看板积分消耗与账号昵称（PR #45）；
- **[@teddyli18000](https://github.com/teddyli18000)**：单模型限流可视化（PR #50）、`/health` 鉴权状态修正（PR #52）；
- **[@LuFering](https://github.com/LuFering)**：Docker 部署下的 Linux 桌面凭据挂载说明（PR #55）；
- **[@zhangzm0](https://github.com/zhangzm0)**：`tool_choice="none"` 保留工具声明（PR #57）。

---

## 使用说明

1. 本项目为非官方自托管网关，仅供技术研究、逆向协议学习与个人合法授权账号在私有环境测试使用。
2. 本项目不提供任何账号及额度。请严格遵守官方服务条款，禁止用于任何商业转售、恶意并发或违规滥用。
