# Workbody-FHUB 部署与迁移说明

日期：2026-10-07。本分支保留 WorkBuddy 国内与国际出口，继续使用 Python 标准库和现有 Docker / 1Panel 部署。模型页的渠道选择只改变目录展示；实际对话由网关 Key 的出口绑定及已有账号池规则决定。

## 当前能力

- 模型渠道为 `workbuddy-cn` 与 `workbuddy-intl`，默认目录沿用原来的 Key/realm 规则。
- 网关 Key 支持跟随面板、固定国内出口和固定国际出口，并继续执行模型限制。
- WorkBuddy 账号导入保留产品身份、添加时间和代理槽绑定；使用现有账号和设置存储格式。
- 本地网络工具继续默认关闭；启用后 Responses 请求可由网关执行搜索和抓取。后端与限制见[网络搜索说明](research/web-search-support.md)。

## 旧出口配置的迁移

已移除旧的第三方反代、独立目录模块、上游配置入口和看板账号区。旧配置文件中的未知字段保留原有内容，应用不会再读取旧上游配置。历史用量和 Key 名称继续保留；绑定已移除出口的 Key 会被判为停用，面板显示“出口已移除”。编辑该 Key、明确选择一个现有出口后，才可重新启用。

停用所有现存 Key 会拒绝 API 请求。只有操作者明确使用原有关闭鉴权开关，才按该开关允许免 Key 调用。新安装且未配置任何 Key 的历史行为继续沿用启动方式；容器 `--lan` 会生成启动 Key。

## 部署本地源码

云镜像为 `ghcr.io/albert-li-sz/workbody-fhub:1.0.0`，使用 `docker compose -f docker-compose.cloud.yml up -d` 拉取并部署。

默认 `docker-compose.yml` 构建本分支源码，镜像名为 `workbody-fhub:1.0.0`，默认只向 `127.0.0.1` 发布端口。兼容的源码构建配置也可使用：

```sh
docker compose -f docker-compose.build.yml up -d --build
```

应用使用 `accounts` 与 `usage` 两个持久化卷。升级前备份它们，确认国内/国际 Key 仍绑定正确出口，并用实际模型完成一次响应验证。API 可连接、目录可读取和单元测试通过不能代替真实模型调用。

若需要单独配置网络工具代理，在部署的环境变量中加入 `WB_WEB_PROXY`。不要将凭据写入仓库或公开日志。构建上下文排除账号、日志和环境文件。首次启动生成随机面板密码，旧默认 admin 会自动替换，已有自定义密码保留；支持 PANEL_PASSWORD/PANEL_PASSWORD_FILE。镜像构建与验证见[修复报告](audit-2026-10-07.md)。

## 验证入口

```sh
python3 tests/run_all.py
python3 scripts/audit_web_tools.py
```

前者运行回归测试，后者以本机 HTTP 服务和合成模型响应复查安全边界、工具编排和计量，不访问真实账号或外部模型。上游来源见[upstreams.json](../upstreams.json)，修复状态与验证边界见[审计报告](audit-2026-10-07.md)。
