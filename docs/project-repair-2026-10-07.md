# Workbody-FHUB 1.0.1 全项目审计修复

日期：2026-10-07。修复前基线：`01ccabc1753eeb7a76005a264e66248959d75910`。对应[原审计报告](project-audit-2026-10-07.md)的 10 项可复现缺陷已经修复，并纳入回归测试。原报告及修复前 JSON 保留，源码位置链接固定到原基线，便于复核。

## 缺陷处理结果

| 编号 | 修复后的行为 | 验证结果 |
| --- | --- | --- |
| A01 · 配置损坏恢复旧 Key | 保留最后一次有效设置；冷启动没有可信快照时拒绝请求。面板建立 Key 列表后，删除最后一个 Key 也不会恢复启动 Key | 损坏前后旧 Key 均被拒绝，新 Key 均有效；另覆盖冷启动损坏、非法 Key 列表和最后一个 Key 删除 |
| A02 · 轮转降低每日预算 | 日计量覆盖主文件和归档，识别轮转、文件替换和重启；追加记录继续增量计数 | 1200 Token 轮转后仍为 1200；积分、模型限额、重启和后续追加都保持正确 |
| A03 · 历史静默截断 | 默认按行读取完整 JSONL，移除每文件 8 MiB 的隐式尾部窗口 | 9.07 MB 文件的 2200 条记录全部返回，第一条索引为 0 |
| A04 · URL 密码泄漏 | 移除 URL 密码自动登录，页面清理遗留 `pwd/password` 参数；访问日志对敏感查询参数脱敏 | 合成密码未进入访问日志；编码参数名和大小写边界有覆盖；启动函数未触发 URL 登录 |
| A05 · 健康检查触发刷新 | 匿名 `/health` 仅读取缓存账户状态，不同步刷新凭据 | 合成过期账户刷新次数为 0，健康响应为 200 |
| A06 · 排程保存停止工作线程 | 排程设置直接应用到运行配置；线程启停受生命周期锁保护，停止等待可中断 | 真实线程停止后重新启动，创建新线程并保持存活；设置响应为 `updated` |
| A07 · 启动巡检忽略停止 | 启动等待使用停止事件，执行前检查启用和停止状态 | 已暂停且停止的调度器未执行签到任务 |
| A08 · 非法请求断开连接 | 在 Chat、Responses、Messages 和 count_tokens 的协议转换前校验公共字段类型 | 9 个非法字段案例返回协议对应的 HTTP 400，无处理器异常；正常连接复用仍通过 |
| A09 · 密码校验异常 | 密码修改复用存储层的校验规则，将校验失败转换为 400 | 新密码 `admin` 返回明确的 400，不再断开连接 |
| A10 · 输入错误清除会话 | 当前密码错误使用 `current_password_invalid` 错误码，前端保留有效会话并显示校验信息 | 错误密码返回 400，后端会话仍有效；真实会话失效的对照案例仍清理会话 |

后端使用临时数据目录、回环 HTTP、合成账户及模拟上游；前端直接执行当前 HTML 的函数，使用 Node VM 模拟 HTTP/DOM。没有读取生产账户或调用真实上游。修复前测试能够检出缺陷，修复后相同探针的 `findings` 均为空。

- 修复后证据：[后端](project-repair-2026-10-07-backend.json)、[前端](project-repair-2026-10-07-frontend.json)。
- 修复前证据：[后端](project-audit-2026-10-07-backend.json)、[前端](project-audit-2026-10-07-frontend.json)。
- 固定回归：[Python 套件](../tests/_test_project_repairs.py)、[JavaScript 套件](../tests/_test_project_repairs.js)。
- 可独立运行：[后端探针](../scripts/audit_project.py)、[前端探针](../scripts/audit_project_ui.js)。

## 目录、配置与发布流程

- 公共请求校验提取到 `wb_validation.py`，三种协议共享 HTTP 边界校验。
- 根目录维护脚本移入 `tools/`；启动器重写工具增加 main 入口，导入不再自动改写文件。取价工具的入口引用同步修改，维护工具不进入运行镜像。
- 上游历史更新原文移入 [CHANGELOG.upstream.md](../CHANGELOG.upstream.md)，README 保留当前使用说明。原项目声明、致谢、贡献者、免责声明以及两份许可证均保留。
- `wb_version.VERSION` 统一 API 与服务版本。发布检查同时验证 tag、Dockerfile、Compose 和 README 的版本。
- 面板和 README 说明：启动参数、环境变量或密码文件持续指定密码时，下次启动会覆盖网页修改；配置损坏使用可信快照时也给出可见提示。
- 测试入口增加默认 180 秒的单套件超时；CI 增加任务超时。
- 镜像验证支持 `--revision`，从目标发布版本读取源码哈希及测试，不再拿当前工作树误判旧镜像。
- 云发布先推送固定版本，在两种架构的成品通过启动、鉴权、关键回归和普通 UID 检查后再更新 `latest`。Docker metadata-action 的自动 latest 行为显式关闭，避免提前移动稳定标签；依据为[官方 v5 flavor 输入说明](https://github.com/docker/metadata-action/tree/v5#flavor-input)。

部署仍使用单一云镜像 `docker-compose.yml`，保持用户指定的 `0.0.0.0:8788:8788` 和已有默认 UID/GID。镜像固定到 `ghcr.io/albert-li-sz/workbody-fhub:1.0.1`；使用普通 UID 时应先准备该 UID 可写的数据目录。

## 验证

完整测试：**84 个套件通过，0 失败，0 整套跳过**，包括 69 个 Python 和 15 个 JavaScript。部分套件内部的 Windows 或真实外网条件用例按平台跳过。宿主机为 Python 3.14.7、Node 24.18.0；[完整测试输出](project-repair-2026-10-07-tests.txt)保留实际结果。

本地成品为 `linux/amd64` 和 `linux/arm64`。两种架构均校验 31 个源码/声明文件哈希、Python 3.11.17、健康响应、匿名 API 拒绝、旧默认密码拒绝、随机密码登录、设置文件 `0600`，同时验证 UID 0 和 UID 1000。每种架构运行搜索、网络防护、工具流程、初始鉴权、移除出口、健康鉴权和本次修复等 7 个回归套件。容器使用隔离数据卷与 `--network none`，结束后清理测试容器和卷；[镜像验证结果](project-repair-2026-10-07-image.json)记录实际产物检查。

```bash
python3 tests/run_all.py
python3 scripts/audit_project.py
node scripts/audit_project_ui.js
python3 scripts/verify_image.py workbody-fhub:1.0.1 --non-root
```

[1.0.1 Release](https://github.com/Albert-Li-Sz/Workbody-FHUB/releases/tag/v1.0.1) 已发布。应用源码对应 `66ec2d6087de78bf106de44419cb466b3f2e32c1`；主分支后续提交补充发布验证工具和证据，不修改这个发布标签。

- [修复提交 CI](https://github.com/Albert-Li-Sz/Workbody-FHUB/actions/runs/37612591910)、[发布标签 CI](https://github.com/Albert-Li-Sz/Workbody-FHUB/actions/runs/37612920526)、[发布检查工具 CI](https://github.com/Albert-Li-Sz/Workbody-FHUB/actions/runs/37614769363) 均通过 Linux Python 3.9、3.12 和 Windows Python 3.12；标签版本一致性检查也通过。
- [云端镜像复核与 latest 更新](https://github.com/Albert-Li-Sz/Workbody-FHUB/actions/runs/37614798761) 通过两种架构、普通 UID、每种架构 7 个回归套件和 31 个源码/声明文件哈希检查。[云端结果](project-repair-2026-10-07-cloud-ci.json)和[本机拉取结果](project-repair-2026-10-07-cloud-image.json)分别保留。
- [匿名注册表检查](project-repair-2026-10-07-cloud-registry.json)确认无需登录即可读取镜像；`1.0.1`、`v1.0.1`、`latest` 都指向 `sha256:aae688609b751e92b4d6105f9318c6ee56a56eb8dfb0b51594c0535b2f89e290`，两种架构的版本及源码标签均正确。
- Release 提供双架构 Docker 导入包和 amd64/arm64 独立导入包；[归档大小及 SHA-256](project-repair-2026-10-07-artifacts.json)已核对上传资产。双架构包适用于 containerd 多平台镜像存储，传统 Docker 镜像存储应选对应架构的独立包。附件另含测试、成品与云端验证证据，完整校验和由 Release 工作流生成。

首次发布流程在普通 UID 启动检查上连续两次超时，本机同一镜像验证通过。原验证脚本只循环等待约 10 秒，日志也缺少架构和权限诊断。现将启动窗口改为有上限的 60 秒，并补充不含凭据的诊断；故意使用错误端口的控制实验确认超时有界、能报告 UID 和私有目录权限。新流程按既有发布标签核验已经上传的镜像，全部通过后才更新 `latest`；原失败流水线作为历史记录保留，没有绕过成品检查或重写发布标签。当前 ARM64 普通 UID 整段烟测在云端约需 20 秒。

默认部署更新：

```bash
git pull
docker compose pull
docker compose up -d
```

若 `.env` 中显式配置了 `WORKBODY_IMAGE`，更新前将它改为目标版本 `ghcr.io/albert-li-sz/workbody-fhub:1.0.1`。

## 保留的改进建议与验证边界

`wb_proxy.py` 和 `dashboard.html` 仍然较大。本次先提取公共校验和隔离维护工具，后续可按鉴权、用量、协议适配器、面板功能逐步拆分。历史查询已修复漏数据，但仍以完整扫描及内存缓存为主；大规模日志宜增加索引或查询分页。停用账户与暂停后台任务是两套已有策略，保持可配置语义。

真实上游模型、OAuth、生产网络中的 DuckDuckGo HTML/Lite、实际浏览器完整交互及生产部署未在本次修复中重新验收。回归探针和无网络容器测试证明上述触发条件已经修复，不替代这些实际环境检查。
